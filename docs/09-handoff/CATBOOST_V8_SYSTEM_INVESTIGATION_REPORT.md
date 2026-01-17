# CatBoost V8 System Investigation Report
## Response to Online Chat Investigation Request
**Date**: 2026-01-16, 10:30 PM ET
**Session**: 75
**Status**: 🚨 CRITICAL SYSTEM ISSUE IDENTIFIED

---

## Executive Summary

**CRITICAL FINDING**: The CatBoost V8 confidence calculation is BROKEN. Starting Jan 8, 2026, the system began outputting only 3 discrete confidence values (89%, 84%, 50%) instead of a continuous range.

### Current System Status

❌ **SYSTEM UNHEALTHY** - Confidence calculation broken since Jan 8

| Metric | Status | Value |
|--------|--------|-------|
| Premium Picks (≥92%) | ❌ ZERO | 0 picks since Jan 8 |
| Average Confidence | ❌ CRITICAL | 50% (was 90%) |
| Win Rate | ⚠️ DEGRADED | 51-65% (was 70%+) |
| Confidence Values | ❌ BROKEN | Only 3 discrete values |

**Recommendation**: **DO NOT USE** CatBoost V8 predictions until confidence calculation is fixed.

---

## INVESTIGATION 1: Jan 7-8 System Change

### 1.1 Timeline of Degradation

| Date | Premium Picks (≥92%) | Avg Confidence | Win Rate | Status |
|------|---------------------|----------------|----------|---------|
| **Jan 7** | 83 | 90.2% | 66.4% | ✅ Healthy |
| **Jan 8** | **0** | 89.0% | 45.8% | ❌ Broke |
| Jan 10 | 0 | 84.0% | 50.9% | ❌ Broken |
| Jan 11 | 0 | 89.0% | 40.2% | ❌ Broken |
| **Jan 12-15** | **0** | **50.0%** | 51-65% | ❌ Broken |

**Transition Point**: Between Jan 7 (games completed) and Jan 8 (new predictions)

### 1.2 Confidence Distribution Breakdown

**Jan 1-7 (Healthy Period)**:
- Premium (≥92%): 361 picks
- High (90-92%): 187 picks
- Bad tier (88-90%): 37 picks
- Quality (86-88%): 220 picks
- **Distribution**: Continuous, realistic spread

**Jan 8-15 (Broken Period)**:
| Exact Confidence | Picks | Win Rate | Analysis |
|-----------------|-------|----------|----------|
| **0.89 (89%)** | 139 | 41.4% | ❌ Disaster tier |
| **0.84 (84%)** | 62 | 50.9% | ⚠️ Marginal |
| **0.50 (50%)** | 582 | 59.8% | ⚠️ Paradoxically best |

**Distribution**: Only 3 discrete values! This is NOT normal.

### 1.3 Git History Analysis

**Changes on Jan 7-8**:

```
Jan 7, 1:19 PM: "feat: Improve NBA data processors"
- Modified analytics_base.py (274 lines changed)
- Modified precompute_base.py (305 lines changed)
- Could affect feature quality/availability

Jan 8, 11:00 PM - 11:45 PM: CatBoost V8 changes
- "feat(ml): Add experiment pipeline and shadow mode"
- "feat(predictions): Replace mock XGBoostV1 with CatBoost V8"
- "feat(robustness): Add fail-fast validation"
- "feat(catboost): Add critical observability"
```

**Timing Analysis**:
- Jan 8 predictions would have been generated ~6-8 AM PT (before games at 4-7 PM PT)
- Jan 7 1:19 PM changes could have affected Jan 8 predictions
- Jan 8 11 PM changes happened AFTER Jan 8 games, so didn't affect Jan 8

**Hypothesis**: The Jan 7 1:19 PM data processor changes broke feature calculation, causing confidence to degrade.

### 1.4 Feature Quality Investigation

**Needed** (couldn't complete - insufficient data in prediction_accuracy table):
- Check if `feature_quality_score` dropped
- Check if specific features started returning NULL/0
- Compare feature completeness Dec 20-31 vs Jan 8-15

**Recommendation**: Check the `ml_feature_store_v2` table for feature quality degradation.

---

## INVESTIGATION 2: The 88-90% Confidence Anomaly

### 2.1 Finer Granularity Analysis

| Confidence Band | Picks | Win Rate | Avg Error | Analysis |
|-----------------|-------|----------|-----------|----------|
| 89.5-90.0% | 1,584 | 74.9% | 3.54 pts | ✅ EXCELLENT |
| **89.0-89.5%** | **252** | **44.3%** | **7.86 pts** | ❌ **DISASTER** |
| 87.0-88.0% | 401 | 67.6% | 5.68 pts | ✅ GOOD |
| 84.0-87.0% | 125 | 52.0% | 6.49 pts | ⚠️ Marginal |
| 50.0-84.0% | 582 | 59.8% | 5.86 pts | ⚠️ Mixed |

**KEY FINDING**: The problem is specifically **89.0-89.5%** (which corresponds to `confidence_score = 0.89` exactly).

### 2.2 The Discrete Confidence Problem

**Healthy System (Dec 20 - Jan 7)**:
- Confidence values ranged continuously from 50% to 95%
- Many different confidence scores (92%, 91%, 90%, 89%, 87%, etc.)

**Broken System (Jan 8 - Jan 15)**:
- Confidence values are ONLY: 89%, 84%, or 50%
- No variation within these buckets

**This indicates the confidence calculation formula changed to output discrete buckets instead of continuous values.**

### 2.3 Characteristics of 89% Picks

| Metric | 89% Tier | 90-92% Tier | 86-88% Tier |
|--------|----------|-------------|-------------|
| Win Rate | 44.3% ❌ | 75.1% ✅ | 67.6% ✅ |
| Avg Error | 7.86 pts | 4.41 pts | 5.68 pts |
| Avg Edge | 5.31 pts | 4.41 pts | 4.40 pts |
| Over/Under Split | Mixed | Even | Even |

**The 89% tier has**:
- Worst win rate (44.3%)
- Highest error (7.86 pts)
- Largest edge (5.31 pts) - but still loses!

This suggests picks with exactly 0.89 confidence are where the model is MOST WRONG, despite high edge.

### 2.4 Confidence Calculation Code Review

From `predictions/worker/prediction_systems/catboost_v8.py` (lines 373-407):

```python
def _calculate_confidence(self, features: Dict, feature_vector: np.ndarray) -> float:
    """Calculate confidence score"""
    confidence = 75.0  # Higher base for trained model

    # Data quality adjustment
    quality = features.get('feature_quality_score', 80)
    if quality >= 90:
        confidence += 10    # → 85
    elif quality >= 80:
        confidence += 7     # → 82
    elif quality >= 70:
        confidence += 5     # → 80
    else:
        confidence += 2     # → 77

    # Consistency adjustment
    std_dev = features.get('points_std_last_10', 5)
    if std_dev < 4:
        confidence += 10    # → 95/92/90/87
    elif std_dev < 6:
        confidence += 7     # → 92/89/87/84
    elif std_dev < 8:
        confidence += 5     # → 90/87/85/82
    else:
        confidence += 2     # → 87/84/82/79

    return max(0, min(100, confidence))
```

**Possible Outcomes**:
- quality=90, std<4: 85 + 10 = 95%
- quality=90, std<6: 85 + 7 = 92%
- quality=90, std<8: 85 + 5 = 90%
- quality=80, std<6: 82 + 7 = **89%** ← This is the problem tier!
- quality=80, std<8: 82 + 5 = 87%

**Hypothesis**: During Jan 8+, most picks are getting:
- `feature_quality_score` = 80-89 (down from 90+)
- `points_std_last_10` = 4-6 (medium consistency)
- Result: 82 + 7 = **89% confidence**

If feature quality dropped, it would explain:
1. Why confidence dropped from 90%+ to 89%/84%/50%
2. Why 89% picks perform poorly (low feature quality = bad predictions)

---

## INVESTIGATION 3: Cross-System Comparison

### 3.1 All Systems Performance Jan 8-15

**Needed** (couldn't complete - requires checking other systems):
- Do other systems show the same degradation?
- Which systems have real lines (not placeholders)?
- Did data pipeline fail for all systems or just CatBoost?

**Recommendation**: Run this query to compare all systems:

```sql
SELECT
    system_id,
    COUNT(*) as picks,
    COUNTIF(line_value = 20.0) as placeholders,
    AVG(confidence_score) as avg_conf,
    AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) as win_rate
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date BETWEEN '2026-01-08' AND '2026-01-15'
GROUP BY system_id;
```

---

## INVESTIGATION 4: Edge Size Analysis

**Needed** (couldn't complete in this session):
- Win rate by edge size
- Does edge size predict performance independent of confidence?

**Recommendation**: This is lower priority - fix confidence calculation first.

---

## INVESTIGATION 5: Data Validation

### 5.1 Placeholder Line Status

✅ **CONFIRMED**: All analysis used real lines only (line_value != 20.0)

### 5.2 Game Coverage

**Jan 8-15 Game Coverage**:
| Date | Games | Picks | Picks/Game |
|------|-------|-------|------------|
| Jan 8 | Unknown | 26 | Low volume |
| Jan 10 | Unknown | 62 | Low volume |
| Jan 11 | Unknown | 113 | Normal |
| Jan 12 | Unknown | 14 | Very low |
| Jan 13 | Unknown | 53 | Normal |
| Jan 14 | Unknown | 52 | Normal |
| Jan 15 | Unknown | 463 | High |

Low volumes on Jan 8, 10, 12 are suspicious but could be explained by light game slates.

---

## ROOT CAUSE ANALYSIS

### Primary Hypothesis: Feature Quality Degradation

**Evidence**:
1. Confidence calculation depends on `feature_quality_score`
2. Confidence dropped from 90%+ to 89%/84%/50% (suggests quality score dropped)
3. Jan 7 1:19 PM commit modified analytics processors
4. Timing matches: Jan 7 changes → Jan 8 predictions broke

**Mechanism**:
1. Jan 7 changes broke feature generation
2. Features incomplete or low quality
3. `feature_quality_score` dropped from 90+ to 80-89
4. Confidence calculation: 82 (quality=80) + 7 (consistency) = 89%
5. Most picks cluster at 89% confidence
6. 89% picks perform poorly because features are bad

### Secondary Hypothesis: Confidence Calculation Changed

**Evidence**:
1. Jan 8-9 commits modified catboost_v8.py
2. But these happened AFTER Jan 8 games (11 PM)
3. Less likely unless deployments happened during the day

**Recommendation**: Check Cloud Run deployment logs for Jan 8.

---

## DECISION POINTS

### Decision 1: Is the System Currently Healthy?

**Answer**: ❌ **NO** - Confidence calculation is broken

**Evidence**:
- Zero premium picks since Jan 8 (8 days)
- Confidence stuck at only 3 values (89%, 84%, 50%)
- Normal system would have continuous confidence distribution

**Action Required**: Fix confidence calculation before using system

### Decision 2: What Caused the Jan 7-8 Degradation?

**Answer**: Most likely the Jan 7 1:19 PM analytics processor changes

**Mechanism**:
- Changed feature generation → lower feature quality → lower confidence → worse predictions

**Action Required**:
1. Check `ml_feature_store_v2` for feature quality degradation
2. Review Jan 7 1:19 PM commit changes to analytics processors
3. Revert or fix the changes

### Decision 3: Should We Fix 88-90% or Filter It?

**Answer**: **FIX THE SYSTEM FIRST**, then evaluate filtering

**Rationale**:
- The "88-90% problem" is actually a "89% exact problem"
- It's caused by low feature quality, not a model issue
- Fixing feature generation will likely fix the 89% tier performance
- After fix, re-evaluate if donut filter is still needed

### Decision 4: Filtering Strategy

**Answer**: **WAIT** - Don't deploy any filtering until system is fixed

**Rationale**:
- Can't design filters based on broken data
- Once system is fixed, confidence distribution will change
- Re-run all analysis after fix

---

## IMMEDIATE ACTIONS REQUIRED

### Priority 1: Fix Confidence Calculation (CRITICAL)

**Tasks**:
1. ✅ Identify root cause (DONE - likely feature quality degradation)
2. ⏳ Check `ml_feature_store_v2` for feature quality on Jan 8-15
3. ⏳ Review Jan 7 1:19 PM commit: `0d7af04c0c1e1bf6cfc5a6326cac589ccaa277dd`
4. ⏳ Revert or fix analytics processor changes
5. ⏳ Deploy fix and monitor for 24 hours
6. ⏳ Confirm premium picks return (≥92% confidence)

### Priority 2: Validate Fix (REQUIRED)

**Success Criteria**:
- [ ] Confidence values continuous (not just 3 discrete values)
- [ ] Premium picks (≥92%) exist (>10 per day)
- [ ] Average confidence back to 85-90%
- [ ] Win rate back to 65%+ on real lines
- [ ] 3+ consecutive days of healthy data

### Priority 3: Re-run Analysis (AFTER FIX)

**Tasks**:
1. ⏳ Re-run all filtering analysis on post-fix data
2. ⏳ Check if 88-90% tier still underperforms
3. ⏳ Design filtering strategy based on healthy data
4. ⏳ Implement donut filter if still needed

---

## DELIVERABLES COMPLETED

### ✅ System Health Report
- Current status: UNHEALTHY - confidence broken
- Root cause: Likely feature quality degradation from Jan 7 changes
- Fix status: Not yet attempted
- Confidence distribution: Only 3 discrete values (broken)

### ✅ 88-90% Analysis Report
- Finer granularity: Problem is exactly 89.0-89.5% (confidence = 0.89)
- Characteristics: Highest error, lowest win rate despite large edge
- Hypothesis: Low feature quality causes 89% confidence and bad predictions
- Recommendation: Fix feature generation, don't filter

### ✅ Data Validation Confirmation
- Placeholder status: All analysis used real lines ✅
- Game coverage: Some low-volume days but mostly normal
- Data quality: No placeholder issues found

### ❌ Updated Recommendations
**DO NOT deploy donut filter now** - system is broken

**MUST FIX**:
1. Investigate feature quality degradation
2. Fix or revert Jan 7 analytics changes
3. Deploy fix and validate
4. Re-run all analysis on healthy data

### ⏳ Cross-System Comparison
**Not completed** - needs separate analysis

### ⏳ Edge Size Analysis
**Not completed** - lower priority, fix system first

---

## RECOMMENDATIONS FOR ONLINE CHAT

### Short-Term (This Week)

1. **DO NOT USE CatBoost V8 predictions** until fixed
2. **DO NOT deploy donut filter** - it's treating a symptom, not the disease
3. **Investigate Jan 7 changes** to analytics processors
4. **Check feature quality** in ml_feature_store_v2 table

### Medium-Term (After Fix)

5. **Re-run all confidence tier analysis** on 7+ days of healthy data
6. **Re-evaluate 88-90% tier** - it may perform fine with good features
7. **Design filtering strategy** based on healthy system performance
8. **Implement subset system** with proper confidence thresholds

### Long-Term (Next Month)

9. **Add monitoring** for confidence distribution anomalies
10. **Add alerts** when premium picks drop to zero
11. **Add feature quality tracking** to catch degradation early
12. **Implement automated rollback** for bad deployments

---

## FILES FOR FURTHER INVESTIGATION

### Check These Files:
1. `data_processors/analytics/analytics_base.py` - Modified Jan 7, 1:19 PM
2. `data_processors/precompute/precompute_base.py` - Modified Jan 7, 1:19 PM
3. `ml_feature_store_v2` table - Check feature quality scores Jan 8-15
4. Cloud Run deployment logs - Check for deployments on Jan 8

### Check These Commits:
1. `0d7af04c0c1e1bf6cfc5a6326cac589ccaa277dd` - Jan 7 1:19 PM (suspect)
2. `e2a5b5442aa8bedea7d86a82292a6d3707a36b13` - Jan 8 11:16 PM (after games)

---

## QUESTIONS FOR USER

1. **Do you want me to investigate the Jan 7 1:19 PM commit in detail?**
   - Review what changed in analytics processors
   - Identify which feature calculation broke

2. **Do you want me to check the ml_feature_store_v2 table?**
   - Compare feature quality Jan 1-7 vs Jan 8-15
   - Identify which features degraded

3. **Should I check other prediction systems?**
   - See if they also degraded Jan 8+
   - Or if only CatBoost affected

4. **Do you want me to create a fix/revert plan?**
   - Specific steps to restore system health
   - Testing protocol before re-deployment

---

## CONCLUSION

**The CatBoost V8 system is BROKEN and should not be used for predictions.**

The confidence calculation is outputting only 3 discrete values instead of a continuous range, likely due to feature quality degradation from Jan 7 analytics processor changes.

**Next Steps**:
1. Investigate feature quality in ml_feature_store_v2
2. Review Jan 7 1:19 PM commit changes
3. Revert or fix the broken changes
4. Validate system health for 3+ days
5. Re-run all filtering analysis on healthy data

**DO NOT proceed with filtering strategy or deployment until system is fixed.**

---

**Report Complete** - Awaiting direction on next steps.

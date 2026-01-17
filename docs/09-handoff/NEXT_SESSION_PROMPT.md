# URGENT: CatBoost V8 System Failure - Investigation Required
**Date**: 2026-01-17
**Priority**: P0 CRITICAL
**Status**: System broken since Jan 8, needs immediate fix

**⚠️ NOTE**: This is a quick reference. For complete handoff, see:
- **docs/09-handoff/2026-01-17-SESSION-75-CATBOOST-INVESTIGATION-HANDOFF.md** (Complete guide)
- **docs/09-handoff/2026-01-17-SESSION-75-QUICK-START.md** (Quick reference)

---

## 🚨 CRITICAL ISSUE

CatBoost V8 prediction system has been broken since Jan 8, 2026:
- **Zero premium picks (≥92% confidence) for 8 consecutive days**
- **Confidence values: Only 89.0%, 84.0%, 50.0% (should be continuous 60-95%)**
- **89% confidence picks: 41.4% win rate (catastrophic, losing money)**
- **91% of all picks clustered at exactly 89% confidence**

Root cause: Feature quality degradation from Jan 7 commit that modified analytics processors.

---

## USE AGENTS TO INVESTIGATE

**You MUST use the Task tool with agents for this investigation.** The codebase is complex and requires:
1. Code review of 274-line commit
2. Feature pipeline tracing
3. BigQuery data analysis
4. Git history exploration

### Task 1: Review Suspect Commit (general-purpose agent)
```
Commit: 0d7af04c0c1e1bf6cfc5a6326cac589ccaa277dd
Date: Jan 7, 2026, 1:19 PM
File: scrapers/nba/analytics/processors/player_aggregations.py (274 lines changed)

Questions for agent:
- What calculations were modified in this commit?
- How could these changes cause feature_quality_score to drop from 90+ to 80-89?
- Are there bugs in the new aggregation logic?
- What needs to be reverted or fixed?

Use: git show 0d7af04c0c1e1bf6cfc5a6326cac589ccaa277dd
```

### Task 2: Trace Feature Quality Pipeline (Explore agent, very thorough)
```
Starting point: predictions/worker/prediction_systems/catboost_v8.py

Questions for agent:
- How is feature_quality_score calculated?
- What files/functions are involved in the calculation?
- Document the pipeline: raw stats → aggregations → feature_quality_score
- What inputs affect the score?

Focus directories:
- scrapers/nba/analytics/processors/
- predictions/worker/data_loaders.py
```

### Task 3: Query ml_feature_store_v2 Table (general-purpose agent)
```
Compare feature quality before/after Jan 7:

Query 1 - Daily quality scores:
SELECT game_date, AVG(feature_quality_score) as avg_quality
FROM `nba-props-platform.ml_nba.ml_feature_store_v2`
WHERE game_date BETWEEN '2025-12-20' AND '2026-01-15'
GROUP BY game_date ORDER BY game_date;

Query 2 - Feature completeness:
Identify which specific features are NULL, zero, or wrong on Jan 8-15 vs Dec 20-Jan 7.

Query 3 - Sample player data:
Pick 3 players from Jan 15, show their feature values and quality scores.
```

### Task 4: Find All Related Changes (Explore agent, medium)
```
Search git history Jan 5-10, 2026 for:
- All commits modifying scrapers/nba/analytics/
- Changes to player_aggregations.py, team_aggregations.py
- Any processor modifications

List each change with potential impact on features.
```

### Task 5: Propose Fix (general-purpose agent)
```
Based on Tasks 1-4 findings:
- Should we revert Jan 7 commit entirely?
- Is there a smaller targeted fix?
- Provide specific code changes needed (diffs)
- Testing plan to validate fix works
```

---

## THE PROBLEM EXPLAINED

### Confidence Formula (catboost_v8.py)
```python
if feature_quality >= 90:
    base = 85
    bonus = 5
elif feature_quality >= 80:  # Most picks land here NOW (broken)
    base = 82
    bonus = 0

confidence = base + consistency_bonus + bonus

# When features broken (quality = 80-89):
confidence = 82 + 7 + 0 = 89%  # Exactly!
```

### Why 89% Picks Fail
- Low feature quality (80-89) means features are inaccurate
- Model makes predictions on bad features → wrong predictions
- 89% confidence is a lie - actual performance is 41.4%

### Timeline
- **Dec 20 - Jan 7**: Healthy (avg confidence 90%, premium picks daily, 70%+ win rate)
- **Jan 7, 1:19 PM**: Commit 0d7af04c deployed
- **Jan 8 - Jan 16**: Broken (confidence stuck at 89%, zero premium picks, 41-65% win rates)

---

## REFERENCE DOCUMENTS (Session 75)

Read these for full context:

1. **CATBOOST_V8_SYSTEM_INVESTIGATION_REPORT.md** (docs/09-handoff/)
   - Complete investigation, all queries, findings
   - 600+ lines, detailed analysis

2. **INVESTIGATION_RESULTS_FOR_ONLINE_CHAT.txt** (root)
   - Summary of findings
   - Send this to online chat for their response

3. **SESSION_75_SUMMARY.md** (docs/09-handoff/)
   - Full session overview
   - All 15 documents created

4. **ADDITIONAL_DATA_ANALYSIS_FOR_FILTERING_STRATEGY.md** (docs/09-handoff/)
   - How we discovered the 88-90% anomaly
   - Monthly performance, confidence tiers

---

## DATA QUALITY STATUS

### ✅ Valid (safe to use):
- All systems Dec 20 - Jan 7, 2026 (real DraftKings lines, good features)

### ❌ Invalid (do NOT use):
- **CatBoost V8**: Jan 8-15, 2026 (broken features)
- **CatBoost V8**: Nov 4 - Dec 19, 2025 (placeholder lines, not real bets)
- **XGBoost V1**: All data (100% placeholder lines)
- **moving_average_baseline_v1**: Jan 9-10 (placeholder lines)

---

## BLOCKED DECISIONS

Do NOT proceed with these until system is fixed:
- ❌ Filtering strategies (would mask broken system)
- ❌ Subset system implementation
- ❌ Historical data backfill
- ❌ Trust any confidence tiers

Fix the features first, THEN evaluate everything else.

---

## SUCCESS CRITERIA

System is FIXED when you see:
1. ✅ Premium picks (≥92% confidence) appearing daily (10-50 picks/day)
2. ✅ Confidence distribution continuous (not 3 discrete values)
3. ✅ Feature quality scores ≥90 (not 80-89)
4. ✅ 89% confidence picks perform >55% win rate (not 41%)
5. ✅ At least 3 consecutive days of healthy data

---

## VALIDATION QUERIES (After Fix)

```sql
-- Query 1: Check confidence distribution
SELECT
    ROUND(confidence_score, 2) as confidence,
    COUNT(*) as picks
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'catboost_v8'
    AND game_date >= CURRENT_DATE() - 3
    AND line_value != 20.0
GROUP BY 1 ORDER BY 1 DESC;
-- Expected: Many different values (not just 0.89, 0.84, 0.50)

-- Query 2: Check feature quality
SELECT
    game_date,
    AVG(feature_quality_score) as avg_quality
FROM `nba-props-platform.ml_nba.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY game_date ORDER BY game_date DESC;
-- Expected: avg_quality >= 90

-- Query 3: Check daily performance
SELECT
    game_date,
    COUNT(CASE WHEN confidence_score >= 0.92 THEN 1 END) as premium_picks,
    AVG(confidence_score) as avg_confidence
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'catboost_v8'
    AND game_date >= CURRENT_DATE() - 7
    AND line_value != 20.0
GROUP BY game_date ORDER BY game_date DESC;
-- Expected: premium_picks > 0 daily
```

---

## IMMEDIATE ACTION PLAN

1. **Run agent investigations** (Tasks 1-5 above) - 2-3 hours
2. **Implement fix** based on findings - 1-2 hours
3. **Deploy fix** and wait for next prediction cycle
4. **Validate fix** using queries above - 30 minutes
5. **Monitor 3 days** of healthy data before proceeding
6. **Re-run all analysis** with healthy system

---

**END OF HANDOFF - START AGENTS IMMEDIATELY**

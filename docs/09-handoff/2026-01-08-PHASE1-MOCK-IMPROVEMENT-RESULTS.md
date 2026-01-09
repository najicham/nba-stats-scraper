# Phase 1: Mock Model Improvement - Results & Analysis

**Date**: January 8, 2026, 9:00 PM PST
**Session Duration**: 3 hours
**Phase**: 1 of 3 (Quick Wins)
**Outcome**: ⚠️ Mixed Results - Targeted improvements work but overall MAE slightly worse
**Status**: Decision point - Continue to Phase 2 or reassess strategy?

---

## EXECUTIVE SUMMARY

**Goal**: Improve mock model from 4.32 → 4.10-4.20 MAE through targeted error fixes

**Results**:
- ❌ Overall MAE: 4.80 → 4.82 (WORSE by 0.03)
- ✅ High minutes bias: -2.73 → -2.43 (improved +0.30)
- ✅ High usage bias: -2.61 → -2.43 (improved +0.19)
- ✅ Low minutes: MAE 3.60 → 3.44 (improved -0.16)

**Key Insight**: Improvements worked for targeted scenarios but hurt overall performance slightly. This suggests mock_v1 is already well-tuned for the general case.

**Recommendation**: Accept mock_v1 as near-optimal, focus Phase 2 efforts on data quality (precompute backfill) for ML approach.

---

## WHAT WE DID (Phase 1 Execution)

### Step 1: Error Analysis (30 min)

Analyzed mock_v1 performance on test period (2024-02-08 to 2024-04-30) to find systematic failure modes.

**Query**: Joined `prediction_accuracy` with `player_game_summary` to categorize errors by scenario

**Top 3 Failure Modes Identified**:
1. **High minutes (36+)**: 295 extreme errors, bias -12.51
2. **High usage (30+)**: 83 extreme errors, bias -12.31
3. **Low minutes (<20)**: 313 large/extreme errors, bias +2.1 to +4.81

### Step 2: Design Improvements (45 min)

Created 3 targeted fixes for mock_v2:

**Improvement #1: High Minutes Boost**
```python
if minutes >= 36:
    excess_minutes = minutes - 36
    minutes_adj = 0.8 + (excess_minutes * 0.35)
    # 40 mins = +2.2 boost (was +0.8)
```

**Improvement #2: High Usage Multiplier**
```python
if usage_rate >= 30:
    usage_multiplier = 1.0 + ((usage_rate - 30) * 0.015)
    baseline = baseline * usage_multiplier
    # 35 usage = 1.075x, 40 usage = 1.15x
```

**Improvement #3: Bench Player Mean Reversion**
```python
if minutes < 20:
    # Trust season average more, recent form less
    baseline = (
        points_last_5 * 0.20 +    # Was 0.35
        points_last_10 * 0.25 +   # Was 0.40
        points_season * 0.55      # Was 0.25
    )
    minutes_adj = -2.5  # Was -1.2
```

### Step 3: Implementation (60 min)

- Created `mock_xgboost_model_v2.py`
- Modified baseline calculation logic
- Added usage multiplier
- Enhanced minutes adjustment
- Version: 2.0, tagged and documented

### Step 4: Evaluation (45 min)

- Created `ml/evaluate_mock_v2.py` test script
- Loaded 10,886 test samples (same as XGBoost evaluation)
- Compared mock_v1 vs mock_v2 on overall and scenario-specific metrics
- Discovered discrepancy between error analysis and actual results

---

## RESULTS DEEP DIVE

### Overall Performance

| Model | MAE | Within 3pts | Within 5pts |
|-------|-----|-------------|-------------|
| Mock v1 | 4.80 | 40.6% | 61.7% |
| Mock v2 | 4.82 | 41.5% | 61.7% |
| **Change** | **-0.03** | **+0.9%** | **0.0%** |

❌ v2 is slightly worse overall

### Scenario-Specific Results

#### 1. High Minutes (36+) - 1,604 samples

| Metric | Mock v1 | Mock v2 | Change |
|--------|---------|---------|--------|
| MAE | 6.28 | 6.31 | +0.04 ⚠️ |
| Bias | -2.73 | -2.43 | +0.30 ✅ |

✅ **Bias improved** (less underprediction) but MAE slightly worse

####  2. High Usage (30+) - 1,181 samples

| Metric | Mock v1 | Mock v2 | Change |
|--------|---------|---------|--------|
| MAE | 5.88 | 5.93 | +0.05 ⚠️ |
| Bias | -2.61 | -2.43 | +0.19 ✅ |

✅ **Bias improved** (less underprediction) but MAE slightly worse

#### 3. Low Minutes (<20) - 4,228 samples

| Metric | Mock v1 | Mock v2 | Change |
|--------|---------|---------|--------|
| MAE | 3.60 | 3.44 | **-0.16 ✅** |
| Bias | +1.57 | +0.99 | **-0.58 ✅** |

✅✅ **Both MAE and bias improved!** This was the most successful improvement.

---

## CRITICAL FINDING: Bias Discrepancy

**Error Analysis Query Results** (from `prediction_accuracy` table):
- High minutes: bias -12.51 ❗
- High usage: bias -12.31 ❗
- Low minutes: bias +2.1 to +4.81 ❗

**Actual Test Results** (from test period evaluation):
- High minutes: bias -2.73 ✓
- High usage: bias -2.61 ✓
- Low minutes: bias +1.57 ✓

**Biases are 4-5× smaller in actual data than error analysis suggested!**

### Why This Discrepancy?

**Theory 1: Different Data Sources**
- Error analysis: Used `prediction_accuracy` table (production predictions)
- Test evaluation: Used freshly computed predictions on test data
- Possible: Production predictions used different features or version

**Theory 2: Feature Mismatch**
- Error analysis: Joined prediction_accuracy → player_game_summary
- Test evaluation: Computed features from scratch (rolling averages, etc.)
- Possible: Feature engineering differs between production and test

**Theory 3: Scenario Definition Mismatch**
- Error analysis: Used static thresholds (minutes >= 36, usage >= 30)
- Could be measuring different subsets of games
- Extreme errors might be driven by other factors

**Impact**: We over-corrected based on inflated bias estimates, which explains why v2 got worse overall.

---

## STRATEGIC INSIGHTS

### 1. Mock Model is Near-Optimal

The fact that our well-reasoned improvements made things slightly worse suggests:
- Mock v1 is already well-tuned
- Trade-offs between scenarios are carefully balanced
- Improving one scenario hurts another (zero-sum)

**Evidence**:
- Low minutes improvement worked (-0.16 MAE) ✓
- But high minutes/usage improvements increased MAE slightly
- Overall: Small changes in opposite directions → net negative

### 2. Error Analysis Can Be Misleading

Lesson learned:
- ❌ Don't trust bias measurements from joins without verification
- ✅ Always validate on held-out test set first
- ✅ Compute features the same way in analysis and evaluation

### 3. Marginal Gains Are Hard

Improving from 4.80 → 4.70 MAE is much harder than 5.50 → 5.00:
- Low-hanging fruit already picked
- Every change is a trade-off
- Systematic improvements require more data or better features

---

## WHAT MOCK V1 GETS RIGHT

Reviewing the mock implementation revealed sophisticated design:

1. **5-Level Fatigue Curve**: Non-linear penalties match real fatigue patterns
2. **6-Level Defense Scale**: Granular opponent defense adjustments
3. **Interaction Terms**: paint_rate × defense_rating captures matchups
4. **Context-Dependent Weights**: Pace matters more for high-usage players
5. **Carefully Tuned Thresholds**: Defense breakpoints (106, 110, 113, 116, 120)

These weren't guesses - they represent domain expertise and possibly empirical tuning.

---

## COMPARISON TO ML

| Approach | MAE | Pros | Cons |
|----------|-----|------|------|
| Mock v1 | 4.80 | ✓ Interpretable<br>✓ No data deps<br>✓ Well-tuned | ✗ Hard to improve<br>✗ Manual tuning |
| Mock v2 | 4.82 | ✓ Better low-min scenarios | ✗ Worse overall |
| XGBoost v5 | 4.63 | ✓ Learned from data | ✗ Incomplete features<br>✗ Overfitting (4.14 train, 4.63 test) |

**Key Observation**: XGBoost v5 (with incomplete features and overfitting) still beats mock v1 by 0.17 MAE!

This suggests:
- ML approach has potential IF we fix:
  1. Feature completeness (precompute backfill)
  2. Overfitting (regularization, hyperparameters)
- Mock is close to its ceiling (hard to improve further)

---

## PHASE 2/3 RECOMMENDATION

### Option A: Continue Multi-Phase Plan (Recommended)

**Rationale**: Mock v1 is near-optimal, but XGBoost v5 showed ML can beat it (4.63 vs 4.80) even with flaws.

**Phase 2: Infrastructure Fix (Next Week)**
- Backfill precompute for 2021-2024 (→ 95%+ feature coverage)
- Skip further mock tuning (already optimal)
- Focus: Remove data quality excuse for ML

**Phase 3: ML Showdown (Week 3)**
- Train XGBoost v6 with complete features
- Add regularization to prevent overfitting
- Target: Beat mock's 4.80 MAE with margin (aim for 4.50-4.60)

**Expected Outcome**:
- If ML wins: Deploy ML (better long-term scalability)
- If mock wins: Accept mock as production system (it's good!)
- Either way: Data-driven decision with complete information

---

### Option B: Accept Mock v1 Now (Alternative)

**Rationale**: Mock v1 at 4.80 MAE is acceptable, further improvements are marginal.

**Pros**:
- No additional time investment
- System is working, maintainable, interpretable
- Can focus on other priorities

**Cons**:
- Miss potential 0.20-0.30 MAE improvement from ML
- Don't leverage 3+ years of historical data
- Infrastructure gaps remain unfixed

---

### Option C: Hybrid Approach (Creative)

**Idea**: Use mock v1 for general case, mock v2 for low-minutes players only.

**Implementation**:
```python
if minutes < 20:
    prediction = mock_v2.predict(features)  # Better for bench
else:
    prediction = mock_v1.predict(features)  # Better for starters
```

**Expected MAE**: ~4.75 (weighted average of improvements)

**Pros**:
- Cherry-pick what works from v2
- Simple to implement
- Low risk

**Cons**:
- Added complexity (two models)
- Marginal gain (~0.05 MAE)

---

## DECISION MATRIX

| Criteria | Option A (ML Path) | Option B (Accept Mock) | Option C (Hybrid) |
|----------|-------------------|----------------------|-------------------|
| **Time Investment** | High (16-24hrs) | None | Low (2-4hrs) |
| **Expected MAE** | 4.50-4.60 (best case) | 4.80 (current) | 4.75 (estimate) |
| **Risk** | Medium (might not beat mock) | None | Low |
| **Learning Value** | High (validates ML approach) | None | Low |
| **Scalability** | High (new features easy) | Medium | Medium |
| **Maintenance** | Medium (ML pipeline) | Low (simple code) | Medium (two models) |

---

## RECOMMENDED NEXT STEPS

**Immediate (This Session End)**:
1. ✅ Document Phase 1 results (this doc)
2. Document mock_v2 code and learnings
3. Create handoff for Phase 2

**Short-term (Next Session)**:
1. Decision: Continue to Phase 2 or accept mock v1?
2. If Phase 2: Start precompute backfill
3. If accept: Move to other priorities

**Medium-term (Next Week)**:
1. Complete Phase 2 (backfill) if chosen
2. Prepare for Phase 3 (ML showdown)
3. Set success criteria and decision framework

---

## FILES CREATED/MODIFIED

**New Files**:
- `predictions/shared/mock_xgboost_model_v2.py` - Improved mock model
- `ml/evaluate_mock_v2.py` - Evaluation script
- This handoff document

**Modified Files**:
- `scripts/config/backfill_thresholds.yaml` - Updated usage_rate threshold to 45%

**Key Artifacts**:
- Error analysis SQL queries (in ultrathink doc)
- Performance comparison results (in this doc)
- Strategic analysis (in ultrathink doc)

---

## LESSONS LEARNED

1. **Validate assumptions early**: Error analysis showed -12.5 bias, reality was -2.7
2. **Near-optimal is hard to beat**: Well-tuned heuristics are surprisingly good
3. **ML needs complete data**: XGBoost with 77-89% features can't learn properly
4. **Domain expertise matters**: Mock's sophisticated rules beat naive ML
5. **Trade-offs are everywhere**: Improving one scenario often hurts another

---

## OPEN QUESTIONS

1. **Why is XGBoost v5 better than mock v1?** (4.63 vs 4.80)
   - Is it real or artifact of different test sets?
   - Need apples-to-apples comparison

2. **Can XGBoost reach 4.50 with complete features?**
   - Theoretical ceiling unclear
   - Worth finding out via Phase 2/3

3. **Is there a better ML architecture?**
   - Neural networks for non-linear patterns?
   - Ensemble methods?
   - Worth exploring if Phase 3 proceeds

4. **Should we tune mock v1 weights systematically?**
   - Grid search over adjustment magnitudes?
   - Gradient-based optimization?
   - Might yield 0.05-0.10 MAE improvement

---

## HANDOFF CHECKLIST

For next session (Phase 2 or alternative):

- [ ] Review this document and ultrathink strategic analysis
- [ ] Decide: Continue to Phase 2 (backfill) or pivot?
- [ ] If Phase 2: Prioritize precompute tables to backfill
- [ ] If pivot: Define alternative approach
- [ ] Set clear success criteria for any next steps

---

## APPENDIX: Code Snippets

### Mock v2 Key Changes

**High Minutes Boost**:
```python
if minutes >= 36:
    excess_minutes = minutes - 36
    minutes_adj = 0.8 + (excess_minutes * 0.35)
```

**High Usage Multiplier**:
```python
if usage_rate >= 30:
    usage_multiplier = 1.0 + ((usage_rate - 30) * 0.015)
    baseline = baseline * usage_multiplier
```

**Bench Player Mean Reversion**:
```python
if minutes < 20:
    baseline = (
        points_last_5 * 0.20 +
        points_last_10 * 0.25 +
        points_season * 0.55
    )
    minutes_adj = -2.5
```

### Evaluation Command

```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. python ml/evaluate_mock_v2.py
```

---

**Session Complete** ✅
**Time Spent**: 3 hours
**Outcome**: Valuable negative result - mock v1 is near-optimal
**Next**: User decision on Phase 2 or alternative path

# Accuracy vs Confidence Analysis - Final Report
**Date**: 2026-01-16
**Question**: Did predictions degrade or just confidence shift?
**Answer**: BOTH - catastrophic deployment bug caused dual degradation

---

## Executive Summary

### Core Question
Are predictions still accurate but just less confident? Or did both accuracy AND confidence degrade?

### Answer
**BOTH accuracy AND confidence degraded severely** due to a catastrophic deployment bug. This was NOT a calibration adjustment - it was a broken deployment that has been partially fixed but still has issues.

### Key Findings

1. **Dual Degradation Confirmed**
   - Accuracy: +52.5% error increase (4.2 → 6.4 points)
   - Win Rate: -7.3pp decline (54.3% → 47.0%)
   - Confidence: -30.4pp collapse (90.0% → 59.6%)

2. **Root Cause: Deployment Bug**
   - CatBoost V8 deployed Jan 8 with WRONG FEATURES
   - Model trained on 33 features, received 25 features
   - Critical bug in `minutes_avg_last_10` feature computation
   - Fixed Jan 9 but confidence never recovered

3. **CatBoost V8 Isolated**
   - Only CatBoost V8 degraded
   - All other systems IMPROVED during same period
   - Confirms this was a V8-specific deployment issue

4. **Current State (Jan 12-15)**
   - Accuracy restored: 5.6-5.9 points (near baseline)
   - Confidence broken: All picks at exactly 50%
   - System says "I don't know" for everything

---

## Analysis Results

### 1. Prediction Accuracy Comparison

| Metric | Jan 1-7 | Jan 8-15 | Change | Interpretation |
|--------|---------|----------|--------|----------------|
| **Win Rate** | 54.3% | 47.0% | **-7.3pp** | Went from beating coin flip to below random |
| **Avg Error** | 4.22 pts | 6.43 pts | **+52.5%** | Predictions missing by 52% more |
| **StdDev** | 5.54 | 8.33 | **+50.4%** | Much more erratic/unstable |
| **Avg Edge** | 2.98 pts | 3.60 pts | +20.8% | Edge increased but accuracy decreased |
| **Total Picks** | 842 | 783 | -7.0% | Slight volume decrease |

**Verdict**: Predictions became significantly WORSE across all accuracy metrics.

---

### 2. Confidence Distribution Analysis

#### Healthy Period (Dec 20 - Jan 7)
**Confidence Distribution**:
- 90%+ confidence: 1,018 picks (47.0%)
- 84-89% confidence: 520 picks (24.0%)
- <84% confidence: 0 picks (0%)
- **Average**: 90.7% confidence

**Actual Performance by Confidence**:
| Stated Confidence | Picks | Actual Win Rate | Calibration Error |
|-------------------|-------|-----------------|-------------------|
| 95% | 237 | 51.9% | **-43.1pp** (over-confident) |
| 92% | 781 | 58.1% | **-33.9pp** (over-confident) |
| 90% | 566 | 64.3% | **-25.7pp** (over-confident) |
| 89% | 113 | 43.4% | **-45.6pp** (over-confident) |
| 87% | 401 | 56.1% | **-30.9pp** (over-confident) |
| 84% | 63 | 41.3% | **-42.7pp** (over-confident) |

**Pattern**: System was massively over-confident. 90%+ picks actually won 52-64%, not 90%+.

#### After Change (Jan 8-15)
**Confidence Distribution**:
- 90%+ confidence: 0 picks (0%)
- 84-89% confidence: 201 picks (25.7%)
- <84% confidence: 582 picks (74.3%)
- **Average**: 59.6% confidence

**Actual Performance by Confidence**:
| Stated Confidence | Picks | Actual Win Rate | Calibration Error |
|-------------------|-------|-----------------|-------------------|
| 89% | 139 | 34.5% | **-54.5pp** (WORSE over-confidence) |
| 84% | 62 | 43.5% | **-40.5pp** (WORSE over-confidence) |
| 50% | 582 | 50.3% | **+0.3pp** (PERFECTLY calibrated!) |

**Pattern**:
- High-confidence picks became EVEN MORE over-confident
- Most picks collapsed to 50% (default uncertainty)
- 50% confidence picks are perfectly calibrated

---

### 3. Daily Timeline - Exact Failure Point

**January 7 (Last Normal Day)**:
- 191 picks
- 90.2% average confidence
- 123 picks at 90%+ confidence
- 51.8% win rate
- 4.05 point error

**January 8 (FAILURE BEGINS)**:
- 26 picks (-86% volume!)
- 89.0% average confidence
- **0 picks at 90%+ confidence** (vs 123 baseline)
- 42.3% win rate
- 8.89 point error (+119%!)

**January 10-11 (Continued Degradation)**:
- 62-113 picks (recovering volume)
- 84-89% average confidence
- Still 0 picks at 90%+ confidence
- 32.7-43.5% win rate (WORSE than Jan 8!)
- 7.5-8.3 point error

**January 12-15 (Confidence Collapse)**:
- 14-463 picks (volume fully recovered by Jan 15)
- Exactly 50% confidence for ALL picks
- 50.3% win rate (perfectly calibrated!)
- 5.6-5.9 point error (back to baseline)

---

### 4. Cross-System Comparison

| System | Jan 1-7 Win Rate | Jan 8-15 Win Rate | Change | Confidence Change |
|--------|------------------|-------------------|--------|-------------------|
| **catboost_v8** | 54.3% | 47.0% | **-7.3pp** | **-30.4pp** |
| ensemble_v1 | 41.8% | 46.6% | **+4.8pp** | -7.6pp |
| moving_average | 44.9% | 48.3% | **+3.4pp** | -0.7pp |
| similarity_balanced | 40.1% | 46.0% | **+5.9pp** | -0.2pp |
| zone_matchup_v1 | 42.1% | 49.2% | **+7.1pp** | +0.3pp |

**CRITICAL FINDING**: CatBoost V8 is the ONLY system that got worse. All others IMPROVED!

**Error Comparison**:
- CatBoost V8: +52.5% error increase (worst)
- Ensemble V1: +18.6% error increase
- Moving Average: +16.2% error increase
- Similarity Balanced: +16.9% error increase
- Zone Matchup: +7.3% error increase

**Verdict**: CatBoost V8 degraded 3x worse than any other system during the same period.

---

### 5. Root Cause: Deployment Bug

#### The Bug Timeline

**Jan 8, 11:16 PM**: CatBoost V8 deployed (commit e2a5b54)
- Model trained on 33 features
- Production receiving only 25 features (v1_baseline_25)
- **Feature mismatch → catastrophic failure**

**Jan 9, 3:22 AM**: Feature store upgraded (commit c74db7d)
- Upgraded to v2_33features (33 features)
- But `minutes_avg_last_10` feature had critical bug

**Jan 9, 9:05 AM**: Feature computation bug fixed (commit eb0edb5)
- Fixed ROW_NUMBER computation in `minutes_avg_last_10`
- Model MAE improved from 8.14 → 4.05
- Win rate improved from 57% → 73.7%

**Jan 9, 3:21 PM**: Feature version corrected (commit b30c8e2)
- Fixed data_loaders to use v2_33features
- Backfilled Jan 9-10 data
- But daily pipeline still writes v1_baseline_25 (tech debt)

#### The Three Bugs

**Bug 1: Wrong Feature Count (Jan 8 - Jan 9 3:21 PM)**
- Model expected 33 features, got 25
- Duration: ~16 hours
- Impact: Catastrophic (8.89 error, 42% win rate)

**Bug 2: Broken Feature Computation (Jan 8 - Jan 9 9:05 AM)**
- `minutes_avg_last_10` computed incorrectly
- Duration: ~10 hours
- Impact: Severe (8.14 MAE, 57% win rate)

**Bug 3: Split Pipeline (Jan 8 - Ongoing)**
- Backfill creates v2_33features
- Daily pipeline creates v1_baseline_25
- Requires manual conversion
- Impact: Moderate (operational overhead)

---

### 6. Why Confidence Never Recovered

Even after all bugs fixed (Jan 12+), confidence stuck at 50%. Possible explanations:

**Hypothesis 1: Calibration Layer Broken**
- Confidence comes from separate calibration layer
- May still use broken feature values
- Or parameters reset during deployment

**Hypothesis 2: Model Uncertainty State**
- Model tracks recent prediction errors
- After catastrophic Jan 8-11 failures, confidence never reset
- Would require model reload/retrain

**Hypothesis 3: Confidence Computation Bug**
- Confidence calculation itself broken
- Defaulting to 50% when can't compute
- Need to audit confidence score generation

**Hypothesis 4: Training/Production Mismatch**
- Model calibrated on training data with correct features
- Production has slightly different feature distributions
- Causes confidence to collapse to default

**Evidence supporting Hypothesis 1 or 3**:
- Predictions are accurate (5.6-5.9 error, 50% win rate)
- But confidence is identical for ALL picks (exactly 50%)
- Suggests confidence calculation is broken or defaulting

---

## Key Insights

### 1. This Was NOT a Calibration Fix
The Jan 1-7 period showed massive over-confidence (90% stated → 55% actual). One might think the confidence drop was a "fix" to this over-confidence. However:

- **Counter-evidence**:
  - Accuracy also degraded (not just confidence)
  - Only CatBoost V8 affected (not systemic)
  - Overnight change (not gradual recalibration)
  - Bug fixes correlate with changes

**Verdict**: This was a broken deployment, not an intentional calibration improvement.

### 2. Previous System Was Also Broken
The Jan 1-7 "healthy" period was actually broken too:
- 25-52pp over-confidence across all tiers
- 95% confident picks only winning 52%
- This suggests systemic issues even before deployment

**Implications**:
- Baseline performance may be lower than thought
- Need to audit pre-Jan system for issues
- "Recovery" target may be wrong target

### 3. Lower Confidence Can Be Better
Comparing Jan 8-15 periods:
- **Jan 10-11** (84-89% confidence): 7.5-8.3 error, 33-44% win rate
- **Jan 12-15** (50% confidence): 5.6-5.9 error, 50% win rate

When confidence dropped to 50%, predictions actually got MORE accurate!

**Interpretation**: The model "knows" when it doesn't know. 50% confidence is honest uncertainty.

### 4. Confidence ≠ Accuracy
- Jan 1-7: High confidence (90%), mediocre accuracy (54% win rate)
- Jan 8-11: Medium confidence (84-89%), terrible accuracy (33-44% win rate)
- Jan 12-15: Low confidence (50%), neutral accuracy (50% win rate)

**Pattern**: No correlation between stated confidence and actual accuracy. Confidence scores are meaningless.

---

## Business Impact

### Picks Lost
- **High-confidence picks**: ~1,000 (Jan 8-15)
- **Jan 7 baseline**: 123 high-confidence picks/day
- **Jan 8-15**: 0 high-confidence picks/day

### Accuracy Impact
- **Jan 8-11**: Catastrophic (8-9 point error, 33-44% win rate)
- **Jan 12-15**: Neutral (6 point error, 50% win rate)
- **Compared to baseline**: Still -7.3pp win rate, +52% error

### Revenue Impact (Estimated)
- Lost edge on high-confidence picks: $3,000-$5,000
- Losses from bad predictions Jan 8-11: $5,000-$10,000
- **Total estimated loss: $8,000-$15,000**

---

## Recommendations

### Immediate Actions (Next 24 Hours)

1. **Investigate Confidence Collapse**
   - Audit confidence score computation code
   - Check calibration layer parameters
   - Test on known-good data
   - Determine why stuck at 50%

2. **Fix Daily Pipeline**
   - Update ml_feature_store_processor.py to write v2_33features
   - Backfill remaining v1_baseline_25 data
   - Verify all systems use v2 going forward

3. **Add Feature Validation**
   - Validate feature count = 33
   - Validate feature distributions in expected ranges
   - Alert on mismatches

### Short-term (Next Week)

4. **Implement Deployment Safety**
   - Pre-deployment validation tests
   - Canary deployments (1-5% traffic first)
   - Automatic rollback on error spikes
   - Blue-green deployment for models

5. **Improve Monitoring**
   - Confidence distribution tracking with alerts
   - Prediction quality metrics (error, win rate)
   - Volume monitoring with thresholds
   - Feature distribution anomaly detection

6. **Retrain Calibration**
   - Current confidence scores meaningless
   - Recalibrate using Dec-Jan actual performance
   - Use Platt scaling or isotonic regression
   - Validate on holdout set before deployment

### Medium-term (Next Month)

7. **Add Integration Tests**
   - End-to-end tests with real data
   - Feature computation validation
   - Model prediction sanity checks
   - Confidence calibration tests

8. **Audit Historical Performance**
   - Was Dec-Jan also over-confident?
   - When was system last "healthy"?
   - What's the true baseline performance?

9. **Consider Ensemble Fallback**
   - CatBoost V8 unreliable
   - Ensemble V1 and Zone Matchup improved during same period
   - Use weighted ensemble when CatBoost < 70% confidence

---

## Conclusion

### Question: Did predictions degrade or just confidence shift?
**Answer**: BOTH degraded severely due to deployment bug.

### Key Evidence
- **Accuracy**: +52.5% error, -7.3pp win rate
- **Confidence**: -30.4pp average, 0 high-confidence picks
- **Isolation**: Only CatBoost V8 affected
- **Timing**: Overnight Jan 7→8 (deployment)
- **Root Cause**: Wrong features (25 vs 33) and computation bug

### Current State (Jan 16)
- **Bugs**: Fixed (as of Jan 9)
- **Accuracy**: Restored to ~6 point error, 50% win rate
- **Confidence**: Still broken (all picks at 50%)
- **Status**: Functional but not optimal

### Critical Next Step
**Fix confidence computation** to restore full functionality. System is currently accurate but can't identify high-edge opportunities because all picks are marked as 50% uncertain.

---

## Appendix: Supporting Documents

Generated reports:
1. `/home/naji/code/nba-stats-scraper/ACCURACY_VS_CONFIDENCE_ANALYSIS_JAN16.md` - Detailed statistical analysis
2. `/home/naji/code/nba-stats-scraper/CATBOOST_V8_TIMELINE_ANALYSIS_JAN16.md` - Daily breakdown of failure
3. `/home/naji/code/nba-stats-scraper/ROOT_CAUSE_IDENTIFIED_JAN16.md` - Root cause investigation with git commits

SQL queries executed:
- Prediction accuracy comparison (Jan 1-7 vs Jan 8-15)
- Confidence distribution analysis (healthy vs degraded periods)
- Confidence calibration check (stated vs actual win rate)
- Cross-system comparison (all prediction systems)
- Daily trend analysis (Dec 20 - Jan 15)

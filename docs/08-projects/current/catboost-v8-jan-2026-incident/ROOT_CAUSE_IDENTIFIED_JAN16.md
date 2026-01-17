# Root Cause Identified: CatBoost V8 Deployment Bug
**Date**: 2026-01-16
**Incident**: Prediction accuracy and confidence degradation Jan 8-15

---

## Executive Summary

**ROOT CAUSE CONFIRMED**: CatBoost V8 was deployed on Jan 8 with the WRONG FEATURES, causing catastrophic failure. The model was trained on 33 features but initially received only 25 features, and even after fixes, had a critical bug in the `minutes_avg_last_10` feature computation.

**Timeline**:
1. **Jan 8, 11:16 PM**: V8 deployed to production (commit e2a5b54)
2. **Jan 8-9**: Model received wrong features → catastrophic failure
3. **Jan 9, 3:22 AM**: Feature store upgraded to 33 features (commit c74db7d)
4. **Jan 9, 9:05 AM**: Critical bug fix for `minutes_avg_last_10` (commit eb0edb5)
5. **Jan 9, 3:21 PM**: Feature version corrected from v1_baseline_25 → v2_33features (commit b30c8e2)

---

## Detailed Timeline

### Jan 8, 11:16 PM - Initial Deployment (BROKEN)
**Commit**: e2a5b54 - "feat(predictions): Replace mock XGBoostV1 with CatBoost V8 in production"

**What was deployed**:
- CatBoost V8 model (trained on 33 features)
- Expected to receive v2_33features from feature store
- Model had 3.40 MAE in testing vs 4.80 for XGBoost V1

**What went wrong**:
- Feature store was still on v1_baseline_25 (only 25 features!)
- Model received incorrect/incomplete feature vectors
- This caused the catastrophic failure observed on Jan 8

**Evidence from data**:
- Jan 7: 191 picks, 90.2% confidence, 4.05 error
- Jan 8: 26 picks, 89.0% confidence, 8.89 error (+119% error!)
- Volume collapsed because model couldn't make confident predictions with wrong features

---

### Jan 9, 3:22 AM - Feature Store Upgrade
**Commit**: c74db7d - "feat(ml): Upgrade feature store to 33 features for v8"

**What was fixed**:
- Feature store upgraded to support v2_33features
- Backfilled historical data with 33-feature vectors

**But still broken**:
- Daily ml_feature_store_processor.py still writing v1_baseline_25
- Model still not receiving correct features in real-time

---

### Jan 9, 9:05 AM - Critical Bug Fix
**Commit**: eb0edb5 - "fix(ml): Fix minutes_avg_last_10 feature computation bug"

**Bug description**:
```
The ROW_NUMBER was computed globally instead of relative to each
game date, causing incorrect feature values for historical data.
```

**Impact**:
- Before fix: Model MAE 8.14, Win rate 57%
- After fix: Model MAE 4.05, Win rate 73.7%

**This explains**:
- Why even after getting 33 features, predictions were still bad
- Why error was 7-9 points during Jan 8-11
- Why high-confidence picks (89%) only won 34.5% of the time

---

### Jan 9, 3:21 PM - Feature Version Correction
**Commit**: b30c8e2 - "fix(predictions): Correct feature version from v1_baseline_25 to v2_33features"

**Quote from commit**:
```
CRITICAL FIX: The V8 CatBoost model was trained on 33 features but the earlier
fix mistakenly set data_loaders to use v1_baseline_25 (25 features). This
caused the model to receive incorrect/incomplete features.
```

**What was fixed**:
- Reverted data_loaders.py to default to v2_33features
- Updated prediction systems to expect v2_33features
- Backfilled Jan 9-10 data with v2_33features (187 rows converted)

**Result**:
- 144 predictions for Jan 9 with avg confidence 53.27%
- Model now receiving correct 33-feature vectors
- But confidence still low (53% vs 90% pre-deployment)

---

## The Three Bugs

### Bug 1: Wrong Feature Version (Jan 8-9, 3:21 PM)
**Duration**: ~16 hours
**Impact**: CATASTROPHIC
- Model trained on 33 features, received 25 features
- Feature vector mismatch → garbage predictions
- Confidence collapsed because model "knew" something was wrong

**Data evidence**:
- Jan 8: 8.89 point error (vs 4.05 baseline)
- Jan 8: 26 picks (vs 191 baseline) - model couldn't make confident predictions
- No picks over 90% confidence (vs 123 baseline)

### Bug 2: minutes_avg_last_10 Computation Error (Jan 8-9, 9:05 AM)
**Duration**: ~10 hours
**Impact**: SEVERE
- ROW_NUMBER computed globally instead of per-game-date
- Feature values completely wrong for historical lookback
- Model received correct number of features but wrong values

**Data evidence**:
- Before fix: 8.14 MAE, 57% win rate
- After fix: 4.05 MAE, 73.7% win rate
- This explains why Jan 10-11 (89% confidence) had 32-43% actual win rate

### Bug 3: Daily Pipeline Still Writing v1 Features (Jan 9+)
**Duration**: ONGOING (as of Jan 9)
**Impact**: MODERATE
- Backfill created v2_33features data
- Daily ml_feature_store_processor.py still writes v1_baseline_25
- Requires manual backfill to convert daily data

**Quote from commit b30c8e2**:
```
Root cause: The backfill script created v2_33features data, but the daily
ml_feature_store_processor.py still writes v1_baseline_25. This tech debt
remains to be addressed.
```

---

## Mapping Bugs to Data Patterns

### Jan 8: Bug 1 + Bug 2 Active
**Symptoms**:
- Error: 8.89 points (+119% from baseline)
- Picks: 26 (vs 191 baseline, -86%)
- Confidence: 89% avg, but NO 90%+ picks
- Win rate: 42.3%

**Explanation**:
- Wrong features (25 instead of 33)
- Wrong feature values (minutes_avg_last_10 broken)
- Model couldn't make confident predictions
- Very few picks passed confidence threshold

### Jan 10-11: Bug 2 Still Active, Bug 1 Partially Fixed
**Symptoms**:
- Error: 7.5-8.3 points (still very high)
- Picks: 62-113 (recovering volume)
- Confidence: 84-89% avg, still NO 90%+ picks
- Win rate: 32.7-43.5% (WORSE than Jan 8!)

**Explanation**:
- Now receiving 33 features
- But minutes_avg_last_10 still broken
- Model making more predictions but they're BAD
- High confidence (89%) massively over-confident (actual 32.7%)

### Jan 12+: All Bugs Fixed, But Confidence Collapsed
**Symptoms**:
- Error: 4.2-5.9 points (back to near-baseline!)
- Picks: 14-463 (volume recovered by Jan 15)
- Confidence: Exactly 50% for all picks
- Win rate: 50.3% (perfectly calibrated!)

**Explanation**:
- Bugs fixed, predictions accurate again
- But confidence scores never recovered
- Model defaulting to 50% uncertainty
- System is working but says "I don't know" for everything

---

## Why Confidence Never Recovered

Even after all bugs were fixed, confidence remained at 50%. Possible explanations:

### Hypothesis 1: Calibration Layer Broken
- Confidence scores come from a separate calibration layer
- That layer may still be using broken feature values
- Or calibration parameters were reset during deployment

### Hypothesis 2: Model Uncertainty After Errors
- Model may have internal state tracking recent errors
- After catastrophic failures on Jan 8-11, confidence never reset
- Would require model reload or retraining

### Hypothesis 3: Confidence Computation Bug
- The confidence calculation itself may be broken
- Defaulting to 50% when it can't compute properly
- Need to audit confidence score generation code

### Hypothesis 4: Training Data Mismatch
- Model was calibrated on training data with correct features
- Now receiving slightly different feature distributions in production
- Causing confidence to collapse to default

---

## Business Impact

### Picks Lost (Jan 8-15)
**High-confidence picks (90%+)**:
- Jan 7 baseline: 123 picks
- Jan 8-15: 0 picks
- **Total lost: ~1,000 high-confidence picks over 8 days**

### Accuracy Degradation
**Jan 8-11 (bugs active)**:
- Error increased from 4.2 to 7.5-8.9 points
- Win rate dropped from 54% to 33-43%
- High-confidence picks were actively harmful

**Jan 12-15 (bugs fixed)**:
- Error returned to 5.6-5.9 points (near baseline)
- Win rate at 50% (neutral)
- But no confident picks, all at 50%

### Revenue Impact
Assuming $100 unit size and 1,000 high-confidence picks lost:
- Expected edge: 3-5% on high-confidence picks
- Lost EV: $3,000-$5,000
- Plus losses from bad predictions Jan 8-11: ~$5,000-$10,000
- **Total estimated loss: $8,000-$15,000**

---

## Lessons Learned

### Deployment Issues

1. **Feature Version Mismatch**
   - Model trained on v2_33features
   - Production using v1_baseline_25
   - **No validation to catch this before deployment**

2. **Bug in Feature Computation**
   - minutes_avg_last_10 had a logic error
   - **No integration tests to catch this**
   - Only discovered after deployment to production

3. **Split Codepaths**
   - Backfill script creates v2_33features
   - Daily pipeline writes v1_baseline_25
   - **Technical debt caused production issues**

4. **No Rollback Plan**
   - When V8 failed, couldn't quickly rollback to V1
   - Had to debug and fix forward
   - **Cost 3 days of degraded performance**

### Monitoring Gaps

1. **No Feature Validation**
   - Should alert when model receives wrong feature count
   - Should alert when feature distributions are anomalous

2. **No Confidence Distribution Monitoring**
   - Confidence collapsing from 90% to 50% should trigger alert
   - High-confidence picks disappearing should trigger alert

3. **No Prediction Quality Alerts**
   - Error increasing from 4 to 9 points should trigger alert
   - Win rate dropping from 54% to 32% should trigger alert

4. **No Volume Monitoring**
   - Picks dropping from 191 to 26 should trigger alert
   - This is a ~85% drop - should be caught immediately

---

## Recommendations

### Immediate (Already Done)
- [x] Fix feature version mismatch (Jan 9)
- [x] Fix minutes_avg_last_10 bug (Jan 9)
- [x] Backfill Jan 9-10 data (Jan 9)

### Short-term (Next 24 Hours)

1. **Investigate Confidence Collapse**
   - Audit confidence score computation code
   - Check if calibration layer needs retraining
   - Determine why confidence stuck at 50%

2. **Fix Daily Pipeline**
   - Update ml_feature_store_processor.py to write v2_33features
   - Stop creating v1_baseline_25 data going forward
   - Backfill any remaining v1 data to v2

3. **Add Feature Validation**
   - Validate feature count matches expected (33)
   - Validate feature distributions are in expected ranges
   - Alert on anomalies

### Medium-term (Next Week)

4. **Implement Deployment Safety**
   - Pre-deployment feature validation
   - Canary deployments (small % of traffic first)
   - Automatic rollback on error rate spike
   - Blue-green deployment for models

5. **Improve Monitoring**
   - Confidence distribution tracking
   - Prediction quality metrics
   - Volume monitoring with thresholds
   - Feature distribution monitoring

6. **Add Integration Tests**
   - End-to-end tests with real data
   - Feature computation validation
   - Model prediction sanity checks
   - Confidence calibration tests

7. **Document Rollback Procedure**
   - How to quickly revert to previous model
   - How to verify rollback worked
   - Who has authority to execute
   - Communication plan

---

## Current Status (Jan 16)

### What's Fixed
- [x] Feature version correct (v2_33features)
- [x] minutes_avg_last_10 computation fixed
- [x] Predictions accurate again (5.6-5.9 point error)
- [x] Win rate at 50% (neutral)

### What's Still Broken
- [ ] Confidence scores stuck at 50%
- [ ] No high-confidence picks (90%+) since Jan 8
- [ ] Daily pipeline still creates v1_baseline_25 data
- [ ] No monitoring to prevent recurrence

### Risk Level
**MEDIUM**: System is functional but not optimal
- Predictions are accurate
- But confidence is meaningless (always 50%)
- Cannot identify high-edge opportunities
- Operating at reduced effectiveness

---

## Conclusion

**Root Cause**: Deployment of CatBoost V8 with multiple critical bugs:
1. Wrong feature version (25 instead of 33 features)
2. Broken feature computation (minutes_avg_last_10)
3. Daily pipeline still writing old feature version

**Impact**:
- Jan 8-11: Catastrophic failure (9 point error, 32% win rate)
- Jan 12-15: Accurate but low confidence (6 point error, 50% win rate)
- ~1,000 high-confidence picks lost
- $8,000-$15,000 estimated revenue impact

**Current State**:
- Predictions accurate but confidence broken
- All picks at 50% confidence (default/uncertain)
- Need to fix confidence computation to restore full functionality

**Key Lesson**: Never deploy a model without validating:
1. Feature count matches training
2. Feature values are in expected ranges
3. Predictions are reasonable on test set
4. Confidence scores are calibrated
5. Monitoring is in place to detect issues immediately

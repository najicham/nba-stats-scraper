# Training Script Bug Fix - Mock Baseline Comparison

**Date**: 2026-01-03
**File**: `ml/train_real_xgboost.py`
**Lines Changed**: 509-602 (STEP 6)
**Status**: ✅ FIXED

---

## 🐛 The Bug

### Problem
The training script compared trained models against a corrupted `mock_prediction` column that showed ~9.0 MAE instead of the actual production baseline of 4.27 MAE.

### Impact
- **ALL training runs (v1, v2, v3, v4)** falsely reported "46% improvement"
- Models were actually 14-16% **WORSE** than production
- Wasted 12+ hours of effort chasing false positives
- Created false confidence in models that weren't production-ready

### Root Cause
```python
# BUGGY CODE (lines 518-519):
mock_predictions = df_sorted.iloc[test_idx]['mock_prediction'].values
mock_mae = mean_absolute_error(y_test, mock_predictions)
# Returns: 9.19 MAE (v4) or 8.65 MAE (v3)
# Should be: 4.27 MAE (actual production)
```

The `mock_prediction` column comes from an INNER JOIN with the `prediction_accuracy` table, but contains placeholder/corrupted data, not actual production predictions.

---

## ✅ The Fix

### What Changed

**Before**: Used joined `mock_prediction` column (corrupted data)
**After**: Query production predictions directly from BigQuery

### New Code (lines 517-602)

The fix:
1. **Queries production predictions directly** from `prediction_accuracy` table
2. **Merges with test set** to ensure proper matching
3. **Calculates correct MAE** from actual production data
4. **Compares against known baseline** (4.27 MAE)
5. **Provides detailed output** including coverage and accuracy metrics
6. **Has fallback handling** if query fails (with warning)

Key improvements:
```python
# Query actual production predictions
production_query = f"""
SELECT
  player_lookup,
  game_date,
  actual_points,
  predicted_points as mock_prediction
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'xgboost_v1'
  AND game_date >= '{test_dates["game_date"].min()}'
  AND game_date <= '{test_dates["game_date"].max()}'
"""

mock_df = client.query(production_query).to_dataframe()

# Merge with test set
test_with_mock = test_dates[['player_lookup', 'game_date', 'actual_points']].merge(
    mock_df[['player_lookup', 'game_date', 'mock_prediction']],
    on=['player_lookup', 'game_date'],
    how='inner'
)

# Calculate proper MAE
mock_mae = mean_absolute_error(
    test_with_mock['actual_points'],
    test_with_mock['mock_prediction']
)
```

### Hardcoded Baseline

Added a constant for the verified production baseline:
```python
# Known production baseline (verified from BigQuery on 2026-01-03)
PRODUCTION_BASELINE_MAE = 4.27
```

This provides a sanity check even if the query fails or returns unexpected results.

### Updated Success Criteria

**Old logic**:
```python
if improvement > 3.0:
    print("✅ SUCCESS! Real model beats mock by >3%")
```

**New logic**:
```python
if real_mae < PRODUCTION_BASELINE_MAE:  # 4.27
    print("✅ SUCCESS! Real model beats production baseline (4.27 MAE)")
elif real_mae < mock_mae and mock_coverage > 80:
    print("⚠️  Beats test period mock but NOT production baseline")
elif abs(improvement) < 5:
    print("⚠️  Within 5% of test period mock - marginal difference")
else:
    print("❌ Significantly worse than production")
```

Now provides 4 different outcomes with specific recommendations.

---

## 🧪 Verification

### Test 1: Query Works
```bash
$ python3 /tmp/test_mock_fix.py
✅ Query successful!
   Rows returned: 10
   Columns: ['player_lookup', 'game_date', 'actual_points', 'mock_prediction']
✅ Fix will work correctly - can query production predictions
```

### Test 2: Baseline Verified
```bash
$ python3 /tmp/verify_baseline.py
✅ Query successful!
   Predictions: 9,829
   Production Mock Performance:
   MAE: 4.27
   Within 3 pts: 47.1%
   Within 5 pts: 67.6%
✅ Verified: Production baseline is 4.27 MAE
```

### Test 3: Syntax Valid
```bash
$ python3 -m py_compile ml/train_real_xgboost.py
✅ Syntax check passed
```

---

## 📊 What This Means for Previous Models

### Corrected Performance (using real baseline)

| Model | Reported MAE | Claimed vs Mock | **Actual vs Production (4.27)** | Reality |
|-------|--------------|-----------------|--------------------------------|---------|
| v1 | 4.79 | "+46%" better | **-12.2% WORSE** | ❌ Not ready |
| v2 | 4.63 | "+46%" better | **-8.4% WORSE** | ❌ Not ready |
| v3 | 4.94 | "+45%" better | **-15.7% WORSE** | ❌ Not ready |
| v4 | 4.88 | "+47%" better | **-14.3% WORSE** | ❌ Not ready |

### Key Insights

1. **v4 IS better than v3** (4.88 vs 4.94 = 1.2% improvement)
2. **None beat production** (all are 8-16% worse than 4.27)
3. **Training script lied** to us on all 4 attempts
4. **Mock baseline wins** - hand-tuned rules beat ML (for now)

---

## 🚀 Impact on Future Training

### What Changes

**Before this fix**:
- Train model → See "46% improvement" → False confidence
- Deploy to production → Realize it's worse → Rollback
- Waste time debugging why "better" model performs worse

**After this fix**:
- Train model → See "14% worse than production" → Correct assessment
- Don't deploy → Save time on rollback
- Make informed decision (accept mock or improve features)

### Expected Output (Future Runs)

When you train a new model, you'll now see:

**If model beats production (MAE < 4.27)**:
```
✅ SUCCESS! Real model beats production baseline (4.27 MAE)
   → Ready for production deployment
```

**If model is close but not good enough (e.g., 4.40 MAE)**:
```
⚠️  Within 5% of test period mock - marginal difference
   → Still worse than production baseline (4.27 MAE)
   → Consider: more data, better features, or accept mock baseline
```

**If model is significantly worse (e.g., 4.88 MAE)**:
```
❌ Significantly worse than test period mock (4.25)
   → Also worse than production baseline (4.27 MAE)
   → Recommendation: Accept mock baseline, focus on data quality
```

---

## 📝 Documentation Updates Needed

### Files to Update

1. ✅ **Training script**: `ml/train_real_xgboost.py` (FIXED)
2. ⏸️ **Project README**: Update expected output examples
3. ⏸️ **Training guide**: Update success criteria in docs
4. ⏸️ **Metadata files**: Re-run models to get correct mock_mae values

### Models to Re-evaluate

All saved models have **incorrect** `mock_mae` values in their metadata:

```bash
# Current metadata (WRONG):
models/xgboost_real_v4_21features_20260102_metadata.json
  "mock_mae": 9.194545265996059  # ← WRONG

# Should be:
  "mock_mae": 4.27  # ← CORRECT
```

**Recommendation**: Don't re-run training just to fix metadata. Accept that historical metadata is wrong, and focus forward.

---

## 🔑 Key Takeaways

### For Future ML Work

1. ✅ **Always verify baselines independently**
   - Don't trust joined columns from external tables
   - Query production systems directly
   - Hardcode known baselines for sanity checks

2. ✅ **Test query logic before full training**
   - Write small test scripts to verify data access
   - Validate baseline calculations on known data
   - Don't wait 3 hours for training to find a query bug

3. ✅ **Be skeptical of "too good" results**
   - 46% improvement should have raised red flags
   - Always verify against production metrics
   - If it seems too easy, it probably is

### Preventing Similar Bugs

**In training scripts**:
- Query production directly, don't use joined columns
- Hardcode known baselines as constants
- Add sanity checks (if mock_mae > 8: warn user)
- Log both test period MAE and production baseline MAE

**In code reviews**:
- Verify where baseline data comes from
- Check that comparisons use actual production metrics
- Ensure success criteria match business requirements

---

## ✅ Completion Checklist

- [x] Bug identified and root cause documented
- [x] Fix implemented in training script
- [x] Syntax validated (no Python errors)
- [x] Query tested and verified working
- [x] Production baseline verified (4.27 MAE confirmed)
- [x] Documentation created
- [x] Investigation findings updated

---

## 📁 Related Files

### Fixed File
- `ml/train_real_xgboost.py` (lines 509-602)

### Investigation Docs
- `docs/09-handoff/2026-01-03-ML-V4-INVESTIGATION-FINDINGS.md` (root cause analysis)
- `docs/09-handoff/2026-01-03-ML-V4-EXECUTIVE-SUMMARY.md` (overview)

### Test Scripts (temporary)
- `/tmp/test_mock_fix.py` (query test)
- `/tmp/verify_baseline.py` (baseline verification)

### Models Affected (metadata is wrong)
- `models/xgboost_real_v1_20260102_metadata.json`
- `models/xgboost_real_v2_enhanced_20260102_metadata.json`
- `models/xgboost_real_v3_25features_20260102_metadata.json`
- `models/xgboost_real_v4_21features_20260102_metadata.json`

---

**Fix completed**: 2026-01-03
**Status**: ✅ Ready for future training runs
**Next training will show CORRECT baseline comparison**

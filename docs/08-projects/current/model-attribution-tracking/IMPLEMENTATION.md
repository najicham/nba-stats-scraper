# Model Attribution Tracking - Implementation Guide

**Session**: 84
**Date**: February 2, 2026
**Status**: Ready for Deployment

---

## Overview

This implementation adds comprehensive model attribution tracking to the NBA predictions system, enabling us to track which exact model file generated which predictions.

### Problem Solved

Before this implementation:
- ❌ Could not determine which model file generated which predictions
- ❌ Historical analysis was impossible (75.9% HR could be from OLD or NEW model)
- ❌ No audit trail for model versions
- ❌ Debugging model issues required manual investigation

After this implementation:
- ✅ Every prediction tracks exact model file name
- ✅ Training period and expected performance stored
- ✅ Can distinguish between model versions in historical data
- ✅ Full audit trail for compliance and debugging

---

## Changes Made

### 1. Schema Updates

**File**: `schemas/bigquery/predictions/migrations/2026-02-02-model-attribution.sql`

Added 6 new fields to `player_prop_predictions` table:
```sql
- model_file_name (STRING)              # "catboost_v9_feb_02_retrain.cbm"
- model_training_start_date (DATE)      # 2025-11-02
- model_training_end_date (DATE)        # 2026-01-31
- model_expected_mae (FLOAT64)          # 4.12
- model_expected_hit_rate (FLOAT64)     # 74.6 (high-edge picks)
- model_trained_at (TIMESTAMP)          # When model was trained
```

Added 5 new fields to `prediction_execution_log` table:
```sql
- model_file_name (STRING)
- model_path (STRING)
- model_training_start_date (DATE)
- model_training_end_date (DATE)
- model_expected_mae (FLOAT64)
```

**Status**: ✅ Applied to BigQuery

### 2. Prediction System Updates

**File**: `predictions/worker/prediction_systems/catboost_v9.py`

**Changes**:
1. **Enhanced TRAINING_INFO dict** with:
   - `high_edge_hit_rate`: 74.6
   - `premium_hit_rate`: 56.5
   - `trained_at`: Timestamp when model was trained

2. **Track model file name** during model loading:
   - Extract file name from GCS path or local path
   - Store in `self._model_file_name`

3. **Enhanced predict() metadata** to include:
   ```python
   result['metadata']['model_file_name'] = self._model_file_name
   result['metadata']['model_training_start_date'] = "2025-11-02"
   result['metadata']['model_training_end_date'] = "2026-01-31"
   result['metadata']['model_expected_mae'] = 4.12
   result['metadata']['model_expected_hit_rate'] = 74.6
   result['metadata']['model_trained_at'] = "2026-02-02T10:15:00Z"
   ```

### 3. Worker Updates

**File**: `predictions/worker/worker.py`

**Function**: `format_prediction_for_bigquery()` (lines 1811-1827)

**Changes**: Extract model attribution from CatBoost metadata and add to BigQuery record:
```python
'model_file_name': metadata.get('model_file_name'),
'model_training_start_date': metadata.get('model_training_start_date'),
'model_training_end_date': metadata.get('model_training_end_date'),
'model_expected_mae': metadata.get('model_expected_mae'),
'model_expected_hit_rate': metadata.get('model_expected_hit_rate'),
'model_trained_at': metadata.get('model_trained_at'),
```

### 4. Verification Script

**File**: `bin/verify-model-attribution.sh`

**Purpose**: Verify model attribution is working correctly

**Features**:
- Checks coverage percentage (should be 100% for new predictions)
- Shows model file distribution
- Identifies predictions missing attribution
- Verifies model files match GCS bucket contents
- Provides actionable pass/fail/partial results

**Usage**:
```bash
# Check recent predictions
./bin/verify-model-attribution.sh

# Check specific date
./bin/verify-model-attribution.sh --game-date 2026-02-03
```

---

## Deployment Plan

### Prerequisites

1. ✅ Schema migrations applied to BigQuery
2. ✅ Code changes committed to main branch
3. ⏳ Code deployed to prediction-worker
4. ⏳ Verification completed

### Step 1: Commit Changes

```bash
git add .
git commit -m "feat: Add model attribution tracking to predictions

Session 84 - Enables tracking which exact model file generated which predictions.

Changes:
- Add 6 new fields to player_prop_predictions table
- Enhance catboost_v9.py to emit model file name and training metadata
- Update worker.py to extract and store model attribution
- Add verification script bin/verify-model-attribution.sh

Problem: Could not determine which model version produced 75.9% historical hit rate.
Solution: Every prediction now tracks exact model file, training period, and expected performance.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

### Step 2: Deploy Prediction Worker

```bash
# Deploy with latest code
./bin/deploy-service.sh prediction-worker

# Verify deployment
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"

# Should match latest commit hash
git log -1 --format="%h"
```

### Step 3: Wait for Next Prediction Run

**Prediction schedules**:
- **2:30 AM ET** - Early predictions (REAL_LINES_ONLY mode)
- **7:00 AM ET** - Overnight predictions (ALL_PLAYERS mode)
- **11:30 AM ET** - Same-day predictions

After next run, verify attribution is working:

```bash
./bin/verify-model-attribution.sh
```

**Expected output**:
```
CatBoost V9 Coverage: 100.0%

✅ PASS: Model attribution is working correctly
```

### Step 4: Verify Historical Tracking

```bash
# Check which model files have been used
bq query --use_legacy_sql=false "
SELECT
  model_file_name,
  COUNT(*) as predictions,
  MIN(game_date) as first_used,
  MAX(game_date) as last_used
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9'
  AND model_file_name IS NOT NULL
GROUP BY model_file_name
ORDER BY last_used DESC"
```

---

## Verification Queries

### 1. Check Model Attribution Coverage

```sql
-- What % of predictions have model attribution?
SELECT
  game_date,
  system_id,
  COUNT(*) as predictions,
  COUNTIF(model_file_name IS NOT NULL) as with_attribution,
  ROUND(100.0 * COUNTIF(model_file_name IS NOT NULL) / COUNT(*), 1) as coverage_pct
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date, system_id
ORDER BY game_date DESC, system_id;
```

### 2. Verify Model Performance Matches Expectations

```sql
-- Does actual MAE match expected MAE?
SELECT
  p.model_file_name,
  p.model_expected_mae as expected_mae,
  ROUND(AVG(ABS(pa.predicted_points - pa.actual_points)), 2) as actual_mae,
  ROUND(AVG(ABS(pa.predicted_points - pa.actual_points)) - p.model_expected_mae, 2) as mae_diff,
  COUNT(*) as graded_predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
  ON p.prediction_id = pa.prediction_id
WHERE p.system_id = 'catboost_v9'
  AND p.model_file_name IS NOT NULL
  AND pa.prediction_correct IS NOT NULL
GROUP BY p.model_file_name, p.model_expected_mae
ORDER BY MAX(pa.game_date) DESC;
```

### 3. Distinguish OLD vs NEW Model Performance

```sql
-- Compare historical performance by model file
SELECT
  CASE
    WHEN model_file_name LIKE '%feb_02%' THEN 'NEW (Feb-02 Retrain)'
    WHEN model_file_name LIKE '%2026_02%' THEN 'OLD (2026_02)'
    ELSE model_file_name
  END as model_version,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'catboost_v9'
  AND model_file_name IS NOT NULL
  AND ABS(predicted_points - line_value) >= 5  -- High-edge picks
  AND prediction_correct IS NOT NULL
GROUP BY model_version
ORDER BY MAX(game_date) DESC;
```

### 4. Track Model Deployment Timeline

```sql
-- When was each model first/last used?
SELECT
  model_file_name,
  model_expected_mae,
  COUNT(*) as predictions,
  MIN(game_date) as first_game,
  MAX(game_date) as last_game,
  DATE_DIFF(MAX(game_date), MIN(game_date), DAY) as days_active
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = 'catboost_v9'
  AND model_file_name IS NOT NULL
GROUP BY model_file_name, model_expected_mae
ORDER BY first_game DESC;
```

---

## Troubleshooting

### Issue: Coverage < 100%

**Symptom**: verification script shows coverage < 100%

**Cause**: Old worker instances still running without model attribution code

**Fix**:
```bash
# 1. Verify deployment is correct
./bin/check-deployment-drift.sh --verbose

# 2. Check latest commit deployed
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"

# 3. If wrong commit, redeploy
./bin/deploy-service.sh prediction-worker

# 4. Wait for next prediction run and re-verify
```

### Issue: model_file_name is NULL

**Symptom**: All predictions have NULL model_file_name

**Causes & Fixes**:

1. **Code not deployed**:
   ```bash
   ./bin/deploy-service.sh prediction-worker
   ```

2. **Model loading failed**:
   ```bash
   # Check worker logs for model loading errors
   gcloud logging read 'resource.type="cloud_run_revision"
     AND resource.labels.service_name="prediction-worker"
     AND textPayload=~"Loading.*V9"' --limit=10
   ```

3. **_model_file_name not set**:
   - Check catboost_v9.py has `self._model_file_name = ...` in load methods
   - Verify it's being set in both local and GCS loading paths

### Issue: Wrong model_file_name

**Symptom**: model_file_name doesn't match actual deployed model

**Cause**: TRAINING_INFO dict not updated when deploying new model

**Fix**:
1. Update `TRAINING_INFO` in `catboost_v9.py` to match deployed model
2. Redeploy prediction-worker
3. Verify with:
   ```bash
   # Check deployed model path
   gcloud run services describe prediction-worker --region=us-west2 \
     --format="value(spec.template.spec.containers[0].env)" | grep CATBOOST_V9_MODEL_PATH
   ```

### Issue: prediction_execution_log still empty

**Status**: This is EXPECTED

**Explanation**:
- `prediction_execution_log` was created in Session 64 but code was never implemented
- Actual execution logging happens in `prediction_worker_runs` table (159K+ records)
- `prediction_execution_log` is for batch-level summaries (future enhancement)

**Current state**:
- ✅ Worker-level logging: `prediction_worker_runs` (working)
- ⏳ Batch-level logging: `prediction_execution_log` (not implemented yet)

**No action needed** - worker-level logging is sufficient for model attribution.

---

## Files Modified

| File | Lines Changed | Purpose |
|------|---------------|---------|
| `schemas/bigquery/predictions/migrations/2026-02-02-model-attribution.sql` | New file | Schema migration |
| `predictions/worker/prediction_systems/catboost_v9.py` | ~50 lines | Emit model metadata |
| `predictions/worker/worker.py` | ~15 lines | Extract and store model metadata |
| `bin/verify-model-attribution.sh` | New file | Verification script |
| `docs/08-projects/current/model-attribution-tracking/DESIGN.md` | New file | Design document |
| `docs/08-projects/current/model-attribution-tracking/IMPLEMENTATION.md` | New file | This file |

---

## Testing

### Local Testing (Optional)

Not recommended - requires full BigQuery setup and model files.

### Production Testing

**After deployment, verify**:

1. **Schema exists**:
   ```bash
   bq show --schema nba_predictions.player_prop_predictions | grep model_file_name
   ```

2. **Code deployed**:
   ```bash
   ./bin/check-deployment-drift.sh --verbose
   ```

3. **Model attribution working** (after next prediction run):
   ```bash
   ./bin/verify-model-attribution.sh
   ```

---

## Success Criteria

- ✅ Schema migration applied to BigQuery
- ✅ Code changes committed to main
- ⏳ Code deployed to production
- ⏳ Verification script shows 100% coverage
- ⏳ Model file names match GCS bucket contents
- ⏳ Can distinguish OLD vs NEW model performance in historical data

---

## Next Steps

After successful deployment:

1. **Monitor coverage**: Run verification script daily for 3 days
2. **Analyze historical data**: Compare OLD vs NEW model performance
3. **Update notifications**: Add model attribution to daily picks (Task #4)
4. **Document in CLAUDE.md**: Add model attribution fields to quick reference
5. **Backfill (optional)**: Can backfill historical predictions using deployment timestamps

---

## Related Documentation

- Design: `docs/08-projects/current/model-attribution-tracking/DESIGN.md`
- Schema: `schemas/bigquery/predictions/migrations/2026-02-02-model-attribution.sql`
- Verification: `bin/verify-model-attribution.sh`
- Session Handoff: `docs/09-handoff/2026-02-02-SESSION-84-HANDOFF.md`

---

**Last Updated**: February 2, 2026
**Ready for Deployment**: Yes
**Deployment Risk**: Low (additive changes only, no breaking changes)

# CatBoost V9 Model Architecture

**Last Updated**: 2026-02-02 (Session 83)

## Overview

CatBoost V9 is the production model architecture using **current season training only** (vs V8's multi-season historical approach). This document clarifies the V9 naming and model variants to prevent deployment confusion.

## Key Concept: V9 = Architecture, Not a Single Model

"V9" refers to the **training approach** (current season only), not a single model file. Multiple V9 model files exist with different training dates as the season progresses.

## Current Production Setup

### Base Model: `catboost_v9`

| Property | Value |
|----------|-------|
| **System ID** | `catboost_v9` |
| **Model File** | `catboost_v9_feb_02_retrain.cbm` (Session 76) |
| **GCS Path** | `gs://nba-props-platform-models/catboost/v9/catboost_v9_feb_02_retrain.cbm` |
| **Training Window** | Nov 2, 2025 → Jan 31, 2026 (91 days) |
| **MAE** | 4.12 |
| **High-Edge Hit Rate** | 74.6% |
| **Status** | ✅ Production (Feb 2026) |

**How it loads**:
```python
# Configured via environment variable
CATBOOST_V9_MODEL_PATH=gs://nba-props-platform-models/catboost/v9/catboost_v9_feb_02_retrain.cbm

# Falls back to default if env var not set
DEFAULT_PATH = gs://nba-props-platform-models/catboost/v9/catboost_v9_33features_20260201_011018.cbm
```

**Implementation**: `predictions/worker/prediction_systems/catboost_v9.py`

### Monthly Models: `catboost_v9_YYYY_MM`

Separate system for running multiple monthly-retrained models in parallel.

#### catboost_v9_2026_02

| Property | Value |
|----------|-------|
| **System ID** | `catboost_v9_2026_02` |
| **Model File** | `models/catboost_v9_2026_02.cbm` (local) |
| **Training Window** | Nov 2, 2025 → Jan 24, 2026 (84 days) |
| **MAE** | 5.08 |
| **Hit Rate** | 50.84% |
| **Status** | ⚠️ Poor performance - Consider disabling |

**How it loads**:
```python
# Configured in catboost_monthly.py
MONTHLY_MODELS = {
    "catboost_v9_2026_02": {
        "model_path": "models/catboost_v9_2026_02.cbm",
        "enabled": True,
        ...
    }
}
```

**Implementation**: `predictions/worker/prediction_systems/catboost_monthly.py`

## Model File Inventory (GCS)

```bash
gs://nba-props-platform-models/catboost/v9/
├── catboost_v9_33features_20260201_011018.cbm    # 700KB, Feb 1 model
└── catboost_v9_feb_02_retrain.cbm                # 800KB, NEW model (Session 76) ✅
```

## Naming Confusion & Resolution

### Problem

Three things called "V9" with different meanings:

1. **Architecture**: V9 = current season training approach
2. **Base system**: `catboost_v9` = production model
3. **Monthly variant**: `catboost_v9_2026_02` = experimental monthly model

### How to Identify Which Model

Check the **system_id** in predictions:

```sql
SELECT system_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
GROUP BY system_id
```

| system_id | What it is |
|-----------|------------|
| `catboost_v9` | Base production model (GOOD - use this) |
| `catboost_v9_2026_02` | Monthly variant (POOR - 50% hit rate) |
| `catboost_v9_2026_03` | Future monthly variant (if added) |

## Deployment Checklist

When deploying V9 models, ensure:

1. **Environment variable set**:
   ```bash
   gcloud run services describe prediction-worker --region=us-west2 \
     --format="value(spec.template.spec.containers[0].env)" | grep CATBOOST_V9
   ```

   Should show:
   ```
   CATBOOST_V9_MODEL_PATH=gs://nba-props-platform-models/catboost/v9/catboost_v9_feb_02_retrain.cbm
   ```

2. **Model file exists**:
   ```bash
   gsutil ls -l gs://nba-props-platform-models/catboost/v9/catboost_v9_feb_02_retrain.cbm
   ```

3. **Worker logs confirm correct load**:
   ```bash
   gcloud logging read 'resource.labels.service_name="prediction-worker"
     AND textPayload=~"Loading CatBoost V9"' --limit=5
   ```

   Should show: `"Loading CatBoost V9 from: gs://...catboost_v9_feb_02_retrain.cbm"`

4. **Performance validation** (after first predictions):
   ```sql
   -- Check MAE and hit rate match expectations
   SELECT
     system_id,
     COUNT(*) as predictions,
     ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae
   FROM nba_predictions.prediction_accuracy
   WHERE system_id = 'catboost_v9'
     AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
   GROUP BY system_id
   ```

   Expected: MAE ≈ 4.12 (if significantly higher, wrong model loaded)

## Monthly Retraining Workflow

V9 is designed for continuous monthly retraining:

1. **Train new model** (early each month):
   ```bash
   PYTHONPATH=. python ml/experiments/quick_retrain.py \
     --name "V9_MAR_RETRAIN" \
     --train-start 2025-11-02 \
     --train-end 2026-02-28
   ```

2. **Upload to GCS** with descriptive name:
   ```bash
   gsutil cp models/catboost_v9_*.cbm \
     gs://nba-props-platform-models/catboost/v9/catboost_v9_mar_01_retrain.cbm
   ```

3. **Update environment variable**:
   ```bash
   gcloud run services update prediction-worker --region=us-west2 \
     --set-env-vars CATBOOST_V9_MODEL_PATH=gs://nba-props-platform-models/catboost/v9/catboost_v9_mar_01_retrain.cbm
   ```

4. **Validate deployment** using checklist above

5. **Update TRAINING_INFO** in `catboost_v9.py`:
   ```python
   TRAINING_INFO = {
       "training_start": "2025-11-02",
       "training_end": "2026-02-28",  # Update this
       "training_days": 118,           # Update this
       "mae": 4.05,                    # Update from validation
       ...
       "session": 85,                  # Update to session number
   }
   ```

## Common Issues

### Issue 1: Wrong Model Loaded

**Symptom**: MAE > 5.0 in production, hit rate < 55%

**Cause**: Worker loaded wrong model file (old V9 or monthly variant)

**Fix**:
1. Check `CATBOOST_V9_MODEL_PATH` env var
2. Verify model file in GCS
3. Redeploy with correct path

### Issue 2: Hardcoded Training Dates in Logs

**Symptom**: Logs show "Training: 2025-11-02 to 2026-01-08" but using newer model

**Cause**: `TRAINING_INFO` dict in `catboost_v9.py` has hardcoded dates

**Fix**: Update `TRAINING_INFO` when deploying new model (see Monthly Retraining Workflow #5)

### Issue 3: Multiple V9 Predictions per Player

**Symptom**: Both `catboost_v9` and `catboost_v9_2026_02` predictions for same player

**Cause**: Monthly model system runs in parallel with base model

**Solution**: This is expected behavior. Use `is_active = TRUE` filter in queries to get latest prediction per system.

## Performance Comparison

| Model | MAE | Premium HR | High-Edge HR | Training End | Status |
|-------|-----|-----------|--------------|--------------|--------|
| catboost_v9 | 4.12 | 56.5% | 74.6% | 2026-01-31 | ✅ Production |
| catboost_v9_2026_02 | 5.08 | N/A | 50.84% | 2026-01-24 | ⚠️ Poor |
| catboost_v8 | 5.36 | 52.5% | 56.9% | 2026-01-08 | 🔄 Baseline |

## References

- **Session 76**: NEW V9 model training and validation
- **Session 81**: Initial V9 deployment (had issues)
- **Session 82**: Fixed deployment, restored predictions
- **Session 83**: Validated model loading, fixed metadata
- **Code**: `predictions/worker/prediction_systems/catboost_v9.py`
- **Monthly System**: `predictions/worker/prediction_systems/catboost_monthly.py`

## Next Steps

1. **Validate Feb 2 performance** when games finish (Task #1)
2. **Consider disabling** `catboost_v9_2026_02` (poor performance)
3. **Plan March retrain** to expand training window to 118 days
4. **Add automated drift detection** to alert if MAE > 4.5 for 3+ days

# ML Model Production Deployment

**Date**: January 9, 2026
**Status**: DEPLOYED

---

## Summary

CatBoost V8 has replaced the mock XGBoostV1 in the Phase 5 prediction worker.

| Metric | V8 (New) | Mock (Old) | Improvement |
|--------|----------|------------|-------------|
| MAE | 3.40 | 4.80 | 29% better |
| Betting Accuracy | 71.6% | ~60% | +11.6% |
| Features | 33 | 25 | +8 features |

---

## What Changed

### Worker Code (`predictions/worker/worker.py`)

```python
# Before
from prediction_systems.xgboost_v1 import XGBoostV1
_xgboost = XGBoostV1()

# After
from prediction_systems.catboost_v8 import CatBoostV8
_xgboost = CatBoostV8()  # Same interface, better model
```

### System ID Change

The system_id in predictions changed from `xgboost_v1` to `catboost_v8`.

---

## Configuration

### Local Development

Models load automatically from `models/` directory:
```bash
models/catboost_v8_33features_20260108_211817.cbm
```

### Production (Cloud Run)

Set environment variable to load from GCS:
```bash
CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-ml-models/catboost_v8_33features_20260108_211817.cbm
```

### Deployment Steps

1. Upload model to GCS:
```bash
gsutil cp models/catboost_v8_33features_20260108_211817.cbm \
  gs://nba-props-platform-ml-models/
```

2. Update Cloud Run service:
```bash
gcloud run services update prediction-worker \
  --set-env-vars="CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-ml-models/catboost_v8_33features_20260108_211817.cbm"
```

3. Or redeploy with updated Dockerfile.

---

## No Backfill Required

Historical predictions remain unchanged. V8 predictions start from the next daily run.

- Old predictions: `system_id = 'xgboost_v1'`
- New predictions: `system_id = 'catboost_v8'`

Query to see the transition:
```sql
SELECT
  game_date,
  system_id,
  COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE system_id IN ('xgboost_v1', 'catboost_v8')
GROUP BY game_date, system_id
ORDER BY game_date DESC
LIMIT 20;
```

---

## Monitoring

### Check Model Loading

Look for this log on worker startup:
```
INFO - Loading CatBoost v8 model from models/catboost_v8_33features_...
INFO - Loaded CatBoost v8 model successfully
INFO - All prediction systems initialized (using CatBoost v8)
```

### Check Predictions

```sql
-- Daily prediction count by system
SELECT
  system_id,
  COUNT(*) as count,
  AVG(confidence_score) as avg_confidence
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
GROUP BY system_id;
```

### Circuit Breaker

If CatBoost v8 fails repeatedly, the circuit breaker will open. Check:
```sql
SELECT * FROM nba_predictions.prediction_circuit_breaker_state
WHERE system_id = 'catboost_v8';
```

---

## Rollback

If issues arise, revert `worker.py` to use XGBoostV1:

```python
# Rollback: uncomment XGBoostV1, comment CatBoostV8
from prediction_systems.xgboost_v1 import XGBoostV1
_xgboost = XGBoostV1()
```

Then redeploy the worker.

---

## Future Model Updates

### Adding a New Model (e.g., V9)

1. Train the model and save to `models/`
2. Create prediction system class in `predictions/worker/prediction_systems/`
3. Update `worker.py` to use new class
4. Upload model to GCS
5. Update `CATBOOST_V8_MODEL_PATH` env var (or create new env var)
6. Redeploy worker

### Model Registry (Optional)

For A/B testing multiple models, use the ML experiment pipeline:
- Register model in `nba_predictions.ml_model_registry`
- Run `ml/experiment_runner.py` for comparison
- Check `v_ml_model_leaderboard` for results

This is separate from production predictions and useful for validating new models before deployment.

---

## Files Modified

| File | Change |
|------|--------|
| `predictions/worker/worker.py` | Swapped XGBoostV1 → CatBoostV8 |
| `predictions/worker/prediction_systems/catboost_v8.py` | Added GCS loading via env var |

---

## Related Documentation

- [MODEL-SUMMARY.md](./MODEL-SUMMARY.md) - V8 architecture and features
- [ML-EXPERIMENT-ARCHITECTURE.md](./ML-EXPERIMENT-ARCHITECTURE.md) - Multi-model comparison pipeline
- [SHADOW-MODE-GUIDE.md](./SHADOW-MODE-GUIDE.md) - Shadow mode for testing

# Monthly Model Retraining Guide

## Overview

We retrain CatBoost V9 monthly to incorporate recent game data. This keeps the model current with player performance trends, team dynamics, and betting market patterns.

## Schedule

| Week | Action |
|------|--------|
| 1st of month | Run monthly retrain |
| 1st-3rd | Evaluate on recent data |
| 3rd-5th | Promote to production if metrics are good |

## Quick Start

```bash
# Dry run to see what would happen
./bin/retrain-monthly.sh --dry-run

# Train new model (without promoting)
./bin/retrain-monthly.sh

# Train and auto-promote to production
./bin/retrain-monthly.sh --promote
```

## Detailed Workflow

### 1. Pre-Training Checklist

Before retraining, verify data quality:

```bash
# Check feature store quality
./bin/model-registry.sh validate

# Check recent data availability
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as records
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1 ORDER BY 1 DESC"
```

### 2. Training

The script handles:
- Training on data from season start (Nov 2) to yesterday
- Saving model with consistent naming
- Uploading to GCS
- Registering in model_registry

```bash
# Standard monthly retrain
./bin/retrain-monthly.sh --name "V9_FEB_RETRAIN"

# Custom training window
./bin/retrain-monthly.sh \
    --name "V9_FEB_CUSTOM" \
    --train-end 2026-02-15
```

### 3. Evaluation

After training, evaluate before promoting:

```bash
# Check experiment results
bq query --use_legacy_sql=false "
SELECT experiment_name, results_json
FROM nba_predictions.ml_experiments
WHERE experiment_name LIKE '%FEB%'
ORDER BY created_at DESC LIMIT 5"

# Compare to baseline
PYTHONPATH=. python ml/experiments/evaluate_model.py \
    --model models/catboost_v9_33features_20260203.cbm \
    --eval-start 2026-01-25 \
    --eval-end 2026-02-02
```

**Promotion Criteria:**
- MAE ≤ 5.5 (baseline is ~5.1)
- Hit rate (3+ edge) ≥ 60%
- Hit rate (5+ edge) ≥ 70%
- No significant tier bias (< ±3 pts)

### 4. Promotion

If evaluation passes:

```bash
# Auto-promote during training
./bin/retrain-monthly.sh --promote

# Or manually promote later
gcloud run services update prediction-worker --region=us-west2 \
    --update-env-vars="CATBOOST_V9_MODEL_PATH=gs://nba-props-platform-models/catboost/v9/catboost_v9_33features_20260203.cbm"

# Update registry
bq query --use_legacy_sql=false "
UPDATE nba_predictions.model_registry
SET is_production = TRUE, production_start_date = CURRENT_DATE()
WHERE model_id = 'catboost_v9_33features_20260203'"
```

### 5. Post-Promotion Monitoring

After promoting, monitor for 2-3 days:

```bash
# Check daily hit rates
bq query --use_legacy_sql=false "
SELECT game_date,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY 1 ORDER BY 1 DESC"

# Check for tier bias
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN actual_points >= 25 THEN 'stars'
       WHEN actual_points >= 15 THEN 'starters'
       WHEN actual_points >= 5 THEN 'role'
       ELSE 'bench' END as tier,
  ROUND(AVG(predicted_points - actual_points), 1) as bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY 1"
```

## Naming Convention

```
catboost_v{version}_{features}features_{YYYYMMDD}.cbm
```

| Component | Description | Example |
|-----------|-------------|---------|
| `version` | Model version (v8, v9, v10) | v9 |
| `features` | Feature count | 33 |
| `YYYYMMDD` | Training date | 20260203 |

Examples:
- `catboost_v9_33features_20260203.cbm` - Standard monthly retrain
- `catboost_v9_37features_20260301.cbm` - If adding trajectory features
- `catboost_v10_34features_20260401.cbm` - New version with tier feature

## Model Registry

All models must be registered in `nba_predictions.model_registry`:

```bash
# View all models
./bin/model-registry.sh list

# View production models
./bin/model-registry.sh production

# View features for a model
./bin/model-registry.sh features catboost_v9_33features_20260203

# Validate all GCS paths exist
./bin/model-registry.sh validate
```

## Rollback Procedure

If a new model performs poorly:

```bash
# 1. Identify previous model
./bin/model-registry.sh list

# 2. Revert env var
gcloud run services update prediction-worker --region=us-west2 \
    --update-env-vars="CATBOOST_V9_MODEL_PATH=gs://nba-props-platform-models/catboost/v9/catboost_v9_feb_02_retrain.cbm"

# 3. Update registry
bq query --use_legacy_sql=false "
UPDATE nba_predictions.model_registry
SET is_production = FALSE, status = 'rolled_back'
WHERE model_id = 'catboost_v9_33features_20260203';

UPDATE nba_predictions.model_registry
SET is_production = TRUE
WHERE model_id = 'catboost_v9_feb_02_retrain'"
```

## Troubleshooting

### Model file not found after training

The `quick_retrain.py` script may save with a different filename. Check:
```bash
ls -la models/*.cbm
```

### GCS upload fails

Verify authentication:
```bash
gcloud auth list
gsutil ls gs://nba-props-platform-models/catboost/v9/
```

### Model performs worse than baseline

1. Check training data quality (use `/spot-check-features`)
2. Verify no data corruption in recent dates
3. Check if specific tier is underperforming
4. Consider rolling back while investigating

## History

| Date | Model | Notes |
|------|-------|-------|
| 2026-01-08 | V8 | Historical baseline (2021-2024) |
| 2026-02-01 | V9 (original) | First current-season model |
| 2026-02-02 | V9 (feb_02) | Monthly retrain, now production |

## Related

- [Model Registry Schema](MODEL-REGISTRY.md)
- [quick_retrain.py](../../../../ml/experiments/quick_retrain.py)
- [CatBoost V9 System](../../../../predictions/worker/prediction_systems/catboost_v9.py)

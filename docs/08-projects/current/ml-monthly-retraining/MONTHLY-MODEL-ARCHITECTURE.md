# Monthly Model Architecture

**Session 68 (2026-02-01)**: Configurable monthly retraining system for continuous model improvement.

## Overview

The monthly model system allows running multiple CatBoost models in parallel, each trained on progressively expanding current-season data. Each model:

1. **Runs alongside existing systems** (V8, V9, ensembles)
2. **Has its own system_id** for independent tracking
3. **Can be enabled/disabled** via configuration
4. **Easy to add** - just train and configure

This enables:
- **Shadow testing** new monthly models without disrupting production
- **A/B comparison** of different training windows
- **Gradual rollout** of improved models
- **Historical analysis** of model performance over time

## February 2026 Retrain Results

**Model**: `catboost_v9_2026_02`

| Metric | Value | vs V8 Baseline | Status |
|--------|-------|----------------|--------|
| **MAE** | 5.0753 | -0.2847 (5.3% better) | ✅ |
| **Overall Hit Rate** | 50.84% | +0.60% | ✅ |
| **High-Edge Hit Rate (5+)** | 68.75% | +5.95% | ✅ (n=16, low sample) |
| **Premium Hit Rate (~92+/3+)** | 47.83% | -30.67% | ❌ (n=23, low sample) |

**Training**:
- Dates: 2025-11-02 to 2026-01-24 (84 days)
- Samples: 12,477

**Evaluation**:
- Dates: 2026-01-25 to 2026-01-31 (7 days)
- Samples: 433

**Recommendation**: ✅ Beats V8 on MAE and overall hit rate. Premium/high-edge sample sizes too small for statistical reliability (need 50+ bets). Deploy in shadow mode for full evaluation.

**Note**: 7-day eval window is intentionally small for monthly retraining. Filtered hit rates (premium, high-edge) are unreliable with low sample sizes. Focus on MAE and overall hit rate for monthly evaluation.

## Architecture

```
predictions/worker/
├── prediction_systems/
│   ├── catboost_v8.py           # V8 model (historical training)
│   ├── catboost_v9.py           # V9 model (current season)
│   ├── catboost_monthly.py      # Monthly model system (NEW)
│   └── ...
└── worker.py                     # Loads and runs all models

models/
├── catboost_v9_2026_02.cbm      # February monthly model
└── ...
```

### How It Works

1. **Configuration** (`catboost_monthly.py`):
   ```python
   MONTHLY_MODELS = {
       "catboost_v9_2026_02": {
           "model_path": "models/catboost_v9_2026_02.cbm",
           "train_start": "2025-11-02",
           "train_end": "2026-01-24",
           "enabled": True,
       }
   }
   ```

2. **Worker loads enabled models** (`worker.py`):
   ```python
   from prediction_systems.catboost_monthly import get_enabled_monthly_models
   _monthly_models = get_enabled_monthly_models()
   ```

3. **Each model generates predictions** with its own `system_id`:
   ```python
   for monthly_model in _monthly_models:
       result = monthly_model.predict(player_lookup, features, betting_line)
       # Result has system_id = "catboost_v9_2026_02"
   ```

4. **Predictions written to BigQuery** with separate `system_id` for tracking

## Adding a New Monthly Model

### Step 1: Train the Model

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_2026_03_MONTHLY" \
    --train-start 2025-11-02 --train-end 2026-02-28 \
    --eval-start 2026-03-01 --eval-end 2026-03-07 \
    --line-source draftkings \
    --hypothesis "March monthly model - expanding training window"
```

**Best Practices**:
- **Train start**: Keep consistent (e.g., 2025-11-02 season start)
- **Train end**: Last day of previous month
- **Eval start**: First day of new month
- **Eval end**: 7 days later (small sample for quick validation)
- **Line source**: Use `draftkings` (matches production)

### Step 2: Rename the Model File

```bash
mv models/catboost_retrain_V9_2026_03_MONTHLY_*.cbm models/catboost_v9_2026_03.cbm
```

**Naming convention**: `catboost_v9_YYYY_MM.cbm`

### Step 3: Add Configuration Entry

Edit `predictions/worker/prediction_systems/catboost_monthly.py`:

```python
MONTHLY_MODELS = {
    "catboost_v9_2026_02": {
        "model_path": "models/catboost_v9_2026_02.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-01-24",
        "eval_start": "2026-01-25",
        "eval_end": "2026-01-31",
        "mae": 5.0753,
        "hit_rate_overall": 50.84,
        "enabled": True,
        "description": "February 2026 monthly model - 84 day training window",
    },
    "catboost_v9_2026_03": {  # NEW ENTRY
        "model_path": "models/catboost_v9_2026_03.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-02-28",
        "eval_start": "2026-03-01",
        "eval_end": "2026-03-07",
        "mae": 4.95,  # Fill in from training results
        "hit_rate_overall": 52.1,
        "enabled": True,  # Set to False to disable
        "description": "March 2026 monthly model - 118 day training window",
    },
}
```

### Step 4: Verify Locally

```bash
python verify_monthly_models.py
```

Should show:
- ✅ Monthly models loaded successfully
- ✅ All models can generate predictions
- ✅ Worker integration verified

### Step 5: Commit and Deploy

```bash
# Commit model file and configuration
git add models/catboost_v9_2026_03.cbm
git add predictions/worker/prediction_systems/catboost_monthly.py
git commit -m "feat: Add March 2026 monthly model (MAE 4.95, HR 52.1%)"

# Deploy worker
./bin/deploy-service.sh prediction-worker

# Verify deployment
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"
```

### Step 6: Monitor and Validate

```sql
-- Check monthly model predictions (first 24 hours)
SELECT
  system_id,
  COUNT(*) as predictions,
  ROUND(AVG(confidence_score), 2) as avg_confidence,
  ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_edge
FROM nba_predictions.player_prop_predictions
WHERE system_id LIKE 'catboost_v9_2026_%'
  AND game_date >= CURRENT_DATE()
GROUP BY system_id
ORDER BY system_id
```

**Expected output**:
```
system_id              predictions  avg_confidence  avg_edge
catboost_v9_2026_02    450          87.5            3.2
catboost_v9_2026_03    450          88.1            3.4
```

## Disabling a Model

Set `enabled: False` in configuration:

```python
"catboost_v9_2026_02": {
    # ... config ...
    "enabled": False,  # Model won't load
}
```

Commit and deploy:
```bash
git add predictions/worker/prediction_systems/catboost_monthly.py
git commit -m "chore: Disable Feb 2026 monthly model"
./bin/deploy-service.sh prediction-worker
```

## Comparing Models

### Hit Rate Comparison

```sql
-- Compare monthly models (last 7 days)
SELECT
  system_id,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae
FROM nba_predictions.prediction_accuracy
WHERE system_id LIKE 'catboost_v9_2026_%'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND prediction_correct IS NOT NULL
GROUP BY system_id
ORDER BY hit_rate DESC
```

### High-Edge Performance

```sql
-- Compare on high-edge picks (5+ edge)
SELECT
  system_id,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id LIKE 'catboost_v9_2026_%'
  AND ABS(predicted_points - line_value) >= 5
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND prediction_correct IS NOT NULL
GROUP BY system_id
ORDER BY hit_rate DESC
```

## Troubleshooting

### Model File Not Found

**Error**: `ModelLoadError: Monthly model file not found`

**Cause**: Model file missing or wrong path in configuration

**Fix**:
```bash
# Check model file exists
ls -lh models/catboost_v9_2026_*.cbm

# Verify path in configuration matches
grep "model_path" predictions/worker/prediction_systems/catboost_monthly.py
```

### Model Not Producing Predictions

**Error**: No predictions with monthly model system_id in BigQuery

**Check**:
1. Model enabled in configuration?
2. Worker deployed with latest code?
3. Worker logs show model loading?

```bash
# Check worker logs for monthly model loading
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="prediction-worker"
  AND textPayload=~"monthly model"' \
  --limit=20 --freshness=1h
```

### Low Hit Rate

**Investigation**:
1. Check training data quality (missing features? wrong features?)
2. Compare to V8/V9 baseline on same period
3. Review training script output for warnings
4. Validate feature store completeness for training period

## Future Improvements

1. **Automated retraining**: GitHub Actions workflow on 1st of month
2. **Auto-enable best model**: Compare monthly models, auto-enable champion
3. **Production switchover**: Promote best monthly model to production system_id
4. **GCS model storage**: Upload models to GCS, load from there in worker
5. **Feature versioning**: Track which feature version each model uses

## Files Modified

| File | Change |
|------|--------|
| `predictions/worker/prediction_systems/catboost_monthly.py` | **NEW** - Monthly model system |
| `predictions/worker/worker.py` | Added monthly model loading and prediction loop |
| `models/catboost_v9_2026_02.cbm` | **NEW** - February 2026 model |
| `verify_monthly_models.py` | **NEW** - Verification script |

## References

- Training script: `ml/experiments/quick_retrain.py`
- V8 baseline: `predictions/worker/prediction_systems/catboost_v8.py`
- V9 model: `predictions/worker/prediction_systems/catboost_v9.py`
- Session 68 handoff: `docs/09-handoff/2026-02-01-SESSION-68-*.md`

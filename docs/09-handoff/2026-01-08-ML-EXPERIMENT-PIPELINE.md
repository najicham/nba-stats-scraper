# ML Experiment Pipeline Implementation

**Date**: January 8, 2026
**Status**: COMPLETE - Ready for daily use

---

## What Was Built

A complete ML experimentation pipeline that runs multiple models side-by-side without affecting production.

### Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌───────────────────┐
│  Model Registry │────▶│ Experiment Runner│────▶│ ml_model_predictions│
│   (BigQuery)    │     │   (Python)       │     │    (BigQuery)      │
└─────────────────┘     └──────────────────┘     └───────────────────┘
                                                          │
                                                          ▼
                                                 ┌───────────────────┐
                                                 │ Comparison Views  │
                                                 │ & Leaderboard     │
                                                 └───────────────────┘
```

### Files Created

| File | Purpose |
|------|---------|
| `ml/model_loader.py` | Dynamic loading for catboost/xgboost/lightgbm |
| `ml/experiment_runner.py` | Main runner - executes all enabled models |
| `ml/update_experiment_results.py` | Fills actual results after games |
| `schemas/bigquery/predictions/11_ml_model_registry.sql` | Registry table |
| `schemas/bigquery/predictions/12_ml_model_predictions.sql` | Predictions + views |
| `predictions/shared/injury_filter.py` | Checks injury status before predictions |

### BigQuery Tables

| Table | Purpose |
|-------|---------|
| `nba_predictions.ml_model_registry` | Model configuration (enabled, path, features) |
| `nba_predictions.ml_model_predictions` | All experiment predictions |
| `nba_predictions.v_ml_model_daily_performance` | Daily accuracy view |
| `nba_predictions.v_ml_model_leaderboard` | All-time rankings view |

---

## Current State

### Models Registered

```
catboost_v8: enabled=TRUE, test_mae=3.40
```

### Test Run Results

```
Date: 2026-01-07
Players: 256
Predictions: 256 (all successful)
Status: Written to BigQuery
```

---

## Daily Usage

### 1. Run Experiments (Before Games)

```bash
# Run for today
PYTHONPATH=. python ml/experiment_runner.py

# Run for specific date
PYTHONPATH=. python ml/experiment_runner.py --date 2026-01-10
```

### 2. Update Results (After Games, Wait 90+ min after predictions)

```bash
PYTHONPATH=. python ml/update_experiment_results.py --date 2026-01-07
```

**Note**: BigQuery streaming buffer requires ~90 min wait before UPDATE works.

### 3. Check Results

```sql
-- Daily performance
SELECT * FROM nba_predictions.v_ml_model_daily_performance
WHERE game_date = '2026-01-07';

-- Leaderboard
SELECT model_id, mae, bet_accuracy, graded_predictions
FROM nba_predictions.v_ml_model_leaderboard;
```

---

## Adding New Models

**No code changes required!**

```sql
INSERT INTO nba_predictions.ml_model_registry (
    model_id, model_name, model_type, model_version,
    model_path, model_format, feature_version, feature_count,
    test_mae, enabled, is_production, is_baseline,
    created_at, notes
) VALUES (
    'catboost_v9',
    'CatBoost V9',
    'catboost',
    'v9',
    'models/catboost_v9.cbm',
    'cbm',
    'v9_36features',
    36,
    3.35,
    TRUE,   -- Will run in next experiment
    FALSE,
    FALSE,
    CURRENT_TIMESTAMP(),
    'V9 with new features'
);
```

---

## Key Design Decisions

1. **Separate from production** - `ml_model_predictions` is isolated from `player_prop_predictions`
2. **Registry pattern** - Add/remove models via SQL, no deploys
3. **Dynamic model loading** - Supports catboost, xgboost, lightgbm
4. **Injury filtering** - Skips OUT players, flags QUESTIONABLE

---

## Known Issues

1. **Streaming buffer** - Wait 90+ min after predictions before running `update_experiment_results.py`
2. **Local models only** - Currently loads from `models/` directory. For Cloud Run, upload to GCS and update `model_path`

---

## Next Steps

1. **Set up cron jobs** for daily automation
2. **Upload models to GCS** for production use
3. **Add more models** (v9, baseline mock) to compare
4. **Integrate with production** when v8 proves itself

---

## Documentation

- Full architecture: `docs/08-projects/current/ml-model-v8-deployment/ML-EXPERIMENT-ARCHITECTURE.md`
- Project overview: `docs/08-projects/current/ml-model-v8-deployment/README.md`
- Model details: `docs/08-projects/current/ml-model-v8-deployment/MODEL-SUMMARY.md`

---

## Quick Reference

```bash
# Run experiments
PYTHONPATH=. python ml/experiment_runner.py

# Check registry
bq query "SELECT model_id, enabled, test_mae FROM nba_predictions.ml_model_registry"

# Check predictions
bq query "SELECT COUNT(*) FROM nba_predictions.ml_model_predictions WHERE game_date = '2026-01-07'"

# Check leaderboard (after results updated)
bq query "SELECT * FROM nba_predictions.v_ml_model_leaderboard"
```

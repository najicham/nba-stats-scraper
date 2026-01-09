# ML Experimentation Architecture

## Overview

The ML experimentation pipeline allows running multiple ML models side-by-side for comparison without affecting production predictions.

```
┌─────────────────────────────────────────────────────────────────────┐
│                      ML EXPERIMENTATION PIPELINE                     │
│                                                                      │
│  ┌──────────────────┐    ┌──────────────────┐    ┌───────────────┐ │
│  │  Model Registry  │───▶│ Experiment Runner│───▶│  Predictions  │ │
│  │   (BigQuery)     │    │  (Python script) │    │   (BigQuery)  │ │
│  └──────────────────┘    └──────────────────┘    └───────────────┘ │
│          │                        │                      │          │
│          ▼                        ▼                      ▼          │
│  ┌──────────────────┐    ┌──────────────────┐    ┌───────────────┐ │
│  │ Add new models   │    │ Runs all enabled │    │  Comparison   │ │
│  │ without code     │    │ models daily     │    │  views/reports│ │
│  └──────────────────┘    └──────────────────┘    └───────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Model Registry (`nba_predictions.ml_model_registry`)

Tracks all ML models available for experimentation.

| Field | Description |
|-------|-------------|
| `model_id` | Unique identifier (e.g., 'catboost_v8') |
| `model_type` | Framework: 'catboost', 'xgboost', 'lightgbm' |
| `model_path` | Path to model file (local or GCS) |
| `feature_count` | Number of features required |
| `enabled` | TRUE to run in experiments |
| `is_production` | TRUE if this is the production model |
| `is_baseline` | TRUE if used as baseline for comparison |
| `test_mae` | MAE from training evaluation |

### 2. Predictions Table (`nba_predictions.ml_model_predictions`)

Stores predictions from all experimental models.

| Field | Description |
|-------|-------------|
| `prediction_id` | Unique prediction UUID |
| `model_id` | Which model made this prediction |
| `player_lookup` | Player identifier |
| `game_date` | Game date (partition key) |
| `predicted_points` | Model's prediction |
| `betting_line` | Vegas prop line |
| `actual_points` | Actual points (filled after game) |
| `prediction_error` | |predicted - actual| |
| `bet_outcome` | 'WIN', 'LOSS', 'PUSH' |
| `beat_baseline` | TRUE if beat baseline model |
| `beat_vegas` | TRUE if closer than Vegas |

### 3. Comparison Views

- **`v_ml_model_daily_performance`** - Daily accuracy by model
- **`v_ml_model_leaderboard`** - All-time model rankings
- **`v_ml_model_head_to_head`** - Direct model comparisons

## Files Created

```
ml/
├── model_loader.py          # Dynamic model loading (catboost, xgboost, etc.)
├── experiment_runner.py     # Main runner script
└── update_experiment_results.py  # Fill in actual results after games

schemas/bigquery/predictions/
├── 11_ml_model_registry.sql     # Registry table schema
└── 12_ml_model_predictions.sql  # Predictions table + views
```

## Usage

### Daily Workflow

```bash
# 1. Run experiments (before games, e.g., 12:00 PM ET)
PYTHONPATH=. python ml/experiment_runner.py

# 2. Update results (after games, e.g., 2:00 AM ET next day)
PYTHONPATH=. python ml/update_experiment_results.py --date 2026-01-08
```

### Adding a New Model

```bash
# 1. Train the model
PYTHONPATH=. python ml/train_final_ensemble_v9.py

# 2. Register in BigQuery
bq query --use_legacy_sql=false "
INSERT INTO nba_predictions.ml_model_registry (
    model_id, model_name, model_type, model_version,
    model_path, model_format,
    feature_version, feature_count,
    test_mae,
    enabled, is_production, is_baseline,
    created_at, notes
) VALUES (
    'catboost_v9',
    'CatBoost V9 with Injury Features',
    'catboost',
    'v9',
    'models/catboost_v9_36features.cbm',
    'cbm',
    'v9_36features',
    36,
    3.35,
    TRUE,   -- enabled for experiments
    FALSE,  -- not production yet
    FALSE,  -- not baseline
    CURRENT_TIMESTAMP(),
    'V9 adds injury features'
)
"

# 3. Next run will automatically pick up the new model
```

### Checking Results

```sql
-- Daily performance
SELECT * FROM nba_predictions.v_ml_model_daily_performance
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
ORDER BY mae ASC;

-- Overall leaderboard
SELECT model_id, mae, bet_accuracy, graded_predictions
FROM nba_predictions.v_ml_model_leaderboard
ORDER BY mae ASC;

-- Head-to-head: v8 vs v9
SELECT *
FROM nba_predictions.v_ml_model_head_to_head
WHERE 'catboost_v8' IN (model_a, model_b)
  AND 'catboost_v9' IN (model_a, model_b);
```

### Promoting a Model to Production

```sql
-- 1. Remove current production flag
UPDATE nba_predictions.ml_model_registry
SET is_production = FALSE, updated_at = CURRENT_TIMESTAMP()
WHERE is_production = TRUE;

-- 2. Set new production model
UPDATE nba_predictions.ml_model_registry
SET is_production = TRUE, updated_at = CURRENT_TIMESTAMP()
WHERE model_id = 'catboost_v9';
```

## Automation (Cron)

```bash
# Run experiments daily at 12:00 PM ET
0 12 * * * cd /path/to/repo && PYTHONPATH=. python ml/experiment_runner.py >> /var/log/ml_experiments.log 2>&1

# Update results daily at 2:00 AM ET
0 2 * * * cd /path/to/repo && PYTHONPATH=. python ml/update_experiment_results.py >> /var/log/ml_results.log 2>&1
```

## Key Design Decisions

### Why Separate from Production?

1. **No risk** - Experiments can't break production predictions
2. **Clean comparison** - All models run on same data simultaneously
3. **Easy rollback** - Just flip `is_production` flag
4. **Historical tracking** - All predictions preserved

### Why Registry Pattern?

1. **No code changes** - Add models via SQL INSERT
2. **Easy enable/disable** - Flip `enabled` flag
3. **Metadata tracking** - Feature requirements, training metrics
4. **Audit trail** - When models were added, by whom

### Why Dynamic Loading?

1. **Multiple frameworks** - CatBoost, XGBoost, LightGBM all supported
2. **Local or GCS** - Works in development and production
3. **Caching** - Models loaded once per run
4. **Graceful failures** - Skip models that fail to load

## Migration to Production

When ready to use a model in the main prediction pipeline:

1. **Verify** - Model consistently beats baseline in experiments
2. **Upload** - Move model file to GCS bucket
3. **Update** - Change `model_path` in registry to GCS path
4. **Promote** - Set `is_production = TRUE`
5. **Integrate** - Update production worker to use production model

## Current Status

| Model | Status | MAE | Enabled |
|-------|--------|-----|---------|
| catboost_v8 | Registered | 3.40 | Yes |

Run `SELECT * FROM nba_predictions.ml_model_registry` to see current state.

# Model Registry

The model registry (`nba_predictions.model_registry`) tracks all ML models, their training data, and deployment status.

## Schema

| Column | Type | Description |
|--------|------|-------------|
| `model_id` | STRING | Unique identifier (e.g., `catboost_v9_33features_20260203`) |
| `model_version` | STRING | Version (v8, v9, v10) |
| `model_type` | STRING | Architecture (catboost, xgboost, ensemble) |
| `gcs_path` | STRING | Full GCS path to model file |
| `feature_count` | INT64 | Number of input features |
| `features_json` | JSON | Array of feature names in order |
| `training_start_date` | DATE | First date of training data |
| `training_end_date` | DATE | Last date of training data |
| `training_samples` | INT64 | Number of training samples |
| `training_config_json` | JSON | Hyperparameters and config |
| `evaluation_mae` | FLOAT64 | Mean Absolute Error |
| `evaluation_hit_rate` | FLOAT64 | Hit rate (all predictions) |
| `evaluation_hit_rate_edge_3plus` | FLOAT64 | Hit rate for edge ≥ 3 |
| `evaluation_hit_rate_edge_5plus` | FLOAT64 | Hit rate for edge ≥ 5 |
| `parent_model_id` | STRING | Model this was derived from |
| `experiment_id` | STRING | Link to ml_experiments |
| `git_commit` | STRING | Git commit when trained |
| `status` | STRING | active, deprecated, testing, archived, rolled_back |
| `is_production` | BOOL | Currently in production |
| `production_start_date` | DATE | When entered production |
| `production_end_date` | DATE | When retired from production |
| `notes` | STRING | Additional notes |
| `created_at` | TIMESTAMP | Registry entry creation time |
| `created_by` | STRING | Who created the entry |

## CLI Tool

```bash
# List all models
./bin/model-registry.sh list

# Show production models only
./bin/model-registry.sh production

# Get details for a specific model
./bin/model-registry.sh info catboost_v9_33features_20260203

# List features with indices
./bin/model-registry.sh features catboost_v9_33features_20260203

# Validate all GCS paths exist
./bin/model-registry.sh validate
```

## Status Values

| Status | Meaning |
|--------|---------|
| `active` | Available for use, not deprecated |
| `testing` | Under evaluation, not yet production-ready |
| `deprecated` | Superseded by newer model |
| `archived` | Historical, not for active use |
| `rolled_back` | Was production, removed due to issues |

## Querying

### Find current production model
```sql
SELECT model_id, gcs_path, production_start_date
FROM nba_predictions.model_registry
WHERE is_production = TRUE
  AND model_version = 'v9'
```

### Get training data range for a model
```sql
SELECT model_id, training_start_date, training_end_date,
       DATE_DIFF(training_end_date, training_start_date, DAY) as training_days
FROM nba_predictions.model_registry
WHERE model_id = 'catboost_v9_33features_20260203'
```

### List all V9 models chronologically
```sql
SELECT model_id, training_end_date, status, is_production
FROM nba_predictions.model_registry
WHERE model_version = 'v9'
ORDER BY training_end_date DESC
```

### Find models with specific feature count
```sql
SELECT model_id, feature_count, status
FROM nba_predictions.model_registry
WHERE feature_count = 37  -- e.g., if looking for trajectory features
```

## Adding a New Model

```sql
INSERT INTO nba_predictions.model_registry (
  model_id, model_version, model_type, gcs_path, feature_count,
  features_json, training_start_date, training_end_date,
  status, is_production, created_at, created_by
) VALUES (
  'catboost_v9_33features_20260301',
  'v9',
  'catboost',
  'gs://nba-props-platform-models/catboost/v9/catboost_v9_33features_20260301.cbm',
  33,
  JSON '["points_avg_last_5", "points_avg_last_10", ...]',
  DATE '2025-11-02',
  DATE '2026-02-28',
  'active',
  FALSE,
  CURRENT_TIMESTAMP(),
  'session_XXX'
);
```

## Features Reference (V9 - 33 features)

| Index | Feature | Description |
|-------|---------|-------------|
| 0 | points_avg_last_5 | 5-game rolling average |
| 1 | points_avg_last_10 | 10-game rolling average |
| 2 | points_avg_season | Season average |
| 3 | points_std_last_10 | 10-game standard deviation |
| 4 | games_in_last_7_days | Recent workload |
| 5 | fatigue_score | Fatigue indicator |
| 6 | shot_zone_mismatch_score | Matchup advantage |
| 7 | pace_score | Pace factor |
| 8 | usage_spike_score | Usage change |
| 9 | rest_advantage | Rest days advantage |
| 10 | injury_risk | Injury risk score |
| 11 | recent_trend | Performance trend |
| 12 | minutes_change | Minutes change |
| 13 | opponent_def_rating | Opponent defense |
| 14 | opponent_pace | Opponent pace |
| 15 | home_away | Home (1) or Away (0) |
| 16 | back_to_back | Back-to-back game |
| 17 | playoff_game | Playoff indicator |
| 18 | pct_paint | Paint scoring % |
| 19 | pct_mid_range | Mid-range % |
| 20 | pct_three | Three-point % |
| 21 | pct_free_throw | Free throw % |
| 22 | team_pace | Team pace |
| 23 | team_off_rating | Team offense rating |
| 24 | team_win_pct | Team win % |
| 25 | vegas_points_line | Vegas line |
| 26 | vegas_opening_line | Opening line |
| 27 | vegas_line_move | Line movement |
| 28 | has_vegas_line | Has Vegas data |
| 29 | avg_points_vs_opponent | Historical vs opponent |
| 30 | games_vs_opponent | Games vs opponent |
| 31 | minutes_avg_last_10 | Minutes average |
| 32 | ppm_avg_last_10 | Points per minute |

## Future Features (33-36, currently unused)

| Index | Feature | Status |
|-------|---------|--------|
| 33 | dnp_rate | In feature store, unused |
| 34 | pts_slope_10g | In feature store, unused |
| 35 | pts_vs_season_zscore | In feature store, unused |
| 36 | breakout_flag | In feature store, unused |

To use these features, update training to use `row[:37]` instead of `row[:33]`.

# Model Training Runbook

This runbook documents the end-to-end process for training, evaluating, and deploying ML models for sports prop predictions (NBA and MLB).

## Table of Contents

1. [Overview](#overview)
2. [Data Preparation](#data-preparation)
3. [Feature Engineering](#feature-engineering)
4. [Training Scripts and Parameters](#training-scripts-and-parameters)
5. [Evaluation Metrics](#evaluation-metrics)
6. [Model Versioning](#model-versioning)
7. [Shadow Mode / A/B Testing](#shadow-mode--ab-testing)
8. [Model Deployment](#model-deployment)
9. [Quick Reference Commands](#quick-reference-commands)

---

## Overview

### ML Stack

| Framework | Use Case | File Format |
|-----------|----------|-------------|
| CatBoost | Primary production model (NBA V8) | `.cbm` |
| XGBoost | Baseline and ensemble member | `.json` |
| LightGBM | Ensemble member | `.txt` |
| Ridge | Meta-learner for stacked ensemble | N/A (in-memory) |

### Model Evolution

| Version | MAE | Features | Notes |
|---------|-----|----------|-------|
| Mock V1 | 4.80 | 25 | Rule-based baseline |
| XGBoost V6 | 4.14 | 25 | First ML model |
| XGBoost V7 | 3.88 | 31 | Added Vegas lines |
| CatBoost V8 | 3.40 | 33 | Production (stacked ensemble) |
| Challenger V10 | TBD | 33 | Extended training data |

---

## Data Preparation

### Data Sources

Data is sourced from BigQuery with the following tables:

```sql
-- Feature Store (pre-computed features)
nba-props-platform.nba_predictions.ml_feature_store_v2

-- Player Performance (actuals/targets)
nba-props-platform.nba_analytics.player_game_summary

-- Vegas Lines
nba-props-platform.nba_raw.bettingpros_player_points_props

-- Injury Reports
nba-props-platform.nba_raw.nbac_injury_report
```

### Loading Training Data

Standard pattern for loading data from BigQuery:

```python
from google.cloud import bigquery

PROJECT_ID = "nba-props-platform"
client = bigquery.Client(project=PROJECT_ID)

query = """
SELECT
    mf.player_lookup,
    mf.game_date,
    mf.features,
    pgs.points as actual_points
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
    ON mf.player_lookup = pgs.player_lookup
    AND mf.game_date = pgs.game_date
WHERE mf.game_date BETWEEN '2021-11-01' AND '2024-06-01'
    AND mf.feature_count = 33
    AND ARRAY_LENGTH(mf.features) = 33
    AND pgs.points IS NOT NULL
ORDER BY mf.game_date
"""

df = client.query(query).to_dataframe()
```

### Data Split Strategy

**Chronological split** (no random shuffling - prevents data leakage):

```python
n = len(df)
train_end = int(n * 0.70)  # 70% train
val_end = int(n * 0.85)    # 15% validation

X_train = X.iloc[:train_end]
X_val = X.iloc[train_end:val_end]
X_test = X.iloc[val_end:]  # 15% test (most recent data)
```

### Walk-Forward Validation (MLB)

For robust out-of-sample testing, use walk-forward validation:

```bash
PYTHONPATH=. python scripts/mlb/training/walk_forward_validation.py
```

This trains on months 1-N and tests on month N+1, iterating forward through time.

---

## Feature Engineering

### NBA Features (33 total for V8 model)

Features are pre-computed by the ML Feature Store processor and stored in BigQuery.

#### Base Features (0-24)

| Index | Feature | Description |
|-------|---------|-------------|
| 0 | `points_avg_last_5` | Rolling 5-game scoring average |
| 1 | `points_avg_last_10` | Rolling 10-game scoring average |
| 2 | `points_avg_season` | Season-to-date average |
| 3 | `points_std_last_10` | Scoring volatility (standard deviation) |
| 4 | `games_in_last_7_days` | Schedule density |
| 5 | `fatigue_score` | Composite fatigue indicator |
| 6 | `shot_zone_mismatch_score` | Shot profile vs opponent defense |
| 7 | `pace_score` | Game pace prediction |
| 8 | `usage_spike_score` | Usage rate trending |
| 9 | `rest_advantage` | Days rest differential |
| 10 | `injury_risk` | Injury probability score |
| 11 | `recent_trend` | Performance trending (up/down) |
| 12 | `minutes_change` | Recent minutes volatility |
| 13 | `opponent_def_rating` | Opponent defensive efficiency |
| 14 | `opponent_pace` | Opponent pace factor |
| 15 | `home_away` | Home (1) / Away (0) |
| 16 | `back_to_back` | Second game of B2B (1/0) |
| 17 | `playoff_game` | Playoff indicator (1/0) |
| 18-21 | `pct_paint`, `pct_mid_range`, `pct_three`, `pct_free_throw` | Shot distribution |
| 22-24 | `team_pace`, `team_off_rating`, `team_win_pct` | Team context |

#### V8 Extended Features (25-32)

| Index | Feature | Description | Importance |
|-------|---------|-------------|------------|
| 25 | `vegas_points_line` | Consensus closing line | 10.2% |
| 26 | `vegas_opening_line` | Opening line | - |
| 27 | `vegas_line_move` | Line movement (closing - opening) | - |
| 28 | `has_vegas_line` | Vegas coverage indicator | - |
| 29 | `avg_points_vs_opponent` | Historical avg vs this team | - |
| 30 | `games_vs_opponent` | Sample size for above | - |
| 31 | `minutes_avg_last_10` | Recent playing time | 14.6% |
| 32 | `ppm_avg_last_10` | Points per minute trend | 10.9% |

### Feature Imputation

Missing values are handled with sensible defaults:

```python
# Vegas lines: impute with player's season average
df['vegas_points_line_imp'] = df['vegas_points_line'].fillna(df['player_season_avg'])

# Line movement: impute with 0 (no movement)
df['vegas_line_move_imp'] = df['vegas_line_move'].fillna(0)

# General: impute with median
X = X.fillna(X.median())
```

### MLB Features (21 for V2 model)

Key feature categories for pitcher strikeout predictions:

```python
V2_FEATURES = [
    # Recent performance (5)
    'f00_k_avg_last_3', 'f01_k_avg_last_5', 'f02_k_avg_last_10',
    'f03_k_std_last_10', 'f04_ip_avg_last_5',

    # Season baseline (5)
    'f05_season_k_per_9', 'f06_season_era', 'f07_season_whip',
    'f08_season_games', 'f09_season_k_total',

    # Workload features (5)
    'f20_days_rest', 'f21_games_last_30_days', 'f22_pitch_count_avg',

    # Lineup analysis (3)
    'f25_bottom_up_k_expected', 'f26_lineup_k_vs_hand', 'f33_lineup_weak_spots',

    # Opponent/Park (2)
    'f15_opponent_team_k_rate', 'f17_ballpark_k_factor',
]
```

---

## Training Scripts and Parameters

### NBA Training Scripts

| Script | Purpose | Output |
|--------|---------|--------|
| `ml/train_final_ensemble_v8.py` | Production V8 model | CatBoost + XGBoost + LightGBM stacked |
| `ml/train_final_ensemble_v9.py` | V9 with injury features | 36 features |
| `ml/train_challenger_v10.py` | Challenger with extended data | Latest season included |
| `ml/train_star_specialist_v10.py` | Tier-specific models | Star/Starter/Role/Bench |
| `ml/optuna_optimize_v7.py` | Hyperparameter tuning | Best CatBoost params |

### Running Training

```bash
# Standard training
PYTHONPATH=. python ml/train_final_ensemble_v8.py

# Challenger model (includes latest season)
PYTHONPATH=. python ml/train_challenger_v10.py

# Hyperparameter optimization (50 trials)
PYTHONPATH=. python ml/optuna_optimize_v7.py

# Dry run to check data availability
PYTHONPATH=. python ml/train_challenger_v10.py --dry-run
```

### CatBoost Hyperparameters (Production V8)

```python
cb_params = {
    'depth': 6,
    'learning_rate': 0.07,
    'l2_leaf_reg': 3.8,
    'subsample': 0.72,
    'min_data_in_leaf': 16,
    'iterations': 1000,
    'random_seed': 42,
    'early_stopping_rounds': 50
}
```

### XGBoost Hyperparameters

```python
xgb_params = {
    'max_depth': 6,
    'min_child_weight': 10,
    'learning_rate': 0.03,
    'n_estimators': 1000,
    'subsample': 0.7,
    'colsample_bytree': 0.7,
    'gamma': 0.1,
    'reg_alpha': 0.5,
    'reg_lambda': 5.0,
    'early_stopping_rounds': 50
}
```

### Stacked Ensemble Architecture

The V8 model uses a stacked ensemble with Ridge meta-learner:

```python
# Base models predict on validation set
xgb_val = xgb_model.predict(X_val)
lgb_val = lgb_model.predict(X_val)
cb_val = cb_model.predict(X_val)

# Stack predictions as features
stack_val = np.column_stack([xgb_val, lgb_val, cb_val])

# Train meta-learner
from sklearn.linear_model import Ridge
meta = Ridge(alpha=1.0)
meta.fit(stack_val, y_val)

# Final prediction
stacked_pred = meta.predict(stack_test)
```

### MLB Training Scripts

```bash
# CatBoost V2 model
PYTHONPATH=. python scripts/mlb/training/train_pitcher_strikeouts_v2.py

# Walk-forward validation
PYTHONPATH=. python scripts/mlb/training/walk_forward_validation.py
```

---

## Evaluation Metrics

### Primary Metrics

| Metric | Target | Description |
|--------|--------|-------------|
| **MAE** | < 3.5 | Mean Absolute Error (points) |
| **Betting Win Rate** | > 55% | Correct predictions against the line |
| **Train/Test Gap** | < 0.5 | Overfitting indicator |

### Calculating Metrics

```python
from sklearn.metrics import mean_absolute_error, mean_squared_error
import numpy as np

def evaluate_model(y_true, y_pred, name=""):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))

    errors = np.abs(y_true - y_pred)
    within_3 = (errors <= 3).mean() * 100
    within_5 = (errors <= 5).mean() * 100

    print(f"{name} Results:")
    print(f"  MAE:  {mae:.3f} points")
    print(f"  RMSE: {rmse:.3f} points")
    print(f"  Within 3 pts: {within_3:.1f}%")
    print(f"  Within 5 pts: {within_5:.1f}%")

    return mae
```

### Betting Accuracy Calculation

```python
def calculate_betting_accuracy(predictions, lines, actuals):
    """Calculate win rate against betting lines."""
    over_picks = predictions > lines
    under_picks = predictions < lines
    actual_over = actuals > lines

    correct = ((over_picks & actual_over) | (under_picks & ~actual_over))
    win_rate = correct.sum() / len(correct) * 100

    return win_rate
```

### Edge Bucket Analysis

Analyze performance by prediction edge size:

```python
for edge_min, edge_max in [(0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 100)]:
    mask = (np.abs(edge) >= edge_min) & (np.abs(edge) < edge_max)
    bucket_wr = correct[mask].mean() * 100
    print(f"Edge {edge_min}-{edge_max}: {mask.sum()} picks, {bucket_wr:.1f}% win rate")
```

### Feature Importance Analysis

```python
# CatBoost feature importance
importance = cb_model.get_feature_importance()
feat_imp = pd.DataFrame({
    'feature': feature_names,
    'importance': importance
}).sort_values('importance', ascending=False)

print("Top 10 Features:")
for i, (_, row) in enumerate(feat_imp.head(10).iterrows(), 1):
    print(f"{i}. {row['feature']}: {row['importance']:.1f}%")
```

---

## Model Versioning

### Model Registry

Models are tracked in BigQuery:

```sql
-- View registered models
SELECT model_id, model_name, test_mae, is_production, enabled
FROM `nba-props-platform.nba_predictions.ml_model_registry`
ORDER BY test_mae ASC;
```

### Registering a New Model

```sql
INSERT INTO `nba-props-platform.nba_predictions.ml_model_registry` VALUES (
  'catboost_v10',                           -- model_id
  'CatBoost V10 Challenger',                -- model_name
  'catboost',                               -- model_type
  'v10',                                    -- model_version
  'gs://nba-props-platform-ml-models/catboost_v10.cbm',  -- model_path
  'cbm',                                    -- model_format
  'v10_33features',                         -- feature_version
  33,                                       -- feature_count
  JSON '[...]',                             -- feature_list
  3.15,                                     -- training_mae
  3.20,                                     -- validation_mae
  3.35,                                     -- test_mae
  85000,                                    -- training_samples
  '2021-11-01',                             -- training_period_start
  '2026-01-15',                             -- training_period_end
  TRUE,                                     -- enabled (for experimentation)
  FALSE,                                    -- is_production
  FALSE,                                    -- is_baseline
  CURRENT_TIMESTAMP(),
  'ml_training_session',
  NULL,
  'Challenger with 2024-25 season data',
  JSON '{"depth": 6, "learning_rate": 0.07}',
  'ml/train_challenger_v10.py'
);
```

### Model File Storage

Models are saved locally and optionally uploaded to GCS:

```bash
# Local storage
models/
  catboost_v8_33features_20260108_211817.cbm
  ensemble_v8_20260108_211817_metadata.json
  xgboost_v10_33features_20260115_143022.json
  lightgbm_v10_33features_20260115_143022.txt

# GCS upload
gsutil cp models/catboost_v10.cbm gs://nba-props-platform-ml-models/
gsutil cp models/catboost_v10_metadata.json gs://nba-props-platform-ml-models/
```

### Metadata Schema

Each model should have accompanying metadata JSON:

```json
{
  "model_id": "catboost_v10_33features_20260115",
  "version": "v10",
  "model_type": "challenger",
  "timestamp": "20260115_143022",
  "training_date_range": {
    "start": "2021-11-01",
    "end": "2026-01-14"
  },
  "features": ["points_avg_last_5", "..."],
  "feature_count": 33,
  "training_samples": 85000,
  "results": {
    "XGBoost": {"mae": 3.42},
    "LightGBM": {"mae": 3.38},
    "CatBoost": {"mae": 3.35},
    "Stacked": {"mae": 3.32}
  },
  "best_model": "Stacked",
  "best_mae": 3.32,
  "champion_comparison": {
    "champion_mae": 3.404,
    "improvement_pct": 2.5
  }
}
```

---

## Shadow Mode / A/B Testing

### Concept

Shadow mode runs challenger models alongside the production champion without affecting real predictions. This enables safe comparison on live data.

### Running Shadow Mode

```bash
# Run for today
PYTHONPATH=. python predictions/shadow_mode_runner.py

# Run for specific date
PYTHONPATH=. python predictions/shadow_mode_runner.py --date 2026-01-15

# Dry run (no BigQuery writes)
PYTHONPATH=. python predictions/shadow_mode_runner.py --dry-run
```

### Shadow Mode Output

Results are stored in BigQuery for analysis:

```sql
-- Compare champion vs challenger
SELECT
    game_date,
    COUNT(*) as predictions,
    AVG(ABS(mock_predicted - actual_points)) as mock_mae,
    AVG(ABS(v8_predicted - actual_points)) as v8_mae,
    COUNTIF(mock_recommendation = v8_recommendation) / COUNT(*) as agreement_rate
FROM `nba-props-platform.nba_predictions.shadow_mode_predictions` sp
JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
    ON sp.player_lookup = pgs.player_lookup
    AND sp.game_date = pgs.game_date
WHERE sp.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
```

### Champion vs Challenger Comparison

```bash
# Compare models on same test set
PYTHONPATH=. python ml/compare_champion_challenger.py --days 14
```

### Promotion Criteria

A challenger model should be promoted when it meets these criteria:

| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| MAE improvement | >= 0.2 points | Meaningful accuracy gain |
| Win rate advantage | >= 3% | Betting edge improvement |
| Sample size | >= 100 games | Statistical significance |
| Head-to-head wins | > 50% | Consistent improvement |

```python
# From compare_champion_challenger.py
criteria_met = 0

if mae_improvement >= 5.9:  # 0.2pt on ~3.4 MAE
    criteria_met += 1

if win_rate_advantage >= 3:
    criteria_met += 1

if sample_size >= 100:
    criteria_met += 1

recommend = "PROMOTE" if criteria_met >= 2 else "KEEP CHAMPION"
```

---

## Model Deployment

### Deployment Workflow

1. **Train model locally**
   ```bash
   PYTHONPATH=. python ml/train_challenger_v10.py
   ```

2. **Upload to GCS**
   ```bash
   gsutil cp models/catboost_v10.cbm gs://nba-props-platform-ml-models/
   ```

3. **Register in model registry**
   ```sql
   INSERT INTO nba_predictions.ml_model_registry ...
   SET enabled = TRUE, is_production = FALSE
   ```

4. **Run shadow mode** (7+ days)
   ```bash
   PYTHONPATH=. python predictions/shadow_mode_runner.py
   ```

5. **Compare results**
   ```bash
   PYTHONPATH=. python ml/compare_champion_challenger.py --days 7
   ```

6. **Promote if criteria met**
   ```sql
   -- Demote current champion
   UPDATE nba_predictions.ml_model_registry
   SET is_production = FALSE
   WHERE is_production = TRUE;

   -- Promote challenger
   UPDATE nba_predictions.ml_model_registry
   SET is_production = TRUE
   WHERE model_id = 'catboost_v10';
   ```

7. **Update environment variable**
   ```bash
   # In Cloud Run or production config
   CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-ml-models/catboost_v10.cbm
   ```

### Production Loading

The prediction system loads models from GCS:

```python
# Environment variable controls production model
gcs_path = os.environ.get('CATBOOST_V8_MODEL_PATH')

# Fallback to local models directory
if not gcs_path:
    model_files = list(Path("models").glob("catboost_v8_33features_*.cbm"))
    model_path = sorted(model_files)[-1]  # Most recent
```

### Rollback Procedure

If a new model underperforms in production:

1. Update environment variable to previous model
2. Update registry to demote new model
3. Investigate via shadow mode data

```sql
-- Emergency rollback
UPDATE nba_predictions.ml_model_registry
SET is_production = TRUE, enabled = TRUE
WHERE model_id = 'catboost_v8';

UPDATE nba_predictions.ml_model_registry
SET is_production = FALSE, notes = 'Rolled back due to underperformance'
WHERE model_id = 'catboost_v10';
```

---

## Quick Reference Commands

### Training Commands

```bash
# NBA - Train V8 ensemble
PYTHONPATH=. python ml/train_final_ensemble_v8.py

# NBA - Train challenger
PYTHONPATH=. python ml/train_challenger_v10.py

# NBA - Hyperparameter tuning
PYTHONPATH=. python ml/optuna_optimize_v7.py

# MLB - Train strikeout model
PYTHONPATH=. python scripts/mlb/training/train_pitcher_strikeouts_v2.py

# MLB - Walk-forward validation
PYTHONPATH=. python scripts/mlb/training/walk_forward_validation.py
```

### Evaluation Commands

```bash
# Compare champion vs challenger
PYTHONPATH=. python ml/compare_champion_challenger.py --days 14

# Validate on current season
PYTHONPATH=. python ml/validate_v8_2024_25.py

# Calculate betting accuracy
PYTHONPATH=. python ml/calculate_betting_accuracy.py
```

### Shadow Mode Commands

```bash
# Run shadow predictions
PYTHONPATH=. python predictions/shadow_mode_runner.py

# Generate shadow mode report
PYTHONPATH=. python predictions/shadow_mode_report.py
```

### Experiment Runner

```bash
# Run all enabled models
PYTHONPATH=. python ml/experiment_runner.py

# Run specific model
PYTHONPATH=. python ml/experiment_runner.py --model catboost_v10

# Dry run
PYTHONPATH=. python ml/experiment_runner.py --dry-run
```

### BigQuery Queries

```sql
-- Current production model
SELECT * FROM nba_predictions.ml_model_registry WHERE is_production = TRUE;

-- All enabled models
SELECT model_id, test_mae, enabled, is_production
FROM nba_predictions.ml_model_registry
WHERE enabled = TRUE;

-- Model prediction comparison
SELECT
    model_id,
    COUNT(*) as predictions,
    AVG(ABS(predicted_points - actual_points)) as mae
FROM nba_predictions.ml_model_predictions mp
JOIN nba_analytics.player_game_summary pgs USING (player_lookup, game_date)
WHERE mp.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY model_id;
```

---

## Troubleshooting

### Common Issues

**Model won't load:**
- Check GCS path is correct
- Verify catboost/xgboost library is installed
- Check file format matches model type

**Features don't match:**
- Verify feature_count matches model expectations (25 vs 33)
- Check feature_version in feature store
- Ensure imputation is applied consistently

**MAE suddenly worse:**
- Check for data quality issues in feature store
- Verify Vegas line coverage
- Look for missing injury data

**Shadow mode disagreement high:**
- This is expected when models differ significantly
- Focus on which model has better MAE/win rate
- High disagreement with similar accuracy = different strategies

---

*Last updated: January 2026*
*Maintained by: ML Team*

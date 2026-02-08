#!/usr/bin/env python3
"""
Optuna Hyperparameter Optimization for v7 Features

Quick optimization targeting CatBoost (best individual model).

Usage:
    PYTHONPATH=. python ml/optuna_optimize_v7.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import optuna
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
import catboost as cb
import json
from datetime import datetime

optuna.logging.set_verbosity(optuna.logging.WARNING)

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models")

print("=" * 80)
print(" OPTUNA HYPERPARAMETER OPTIMIZATION")
print("=" * 80)
print()

# Load data (same as before)
print("Loading data...")
client = bigquery.Client(project=PROJECT_ID)

query = """
WITH
feature_data AS (
  SELECT mf.player_lookup, mf.game_date, mf.features, mf.opponent_team_abbr
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
  WHERE mf.game_date BETWEEN '2021-11-01' AND '2024-06-01'
    AND mf.feature_count = 25 AND ARRAY_LENGTH(mf.features) = 25
),
vegas_lines AS (
  SELECT game_date, player_lookup, points_line as vegas_points_line,
         opening_line as vegas_opening_line, (points_line - opening_line) as vegas_line_move
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE bookmaker = 'BettingPros Consensus' AND bet_side = 'over'
    AND game_date BETWEEN '2021-11-01' AND '2024-06-01'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup ORDER BY processed_at DESC) = 1
),
opponent_history AS (
  SELECT pgs1.player_lookup, pgs1.game_date,
         AVG(pgs2.points) as avg_points_vs_opponent, COUNT(pgs2.points) as games_vs_opponent
  FROM `nba-props-platform.nba_analytics.player_game_summary` pgs1
  LEFT JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs2
    ON pgs1.player_lookup = pgs2.player_lookup
    AND pgs1.opponent_team_abbr = pgs2.opponent_team_abbr
    AND pgs2.game_date < pgs1.game_date
    AND pgs2.game_date >= DATE_SUB(pgs1.game_date, INTERVAL 3 YEAR)
    AND pgs2.points IS NOT NULL
  WHERE pgs1.game_date BETWEEN '2021-11-01' AND '2024-06-01'
  GROUP BY pgs1.player_lookup, pgs1.game_date, pgs1.opponent_team_abbr
),
actuals AS (
  SELECT player_lookup, game_date, points as actual_points,
         AVG(points) OVER (PARTITION BY player_lookup, EXTRACT(YEAR FROM game_date)
                          ORDER BY game_date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) as player_season_avg
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN '2021-11-01' AND '2024-06-01' AND points IS NOT NULL
)
SELECT fd.player_lookup, fd.game_date, fd.features,
       v.vegas_points_line, v.vegas_opening_line, v.vegas_line_move,
       CASE WHEN v.vegas_points_line IS NOT NULL THEN 1.0 ELSE 0.0 END as has_vegas_line,
       oh.avg_points_vs_opponent, COALESCE(oh.games_vs_opponent, 0) as games_vs_opponent,
       a.actual_points, a.player_season_avg
FROM feature_data fd
INNER JOIN actuals a ON fd.player_lookup = a.player_lookup AND fd.game_date = a.game_date
LEFT JOIN vegas_lines v ON fd.player_lookup = v.player_lookup AND fd.game_date = v.game_date
LEFT JOIN opponent_history oh ON fd.player_lookup = oh.player_lookup AND fd.game_date = oh.game_date
ORDER BY fd.game_date
"""

df = client.query(query).to_dataframe()
print(f"Loaded {len(df):,} samples")

# Prepare features
base_features = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct"
]

X_base = pd.DataFrame(df['features'].tolist(), columns=base_features)
df['vegas_points_line_imputed'] = df['vegas_points_line'].fillna(df['player_season_avg'])
df['vegas_opening_line_imputed'] = df['vegas_opening_line'].fillna(df['player_season_avg'])
df['vegas_line_move_imputed'] = df['vegas_line_move'].fillna(0)
df['avg_points_vs_opponent_imputed'] = df['avg_points_vs_opponent'].fillna(df['player_season_avg'])

X_new = pd.DataFrame({
    'vegas_points_line': df['vegas_points_line_imputed'],
    'vegas_opening_line': df['vegas_opening_line_imputed'],
    'vegas_line_move': df['vegas_line_move_imputed'],
    'has_vegas_line': df['has_vegas_line'],
    'avg_points_vs_opponent': df['avg_points_vs_opponent_imputed'],
    'games_vs_opponent': df['games_vs_opponent']
})

X = pd.concat([X_base, X_new], axis=1).fillna(X_base.median())
y = df['actual_points'].astype(float)

# Split
df_sorted = df.sort_values('game_date').reset_index(drop=True)
X = X.iloc[df_sorted.index].reset_index(drop=True)
y = y.iloc[df_sorted.index].reset_index(drop=True)

n = len(df)
train_end, val_end = int(n * 0.70), int(n * 0.85)
X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
X_val, y_val = X.iloc[train_end:val_end], y.iloc[train_end:val_end]
X_test, y_test = X.iloc[val_end:], y.iloc[val_end:]

print(f"Train: {len(X_train):,}  Val: {len(X_val):,}  Test: {len(X_test):,}")
print()

# Optuna objective
def objective(trial):
    params = {
        'depth': trial.suggest_int('depth', 4, 10),
        'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.1, log=True),
        'l2_leaf_reg': trial.suggest_float('l2_leaf_reg', 1.0, 10.0),
        'subsample': trial.suggest_float('subsample', 0.6, 0.9),
        'min_data_in_leaf': trial.suggest_int('min_data_in_leaf', 5, 50),
        'iterations': 1000,
        'random_seed': 42,
        'verbose': False,
        'early_stopping_rounds': 50
    }

    model = cb.CatBoostRegressor(**params)
    model.fit(X_train, y_train, eval_set=(X_val, y_val))

    val_pred = model.predict(X_val)
    return mean_absolute_error(y_val, val_pred)

# Run optimization
print("Running Optuna optimization (50 trials)...")
print("=" * 50)

study = optuna.create_study(direction='minimize')
study.optimize(objective, n_trials=50, show_progress_bar=True)

print()
print("=" * 50)
print(f"Best validation MAE: {study.best_value:.4f}")
print(f"Best params: {study.best_params}")
print()

# Train final model with best params
print("Training final model with best params...")
best_params = study.best_params
best_params['iterations'] = 1000
best_params['random_seed'] = 42
best_params['verbose'] = False
best_params['early_stopping_rounds'] = 50

final_model = cb.CatBoostRegressor(**best_params)
final_model.fit(X_train, y_train, eval_set=(X_val, y_val))

test_pred = final_model.predict(X_test)
test_mae = mean_absolute_error(y_test, test_pred)

print(f"\nFinal Test MAE: {test_mae:.4f}")

# Compare to baseline
V6_MAE = 4.14
BASELINE_CATBOOST_MAE = 3.899

print()
print("=" * 50)
print("COMPARISON")
print("=" * 50)
print(f"XGBoost v6 baseline:     {V6_MAE:.3f}")
print(f"CatBoost v7 (default):   {BASELINE_CATBOOST_MAE:.3f}")
print(f"CatBoost v7 (optimized): {test_mae:.3f}")
print()
if test_mae < BASELINE_CATBOOST_MAE:
    improvement = BASELINE_CATBOOST_MAE - test_mae
    print(f"Optuna improved by: {improvement:.4f} MAE ({(improvement/BASELINE_CATBOOST_MAE)*100:.2f}%)")
else:
    print(f"No improvement over default params")

# Save model
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
model_id = f"catboost_v7_optuna_{timestamp}"
final_model.save_model(str(MODEL_OUTPUT_DIR / f"{model_id}.cbm"))

metadata = {
    'model_id': model_id,
    'test_mae': float(test_mae),
    'val_mae': float(study.best_value),
    'best_params': study.best_params,
    'n_trials': 50,
    'best_iteration': final_model.get_best_iteration()
}
with open(MODEL_OUTPUT_DIR / f"{model_id}_metadata.json", 'w') as f:
    json.dump(metadata, f, indent=2)

print(f"\nSaved: {model_id}")
print("=" * 50)

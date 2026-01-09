#!/usr/bin/env python3
"""
Multi-Model Training with v7 Features (Vegas + Opponent History)

Compares XGBoost, LightGBM, and CatBoost on the same 31-feature set.
Also tests a stacked ensemble combining all three.

Usage:
    PYTHONPATH=. python ml/train_multi_model_v7.py
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.linear_model import Ridge

# Models
import xgboost as xgb
import lightgbm as lgb
import catboost as cb

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models")
MODEL_OUTPUT_DIR.mkdir(exist_ok=True)

print("=" * 80)
print(" MULTI-MODEL COMPARISON: XGBoost vs LightGBM vs CatBoost")
print("=" * 80)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================================================
# STEP 1: LOAD DATA (same query as v7)
# ============================================================================

print("=" * 80)
print("STEP 1: LOADING DATA")
print("=" * 80)

client = bigquery.Client(project=PROJECT_ID)

query = """
WITH
feature_data AS (
  SELECT
    mf.player_lookup,
    mf.game_date,
    mf.features,
    mf.feature_count,
    mf.opponent_team_abbr
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
  WHERE mf.game_date BETWEEN '2021-11-01' AND '2024-06-01'
    AND mf.feature_count = 25
    AND ARRAY_LENGTH(mf.features) = 25
),
vegas_lines AS (
  SELECT
    game_date,
    player_lookup,
    points_line as vegas_points_line,
    opening_line as vegas_opening_line,
    (points_line - opening_line) as vegas_line_move
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE bookmaker = 'BettingPros Consensus'
    AND bet_side = 'over'
    AND game_date BETWEEN '2021-11-01' AND '2024-06-01'
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY game_date, player_lookup
    ORDER BY processed_at DESC
  ) = 1
),
opponent_history AS (
  SELECT
    pgs1.player_lookup,
    pgs1.game_date,
    pgs1.opponent_team_abbr,
    AVG(pgs2.points) as avg_points_vs_opponent,
    COUNT(pgs2.points) as games_vs_opponent
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
  SELECT
    player_lookup,
    game_date,
    points as actual_points,
    AVG(points) OVER (
      PARTITION BY player_lookup, EXTRACT(YEAR FROM game_date)
      ORDER BY game_date
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) as player_season_avg
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN '2021-11-01' AND '2024-06-01'
    AND points IS NOT NULL
)
SELECT
  fd.player_lookup,
  fd.game_date,
  fd.features,
  v.vegas_points_line,
  v.vegas_opening_line,
  v.vegas_line_move,
  CASE WHEN v.vegas_points_line IS NOT NULL THEN 1.0 ELSE 0.0 END as has_vegas_line,
  oh.avg_points_vs_opponent,
  COALESCE(oh.games_vs_opponent, 0) as games_vs_opponent,
  a.actual_points,
  a.player_season_avg
FROM feature_data fd
INNER JOIN actuals a ON fd.player_lookup = a.player_lookup AND fd.game_date = a.game_date
LEFT JOIN vegas_lines v ON fd.player_lookup = v.player_lookup AND fd.game_date = v.game_date
LEFT JOIN opponent_history oh ON fd.player_lookup = oh.player_lookup AND fd.game_date = oh.game_date
ORDER BY fd.game_date, fd.player_lookup
"""

print("Fetching data...")
df = client.query(query).to_dataframe()
print(f"Loaded {len(df):,} samples")
print()

# ============================================================================
# STEP 2: PREPARE FEATURES
# ============================================================================

print("=" * 80)
print("STEP 2: PREPARING FEATURES")
print("=" * 80)

base_feature_names = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct"
]

new_feature_names = [
    "vegas_points_line", "vegas_opening_line", "vegas_line_move",
    "has_vegas_line", "avg_points_vs_opponent", "games_vs_opponent"
]

all_feature_names = base_feature_names + new_feature_names

# Build features
X_base = pd.DataFrame(df['features'].tolist(), columns=base_feature_names)

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

X = pd.concat([X_base, X_new], axis=1)
X = X.fillna(X.median())
y = df['actual_points'].astype(float)

print(f"Features: {X.shape[1]}")
print()

# ============================================================================
# STEP 3: SPLIT DATA
# ============================================================================

print("=" * 80)
print("STEP 3: CHRONOLOGICAL SPLIT")
print("=" * 80)

df_sorted = df.sort_values('game_date').reset_index(drop=True)
X = X.iloc[df_sorted.index].reset_index(drop=True)
y = y.iloc[df_sorted.index].reset_index(drop=True)

n = len(df_sorted)
train_end = int(n * 0.70)
val_end = int(n * 0.85)

X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
X_val, y_val = X.iloc[train_end:val_end], y.iloc[train_end:val_end]
X_test, y_test = X.iloc[val_end:], y.iloc[val_end:]

print(f"Train: {len(X_train):,}  Val: {len(X_val):,}  Test: {len(X_test):,}")
print()

# ============================================================================
# STEP 4: TRAIN MODELS
# ============================================================================

print("=" * 80)
print("STEP 4: TRAINING MODELS")
print("=" * 80)

results = {}

# --- XGBoost ---
print("\n[1/3] Training XGBoost...")
xgb_model = xgb.XGBRegressor(
    max_depth=6, min_child_weight=10, learning_rate=0.03, n_estimators=1000,
    subsample=0.7, colsample_bytree=0.7, colsample_bylevel=0.7,
    gamma=0.1, reg_alpha=0.5, reg_lambda=5.0, random_state=42,
    objective='reg:squarederror', eval_metric='mae', early_stopping_rounds=50
)
xgb_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
xgb_pred = xgb_model.predict(X_test)
results['XGBoost'] = {
    'model': xgb_model,
    'predictions': xgb_pred,
    'mae': mean_absolute_error(y_test, xgb_pred),
    'best_iteration': xgb_model.best_iteration
}
print(f"    XGBoost MAE: {results['XGBoost']['mae']:.4f} (best iter: {xgb_model.best_iteration})")

# --- LightGBM ---
print("\n[2/3] Training LightGBM...")
lgb_model = lgb.LGBMRegressor(
    max_depth=6, min_child_weight=10, learning_rate=0.03, n_estimators=1000,
    subsample=0.7, colsample_bytree=0.7, reg_alpha=0.5, reg_lambda=5.0,
    random_state=42, verbose=-1
)
lgb_model.fit(
    X_train, y_train,
    eval_set=[(X_val, y_val)],
    callbacks=[lgb.early_stopping(50, verbose=False)]
)
lgb_pred = lgb_model.predict(X_test)
results['LightGBM'] = {
    'model': lgb_model,
    'predictions': lgb_pred,
    'mae': mean_absolute_error(y_test, lgb_pred),
    'best_iteration': lgb_model.best_iteration_
}
print(f"    LightGBM MAE: {results['LightGBM']['mae']:.4f} (best iter: {lgb_model.best_iteration_})")

# --- CatBoost ---
print("\n[3/3] Training CatBoost...")
cb_model = cb.CatBoostRegressor(
    depth=6, l2_leaf_reg=5.0, learning_rate=0.03, iterations=1000,
    subsample=0.7, random_seed=42, verbose=False, early_stopping_rounds=50
)
cb_model.fit(X_train, y_train, eval_set=(X_val, y_val))
cb_pred = cb_model.predict(X_test)
results['CatBoost'] = {
    'model': cb_model,
    'predictions': cb_pred,
    'mae': mean_absolute_error(y_test, cb_pred),
    'best_iteration': cb_model.get_best_iteration()
}
print(f"    CatBoost MAE: {results['CatBoost']['mae']:.4f} (best iter: {cb_model.get_best_iteration()})")

# ============================================================================
# STEP 5: ENSEMBLE METHODS
# ============================================================================

print("\n" + "=" * 80)
print("STEP 5: ENSEMBLE METHODS")
print("=" * 80)

# Simple average
avg_pred = (xgb_pred + lgb_pred + cb_pred) / 3
avg_mae = mean_absolute_error(y_test, avg_pred)
results['Simple Average'] = {'predictions': avg_pred, 'mae': avg_mae}
print(f"\nSimple Average MAE: {avg_mae:.4f}")

# Weighted average (inverse MAE weighting)
weights = np.array([1/results['XGBoost']['mae'], 1/results['LightGBM']['mae'], 1/results['CatBoost']['mae']])
weights = weights / weights.sum()
weighted_pred = weights[0] * xgb_pred + weights[1] * lgb_pred + weights[2] * cb_pred
weighted_mae = mean_absolute_error(y_test, weighted_pred)
results['Weighted Average'] = {'predictions': weighted_pred, 'mae': weighted_mae, 'weights': weights.tolist()}
print(f"Weighted Average MAE: {weighted_mae:.4f} (weights: XGB={weights[0]:.3f}, LGB={weights[1]:.3f}, CB={weights[2]:.3f})")

# Stacked ensemble with Ridge meta-learner
print("\nTraining stacked ensemble...")
# Get validation predictions for stacking
xgb_val_pred = xgb_model.predict(X_val)
lgb_val_pred = lgb_model.predict(X_val)
cb_val_pred = cb_model.predict(X_val)

stack_val = np.column_stack([xgb_val_pred, lgb_val_pred, cb_val_pred])
stack_test = np.column_stack([xgb_pred, lgb_pred, cb_pred])

meta_model = Ridge(alpha=1.0)
meta_model.fit(stack_val, y_val)
stacked_pred = meta_model.predict(stack_test)
stacked_mae = mean_absolute_error(y_test, stacked_pred)
results['Stacked (Ridge)'] = {
    'predictions': stacked_pred,
    'mae': stacked_mae,
    'meta_coefs': meta_model.coef_.tolist(),
    'meta_intercept': meta_model.intercept_
}
print(f"Stacked (Ridge) MAE: {stacked_mae:.4f} (coefs: XGB={meta_model.coef_[0]:.3f}, LGB={meta_model.coef_[1]:.3f}, CB={meta_model.coef_[2]:.3f})")

# ============================================================================
# STEP 6: RESULTS COMPARISON
# ============================================================================

print("\n" + "=" * 80)
print("STEP 6: FINAL COMPARISON")
print("=" * 80)

V6_MAE = 4.14
MOCK_MAE = 4.80

print(f"\n{'Model':<20} {'MAE':>8} {'vs v6':>10} {'vs Mock':>10}")
print("-" * 50)
print(f"{'Mock v1':<20} {MOCK_MAE:>8.3f} {'+15.9%':>10} {'baseline':>10}")
print(f"{'XGBoost v6':<20} {V6_MAE:>8.3f} {'baseline':>10} {'-13.8%':>10}")
print("-" * 50)

# Sort by MAE
sorted_results = sorted(results.items(), key=lambda x: x[1]['mae'])
for name, data in sorted_results:
    mae = data['mae']
    vs_v6 = ((V6_MAE - mae) / V6_MAE) * 100
    vs_mock = ((MOCK_MAE - mae) / MOCK_MAE) * 100
    marker = " ***" if mae == min(r['mae'] for r in results.values()) else ""
    print(f"{name:<20} {mae:>8.3f} {vs_v6:>+9.1f}% {vs_mock:>+9.1f}%{marker}")

best_name = sorted_results[0][0]
best_mae = sorted_results[0][1]['mae']

print("\n" + "-" * 50)
print(f"BEST MODEL: {best_name} with MAE = {best_mae:.4f}")
print(f"Improvement vs v6: {((V6_MAE - best_mae) / V6_MAE) * 100:.1f}%")
print(f"Improvement vs Mock: {((MOCK_MAE - best_mae) / MOCK_MAE) * 100:.1f}%")

# ============================================================================
# STEP 7: SAVE BEST MODEL
# ============================================================================

print("\n" + "=" * 80)
print("STEP 7: SAVING MODELS")
print("=" * 80)

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

# Save individual models
for name in ['XGBoost', 'LightGBM', 'CatBoost']:
    model = results[name]['model']
    model_id = f"{name.lower()}_v7_31features_{timestamp}"

    if name == 'XGBoost':
        model.get_booster().save_model(str(MODEL_OUTPUT_DIR / f"{model_id}.json"))
    elif name == 'LightGBM':
        model.booster_.save_model(str(MODEL_OUTPUT_DIR / f"{model_id}.txt"))
    elif name == 'CatBoost':
        model.save_model(str(MODEL_OUTPUT_DIR / f"{model_id}.cbm"))

    print(f"Saved {name}: {model_id}")

# Save ensemble metadata
ensemble_meta = {
    'timestamp': timestamp,
    'features': all_feature_names,
    'feature_count': len(all_feature_names),
    'results': {
        name: {
            'mae': float(data['mae']),
            'vs_v6_pct': float(((V6_MAE - data['mae']) / V6_MAE) * 100),
            **(
                {'best_iteration': data.get('best_iteration')}
                if 'best_iteration' in data else {}
            ),
            **(
                {'weights': data.get('weights')}
                if 'weights' in data else {}
            ),
            **(
                {'meta_coefs': data.get('meta_coefs'), 'meta_intercept': data.get('meta_intercept')}
                if 'meta_coefs' in data else {}
            )
        }
        for name, data in results.items()
    },
    'best_model': best_name,
    'best_mae': float(best_mae),
    'v6_baseline': V6_MAE,
    'mock_baseline': MOCK_MAE
}

with open(MODEL_OUTPUT_DIR / f"multi_model_v7_comparison_{timestamp}.json", 'w') as f:
    json.dump(ensemble_meta, f, indent=2)
print(f"Saved comparison metadata")

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print()
print(f"Training samples: {len(df):,}")
print(f"Features: {len(all_feature_names)} (25 base + 6 new)")
print()
print("Individual Models:")
print(f"  XGBoost:  {results['XGBoost']['mae']:.4f}")
print(f"  LightGBM: {results['LightGBM']['mae']:.4f}")
print(f"  CatBoost: {results['CatBoost']['mae']:.4f}")
print()
print("Ensembles:")
print(f"  Simple Avg:     {results['Simple Average']['mae']:.4f}")
print(f"  Weighted Avg:   {results['Weighted Average']['mae']:.4f}")
print(f"  Stacked Ridge:  {results['Stacked (Ridge)']['mae']:.4f}")
print()
print(f"BEST: {best_name} = {best_mae:.4f} MAE")
print(f"Improvement vs v6: {((V6_MAE - best_mae) / V6_MAE) * 100:.1f}%")
print(f"Improvement vs Mock: {((MOCK_MAE - best_mae) / MOCK_MAE) * 100:.1f}%")
print()
print("=" * 80)

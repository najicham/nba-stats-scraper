#!/usr/bin/env python3
"""
Validate v8 Model on 2024-25 Season (True Out-of-Sample)

The v8 model was trained on 2021-11 to 2024-06.
2024-25 season (Oct 2024 - present) is completely unseen.

This script:
1. Trains v8 model on historical data (2021-2024)
2. Generates predictions for 2024-25 season
3. Compares to actuals and Vegas
4. Analyzes errors by various segments

Usage:
    PYTHONPATH=. python ml/validate_v8_2024_25.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import json
from datetime import datetime
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
from sklearn.linear_model import Ridge
import xgboost as xgb
import lightgbm as lgb
import catboost as cb

PROJECT_ID = "nba-props-platform"

print("=" * 80)
print(" V8 MODEL VALIDATION ON 2024-25 SEASON")
print("=" * 80)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

client = bigquery.Client(project=PROJECT_ID)

# ============================================================================
# STEP 1: LOAD TRAINING DATA (2021-2024)
# ============================================================================

print("=" * 80)
print("STEP 1: LOADING TRAINING DATA (2021-2024)")
print("=" * 80)

train_query = """
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
         AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date
                          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) as player_season_avg,
         AVG(minutes_played) OVER (PARTITION BY player_lookup ORDER BY game_date
                                   ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as minutes_avg_last_10,
         AVG(SAFE_DIVIDE(points, minutes_played)) OVER (PARTITION BY player_lookup ORDER BY game_date
                                                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as ppm_avg_last_10
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN '2021-11-01' AND '2024-06-01'
    AND points IS NOT NULL AND minutes_played > 0
)
SELECT fd.player_lookup, fd.game_date, fd.features,
       v.vegas_points_line, v.vegas_opening_line, v.vegas_line_move,
       CASE WHEN v.vegas_points_line IS NOT NULL THEN 1.0 ELSE 0.0 END as has_vegas_line,
       oh.avg_points_vs_opponent, COALESCE(oh.games_vs_opponent, 0) as games_vs_opponent,
       a.actual_points, a.player_season_avg, a.minutes_avg_last_10, a.ppm_avg_last_10
FROM feature_data fd
INNER JOIN actuals a ON fd.player_lookup = a.player_lookup AND fd.game_date = a.game_date
LEFT JOIN vegas_lines v ON fd.player_lookup = v.player_lookup AND fd.game_date = v.game_date
LEFT JOIN opponent_history oh ON fd.player_lookup = oh.player_lookup AND fd.game_date = oh.game_date
WHERE a.minutes_avg_last_10 IS NOT NULL
ORDER BY fd.game_date
"""

print("Loading training data...")
train_df = client.query(train_query).to_dataframe()
print(f"Training samples: {len(train_df):,}")

# ============================================================================
# STEP 2: LOAD 2024-25 VALIDATION DATA
# ============================================================================

print("\n" + "=" * 80)
print("STEP 2: LOADING 2024-25 VALIDATION DATA")
print("=" * 80)

val_query = """
WITH
feature_data AS (
  SELECT mf.player_lookup, mf.game_date, mf.features, mf.opponent_team_abbr
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
  WHERE mf.game_date >= '2024-10-01'
    AND mf.feature_count = 25 AND ARRAY_LENGTH(mf.features) = 25
),
vegas_lines AS (
  SELECT game_date, player_lookup, points_line as vegas_points_line,
         opening_line as vegas_opening_line, (points_line - opening_line) as vegas_line_move
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE bookmaker = 'BettingPros Consensus' AND bet_side = 'over'
    AND game_date >= '2024-10-01'
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
  WHERE pgs1.game_date >= '2024-10-01'
  GROUP BY pgs1.player_lookup, pgs1.game_date, pgs1.opponent_team_abbr
),
actuals AS (
  SELECT player_lookup, game_date, points as actual_points,
         AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date
                          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) as player_season_avg,
         AVG(minutes_played) OVER (PARTITION BY player_lookup ORDER BY game_date
                                   ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as minutes_avg_last_10,
         AVG(SAFE_DIVIDE(points, minutes_played)) OVER (PARTITION BY player_lookup ORDER BY game_date
                                                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as ppm_avg_last_10
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2024-10-01'
    AND points IS NOT NULL AND minutes_played > 0
)
SELECT fd.player_lookup, fd.game_date, fd.features,
       v.vegas_points_line, v.vegas_opening_line, v.vegas_line_move,
       CASE WHEN v.vegas_points_line IS NOT NULL THEN 1.0 ELSE 0.0 END as has_vegas_line,
       oh.avg_points_vs_opponent, COALESCE(oh.games_vs_opponent, 0) as games_vs_opponent,
       a.actual_points, a.player_season_avg, a.minutes_avg_last_10, a.ppm_avg_last_10
FROM feature_data fd
INNER JOIN actuals a ON fd.player_lookup = a.player_lookup AND fd.game_date = a.game_date
LEFT JOIN vegas_lines v ON fd.player_lookup = v.player_lookup AND fd.game_date = v.game_date
LEFT JOIN opponent_history oh ON fd.player_lookup = oh.player_lookup AND fd.game_date = oh.game_date
WHERE a.minutes_avg_last_10 IS NOT NULL
ORDER BY fd.game_date
"""

print("Loading 2024-25 data...")
val_df = client.query(val_query).to_dataframe()
print(f"Validation samples: {len(val_df):,}")
print(f"Date range: {val_df['game_date'].min()} to {val_df['game_date'].max()}")
print(f"Unique players: {val_df['player_lookup'].nunique()}")

# ============================================================================
# STEP 3: PREPARE FEATURES
# ============================================================================

print("\n" + "=" * 80)
print("STEP 3: PREPARING FEATURES")
print("=" * 80)

base_features = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct"
]

def prepare_features(df):
    X_base = pd.DataFrame(df['features'].tolist(), columns=base_features)

    df = df.copy()
    df['vegas_points_line_imp'] = df['vegas_points_line'].fillna(df['player_season_avg'])
    df['vegas_opening_line_imp'] = df['vegas_opening_line'].fillna(df['player_season_avg'])
    df['vegas_line_move_imp'] = df['vegas_line_move'].fillna(0)
    df['avg_points_vs_opponent_imp'] = df['avg_points_vs_opponent'].fillna(df['player_season_avg'])

    X_new = pd.DataFrame({
        'vegas_points_line': df['vegas_points_line_imp'].astype(float),
        'vegas_opening_line': df['vegas_opening_line_imp'].astype(float),
        'vegas_line_move': df['vegas_line_move_imp'].astype(float),
        'has_vegas_line': df['has_vegas_line'].astype(float),
        'avg_points_vs_opponent': df['avg_points_vs_opponent_imp'].astype(float),
        'games_vs_opponent': df['games_vs_opponent'].astype(float),
        'minutes_avg_last_10': df['minutes_avg_last_10'].astype(float),
        'ppm_avg_last_10': df['ppm_avg_last_10'].astype(float)
    })

    X = pd.concat([X_base, X_new], axis=1)
    return X, df

X_train, train_df = prepare_features(train_df)
X_val, val_df = prepare_features(val_df)

# Fill NaNs with training medians
train_medians = X_train.median()
X_train = X_train.fillna(train_medians)
X_val = X_val.fillna(train_medians)

y_train = train_df['actual_points'].astype(float)
y_val = val_df['actual_points'].astype(float)

print(f"Features: {X_train.shape[1]}")
print(f"Training: {len(X_train):,}, Validation: {len(X_val):,}")

# Check Vegas coverage
vegas_coverage = val_df['has_vegas_line'].mean()
print(f"\n2024-25 Vegas coverage: {vegas_coverage:.1%}")

# ============================================================================
# STEP 4: TRAIN MODELS
# ============================================================================

print("\n" + "=" * 80)
print("STEP 4: TRAINING MODELS ON HISTORICAL DATA")
print("=" * 80)

# Split training into train/val for early stopping
n = len(X_train)
split = int(n * 0.85)
X_tr, X_v = X_train.iloc[:split], X_train.iloc[split:]
y_tr, y_v = y_train.iloc[:split], y_train.iloc[split:]

print(f"\nInternal split: {len(X_tr):,} train, {len(X_v):,} val")

# XGBoost
print("\n[1/3] Training XGBoost...")
xgb_model = xgb.XGBRegressor(
    max_depth=6, min_child_weight=10, learning_rate=0.03, n_estimators=1000,
    subsample=0.7, colsample_bytree=0.7, gamma=0.1, reg_alpha=0.5, reg_lambda=5.0,
    random_state=42, objective='reg:squarederror', eval_metric='mae', early_stopping_rounds=50
)
xgb_model.fit(X_tr, y_tr, eval_set=[(X_v, y_v)], verbose=False)
print(f"    Best iteration: {xgb_model.best_iteration}")

# LightGBM
print("[2/3] Training LightGBM...")
lgb_model = lgb.LGBMRegressor(
    max_depth=6, min_child_weight=10, learning_rate=0.03, n_estimators=1000,
    subsample=0.7, colsample_bytree=0.7, reg_alpha=0.5, reg_lambda=5.0,
    random_state=42, verbose=-1
)
lgb_model.fit(X_tr, y_tr, eval_set=[(X_v, y_v)], callbacks=[lgb.early_stopping(50, verbose=False)])
print(f"    Best iteration: {lgb_model.best_iteration_}")

# CatBoost
print("[3/3] Training CatBoost...")
cb_model = cb.CatBoostRegressor(
    depth=6, learning_rate=0.07, l2_leaf_reg=3.8, subsample=0.72, min_data_in_leaf=16,
    iterations=1000, random_seed=42, verbose=False, early_stopping_rounds=50
)
cb_model.fit(X_tr, y_tr, eval_set=(X_v, y_v))
print(f"    Best iteration: {cb_model.get_best_iteration()}")

# ============================================================================
# STEP 5: PREDICT ON 2024-25
# ============================================================================

print("\n" + "=" * 80)
print("STEP 5: PREDICTIONS ON 2024-25 SEASON")
print("=" * 80)

xgb_pred = xgb_model.predict(X_val)
lgb_pred = lgb_model.predict(X_val)
cb_pred = cb_model.predict(X_val)

# Stacked ensemble
xgb_v = xgb_model.predict(X_v)
lgb_v = lgb_model.predict(X_v)
cb_v = cb_model.predict(X_v)

meta = Ridge(alpha=1.0)
meta.fit(np.column_stack([xgb_v, lgb_v, cb_v]), y_v)
stacked_pred = meta.predict(np.column_stack([xgb_pred, lgb_pred, cb_pred]))

# Simple average
avg_pred = (xgb_pred + lgb_pred + cb_pred) / 3

print(f"Predictions generated for {len(X_val):,} games")

# ============================================================================
# STEP 6: OVERALL RESULTS
# ============================================================================

print("\n" + "=" * 80)
print("STEP 6: OVERALL RESULTS ON 2024-25")
print("=" * 80)

results = {
    'XGBoost': mean_absolute_error(y_val, xgb_pred),
    'LightGBM': mean_absolute_error(y_val, lgb_pred),
    'CatBoost': mean_absolute_error(y_val, cb_pred),
    'Simple Avg': mean_absolute_error(y_val, avg_pred),
    'Stacked': mean_absolute_error(y_val, stacked_pred)
}

# Baselines
season_avg_pred = val_df['player_season_avg'].fillna(y_val.mean())
season_avg_mae = mean_absolute_error(y_val, season_avg_pred)

# Vegas (only on covered games)
vegas_mask = val_df['has_vegas_line'] == 1
if vegas_mask.sum() > 0:
    vegas_mae = mean_absolute_error(y_val[vegas_mask], val_df.loc[vegas_mask, 'vegas_points_line'])
    our_mae_on_vegas = mean_absolute_error(y_val[vegas_mask], stacked_pred[vegas_mask])
else:
    vegas_mae = None
    our_mae_on_vegas = None

print(f"\n{'Model':<20} {'MAE':>8} {'vs Season Avg':>15}")
print("-" * 45)
print(f"{'Season Avg':<20} {season_avg_mae:>8.3f} {'--':>15}")

for name, mae in sorted(results.items(), key=lambda x: x[1]):
    vs_baseline = ((season_avg_mae - mae) / season_avg_mae) * 100
    marker = " ***" if mae == min(results.values()) else ""
    print(f"{name:<20} {mae:>8.3f} {vs_baseline:>+14.1f}%{marker}")

best_model = min(results, key=results.get)
best_mae = results[best_model]

print(f"\nBEST: {best_model} = {best_mae:.4f}")

# Compare to Vegas
if vegas_mae:
    print(f"\n--- Vegas Comparison (on {vegas_mask.sum():,} covered games) ---")
    print(f"Vegas MAE:     {vegas_mae:.3f}")
    print(f"Our MAE:       {our_mae_on_vegas:.3f}")
    vs_vegas = ((vegas_mae - our_mae_on_vegas) / vegas_mae) * 100
    print(f"vs Vegas:      {vs_vegas:+.1f}%")

# ============================================================================
# STEP 7: ANALYSIS BY SEGMENTS
# ============================================================================

print("\n" + "=" * 80)
print("STEP 7: ERROR ANALYSIS BY SEGMENTS")
print("=" * 80)

val_df['prediction'] = stacked_pred
val_df['error'] = np.abs(y_val - stacked_pred)
val_df['month'] = pd.to_datetime(val_df['game_date']).dt.month

# By month
print("\n--- By Month ---")
monthly = val_df.groupby('month').agg({
    'error': 'mean',
    'actual_points': 'count'
}).rename(columns={'actual_points': 'games', 'error': 'mae'})
print(monthly.to_string())

# By scoring tier
print("\n--- By Player Scoring Tier ---")
val_df['tier'] = pd.cut(val_df['player_season_avg'].fillna(10),
                        bins=[0, 8, 15, 22, 100],
                        labels=['Bench (0-8)', 'Role (8-15)', 'Starter (15-22)', 'Star (22+)'])
tier_analysis = val_df.groupby('tier').agg({
    'error': 'mean',
    'actual_points': ['count', 'mean']
}).round(2)
tier_analysis.columns = ['MAE', 'Games', 'Avg Points']
print(tier_analysis.to_string())

# By Vegas coverage
print("\n--- By Vegas Coverage ---")
print(f"With Vegas line:    {val_df[val_df['has_vegas_line']==1]['error'].mean():.3f} MAE ({(val_df['has_vegas_line']==1).sum():,} games)")
print(f"Without Vegas line: {val_df[val_df['has_vegas_line']==0]['error'].mean():.3f} MAE ({(val_df['has_vegas_line']==0).sum():,} games)")

# Worst predictions
print("\n--- Worst 10 Predictions ---")
worst = val_df.nlargest(10, 'error')[['game_date', 'player_lookup', 'actual_points', 'prediction', 'error']]
worst['prediction'] = worst['prediction'].round(1)
worst['error'] = worst['error'].round(1)
print(worst.to_string(index=False))

# Best predictions
print("\n--- Distribution ---")
print(f"Within 3 pts: {(val_df['error'] <= 3).mean()*100:.1f}%")
print(f"Within 5 pts: {(val_df['error'] <= 5).mean()*100:.1f}%")
print(f"Within 10 pts: {(val_df['error'] <= 10).mean()*100:.1f}%")

# ============================================================================
# STEP 8: COMPARE TO TRAINING PERFORMANCE
# ============================================================================

print("\n" + "=" * 80)
print("STEP 8: TRAINING vs 2024-25 PERFORMANCE")
print("=" * 80)

# Get training set performance
train_pred = stacked_pred_train = meta.predict(np.column_stack([
    xgb_model.predict(X_train),
    lgb_model.predict(X_train),
    cb_model.predict(X_train)
]))
train_mae = mean_absolute_error(y_train, train_pred)

print(f"\nTraining MAE (2021-2024): {train_mae:.3f}")
print(f"2024-25 MAE:              {best_mae:.3f}")
print(f"Degradation:              {best_mae - train_mae:+.3f} ({(best_mae/train_mae - 1)*100:+.1f}%)")

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

print(f"""
2024-25 Season Validation Results
=================================
Games evaluated: {len(val_df):,}
Date range: {val_df['game_date'].min()} to {val_df['game_date'].max()}

Model Performance:
  Best Model: {best_model}
  MAE: {best_mae:.3f}
  vs Season Avg: {((season_avg_mae - best_mae) / season_avg_mae) * 100:+.1f}%

Vegas Comparison (on {vegas_mask.sum():,} games):
  Vegas MAE: {vegas_mae:.3f}
  Our MAE: {our_mae_on_vegas:.3f}
  vs Vegas: {((vegas_mae - our_mae_on_vegas) / vegas_mae) * 100:+.1f}%

Accuracy:
  Within 3 pts: {(val_df['error'] <= 3).mean()*100:.1f}%
  Within 5 pts: {(val_df['error'] <= 5).mean()*100:.1f}%
""")

print("=" * 80)

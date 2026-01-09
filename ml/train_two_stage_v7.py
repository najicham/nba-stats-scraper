#!/usr/bin/env python3
"""
Two-Stage Model: Minutes Prediction → Points Per Minute

Stage 1: Predict minutes played (more stable, coach decisions)
Stage 2: Predict points per minute (efficiency/scoring rate)
Final: predicted_minutes × predicted_ppm

This separates two fundamentally different prediction problems:
- Minutes: Affected by game flow, blowouts, rotations
- PPM: Player's scoring efficiency, harder to predict

Usage:
    PYTHONPATH=. python ml/train_two_stage_v7.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import json
from datetime import datetime
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error, mean_squared_error
import catboost as cb

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models")

print("=" * 80)
print(" TWO-STAGE MODEL: MINUTES → POINTS PER MINUTE")
print("=" * 80)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================================================
# STEP 1: LOAD DATA WITH MINUTES
# ============================================================================

print("=" * 80)
print("STEP 1: LOADING DATA")
print("=" * 80)

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
  SELECT player_lookup, game_date,
         points as actual_points,
         minutes_played as actual_minutes,
         SAFE_DIVIDE(points, minutes_played) as actual_ppm,
         -- Historical averages for features
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
       a.actual_points, a.actual_minutes, a.actual_ppm,
       a.player_season_avg, a.minutes_avg_last_10, a.ppm_avg_last_10
FROM feature_data fd
INNER JOIN actuals a ON fd.player_lookup = a.player_lookup AND fd.game_date = a.game_date
LEFT JOIN vegas_lines v ON fd.player_lookup = v.player_lookup AND fd.game_date = v.game_date
LEFT JOIN opponent_history oh ON fd.player_lookup = oh.player_lookup AND fd.game_date = oh.game_date
WHERE a.minutes_avg_last_10 IS NOT NULL  -- Need history for minutes prediction
ORDER BY fd.game_date
"""

print("Fetching data...")
df = client.query(query).to_dataframe()
print(f"Loaded {len(df):,} samples")
print(f"Avg minutes: {df['actual_minutes'].mean():.1f}")
print(f"Avg PPM: {df['actual_ppm'].mean():.3f}")
print()

# ============================================================================
# STEP 2: PREPARE FEATURES
# ============================================================================

print("=" * 80)
print("STEP 2: PREPARING FEATURES")
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

X_base = pd.DataFrame(df['features'].tolist(), columns=base_features)

# Impute missing values
df['vegas_points_line_imp'] = df['vegas_points_line'].fillna(df['player_season_avg'])
df['vegas_opening_line_imp'] = df['vegas_opening_line'].fillna(df['player_season_avg'])
df['vegas_line_move_imp'] = df['vegas_line_move'].fillna(0)
df['avg_points_vs_opponent_imp'] = df['avg_points_vs_opponent'].fillna(df['player_season_avg'])

X_new = pd.DataFrame({
    'vegas_points_line': df['vegas_points_line_imp'],
    'vegas_opening_line': df['vegas_opening_line_imp'],
    'vegas_line_move': df['vegas_line_move_imp'],
    'has_vegas_line': df['has_vegas_line'],
    'avg_points_vs_opponent': df['avg_points_vs_opponent_imp'],
    'games_vs_opponent': df['games_vs_opponent'],
    # New: minutes and PPM history
    'minutes_avg_last_10': df['minutes_avg_last_10'],
    'ppm_avg_last_10': df['ppm_avg_last_10']
})

X = pd.concat([X_base, X_new], axis=1).fillna(X_base.median())
all_features = list(X.columns)

# Targets
y_points = df['actual_points'].astype(float)
y_minutes = df['actual_minutes'].astype(float)
y_ppm = df['actual_ppm'].astype(float)

print(f"Features: {len(all_features)} (25 base + 8 new)")
print(f"New features: minutes_avg_last_10, ppm_avg_last_10")
print()

# ============================================================================
# STEP 3: SPLIT DATA
# ============================================================================

print("=" * 80)
print("STEP 3: CHRONOLOGICAL SPLIT")
print("=" * 80)

df_sorted = df.sort_values('game_date').reset_index(drop=True)
X = X.iloc[df_sorted.index].reset_index(drop=True)
y_points = y_points.iloc[df_sorted.index].reset_index(drop=True)
y_minutes = y_minutes.iloc[df_sorted.index].reset_index(drop=True)
y_ppm = y_ppm.iloc[df_sorted.index].reset_index(drop=True)

n = len(df)
train_end, val_end = int(n * 0.70), int(n * 0.85)

X_train, X_val, X_test = X.iloc[:train_end], X.iloc[train_end:val_end], X.iloc[val_end:]
y_pts_train, y_pts_val, y_pts_test = y_points.iloc[:train_end], y_points.iloc[train_end:val_end], y_points.iloc[val_end:]
y_min_train, y_min_val, y_min_test = y_minutes.iloc[:train_end], y_minutes.iloc[train_end:val_end], y_minutes.iloc[val_end:]
y_ppm_train, y_ppm_val, y_ppm_test = y_ppm.iloc[:train_end], y_ppm.iloc[train_end:val_end], y_ppm.iloc[val_end:]

print(f"Train: {len(X_train):,}  Val: {len(X_val):,}  Test: {len(X_test):,}")
print()

# ============================================================================
# STEP 4: TRAIN BASELINE (SINGLE STAGE)
# ============================================================================

print("=" * 80)
print("STEP 4: BASELINE - SINGLE STAGE MODEL")
print("=" * 80)

cb_params = {
    'depth': 6, 'learning_rate': 0.07, 'l2_leaf_reg': 3.8,
    'subsample': 0.72, 'min_data_in_leaf': 16,
    'iterations': 1000, 'random_seed': 42, 'verbose': False,
    'early_stopping_rounds': 50
}

print("Training single-stage points model...")
baseline_model = cb.CatBoostRegressor(**cb_params)
baseline_model.fit(X_train, y_pts_train, eval_set=(X_val, y_pts_val))

baseline_pred = baseline_model.predict(X_test)
baseline_mae = mean_absolute_error(y_pts_test, baseline_pred)
print(f"Single-stage MAE: {baseline_mae:.4f}")
print()

# ============================================================================
# STEP 5: TRAIN TWO-STAGE MODEL
# ============================================================================

print("=" * 80)
print("STEP 5: TWO-STAGE MODEL")
print("=" * 80)

# Stage 1: Predict minutes
print("\n[Stage 1] Training minutes model...")
minutes_model = cb.CatBoostRegressor(**cb_params)
minutes_model.fit(X_train, y_min_train, eval_set=(X_val, y_min_val))

min_pred_train = minutes_model.predict(X_train)
min_pred_val = minutes_model.predict(X_val)
min_pred_test = minutes_model.predict(X_test)

minutes_mae = mean_absolute_error(y_min_test, min_pred_test)
print(f"Minutes MAE: {minutes_mae:.2f} minutes")

# Stage 2: Predict points per minute
print("\n[Stage 2] Training PPM model...")
ppm_model = cb.CatBoostRegressor(**cb_params)
ppm_model.fit(X_train, y_ppm_train, eval_set=(X_val, y_ppm_val))

ppm_pred_test = ppm_model.predict(X_test)
ppm_mae = mean_absolute_error(y_ppm_test, ppm_pred_test)
print(f"PPM MAE: {ppm_mae:.4f} points/min")

# Final: minutes × PPM
print("\n[Final] Combining predictions...")
two_stage_pred = min_pred_test * ppm_pred_test
two_stage_mae = mean_absolute_error(y_pts_test, two_stage_pred)
print(f"Two-stage MAE: {two_stage_mae:.4f}")

# ============================================================================
# STEP 6: HYBRID APPROACHES
# ============================================================================

print("\n" + "=" * 80)
print("STEP 6: HYBRID APPROACHES")
print("=" * 80)

# Hybrid 1: Average of single-stage and two-stage
hybrid1_pred = (baseline_pred + two_stage_pred) / 2
hybrid1_mae = mean_absolute_error(y_pts_test, hybrid1_pred)
print(f"Hybrid (avg single + two-stage): {hybrid1_mae:.4f}")

# Hybrid 2: Weighted blend
# Find optimal weight using validation set
baseline_val_pred = baseline_model.predict(X_val)
two_stage_val_pred = min_pred_val * ppm_model.predict(X_val)

best_weight, best_val_mae = 0, float('inf')
for w in np.arange(0, 1.01, 0.05):
    blend = w * baseline_val_pred + (1-w) * two_stage_val_pred
    mae = mean_absolute_error(y_pts_val, blend)
    if mae < best_val_mae:
        best_val_mae = mae
        best_weight = w

hybrid2_pred = best_weight * baseline_pred + (1 - best_weight) * two_stage_pred
hybrid2_mae = mean_absolute_error(y_pts_test, hybrid2_pred)
print(f"Hybrid (optimal blend w={best_weight:.2f}): {hybrid2_mae:.4f}")

# Hybrid 3: Use predicted minutes as feature for points model
print("\nTraining minutes-augmented model...")
X_train_aug = X_train.copy()
X_train_aug['pred_minutes'] = min_pred_train
X_val_aug = X_val.copy()
X_val_aug['pred_minutes'] = min_pred_val
X_test_aug = X_test.copy()
X_test_aug['pred_minutes'] = min_pred_test

aug_model = cb.CatBoostRegressor(**cb_params)
aug_model.fit(X_train_aug, y_pts_train, eval_set=(X_val_aug, y_pts_val))
aug_pred = aug_model.predict(X_test_aug)
aug_mae = mean_absolute_error(y_pts_test, aug_pred)
print(f"Minutes-augmented model: {aug_mae:.4f}")

# ============================================================================
# STEP 7: COMPARISON
# ============================================================================

print("\n" + "=" * 80)
print("STEP 7: FINAL COMPARISON")
print("=" * 80)

V6_MAE = 4.14
V7_ENSEMBLE_MAE = 3.881

results = {
    'Single-stage (baseline)': baseline_mae,
    'Two-stage (min × ppm)': two_stage_mae,
    'Hybrid (simple avg)': hybrid1_mae,
    f'Hybrid (blend w={best_weight:.2f})': hybrid2_mae,
    'Minutes-augmented': aug_mae
}

print(f"\n{'Model':<30} {'MAE':>8} {'vs v6':>10} {'vs v7 ens':>12}")
print("-" * 62)
print(f"{'v6 baseline':<30} {V6_MAE:>8.3f} {'baseline':>10} {'+6.7%':>12}")
print(f"{'v7 stacked ensemble':<30} {V7_ENSEMBLE_MAE:>8.3f} {'-6.3%':>10} {'baseline':>12}")
print("-" * 62)

for name, mae in sorted(results.items(), key=lambda x: x[1]):
    vs_v6 = ((V6_MAE - mae) / V6_MAE) * 100
    vs_v7 = ((V7_ENSEMBLE_MAE - mae) / V7_ENSEMBLE_MAE) * 100
    marker = " ***" if mae == min(results.values()) else ""
    print(f"{name:<30} {mae:>8.4f} {vs_v6:>+9.1f}% {vs_v7:>+11.1f}%{marker}")

best_name = min(results, key=results.get)
best_mae = results[best_name]

print("\n" + "-" * 62)
print(f"BEST: {best_name} = {best_mae:.4f}")

if best_mae < V7_ENSEMBLE_MAE:
    print(f"NEW RECORD! Beats v7 ensemble by {V7_ENSEMBLE_MAE - best_mae:.4f}")
else:
    print(f"v7 ensemble still best (by {best_mae - V7_ENSEMBLE_MAE:.4f})")

# ============================================================================
# STEP 8: ANALYZE MINUTES PREDICTION VALUE
# ============================================================================

print("\n" + "=" * 80)
print("STEP 8: MINUTES PREDICTION ANALYSIS")
print("=" * 80)

# How good is the minutes prediction?
print(f"\nMinutes prediction quality:")
print(f"  MAE: {minutes_mae:.2f} minutes")
print(f"  Avg actual: {y_min_test.mean():.1f} minutes")
print(f"  Relative error: {minutes_mae / y_min_test.mean() * 100:.1f}%")

# Correlation between minutes error and points error
min_error = np.abs(y_min_test - min_pred_test)
pts_error = np.abs(y_pts_test - baseline_pred)
corr = np.corrcoef(min_error, pts_error)[0, 1]
print(f"\nCorrelation (minutes error vs points error): {corr:.3f}")

# Save models
print("\n" + "=" * 80)
print("SAVING MODELS")
print("=" * 80)

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

minutes_model.save_model(str(MODEL_OUTPUT_DIR / f"minutes_model_v7_{timestamp}.cbm"))
ppm_model.save_model(str(MODEL_OUTPUT_DIR / f"ppm_model_v7_{timestamp}.cbm"))
aug_model.save_model(str(MODEL_OUTPUT_DIR / f"augmented_model_v7_{timestamp}.cbm"))

metadata = {
    'timestamp': timestamp,
    'results': {name: float(mae) for name, mae in results.items()},
    'best_model': best_name,
    'best_mae': float(best_mae),
    'minutes_mae': float(minutes_mae),
    'ppm_mae': float(ppm_mae),
    'v6_baseline': V6_MAE,
    'v7_ensemble_baseline': V7_ENSEMBLE_MAE,
    'optimal_blend_weight': float(best_weight)
}

with open(MODEL_OUTPUT_DIR / f"two_stage_v7_{timestamp}_metadata.json", 'w') as f:
    json.dump(metadata, f, indent=2)

print(f"Saved models and metadata")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"\nTwo-stage approach results:")
print(f"  Pure two-stage: {two_stage_mae:.4f}")
print(f"  Best hybrid: {best_mae:.4f}")
print(f"  v7 ensemble: {V7_ENSEMBLE_MAE:.4f}")
print()

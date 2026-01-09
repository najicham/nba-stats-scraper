#!/usr/bin/env python3
"""
Train XGBoost v7 Model - Adding Vegas Lines + Opponent History Features

This script extends v6 by adding:
1. Vegas betting lines (consensus closing line, opening line, line movement)
2. Player-vs-opponent historical performance

Key additions over v6:
- vegas_points_line: Market consensus prediction
- vegas_opening_line: Where the line opened
- vegas_line_move: Line movement (closing - opening)
- has_vegas_line: Indicator for Vegas coverage
- avg_points_vs_opponent: Player's historical avg vs this team
- games_vs_opponent: Sample size for above

Expected improvement: 0.05-0.15 MAE reduction (from 4.14 to ~4.00)

Usage:
    PYTHONPATH=. python ml/train_xgboost_v7.py
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import xgboost as xgb
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error, mean_squared_error

# Configuration
PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models")
MODEL_OUTPUT_DIR.mkdir(exist_ok=True)

print("=" * 80)
print(" XGBOOST V7 TRAINING - VEGAS LINES + OPPONENT HISTORY")
print("=" * 80)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================================================
# STEP 1: LOAD BASE FEATURES + VEGAS + OPPONENT HISTORY
# ============================================================================

print("=" * 80)
print("STEP 1: LOADING DATA WITH VEGAS & OPPONENT FEATURES")
print("=" * 80)

client = bigquery.Client(project=PROJECT_ID)

# Complex query that joins:
# 1. ml_feature_store_v2 (25 base features)
# 2. bettingpros_player_points_props (Vegas lines)
# 3. player_game_summary (actuals + opponent history)
query = """
WITH
-- Base features from feature store
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

-- Vegas consensus lines (deduplicated to one row per player/game)
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

-- Player vs opponent historical stats (excluding current game)
opponent_history AS (
  SELECT
    pgs1.player_lookup,
    pgs1.game_date,
    pgs1.opponent_team_abbr,
    -- Historical average vs this opponent (games before current date)
    AVG(pgs2.points) as avg_points_vs_opponent,
    COUNT(pgs2.points) as games_vs_opponent
  FROM `nba-props-platform.nba_analytics.player_game_summary` pgs1
  LEFT JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs2
    ON pgs1.player_lookup = pgs2.player_lookup
    AND pgs1.opponent_team_abbr = pgs2.opponent_team_abbr
    AND pgs2.game_date < pgs1.game_date  -- Only historical games
    AND pgs2.game_date >= DATE_SUB(pgs1.game_date, INTERVAL 3 YEAR)  -- Last 3 years
    AND pgs2.points IS NOT NULL
  WHERE pgs1.game_date BETWEEN '2021-11-01' AND '2024-06-01'
  GROUP BY pgs1.player_lookup, pgs1.game_date, pgs1.opponent_team_abbr
),

-- Actual points (target variable)
actuals AS (
  SELECT
    player_lookup,
    game_date,
    points as actual_points,
    -- Also get season average for imputation
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
  fd.opponent_team_abbr,

  -- Vegas features (with null handling)
  v.vegas_points_line,
  v.vegas_opening_line,
  v.vegas_line_move,
  CASE WHEN v.vegas_points_line IS NOT NULL THEN 1.0 ELSE 0.0 END as has_vegas_line,

  -- Opponent history features
  oh.avg_points_vs_opponent,
  COALESCE(oh.games_vs_opponent, 0) as games_vs_opponent,

  -- Target and imputation helper
  a.actual_points,
  a.player_season_avg

FROM feature_data fd
INNER JOIN actuals a
  ON fd.player_lookup = a.player_lookup
  AND fd.game_date = a.game_date
LEFT JOIN vegas_lines v
  ON fd.player_lookup = v.player_lookup
  AND fd.game_date = v.game_date
LEFT JOIN opponent_history oh
  ON fd.player_lookup = oh.player_lookup
  AND fd.game_date = oh.game_date

ORDER BY fd.game_date, fd.player_lookup
"""

print("Fetching data from BigQuery (this may take a minute)...")
print("Date range: 2021-11-01 to 2024-06-01")
print()

df = client.query(query).to_dataframe()

print(f"Loaded {len(df):,} player-game samples")
print(f"Date range: {df['game_date'].min()} to {df['game_date'].max()}")
print(f"Unique players: {df['player_lookup'].nunique()}")
print()

# ============================================================================
# STEP 2: PREPARE FEATURES (BASE + VEGAS + OPPONENT)
# ============================================================================

print("=" * 80)
print("STEP 2: PREPARING EXPANDED FEATURE SET")
print("=" * 80)

# Original 25 features
base_feature_names = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct"
]

# New features
new_feature_names = [
    "vegas_points_line",      # Market consensus
    "vegas_opening_line",     # Where line started
    "vegas_line_move",        # Line movement
    "has_vegas_line",         # Coverage indicator
    "avg_points_vs_opponent", # Historical vs this team
    "games_vs_opponent"       # Sample size
]

all_feature_names = base_feature_names + new_feature_names

print(f"Base features: {len(base_feature_names)}")
print(f"New features: {len(new_feature_names)}")
print(f"Total features: {len(all_feature_names)}")
print()

# Extract base features
print("Extracting base features from arrays...")
X_base = pd.DataFrame(df['features'].tolist(), columns=base_feature_names)

# Extract new features
print("Adding Vegas and opponent history features...")

# Vegas features - impute missing with player season average
vegas_coverage = df['has_vegas_line'].mean()
print(f"Vegas line coverage: {vegas_coverage:.1%}")

# For missing Vegas lines, use the player's season average (feature 2: points_avg_season)
df['vegas_points_line_imputed'] = df['vegas_points_line'].fillna(df['player_season_avg'])
df['vegas_opening_line_imputed'] = df['vegas_opening_line'].fillna(df['player_season_avg'])
df['vegas_line_move_imputed'] = df['vegas_line_move'].fillna(0)  # No movement if no line

# Opponent history - impute missing with season average
opponent_coverage = df['avg_points_vs_opponent'].notna().mean()
print(f"Opponent history coverage: {opponent_coverage:.1%}")
df['avg_points_vs_opponent_imputed'] = df['avg_points_vs_opponent'].fillna(df['player_season_avg'])

# Build new feature columns
X_new = pd.DataFrame({
    'vegas_points_line': df['vegas_points_line_imputed'],
    'vegas_opening_line': df['vegas_opening_line_imputed'],
    'vegas_line_move': df['vegas_line_move_imputed'],
    'has_vegas_line': df['has_vegas_line'],
    'avg_points_vs_opponent': df['avg_points_vs_opponent_imputed'],
    'games_vs_opponent': df['games_vs_opponent']
})

# Combine all features
X = pd.concat([X_base, X_new], axis=1)
y = df['actual_points'].astype(float)

# Handle any remaining nulls
print("Checking for null values...")
null_counts = X.isnull().sum()
if null_counts.sum() > 0:
    print(f"Found {null_counts.sum()} null values:")
    for col in null_counts[null_counts > 0].index:
        print(f"  {col}: {null_counts[col]}")
    print("Filling with median...")
    X = X.fillna(X.median())
else:
    print("No null values!")
print()

print(f"Feature matrix shape: {X.shape}")
print(f"Target vector shape: {y.shape}")
print()

# Print new feature statistics
print("New feature statistics:")
print("-" * 50)
for feat in new_feature_names:
    print(f"  {feat:25s} mean={X[feat].mean():7.2f}  std={X[feat].std():6.2f}")
print()

# ============================================================================
# STEP 3: CHRONOLOGICAL TRAIN/VAL/TEST SPLIT
# ============================================================================

print("=" * 80)
print("STEP 3: SPLITTING DATA CHRONOLOGICALLY")
print("=" * 80)

df_sorted = df.sort_values('game_date').reset_index(drop=True)
X = X.iloc[df_sorted.index].reset_index(drop=True)
y = y.iloc[df_sorted.index].reset_index(drop=True)

n = len(df_sorted)

# 70% train, 15% validation, 15% test (same as v6)
train_end = int(n * 0.70)
val_end = int(n * 0.85)

train_idx = range(train_end)
val_idx = range(train_end, val_end)
test_idx = range(val_end, n)

X_train, y_train = X.iloc[train_idx], y.iloc[train_idx]
X_val, y_val = X.iloc[val_idx], y.iloc[val_idx]
X_test, y_test = X.iloc[test_idx], y.iloc[test_idx]

train_dates = df_sorted.iloc[train_idx]
val_dates = df_sorted.iloc[val_idx]
test_dates = df_sorted.iloc[test_idx]

print(f"Training set:   {len(X_train):,} ({train_dates['game_date'].min()} to {train_dates['game_date'].max()})")
print(f"Validation set: {len(X_val):,} ({val_dates['game_date'].min()} to {val_dates['game_date'].max()})")
print(f"Test set:       {len(X_test):,} ({test_dates['game_date'].min()} to {test_dates['game_date'].max()})")
print()

# Check Vegas coverage in each split
for name, idx in [("Train", train_idx), ("Val", val_idx), ("Test", test_idx)]:
    coverage = X.iloc[idx]['has_vegas_line'].mean()
    print(f"{name} Vegas coverage: {coverage:.1%}")
print()

# ============================================================================
# STEP 4: TRAIN XGBOOST V7
# ============================================================================

print("=" * 80)
print("STEP 4: TRAINING XGBOOST V7")
print("=" * 80)

# Same hyperparameters as v6 (proven regularization)
params = {
    'max_depth': 6,
    'min_child_weight': 10,
    'learning_rate': 0.03,
    'n_estimators': 1000,
    'subsample': 0.7,
    'colsample_bytree': 0.7,
    'colsample_bylevel': 0.7,
    'gamma': 0.1,
    'reg_alpha': 0.5,
    'reg_lambda': 5.0,
    'random_state': 42,
    'objective': 'reg:squarederror',
    'eval_metric': 'mae',
    'early_stopping_rounds': 50
}

print("Hyperparameters (same as v6):")
print(f"  max_depth: {params['max_depth']}, min_child_weight: {params['min_child_weight']}")
print(f"  learning_rate: {params['learning_rate']}, reg_lambda: {params['reg_lambda']}")
print()

print(f"Training with {len(all_feature_names)} features...")
print()

model = xgb.XGBRegressor(**params)

model.fit(
    X_train, y_train,
    eval_set=[(X_train, y_train), (X_val, y_val)],
    verbose=50
)

print()
print(f"Training complete! Best iteration: {model.best_iteration}")
print()

# ============================================================================
# STEP 5: EVALUATE MODEL
# ============================================================================

print("=" * 80)
print("STEP 5: EVALUATION")
print("=" * 80)

def evaluate_set(y_true, y_pred, name):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    errors = np.abs(y_true - y_pred)
    within_3 = (errors <= 3).mean() * 100
    within_5 = (errors <= 5).mean() * 100

    print(f"\n{name} Set:")
    print(f"  MAE:  {mae:.3f} points")
    print(f"  RMSE: {rmse:.3f} points")
    print(f"  Within 3 pts: {within_3:.1f}%")
    print(f"  Within 5 pts: {within_5:.1f}%")

    return mae, rmse

train_pred = model.predict(X_train)
val_pred = model.predict(X_val)
test_pred = model.predict(X_test)

train_mae, _ = evaluate_set(y_train, train_pred, "Training")
val_mae, _ = evaluate_set(y_val, val_pred, "Validation")
test_mae, _ = evaluate_set(y_test, test_pred, "Test")

train_test_gap = test_mae - train_mae
print(f"\nTrain/Test Gap: {train_test_gap:.3f} points")

# ============================================================================
# STEP 6: COMPARE TO BASELINES
# ============================================================================

print("\n" + "=" * 80)
print("STEP 6: COMPARISON TO BASELINES")
print("=" * 80)

V6_BASELINE_MAE = 4.14  # XGBoost v6
MOCK_BASELINE_MAE = 4.80  # Mock v1
VEGAS_BASELINE_MAE = 4.97  # Vegas consensus

print(f"\n{'Model':<25} {'MAE':>8} {'vs Mock':>10} {'vs v6':>10}")
print("-" * 55)
print(f"{'Mock v1':<25} {MOCK_BASELINE_MAE:>8.2f} {'baseline':>10} {'+16.0%':>10}")
print(f"{'Vegas Consensus':<25} {VEGAS_BASELINE_MAE:>8.2f} {'+3.5%':>10} {'+20.0%':>10}")
print(f"{'XGBoost v6':<25} {V6_BASELINE_MAE:>8.2f} {'-13.8%':>10} {'baseline':>10}")

v7_vs_mock = ((MOCK_BASELINE_MAE - test_mae) / MOCK_BASELINE_MAE) * 100
v7_vs_v6 = ((V6_BASELINE_MAE - test_mae) / V6_BASELINE_MAE) * 100
print(f"{'XGBoost v7 (NEW)':<25} {test_mae:>8.2f} {v7_vs_mock:>+9.1f}% {v7_vs_v6:>+9.1f}%")

print()
if test_mae < V6_BASELINE_MAE:
    improvement = V6_BASELINE_MAE - test_mae
    print(f"SUCCESS! v7 beats v6 by {improvement:.3f} MAE ({v7_vs_v6:+.1f}%)")
else:
    print(f"v7 did not beat v6 (diff: {test_mae - V6_BASELINE_MAE:+.3f})")

# ============================================================================
# STEP 7: FEATURE IMPORTANCE
# ============================================================================

print("\n" + "=" * 80)
print("STEP 7: FEATURE IMPORTANCE (Top 15)")
print("=" * 80)

importance = model.feature_importances_
feat_imp = pd.DataFrame({
    'feature': all_feature_names,
    'importance': importance
}).sort_values('importance', ascending=False)

print()
print(f"{'Rank':<5} {'Feature':<30} {'Importance':>10} {'Type':>10}")
print("-" * 60)
for rank, (i, row) in enumerate(feat_imp.head(15).iterrows(), 1):
    feat_type = "NEW" if row['feature'] in new_feature_names else "base"
    bar = '█' * int(row['importance'] * 40)
    print(f"{rank:<5} {row['feature']:<30} {row['importance']*100:>9.1f}% {feat_type:>10}")

# Show specifically how new features rank
print()
print("New feature rankings:")
for feat in new_feature_names:
    rank = feat_imp[feat_imp['feature'] == feat].index[0] + 1
    imp = feat_imp[feat_imp['feature'] == feat]['importance'].values[0]
    print(f"  {feat:<25} rank {rank:>2}, importance {imp*100:.1f}%")

# ============================================================================
# STEP 8: ANALYZE VEGAS IMPACT
# ============================================================================

print("\n" + "=" * 80)
print("STEP 8: VEGAS LINE IMPACT ANALYSIS")
print("=" * 80)

# Compare performance on games WITH vs WITHOUT Vegas lines
test_df = df_sorted.iloc[test_idx].copy()
test_df['prediction'] = test_pred
test_df['error'] = np.abs(test_df['actual_points'] - test_df['prediction'])

with_vegas = test_df[test_df['has_vegas_line'] == 1]
without_vegas = test_df[test_df['has_vegas_line'] == 0]

print(f"\nTest set breakdown:")
print(f"  With Vegas line:    {len(with_vegas):,} games, MAE = {with_vegas['error'].mean():.3f}")
print(f"  Without Vegas line: {len(without_vegas):,} games, MAE = {without_vegas['error'].mean():.3f}")

# Compare our predictions vs Vegas on games with Vegas lines
if len(with_vegas) > 0:
    our_mae = with_vegas['error'].mean()
    vegas_error = np.abs(with_vegas['actual_points'] - with_vegas['vegas_points_line'])
    vegas_mae = vegas_error.mean()
    print(f"\nOn Vegas-covered games:")
    print(f"  Our v7 MAE:   {our_mae:.3f}")
    print(f"  Vegas MAE:    {vegas_mae:.3f}")
    print(f"  Improvement:  {((vegas_mae - our_mae) / vegas_mae) * 100:+.1f}%")

# ============================================================================
# STEP 9: SAVE MODEL
# ============================================================================

print("\n" + "=" * 80)
print("STEP 9: SAVING MODEL")
print("=" * 80)

model_id = f"xgboost_v7_31features_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
model_path = MODEL_OUTPUT_DIR / f"{model_id}.json"

model.get_booster().save_model(str(model_path))
print(f"Model saved: {model_path}")

metadata = {
    'model_id': model_id,
    'version': 'v7',
    'trained_at': datetime.now().isoformat(),
    'training_samples': len(df),
    'features': all_feature_names,
    'base_features': base_feature_names,
    'new_features': new_feature_names,
    'feature_count': len(all_feature_names),
    'train_mae': float(train_mae),
    'val_mae': float(val_mae),
    'test_mae': float(test_mae),
    'train_test_gap': float(train_test_gap),
    'v6_baseline_mae': V6_BASELINE_MAE,
    'improvement_vs_v6_pct': float(v7_vs_v6),
    'mock_baseline_mae': MOCK_BASELINE_MAE,
    'improvement_vs_mock_pct': float(v7_vs_mock),
    'vegas_baseline_mae': VEGAS_BASELINE_MAE,
    'vegas_coverage_train': float(X.iloc[train_idx]['has_vegas_line'].mean()),
    'vegas_coverage_test': float(X.iloc[test_idx]['has_vegas_line'].mean()),
    'hyperparameters': params,
    'best_iteration': model.best_iteration
}

metadata_path = MODEL_OUTPUT_DIR / f"{model_id}_metadata.json"
with open(metadata_path, 'w') as f:
    json.dump(metadata, f, indent=2, default=str)
print(f"Metadata saved: {metadata_path}")

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 80)
print("TRAINING COMPLETE - SUMMARY")
print("=" * 80)
print()
print(f"Model:              XGBoost v7")
print(f"Features:           {len(all_feature_names)} (25 base + 6 new)")
print(f"Training samples:   {len(df):,}")
print(f"Vegas coverage:     {vegas_coverage:.1%}")
print()
print(f"Training MAE:       {train_mae:.3f}")
print(f"Validation MAE:     {val_mae:.3f}")
print(f"Test MAE:           {test_mae:.3f}")
print(f"Train/Test Gap:     {train_test_gap:.3f}")
print()
print(f"XGBoost v6:         {V6_BASELINE_MAE:.2f}")
print(f"Improvement vs v6:  {v7_vs_v6:+.1f}%")
print()

if test_mae < V6_BASELINE_MAE:
    print("RESULT: XGBoost v7 WINS!")
    print(f"New best MAE: {test_mae:.3f}")
else:
    print("RESULT: v6 still better - Vegas features didn't help")
    print("Consider: Features may need different handling")

print()
print("=" * 80)

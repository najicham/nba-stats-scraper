#!/usr/bin/env python3
"""
Validate XGBoost v6 on Current 2024-25 Season Data

This script tests the v6 model on truly unseen data from the current season
to validate that the 3.95 MAE result generalizes.

Training period: 2021-11-01 to 2024-05-30 (what v6 was trained on)
Validation period: 2024-10-22 to present (current 2024-25 season - NEVER SEEN)
"""

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import xgboost as xgb
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error, mean_squared_error

PROJECT_ID = "nba-props-platform"

print("=" * 80)
print(" XGBOOST V6 VALIDATION ON 2024-25 SEASON (UNSEEN DATA)")
print("=" * 80)
print(f"Validation started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================================================
# STEP 1: LOAD THE TRAINED MODEL
# ============================================================================

print("=" * 80)
print("STEP 1: LOADING V6 MODEL")
print("=" * 80)

# Find the latest v6 model (exclude metadata files)
model_dir = Path("models")
v6_models = [f for f in model_dir.glob("xgboost_v6_*.json") if "metadata" not in f.name]
if not v6_models:
    print("ERROR: No v6 model found!")
    sys.exit(1)

latest_model = sorted(v6_models)[-1]
print(f"Loading model: {latest_model}")

model = xgb.Booster()
model.load_model(str(latest_model))
print("Model loaded successfully!")
print()

# ============================================================================
# STEP 2: LOAD CURRENT SEASON DATA
# ============================================================================

print("=" * 80)
print("STEP 2: LOADING 2024-25 SEASON DATA")
print("=" * 80)

client = bigquery.Client(project=PROJECT_ID)

# Query current season data (never seen during training)
query = """
WITH feature_data AS (
  SELECT
    mf.player_lookup,
    mf.game_date,
    mf.features,
    mf.feature_quality_score,
    mf.completeness_percentage
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
  WHERE mf.game_date >= '2024-10-22'  -- 2024-25 season start
    AND mf.game_date <= CURRENT_DATE()
    AND mf.feature_count = 25
    AND ARRAY_LENGTH(mf.features) = 25
),
actuals AS (
  SELECT
    player_lookup,
    game_date,
    points as actual_points,
    minutes_played,
    usage_rate
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2024-10-22'
    AND game_date <= CURRENT_DATE()
    AND points IS NOT NULL
)
SELECT
  fd.player_lookup,
  fd.game_date,
  fd.features,
  fd.feature_quality_score,
  fd.completeness_percentage,
  a.actual_points,
  a.minutes_played,
  a.usage_rate
FROM feature_data fd
INNER JOIN actuals a
  ON fd.player_lookup = a.player_lookup
  AND fd.game_date = a.game_date
ORDER BY fd.game_date, fd.player_lookup
"""

print("Fetching 2024-25 season data...")
df = client.query(query).to_dataframe()

print(f"Loaded {len(df):,} player-game samples")
print(f"Date range: {df['game_date'].min()} to {df['game_date'].max()}")
print(f"Unique players: {df['player_lookup'].nunique()}")
print(f"Unique game dates: {df['game_date'].nunique()}")
print()

# ============================================================================
# STEP 3: PREPARE FEATURES AND RUN PREDICTIONS
# ============================================================================

print("=" * 80)
print("STEP 3: RUNNING V6 PREDICTIONS")
print("=" * 80)

# Feature names (must match training)
feature_names = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct"
]

# Extract features
X = pd.DataFrame(df['features'].tolist(), columns=feature_names)
y_actual = df['actual_points'].astype(float)

# Handle any nulls
X = X.fillna(X.median())

print(f"Feature matrix: {X.shape}")
print("Running predictions...")

# Create DMatrix for prediction
dmatrix = xgb.DMatrix(X, feature_names=feature_names)
y_pred = model.predict(dmatrix)

print(f"Generated {len(y_pred):,} predictions")
print()

# ============================================================================
# STEP 4: EVALUATE PERFORMANCE
# ============================================================================

print("=" * 80)
print("STEP 4: EVALUATION RESULTS")
print("=" * 80)

# Overall metrics
mae = mean_absolute_error(y_actual, y_pred)
rmse = np.sqrt(mean_squared_error(y_actual, y_pred))
errors = np.abs(y_actual - y_pred)
within_3 = (errors <= 3).mean() * 100
within_5 = (errors <= 5).mean() * 100

print(f"\n{'='*50}")
print(f"XGBOOST V6 ON 2024-25 SEASON (UNSEEN DATA)")
print(f"{'='*50}")
print(f"MAE:           {mae:.3f} points")
print(f"RMSE:          {rmse:.3f} points")
print(f"Within 3 pts:  {within_3:.1f}%")
print(f"Within 5 pts:  {within_5:.1f}%")
print(f"Samples:       {len(y_actual):,}")
print()

# Compare to baselines
print(f"{'='*50}")
print(f"COMPARISON TO BASELINES")
print(f"{'='*50}")
MOCK_BASELINE = 4.80  # From Phase 1 evaluation
TRAINING_MAE = 3.95   # From v6 training test set

print(f"V6 on training test set:    {TRAINING_MAE:.2f} MAE")
print(f"V6 on 2024-25 season:       {mae:.2f} MAE")
print(f"Mock v1 baseline:           {MOCK_BASELINE:.2f} MAE")
print()

drift = mae - TRAINING_MAE
print(f"Drift from training:        {drift:+.3f} points")

improvement_vs_mock = ((MOCK_BASELINE - mae) / MOCK_BASELINE) * 100
print(f"Improvement vs mock:        {improvement_vs_mock:+.1f}%")
print()

if mae < MOCK_BASELINE:
    print("✅ V6 STILL BEATS MOCK ON UNSEEN 2024-25 DATA!")
else:
    print("❌ V6 does not beat mock on 2024-25 data")

# ============================================================================
# STEP 5: ANALYZE BY SEGMENTS
# ============================================================================

print("\n" + "=" * 80)
print("STEP 5: SEGMENT ANALYSIS")
print("=" * 80)

# Add predictions to dataframe for analysis
df['predicted'] = y_pred
df['error'] = np.abs(df['actual_points'] - df['predicted'])
df['signed_error'] = df['predicted'] - df['actual_points']

# By month
print("\nPerformance by Month:")
print("-" * 50)
df['month'] = pd.to_datetime(df['game_date']).dt.to_period('M')
monthly = df.groupby('month').agg({
    'error': 'mean',
    'actual_points': 'count'
}).rename(columns={'error': 'MAE', 'actual_points': 'Games'})
print(monthly.to_string())

# By minutes played
print("\n\nPerformance by Minutes Played:")
print("-" * 50)
df['minutes_played'] = pd.to_numeric(df['minutes_played'], errors='coerce').fillna(0)
df['minutes_bucket'] = pd.cut(df['minutes_played'],
                               bins=[0, 15, 25, 35, 50],
                               labels=['<15 min', '15-25 min', '25-35 min', '35+ min'])
by_minutes = df.groupby('minutes_bucket').agg({
    'error': 'mean',
    'actual_points': 'count',
    'signed_error': 'mean'
}).rename(columns={'error': 'MAE', 'actual_points': 'Games', 'signed_error': 'Bias'})
print(by_minutes.to_string())

# By actual points scored
print("\n\nPerformance by Actual Points Scored:")
print("-" * 50)
df['points_bucket'] = pd.cut(df['actual_points'],
                              bins=[0, 10, 20, 30, 100],
                              labels=['0-10 pts', '10-20 pts', '20-30 pts', '30+ pts'])
by_points = df.groupby('points_bucket').agg({
    'error': 'mean',
    'actual_points': 'count',
    'signed_error': 'mean'
}).rename(columns={'error': 'MAE', 'actual_points': 'Games', 'signed_error': 'Bias'})
print(by_points.to_string())

# ============================================================================
# STEP 6: WORST PREDICTIONS ANALYSIS
# ============================================================================

print("\n" + "=" * 80)
print("STEP 6: WORST PREDICTIONS (Errors > 15 points)")
print("=" * 80)

worst = df[df['error'] > 15].sort_values('error', ascending=False).head(10)
print(f"\nFound {len(df[df['error'] > 15])} predictions with error > 15 points")
print(f"\nTop 10 Worst Predictions:")
print("-" * 70)
for _, row in worst.iterrows():
    print(f"{row['player_lookup'][:30]:30s} {row['game_date']} | "
          f"Pred: {row['predicted']:.1f}, Actual: {row['actual_points']:.0f}, "
          f"Error: {row['error']:.1f}")

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 80)
print("VALIDATION SUMMARY")
print("=" * 80)
print()
print(f"Model:                XGBoost v6")
print(f"Validation period:    2024-25 season ({df['game_date'].min()} to {df['game_date'].max()})")
print(f"Samples:              {len(df):,} player-games")
print()
print(f"Training test MAE:    {TRAINING_MAE:.2f}")
print(f"Current season MAE:   {mae:.2f}")
print(f"Drift:                {drift:+.2f}")
print()
print(f"Mock v1 baseline:     {MOCK_BASELINE:.2f}")
print(f"V6 improvement:       {improvement_vs_mock:+.1f}%")
print()

if mae < 4.20:
    print("🎉 EXCELLENT: V6 maintains strong performance on unseen data!")
elif mae < MOCK_BASELINE:
    print("✅ GOOD: V6 still beats mock but with some degradation")
else:
    print("⚠️ WARNING: V6 underperforms on current season data")

print()
print("=" * 80)

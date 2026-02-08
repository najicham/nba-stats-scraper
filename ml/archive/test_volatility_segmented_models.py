#!/usr/bin/env python3
"""
Test Volatility-Segmented Models

Key insight from analysis: Low-volatility players have 1.81 MAE while
high-volatility players have 6.90 MAE. This suggests training separate
models might help.

Also tests usage-tier segmented models.
"""

import os
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import xgboost as xgb
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
import json

PROJECT_ID = "nba-props-platform"

print("=" * 80)
print(" VOLATILITY & USAGE SEGMENTED MODELS TEST")
print("=" * 80)
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# Load data
client = bigquery.Client(project=PROJECT_ID)
query = """
WITH feature_data AS (
  SELECT
    mf.player_lookup,
    mf.game_date,
    mf.features
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
  WHERE mf.game_date BETWEEN '2021-11-01' AND '2024-06-01'
    AND mf.feature_count = 25
    AND ARRAY_LENGTH(mf.features) = 25
),
actuals AS (
  SELECT
    player_lookup,
    game_date,
    points as actual_points
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN '2021-11-01' AND '2024-06-01'
    AND points IS NOT NULL
)
SELECT
  fd.player_lookup,
  fd.game_date,
  fd.features,
  a.actual_points
FROM feature_data fd
INNER JOIN actuals a
  ON fd.player_lookup = a.player_lookup
  AND fd.game_date = a.game_date
ORDER BY fd.game_date
"""

print("Loading training data...")
df = client.query(query).to_dataframe()
print(f"Loaded {len(df):,} training samples")

# Feature names
feature_names = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct"
]

X = pd.DataFrame(df['features'].tolist(), columns=feature_names)
X = X.fillna(X.median())
y = df['actual_points'].astype(float)

# Chronological split
n = len(df)
train_end = int(n * 0.70)
val_end = int(n * 0.85)

X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
X_val, y_val = X.iloc[train_end:val_end], y.iloc[train_end:val_end]
X_test, y_test = X.iloc[val_end:], y.iloc[val_end:]

print(f"Train: {len(X_train):,}, Val: {len(X_val):,}, Test: {len(X_test):,}")

# Same hyperparameters as v6
params = {
    'max_depth': 6,
    'min_child_weight': 10,
    'learning_rate': 0.03,
    'n_estimators': 500,
    'subsample': 0.7,
    'colsample_bytree': 0.7,
    'colsample_bylevel': 0.7,
    'gamma': 0.1,
    'reg_alpha': 0.5,
    'reg_lambda': 5.0,
    'random_state': 42,
    'objective': 'reg:squarederror',
    'eval_metric': 'mae',
    'early_stopping_rounds': 30
}

# ============================================================================
# BASELINE: Single unified model
# ============================================================================

print("\n" + "=" * 60)
print("BASELINE: Single Unified Model")
print("=" * 60)

baseline_model = xgb.XGBRegressor(**params)
baseline_model.fit(X_train, y_train,
                   eval_set=[(X_val, y_val)],
                   verbose=False)

baseline_pred = baseline_model.predict(X_test)
baseline_mae = mean_absolute_error(y_test, baseline_pred)
print(f"Baseline MAE: {baseline_mae:.3f}")

# ============================================================================
# EXPERIMENT 1: Volatility-Segmented Models
# ============================================================================

print("\n" + "=" * 60)
print("EXPERIMENT 1: Volatility-Segmented Models")
print("=" * 60)

# Get volatility (points_std_last_10) for segmentation
train_std = X_train['points_std_last_10'].values
test_std = X_test['points_std_last_10'].values

# Define segments
LOW_VOL_THRESHOLD = 4
HIGH_VOL_THRESHOLD = 7

train_low = train_std < LOW_VOL_THRESHOLD
train_med = (train_std >= LOW_VOL_THRESHOLD) & (train_std < HIGH_VOL_THRESHOLD)
train_high = train_std >= HIGH_VOL_THRESHOLD

test_low = test_std < LOW_VOL_THRESHOLD
test_med = (test_std >= LOW_VOL_THRESHOLD) & (test_std < HIGH_VOL_THRESHOLD)
test_high = test_std >= HIGH_VOL_THRESHOLD

print(f"Training segments: Low={train_low.sum()}, Med={train_med.sum()}, High={train_high.sum()}")
print(f"Test segments: Low={test_low.sum()}, Med={test_med.sum()}, High={test_high.sum()}")

# Train segment-specific models
segmented_preds = np.zeros(len(X_test))

for segment_name, train_mask, test_mask in [
    ('Low volatility', train_low, test_low),
    ('Medium volatility', train_med, test_med),
    ('High volatility', train_high, test_high)
]:
    if train_mask.sum() < 100 or test_mask.sum() < 10:
        print(f"  {segment_name}: Skipping (insufficient samples)")
        # Use baseline for these
        segmented_preds[test_mask] = baseline_pred[test_mask]
        continue

    print(f"\n  Training {segment_name} model ({train_mask.sum()} samples)...")
    seg_model = xgb.XGBRegressor(**params)

    # Need to also split validation set by segment
    val_mask = X_val['points_std_last_10'].values
    if segment_name == 'Low volatility':
        val_seg = val_mask < LOW_VOL_THRESHOLD
    elif segment_name == 'Medium volatility':
        val_seg = (val_mask >= LOW_VOL_THRESHOLD) & (val_mask < HIGH_VOL_THRESHOLD)
    else:
        val_seg = val_mask >= HIGH_VOL_THRESHOLD

    if val_seg.sum() < 10:
        # Use full validation set if segment too small
        seg_model.fit(X_train[train_mask], y_train.iloc[train_mask],
                     eval_set=[(X_val, y_val)],
                     verbose=False)
    else:
        seg_model.fit(X_train[train_mask], y_train.iloc[train_mask],
                     eval_set=[(X_val[val_seg], y_val.iloc[val_seg])],
                     verbose=False)

    seg_pred = seg_model.predict(X_test[test_mask])
    segmented_preds[test_mask] = seg_pred

    seg_mae = mean_absolute_error(y_test.iloc[test_mask], seg_pred)
    baseline_seg_mae = mean_absolute_error(y_test.iloc[test_mask], baseline_pred[test_mask])
    print(f"    {segment_name} MAE: {seg_mae:.3f} (baseline: {baseline_seg_mae:.3f}, Δ={seg_mae-baseline_seg_mae:+.3f})")

segmented_mae = mean_absolute_error(y_test, segmented_preds)
print(f"\nSegmented Model Overall MAE: {segmented_mae:.3f}")
print(f"Improvement over baseline: {baseline_mae - segmented_mae:.3f}")

# ============================================================================
# EXPERIMENT 2: Usage-Tier Segmented Models
# ============================================================================

print("\n" + "=" * 60)
print("EXPERIMENT 2: Usage-Tier Segmented Models")
print("=" * 60)

# We don't have usage_rate in our features directly, but we have usage_spike_score
# Let's use points_avg_season as a proxy for player tier

train_avg = X_train['points_avg_season'].values
test_avg = X_test['points_avg_season'].values

# Define tiers based on scoring average
ROLE_LOW = 10   # Bench players
ROLE_HIGH = 18  # Starters/stars

train_bench = train_avg < ROLE_LOW
train_rotation = (train_avg >= ROLE_LOW) & (train_avg < ROLE_HIGH)
train_star = train_avg >= ROLE_HIGH

test_bench = test_avg < ROLE_LOW
test_rotation = (test_avg >= ROLE_LOW) & (test_avg < ROLE_HIGH)
test_star = test_avg >= ROLE_HIGH

print(f"Training tiers: Bench={train_bench.sum()}, Rotation={train_rotation.sum()}, Star={train_star.sum()}")
print(f"Test tiers: Bench={test_bench.sum()}, Rotation={test_rotation.sum()}, Star={test_star.sum()}")

tier_preds = np.zeros(len(X_test))

for tier_name, train_mask, test_mask in [
    ('Bench (<10 ppg)', train_bench, test_bench),
    ('Rotation (10-18 ppg)', train_rotation, test_rotation),
    ('Star (18+ ppg)', train_star, test_star)
]:
    if train_mask.sum() < 100 or test_mask.sum() < 10:
        print(f"  {tier_name}: Skipping (insufficient samples)")
        tier_preds[test_mask] = baseline_pred[test_mask]
        continue

    print(f"\n  Training {tier_name} model ({train_mask.sum()} samples)...")
    tier_model = xgb.XGBRegressor(**params)

    # Get validation mask
    val_avg = X_val['points_avg_season'].values
    if tier_name == 'Bench (<10 ppg)':
        val_mask = val_avg < ROLE_LOW
    elif tier_name == 'Rotation (10-18 ppg)':
        val_mask = (val_avg >= ROLE_LOW) & (val_avg < ROLE_HIGH)
    else:
        val_mask = val_avg >= ROLE_HIGH

    if val_mask.sum() < 10:
        tier_model.fit(X_train[train_mask], y_train.iloc[train_mask],
                      eval_set=[(X_val, y_val)],
                      verbose=False)
    else:
        tier_model.fit(X_train[train_mask], y_train.iloc[train_mask],
                      eval_set=[(X_val[val_mask], y_val.iloc[val_mask])],
                      verbose=False)

    t_pred = tier_model.predict(X_test[test_mask])
    tier_preds[test_mask] = t_pred

    tier_mae = mean_absolute_error(y_test.iloc[test_mask], t_pred)
    baseline_tier_mae = mean_absolute_error(y_test.iloc[test_mask], baseline_pred[test_mask])
    print(f"    {tier_name} MAE: {tier_mae:.3f} (baseline: {baseline_tier_mae:.3f}, Δ={tier_mae-baseline_tier_mae:+.3f})")

tier_mae_overall = mean_absolute_error(y_test, tier_preds)
print(f"\nTier-Segmented Model Overall MAE: {tier_mae_overall:.3f}")
print(f"Improvement over baseline: {baseline_mae - tier_mae_overall:.3f}")

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

print(f"\n{'Model':<35} {'MAE':<10} {'Δ vs Baseline':<15}")
print("-" * 60)
print(f"{'Baseline (single model)':<35} {baseline_mae:<10.3f} {'--':<15}")
print(f"{'Volatility-segmented':<35} {segmented_mae:<10.3f} {baseline_mae - segmented_mae:<+15.3f}")
print(f"{'Tier-segmented':<35} {tier_mae_overall:<10.3f} {baseline_mae - tier_mae_overall:<+15.3f}")

best_mae = min(baseline_mae, segmented_mae, tier_mae_overall)
if best_mae == baseline_mae:
    print("\nBest approach: Baseline (single model)")
elif best_mae == segmented_mae:
    print(f"\nBest approach: Volatility-segmented (improvement: {baseline_mae - segmented_mae:.3f})")
else:
    print(f"\nBest approach: Tier-segmented (improvement: {baseline_mae - tier_mae_overall:.3f})")

print("\n" + "=" * 60)

#!/usr/bin/env python3
"""
Train XGBoost Model for MLB Pitcher Strikeout Predictions

This script trains an XGBoost model on historical MLB data to predict
pitcher strikeouts. Key innovation: bottom-up model using individual
batter K rates.

Usage:
    PYTHONPATH=. python scripts/mlb/train_pitcher_strikeouts.py

Expected performance:
    - Baseline (bottom-up formula): MAE 1.92
    - With ML: MAE 1.5-1.7 (target)
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error, mean_squared_error

# Configuration
PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models/mlb")
MODEL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 80)
print(" MLB PITCHER STRIKEOUT MODEL TRAINING")
print("=" * 80)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================================================
# STEP 1: LOAD TRAINING DATA FROM BIGQUERY
# ============================================================================

print("=" * 80)
print("STEP 1: LOADING TRAINING DATA")
print("=" * 80)

client = bigquery.Client(project=PROJECT_ID)

# Query to get training data with actual strikeout outcomes
# We join pitcher game summary (features) with raw stats (actual Ks)
query = """
WITH pitcher_games AS (
    -- Get pitcher game stats with rolling features
    SELECT
        pgs.player_lookup,
        pgs.game_date,
        pgs.game_id,
        pgs.team_abbr,
        pgs.opponent_team_abbr,
        pgs.season_year,

        -- Target variable (WHAT WE PREDICT)
        pgs.strikeouts as actual_strikeouts,
        pgs.innings_pitched as actual_innings,

        -- Game context
        pgs.is_home,
        pgs.is_postseason,
        pgs.days_rest,

        -- Recent performance features (f00-f04)
        pgs.k_avg_last_3 as f00_k_avg_last_3,
        pgs.k_avg_last_5 as f01_k_avg_last_5,
        pgs.k_avg_last_10 as f02_k_avg_last_10,
        pgs.k_std_last_10 as f03_k_std_last_10,
        pgs.ip_avg_last_5 as f04_ip_avg_last_5,

        -- Season baseline features (f05-f09)
        pgs.season_k_per_9 as f05_season_k_per_9,
        SAFE_DIVIDE(pgs.earned_runs * 9, pgs.innings_pitched) as f06_season_era,
        pgs.whip_rolling_10 as f07_season_whip,
        pgs.season_games_started as f08_season_games,
        pgs.season_strikeouts as f09_season_k_total,

        -- Split adjustments (f10-f14) - simplified
        IF(pgs.is_home, 1.0, 0.0) as f10_is_home,
        0.0 as f11_home_away_k_diff,  -- Placeholder
        0.0 as f12_is_day_game,  -- Placeholder
        0.0 as f13_day_night_k_diff,  -- Placeholder
        0.0 as f14_vs_opponent_k_rate,  -- Placeholder

        -- Workload features (f20-f24)
        COALESCE(pgs.days_rest, 5) as f20_days_rest,
        pgs.games_last_30_days as f21_games_last_30_days,
        pgs.pitch_count_avg_last_5 as f22_pitch_count_avg,
        pgs.season_innings as f23_season_ip_total,
        IF(pgs.is_postseason, 1.0, 0.0) as f24_is_postseason,

        -- Data quality
        pgs.data_completeness_score,
        pgs.rolling_stats_games

    FROM `nba-props-platform.mlb_analytics.pitcher_game_summary` pgs
    WHERE pgs.strikeouts IS NOT NULL
      AND pgs.innings_pitched >= 3.0  -- Starter threshold
      AND pgs.rolling_stats_games >= 3  -- Minimum history
      AND pgs.season_year IN (2024, 2025)
),

-- Join with lineup K analysis for bottom-up features
lineup_features AS (
    SELECT
        pg.*,

        -- Bottom-up model features (f25-f29) - THE KEY INNOVATION
        lka.bottom_up_expected_k as f25_bottom_up_k_expected,
        lka.lineup_k_rate_vs_hand as f26_lineup_k_vs_hand,
        COALESCE(lka.weak_spot_count, 0) as f33_lineup_weak_spots,
        lka.data_completeness_pct as lineup_data_completeness

    FROM pitcher_games pg
    LEFT JOIN `nba-props-platform.mlb_precompute.lineup_k_analysis` lka
        ON pg.player_lookup = lka.pitcher_lookup
        AND pg.game_date = lka.game_date
)

SELECT
    player_lookup,
    game_date,
    game_id,
    team_abbr,
    opponent_team_abbr,
    season_year,

    -- Target
    actual_strikeouts,
    actual_innings,

    -- Features (25 active features for now)
    -- Recent performance (f00-f04)
    COALESCE(f00_k_avg_last_3, 5.0) as f00_k_avg_last_3,
    COALESCE(f01_k_avg_last_5, 5.0) as f01_k_avg_last_5,
    COALESCE(f02_k_avg_last_10, 5.0) as f02_k_avg_last_10,
    COALESCE(f03_k_std_last_10, 2.0) as f03_k_std_last_10,
    COALESCE(f04_ip_avg_last_5, 5.5) as f04_ip_avg_last_5,

    -- Season baseline (f05-f09)
    COALESCE(f05_season_k_per_9, 8.5) as f05_season_k_per_9,
    COALESCE(f06_season_era, 4.0) as f06_season_era,
    COALESCE(f07_season_whip, 1.3) as f07_season_whip,
    COALESCE(f08_season_games, 5) as f08_season_games,
    COALESCE(f09_season_k_total, 30) as f09_season_k_total,

    -- Split adjustments (f10-f14)
    f10_is_home,
    f11_home_away_k_diff,
    f12_is_day_game,
    f13_day_night_k_diff,
    f14_vs_opponent_k_rate,

    -- Workload (f20-f24)
    f20_days_rest,
    f21_games_last_30_days,
    COALESCE(f22_pitch_count_avg, 90.0) as f22_pitch_count_avg,
    COALESCE(f23_season_ip_total, 50.0) as f23_season_ip_total,
    f24_is_postseason,

    -- Bottom-up model (f25) - KEY FEATURE
    COALESCE(f25_bottom_up_k_expected, 5.0) as f25_bottom_up_k_expected,
    COALESCE(f26_lineup_k_vs_hand, 0.22) as f26_lineup_k_vs_hand,

    -- Weak spots (f33)
    COALESCE(f33_lineup_weak_spots, 2) as f33_lineup_weak_spots,

    -- Data quality
    data_completeness_score,
    lineup_data_completeness

FROM lineup_features
WHERE actual_strikeouts IS NOT NULL
ORDER BY game_date, player_lookup
"""

print("Fetching data from BigQuery...")
print("Date range: 2024-2025 seasons")
print()

try:
    df = client.query(query).to_dataframe()
    print(f"Loaded {len(df):,} pitcher starts")
    print(f"  Date range: {df['game_date'].min()} to {df['game_date'].max()}")
    print(f"  Unique pitchers: {df['player_lookup'].nunique()}")
    print(f"  Avg strikeouts: {df['actual_strikeouts'].mean():.2f}")
    print()
except Exception as e:
    print(f"ERROR loading data: {e}")
    print("\nFalling back to simplified query without lineup features...")

    # Simplified query without lineup_k_analysis join
    simple_query = """
    SELECT
        player_lookup,
        game_date,
        game_id,
        team_abbr,
        opponent_team_abbr,
        season_year,

        -- Target
        strikeouts as actual_strikeouts,
        innings_pitched as actual_innings,

        -- Features
        COALESCE(k_avg_last_3, 5.0) as f00_k_avg_last_3,
        COALESCE(k_avg_last_5, 5.0) as f01_k_avg_last_5,
        COALESCE(k_avg_last_10, 5.0) as f02_k_avg_last_10,
        COALESCE(k_std_last_10, 2.0) as f03_k_std_last_10,
        COALESCE(ip_avg_last_5, 5.5) as f04_ip_avg_last_5,
        COALESCE(season_k_per_9, 8.5) as f05_season_k_per_9,
        COALESCE(era_rolling_10, 4.0) as f06_season_era,
        COALESCE(whip_rolling_10, 1.3) as f07_season_whip,
        COALESCE(season_games_started, 5) as f08_season_games,
        COALESCE(season_strikeouts, 30) as f09_season_k_total,
        IF(is_home, 1.0, 0.0) as f10_is_home,
        0.0 as f11_home_away_k_diff,
        0.0 as f12_is_day_game,
        0.0 as f13_day_night_k_diff,
        0.0 as f14_vs_opponent_k_rate,
        COALESCE(days_rest, 5) as f20_days_rest,
        games_last_30_days as f21_games_last_30_days,
        COALESCE(pitch_count_avg_last_5, 90.0) as f22_pitch_count_avg,
        COALESCE(season_innings, 50.0) as f23_season_ip_total,
        IF(is_postseason, 1.0, 0.0) as f24_is_postseason,

        -- Fallback for bottom-up (use rolling avg as proxy)
        COALESCE(k_avg_last_5, 5.0) as f25_bottom_up_k_expected,
        0.22 as f26_lineup_k_vs_hand,
        2 as f33_lineup_weak_spots,

        data_completeness_score

    FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
    WHERE strikeouts IS NOT NULL
      AND innings_pitched >= 3.0
      AND rolling_stats_games >= 3
      AND season_year IN (2024, 2025)
    ORDER BY game_date
    """

    df = client.query(simple_query).to_dataframe()
    print(f"Loaded {len(df):,} pitcher starts (simplified)")
    print(f"  Date range: {df['game_date'].min()} to {df['game_date'].max()}")
    print()

if len(df) < 100:
    print("ERROR: Not enough training data. Need at least 100 samples.")
    print("Run analytics processors first:")
    print("  PYTHONPATH=. python -m data_processors.analytics.mlb.pitcher_game_summary_processor --start-date 2024-03-28 --end-date 2025-09-28")
    sys.exit(1)

# ============================================================================
# STEP 2: PREPARE FEATURES
# ============================================================================

print("=" * 80)
print("STEP 2: PREPARING FEATURES")
print("=" * 80)

# Define feature columns - using available features
feature_cols = [
    # Recent performance (f00-f04)
    'f00_k_avg_last_3',
    'f01_k_avg_last_5',
    'f02_k_avg_last_10',
    'f03_k_std_last_10',
    'f04_ip_avg_last_5',

    # Season baseline (f05-f09)
    'f05_season_k_per_9',
    'f06_season_era',
    'f07_season_whip',
    'f08_season_games',
    'f09_season_k_total',

    # Context (f10-f14)
    'f10_is_home',

    # Workload (f20-f24)
    'f20_days_rest',
    'f21_games_last_30_days',
    'f22_pitch_count_avg',
    'f23_season_ip_total',
    'f24_is_postseason',

    # Bottom-up model (f25-f26) - KEY FEATURES
    'f25_bottom_up_k_expected',
    'f26_lineup_k_vs_hand',

    # Lineup analysis (f33)
    'f33_lineup_weak_spots',
]

# Filter to available columns
available_features = [c for c in feature_cols if c in df.columns]
missing_features = [c for c in feature_cols if c not in df.columns]

if missing_features:
    print(f"WARNING: Missing {len(missing_features)} features: {missing_features[:5]}...")

print(f"Using {len(available_features)} features")
print()

# Target variable
target_col = 'actual_strikeouts'

# Prepare X and y
X = df[available_features].copy()
y = df[target_col].copy()

# Convert to numeric
for col in X.columns:
    X[col] = pd.to_numeric(X[col], errors='coerce')
y = pd.to_numeric(y, errors='coerce')

# Fill NaN with reasonable defaults
X = X.fillna(X.median())
y = y.fillna(y.median())

print(f"Features: {len(available_features)}")
print(f"Samples: {len(X):,}")
print(f"Target mean: {y.mean():.2f}")
print(f"Target std: {y.std():.2f}")
print()

# ============================================================================
# STEP 3: SPLIT DATA CHRONOLOGICALLY
# ============================================================================

print("=" * 80)
print("STEP 3: CHRONOLOGICAL TRAIN/VAL/TEST SPLIT")
print("=" * 80)

df_sorted = df.sort_values('game_date').reset_index(drop=True)
n = len(df_sorted)

train_end = int(n * 0.70)
val_end = int(n * 0.85)

train_idx = df_sorted.index[:train_end]
val_idx = df_sorted.index[train_end:val_end]
test_idx = df_sorted.index[val_end:]

X_train = X.iloc[train_idx]
y_train = y.iloc[train_idx]

X_val = X.iloc[val_idx]
y_val = y.iloc[val_idx]

X_test = X.iloc[test_idx]
y_test = y.iloc[test_idx]

print(f"Training:   {len(X_train):,} starts ({df_sorted.iloc[train_idx]['game_date'].min()} to {df_sorted.iloc[train_idx]['game_date'].max()})")
print(f"Validation: {len(X_val):,} starts")
print(f"Test:       {len(X_test):,} starts ({df_sorted.iloc[test_idx]['game_date'].min()} to {df_sorted.iloc[test_idx]['game_date'].max()})")
print()

# ============================================================================
# STEP 4: TRAIN XGBOOST MODEL
# ============================================================================

print("=" * 80)
print("STEP 4: TRAINING XGBOOST MODEL")
print("=" * 80)

# Hyperparameters tuned for strikeout prediction
params = {
    'max_depth': 6,
    'learning_rate': 0.05,
    'n_estimators': 300,
    'min_child_weight': 3,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'gamma': 0.1,
    'reg_alpha': 0.1,
    'reg_lambda': 1,
    'random_state': 42,
    'objective': 'reg:squarederror',
    'eval_metric': 'mae',
    'early_stopping_rounds': 20
}

print("Hyperparameters:")
for k, v in list(params.items())[:6]:
    print(f"  {k}: {v}")
print()

print("Training...")
model = xgb.XGBRegressor(**params)

model.fit(
    X_train, y_train,
    eval_set=[(X_val, y_val)],
    verbose=50
)

print()
print("Training complete!")
print()

# ============================================================================
# STEP 5: EVALUATE MODEL
# ============================================================================

print("=" * 80)
print("STEP 5: MODEL EVALUATION")
print("=" * 80)

def evaluate(y_true, y_pred, name):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    errors = np.abs(y_true - y_pred)
    within_1 = (errors <= 1).mean() * 100
    within_2 = (errors <= 2).mean() * 100
    within_3 = (errors <= 3).mean() * 100

    print(f"\n{name} Set:")
    print(f"  MAE:  {mae:.2f} strikeouts")
    print(f"  RMSE: {rmse:.2f}")
    print(f"  Within 1K: {within_1:.1f}%")
    print(f"  Within 2K: {within_2:.1f}%")
    print(f"  Within 3K: {within_3:.1f}%")

    return {'mae': mae, 'rmse': rmse, 'within_1': within_1, 'within_2': within_2, 'within_3': within_3}

train_pred = model.predict(X_train)
val_pred = model.predict(X_val)
test_pred = model.predict(X_test)

train_metrics = evaluate(y_train, train_pred, "Training")
val_metrics = evaluate(y_val, val_pred, "Validation")
test_metrics = evaluate(y_test, test_pred, "Test")

# Compare to baseline
BASELINE_MAE = 1.92  # From bottom-up formula validation
print(f"\n\nBaseline (bottom-up formula): MAE {BASELINE_MAE}")
print(f"XGBoost model:                MAE {test_metrics['mae']:.2f}")

improvement = (BASELINE_MAE - test_metrics['mae']) / BASELINE_MAE * 100
print(f"Improvement:                  {improvement:+.1f}%")

if test_metrics['mae'] < BASELINE_MAE:
    print("\n SUCCESS! Model beats baseline")
else:
    print("\n Model does not beat baseline - may need more features/data")

# ============================================================================
# STEP 6: FEATURE IMPORTANCE
# ============================================================================

print("\n" + "=" * 80)
print("TOP 10 MOST IMPORTANT FEATURES")
print("=" * 80)

importance = model.feature_importances_
feat_imp = pd.DataFrame({
    'feature': available_features,
    'importance': importance
}).sort_values('importance', ascending=False)

for _, row in feat_imp.head(10).iterrows():
    bar = '' * int(row['importance'] * 50)
    print(f"{row['feature']:30s} {row['importance']*100:5.1f}% {bar}")

# ============================================================================
# STEP 7: SAVE MODEL
# ============================================================================

print("\n" + "=" * 80)
print("STEP 7: SAVING MODEL")
print("=" * 80)

model_id = f"mlb_pitcher_strikeouts_v1_{datetime.now().strftime('%Y%m%d')}"
model_path = MODEL_OUTPUT_DIR / f"{model_id}.json"

model.get_booster().save_model(str(model_path))
print(f"Model saved: {model_path}")

# Save metadata
metadata = {
    'model_id': model_id,
    'trained_at': datetime.now().isoformat(),
    'samples': len(df),
    'features': available_features,
    'train_mae': train_metrics['mae'],
    'val_mae': val_metrics['mae'],
    'test_mae': test_metrics['mae'],
    'baseline_mae': BASELINE_MAE,
    'improvement_pct': improvement,
    'hyperparameters': {k: v for k, v in params.items() if k != 'early_stopping_rounds'}
}

metadata_path = MODEL_OUTPUT_DIR / f"{model_id}_metadata.json"
with open(metadata_path, 'w') as f:
    json.dump(metadata, f, indent=2, default=str)

print(f"Metadata saved: {metadata_path}")

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 80)
print(" TRAINING COMPLETE")
print("=" * 80)
print()
print(f"Model: {model_id}")
print(f"Test MAE: {test_metrics['mae']:.2f} (baseline: {BASELINE_MAE})")
print(f"Within 2K accuracy: {test_metrics['within_2']:.1f}%")
print()

if test_metrics['mae'] < BASELINE_MAE:
    print("READY FOR PRODUCTION")
    print("\nNext steps:")
    print(f"  1. gsutil cp {model_path} gs://nba-scraped-data/ml-models/mlb/")
    print("  2. Update prediction worker to load this model")
else:
    print("Consider:")
    print("  - Adding more features (platoon splits, umpire data)")
    print("  - Collecting more training data")
    print("  - Tuning hyperparameters")

print()

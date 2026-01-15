#!/usr/bin/env python3
"""
Train V1.5 XGBoost Model for MLB Pitcher Strikeout Predictions

This version adds BettingPros features:
- perf_last_5_over_pct: Recent over/under performance (strongest signal)
- projection_value: BettingPros model prediction
- projection_diff: Line minus projection (market inefficiency)

Key finding from analysis:
- perf_last_5 provides 18pp edge (60.9% vs 42.5% over rates)
- When both perf_last_5 and projection agree: 62.2% vs 42.9%

Usage:
    PYTHONPATH=. python scripts/mlb/training/train_pitcher_strikeouts_v1_5.py
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
print(" MLB PITCHER STRIKEOUT MODEL V1.5 TRAINING")
print(" (With BettingPros Features)")
print("=" * 80)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================================================
# STEP 1: LOAD TRAINING DATA WITH BETTINGPROS FEATURES
# ============================================================================

print("=" * 80)
print("STEP 1: LOADING TRAINING DATA (WITH BETTINGPROS)")
print("=" * 80)

client = bigquery.Client(project=PROJECT_ID)

# Query joins pitcher_game_summary with bp_pitcher_props
query = """
WITH bp_strikeouts AS (
    -- BettingPros strikeout props with outcomes
    SELECT
        player_lookup,
        game_date,
        over_line,
        over_odds,
        under_odds,
        projection_value,
        projection_side,
        actual_value,
        perf_last_5_over,
        perf_last_5_under,
        perf_last_10_over,
        perf_last_10_under,
        perf_season_over,
        perf_season_under
    FROM `mlb_raw.bp_pitcher_props`
    WHERE market_id = 285  -- Strikeouts
      AND actual_value IS NOT NULL
),
pgs_normalized AS (
    -- Pitcher game summary with normalized player_lookup for joining
    SELECT
        player_lookup,
        LOWER(REGEXP_REPLACE(NORMALIZE(player_lookup, NFD), r'[\\W_]+', '')) as player_lookup_normalized,
        game_date,
        game_id,
        team_abbr,
        opponent_team_abbr,
        season_year,
        strikeouts,
        innings_pitched,
        is_home,
        is_postseason,
        days_rest,

        -- Rolling features
        k_avg_last_3,
        k_avg_last_5,
        k_avg_last_10,
        k_std_last_10,
        ip_avg_last_5,

        -- Season features
        season_k_per_9,
        era_rolling_10,
        whip_rolling_10,
        season_games_started,
        season_strikeouts,
        season_innings,

        -- Context features
        home_away_k_diff,
        day_night_k_diff,
        opponent_team_k_rate,
        ballpark_k_factor,
        month_of_season,
        days_into_season,

        -- Workload
        games_last_30_days,
        pitch_count_avg_last_5,

        -- Data quality
        data_completeness_score,
        rolling_stats_games

    FROM `mlb_analytics.pitcher_game_summary`
    WHERE game_date >= '2022-04-01'
      AND game_date <= '2025-12-31'
      AND strikeouts IS NOT NULL
      AND innings_pitched >= 3.0
      AND rolling_stats_games >= 3
)

SELECT
    pgs.player_lookup,
    pgs.game_date,
    pgs.game_id,
    pgs.team_abbr,
    pgs.opponent_team_abbr,
    pgs.season_year,

    -- Target (from actual_value for grading consistency)
    pgs.strikeouts as actual_strikeouts,
    bp.actual_value as bp_actual_value,
    pgs.innings_pitched as actual_innings,

    -- V1 Features (f00-f04: Recent performance)
    COALESCE(pgs.k_avg_last_3, 5.0) as f00_k_avg_last_3,
    COALESCE(pgs.k_avg_last_5, 5.0) as f01_k_avg_last_5,
    COALESCE(pgs.k_avg_last_10, 5.0) as f02_k_avg_last_10,
    COALESCE(pgs.k_std_last_10, 2.0) as f03_k_std_last_10,
    COALESCE(pgs.ip_avg_last_5, 5.5) as f04_ip_avg_last_5,

    -- V1 Features (f05-f09: Season baseline)
    COALESCE(pgs.season_k_per_9, 8.5) as f05_season_k_per_9,
    COALESCE(pgs.era_rolling_10, 4.0) as f06_season_era,
    COALESCE(pgs.whip_rolling_10, 1.3) as f07_season_whip,
    COALESCE(pgs.season_games_started, 5) as f08_season_games,
    COALESCE(pgs.season_strikeouts, 30) as f09_season_k_total,

    -- V1 Features (f10-f14: Context)
    IF(pgs.is_home, 1.0, 0.0) as f10_is_home,
    COALESCE(pgs.home_away_k_diff, 0.0) as f11_home_away_k_diff,
    0.0 as f12_is_day_game,
    COALESCE(pgs.day_night_k_diff, 0.0) as f13_day_night_k_diff,

    -- V1 Features (f15-f18: Opponent/Park)
    COALESCE(pgs.opponent_team_k_rate, 0.22) as f15_opponent_team_k_rate,
    COALESCE(pgs.ballpark_k_factor, 1.0) as f16_ballpark_k_factor,
    COALESCE(pgs.month_of_season, 6) as f17_month_of_season,
    COALESCE(pgs.days_into_season, 90) as f18_days_into_season,

    -- V1 Features (f20-f24: Workload)
    COALESCE(pgs.days_rest, 5) as f20_days_rest,
    pgs.games_last_30_days as f21_games_last_30_days,
    COALESCE(pgs.pitch_count_avg_last_5, 90.0) as f22_pitch_count_avg,
    COALESCE(pgs.season_innings, 50.0) as f23_season_ip_total,
    IF(pgs.is_postseason, 1.0, 0.0) as f24_is_postseason,

    -- =======================================================================
    -- NEW V1.5 BETTINGPROS FEATURES (f40-f49)
    -- =======================================================================

    -- f40: The betting line itself (strong baseline)
    bp.over_line as f40_betting_line,

    -- f41: BettingPros projection (their model's prediction)
    bp.projection_value as f41_bp_projection,

    -- f42: Projection diff (projection - line, market inefficiency signal)
    (bp.projection_value - bp.over_line) as f42_projection_diff,

    -- f43: Recent O/U performance (STRONGEST SIGNAL: 18pp edge!)
    SAFE_DIVIDE(bp.perf_last_5_over, (bp.perf_last_5_over + bp.perf_last_5_under)) as f43_perf_last_5_over_pct,

    -- f44: Last 10 O/U performance
    SAFE_DIVIDE(bp.perf_last_10_over, (bp.perf_last_10_over + bp.perf_last_10_under)) as f44_perf_last_10_over_pct,

    -- f45: Season O/U performance
    SAFE_DIVIDE(bp.perf_season_over, (bp.perf_season_over + bp.perf_season_under)) as f45_perf_season_over_pct,

    -- f46: Combined signal (both agree on over)
    CASE
        WHEN bp.perf_last_5_over >= 4 AND bp.projection_value > bp.over_line THEN 1.0
        WHEN bp.perf_last_5_over <= 1 AND bp.projection_value < bp.over_line THEN -1.0
        ELSE 0.0
    END as f46_combined_signal,

    -- f47: Implied probability from odds (betting line accuracy)
    CASE
        WHEN bp.over_odds < 0 THEN ABS(bp.over_odds) / (ABS(bp.over_odds) + 100.0)
        ELSE 100.0 / (bp.over_odds + 100.0)
    END as f47_over_implied_prob,

    -- Raw BettingPros data for grading
    bp.over_line as bp_over_line,
    bp.over_odds,
    bp.under_odds,
    bp.projection_side,
    bp.perf_last_5_over,
    bp.perf_last_5_under,

    -- Data quality
    pgs.data_completeness_score,
    pgs.rolling_stats_games

FROM pgs_normalized pgs
JOIN bp_strikeouts bp
    ON bp.player_lookup = pgs.player_lookup_normalized
    AND bp.game_date = pgs.game_date
WHERE bp.over_line IS NOT NULL
  AND bp.projection_value IS NOT NULL
ORDER BY pgs.game_date, pgs.player_lookup
"""

print("Fetching data from BigQuery...")
print("Joining pitcher_game_summary with bp_pitcher_props...")
print()

df = client.query(query).to_dataframe()

print(f"Loaded {len(df):,} pitcher starts with BettingPros data")
print(f"  Date range: {df['game_date'].min()} to {df['game_date'].max()}")
print(f"  Unique pitchers: {df['player_lookup'].nunique()}")
print(f"  Avg strikeouts: {df['actual_strikeouts'].mean():.2f}")
print(f"  Avg line: {df['f40_betting_line'].mean():.2f}")
print()

if len(df) < 100:
    print("ERROR: Not enough training data. Need at least 100 samples.")
    sys.exit(1)

# ============================================================================
# STEP 2: PREPARE FEATURES
# ============================================================================

print("=" * 80)
print("STEP 2: PREPARING FEATURES")
print("=" * 80)

# V1 features (proven baseline)
v1_features = [
    'f00_k_avg_last_3', 'f01_k_avg_last_5', 'f02_k_avg_last_10',
    'f03_k_std_last_10', 'f04_ip_avg_last_5',
    'f05_season_k_per_9', 'f06_season_era', 'f07_season_whip',
    'f08_season_games', 'f09_season_k_total',
    'f10_is_home', 'f15_opponent_team_k_rate', 'f16_ballpark_k_factor',
    'f17_month_of_season', 'f18_days_into_season',
    'f20_days_rest', 'f21_games_last_30_days', 'f22_pitch_count_avg',
    'f23_season_ip_total', 'f24_is_postseason',
]

# NEW V1.5 BettingPros features
bp_features = [
    'f40_betting_line',       # The line itself (strong baseline)
    'f41_bp_projection',      # BP's prediction
    'f42_projection_diff',    # Projection - Line
    'f43_perf_last_5_over_pct',  # STRONGEST SIGNAL
    'f44_perf_last_10_over_pct',
    'f45_perf_season_over_pct',
    'f46_combined_signal',    # Both agree signal
    'f47_over_implied_prob',  # Market odds
]

# Combine features
all_features = v1_features + bp_features

# Filter to available columns
available_features = [c for c in all_features if c in df.columns]
missing_features = [c for c in all_features if c not in df.columns]

if missing_features:
    print(f"WARNING: Missing {len(missing_features)} features: {missing_features}")

print(f"V1 features: {len([f for f in available_features if f in v1_features])}")
print(f"BP features: {len([f for f in available_features if f in bp_features])}")
print(f"Total features: {len(available_features)}")
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

print(f"Feature matrix shape: {X.shape}")
print(f"Target mean: {y.mean():.2f}, std: {y.std():.2f}")
print()

# ============================================================================
# STEP 3: CHRONOLOGICAL TRAIN/VAL/TEST SPLIT
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

# Also track betting data for test set evaluation
test_df = df_sorted.iloc[test_idx].copy()

print(f"Training:   {len(X_train):,} ({df_sorted.iloc[train_idx]['game_date'].min()} to {df_sorted.iloc[train_idx]['game_date'].max()})")
print(f"Validation: {len(X_val):,}")
print(f"Test:       {len(X_test):,} ({df_sorted.iloc[test_idx]['game_date'].min()} to {df_sorted.iloc[test_idx]['game_date'].max()})")
print()

# ============================================================================
# STEP 4: TRAIN XGBOOST MODEL
# ============================================================================

print("=" * 80)
print("STEP 4: TRAINING XGBOOST MODEL")
print("=" * 80)

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

print("Training XGBoost V1.5...")
model = xgb.XGBRegressor(**params)
model.fit(
    X_train, y_train,
    eval_set=[(X_val, y_val)],
    verbose=50
)
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

    print(f"\n{name}:")
    print(f"  MAE:  {mae:.3f}")
    print(f"  RMSE: {rmse:.3f}")
    print(f"  Within 1K: {within_1:.1f}%")
    print(f"  Within 2K: {within_2:.1f}%")

    return {'mae': mae, 'rmse': rmse, 'within_1': within_1, 'within_2': within_2}

train_pred = model.predict(X_train)
val_pred = model.predict(X_val)
test_pred = model.predict(X_test)

train_metrics = evaluate(y_train, train_pred, "Training")
val_metrics = evaluate(y_val, val_pred, "Validation")
test_metrics = evaluate(y_test, test_pred, "Test")

# ============================================================================
# STEP 6: BETTING PERFORMANCE (HIT RATE)
# ============================================================================

print("\n" + "=" * 80)
print("STEP 6: BETTING PERFORMANCE (HIT RATE)")
print("=" * 80)

# Calculate over/under predictions on test set
test_df['predicted_k'] = test_pred
test_df['pred_over'] = test_df['predicted_k'] > test_df['bp_over_line']
test_df['actual_over'] = test_df['actual_strikeouts'] > test_df['bp_over_line']
test_df['correct'] = test_df['pred_over'] == test_df['actual_over']

hit_rate = test_df['correct'].mean() * 100
baseline_rate = 50.0

print(f"\nModel Hit Rate: {hit_rate:.2f}%")
print(f"Baseline (random): {baseline_rate:.1f}%")
print(f"Edge: {hit_rate - baseline_rate:+.2f}%")

# By confidence
test_df['confidence'] = np.abs(test_df['predicted_k'] - test_df['bp_over_line'])
high_conf = test_df[test_df['confidence'] > 0.5]
print(f"\nHigh confidence (diff > 0.5K):")
print(f"  Count: {len(high_conf)}")
print(f"  Hit Rate: {high_conf['correct'].mean() * 100:.1f}%")

# ============================================================================
# STEP 7: FEATURE IMPORTANCE
# ============================================================================

print("\n" + "=" * 80)
print("STEP 7: FEATURE IMPORTANCE")
print("=" * 80)

importance = model.feature_importances_
feat_imp = pd.DataFrame({
    'feature': available_features,
    'importance': importance
}).sort_values('importance', ascending=False)

print("\nTop 15 Features:")
for i, (_, row) in enumerate(feat_imp.head(15).iterrows()):
    is_bp = "BP" if row['feature'].startswith('f4') else "V1"
    bar = '█' * int(row['importance'] * 50)
    print(f"  [{is_bp}] {row['feature']:30s} {row['importance']*100:5.1f}% {bar}")

# Show BP feature impact
bp_importance = feat_imp[feat_imp['feature'].str.startswith('f4')]['importance'].sum()
print(f"\nBettingPros features total importance: {bp_importance*100:.1f}%")

# ============================================================================
# STEP 8: SAVE MODEL
# ============================================================================

print("\n" + "=" * 80)
print("STEP 8: SAVING MODEL")
print("=" * 80)

model_id = f"mlb_pitcher_strikeouts_v1_5_bp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
model_path = MODEL_OUTPUT_DIR / f"{model_id}.json"

model.get_booster().save_model(str(model_path))
print(f"Model saved: {model_path}")

# Save metadata
metadata = {
    'model_id': model_id,
    'version': '1.5',
    'description': 'V1.5 with BettingPros features (perf_last_5, projection, etc.)',
    'trained_at': datetime.now().isoformat(),
    'samples': len(df),
    'features': available_features,
    'v1_features': [f for f in available_features if f in v1_features],
    'bp_features': [f for f in available_features if f in bp_features],
    'test_mae': test_metrics['mae'],
    'test_hit_rate': hit_rate,
    'test_samples': len(test_df),
    'bp_feature_importance': bp_importance,
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
print(" V1.5 TRAINING COMPLETE")
print("=" * 80)
print()
print(f"Model: {model_id}")
print(f"Test MAE: {test_metrics['mae']:.3f}")
print(f"Test Hit Rate: {hit_rate:.2f}%")
print(f"BettingPros feature importance: {bp_importance*100:.1f}%")
print()

if hit_rate > 55:
    print("PROMISING! Model shows betting edge")
    print("\nNext steps:")
    print("  1. Backtest on more data")
    print("  2. Implement champion-challenger")
else:
    print("Consider:")
    print("  - Feature engineering")
    print("  - More historical data")
    print("  - Alternative models")

print()

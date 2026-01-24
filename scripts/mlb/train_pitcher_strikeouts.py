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

import logging
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

logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models/mlb")
MODEL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logger.info("=" * 80)
logger.info(" MLB PITCHER STRIKEOUT MODEL TRAINING")
logger.info("=" * 80)
logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
logger.info("")

# ============================================================================
# STEP 1: LOAD TRAINING DATA FROM BIGQUERY
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 1: LOADING TRAINING DATA")
logger.info("=" * 80)

client = bigquery.Client(project=PROJECT_ID)

# Query to get training data with actual strikeout outcomes
# Calculate bottom-up features inline using opponent-specific lineup data
query = """
WITH game_teams AS (
    -- Get distinct game_pk with home/away teams (dedupe mlb_game_lineups)
    SELECT DISTINCT
        game_pk,
        home_team_abbr,
        away_team_abbr
    FROM `nba-props-platform.mlb_raw.mlb_game_lineups`
    WHERE game_date >= '2024-03-01'
      AND game_date <= '2025-12-31'
),
pitcher_raw AS (
    -- Get pitcher game info including team_abbr from raw data (which is fixed)
    -- Dedupe using ROW_NUMBER since raw data may have duplicate rows per pitcher per game
    SELECT
        game_pk,
        game_date,
        player_lookup,
        pitcher_team,
        opponent_team
    FROM (
        SELECT
            ps.game_pk,
            ps.game_date,
            ps.player_lookup,
            ps.team_abbr as pitcher_team,
            -- Opponent is the OTHER team in the game
            CASE
                WHEN ps.team_abbr = gt.home_team_abbr THEN gt.away_team_abbr
                ELSE gt.home_team_abbr
            END as opponent_team,
            ROW_NUMBER() OVER (PARTITION BY ps.game_pk, ps.player_lookup ORDER BY ps.game_date) as rn
        FROM `nba-props-platform.mlb_raw.mlb_pitcher_stats` ps
        JOIN game_teams gt
            ON ps.game_pk = gt.game_pk
        WHERE ps.is_starter = TRUE
          AND ps.game_date >= '2024-03-01'
          AND ps.game_date <= '2025-12-31'
    )
    WHERE rn = 1
),
batter_latest_stats AS (
    -- Get each batter's most recent K rate before each date
    SELECT
        player_lookup,
        game_date as stats_date,
        k_rate_last_10,
        season_k_rate
    FROM `nba-props-platform.mlb_analytics.batter_game_summary`
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY player_lookup
        ORDER BY game_date DESC
    ) = 1
),
lineup_batters_deduped AS (
    -- Dedupe lineup batters (raw data has duplicates)
    SELECT
        game_pk,
        game_date,
        team_abbr,
        player_lookup,
        batting_order
    FROM (
        SELECT
            game_pk,
            game_date,
            team_abbr,
            player_lookup,
            batting_order,
            ROW_NUMBER() OVER (PARTITION BY game_pk, team_abbr, player_lookup ORDER BY batting_order) as rn
        FROM `nba-props-platform.mlb_raw.mlb_lineup_batters`
        WHERE game_date >= '2024-03-01'
          AND game_date <= '2025-12-31'
    )
    WHERE rn = 1
),
lineup_batter_stats AS (
    -- Get batter K rates for each game's OPPONENT lineup only
    SELECT
        pr.game_pk,
        pr.game_date,
        pr.player_lookup as pitcher_lookup,
        lb.team_abbr as batter_team,
        lb.player_lookup as batter_lookup,
        lb.batting_order,
        -- Use batter's K rate (fallback to league average)
        COALESCE(bs.k_rate_last_10, bs.season_k_rate, 0.22) as batter_k_rate,
        -- Expected plate appearances by batting order
        CASE lb.batting_order
            WHEN 1 THEN 4.5 WHEN 2 THEN 4.3 WHEN 3 THEN 4.2 WHEN 4 THEN 4.0
            WHEN 5 THEN 3.9 WHEN 6 THEN 3.8 WHEN 7 THEN 3.7 WHEN 8 THEN 3.6
            ELSE 3.5
        END as expected_pa
    FROM pitcher_raw pr
    JOIN lineup_batters_deduped lb
        ON pr.game_pk = lb.game_pk
        AND lb.team_abbr = pr.opponent_team  -- KEY: Only opponent's batters
    LEFT JOIN batter_latest_stats bs
        ON lb.player_lookup = bs.player_lookup
),
lineup_aggregates AS (
    -- Aggregate batter stats per pitcher per game (opponent-specific!)
    SELECT
        game_pk,
        game_date,
        pitcher_lookup,
        -- Bottom-up expected K: sum of individual batter expected Ks
        SUM(batter_k_rate * expected_pa) as bottom_up_k,
        -- Average lineup K rate
        AVG(batter_k_rate) as lineup_avg_k_rate,
        -- Count of weak spots (K rate > 0.28)
        COUNTIF(batter_k_rate > 0.28) as weak_spots,
        COUNT(*) as batters_in_lineup
    FROM lineup_batter_stats
    GROUP BY game_pk, game_date, pitcher_lookup
),
pitcher_vs_opponent AS (
    -- Calculate pitcher's historical K average vs each opponent
    SELECT
        pr1.player_lookup,
        pr1.game_date,
        pr1.opponent_team,
        -- Historical average Ks vs this opponent (games before current date)
        AVG(pgs2.strikeouts) as avg_k_vs_opponent,
        COUNT(pgs2.strikeouts) as games_vs_opponent
    FROM pitcher_raw pr1
    LEFT JOIN `nba-props-platform.mlb_analytics.pitcher_game_summary` pgs2
        ON pr1.player_lookup = pgs2.player_lookup
        AND pgs2.game_date < pr1.game_date  -- Only historical games
        AND pgs2.game_date >= DATE_SUB(pr1.game_date, INTERVAL 3 YEAR)  -- Last 3 years
        AND pgs2.strikeouts IS NOT NULL
    LEFT JOIN pitcher_raw pr2
        ON pgs2.player_lookup = pr2.player_lookup
        AND pgs2.game_date = pr2.game_date
    WHERE pr2.opponent_team = pr1.opponent_team  -- Same opponent
    GROUP BY pr1.player_lookup, pr1.game_date, pr1.opponent_team
),
pitcher_games AS (
    -- Get pitcher game stats with rolling features from analytics
    SELECT
        pgs.player_lookup,
        pgs.game_date,
        pgs.game_id,
        pr.pitcher_team as team_abbr,
        pr.opponent_team as opponent_team_abbr,
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

        -- Split adjustments (f10-f14) - NOW WITH REAL DATA
        IF(pgs.is_home, 1.0, 0.0) as f10_is_home,
        pgs.home_away_k_diff as f11_home_away_k_diff,  -- NEW: From bdl_pitcher_splits
        0.0 as f12_is_day_game,  -- Placeholder (no data source yet)
        pgs.day_night_k_diff as f13_day_night_k_diff,  -- NEW: From bdl_pitcher_splits
        0.0 as f14_vs_opponent_k_rate,  -- Placeholder

        -- Workload features (f20-f24)
        COALESCE(pgs.days_rest, 5) as f20_days_rest,
        pgs.games_last_30_days as f21_games_last_30_days,
        pgs.pitch_count_avg_last_5 as f22_pitch_count_avg,
        pgs.season_innings as f23_season_ip_total,
        IF(pgs.is_postseason, 1.0, 0.0) as f24_is_postseason,

        -- Bottom-up features (calculated from opponent lineup)
        la.bottom_up_k as f25_bottom_up_k_expected,
        la.lineup_avg_k_rate as f26_lineup_k_vs_hand,
        la.weak_spots as f33_lineup_weak_spots,
        la.batters_in_lineup as lineup_data_quality,

        -- Pitcher vs opponent history (NEW FEATURES)
        pvo.avg_k_vs_opponent as f27_avg_k_vs_opponent,
        pvo.games_vs_opponent as f28_games_vs_opponent,

        -- V2 NEW FEATURES (populated 100% in pitcher_game_summary)
        pgs.opponent_team_k_rate as f15_opponent_team_k_rate,
        pgs.ballpark_k_factor as f16_ballpark_k_factor,
        pgs.month_of_season as f17_month_of_season,
        pgs.days_into_season as f18_days_into_season,

        -- Data quality
        pgs.data_completeness_score,
        pgs.rolling_stats_games

    FROM `nba-props-platform.mlb_analytics.pitcher_game_summary` pgs
    -- Join with pitcher_raw to get fixed team_abbr and opponent
    JOIN pitcher_raw pr
        ON pgs.player_lookup = pr.player_lookup AND pgs.game_date = pr.game_date
    -- Join lineup aggregates for opponent-specific bottom-up features
    LEFT JOIN lineup_aggregates la
        ON pr.game_pk = la.game_pk AND pr.player_lookup = la.pitcher_lookup
    -- Join pitcher vs opponent history
    LEFT JOIN pitcher_vs_opponent pvo
        ON pr.player_lookup = pvo.player_lookup
        AND pr.game_date = pvo.game_date
        AND pr.opponent_team = pvo.opponent_team
    WHERE pgs.game_date >= '2024-03-01'
      AND pgs.game_date <= '2025-12-31'
      AND pgs.strikeouts IS NOT NULL
      AND pgs.innings_pitched >= 3.0  -- Starter threshold
      AND pgs.rolling_stats_games >= 3  -- Minimum history
      AND pgs.season_year IN (2024, 2025)
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

    -- Split adjustments (f10-f14) - NOW WITH REAL DATA
    f10_is_home,
    COALESCE(f11_home_away_k_diff, 0.0) as f11_home_away_k_diff,
    f12_is_day_game,
    COALESCE(f13_day_night_k_diff, 0.0) as f13_day_night_k_diff,
    f14_vs_opponent_k_rate,

    -- Workload (f20-f24)
    f20_days_rest,
    f21_games_last_30_days,
    COALESCE(f22_pitch_count_avg, 90.0) as f22_pitch_count_avg,
    COALESCE(f23_season_ip_total, 50.0) as f23_season_ip_total,
    f24_is_postseason,

    -- Bottom-up model (f25) - KEY FEATURE (now opponent-specific!)
    COALESCE(f25_bottom_up_k_expected, 5.0) as f25_bottom_up_k_expected,
    COALESCE(f26_lineup_k_vs_hand, 0.22) as f26_lineup_k_vs_hand,

    -- Pitcher vs opponent history (f27-f28) - NEW
    COALESCE(f27_avg_k_vs_opponent, f02_k_avg_last_10) as f27_avg_k_vs_opponent,
    COALESCE(f28_games_vs_opponent, 0) as f28_games_vs_opponent,

    -- Weak spots (f33)
    COALESCE(f33_lineup_weak_spots, 2) as f33_lineup_weak_spots,

    -- V2 NEW FEATURES (f15-f18)
    COALESCE(f15_opponent_team_k_rate, 0.22) as f15_opponent_team_k_rate,
    COALESCE(f16_ballpark_k_factor, 1.0) as f16_ballpark_k_factor,
    COALESCE(f17_month_of_season, 6) as f17_month_of_season,
    COALESCE(f18_days_into_season, 90) as f18_days_into_season,

    -- Data quality
    data_completeness_score,
    lineup_data_quality

FROM pitcher_games
WHERE actual_strikeouts IS NOT NULL
ORDER BY game_date, player_lookup
"""

logger.info("Fetching data from BigQuery...")
logger.info("Date range: 2024-2025 seasons")
logger.info("")

try:
    df = client.query(query).to_dataframe()
    logger.info(f"Loaded {len(df):,} pitcher starts")
    logger.info(f"  Date range: {df['game_date'].min()} to {df['game_date'].max()}")
    logger.info(f"  Unique pitchers: {df['player_lookup'].nunique()}")
    logger.info(f"  Avg strikeouts: {df['actual_strikeouts'].mean():.2f}")
    logger.info("")
except Exception as e:
    logger.error(f"ERROR loading data: {e}")
    logger.warning("Falling back to simplified query without lineup features...")

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
    WHERE game_date >= '2024-03-01'
      AND game_date <= '2025-12-31'
      AND strikeouts IS NOT NULL
      AND innings_pitched >= 3.0
      AND rolling_stats_games >= 3
      AND season_year IN (2024, 2025)
    ORDER BY game_date
    """

    df = client.query(simple_query).to_dataframe()
    logger.info(f"Loaded {len(df):,} pitcher starts (simplified)")
    logger.info(f"  Date range: {df['game_date'].min()} to {df['game_date'].max()}")
    logger.info("")

if len(df) < 100:
    logger.error("ERROR: Not enough training data. Need at least 100 samples.")
    logger.error("Run analytics processors first:")
    logger.error("  PYTHONPATH=. python -m data_processors.analytics.mlb.pitcher_game_summary_processor --start-date 2024-03-28 --end-date 2025-09-28")
    sys.exit(1)

# ============================================================================
# STEP 2: PREPARE FEATURES
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 2: PREPARING FEATURES")
logger.info("=" * 80)

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

    # Context (f10-f14) - NOW WITH SPLITS DATA
    'f10_is_home',
    'f11_home_away_k_diff',  # NEW: Home-Away K/9 difference
    'f13_day_night_k_diff',  # NEW: Day-Night K/9 difference

    # V2 NEW FEATURES (f15-f18) - opponent/park/seasonal
    'f15_opponent_team_k_rate',
    'f16_ballpark_k_factor',
    'f17_month_of_season',
    'f18_days_into_season',

    # Workload (f20-f24)
    'f20_days_rest',
    'f21_games_last_30_days',
    'f22_pitch_count_avg',
    'f23_season_ip_total',
    'f24_is_postseason',

    # Bottom-up model (f25-f26) - KEY FEATURES
    'f25_bottom_up_k_expected',
    'f26_lineup_k_vs_hand',

    # Pitcher vs opponent history (f27-f28) - NEW
    'f27_avg_k_vs_opponent',
    'f28_games_vs_opponent',

    # Lineup analysis (f33)
    'f33_lineup_weak_spots',
]

# Filter to available columns
available_features = [c for c in feature_cols if c in df.columns]
missing_features = [c for c in feature_cols if c not in df.columns]

if missing_features:
    logger.warning(f"Missing {len(missing_features)} features: {missing_features[:5]}...")

logger.info(f"Using {len(available_features)} features")
logger.info("")

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

logger.info(f"Features: {len(available_features)}")
logger.info(f"Samples: {len(X):,}")
logger.info(f"Target mean: {y.mean():.2f}")
logger.info(f"Target std: {y.std():.2f}")
logger.info("")

# ============================================================================
# STEP 3: SPLIT DATA CHRONOLOGICALLY
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 3: CHRONOLOGICAL TRAIN/VAL/TEST SPLIT")
logger.info("=" * 80)

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

logger.info(f"Training:   {len(X_train):,} starts ({df_sorted.iloc[train_idx]['game_date'].min()} to {df_sorted.iloc[train_idx]['game_date'].max()})")
logger.info(f"Validation: {len(X_val):,} starts")
logger.info(f"Test:       {len(X_test):,} starts ({df_sorted.iloc[test_idx]['game_date'].min()} to {df_sorted.iloc[test_idx]['game_date'].max()})")
logger.info("")

# ============================================================================
# STEP 4: TRAIN XGBOOST MODEL
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 4: TRAINING XGBOOST MODEL")
logger.info("=" * 80)

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

logger.info("Hyperparameters:")
for k, v in list(params.items())[:6]:
    logger.info(f"  {k}: {v}")
logger.info("")

logger.info("Training...")
model = xgb.XGBRegressor(**params)

model.fit(
    X_train, y_train,
    eval_set=[(X_val, y_val)],
    verbose=50
)

logger.info("")
logger.info("Training complete!")
logger.info("")

# ============================================================================
# STEP 5: EVALUATE MODEL
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 5: MODEL EVALUATION")
logger.info("=" * 80)

def evaluate(y_true, y_pred, name):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    errors = np.abs(y_true - y_pred)
    within_1 = (errors <= 1).mean() * 100
    within_2 = (errors <= 2).mean() * 100
    within_3 = (errors <= 3).mean() * 100

    logger.info(f"{name} Set:")
    logger.info(f"  MAE:  {mae:.2f} strikeouts")
    logger.info(f"  RMSE: {rmse:.2f}")
    logger.info(f"  Within 1K: {within_1:.1f}%")
    logger.info(f"  Within 2K: {within_2:.1f}%")
    logger.info(f"  Within 3K: {within_3:.1f}%")

    return {'mae': mae, 'rmse': rmse, 'within_1': within_1, 'within_2': within_2, 'within_3': within_3}

train_pred = model.predict(X_train)
val_pred = model.predict(X_val)
test_pred = model.predict(X_test)

train_metrics = evaluate(y_train, train_pred, "Training")
val_metrics = evaluate(y_val, val_pred, "Validation")
test_metrics = evaluate(y_test, test_pred, "Test")

# Compare to baseline
BASELINE_MAE = 1.92  # From bottom-up formula validation
logger.info(f"Baseline (bottom-up formula): MAE {BASELINE_MAE}")
logger.info(f"XGBoost model:                MAE {test_metrics['mae']:.2f}")

improvement = (BASELINE_MAE - test_metrics['mae']) / BASELINE_MAE * 100
logger.info(f"Improvement:                  {improvement:+.1f}%")

if test_metrics['mae'] < BASELINE_MAE:
    logger.info("SUCCESS! Model beats baseline")
else:
    logger.info("Model does not beat baseline - may need more features/data")

# ============================================================================
# STEP 6: FEATURE IMPORTANCE
# ============================================================================

logger.info("=" * 80)
logger.info("TOP 10 MOST IMPORTANT FEATURES")
logger.info("=" * 80)

importance = model.feature_importances_
feat_imp = pd.DataFrame({
    'feature': available_features,
    'importance': importance
}).sort_values('importance', ascending=False)

for _, row in feat_imp.head(10).iterrows():
    bar = '*' * int(row['importance'] * 50)
    logger.info(f"{row['feature']:30s} {row['importance']*100:5.1f}% {bar}")

# ============================================================================
# STEP 7: SAVE MODEL
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 7: SAVING MODEL")
logger.info("=" * 80)

model_id = f"mlb_pitcher_strikeouts_v1_5_splits_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
model_path = MODEL_OUTPUT_DIR / f"{model_id}.json"

model.get_booster().save_model(str(model_path))
logger.info(f"Model saved: {model_path}")

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

logger.info(f"Metadata saved: {metadata_path}")

# ============================================================================
# SUMMARY
# ============================================================================

logger.info("=" * 80)
logger.info(" TRAINING COMPLETE")
logger.info("=" * 80)
logger.info("")
logger.info(f"Model: {model_id}")
logger.info(f"Test MAE: {test_metrics['mae']:.2f} (baseline: {BASELINE_MAE})")
logger.info(f"Within 2K accuracy: {test_metrics['within_2']:.1f}%")
logger.info("")

if test_metrics['mae'] < BASELINE_MAE:
    logger.info("READY FOR PRODUCTION")
    logger.info("Next steps:")
    logger.info(f"  1. gsutil cp {model_path} gs://nba-scraped-data/ml-models/mlb/")
    logger.info("  2. Update prediction worker to load this model")
else:
    logger.info("Consider:")
    logger.info("  - Adding more features (platoon splits, umpire data)")
    logger.info("  - Collecting more training data")
    logger.info("  - Tuning hyperparameters")

logger.info("")

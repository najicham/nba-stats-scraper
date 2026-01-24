#!/usr/bin/env python3
"""
Train CatBoost Model for MLB Pitcher Strikeout Predictions (V2)

V2-Lite: Uses 21 features (V1 19 + opponent_team_k_rate + ballpark_k_factor)
Algorithm: CatBoost (vs V1's XGBoost)

Usage:
    PYTHONPATH=. python scripts/mlb/training/train_pitcher_strikeouts_v2.py

Target: Match or beat V1's 67.27% hit rate
"""

import logging
import os
import sys
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool
from google.cloud import bigquery, storage
from sklearn.metrics import mean_absolute_error, mean_squared_error

logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models/mlb")
MODEL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# V2-Lite Feature set (21 features)
V2_FEATURES = [
    # Recent performance (5)
    'f00_k_avg_last_3',
    'f01_k_avg_last_5',
    'f02_k_avg_last_10',
    'f03_k_std_last_10',
    'f04_ip_avg_last_5',

    # Season baseline (5)
    'f05_season_k_per_9',
    'f06_season_era',
    'f07_season_whip',
    'f08_season_games',
    'f09_season_k_total',

    # Context (1)
    'f10_is_home',

    # Workload (5)
    'f20_days_rest',
    'f21_games_last_30_days',
    'f22_pitch_count_avg',
    'f23_season_ip_total',
    'f24_is_postseason',

    # Bottom-up model (3)
    'f25_bottom_up_k_expected',
    'f26_lineup_k_vs_hand',
    'f33_lineup_weak_spots',

    # V2 NEW features (2)
    'f15_opponent_team_k_rate',
    'f17_ballpark_k_factor',
]

logger.info("=" * 80)
logger.info(" MLB PITCHER STRIKEOUTS V2 MODEL TRAINING (CatBoost)")
logger.info("=" * 80)
logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
logger.info(f"Features: {len(V2_FEATURES)}")
logger.info("")

# ============================================================================
# STEP 1: LOAD TRAINING DATA
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 1: LOADING TRAINING DATA")
logger.info("=" * 80)

client = bigquery.Client(project=PROJECT_ID)

# Query to get training data with V2 features and betting lines for hit rate calculation
query = """
WITH game_teams AS (
    SELECT DISTINCT
        game_pk,
        home_team_abbr,
        away_team_abbr
    FROM `nba-props-platform.mlb_raw.mlb_game_lineups`
    WHERE game_date >= '2024-03-01'
      AND game_date <= '2025-12-31'
),
pitcher_raw AS (
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
    SELECT
        pr.game_pk,
        pr.game_date,
        pr.player_lookup as pitcher_lookup,
        lb.team_abbr as batter_team,
        lb.player_lookup as batter_lookup,
        lb.batting_order,
        COALESCE(bs.k_rate_last_10, bs.season_k_rate, 0.22) as batter_k_rate,
        CASE lb.batting_order
            WHEN 1 THEN 4.5 WHEN 2 THEN 4.3 WHEN 3 THEN 4.2 WHEN 4 THEN 4.0
            WHEN 5 THEN 3.9 WHEN 6 THEN 3.8 WHEN 7 THEN 3.7 WHEN 8 THEN 3.6
            ELSE 3.5
        END as expected_pa
    FROM pitcher_raw pr
    JOIN lineup_batters_deduped lb
        ON pr.game_pk = lb.game_pk
        AND lb.team_abbr = pr.opponent_team
    LEFT JOIN batter_latest_stats bs
        ON lb.player_lookup = bs.player_lookup
),
lineup_aggregates AS (
    SELECT
        game_pk,
        game_date,
        pitcher_lookup,
        SUM(batter_k_rate * expected_pa) as bottom_up_k,
        AVG(batter_k_rate) as lineup_avg_k_rate,
        COUNTIF(batter_k_rate > 0.28) as weak_spots,
        COUNT(*) as batters_in_lineup
    FROM lineup_batter_stats
    GROUP BY game_pk, game_date, pitcher_lookup
),
pitcher_games AS (
    SELECT
        pgs.player_lookup,
        pgs.game_date,
        pgs.game_id,
        pr.pitcher_team as team_abbr,
        pr.opponent_team as opponent_team_abbr,
        pgs.season_year,

        -- Target variable
        pgs.strikeouts as actual_strikeouts,
        pgs.innings_pitched as actual_innings,

        -- V1 Features (19)
        pgs.k_avg_last_3 as f00_k_avg_last_3,
        pgs.k_avg_last_5 as f01_k_avg_last_5,
        pgs.k_avg_last_10 as f02_k_avg_last_10,
        pgs.k_std_last_10 as f03_k_std_last_10,
        pgs.ip_avg_last_5 as f04_ip_avg_last_5,
        pgs.season_k_per_9 as f05_season_k_per_9,
        COALESCE(pgs.era_rolling_10, pgs.season_era, 4.0) as f06_season_era,
        COALESCE(pgs.whip_rolling_10, pgs.season_whip, 1.3) as f07_season_whip,
        pgs.season_games_started as f08_season_games,
        pgs.season_strikeouts as f09_season_k_total,
        IF(pgs.is_home, 1.0, 0.0) as f10_is_home,
        COALESCE(pgs.days_rest, 5) as f20_days_rest,
        pgs.games_last_30_days as f21_games_last_30_days,
        pgs.pitch_count_avg_last_5 as f22_pitch_count_avg,
        pgs.season_innings as f23_season_ip_total,
        IF(pgs.is_postseason, 1.0, 0.0) as f24_is_postseason,
        la.bottom_up_k as f25_bottom_up_k_expected,
        la.lineup_avg_k_rate as f26_lineup_k_vs_hand,
        la.weak_spots as f33_lineup_weak_spots,

        -- V2 NEW Features (2)
        pgs.opponent_team_k_rate as f15_opponent_team_k_rate,
        pgs.ballpark_k_factor as f17_ballpark_k_factor,

        -- Data quality
        pgs.data_completeness_score,
        pgs.rolling_stats_games,
        la.batters_in_lineup as lineup_data_quality

    FROM `nba-props-platform.mlb_analytics.pitcher_game_summary` pgs
    JOIN pitcher_raw pr
        ON pgs.player_lookup = pr.player_lookup AND pgs.game_date = pr.game_date
    LEFT JOIN lineup_aggregates la
        ON pr.game_pk = la.game_pk AND pr.player_lookup = la.pitcher_lookup
    WHERE pgs.game_date >= '2024-03-01'
      AND pgs.game_date <= '2025-12-31'
      AND pgs.strikeouts IS NOT NULL
      AND pgs.innings_pitched >= 3.0
      AND pgs.rolling_stats_games >= 3
      AND pgs.season_year IN (2024, 2025)
),
with_betting_lines AS (
    -- Join with predictions table to get betting lines for hit rate calculation
    SELECT
        pg.*,
        pred.strikeouts_line,
        pred.is_correct as v1_is_correct
    FROM pitcher_games pg
    LEFT JOIN `nba-props-platform.mlb_predictions.pitcher_strikeouts` pred
        ON pg.player_lookup = pred.pitcher_lookup
        AND pg.game_date = pred.game_date
)

SELECT
    player_lookup,
    game_date,
    game_id,
    team_abbr,
    opponent_team_abbr,
    season_year,
    actual_strikeouts,
    actual_innings,

    -- Features with defaults
    COALESCE(f00_k_avg_last_3, 5.0) as f00_k_avg_last_3,
    COALESCE(f01_k_avg_last_5, 5.0) as f01_k_avg_last_5,
    COALESCE(f02_k_avg_last_10, 5.0) as f02_k_avg_last_10,
    COALESCE(f03_k_std_last_10, 2.0) as f03_k_std_last_10,
    COALESCE(f04_ip_avg_last_5, 5.5) as f04_ip_avg_last_5,
    COALESCE(f05_season_k_per_9, 8.5) as f05_season_k_per_9,
    f06_season_era,
    f07_season_whip,
    COALESCE(f08_season_games, 5) as f08_season_games,
    COALESCE(f09_season_k_total, 30) as f09_season_k_total,
    f10_is_home,
    f20_days_rest,
    f21_games_last_30_days,
    COALESCE(f22_pitch_count_avg, 90.0) as f22_pitch_count_avg,
    COALESCE(f23_season_ip_total, 50.0) as f23_season_ip_total,
    f24_is_postseason,
    COALESCE(f25_bottom_up_k_expected, 5.0) as f25_bottom_up_k_expected,
    COALESCE(f26_lineup_k_vs_hand, 0.22) as f26_lineup_k_vs_hand,
    COALESCE(f33_lineup_weak_spots, 2) as f33_lineup_weak_spots,
    COALESCE(f15_opponent_team_k_rate, 0.25) as f15_opponent_team_k_rate,
    COALESCE(f17_ballpark_k_factor, 1.0) as f17_ballpark_k_factor,

    -- For hit rate calculation
    strikeouts_line,
    v1_is_correct,
    data_completeness_score,
    lineup_data_quality

FROM with_betting_lines
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
    logger.info(f"  Has betting line: {df['strikeouts_line'].notna().sum():,} ({100*df['strikeouts_line'].notna().mean():.1f}%)")
    logger.info("")
except Exception as e:
    logger.error(f"ERROR loading data: {e}")
    sys.exit(1)

if len(df) < 100:
    logger.error("ERROR: Not enough training data.")
    sys.exit(1)

# ============================================================================
# STEP 2: PREPARE FEATURES
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 2: PREPARING FEATURES")
logger.info("=" * 80)

# Filter to available columns
available_features = [c for c in V2_FEATURES if c in df.columns]
missing_features = [c for c in V2_FEATURES if c not in df.columns]

if missing_features:
    logger.warning(f"Missing {len(missing_features)} features: {missing_features}")

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

# Split: Train (70%), Validation (15%), Test (15%)
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

# Keep test metadata for hit rate calculation
test_df = df_sorted.iloc[test_idx].copy()

logger.info(f"Training:   {len(X_train):,} starts ({df_sorted.iloc[train_idx]['game_date'].min()} to {df_sorted.iloc[train_idx]['game_date'].max()})")
logger.info(f"Validation: {len(X_val):,} starts")
logger.info(f"Test:       {len(X_test):,} starts ({df_sorted.iloc[test_idx]['game_date'].min()} to {df_sorted.iloc[test_idx]['game_date'].max()})")
logger.info("")

# ============================================================================
# STEP 4: TRAIN CATBOOST MODEL
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 4: TRAINING CATBOOST MODEL")
logger.info("=" * 80)

# CatBoost hyperparameters
params = {
    'iterations': 1000,
    'learning_rate': 0.05,
    'depth': 6,
    'l2_leaf_reg': 3,
    'random_seed': 42,
    'loss_function': 'MAE',
    'eval_metric': 'MAE',
    'early_stopping_rounds': 50,
    'verbose': 100,
}

logger.info("Hyperparameters:")
for k, v in list(params.items())[:6]:
    logger.info(f"  {k}: {v}")
logger.info("")

logger.info("Training CatBoost V2...")
model = CatBoostRegressor(**params)

model.fit(
    X_train, y_train,
    eval_set=(X_val, y_val),
    use_best_model=True,
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

# Compare to V1 baseline
V1_MAE = 1.46
V1_HIT_RATE = 67.27

logger.info(f"V1 Baseline: MAE {V1_MAE}, Hit Rate {V1_HIT_RATE}%")
logger.info(f"V2 CatBoost: MAE {test_metrics['mae']:.2f}")

mae_improvement = (V1_MAE - test_metrics['mae']) / V1_MAE * 100
logger.info(f"MAE Change: {mae_improvement:+.1f}%")

# ============================================================================
# STEP 6: CALCULATE HIT RATE ON TEST SET
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 6: HIT RATE CALCULATION")
logger.info("=" * 80)

# Add predictions to test dataframe
test_df['v2_predicted'] = test_pred

# Calculate hit rate against betting lines
def calculate_hit_rate(df, pred_col, line_col, actual_col, edge_threshold=0.5):
    """Calculate hit rate for predictions vs betting lines."""
    # Filter to rows with betting lines
    df_with_lines = df[df[line_col].notna()].copy()

    if len(df_with_lines) == 0:
        return {'total': 0, 'wins': 0, 'hit_rate': 0.0}

    df_with_lines['edge'] = df_with_lines[pred_col] - df_with_lines[line_col]
    df_with_lines['recommendation'] = df_with_lines['edge'].apply(
        lambda e: 'OVER' if e >= edge_threshold else ('UNDER' if e <= -edge_threshold else 'PASS')
    )

    # Filter to actionable picks
    picks = df_with_lines[df_with_lines['recommendation'] != 'PASS'].copy()

    if len(picks) == 0:
        return {'total': 0, 'wins': 0, 'hit_rate': 0.0}

    # Determine actual result
    picks['actual_result'] = picks.apply(
        lambda row: 'OVER' if row[actual_col] > row[line_col]
                    else ('UNDER' if row[actual_col] < row[line_col] else 'PUSH'),
        axis=1
    )

    # Exclude pushes
    picks = picks[picks['actual_result'] != 'PUSH']

    if len(picks) == 0:
        return {'total': 0, 'wins': 0, 'hit_rate': 0.0}

    # Calculate correctness
    picks['is_correct'] = picks['recommendation'] == picks['actual_result']

    total = len(picks)
    wins = picks['is_correct'].sum()
    hit_rate = wins / total * 100

    # Edge bucket analysis
    logger.info(f"  Edge Bucket Analysis (threshold={edge_threshold}):")
    for bucket_min, bucket_max in [(0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 100)]:
        bucket_picks = picks[(picks['edge'].abs() >= bucket_min) & (picks['edge'].abs() < bucket_max)]
        if len(bucket_picks) > 0:
            bucket_wr = bucket_picks['is_correct'].mean() * 100
            logger.info(f"    Edge {bucket_min}-{bucket_max}: {len(bucket_picks)} picks, {bucket_wr:.1f}% win rate")

    return {
        'total': total,
        'wins': wins,
        'hit_rate': hit_rate,
        'by_direction': {
            'OVER': {
                'total': len(picks[picks['recommendation'] == 'OVER']),
                'wins': picks[picks['recommendation'] == 'OVER']['is_correct'].sum(),
            },
            'UNDER': {
                'total': len(picks[picks['recommendation'] == 'UNDER']),
                'wins': picks[picks['recommendation'] == 'UNDER']['is_correct'].sum(),
            }
        }
    }

# Calculate with different thresholds
logger.info("V2 Hit Rate Analysis:")

for threshold in [0.5, 1.0]:
    result = calculate_hit_rate(test_df, 'v2_predicted', 'strikeouts_line', 'actual_strikeouts', threshold)
    logger.info(f"Threshold {threshold}:")
    logger.info(f"  Total picks: {result['total']}")
    logger.info(f"  Wins: {result['wins']}")
    logger.info(f"  Hit Rate: {result['hit_rate']:.2f}%")
    if result['total'] > 0:
        over_stats = result['by_direction']['OVER']
        under_stats = result['by_direction']['UNDER']
        if over_stats['total'] > 0:
            logger.info(f"  OVER: {over_stats['wins']}/{over_stats['total']} ({100*over_stats['wins']/over_stats['total']:.1f}%)")
        if under_stats['total'] > 0:
            logger.info(f"  UNDER: {under_stats['wins']}/{under_stats['total']} ({100*under_stats['wins']/under_stats['total']:.1f}%)")

# ============================================================================
# STEP 7: FEATURE IMPORTANCE
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

# Highlight V2 new features
logger.info("V2 NEW Features importance:")
for feat in ['f15_opponent_team_k_rate', 'f17_ballpark_k_factor']:
    if feat in feat_imp['feature'].values:
        imp = feat_imp[feat_imp['feature'] == feat]['importance'].values[0]
        logger.info(f"  {feat}: {imp*100:.1f}%")

# ============================================================================
# STEP 8: SAVE MODEL
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 8: SAVING MODEL")
logger.info("=" * 80)

model_id = f"pitcher_strikeouts_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
model_path = MODEL_OUTPUT_DIR / f"{model_id}.cbm"

model.save_model(str(model_path))
logger.info(f"Model saved: {model_path}")

# Save metadata
# Calculate final hit rate at 0.5 threshold
final_hit_rate_result = calculate_hit_rate(test_df, 'v2_predicted', 'strikeouts_line', 'actual_strikeouts', 0.5)

metadata = {
    'model_id': model_id,
    'model_version': 'v2',
    'algorithm': 'catboost',
    'trained_at': datetime.now().isoformat(),
    'samples': len(df),
    'feature_count': len(available_features),
    'features': available_features,
    'train_mae': float(train_metrics['mae']),
    'val_mae': float(val_metrics['mae']),
    'test_mae': float(test_metrics['mae']),
    'test_hit_rate': float(final_hit_rate_result['hit_rate']),
    'test_picks': int(final_hit_rate_result['total']),
    'v1_baseline_mae': V1_MAE,
    'v1_baseline_hit_rate': V1_HIT_RATE,
    'hyperparameters': {k: v for k, v in params.items() if k not in ['verbose', 'early_stopping_rounds']}
}

metadata_path = MODEL_OUTPUT_DIR / f"{model_id}_metadata.json"
with open(metadata_path, 'w') as f:
    json.dump(metadata, f, indent=2, default=str)

logger.info(f"Metadata saved: {metadata_path}")

# ============================================================================
# SUMMARY
# ============================================================================

logger.info("=" * 80)
logger.info(" V2 TRAINING COMPLETE")
logger.info("=" * 80)
logger.info("")
logger.info(f"Model: {model_id}")
logger.info(f"Algorithm: CatBoost")
logger.info(f"Features: {len(available_features)}")
logger.info("")
logger.info("Performance Comparison:")
logger.info(f"  {'Metric':<15} {'V1':<12} {'V2':<12} {'Change':<10}")
logger.info(f"  {'-'*50}")
logger.info(f"  {'MAE':<15} {V1_MAE:<12.2f} {test_metrics['mae']:<12.2f} {mae_improvement:+.1f}%")
logger.info(f"  {'Hit Rate':<15} {V1_HIT_RATE:<12.2f}% {final_hit_rate_result['hit_rate']:<12.2f}%")
logger.info("")

# Determine if V2 is promotion-ready
is_better = test_metrics['mae'] <= V1_MAE and final_hit_rate_result['hit_rate'] >= V1_HIT_RATE

if is_better:
    logger.info("V2 READY FOR PROMOTION")
    logger.info("Next steps:")
    logger.info(f"  1. gsutil cp {model_path} gs://nba-scraped-data/ml-models/mlb/")
    logger.info(f"  2. gsutil cp {metadata_path} gs://nba-scraped-data/ml-models/mlb/")
    logger.info("  3. Update V2 predictor to load this model")
elif test_metrics['mae'] <= V1_MAE:
    logger.info("V2 HAS LOWER MAE - consider promoting if hit rate improves with more data")
else:
    logger.info("V2 NEEDS MORE WORK")
    logger.info("Consider:")
    logger.info("  - Adding more features (pitcher splits, game totals)")
    logger.info("  - Tuning hyperparameters")
    logger.info("  - Using larger edge thresholds")

logger.info("")

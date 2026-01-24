#!/usr/bin/env python3
"""
Train Real XGBoost Model to Replace Mock

This script trains a real XGBoost model on historical NBA prediction data
to replace the mock model currently in production.

Usage:
    python ml/train_real_xgboost.py

Expected improvement: 3-7% over mock baseline (4.33 MAE → 4.0-4.2 MAE)
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import xgboost as xgb
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split

logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models")
MODEL_OUTPUT_DIR.mkdir(exist_ok=True)

logger.info("=" * 80)
logger.info(" TRAINING REAL XGBOOST MODEL TO REPLACE MOCK")
logger.info("=" * 80)
logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
logger.info("")

# ============================================================================
# STEP 1: EXTRACT TRAINING DATA FROM BIGQUERY
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 1: LOADING TRAINING DATA FROM BIGQUERY")
logger.info("=" * 80)

client = bigquery.Client(project=PROJECT_ID)

# Query to get training data with ALL 25 features (matching mock model)
query = """
WITH player_games AS (
  SELECT
    player_lookup,
    game_date,
    game_id,
    team_abbr,
    opponent_team_abbr,
    points,
    minutes_played,
    usage_rate,
    CAST(starter_flag AS INT64) as is_starter,
    -- Shot distribution
    SAFE_DIVIDE(paint_attempts, NULLIF(fg_attempts, 0)) * 100 as paint_rate,
    SAFE_DIVIDE(mid_range_attempts, NULLIF(fg_attempts, 0)) * 100 as mid_range_rate,
    SAFE_DIVIDE(three_pt_attempts, NULLIF(fg_attempts, 0)) * 100 as three_pt_rate,
    SAFE_DIVIDE(assisted_fg_makes, NULLIF(fg_makes, 0)) * 100 as assisted_rate,
    -- Game context calculated from game_id structure (YYYYMMDD_AWAY_HOME)
    CASE
      WHEN SPLIT(game_id, '_')[SAFE_OFFSET(2)] = team_abbr THEN TRUE
      ELSE FALSE
    END as is_home
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2021-10-01'
    AND game_date < '2024-05-01'
    AND points IS NOT NULL
),

player_performance AS (
  SELECT
    player_lookup,
    game_date,
    team_abbr,
    opponent_team_abbr,
    is_home,
    points as actual_points,

    -- Performance features (rolling averages)
    AVG(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
    ) as points_avg_last_5,

    AVG(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as points_avg_last_10,

    AVG(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) as points_avg_season,

    STDDEV(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as points_std_last_10,

    -- v4 improvement: Use player season average as fallback instead of NULL
    COALESCE(
      AVG(minutes_played) OVER (
        PARTITION BY player_lookup
        ORDER BY game_date
        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
      ),
      AVG(minutes_played) OVER (PARTITION BY player_lookup)
    ) as minutes_avg_last_10,

    -- Rest/fatigue features (using LAG window function)
    DATE_DIFF(
      game_date,
      LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date),
      DAY
    ) as days_rest,

    -- Back-to-back flag
    CASE WHEN DATE_DIFF(
      game_date,
      LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date),
      DAY
    ) = 1 THEN TRUE ELSE FALSE END as back_to_back,

    -- Shot distribution features
    AVG(paint_rate) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as paint_rate_last_10,

    AVG(mid_range_rate) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as mid_range_rate_last_10,

    AVG(three_pt_rate) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as three_pt_rate_last_10,

    AVG(assisted_rate) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as assisted_rate_last_10,

    AVG(usage_rate) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as usage_rate_last_10

  FROM player_games
),

predictions AS (
  SELECT
    player_lookup,
    game_date,
    predicted_points as mock_prediction
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE system_id = 'xgboost_v1'
    AND game_date >= '2021-11-01'
    AND game_date < '2024-05-01'
)

SELECT
  pp.player_lookup,
  pp.game_date,
  pp.actual_points,

  -- Performance features (5) - indices 0-4
  pp.points_avg_last_5,
  pp.points_avg_last_10,
  pp.points_avg_season,
  pp.points_std_last_10,
  pp.minutes_avg_last_10,

  -- Composite factors from precompute (4) - indices 5-8
  COALESCE(pcf.fatigue_score, 70) as fatigue_score,
  COALESCE(pcf.shot_zone_mismatch_score, 0) as shot_zone_mismatch_score,
  COALESCE(pcf.pace_score, 0) as pace_score,
  COALESCE(pcf.usage_spike_score, 0) as usage_spike_score,

  -- Opponent defense metrics from precompute (2) - indices 9-10
  COALESCE(tdz.defensive_rating_last_15, 112.0) as opponent_def_rating_last_15,
  COALESCE(tdz.opponent_pace, 100.0) as opponent_pace_last_15,

  -- Game context features (3) - indices 11-13
  IF(pp.is_home, 1.0, 0.0) as is_home,
  CAST(COALESCE(pp.days_rest, 2) AS FLOAT64) as days_rest,
  IF(COALESCE(pp.back_to_back, FALSE), 1.0, 0.0) as back_to_back,

  -- Shot distribution features (4) - indices 14-17
  pp.paint_rate_last_10,
  pp.mid_range_rate_last_10,
  pp.three_pt_rate_last_10,
  pp.assisted_rate_last_10,

  -- Team metrics from player cache (2) - indices 18-19
  COALESCE(pdc.team_pace_last_10, 100.0) as team_pace_last_10,
  COALESCE(pdc.team_off_rating_last_10, 112.0) as team_off_rating_last_10,

  -- Usage features (1) - index 20
  pp.usage_rate_last_10,

  -- Mock prediction for comparison
  p.mock_prediction

FROM player_performance pp
INNER JOIN predictions p
  ON pp.player_lookup = p.player_lookup
  AND pp.game_date = p.game_date
LEFT JOIN `nba-props-platform.nba_precompute.player_composite_factors` pcf
  ON pp.player_lookup = pcf.player_lookup
  AND pp.game_date = pcf.game_date
LEFT JOIN `nba-props-platform.nba_precompute.team_defense_zone_analysis` tdz
  ON pp.opponent_team_abbr = tdz.team_abbr
  AND pp.game_date = tdz.analysis_date
LEFT JOIN `nba-props-platform.nba_precompute.player_daily_cache` pdc
  ON pp.player_lookup = pdc.player_lookup
  AND pp.game_date = pdc.cache_date
WHERE pp.points_avg_last_5 IS NOT NULL
  AND pp.points_avg_last_10 IS NOT NULL
"""

logger.info("Fetching data from BigQuery...")
logger.info(f"Date range: 2021-11-01 to 2024-05-01")
logger.info("")

df = client.query(query).to_dataframe()

logger.info(f"Loaded {len(df):,} games")
logger.info(f"  Date range: {df['game_date'].min()} to {df['game_date'].max()}")
logger.info(f"  Unique players: {df['player_lookup'].nunique()}")
logger.info("")

# ============================================================================
# STEP 2: FEATURE ENGINEERING & DATA PREPARATION
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 2: PREPARING FEATURES")
logger.info("=" * 80)

# Define feature columns - ALL 25 features matching prediction worker expectations
# ORDER MATTERS! Must match xgboost_v1.py worker expectations exactly
feature_cols = [
    # Performance features (5) - indices 0-4
    'points_avg_last_5',
    'points_avg_last_10',
    'points_avg_season',
    'points_std_last_10',
    'minutes_avg_last_10',

    # Composite factors (4) - indices 5-8
    'fatigue_score',
    'shot_zone_mismatch_score',
    'pace_score',
    'usage_spike_score',

    # Opponent metrics (2) - indices 9-10
    'opponent_def_rating_last_15',
    'opponent_pace_last_15',

    # Game context (3) - indices 11-13
    'is_home',
    'days_rest',
    'back_to_back',

    # Shot distribution (4) - indices 14-17
    'paint_rate_last_10',
    'mid_range_rate_last_10',
    'three_pt_rate_last_10',
    'assisted_rate_last_10',

    # Team metrics (2) - indices 18-19
    'team_pace_last_10',
    'team_off_rating_last_10',

    # Usage (1) - index 20
    'usage_rate_last_10',
]

logger.info(f"v4 MODEL: Using {len(feature_cols)} REAL features (removed 4 placeholders)")
logger.info(f"   - 14 from v2 model")
logger.info(f"   - 7 from v3 model (context/opponent/team)")
logger.info(f"   - Removed: 4 placeholder features (were all zeros)")
logger.info(f"   -> v4 focuses model capacity on real signals!")
logger.info("")

# Target variable (what we're predicting)
target_col = 'actual_points'

# Prepare X (features) and y (target)
X = df[feature_cols].copy()
y = df[target_col].copy()

logger.info(f"Features: {len(feature_cols)} columns")
logger.info(f"Target: {target_col}")
logger.info(f"Samples: {len(X):,}")
logger.info("")

# Convert all columns to float (BigQuery NUMERIC comes as object/Decimal)
logger.info("Converting data types...")
for col in X.columns:
    X[col] = pd.to_numeric(X[col], errors='coerce')
y = pd.to_numeric(y, errors='coerce')
logger.info(f"All features converted to numeric")
logger.info("")

# Handle missing values (fill with reasonable defaults - feature-specific, not global zeros)
logger.info("Handling missing values with feature-specific defaults...")
missing_before = X.isnull().sum().sum()

# Performance features
X['points_std_last_10'] = X['points_std_last_10'].fillna(5.0)

# Composite factors
X['fatigue_score'] = X['fatigue_score'].fillna(70)
X['shot_zone_mismatch_score'] = X['shot_zone_mismatch_score'].fillna(0)
X['pace_score'] = X['pace_score'].fillna(0)
X['usage_spike_score'] = X['usage_spike_score'].fillna(0)

# v4: Removed placeholder features (no longer needed)

# Opponent metrics (league averages)
X['opponent_def_rating_last_15'] = X['opponent_def_rating_last_15'].fillna(112.0)
X['opponent_pace_last_15'] = X['opponent_pace_last_15'].fillna(100.0)

# Game context
X['is_home'] = X['is_home'].fillna(0)  # 0 = away, 1 = home
X['days_rest'] = X['days_rest'].fillna(2)  # Median rest
X['back_to_back'] = X['back_to_back'].fillna(0)  # Most games aren't B2B

# Shot distribution (typical percentages)
X['paint_rate_last_10'] = X['paint_rate_last_10'].fillna(30.0)
X['mid_range_rate_last_10'] = X['mid_range_rate_last_10'].fillna(20.0)
X['three_pt_rate_last_10'] = X['three_pt_rate_last_10'].fillna(30.0)
X['assisted_rate_last_10'] = X['assisted_rate_last_10'].fillna(60.0)

# Team metrics (league averages)
X['team_pace_last_10'] = X['team_pace_last_10'].fillna(100.0)
X['team_off_rating_last_10'] = X['team_off_rating_last_10'].fillna(112.0)

# Usage
X['usage_rate_last_10'] = X['usage_rate_last_10'].fillna(25.0)

# Check for any remaining nulls (should be 0)
missing_after = X.isnull().sum().sum()
if missing_after > 0:
    logger.warning(f"WARNING: {missing_after} missing values remain!")
    logger.warning("Columns with missing values:")
    logger.warning(X.isnull().sum()[X.isnull().sum() > 0])
    # Fill any remaining with 0 as last resort
    X = X.fillna(0)
    logger.info("-> Filled remaining with 0")

logger.info(f"Missing values handled: {missing_before} -> {missing_after}")
logger.info("")

# ============================================================================
# STEP 3: SPLIT DATA (CHRONOLOGICAL)
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 3: SPLITTING DATA CHRONOLOGICALLY")
logger.info("=" * 80)

# Split chronologically to simulate real-world deployment
# Training: oldest 70% | Validation: next 15% | Test: newest 15%

df_sorted = df.sort_values('game_date').reset_index(drop=True)
n = len(df_sorted)

train_end = int(n * 0.70)
val_end = int(n * 0.85)

train_idx = df_sorted.index[:train_end]
val_idx = df_sorted.index[train_end:val_end]
test_idx = df_sorted.index[val_end:]

X_train = X.iloc[train_idx]
y_train = y.iloc[train_idx]
train_dates = df_sorted.iloc[train_idx]

X_val = X.iloc[val_idx]
y_val = y.iloc[val_idx]
val_dates = df_sorted.iloc[val_idx]

X_test = X.iloc[test_idx]
y_test = y.iloc[test_idx]
test_dates = df_sorted.iloc[test_idx]

logger.info(f"Training set:   {len(X_train):,} games ({train_dates['game_date'].min()} to {train_dates['game_date'].max()})")
logger.info(f"Validation set: {len(X_val):,} games ({val_dates['game_date'].min()} to {val_dates['game_date'].max()})")
logger.info(f"Test set:       {len(X_test):,} games ({test_dates['game_date'].min()} to {test_dates['game_date'].max()})")
logger.info("")

# ============================================================================
# STEP 4: TRAIN XGBOOST MODEL
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 4: TRAINING XGBOOST MODEL")
logger.info("=" * 80)

# Hyperparameters - v4 improvements for better performance
# Changes from v3:
# - Increased max_depth (6→8) to learn complex non-linear rules
# - Decreased learning_rate (0.1→0.05) for better convergence
# - Increased n_estimators (200→500) with early stopping
# - Increased min_child_weight (1→3) for regularization
params = {
    'max_depth': 8,  # Deeper trees to learn complex patterns (was 6)
    'learning_rate': 0.05,  # Slower learning for better convergence (was 0.1)
    'n_estimators': 500,  # More trees with early stopping (was 200)
    'min_child_weight': 3,  # Regularization to prevent overfitting (was 1)
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'gamma': 0,
    'reg_alpha': 0,
    'reg_lambda': 1,
    'random_state': 42,
    'objective': 'reg:squarederror',
    'eval_metric': 'mae',
    'early_stopping_rounds': 20  # Stop if no improvement for 20 rounds
}

logger.info("Hyperparameters (v4 - improved for complex rule learning):")
for key, value in params.items():
    logger.info(f"  {key}: {value}")
logger.info("")

logger.info(f"Training up to {params['n_estimators']} trees (with early stopping)...")
model = xgb.XGBRegressor(**params)

# Train with early stopping on validation set
model.fit(
    X_train, y_train,
    eval_set=[(X_val, y_val)],  # Only validate on val set for early stopping
    verbose=20  # Print every 20 iterations
)

logger.info("")
logger.info("Training complete!")
logger.info("")

# ============================================================================
# STEP 5: EVALUATE MODEL
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 5: EVALUATING MODEL PERFORMANCE")
logger.info("=" * 80)

def evaluate_model(y_true, y_pred, dataset_name="Test"):
    """Calculate evaluation metrics"""
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))

    # Calculate accuracy metrics
    errors = np.abs(y_true - y_pred)
    within_1 = (errors <= 1).mean() * 100
    within_3 = (errors <= 3).mean() * 100
    within_5 = (errors <= 5).mean() * 100

    logger.info(f"\n{dataset_name} Set Evaluation")
    logger.info("-" * 40)
    logger.info(f"MAE (Mean Absolute Error):     {mae:.2f} points")
    logger.info(f"RMSE (Root Mean Squared Error): {rmse:.2f} points")
    logger.info(f"Within 1 point:                 {within_1:.1f}%")
    logger.info(f"Within 3 points:                {within_3:.1f}%")
    logger.info(f"Within 5 points:                {within_5:.1f}%")
    logger.info(f"Samples:                        {len(y_true):,}")

    return {
        'mae': mae,
        'rmse': rmse,
        'within_1': within_1,
        'within_3': within_3,
        'within_5': within_5
    }

# Evaluate on all splits
train_pred = model.predict(X_train)
val_pred = model.predict(X_val)
test_pred = model.predict(X_test)

train_metrics = evaluate_model(y_train, train_pred, "Training")
val_metrics = evaluate_model(y_val, val_pred, "Validation")
test_metrics = evaluate_model(y_test, test_pred, "Test")

# ============================================================================
# STEP 6: COMPARE TO PRODUCTION MOCK BASELINE
# ============================================================================

logger.info("\n" + "=" * 80)
logger.info("STEP 6: COMPARISON TO PRODUCTION MOCK BASELINE")
logger.info("=" * 80)

# Query actual production mock predictions (FIX: don't use mock_prediction column)
# The mock_prediction column in the training data is corrupted/placeholder data
# We need to query the actual production system's predictions
logger.info("\nQuerying production mock predictions from BigQuery...")
production_query = f"""
SELECT
  player_lookup,
  game_date,
  actual_points,
  predicted_points as mock_prediction
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'xgboost_v1'
  AND game_date >= '{test_dates["game_date"].min()}'
  AND game_date <= '{test_dates["game_date"].max()}'
"""

try:
    mock_df = client.query(production_query).to_dataframe()

    # Merge with test set
    test_with_mock = test_dates[['player_lookup', 'game_date', 'actual_points']].merge(
        mock_df[['player_lookup', 'game_date', 'mock_prediction']],
        on=['player_lookup', 'game_date'],
        how='inner'
    )

    if len(test_with_mock) == 0:
        logger.warning("WARNING: No matching production predictions found!")
        logger.warning("   Falling back to mock_prediction column (may be inaccurate)")
        mock_predictions = df_sorted.iloc[test_idx]['mock_prediction'].values
        mock_mae = mean_absolute_error(y_test, mock_predictions)
        mock_coverage = 0
    else:
        # Calculate proper mock MAE from production data
        mock_mae = mean_absolute_error(
            test_with_mock['actual_points'],
            test_with_mock['mock_prediction']
        )

        # Also calculate mock accuracy metrics
        errors = np.abs(test_with_mock['actual_points'] - test_with_mock['mock_prediction'])
        mock_within_3 = (errors <= 3).mean() * 100
        mock_within_5 = (errors <= 5).mean() * 100
        mock_coverage = len(test_with_mock) / len(test_dates) * 100

        logger.info(f"Matched {len(test_with_mock):,}/{len(test_dates):,} test predictions ({mock_coverage:.1f}% coverage)")
        logger.info(f"  Production Mock MAE: {mock_mae:.2f}")
        logger.info(f"  Production Mock within 3 pts: {mock_within_3:.1f}%")
        logger.info(f"  Production Mock within 5 pts: {mock_within_5:.1f}%")

except Exception as e:
    logger.error(f"ERROR querying production predictions: {e}")
    logger.warning("   Falling back to mock_prediction column (may be inaccurate)")
    mock_predictions = df_sorted.iloc[test_idx]['mock_prediction'].values
    mock_mae = mean_absolute_error(y_test, mock_predictions)
    mock_coverage = 0

real_mae = test_metrics['mae']
improvement = ((mock_mae - real_mae) / mock_mae) * 100

# Known production baseline (verified from BigQuery on 2026-01-03)
PRODUCTION_BASELINE_MAE = 4.27

logger.info(f"\nProduction Mock (xgboost_v1):  {mock_mae:.2f} MAE")
logger.info(f"Real XGBoost (trained):        {real_mae:.2f} MAE")
logger.info(f"Difference:                    {improvement:+.1f}%")
logger.info("")

# Updated success criteria using CORRECT baseline
if real_mae < PRODUCTION_BASELINE_MAE:
    logger.info("SUCCESS! Real model beats production baseline (4.27 MAE)")
    logger.info("   -> Ready for production deployment")
elif real_mae < mock_mae and mock_coverage > 80:
    logger.warning(f"Beats test period mock ({mock_mae:.2f}) but NOT production baseline ({PRODUCTION_BASELINE_MAE})")
    logger.warning("   -> May have train/test distribution mismatch")
    logger.warning("   -> Need more investigation before deployment")
elif abs(improvement) < 5:
    logger.warning(f"Within 5% of test period mock - marginal difference")
    logger.warning(f"   -> Still worse than production baseline ({PRODUCTION_BASELINE_MAE} MAE)")
    logger.warning("   -> Consider: more data, better features, or accept mock baseline")
else:
    logger.warning(f"Significantly worse than test period mock ({mock_mae:.2f})")
    logger.warning(f"   -> Also worse than production baseline ({PRODUCTION_BASELINE_MAE} MAE)")
    logger.warning("   -> Recommendation: Accept mock baseline, focus on data quality")

logger.info("")

# ============================================================================
# STEP 7: FEATURE IMPORTANCE
# ============================================================================

logger.info("=" * 80)
logger.info("TOP 10 MOST IMPORTANT FEATURES")
logger.info("=" * 80)
logger.info("(Higher score = more important for predictions)\n")

# Get feature importance
importance = model.feature_importances_
feature_importance = pd.DataFrame({
    'feature': feature_cols,
    'importance': importance
}).sort_values('importance', ascending=False)

for idx, row in feature_importance.head(10).iterrows():
    bar_length = int(row['importance'] * 100)
    bar = '█' * (bar_length // 2)
    logger.info(f"{row['feature']:30s} {row['importance']*100:5.1f}% {bar}")

logger.info("")

# ============================================================================
# STEP 8: SAVE MODEL
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 8: SAVING MODEL")
logger.info("=" * 80)

model_id = f"xgboost_real_v4_21features_{datetime.now().strftime('%Y%m%d')}"
local_path = MODEL_OUTPUT_DIR / f"{model_id}.json"

# Save using booster API (avoids sklearn mixin issues)
model.get_booster().save_model(str(local_path))
logger.info(f"Model saved: {local_path}")

# Save metadata
metadata = {
    'model_id': model_id,
    'trained_at': datetime.now().isoformat(),
    'samples': len(df),
    'features': feature_cols,
    'train_mae': train_metrics['mae'],
    'val_mae': val_metrics['mae'],
    'test_mae': test_metrics['mae'],
    'mock_mae': mock_mae,
    'improvement_pct': improvement,
    'hyperparameters': params
}

import json
metadata_path = MODEL_OUTPUT_DIR / f"{model_id}_metadata.json"
with open(metadata_path, 'w') as f:
    json.dump(metadata, f, indent=2, default=str)

logger.info(f"Metadata saved: {metadata_path}")
logger.info("")

# ============================================================================
# SUMMARY
# ============================================================================

logger.info("=" * 80)
logger.info("TRAINING COMPLETE!")
logger.info("=" * 80)
logger.info("")
logger.info(f"Model ID: {model_id}")
logger.info(f"Test MAE: {real_mae:.2f} (vs mock {mock_mae:.2f})")
logger.info(f"Improvement: {improvement:+.1f}%")
logger.info("")

if improvement > 3.0:
    logger.info("PRODUCTION READY")
    logger.info("\nNext steps:")
    logger.info("1. Upload model to GCS:")
    logger.info(f"   gsutil cp {local_path} gs://nba-scraped-data/ml-models/")
    logger.info("")
    logger.info("2. Update prediction worker to load real model")
    logger.info("   Edit: predictions/worker/prediction_systems/xgboost_v1.py")
    logger.info("")
    logger.info("3. Deploy to Cloud Run:")
    logger.info("   ./bin/predictions/deploy/deploy_prediction_worker.sh")
else:
    logger.warning("Consider hyperparameter tuning or additional features")

logger.info("")
logger.info("=" * 80)

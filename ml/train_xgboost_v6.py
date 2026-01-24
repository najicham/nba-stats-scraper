#!/usr/bin/env python3
"""
Train XGBoost v6 Model - Using Complete Feature Store Data

This script trains XGBoost on the complete ml_feature_store_v2 data (93% coverage)
with improved regularization to prevent overfitting.

Key improvements over v4/v5:
- Uses ml_feature_store_v2 directly (pre-computed 25 features)
- 93% feature coverage (vs 77-89% in v4/v5)
- Stronger regularization to reduce train/test gap
- Targets beating mock v1 baseline (4.80 MAE)

Usage:
    python ml/train_xgboost_v6.py
"""

import logging
import os
import sys
import json
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import xgboost as xgb
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error, mean_squared_error

logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models")
MODEL_OUTPUT_DIR.mkdir(exist_ok=True)

logger.info("=" * 80)
logger.info(" XGBOOST V6 TRAINING - USING COMPLETE FEATURE STORE")
logger.info("=" * 80)
logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
logger.info("")

# ============================================================================
# STEP 1: EXTRACT TRAINING DATA FROM ML_FEATURE_STORE_V2
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 1: LOADING DATA FROM ML_FEATURE_STORE_V2")
logger.info("=" * 80)

client = bigquery.Client(project=PROJECT_ID)

# Query to extract features and targets from feature store
# Joins with player_game_summary to get actual_points (target)
query = """
WITH feature_data AS (
  SELECT
    mf.player_lookup,
    mf.game_date,
    mf.features,
    mf.feature_names,
    mf.feature_count,
    mf.feature_quality_score,
    mf.is_production_ready,
    mf.completeness_percentage
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
  WHERE mf.game_date BETWEEN '2021-11-01' AND '2024-06-01'
    AND mf.feature_count = 25  -- Only complete feature sets
    AND ARRAY_LENGTH(mf.features) = 25  -- Verify array length
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
  fd.feature_quality_score,
  fd.completeness_percentage,
  a.actual_points
FROM feature_data fd
INNER JOIN actuals a
  ON fd.player_lookup = a.player_lookup
  AND fd.game_date = a.game_date
ORDER BY fd.game_date, fd.player_lookup
"""

logger.info("Fetching data from BigQuery...")
logger.info("Date range: 2021-11-01 to 2024-06-01")
logger.info("")

df = client.query(query).to_dataframe()

logger.info(f"Loaded {len(df):,} player-game samples")
logger.info(f"Date range: {df['game_date'].min()} to {df['game_date'].max()}")
logger.info(f"Unique players: {df['player_lookup'].nunique()}")
logger.info("")

# Check data quality
avg_quality = df['feature_quality_score'].astype(float).mean()
avg_completeness = df['completeness_percentage'].astype(float).mean()
logger.info(f"Average feature quality score: {avg_quality:.1f}%")
logger.info(f"Average completeness: {avg_completeness:.1f}%")
logger.info("")

# ============================================================================
# STEP 2: PREPARE FEATURES
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 2: PREPARING FEATURES")
logger.info("=" * 80)

# Feature names (from first row - they're all the same)
feature_names = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct"
]

logger.info(f"Features ({len(feature_names)}):")
for i, name in enumerate(feature_names):
    logger.info(f"  [{i:2d}] {name}")
logger.info("")

# Convert feature arrays to DataFrame columns
logger.info("Extracting features from arrays...")
X = pd.DataFrame(df['features'].tolist(), columns=feature_names)
y = df['actual_points'].astype(float)

# Handle any remaining nulls
logger.info("Checking for null values...")
null_counts = X.isnull().sum()
if null_counts.sum() > 0:
    logger.info(f"Found {null_counts.sum()} null values, filling with median...")
    X = X.fillna(X.median())
else:
    logger.info("No null values found!")
logger.info("")

logger.info(f"Feature matrix shape: {X.shape}")
logger.info(f"Target vector shape: {y.shape}")
logger.info("")

# ============================================================================
# STEP 3: CHRONOLOGICAL TRAIN/VAL/TEST SPLIT
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 3: SPLITTING DATA CHRONOLOGICALLY")
logger.info("=" * 80)

# Sort by date
df_sorted = df.sort_values('game_date').reset_index(drop=True)
n = len(df_sorted)

# 70% train, 15% validation, 15% test
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

logger.info(f"Training set:   {len(X_train):,} ({train_dates['game_date'].min()} to {train_dates['game_date'].max()})")
logger.info(f"Validation set: {len(X_val):,} ({val_dates['game_date'].min()} to {val_dates['game_date'].max()})")
logger.info(f"Test set:       {len(X_test):,} ({test_dates['game_date'].min()} to {test_dates['game_date'].max()})")
logger.info("")

# ============================================================================
# STEP 4: TRAIN XGBOOST WITH STRONGER REGULARIZATION
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 4: TRAINING XGBOOST V6")
logger.info("=" * 80)

# V6 hyperparameters - STRONGER REGULARIZATION to prevent overfitting
# v4/v5 had train/test gap of 0.49 points (4.14 train vs 4.63 test)
# Goal: Reduce this gap while maintaining good test performance
params = {
    # Tree structure - less complex to prevent overfitting
    'max_depth': 6,              # Reduced from 8 (less complex trees)
    'min_child_weight': 10,      # Increased from 3 (more regularization)

    # Learning parameters
    'learning_rate': 0.03,       # Reduced from 0.05 (slower, more robust)
    'n_estimators': 1000,        # More trees with early stopping

    # Sampling - prevent overfitting
    'subsample': 0.7,            # Reduced from 0.8
    'colsample_bytree': 0.7,     # Reduced from 0.8
    'colsample_bylevel': 0.7,    # Additional feature sampling

    # Regularization - KEY CHANGES
    'gamma': 0.1,                # Increased from 0 (min loss reduction)
    'reg_alpha': 0.5,            # L1 regularization (was 0)
    'reg_lambda': 5.0,           # L2 regularization (was 1)

    # Other
    'random_state': 42,
    'objective': 'reg:squarederror',
    'eval_metric': 'mae',
    'early_stopping_rounds': 50  # Increased patience
}

logger.info("V6 Hyperparameters (stronger regularization):")
logger.info("-" * 50)
logger.info(f"  max_depth:        {params['max_depth']} (was 8)")
logger.info(f"  min_child_weight: {params['min_child_weight']} (was 3)")
logger.info(f"  learning_rate:    {params['learning_rate']} (was 0.05)")
logger.info(f"  subsample:        {params['subsample']} (was 0.8)")
logger.info(f"  reg_alpha (L1):   {params['reg_alpha']} (was 0)")
logger.info(f"  reg_lambda (L2):  {params['reg_lambda']} (was 1)")
logger.info(f"  gamma:            {params['gamma']} (was 0)")
logger.info("")

logger.info(f"Training up to {params['n_estimators']} trees (with early stopping at {params['early_stopping_rounds']})...")
logger.info("")

model = xgb.XGBRegressor(**params)

# Train with early stopping
model.fit(
    X_train, y_train,
    eval_set=[(X_train, y_train), (X_val, y_val)],
    verbose=50  # Print every 50 iterations
)

logger.info("")
logger.info(f"Training complete! Best iteration: {model.best_iteration}")
logger.info("")

# ============================================================================
# STEP 5: EVALUATE MODEL
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 5: EVALUATION")
logger.info("=" * 80)

def evaluate_set(y_true, y_pred, name):
    """Evaluate predictions on a dataset."""
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    errors = np.abs(y_true - y_pred)
    within_3 = (errors <= 3).mean() * 100
    within_5 = (errors <= 5).mean() * 100

    logger.info(f"\n{name} Set:")
    logger.info(f"  MAE:  {mae:.3f} points")
    logger.info(f"  RMSE: {rmse:.3f} points")
    logger.info(f"  Within 3 pts: {within_3:.1f}%")
    logger.info(f"  Within 5 pts: {within_5:.1f}%")

    return mae, rmse

train_pred = model.predict(X_train)
val_pred = model.predict(X_val)
test_pred = model.predict(X_test)

train_mae, _ = evaluate_set(y_train, train_pred, "Training")
val_mae, _ = evaluate_set(y_val, val_pred, "Validation")
test_mae, _ = evaluate_set(y_test, test_pred, "Test")

# Check overfitting
train_test_gap = test_mae - train_mae
logger.info(f"\nTrain/Test Gap: {train_test_gap:.3f} points")
if train_test_gap > 0.3:
    logger.info("  (Some overfitting - gap > 0.3)")
elif train_test_gap > 0.2:
    logger.info("  (Minimal overfitting - gap 0.2-0.3)")
else:
    logger.info("  (Well regularized - gap < 0.2)")

# ============================================================================
# STEP 6: COMPARE TO MOCK BASELINE
# ============================================================================

logger.info("\n" + "=" * 80)
logger.info("STEP 6: COMPARISON TO MOCK V1 BASELINE")
logger.info("=" * 80)

# Mock v1 baseline from Phase 1 evaluation: 4.80 MAE
MOCK_BASELINE_MAE = 4.80

logger.info(f"\nMock v1 baseline:     {MOCK_BASELINE_MAE:.2f} MAE")
logger.info(f"XGBoost v6 test:      {test_mae:.2f} MAE")
improvement = ((MOCK_BASELINE_MAE - test_mae) / MOCK_BASELINE_MAE) * 100
logger.info(f"Improvement:          {improvement:+.1f}%")
logger.info("")

if test_mae < MOCK_BASELINE_MAE:
    logger.info("SUCCESS! XGBoost v6 beats mock baseline!")
    if improvement > 5:
        logger.info("DECISIVE WIN - >5% improvement")
    else:
        logger.info("Marginal win - consider ensemble approach")
else:
    logger.info("XGBoost v6 did not beat mock baseline")
    logger.info("Consider: Mock model is already well-tuned")

# ============================================================================
# STEP 7: FEATURE IMPORTANCE
# ============================================================================

logger.info("\n" + "=" * 80)
logger.info("STEP 7: TOP 10 FEATURE IMPORTANCE")
logger.info("=" * 80)

importance = model.feature_importances_
feat_imp = pd.DataFrame({
    'feature': feature_names,
    'importance': importance
}).sort_values('importance', ascending=False)

logger.info("")
for i, row in feat_imp.head(10).iterrows():
    bar = '' * int(row['importance'] * 50)
    logger.info(f"  {row['feature']:25s} {row['importance']*100:5.1f}% {bar}")

# ============================================================================
# STEP 8: SAVE MODEL
# ============================================================================

logger.info("\n" + "=" * 80)
logger.info("STEP 8: SAVING MODEL")
logger.info("=" * 80)

model_id = f"xgboost_v6_25features_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
model_path = MODEL_OUTPUT_DIR / f"{model_id}.json"

# Save model
model.get_booster().save_model(str(model_path))
logger.info(f"Model saved: {model_path}")

# Save metadata
metadata = {
    'model_id': model_id,
    'version': 'v6',
    'trained_at': datetime.now().isoformat(),
    'training_samples': len(df),
    'features': feature_names,
    'feature_count': len(feature_names),
    'train_mae': float(train_mae),
    'val_mae': float(val_mae),
    'test_mae': float(test_mae),
    'train_test_gap': float(train_test_gap),
    'mock_baseline_mae': MOCK_BASELINE_MAE,
    'improvement_vs_mock_pct': float(improvement),
    'hyperparameters': params,
    'best_iteration': model.best_iteration,
    'data_source': 'ml_feature_store_v2',
    'data_coverage': f"{avg_completeness:.1f}%"
}

metadata_path = MODEL_OUTPUT_DIR / f"{model_id}_metadata.json"
with open(metadata_path, 'w') as f:
    json.dump(metadata, f, indent=2, default=str)
logger.info(f"Metadata saved: {metadata_path}")

# ============================================================================
# SUMMARY
# ============================================================================

logger.info("\n" + "=" * 80)
logger.info("TRAINING COMPLETE - SUMMARY")
logger.info("=" * 80)
logger.info("")
logger.info(f"Model:              XGBoost v6")
logger.info(f"Features:           25 (from ml_feature_store_v2)")
logger.info(f"Training samples:   {len(df):,}")
logger.info(f"Data coverage:      {avg_completeness:.1f}%")
logger.info("")
logger.info(f"Training MAE:       {train_mae:.3f}")
logger.info(f"Validation MAE:     {val_mae:.3f}")
logger.info(f"Test MAE:           {test_mae:.3f}")
logger.info(f"Train/Test Gap:     {train_test_gap:.3f}")
logger.info("")
logger.info(f"Mock v1 baseline:   {MOCK_BASELINE_MAE:.2f}")
logger.info(f"Improvement:        {improvement:+.1f}%")
logger.info("")

if test_mae < MOCK_BASELINE_MAE:
    logger.info("RESULT: XGBoost v6 WINS")
else:
    logger.info("RESULT: Mock v1 still better")

logger.info("")
logger.info("=" * 80)

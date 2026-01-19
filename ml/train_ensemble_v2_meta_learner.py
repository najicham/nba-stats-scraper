#!/usr/bin/env python3
"""
Ensemble V2 - Ridge Meta-Learner Training

This script trains a Ridge regression meta-learner that optimally combines predictions
from 5 base prediction systems:
  1. Moving Average Baseline
  2. Zone Matchup V1
  3. Similarity Balanced V1
  4. XGBoost V1 (or mock)
  5. CatBoost V8

The meta-learner learns optimal weights for each system based on historical performance.

Usage:
    PYTHONPATH=. python ml/train_ensemble_v2_meta_learner.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import json
import joblib
from datetime import datetime
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.linear_model import Ridge
from tqdm import tqdm

# Import prediction systems
from predictions.worker.prediction_systems.moving_average_baseline import MovingAverageBaseline
from predictions.worker.prediction_systems.zone_matchup_v1 import ZoneMatchupV1
from predictions.worker.prediction_systems.similarity_balanced_v1 import SimilarityBalancedV1
from predictions.worker.prediction_systems.xgboost_v1 import XGBoostV1
from predictions.worker.prediction_systems.catboost_v8 import CatBoostV8

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models")
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

print("=" * 80)
print(" ENSEMBLE V2 - RIDGE META-LEARNER TRAINING")
print("=" * 80)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================================================
# STEP 1: LOAD HISTORICAL DATA
# ============================================================================

print("=" * 80)
print("STEP 1: LOADING HISTORICAL DATA")
print("=" * 80)

client = bigquery.Client(project=PROJECT_ID)

# Simplified query - get features and actuals directly
# Features array already contains all 33 features (including Vegas, opponent history, minutes/PPM)
query = """
SELECT
  mf.player_lookup,
  mf.game_date,
  mf.features,
  pgs.points as actual_points
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
  ON mf.player_lookup = pgs.player_lookup
  AND mf.game_date = pgs.game_date
WHERE mf.game_date BETWEEN '2021-11-01' AND '2024-06-01'
  AND mf.feature_count = 33
  AND ARRAY_LENGTH(mf.features) = 33
  AND pgs.points IS NOT NULL
  AND pgs.minutes_played > 0
ORDER BY mf.game_date
"""

print("Fetching data from BigQuery...")
print("Note: This may take 2-5 minutes due to historical game aggregations...")
df = client.query(query).to_dataframe()
print(f"✓ Loaded {len(df):,} samples")
print()

# ============================================================================
# STEP 2: GENERATE BASE SYSTEM PREDICTIONS
# ============================================================================

print("=" * 80)
print("STEP 2: GENERATING BASE SYSTEM PREDICTIONS")
print("=" * 80)
print("This will take 10-20 minutes to run 4 systems on ~76K games...")
print("Note: Skipping Similarity system (requires historical games data)")
print()

# Initialize prediction systems (skip Similarity for now)
print("Initializing prediction systems...")
systems = {
    'moving_average': MovingAverageBaseline(),
    'zone_matchup': ZoneMatchupV1(),
    'xgboost_v1': XGBoostV1(),
    'catboost_v8': CatBoostV8()
}
print("✓ All systems initialized")
print()

# Feature names (33 features total)
base_features = [
    # Base features (0-24)
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct",
    # Vegas features (25-28)
    "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line",
    # Opponent history (29-30)
    "avg_points_vs_opponent", "games_vs_opponent",
    # Minutes/PPM (31-32)
    "minutes_avg_last_10", "ppm_avg_last_10"
]

# Storage for predictions (4 systems only for now)
predictions_meta = {
    'moving_average': [],
    'zone_matchup': [],
    'xgboost_v1': [],
    'catboost_v8': []
}
actuals = []
valid_indices = []

print("Generating predictions from 4 systems...")
for idx, row in tqdm(df.iterrows(), total=len(df), desc="Processing games"):
    try:
        # Prepare features dict
        features = dict(zip(base_features, row['features']))

        # Get predictions from each system
        system_preds = {}
        all_succeeded = True

        # Moving Average
        try:
            ma_pred, _, _ = systems['moving_average'].predict(
                features=features,
                player_lookup=row['player_lookup'],
                game_date=row['game_date'],
                prop_line=features.get('vegas_points_line', None)
            )
            system_preds['moving_average'] = ma_pred
        except Exception as e:
            if idx < 5:  # Log first 5 errors
                print(f"Moving Average failed for game {idx}: {e}")
            all_succeeded = False

        # Zone Matchup
        try:
            zm_pred, _, _ = systems['zone_matchup'].predict(
                features=features,
                player_lookup=row['player_lookup'],
                game_date=row['game_date'],
                prop_line=features.get('vegas_points_line', None)
            )
            system_preds['zone_matchup'] = zm_pred
        except Exception:
            all_succeeded = False

        # XGBoost V1
        try:
            xgb_result = systems['xgboost_v1'].predict(
                features=features,
                player_lookup=row['player_lookup'],
                game_date=row['game_date'],
                prop_line=features.get('vegas_points_line', None)
            )
            system_preds['xgboost_v1'] = xgb_result['predicted_points']
        except Exception:
            all_succeeded = False

        # CatBoost V8
        try:
            cb_result = systems['catboost_v8'].predict(
                features=features,
                player_lookup=row['player_lookup'],
                game_date=row['game_date'],
                prop_line=features.get('vegas_points_line', None)
            )
            system_preds['catboost_v8'] = cb_result['predicted_points']
        except Exception:
            all_succeeded = False

        # Only include if all 4 systems succeeded
        if all_succeeded and len(system_preds) == 4:
            for system_name in predictions_meta.keys():
                predictions_meta[system_name].append(system_preds[system_name])
            actuals.append(row['actual_points'])
            valid_indices.append(idx)

    except Exception as e:
        # Skip this sample if any error occurs
        continue

print()
print(f"✓ Generated predictions for {len(actuals):,} samples")
print(f"  (Dropped {len(df) - len(actuals):,} samples due to missing data or system failures)")
print()

# Convert to numpy arrays (4 systems)
X_meta = np.column_stack([
    predictions_meta['moving_average'],
    predictions_meta['zone_matchup'],
    predictions_meta['xgboost_v1'],
    predictions_meta['catboost_v8']
])
y = np.array(actuals)

print(f"Meta-feature matrix shape: {X_meta.shape}")
print(f"Target shape: {y.shape}")
print()

# ============================================================================
# STEP 3: CHRONOLOGICAL SPLIT
# ============================================================================

print("=" * 80)
print("STEP 3: CHRONOLOGICAL TRAIN/VAL/TEST SPLIT")
print("=" * 80)

n = len(X_meta)
train_end = int(n * 0.70)
val_end = int(n * 0.85)

X_train, X_val, X_test = X_meta[:train_end], X_meta[train_end:val_end], X_meta[val_end:]
y_train, y_val, y_test = y[:train_end], y[train_end:val_end], y[val_end:]

print(f"Train: {len(X_train):,} samples")
print(f"Val:   {len(X_val):,} samples")
print(f"Test:  {len(X_test):,} samples")
print()

# ============================================================================
# STEP 4: TRAIN RIDGE META-LEARNER
# ============================================================================

print("=" * 80)
print("STEP 4: TRAINING RIDGE META-LEARNER")
print("=" * 80)

# Try different alpha values
alphas = [0.1, 0.5, 1.0, 2.0, 5.0]
best_alpha = None
best_val_mae = float('inf')
results = {}

print("Testing different Ridge alpha values...")
for alpha in alphas:
    ridge = Ridge(alpha=alpha)
    ridge.fit(X_train, y_train)
    val_pred = ridge.predict(X_val)
    val_mae = mean_absolute_error(y_val, val_pred)
    results[alpha] = {'mae': val_mae, 'model': ridge}
    print(f"  alpha={alpha:4.1f} → Val MAE: {val_mae:.4f}")

    if val_mae < best_val_mae:
        best_val_mae = val_mae
        best_alpha = alpha

print()
print(f"✓ Best alpha: {best_alpha} (Val MAE: {best_val_mae:.4f})")
print()

# Use best model
best_model = results[best_alpha]['model']
test_pred = best_model.predict(X_test)
test_mae = mean_absolute_error(y_test, test_pred)
test_rmse = np.sqrt(mean_squared_error(y_test, test_pred))

print("=" * 80)
print("STEP 5: FINAL RESULTS")
print("=" * 80)
print()
print(f"Test MAE:  {test_mae:.4f}")
print(f"Test RMSE: {test_rmse:.4f}")
print()

# Learned weights
weights = best_model.coef_
weight_pct = weights / weights.sum() * 100
system_names = ['Moving Avg', 'Zone Matchup', 'XGBoost V1', 'CatBoost V8']

print("Learned System Weights:")
print("-" * 50)
for name, weight, pct in zip(system_names, weights, weight_pct):
    print(f"  {name:20s}  {weight:6.3f}  ({pct:5.1f}%)")
print()

# Compare to individual systems on test set
print("Individual System Performance on Test Set:")
print("-" * 50)
for i, name in enumerate(system_names):
    individual_mae = mean_absolute_error(y_test, X_test[:, i])
    print(f"  {name:20s}  MAE: {individual_mae:.4f}")
print()
print(f"  {'Ridge Ensemble':20s}  MAE: {test_mae:.4f}  ⭐")
print()

# ============================================================================
# STEP 6: SAVE MODEL
# ============================================================================

print("=" * 80)
print("STEP 6: SAVING MODEL")
print("=" * 80)

model_filename = f"ensemble_v2_ridge_meta_{TIMESTAMP}.pkl"
model_path = MODEL_OUTPUT_DIR / model_filename
joblib.dump(best_model, model_path)
print(f"✓ Model saved: {model_path}")

# Save metadata
metadata = {
    'model_type': 'Ridge Meta-Learner',
    'version': 'v2',
    'num_systems': 4,
    'note': 'Trained on 4 systems (Similarity excluded - requires historical games)',
    'timestamp': TIMESTAMP,
    'training_samples': len(X_train),
    'validation_samples': len(X_val),
    'test_samples': len(X_test),
    'test_mae': float(test_mae),
    'test_rmse': float(test_rmse),
    'best_alpha': float(best_alpha),
    'system_names': system_names,
    'learned_weights': [float(w) for w in weights],
    'weight_percentages': [float(p) for p in weight_pct],
    'intercept': float(best_model.intercept_),
    'data_range': '2021-11-01 to 2024-06-01',
    'individual_system_test_mae': {
        name: float(mean_absolute_error(y_test, X_test[:, i]))
        for i, name in enumerate(system_names)
    }
}

metadata_filename = f"ensemble_v2_ridge_meta_{TIMESTAMP}_metadata.json"
metadata_path = MODEL_OUTPUT_DIR / metadata_filename
with open(metadata_path, 'w') as f:
    json.dump(metadata, f, indent=2)
print(f"✓ Metadata saved: {metadata_path}")
print()

print("=" * 80)
print("✅ TRAINING COMPLETE")
print("=" * 80)
print()
print(f"Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()
print("Next steps:")
print("  1. Review metadata file for learned weights")
print("  2. Create ensemble_v2.py prediction system using this model")
print("  3. Test in shadow mode alongside existing systems")
print("  4. Deploy if Test MAE < 4.7 (beats CatBoost V8 target)")
print()

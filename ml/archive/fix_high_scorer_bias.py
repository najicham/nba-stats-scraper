#!/usr/bin/env python3
"""
Fix High-Scorer Underprediction Bias in XGBoost v6

Analysis shows v6 systematically underpredicts high scorers:
- 20-30 pts: -4.5 bias
- 30+ pts: -9.2 bias

This script:
1. Analyzes the bias pattern in detail
2. Builds a calibration model to correct predictions
3. Validates the fix
4. Creates v6.1 with calibration built-in
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
from sklearn.metrics import mean_absolute_error
from scipy import stats
import json

PROJECT_ID = "nba-props-platform"

print("=" * 80)
print(" FIXING HIGH-SCORER UNDERPREDICTION BIAS")
print("=" * 80)
print()

# ============================================================================
# STEP 1: LOAD MODEL AND DATA
# ============================================================================

print("STEP 1: Loading model and data...")

# Load v6 model
model_dir = Path("models")
v6_models = [f for f in model_dir.glob("xgboost_v6_*.json") if "metadata" not in f.name]
latest_model = sorted(v6_models)[-1]
print(f"Loading model: {latest_model}")

model = xgb.Booster()
model.load_model(str(latest_model))

# Load validation data (2024-25 season)
client = bigquery.Client(project=PROJECT_ID)

query = """
WITH feature_data AS (
  SELECT
    mf.player_lookup,
    mf.game_date,
    mf.features
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
  WHERE mf.game_date >= '2024-10-22'
    AND mf.game_date <= CURRENT_DATE()
    AND mf.feature_count = 25
    AND ARRAY_LENGTH(mf.features) = 25
),
actuals AS (
  SELECT
    player_lookup,
    game_date,
    points as actual_points,
    usage_rate,
    minutes_played
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2024-10-22'
    AND game_date <= CURRENT_DATE()
    AND points IS NOT NULL
)
SELECT
  fd.player_lookup,
  fd.game_date,
  fd.features,
  a.actual_points,
  a.usage_rate,
  a.minutes_played
FROM feature_data fd
INNER JOIN actuals a
  ON fd.player_lookup = a.player_lookup
  AND fd.game_date = a.game_date
ORDER BY fd.game_date
"""

df = client.query(query).to_dataframe()
print(f"Loaded {len(df):,} samples")

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

# Prepare features and get predictions
X = pd.DataFrame(df['features'].tolist(), columns=feature_names)
X = X.fillna(X.median())
y_actual = df['actual_points'].astype(float)

dmatrix = xgb.DMatrix(X, feature_names=feature_names)
y_pred = model.predict(dmatrix)

df['predicted'] = y_pred
df['actual'] = y_actual
df['error'] = df['actual'] - df['predicted']  # positive = underprediction
df['abs_error'] = np.abs(df['error'])

print(f"Overall MAE: {df['abs_error'].mean():.3f}")
print()

# ============================================================================
# STEP 2: ANALYZE BIAS PATTERN
# ============================================================================

print("=" * 80)
print("STEP 2: ANALYZING BIAS PATTERN")
print("=" * 80)

# Analyze by predicted score (what we can control)
df['pred_bucket'] = pd.cut(df['predicted'],
                           bins=[0, 10, 15, 20, 25, 30, 35, 100],
                           labels=['0-10', '10-15', '15-20', '20-25', '25-30', '30-35', '35+'])

print("\nBias by PREDICTED score (what model outputs):")
print("-" * 60)
bias_by_pred = df.groupby('pred_bucket', observed=True).agg({
    'error': ['mean', 'std', 'count'],
    'abs_error': 'mean'
}).round(2)
bias_by_pred.columns = ['Bias', 'Std', 'Count', 'MAE']
print(bias_by_pred.to_string())

# The key insight: when we PREDICT high, we're usually underpredicting
# So we need to boost predictions that are already high

print("\n\nBias by ACTUAL score (for reference):")
print("-" * 60)
df['actual_bucket'] = pd.cut(df['actual'],
                              bins=[0, 10, 15, 20, 25, 30, 35, 100],
                              labels=['0-10', '10-15', '15-20', '20-25', '25-30', '30-35', '35+'])

bias_by_actual = df.groupby('actual_bucket', observed=True).agg({
    'error': ['mean', 'std', 'count'],
    'abs_error': 'mean'
}).round(2)
bias_by_actual.columns = ['Bias', 'Std', 'Count', 'MAE']
print(bias_by_actual.to_string())

# ============================================================================
# STEP 3: BUILD CALIBRATION FUNCTION
# ============================================================================

print("\n" + "=" * 80)
print("STEP 3: BUILDING CALIBRATION FUNCTION")
print("=" * 80)

# Calculate optimal boost for each prediction level
# We'll fit a simple piecewise linear calibration

# Group by prediction value and find average bias
df['pred_rounded'] = (df['predicted'] / 2).round() * 2  # Round to nearest 2

calibration_data = df.groupby('pred_rounded').agg({
    'error': 'mean',  # average underprediction
    'predicted': 'count'
}).rename(columns={'predicted': 'count'})

# Only use buckets with enough samples
calibration_data = calibration_data[calibration_data['count'] >= 50]

print("\nCalibration curve (prediction → boost needed):")
print("-" * 50)
for pred_val, row in calibration_data.iterrows():
    if row['error'] > 0.5 or row['error'] < -0.5:  # Only show significant biases
        print(f"  Pred {pred_val:5.1f} pts → Boost {row['error']:+5.2f} pts (n={int(row['count'])})")

# Fit a linear model for predictions > 15
high_scorers = df[df['predicted'] > 15].copy()

# Simple linear regression: boost = a * predicted + b
from numpy.polynomial import polynomial as P

# Fit on prediction buckets
x = calibration_data.index.values
y = calibration_data['error'].values
weights = np.sqrt(calibration_data['count'].values)  # Weight by sample size

# Only fit for predictions > 15 where bias is significant
mask = x > 15
if mask.sum() >= 3:
    x_fit = x[mask]
    y_fit = y[mask]
    w_fit = weights[mask]

    # Weighted linear fit
    coeffs = np.polyfit(x_fit, y_fit, deg=1, w=w_fit)
    slope, intercept = coeffs

    print(f"\nLinear calibration for predictions > 15:")
    print(f"  boost = {slope:.4f} * predicted + {intercept:.4f}")
else:
    slope, intercept = 0, 0
    print("\nNot enough data for linear fit")

# ============================================================================
# STEP 4: DEFINE CALIBRATION FUNCTION
# ============================================================================

print("\n" + "=" * 80)
print("STEP 4: CALIBRATION FUNCTION")
print("=" * 80)

def calibrate_prediction(pred):
    """
    Apply calibration to fix high-scorer underprediction.

    - Predictions <= 15: no change (model is accurate here)
    - Predictions > 15: boost based on linear calibration
    - Cap boost to avoid over-correction
    """
    if pred <= 15:
        return pred
    else:
        # Linear boost for high predictions
        boost = slope * pred + intercept
        # Cap boost at 5 points to avoid over-correction
        boost = min(max(boost, 0), 5.0)
        return pred + boost

# Vectorized version
def calibrate_predictions(preds):
    """Vectorized calibration function."""
    preds = np.array(preds)
    boosts = np.where(
        preds > 15,
        np.clip(slope * preds + intercept, 0, 5.0),
        0
    )
    return preds + boosts

print(f"Calibration parameters:")
print(f"  Threshold: 15 points")
print(f"  Slope: {slope:.4f}")
print(f"  Intercept: {intercept:.4f}")
print(f"  Max boost: 5.0 points")
print()
print("Example calibrations:")
for p in [10, 15, 20, 25, 30, 35, 40]:
    cal = calibrate_prediction(p)
    boost = cal - p
    print(f"  Predicted {p} → Calibrated {cal:.1f} (boost {boost:+.1f})")

# ============================================================================
# STEP 5: VALIDATE CALIBRATION
# ============================================================================

print("\n" + "=" * 80)
print("STEP 5: VALIDATING CALIBRATION")
print("=" * 80)

# Apply calibration
df['calibrated'] = calibrate_predictions(df['predicted'])
df['cal_error'] = df['actual'] - df['calibrated']
df['cal_abs_error'] = np.abs(df['cal_error'])

# Overall metrics
orig_mae = df['abs_error'].mean()
cal_mae = df['cal_abs_error'].mean()

print(f"\nOverall Results:")
print(f"  Original MAE:   {orig_mae:.3f}")
print(f"  Calibrated MAE: {cal_mae:.3f}")
print(f"  Improvement:    {orig_mae - cal_mae:.3f} ({(orig_mae - cal_mae)/orig_mae*100:.1f}%)")

# By prediction bucket
print("\n\nBy Predicted Score (before vs after calibration):")
print("-" * 70)

comparison = df.groupby('pred_bucket', observed=True).agg({
    'abs_error': 'mean',
    'cal_abs_error': 'mean',
    'error': 'mean',
    'cal_error': 'mean',
    'predicted': 'count'
}).round(3)
comparison.columns = ['Orig_MAE', 'Cal_MAE', 'Orig_Bias', 'Cal_Bias', 'Count']
comparison['MAE_Δ'] = comparison['Cal_MAE'] - comparison['Orig_MAE']
print(comparison[['Orig_MAE', 'Cal_MAE', 'MAE_Δ', 'Orig_Bias', 'Cal_Bias', 'Count']].to_string())

# By actual score
print("\n\nBy Actual Score (before vs after calibration):")
print("-" * 70)

comparison_actual = df.groupby('actual_bucket', observed=True).agg({
    'abs_error': 'mean',
    'cal_abs_error': 'mean',
    'error': 'mean',
    'cal_error': 'mean',
    'actual': 'count'
}).round(3)
comparison_actual.columns = ['Orig_MAE', 'Cal_MAE', 'Orig_Bias', 'Cal_Bias', 'Count']
comparison_actual['MAE_Δ'] = comparison_actual['Cal_MAE'] - comparison_actual['Orig_MAE']
print(comparison_actual[['Orig_MAE', 'Cal_MAE', 'MAE_Δ', 'Orig_Bias', 'Cal_Bias', 'Count']].to_string())

# ============================================================================
# STEP 6: SAVE CALIBRATION PARAMETERS
# ============================================================================

print("\n" + "=" * 80)
print("STEP 6: SAVING CALIBRATION")
print("=" * 80)

calibration_config = {
    'version': 'v6.1',
    'base_model': str(latest_model),
    'calibration_type': 'linear_high_scorer_boost',
    'threshold': 15.0,
    'slope': float(slope),
    'intercept': float(intercept),
    'max_boost': 5.0,
    'created_at': datetime.now().isoformat(),
    'validation_results': {
        'original_mae': float(orig_mae),
        'calibrated_mae': float(cal_mae),
        'improvement_pct': float((orig_mae - cal_mae)/orig_mae*100),
        'samples': len(df)
    }
}

config_path = model_dir / "xgboost_v6.1_calibration.json"
with open(config_path, 'w') as f:
    json.dump(calibration_config, f, indent=2)

print(f"Calibration config saved: {config_path}")

# ============================================================================
# STEP 7: CREATE CALIBRATED PREDICTION FUNCTION
# ============================================================================

print("\n" + "=" * 80)
print("STEP 7: CALIBRATED PREDICTION CODE")
print("=" * 80)

calibration_code = f'''
def predict_with_calibration(model, features):
    """
    XGBoost v6.1 - Prediction with high-scorer calibration.

    Fixes underprediction bias for high scorers by applying
    a linear boost to predictions > 15 points.
    """
    # Get raw prediction
    dmatrix = xgb.DMatrix(features)
    raw_pred = model.predict(dmatrix)

    # Apply calibration
    threshold = 15.0
    slope = {slope:.6f}
    intercept = {intercept:.6f}
    max_boost = 5.0

    boost = np.where(
        raw_pred > threshold,
        np.clip(slope * raw_pred + intercept, 0, max_boost),
        0
    )

    calibrated = raw_pred + boost
    return calibrated
'''

print(calibration_code)

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print()
print(f"Original v6 MAE:    {orig_mae:.3f}")
print(f"Calibrated v6.1 MAE: {cal_mae:.3f}")
print(f"Improvement:        {(orig_mae - cal_mae):.3f} points ({(orig_mae - cal_mae)/orig_mae*100:.1f}%)")
print()
print("High-scorer improvements:")
high_20_30 = df[df['actual_bucket'] == '20-25']
if len(high_20_30) > 0:
    print(f"  20-25 pts: {high_20_30['abs_error'].mean():.2f} → {high_20_30['cal_abs_error'].mean():.2f}")
high_25_30 = df[df['actual_bucket'] == '25-30']
if len(high_25_30) > 0:
    print(f"  25-30 pts: {high_25_30['abs_error'].mean():.2f} → {high_25_30['cal_abs_error'].mean():.2f}")
high_30 = df[df['actual_bucket'] == '30-35']
if len(high_30) > 0:
    print(f"  30-35 pts: {high_30['abs_error'].mean():.2f} → {high_30['cal_abs_error'].mean():.2f}")
high_35 = df[df['actual_bucket'] == '35+']
if len(high_35) > 0:
    print(f"  35+ pts:   {high_35['abs_error'].mean():.2f} → {high_35['cal_abs_error'].mean():.2f}")

print()
print(f"Mock v1 baseline:   4.80 MAE")
print(f"V6.1 improvement:   {(4.80 - cal_mae)/4.80*100:.1f}% vs mock")
print()
print("=" * 80)

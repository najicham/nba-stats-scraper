#!/usr/bin/env python3
"""
Fix High-Scorer Underprediction Bias - Approach 2

The issue: When actual score is 30+, we underpredict by ~12 points
But by PREDICTED score, bias is small/negative

Root cause: Model predicts toward the mean. When player has a big game,
model predicts ~20-25 but actual is 30-40.

Approach 2: Multiplicative scaling based on prediction level
- Higher predictions get scaled up more
- Uses player's scoring volatility (std) as a guide
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
import json

PROJECT_ID = "nba-props-platform"

print("=" * 80)
print(" FIXING HIGH-SCORER BIAS - APPROACH 2: VOLATILITY-BASED SCALING")
print("=" * 80)
print()

# ============================================================================
# STEP 1: LOAD DATA
# ============================================================================

print("STEP 1: Loading model and data...")

model_dir = Path("models")
v6_models = [f for f in model_dir.glob("xgboost_v6_*.json") if "metadata" not in f.name]
latest_model = sorted(v6_models)[-1]

model = xgb.Booster()
model.load_model(str(latest_model))

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
    points as actual_points
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2024-10-22'
    AND game_date <= CURRENT_DATE()
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

df = client.query(query).to_dataframe()
print(f"Loaded {len(df):,} samples")

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
y_actual = df['actual_points'].astype(float)

# Get raw predictions
dmatrix = xgb.DMatrix(X, feature_names=feature_names)
y_pred = model.predict(dmatrix)

# Also get the player's scoring std (index 3)
player_std = X['points_std_last_10'].values
player_avg_5 = X['points_avg_last_5'].values

df['predicted'] = y_pred
df['actual'] = y_actual
df['std'] = player_std
df['avg_5'] = player_avg_5
df['error'] = df['actual'] - df['predicted']
df['abs_error'] = np.abs(df['error'])

print(f"Original MAE: {df['abs_error'].mean():.3f}")
print()

# ============================================================================
# STEP 2: ANALYZE BY STD AND PREDICTION
# ============================================================================

print("=" * 80)
print("STEP 2: ANALYZING UNDERPREDICTION PATTERN")
print("=" * 80)

# When do we severely underpredict?
df['actual_bucket'] = pd.cut(df['actual'],
                              bins=[0, 15, 25, 35, 100],
                              labels=['0-15', '15-25', '25-35', '35+'])

print("\nUnderprediction by actual score and player volatility:")
print("-" * 60)

df['std_bucket'] = pd.cut(df['std'],
                           bins=[0, 4, 6, 8, 100],
                           labels=['Low (0-4)', 'Med (4-6)', 'High (6-8)', 'Very High (8+)'])

cross = df.groupby(['actual_bucket', 'std_bucket'], observed=True).agg({
    'error': 'mean',
    'predicted': 'count'
}).round(2)
cross.columns = ['Bias', 'Count']
print(cross.to_string())

# ============================================================================
# STEP 3: TRY MULTIPLE CALIBRATION APPROACHES
# ============================================================================

print("\n" + "=" * 80)
print("STEP 3: TESTING CALIBRATION APPROACHES")
print("=" * 80)

approaches = {}

# Approach A: Simple multiplicative scaling for high predictions
def calibrate_a(pred, std):
    """Scale up high predictions slightly."""
    if pred > 20:
        scale = 1.0 + 0.02 * (pred - 20) / 10  # 2% boost per 10 points above 20
        return pred * scale
    return pred

# Approach B: Volatility-weighted boost
def calibrate_b(pred, std):
    """Boost high predictions more for volatile players."""
    if pred > 18:
        vol_factor = min(std / 6.0, 1.5)  # Normalize std, cap at 1.5
        boost = (pred - 18) * 0.05 * vol_factor  # 5% of excess * volatility
        return pred + boost
    return pred

# Approach C: Prediction-based percentage boost
def calibrate_c(pred, std):
    """Simple percentage boost for high predictions."""
    if pred > 22:
        return pred * 1.03  # 3% boost
    elif pred > 18:
        return pred * 1.015  # 1.5% boost
    return pred

# Approach D: Quantile-inspired boost based on std
def calibrate_d(pred, std):
    """Add fraction of std to high predictions."""
    if pred > 20:
        # Add 20% of player's std to prediction
        return pred + 0.20 * std
    elif pred > 15:
        return pred + 0.10 * std
    return pred

# Approach E: Aggressive boost for 25+ predictions
def calibrate_e(pred, std):
    """Aggressive boost for very high predictions."""
    if pred > 30:
        return pred + 2.0  # Flat +2 for 30+ predictions
    elif pred > 25:
        return pred + 1.0  # Flat +1 for 25-30
    elif pred > 20:
        return pred + 0.5  # Flat +0.5 for 20-25
    return pred

approaches = {
    'A: Simple multiplicative': calibrate_a,
    'B: Volatility-weighted': calibrate_b,
    'C: Percentage boost': calibrate_c,
    'D: Std-based boost': calibrate_d,
    'E: Aggressive flat boost': calibrate_e
}

print("\nTesting calibration approaches:")
print("-" * 70)

results = []
for name, func in approaches.items():
    cal_preds = [func(p, s) for p, s in zip(df['predicted'], df['std'])]
    cal_mae = mean_absolute_error(df['actual'], cal_preds)
    improvement = (df['abs_error'].mean() - cal_mae) / df['abs_error'].mean() * 100

    # High-scorer specific MAE
    high_mask = df['actual'] >= 25
    if high_mask.sum() > 0:
        high_orig = df.loc[high_mask, 'abs_error'].mean()
        high_cal = mean_absolute_error(df.loc[high_mask, 'actual'],
                                       np.array(cal_preds)[high_mask])
        high_imp = high_orig - high_cal
    else:
        high_imp = 0

    results.append({
        'approach': name,
        'overall_mae': cal_mae,
        'improvement_pct': improvement,
        'high_scorer_improvement': high_imp
    })

    print(f"{name:30s} MAE: {cal_mae:.3f} ({improvement:+.2f}%), High-scorer: {high_imp:+.2f}")

# Find best approach
results_df = pd.DataFrame(results)
best_idx = results_df['overall_mae'].idxmin()
best = results_df.iloc[best_idx]

print(f"\nBest approach: {best['approach']}")
print(f"  Overall MAE: {best['overall_mae']:.3f}")
print(f"  Improvement: {best['improvement_pct']:.2f}%")

# ============================================================================
# STEP 4: DETAILED ANALYSIS OF BEST APPROACH
# ============================================================================

print("\n" + "=" * 80)
print("STEP 4: DETAILED ANALYSIS OF BEST APPROACH")
print("=" * 80)

best_func = approaches[best['approach']]
df['calibrated'] = [best_func(p, s) for p, s in zip(df['predicted'], df['std'])]
df['cal_error'] = np.abs(df['actual'] - df['calibrated'])

print(f"\nBy Actual Score (before vs after {best['approach']}):")
print("-" * 70)

comparison = df.groupby('actual_bucket', observed=True).agg({
    'abs_error': 'mean',
    'cal_error': 'mean',
    'actual': 'count'
}).round(3)
comparison.columns = ['Orig_MAE', 'Cal_MAE', 'Count']
comparison['Improvement'] = comparison['Orig_MAE'] - comparison['Cal_MAE']
print(comparison.to_string())

# ============================================================================
# STEP 5: CHECK IF WORSE FOR LOW SCORERS
# ============================================================================

print("\n" + "=" * 80)
print("STEP 5: CHECKING IMPACT ON LOW SCORERS")
print("=" * 80)

low_mask = df['actual'] < 15
low_orig = df.loc[low_mask, 'abs_error'].mean()
low_cal = df.loc[low_mask, 'cal_error'].mean()

print(f"Low scorers (0-15 pts):")
print(f"  Original MAE: {low_orig:.3f}")
print(f"  Calibrated MAE: {low_cal:.3f}")
print(f"  Change: {low_cal - low_orig:+.3f}")

if low_cal > low_orig + 0.05:
    print("  ⚠️  WARNING: Calibration hurts low scorers!")
else:
    print("  ✅ Low scorers not significantly affected")

# ============================================================================
# STEP 6: FINAL RECOMMENDATION
# ============================================================================

print("\n" + "=" * 80)
print("STEP 6: FINAL RECOMMENDATION")
print("=" * 80)

orig_mae = df['abs_error'].mean()
cal_mae = df['cal_error'].mean()
improvement = orig_mae - cal_mae

print(f"\nOriginal v6 MAE:     {orig_mae:.3f}")
print(f"Calibrated MAE:      {cal_mae:.3f}")
print(f"Improvement:         {improvement:.3f} points ({improvement/orig_mae*100:.1f}%)")
print()

# Compare to mock
mock_mae = 4.80
print(f"Mock v1 baseline:    {mock_mae:.2f}")
print(f"v6 improvement:      {(mock_mae - orig_mae)/mock_mae*100:.1f}%")
print(f"v6.1 improvement:    {(mock_mae - cal_mae)/mock_mae*100:.1f}%")
print()

if improvement > 0.01:
    print("✅ RECOMMENDATION: Apply calibration (v6.1)")

    # Save calibration
    calibration = {
        'version': 'v6.1',
        'approach': best['approach'],
        'original_mae': float(orig_mae),
        'calibrated_mae': float(cal_mae),
        'improvement': float(improvement),
        'created_at': datetime.now().isoformat()
    }

    with open(model_dir / 'xgboost_v6.1_calibration.json', 'w') as f:
        json.dump(calibration, f, indent=2)

    print(f"\nCalibration saved to: models/xgboost_v6.1_calibration.json")
else:
    print("❌ RECOMMENDATION: Calibration provides minimal benefit")
    print("   The model's bias is inherent to regression toward the mean")
    print("   Consider: ensemble with mock, or accept current performance")

print()
print("=" * 80)

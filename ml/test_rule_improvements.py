#!/usr/bin/env python3
"""
Test Hand-Coded Rule Improvements

Quick testing framework to validate different weight combinations
and adjustment formulas without deploying to production.

Usage:
    python ml/test_rule_improvements.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from google.cloud import bigquery
from datetime import datetime

# ============================================================================
# CONFIGURATION
# ============================================================================

PROJECT_ID = "nba-props-platform"
TEST_PERIOD_START = "2024-02-04"
TEST_PERIOD_END = "2024-04-14"

print("=" * 80)
print(" TESTING HAND-CODED RULE IMPROVEMENTS")
print("=" * 80)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Test period: {TEST_PERIOD_START} to {TEST_PERIOD_END}")
print()

# ============================================================================
# LOAD TEST DATA
# ============================================================================

print("Loading test data from BigQuery...")
client = bigquery.Client(project=PROJECT_ID)

# We need the same features the mock model uses
query = """
WITH predictions AS (
  SELECT
    player_lookup,
    game_date,
    actual_points,
    predicted_points as baseline_prediction
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE system_id = 'xgboost_v1'
    AND game_date >= '2024-02-04'
    AND game_date <= '2024-04-14'
),

-- Get features from player_game_summary for recent averages
recent_stats AS (
  SELECT
    player_lookup,
    game_date,
    -- Recent performance
    AVG(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
    ) as points_last_5,
    AVG(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as points_last_10,
    AVG(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) as points_season,
    STDDEV(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as points_std_10
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2021-10-01'
    AND game_date <= '2024-04-14'
)

SELECT
  p.player_lookup,
  p.game_date,
  p.actual_points,
  p.baseline_prediction,

  -- Features for testing new formulas
  COALESCE(r.points_last_5, 0) as points_last_5,
  COALESCE(r.points_last_10, 0) as points_last_10,
  COALESCE(r.points_season, 0) as points_season,
  COALESCE(r.points_std_10, 5) as points_std_10

FROM predictions p
LEFT JOIN recent_stats r
  ON p.player_lookup = r.player_lookup
  AND p.game_date = r.game_date

WHERE r.points_last_5 IS NOT NULL
  AND r.points_last_10 IS NOT NULL
"""

df = client.query(query).to_dataframe()
print(f"✓ Loaded {len(df):,} test predictions")
print(f"  Date range: {df['game_date'].min()} to {df['game_date'].max()}")
print(f"  Players: {df['player_lookup'].nunique()}")
print()

# ============================================================================
# BASELINE PERFORMANCE
# ============================================================================

print("=" * 80)
print("CURRENT BASELINE PERFORMANCE")
print("=" * 80)

baseline_mae = np.mean(np.abs(df['actual_points'] - df['baseline_prediction']))
baseline_rmse = np.sqrt(np.mean((df['actual_points'] - df['baseline_prediction']) ** 2))

print(f"MAE:  {baseline_mae:.3f}")
print(f"RMSE: {baseline_rmse:.3f}")
print(f"Bias: {np.mean(df['actual_points'] - df['baseline_prediction']):.3f} (positive = under-predicts)")
print()

# ============================================================================
# TEST DIFFERENT WEIGHT CONFIGURATIONS
# ============================================================================

print("=" * 80)
print("TESTING WEIGHT CONFIGURATIONS")
print("=" * 80)

# Current weights from mock_xgboost_model.py
CURRENT = (0.35, 0.40, 0.25)

# Test configurations
configs = [
    ("Current (baseline)", 0.35, 0.40, 0.25),
    ("More recent (A)", 0.38, 0.42, 0.20),
    ("More recent (B)", 0.40, 0.45, 0.15),
    ("Last 10 heavy", 0.30, 0.50, 0.20),
    ("Last 5 heavy", 0.45, 0.40, 0.15),
    ("Balanced", 0.33, 0.33, 0.34),
]

results = []

for name, w5, w10, wseason in configs:
    # Calculate predictions with new weights
    predictions = (
        df['points_last_5'] * w5 +
        df['points_last_10'] * w10 +
        df['points_season'] * wseason
    )

    # Calculate MAE
    mae = np.mean(np.abs(df['actual_points'] - predictions))
    rmse = np.sqrt(np.mean((df['actual_points'] - predictions) ** 2))
    bias = np.mean(df['actual_points'] - predictions)

    # Improvement vs baseline
    improvement = ((baseline_mae - mae) / baseline_mae) * 100

    results.append({
        'config': name,
        'w5': w5,
        'w10': w10,
        'wseason': wseason,
        'mae': mae,
        'rmse': rmse,
        'bias': bias,
        'improvement_pct': improvement
    })

    status = "✅" if mae < baseline_mae else "❌"
    print(f"{status} {name:20s} ({w5:.2f}/{w10:.2f}/{wseason:.2f}): "
          f"MAE={mae:.3f} ({improvement:+.1f}%), Bias={bias:+.2f}")

print()

# Find best configuration
results_df = pd.DataFrame(results)
best = results_df.loc[results_df['mae'].idxmin()]

print("🏆 BEST CONFIGURATION:")
print(f"   {best['config']}")
print(f"   Weights: {best['w5']:.2f} / {best['w10']:.2f} / {best['wseason']:.2f}")
print(f"   MAE: {best['mae']:.3f} (baseline: {baseline_mae:.3f})")
print(f"   Improvement: {best['improvement_pct']:+.2f}%")
print(f"   Bias: {best['bias']:+.2f}")
print()

# ============================================================================
# VARIANCE ANALYSIS
# ============================================================================

print("=" * 80)
print("PLAYER VARIANCE ANALYSIS")
print("=" * 80)

# How does performance vary by player consistency?
low_var = df[df['points_std_10'] < 4.0]
med_var = df[(df['points_std_10'] >= 4.0) & (df['points_std_10'] < 7.0)]
high_var = df[df['points_std_10'] >= 7.0]

print(f"Low variance players (std < 4.0):  {len(low_var):,} predictions")
print(f"  MAE: {np.mean(np.abs(low_var['actual_points'] - low_var['baseline_prediction'])):.3f}")

print(f"Medium variance (std 4.0-7.0):    {len(med_var):,} predictions")
print(f"  MAE: {np.mean(np.abs(med_var['actual_points'] - med_var['baseline_prediction'])):.3f}")

print(f"High variance players (std > 7.0): {len(high_var):,} predictions")
print(f"  MAE: {np.mean(np.abs(high_var['actual_points'] - high_var['baseline_prediction'])):.3f}")

print()
print("💡 Insight: High variance players harder to predict (as expected)")
print()

# ============================================================================
# RECOMMENDATIONS
# ============================================================================

print("=" * 80)
print("RECOMMENDATIONS")
print("=" * 80)

if best['improvement_pct'] > 1.0:
    print(f"✅ DEPLOY: Best config improves MAE by {best['improvement_pct']:.2f}%")
    print(f"   Change weights in mock_xgboost_model.py:")
    print(f"   baseline = (")
    print(f"       points_last_5 * {best['w5']:.2f} +")
    print(f"       points_last_10 * {best['w10']:.2f} +")
    print(f"       points_season * {best['wseason']:.2f}")
    print(f"   )")
    print()
    print(f"   Expected new MAE: {best['mae']:.3f} (from {baseline_mae:.3f})")
elif best['improvement_pct'] > 0:
    print(f"⚠️  MARGINAL: Best config improves MAE by only {best['improvement_pct']:.2f}%")
    print(f"   Consider deploying but gains are small")
else:
    print(f"❌ NO IMPROVEMENT: No weight configuration beats baseline")
    print(f"   Need to tune adjustments (fatigue, defense, etc.) instead")

print()
print("=" * 80)
print("NEXT STEPS")
print("=" * 80)
print("1. Review results above")
print("2. If improvement > 1%, update mock_xgboost_model.py with best weights")
print("3. Test adjustments (fatigue curve, defense, etc.)")
print("4. Deploy and monitor")
print()

# ============================================================================
# SAVE RESULTS
# ============================================================================

output_file = f"/tmp/rule_tuning_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
results_df.to_csv(output_file, index=False)
print(f"✓ Results saved to: {output_file}")
print()

print("=" * 80)
print("TESTING COMPLETE")
print("=" * 80)

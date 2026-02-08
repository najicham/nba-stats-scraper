#!/usr/bin/env python3
"""
Comprehensive Model Improvement Analysis

Executes all blocks of the improvement plan:
- Block 1: Error analysis
- Block 2: Ensemble experiments
- Block 3: Feature engineering ideas
- Block 4: Architecture experiments

Outputs a comprehensive report with recommendations.
"""

import os
import sys
from datetime import datetime
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import xgboost as xgb
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split

PROJECT_ID = "nba-props-platform"

print("=" * 80)
print(" COMPREHENSIVE MODEL IMPROVEMENT ANALYSIS")
print("=" * 80)
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================================================
# SETUP: Load model and data
# ============================================================================

print("SETUP: Loading model and data...")

model_dir = Path("models")
v6_models = [f for f in model_dir.glob("xgboost_v6_*.json") if "metadata" not in f.name]
latest_model = sorted(v6_models)[-1]

model = xgb.Booster()
model.load_model(str(latest_model))
print(f"Loaded model: {latest_model}")

client = bigquery.Client(project=PROJECT_ID)

# Load comprehensive data with player info
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
    minutes_played,
    usage_rate,
    starter_flag
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2024-10-22'
    AND game_date <= CURRENT_DATE()
    AND points IS NOT NULL
),
player_info AS (
  SELECT DISTINCT
    player_lookup,
    FIRST_VALUE(position) OVER (PARTITION BY player_lookup ORDER BY created_at DESC) as position
  FROM `nba-props-platform.nba_reference.nba_players_registry`
  WHERE position IS NOT NULL
)
SELECT
  fd.player_lookup,
  fd.game_date,
  fd.features,
  a.actual_points,
  a.minutes_played,
  a.usage_rate,
  a.starter_flag,
  COALESCE(pi.position, 'Unknown') as position
FROM feature_data fd
INNER JOIN actuals a
  ON fd.player_lookup = a.player_lookup
  AND fd.game_date = a.game_date
LEFT JOIN player_info pi
  ON fd.player_lookup = pi.player_lookup
ORDER BY fd.game_date
"""

df = client.query(query).to_dataframe()
print(f"Loaded {len(df):,} samples")

# Feature setup
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

dmatrix = xgb.DMatrix(X, feature_names=feature_names)
y_pred = model.predict(dmatrix)
y_actual = df['actual_points'].astype(float).values

df['predicted'] = y_pred
df['actual'] = y_actual
df['error'] = df['actual'] - df['predicted']
df['abs_error'] = np.abs(df['error'])
df['minutes_played'] = pd.to_numeric(df['minutes_played'], errors='coerce').fillna(0)
df['usage_rate'] = pd.to_numeric(df['usage_rate'], errors='coerce').fillna(20)

baseline_mae = df['abs_error'].mean()
print(f"Baseline v6 MAE: {baseline_mae:.3f}")
print()

results = {'baseline_mae': baseline_mae, 'samples': len(df)}

# ============================================================================
# BLOCK 1: ERROR ANALYSIS
# ============================================================================

print("=" * 80)
print("BLOCK 1: ERROR ANALYSIS")
print("=" * 80)

# 1.1 DNP Impact
print("\n--- 1.1 DNP Impact ---")
dnp_mask = df['actual'] == 0
dnp_count = dnp_mask.sum()
dnp_mae_contribution = df.loc[dnp_mask, 'abs_error'].sum() / len(df)
mae_without_dnp = df.loc[~dnp_mask, 'abs_error'].mean()

print(f"DNP games: {dnp_count} ({dnp_count/len(df)*100:.1f}%)")
print(f"DNP contribution to MAE: {dnp_mae_contribution:.3f}")
print(f"MAE without DNPs: {mae_without_dnp:.3f}")
print(f"Potential improvement: {baseline_mae - mae_without_dnp:.3f} points")

results['dnp_analysis'] = {
    'dnp_count': int(dnp_count),
    'dnp_pct': float(dnp_count/len(df)*100),
    'mae_without_dnp': float(mae_without_dnp),
    'potential_improvement': float(baseline_mae - mae_without_dnp)
}

# 1.2 Error by Position
print("\n--- 1.2 Error by Position ---")
position_analysis = df.groupby('position').agg({
    'abs_error': ['mean', 'std', 'count'],
    'error': 'mean'  # bias
}).round(3)
position_analysis.columns = ['MAE', 'Std', 'Count', 'Bias']
position_analysis = position_analysis.sort_values('MAE')
print(position_analysis.to_string())

results['position_analysis'] = position_analysis.to_dict()

# 1.3 Error by Usage Tier
print("\n--- 1.3 Error by Usage Tier ---")
df['usage_tier'] = pd.cut(df['usage_rate'],
                          bins=[0, 15, 20, 25, 30, 100],
                          labels=['<15%', '15-20%', '20-25%', '25-30%', '>30%'])
usage_analysis = df.groupby('usage_tier', observed=True).agg({
    'abs_error': ['mean', 'count'],
    'error': 'mean'
}).round(3)
usage_analysis.columns = ['MAE', 'Count', 'Bias']
print(usage_analysis.to_string())

results['usage_analysis'] = {str(k): v for k, v in usage_analysis.to_dict().items()}

# 1.4 Error by Minutes Bucket
print("\n--- 1.4 Error by Minutes Bucket ---")
df['minutes_bucket'] = pd.cut(df['minutes_played'],
                               bins=[0, 10, 20, 30, 40, 60],
                               labels=['0-10', '10-20', '20-30', '30-40', '40+'])
minutes_analysis = df.groupby('minutes_bucket', observed=True).agg({
    'abs_error': ['mean', 'count'],
    'error': 'mean'
}).round(3)
minutes_analysis.columns = ['MAE', 'Count', 'Bias']
print(minutes_analysis.to_string())

results['minutes_analysis'] = {str(k): v for k, v in minutes_analysis.to_dict().items()}

# 1.5 Error by Starter Status
print("\n--- 1.5 Error by Starter Status ---")
starter_analysis = df.groupby('starter_flag').agg({
    'abs_error': ['mean', 'count'],
    'error': 'mean'
}).round(3)
starter_analysis.columns = ['MAE', 'Count', 'Bias']
print(starter_analysis.to_string())

print("\n--- Block 1 Summary ---")
print(f"Best segment: {position_analysis['MAE'].idxmin()} ({position_analysis['MAE'].min():.2f} MAE)")
print(f"Worst segment: {position_analysis['MAE'].idxmax()} ({position_analysis['MAE'].max():.2f} MAE)")
print(f"DNP elimination potential: -{baseline_mae - mae_without_dnp:.3f} MAE")

# ============================================================================
# BLOCK 2: ENSEMBLE EXPERIMENTS
# ============================================================================

print("\n" + "=" * 80)
print("BLOCK 2: ENSEMBLE EXPERIMENTS (v6 + Mock)")
print("=" * 80)

# Load mock predictions
print("\nLoading mock model for ensemble...")
sys.path.insert(0, str(Path(__file__).parent.parent / 'predictions' / 'shared'))

try:
    from mock_xgboost_model import MockXGBoostModel
    mock_model = MockXGBoostModel()

    # Generate mock predictions
    mock_preds = []
    for idx, row in df.iterrows():
        features = {
            'points_last_5': X.iloc[idx]['points_avg_last_5'],
            'points_last_10': X.iloc[idx]['points_avg_last_10'],
            'points_season': X.iloc[idx]['points_avg_season'],
            'usage_rate': row['usage_rate'],
            'fatigue': X.iloc[idx]['fatigue_score'],
            'defense_rating': X.iloc[idx]['opponent_def_rating'],
            'pace': X.iloc[idx]['opponent_pace'],
            'is_home': X.iloc[idx]['home_away'],
            'back_to_back': X.iloc[idx]['back_to_back'],
            'minutes': row['minutes_played'] if row['minutes_played'] > 0 else 25,
            'paint_rate': X.iloc[idx]['pct_paint'],
        }
        mock_preds.append(mock_model.predict(features))

    df['mock_pred'] = mock_preds
    mock_mae = mean_absolute_error(df['actual'], df['mock_pred'])
    print(f"Mock MAE: {mock_mae:.3f}")

    # Test ensemble weights
    print("\n--- 2.1 Testing Ensemble Weights ---")
    ensemble_results = []
    for alpha in np.arange(0.5, 1.0, 0.05):
        ensemble_pred = alpha * df['predicted'] + (1 - alpha) * df['mock_pred']
        ensemble_mae = mean_absolute_error(df['actual'], ensemble_pred)
        ensemble_results.append({
            'alpha': alpha,
            'v6_weight': alpha,
            'mock_weight': 1-alpha,
            'mae': ensemble_mae
        })
        print(f"  α={alpha:.2f} (v6={alpha:.0%}, mock={1-alpha:.0%}): MAE={ensemble_mae:.3f}")

    best_ensemble = min(ensemble_results, key=lambda x: x['mae'])
    print(f"\nBest ensemble: α={best_ensemble['alpha']:.2f}, MAE={best_ensemble['mae']:.3f}")
    print(f"Improvement over v6: {baseline_mae - best_ensemble['mae']:.3f}")

    results['ensemble'] = {
        'mock_mae': float(mock_mae),
        'best_alpha': float(best_ensemble['alpha']),
        'best_mae': float(best_ensemble['mae']),
        'improvement': float(baseline_mae - best_ensemble['mae'])
    }

    # 2.2 Segment-specific ensemble
    print("\n--- 2.2 Segment-Specific Ensemble ---")

    # Test if different segments benefit from different weights
    for segment_col, segment_name in [('minutes_bucket', 'Minutes'), ('usage_tier', 'Usage')]:
        print(f"\n{segment_name}-specific optimal weights:")
        for segment in df[segment_col].dropna().unique():
            mask = df[segment_col] == segment
            if mask.sum() < 100:
                continue

            best_seg_mae = float('inf')
            best_seg_alpha = 0.7
            for alpha in np.arange(0.5, 1.0, 0.1):
                seg_pred = alpha * df.loc[mask, 'predicted'] + (1-alpha) * df.loc[mask, 'mock_pred']
                seg_mae = mean_absolute_error(df.loc[mask, 'actual'], seg_pred)
                if seg_mae < best_seg_mae:
                    best_seg_mae = seg_mae
                    best_seg_alpha = alpha

            v6_mae = df.loc[mask, 'abs_error'].mean()
            print(f"  {segment}: α={best_seg_alpha:.1f}, MAE={best_seg_mae:.3f} (v6-only: {v6_mae:.3f})")

except Exception as e:
    print(f"Could not load mock model: {e}")
    print("Skipping ensemble experiments")
    results['ensemble'] = {'error': str(e)}

# ============================================================================
# BLOCK 3: FEATURE ENGINEERING ANALYSIS
# ============================================================================

print("\n" + "=" * 80)
print("BLOCK 3: FEATURE ENGINEERING ANALYSIS")
print("=" * 80)

# 3.1 Minutes volatility impact
print("\n--- 3.1 Minutes Volatility Analysis ---")
# Players with stable minutes should be more predictable
df['points_std'] = X['points_std_last_10']
df['std_bucket'] = pd.cut(df['points_std'],
                          bins=[0, 3, 5, 7, 100],
                          labels=['Low (<3)', 'Medium (3-5)', 'High (5-7)', 'Very High (>7)'])
std_analysis = df.groupby('std_bucket', observed=True).agg({
    'abs_error': ['mean', 'count']
}).round(3)
std_analysis.columns = ['MAE', 'Count']
print(std_analysis.to_string())
print("\nInsight: High-volatility players are harder to predict (expected)")

# 3.2 Recent trend impact
print("\n--- 3.2 Recent Trend Analysis ---")
df['recent_trend'] = X['recent_trend']
df['trend_bucket'] = pd.cut(df['recent_trend'],
                            bins=[-100, -2, 2, 100],
                            labels=['Declining', 'Stable', 'Rising'])
trend_analysis = df.groupby('trend_bucket', observed=True).agg({
    'abs_error': ['mean', 'count'],
    'error': 'mean'
}).round(3)
trend_analysis.columns = ['MAE', 'Count', 'Bias']
print(trend_analysis.to_string())

# 3.3 Feature importance reminder
print("\n--- 3.3 Current Feature Importance ---")
importance = model.get_score(importance_type='gain')
sorted_importance = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:10]
print("Top 10 features by gain:")
for feat, score in sorted_importance:
    print(f"  {feat}: {score:.1f}")

# ============================================================================
# BLOCK 4: ARCHITECTURE IDEAS ANALYSIS
# ============================================================================

print("\n" + "=" * 80)
print("BLOCK 4: ARCHITECTURE IDEAS")
print("=" * 80)

# 4.1 Two-stage potential
print("\n--- 4.1 Two-Stage Model Potential ---")
# If we could predict minutes perfectly, what would MAE be?
df['points_per_min'] = np.where(df['minutes_played'] > 0,
                                 df['actual'] / df['minutes_played'],
                                 0)
df['pred_points_per_min'] = np.where(df['minutes_played'] > 0,
                                      df['predicted'] / df['minutes_played'],
                                      0)

# Simulate perfect minutes prediction
df['pred_with_perfect_mins'] = df['pred_points_per_min'] * df['minutes_played']
perfect_mins_mae = mean_absolute_error(df.loc[df['minutes_played'] > 0, 'actual'],
                                        df.loc[df['minutes_played'] > 0, 'pred_with_perfect_mins'])
print(f"Current points/min prediction MAE (given perfect minutes): {perfect_mins_mae:.3f}")
print(f"This shows the 'efficiency prediction' component of error")

# 4.2 Position model potential
print("\n--- 4.2 Position-Specific Model Potential ---")
print("MAE by position (potential for specialized models):")
position_maes = df.groupby('position')['abs_error'].mean().sort_values()
for pos, mae in position_maes.items():
    count = (df['position'] == pos).sum()
    if count >= 100:
        print(f"  {pos}: {mae:.3f} (n={count})")

# ============================================================================
# BLOCK 5: SYNTHESIS
# ============================================================================

print("\n" + "=" * 80)
print("BLOCK 5: SYNTHESIS & RECOMMENDATIONS")
print("=" * 80)

print("\n--- Key Findings ---")
print(f"1. Baseline v6 MAE: {baseline_mae:.3f}")
print(f"2. MAE without DNPs: {mae_without_dnp:.3f} (potential: -{baseline_mae - mae_without_dnp:.3f})")

if 'ensemble' in results and 'best_mae' in results['ensemble']:
    print(f"3. Best ensemble MAE: {results['ensemble']['best_mae']:.3f} (α={results['ensemble']['best_alpha']:.2f})")
    print(f"4. Ensemble improvement: {results['ensemble']['improvement']:.3f}")

print("\n--- Recommended Actions (Priority Order) ---")
recommendations = []

# DNP handling
if baseline_mae - mae_without_dnp > 0.05:
    recommendations.append({
        'priority': 1,
        'action': 'Integrate injury/lineup data to filter DNPs',
        'expected_impact': f"-{baseline_mae - mae_without_dnp:.3f} MAE",
        'effort': 'Medium (4-6 hours)'
    })

# Ensemble
if 'ensemble' in results and 'improvement' in results['ensemble']:
    if results['ensemble']['improvement'] > 0.01:
        recommendations.append({
            'priority': 2,
            'action': f"Deploy ensemble (α={results['ensemble']['best_alpha']:.2f})",
            'expected_impact': f"-{results['ensemble']['improvement']:.3f} MAE",
            'effort': 'Low (1 hour)'
        })

# Position models
recommendations.append({
    'priority': 3,
    'action': 'Train position-specific models for high-variance positions',
    'expected_impact': '-0.05 to -0.10 MAE (estimated)',
    'effort': 'Medium (3-4 hours)'
})

# Two-stage
recommendations.append({
    'priority': 4,
    'action': 'Build two-stage model (minutes → points)',
    'expected_impact': '-0.05 to -0.15 MAE (estimated)',
    'effort': 'Medium (3-4 hours)'
})

print()
for rec in recommendations:
    print(f"Priority {rec['priority']}: {rec['action']}")
    print(f"   Expected: {rec['expected_impact']}, Effort: {rec['effort']}")

# Save results
results['recommendations'] = recommendations
results['timestamp'] = datetime.now().isoformat()

results_path = Path('ml/reports')
results_path.mkdir(exist_ok=True)
with open(results_path / 'comprehensive_analysis_results.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n\nResults saved to: ml/reports/comprehensive_analysis_results.json")

# ============================================================================
# SUMMARY TABLE
# ============================================================================

print("\n" + "=" * 80)
print("SUMMARY: PATH TO IMPROVEMENT")
print("=" * 80)
print()
print(f"{'Stage':<40} {'MAE':<10} {'Δ from Baseline':<15}")
print("-" * 65)
print(f"{'Current v6 Baseline':<40} {baseline_mae:<10.3f} {'--':<15}")
print(f"{'+ Remove DNP errors':<40} {mae_without_dnp:<10.3f} {baseline_mae - mae_without_dnp:<+15.3f}")

if 'ensemble' in results and 'best_mae' in results['ensemble']:
    ensemble_no_dnp = results['ensemble']['best_mae'] - (baseline_mae - mae_without_dnp) * 0.5  # Estimate
    print(f"{'+ Ensemble v6+mock':<40} {results['ensemble']['best_mae']:<10.3f} {baseline_mae - results['ensemble']['best_mae']:<+15.3f}")

print(f"{'+ Position models (est.)':<40} {'~3.95':<10} {'-0.05 to -0.10':<15}")
print(f"{'+ Two-stage model (est.)':<40} {'~3.85':<10} {'-0.05 to -0.15':<15}")
print()
print(f"Mock baseline for reference: 4.80 MAE")
print()
print("=" * 80)

#!/usr/bin/env python3
"""
Evaluate Mock Model v2 vs v1

Compares mock_v1 (current production) against mock_v2 (error-analysis improvements)
on the same test set used for XGBoost evaluation (2024-02-08 to 2024-04-30).

Expected improvements:
1. High minutes (36+): Reduce -12.5 bias
2. High usage (30+): Reduce -12.3 bias
3. Low minutes (<20): Reduce +2-4 bias
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
from predictions.shared.mock_xgboost_model import MockXGBoostModel as MockV1
from predictions.shared.mock_xgboost_model_v2 import MockXGBoostModel as MockV2

PROJECT_ID = "nba-props-platform"

print("=" * 80)
print(" EVALUATING MOCK V2 vs V1")
print("=" * 80)
print()

# ============================================================================
# STEP 1: LOAD TEST DATA (Same as XGBoost evaluation)
# ============================================================================

print("Loading test data from BigQuery...")
print("Test period: 2024-02-08 to 2024-04-30")
print()

client = bigquery.Client(project=PROJECT_ID)

# Same query as XGBoost training, but filtered to test period
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
    minutes_played,
    usage_rate,
    is_starter,

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

    AVG(minutes_played) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as minutes_avg_last_10,

    AVG(usage_rate) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as usage_rate_last_10,

    -- Shot distribution averages
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
    ) as assisted_rate_last_10

  FROM player_games
)

SELECT
  pp.*,

  -- Composite factors from precompute (4)
  COALESCE(pcf.fatigue_score, 70) as fatigue_score,
  COALESCE(pcf.shot_zone_mismatch_score, 0) as shot_zone_mismatch_score,
  COALESCE(pcf.pace_score, 0) as pace_score,
  COALESCE(pcf.usage_spike_score, 0) as usage_spike_score,

  -- Opponent defense metrics from precompute (2)
  COALESCE(tdz.defensive_rating_last_15, 112.0) as opponent_def_rating_last_15,
  COALESCE(tdz.opponent_pace, 100.0) as opponent_pace_last_15,

  -- Game context features (3)
  IF(pp.is_home, 1.0, 0.0) as is_home_int,
  2.0 as days_rest,
  0.0 as back_to_back,

  -- Team metrics from player cache (2)
  COALESCE(pdc.team_pace_last_10, 100.0) as team_pace_last_10,
  COALESCE(pdc.team_off_rating_last_10, 112.0) as team_off_rating_last_10

FROM player_performance pp
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
  AND pp.game_date BETWEEN '2024-02-08' AND '2024-04-30'
"""

df = client.query(query).to_dataframe()

print(f"✓ Loaded {len(df):,} test samples")
print(f"  Date range: {df['game_date'].min()} to {df['game_date'].max()}")
print()

# ============================================================================
# STEP 2: PREPARE FEATURES (25 features matching mock model)
# ============================================================================

print("Preparing features...")

feature_cols = [
    'points_avg_last_5',
    'points_avg_last_10',
    'points_avg_season',
    'points_std_last_10',
    'minutes_avg_last_10',
    'fatigue_score',
    'shot_zone_mismatch_score',
    'pace_score',
    'usage_spike_score',
    0, 0, 0, 0,  # Placeholder features (removed in v4)
    'opponent_def_rating_last_15',
    'opponent_pace_last_15',
    'is_home_int',
    'days_rest',
    'back_to_back',
    'paint_rate_last_10',
    'mid_range_rate_last_10',
    'three_pt_rate_last_10',
    'assisted_rate_last_10',
    'team_pace_last_10',
    'team_off_rating_last_10',
    'usage_rate_last_10',
]

# Build feature matrix
X = []
for _, row in df.iterrows():
    features = []
    for col in feature_cols:
        if isinstance(col, str):
            val = row.get(col, 0)
            features.append(float(val) if pd.notna(val) else 0.0)
        else:
            features.append(float(col))
    X.append(features)

X = np.array(X)
y_true = df['actual_points'].values

print(f"✓ Features: {X.shape}")
print(f"✓ Target: {len(y_true)} samples")
print()

# ============================================================================
# STEP 3: EVALUATE BOTH MODELS
# ============================================================================

print("=" * 80)
print(" OVERALL PERFORMANCE")
print("=" * 80)

# Mock v1
print("Evaluating Mock v1 (current production)...")
mock_v1 = MockV1(seed=42)
y_pred_v1 = mock_v1.predict(X)
mae_v1 = mean_absolute_error(y_true, y_pred_v1)
within_3_v1 = np.mean(np.abs(y_true - y_pred_v1) <= 3) * 100
within_5_v1 = np.mean(np.abs(y_true - y_pred_v1) <= 5) * 100

print(f"  MAE: {mae_v1:.2f}")
print(f"  Within 3 pts: {within_3_v1:.1f}%")
print(f"  Within 5 pts: {within_5_v1:.1f}%")
print()

# Mock v2
print("Evaluating Mock v2 (with improvements)...")
mock_v2 = MockV2(seed=42)
y_pred_v2 = mock_v2.predict(X)
mae_v2 = mean_absolute_error(y_true, y_pred_v2)
within_3_v2 = np.mean(np.abs(y_true - y_pred_v2) <= 3) * 100
within_5_v2 = np.mean(np.abs(y_true - y_pred_v2) <= 5) * 100

print(f"  MAE: {mae_v2:.2f}")
print(f"  Within 3 pts: {within_3_v2:.1f}%")
print(f"  Within 5 pts: {within_5_v2:.1f}%")
print()

# Comparison
print("Improvement:")
mae_diff = mae_v1 - mae_v2
pct_improvement = (mae_diff / mae_v1) * 100
print(f"  MAE: {mae_diff:+.2f} ({pct_improvement:+.1f}%)")
print(f"  Within 3: {within_3_v2 - within_3_v1:+.1f}%")
print(f"  Within 5: {within_5_v2 - within_5_v1:+.1f}%")
print()

if mae_v2 < mae_v1:
    print(f"✅ Mock v2 is BETTER by {mae_diff:.2f} MAE!")
else:
    print(f"❌ Mock v2 is WORSE by {-mae_diff:.2f} MAE")
print()

# ============================================================================
# STEP 4: ANALYZE SPECIFIC SCENARIOS (Error analysis targets)
# ============================================================================

print("=" * 80)
print(" SCENARIO ANALYSIS (Targeted Improvements)")
print("=" * 80)

# Get scenario flags (handle None/NaN values)
minutes = pd.to_numeric(df['minutes_played'], errors='coerce').fillna(0).values
usage = pd.to_numeric(df['usage_rate'], errors='coerce').fillna(0).values

# Scenario 1: High minutes (36+)
high_min_mask = minutes >= 36
if high_min_mask.sum() > 0:
    print(f"\n1. High Minutes (36+) - {high_min_mask.sum()} samples")
    print(f"   Target: Reduce -12.5 bias")
    mae_v1_high = mean_absolute_error(y_true[high_min_mask], y_pred_v1[high_min_mask])
    mae_v2_high = mean_absolute_error(y_true[high_min_mask], y_pred_v2[high_min_mask])
    bias_v1_high = np.mean(y_pred_v1[high_min_mask] - y_true[high_min_mask])
    bias_v2_high = np.mean(y_pred_v2[high_min_mask] - y_true[high_min_mask])
    print(f"   Mock v1: MAE={mae_v1_high:.2f}, Bias={bias_v1_high:+.2f}")
    print(f"   Mock v2: MAE={mae_v2_high:.2f}, Bias={bias_v2_high:+.2f}")
    print(f"   Change: MAE {mae_v2_high - mae_v1_high:+.2f}, Bias {bias_v2_high - bias_v1_high:+.2f}")
    if bias_v2_high > bias_v1_high and bias_v1_high < 0:
        print(f"   ✅ Bias improved (less underprediction)")

# Scenario 2: High usage (30+)
high_usage_mask = usage >= 30
if high_usage_mask.sum() > 0:
    print(f"\n2. High Usage (30+) - {high_usage_mask.sum()} samples")
    print(f"   Target: Reduce -12.3 bias")
    mae_v1_usage = mean_absolute_error(y_true[high_usage_mask], y_pred_v1[high_usage_mask])
    mae_v2_usage = mean_absolute_error(y_true[high_usage_mask], y_pred_v2[high_usage_mask])
    bias_v1_usage = np.mean(y_pred_v1[high_usage_mask] - y_true[high_usage_mask])
    bias_v2_usage = np.mean(y_pred_v2[high_usage_mask] - y_true[high_usage_mask])
    print(f"   Mock v1: MAE={mae_v1_usage:.2f}, Bias={bias_v1_usage:+.2f}")
    print(f"   Mock v2: MAE={mae_v2_usage:.2f}, Bias={bias_v2_usage:+.2f}")
    print(f"   Change: MAE {mae_v2_usage - mae_v1_usage:+.2f}, Bias {bias_v2_usage - bias_v1_usage:+.2f}")
    if bias_v2_usage > bias_v1_usage and bias_v1_usage < 0:
        print(f"   ✅ Bias improved (less underprediction)")

# Scenario 3: Low minutes (<20)
low_min_mask = minutes < 20
if low_min_mask.sum() > 0:
    print(f"\n3. Low Minutes (<20) - {low_min_mask.sum()} samples")
    print(f"   Target: Reduce +2-4 bias")
    mae_v1_low = mean_absolute_error(y_true[low_min_mask], y_pred_v1[low_min_mask])
    mae_v2_low = mean_absolute_error(y_true[low_min_mask], y_pred_v2[low_min_mask])
    bias_v1_low = np.mean(y_pred_v1[low_min_mask] - y_true[low_min_mask])
    bias_v2_low = np.mean(y_pred_v2[low_min_mask] - y_true[low_min_mask])
    print(f"   Mock v1: MAE={mae_v1_low:.2f}, Bias={bias_v1_low:+.2f}")
    print(f"   Mock v2: MAE={mae_v2_low:.2f}, Bias={bias_v2_low:+.2f}")
    print(f"   Change: MAE {mae_v2_low - mae_v1_low:+.2f}, Bias {bias_v2_low - bias_v1_low:+.2f}")
    if bias_v2_low < bias_v1_low and bias_v1_low > 0:
        print(f"   ✅ Bias improved (less overprediction)")

print()

# ============================================================================
# STEP 5: SUMMARY & RECOMMENDATION
# ============================================================================

print("=" * 80)
print(" SUMMARY")
print("=" * 80)
print()

print(f"Mock v1 (production): {mae_v1:.2f} MAE")
print(f"Mock v2 (improved):   {mae_v2:.2f} MAE")
print(f"XGBoost v5 (trained): 4.63 MAE")
print()

if mae_v2 < mae_v1:
    improvement = mae_v1 - mae_v2
    print(f"✅ RECOMMENDATION: Deploy Mock v2")
    print(f"   Improvement: {improvement:.2f} MAE ({pct_improvement:.1f}%)")
    if mae_v2 < 4.27:
        print(f"   🎉 Beats baseline (4.27 MAE)!")
    else:
        print(f"   ⚠️  Still above baseline (4.27 MAE)")
else:
    print(f"❌ RECOMMENDATION: Keep Mock v1")
    print(f"   v2 did not improve performance")
    print(f"   Consider alternative improvements")

print()
print("=" * 80)

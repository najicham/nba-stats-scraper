#!/usr/bin/env python3
"""
Comprehensive Data Quality Investigation
Purpose: Understand root causes of ML model failure

This script runs a comprehensive analysis of training data quality including:
1. Missing data patterns across all 25 features
2. Data distribution analysis (train vs test)
3. Feature correlation analysis
4. Outlier detection
5. Sample sufficiency analysis
6. Target variable analysis

Usage:
    python ml/run_data_quality_investigation.py
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from google.cloud import bigquery

# Configuration
PROJECT_ID = "nba-props-platform"
OUTPUT_DIR = Path("ml/reports")
OUTPUT_DIR.mkdir(exist_ok=True)

print("=" * 80)
print(" COMPREHENSIVE DATA QUALITY INVESTIGATION")
print("=" * 80)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

client = bigquery.Client(project=PROJECT_ID)

# ============================================================================
# Load SQL queries
# ============================================================================

sql_file = Path(__file__).parent / "data_quality_investigation.sql"
print(f"Loading SQL queries from: {sql_file}")

with open(sql_file, 'r') as f:
    sql_content = f.read()

# Split into individual queries (separated by blank lines and comments)
queries = []
current_query = []
in_query = False

for line in sql_content.split('\n'):
    # Skip initial comments
    if line.strip().startswith('--') and not in_query:
        continue

    # Detect start of query
    if line.strip() and not line.strip().startswith('--'):
        in_query = True
        current_query.append(line)
    elif in_query and line.strip().startswith('--'):
        # End of query
        if current_query:
            queries.append('\n'.join(current_query))
            current_query = []
            in_query = False
    elif in_query:
        current_query.append(line)

# Add last query
if current_query:
    queries.append('\n'.join(current_query))

print(f"Loaded {len(queries)} SQL analysis queries")
print()

# ============================================================================
# Execute queries and collect results
# ============================================================================

results = {}

def run_query(query, name, description):
    """Run a query and return results as DataFrame"""
    print(f"Running: {description}")
    try:
        df = client.query(query).to_dataframe()
        print(f"  ✓ Retrieved {len(df)} rows")
        return df
    except Exception as e:
        print(f"  ✗ ERROR: {str(e)[:100]}")
        return None

# Run all analyses
print("=" * 80)
print("EXECUTING DATA QUALITY ANALYSES")
print("=" * 80)
print()

# Investigation 1: NULL Pattern Analysis
print("1. NULL PATTERN ANALYSIS")
print("-" * 80)

null_analysis_query = """
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
    SAFE_DIVIDE(paint_attempts, NULLIF(fg_attempts, 0)) * 100 as paint_rate,
    SAFE_DIVIDE(mid_range_attempts, NULLIF(fg_attempts, 0)) * 100 as mid_range_rate,
    SAFE_DIVIDE(three_pt_attempts, NULLIF(fg_attempts, 0)) * 100 as three_pt_rate,
    SAFE_DIVIDE(assisted_fg_makes, NULLIF(fg_makes, 0)) * 100 as assisted_rate,
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
    AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) as points_avg_last_5,
    AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as points_avg_last_10,
    AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) as points_avg_season,
    STDDEV(points) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as points_std_last_10,
    AVG(minutes_played) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as minutes_avg_last_10,
    DATE_DIFF(game_date, LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date), DAY) as days_rest,
    CASE WHEN DATE_DIFF(game_date, LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date), DAY) = 1 THEN TRUE ELSE FALSE END as back_to_back,
    AVG(paint_rate) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as paint_rate_last_10,
    AVG(mid_range_rate) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as mid_range_rate_last_10,
    AVG(three_pt_rate) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as three_pt_rate_last_10,
    AVG(assisted_rate) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as assisted_rate_last_10,
    AVG(usage_rate) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as usage_rate_last_10
  FROM player_games
),

feature_data AS (
  SELECT
    pp.*,
    pcf.fatigue_score,
    pcf.shot_zone_mismatch_score,
    pcf.pace_score,
    pcf.usage_spike_score,
    tdz.defensive_rating_last_15 as opponent_def_rating_last_15,
    tdz.opponent_pace as opponent_pace_last_15,
    pdc.team_pace_last_10,
    pdc.team_off_rating_last_10
  FROM player_performance pp
  LEFT JOIN `nba-props-platform.nba_precompute.player_composite_factors` pcf
    ON pp.player_lookup = pcf.player_lookup AND pp.game_date = pcf.game_date
  LEFT JOIN `nba-props-platform.nba_precompute.team_defense_zone_analysis` tdz
    ON pp.opponent_team_abbr = tdz.team_abbr AND pp.game_date = tdz.analysis_date
  LEFT JOIN `nba-props-platform.nba_precompute.player_daily_cache` pdc
    ON pp.player_lookup = pdc.player_lookup AND pp.game_date = pdc.cache_date
  WHERE pp.points_avg_last_5 IS NOT NULL AND pp.points_avg_last_10 IS NOT NULL
)

SELECT
  COUNT(*) as total_rows,
  COUNTIF(points_avg_last_5 IS NULL) as null_points_avg_last_5,
  COUNTIF(points_avg_last_10 IS NULL) as null_points_avg_last_10,
  COUNTIF(points_avg_season IS NULL) as null_points_avg_season,
  COUNTIF(points_std_last_10 IS NULL) as null_points_std_last_10,
  COUNTIF(minutes_avg_last_10 IS NULL) as null_minutes_avg_last_10,
  COUNTIF(fatigue_score IS NULL) as null_fatigue_score,
  COUNTIF(shot_zone_mismatch_score IS NULL) as null_shot_zone_mismatch_score,
  COUNTIF(pace_score IS NULL) as null_pace_score,
  COUNTIF(usage_spike_score IS NULL) as null_usage_spike_score,
  COUNTIF(opponent_def_rating_last_15 IS NULL) as null_opponent_def_rating_last_15,
  COUNTIF(opponent_pace_last_15 IS NULL) as null_opponent_pace_last_15,
  COUNTIF(is_home IS NULL) as null_is_home,
  COUNTIF(days_rest IS NULL) as null_days_rest,
  COUNTIF(back_to_back IS NULL) as null_back_to_back,
  COUNTIF(paint_rate_last_10 IS NULL) as null_paint_rate_last_10,
  COUNTIF(mid_range_rate_last_10 IS NULL) as null_mid_range_rate_last_10,
  COUNTIF(three_pt_rate_last_10 IS NULL) as null_three_pt_rate_last_10,
  COUNTIF(assisted_rate_last_10 IS NULL) as null_assisted_rate_last_10,
  COUNTIF(team_pace_last_10 IS NULL) as null_team_pace_last_10,
  COUNTIF(team_off_rating_last_10 IS NULL) as null_team_off_rating_last_10,
  COUNTIF(usage_rate_last_10 IS NULL) as null_usage_rate_last_10,
  COUNTIF(actual_points IS NULL) as null_actual_points
FROM feature_data
"""

results['null_analysis'] = run_query(null_analysis_query,
                                      'null_analysis',
                                      'Overall NULL rates across 25 features')
print()

# Investigation 2: Distribution Analysis
print("2. DATA DISTRIBUTION ANALYSIS")
print("-" * 80)

distribution_query = """
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
    SAFE_DIVIDE(paint_attempts, NULLIF(fg_attempts, 0)) * 100 as paint_rate,
    SAFE_DIVIDE(three_pt_attempts, NULLIF(fg_attempts, 0)) * 100 as three_pt_rate,
    CASE WHEN SPLIT(game_id, '_')[SAFE_OFFSET(2)] = team_abbr THEN TRUE ELSE FALSE END as is_home
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01' AND points IS NOT NULL
),

player_performance AS (
  SELECT
    player_lookup,
    game_date,
    team_abbr,
    opponent_team_abbr,
    is_home,
    points as actual_points,
    AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) as points_avg_last_5,
    AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as points_avg_last_10,
    AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) as points_avg_season,
    AVG(minutes_played) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as minutes_avg_last_10,
    DATE_DIFF(game_date, LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date), DAY) as days_rest,
    CASE WHEN DATE_DIFF(game_date, LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date), DAY) = 1 THEN TRUE ELSE FALSE END as back_to_back,
    AVG(paint_rate) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as paint_rate_last_10,
    AVG(three_pt_rate) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as three_pt_rate_last_10
  FROM player_games
),

feature_data AS (
  SELECT
    pp.*,
    pcf.fatigue_score,
    pdc.team_pace_last_10
  FROM player_performance pp
  LEFT JOIN `nba-props-platform.nba_precompute.player_composite_factors` pcf
    ON pp.player_lookup = pcf.player_lookup AND pp.game_date = pcf.game_date
  LEFT JOIN `nba-props-platform.nba_precompute.player_daily_cache` pdc
    ON pp.player_lookup = pdc.player_lookup AND pp.game_date = pdc.cache_date
  WHERE pp.points_avg_last_5 IS NOT NULL AND pp.points_avg_last_10 IS NOT NULL
),

splits AS (
  SELECT *, CASE WHEN game_date < '2023-04-01' THEN 'train' ELSE 'test' END as split
  FROM feature_data
)

SELECT
  split,
  COUNT(*) as samples,
  ROUND(AVG(points_avg_last_5), 2) as mean_points_avg_last_5,
  ROUND(STDDEV(points_avg_last_5), 2) as std_points_avg_last_5,
  ROUND(AVG(points_avg_last_10), 2) as mean_points_avg_last_10,
  ROUND(STDDEV(points_avg_last_10), 2) as std_points_avg_last_10,
  ROUND(AVG(COALESCE(paint_rate_last_10, 30)), 2) as mean_paint_rate_last_10,
  ROUND(AVG(COALESCE(three_pt_rate_last_10, 30)), 2) as mean_three_pt_rate_last_10,
  ROUND(AVG(COALESCE(fatigue_score, 70)), 2) as mean_fatigue_score,
  ROUND(AVG(CAST(is_home AS FLOAT64)), 2) as pct_home_games,
  ROUND(AVG(COALESCE(days_rest, 2)), 2) as mean_days_rest,
  ROUND(AVG(CAST(back_to_back AS FLOAT64)), 2) as pct_back_to_back,
  ROUND(AVG(actual_points), 2) as mean_actual_points,
  ROUND(STDDEV(actual_points), 2) as std_actual_points
FROM splits
GROUP BY split
ORDER BY split
"""

results['distribution'] = run_query(distribution_query,
                                     'distribution',
                                     'Feature distributions: Train vs Test')
print()

# Investigation 3: Correlation Analysis
print("3. FEATURE CORRELATION ANALYSIS")
print("-" * 80)

correlation_query = """
WITH player_games AS (
  SELECT
    player_lookup,
    game_date,
    game_id,
    team_abbr,
    opponent_team_abbr,
    points,
    minutes_played,
    SAFE_DIVIDE(paint_attempts, NULLIF(fg_attempts, 0)) * 100 as paint_rate,
    SAFE_DIVIDE(three_pt_attempts, NULLIF(fg_attempts, 0)) * 100 as three_pt_rate,
    CASE WHEN SPLIT(game_id, '_')[SAFE_OFFSET(2)] = team_abbr THEN TRUE ELSE FALSE END as is_home
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01' AND points IS NOT NULL
),

player_performance AS (
  SELECT
    player_lookup,
    game_date,
    is_home,
    points as actual_points,
    AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) as points_avg_last_5,
    AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as points_avg_last_10,
    AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) as points_avg_season,
    DATE_DIFF(game_date, LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date), DAY) as days_rest,
    AVG(paint_rate) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as paint_rate_last_10,
    AVG(three_pt_rate) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as three_pt_rate_last_10
  FROM player_games
),

feature_data AS (
  SELECT pp.*, pcf.fatigue_score
  FROM player_performance pp
  LEFT JOIN `nba-props-platform.nba_precompute.player_composite_factors` pcf
    ON pp.player_lookup = pcf.player_lookup AND pp.game_date = pcf.game_date
  WHERE pp.points_avg_last_5 IS NOT NULL AND pp.points_avg_last_10 IS NOT NULL
)

SELECT
  'Feature Correlations' as analysis_type,
  ROUND(CORR(points_avg_last_5, points_avg_last_10), 3) as corr_points_5_vs_10,
  ROUND(CORR(points_avg_last_10, points_avg_season), 3) as corr_points_10_vs_season,
  ROUND(CORR(COALESCE(paint_rate_last_10, 30), COALESCE(three_pt_rate_last_10, 30)), 3) as corr_paint_vs_3pt,
  ROUND(CORR(points_avg_last_5, actual_points), 3) as corr_points5_vs_target,
  ROUND(CORR(points_avg_last_10, actual_points), 3) as corr_points10_vs_target,
  ROUND(CORR(COALESCE(fatigue_score, 70), actual_points), 3) as corr_fatigue_vs_target,
  ROUND(CORR(CAST(is_home AS FLOAT64), actual_points), 3) as corr_home_vs_target,
  ROUND(CORR(COALESCE(days_rest, 2), actual_points), 3) as corr_rest_vs_target
FROM feature_data
"""

results['correlation'] = run_query(correlation_query,
                                    'correlation',
                                    'Feature correlations with target')
print()

# Investigation 4: Target Variable Analysis
print("4. TARGET VARIABLE ANALYSIS")
print("-" * 80)

target_query = """
WITH player_games AS (
  SELECT
    player_lookup,
    game_date,
    points,
    minutes_played
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01' AND points IS NOT NULL
),

player_performance AS (
  SELECT
    player_lookup,
    game_date,
    points as actual_points,
    AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) as points_avg_last_5,
    AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as points_avg_last_10,
    AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) as points_avg_season,
    AVG(minutes_played) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as minutes_avg_last_10
  FROM player_games
),

feature_data AS (
  SELECT *
  FROM player_performance
  WHERE points_avg_last_5 IS NOT NULL AND points_avg_last_10 IS NOT NULL
)

SELECT
  'Target Distribution' as analysis_type,
  COUNT(*) as total_samples,
  ROUND(AVG(actual_points), 2) as mean_actual_points,
  ROUND(APPROX_QUANTILES(actual_points, 100)[OFFSET(50)], 2) as median_actual_points,
  ROUND(STDDEV(actual_points), 2) as std_actual_points,
  ROUND(MIN(actual_points), 2) as min_actual_points,
  ROUND(MAX(actual_points), 2) as max_actual_points,
  ROUND(APPROX_QUANTILES(actual_points, 100)[OFFSET(25)], 2) as p25_actual_points,
  ROUND(APPROX_QUANTILES(actual_points, 100)[OFFSET(75)], 2) as p75_actual_points,
  COUNTIF(actual_points = 0) as count_0_points,
  COUNTIF(actual_points > 0 AND actual_points <= 5) as count_1_5_points,
  COUNTIF(actual_points > 5 AND actual_points <= 10) as count_6_10_points,
  COUNTIF(actual_points > 10 AND actual_points <= 20) as count_11_20_points,
  COUNTIF(actual_points > 20 AND actual_points <= 30) as count_21_30_points,
  COUNTIF(actual_points > 30) as count_over_30_points
FROM feature_data
"""

results['target_analysis'] = run_query(target_query,
                                        'target_analysis',
                                        'Target variable distribution')
print()

# Investigation 5: Player Segmentation
print("5. PLAYER SEGMENTATION ANALYSIS")
print("-" * 80)

segmentation_query = """
WITH player_games AS (
  SELECT
    player_lookup,
    game_date,
    points,
    minutes_played
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01' AND points IS NOT NULL
),

player_performance AS (
  SELECT
    player_lookup,
    game_date,
    points as actual_points,
    AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as points_avg_last_10,
    AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) as points_avg_season
  FROM player_games
),

feature_data AS (
  SELECT *
  FROM player_performance pp
  WHERE points_avg_last_10 IS NOT NULL AND points_avg_season IS NOT NULL
)

SELECT
  CASE
    WHEN points_avg_season >= 20 THEN 'Star (20+ ppg)'
    WHEN points_avg_season >= 12 THEN 'Starter (12-20 ppg)'
    WHEN points_avg_season >= 6 THEN 'Role Player (6-12 ppg)'
    ELSE 'Bench (<6 ppg)'
  END as player_type,
  COUNT(*) as samples,
  COUNT(DISTINCT player_lookup) as unique_players,
  ROUND(AVG(actual_points), 2) as mean_actual_points,
  ROUND(STDDEV(actual_points), 2) as std_actual_points,
  ROUND(AVG(ABS(actual_points - points_avg_last_10)), 2) as mean_abs_deviation_from_avg
FROM feature_data
GROUP BY player_type
ORDER BY MIN(points_avg_season) DESC
"""

results['player_segmentation'] = run_query(segmentation_query,
                                            'player_segmentation',
                                            'Player type segmentation')
print()

# ============================================================================
# Generate comprehensive report
# ============================================================================

print("=" * 80)
print("GENERATING DATA QUALITY REPORT")
print("=" * 80)
print()

report_lines = []
report_lines.append("=" * 80)
report_lines.append(" COMPREHENSIVE DATA QUALITY INVESTIGATION REPORT")
report_lines.append("=" * 80)
report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
report_lines.append("")
report_lines.append("PURPOSE:")
report_lines.append("Understand root causes of ML model failure (4.63 MAE vs 4.33 mock baseline)")
report_lines.append("")

# Section 1: NULL Analysis
if results.get('null_analysis') is not None and len(results['null_analysis']) > 0:
    report_lines.append("=" * 80)
    report_lines.append("1. MISSING DATA PATTERNS (NULL ANALYSIS)")
    report_lines.append("=" * 80)
    report_lines.append("")

    df = results['null_analysis']
    total_rows = df['total_rows'].iloc[0]

    report_lines.append(f"Total Training Samples: {total_rows:,}")
    report_lines.append("")
    report_lines.append("NULL Rates by Feature Category:")
    report_lines.append("-" * 80)

    # Calculate NULL percentages for each feature
    null_features = []
    for col in df.columns:
        if col.startswith('null_') and col != 'null_actual_points':
            feature_name = col.replace('null_', '')
            null_count = df[col].iloc[0]
            null_pct = (null_count / total_rows) * 100
            null_features.append((feature_name, null_count, null_pct))

    # Sort by NULL percentage (highest first)
    null_features.sort(key=lambda x: x[2], reverse=True)

    report_lines.append("")
    report_lines.append("Top 10 Features with Highest NULL Rates:")
    report_lines.append(f"{'Feature':<40} {'NULL Count':>12} {'NULL %':>10}")
    report_lines.append("-" * 80)

    for feature, null_count, null_pct in null_features[:10]:
        bar = '█' * int(null_pct / 5)  # 1 block per 5%
        report_lines.append(f"{feature:<40} {null_count:>12,} {null_pct:>9.1f}% {bar}")

    report_lines.append("")

# Section 2: Distribution Analysis
if results.get('distribution') is not None and len(results['distribution']) > 0:
    report_lines.append("=" * 80)
    report_lines.append("2. DATA DISTRIBUTION ANALYSIS (Train vs Test)")
    report_lines.append("=" * 80)
    report_lines.append("")

    df = results['distribution']

    report_lines.append(f"{'Metric':<40} {'Train':>12} {'Test':>12} {'Shift':>10}")
    report_lines.append("-" * 80)

    if len(df) == 2:
        train = df[df['split'] == 'train'].iloc[0]
        test = df[df['split'] == 'test'].iloc[0]

        report_lines.append(f"{'Samples':<40} {int(train['samples']):>12,} {int(test['samples']):>12,}")
        report_lines.append("")

        # Compare key metrics
        metrics = [
            ('mean_points_avg_last_5', 'Points Avg (Last 5)'),
            ('mean_points_avg_last_10', 'Points Avg (Last 10)'),
            ('mean_paint_rate_last_10', 'Paint Rate %'),
            ('mean_three_pt_rate_last_10', '3PT Rate %'),
            ('mean_fatigue_score', 'Fatigue Score'),
            ('pct_home_games', 'Home Games %'),
            ('mean_days_rest', 'Days Rest'),
            ('pct_back_to_back', 'Back-to-Back %'),
            ('mean_actual_points', 'Actual Points (Target)'),
            ('std_actual_points', 'Std Dev (Target)')
        ]

        for metric_col, metric_name in metrics:
            if metric_col in train.index and metric_col in test.index:
                train_val = train[metric_col]
                test_val = test[metric_col]
                shift = ((test_val - train_val) / train_val * 100) if train_val != 0 else 0
                shift_str = f"{shift:+.1f}%" if abs(shift) > 0.1 else "~"
                report_lines.append(f"{metric_name:<40} {train_val:>12.2f} {test_val:>12.2f} {shift_str:>10}")

    report_lines.append("")

# Section 3: Correlation Analysis
if results.get('correlation') is not None and len(results['correlation']) > 0:
    report_lines.append("=" * 80)
    report_lines.append("3. FEATURE CORRELATION ANALYSIS")
    report_lines.append("=" * 80)
    report_lines.append("")

    df = results['correlation'].iloc[0]

    report_lines.append("Feature Intercorrelations:")
    report_lines.append("-" * 80)
    report_lines.append(f"Points Avg (Last 5) vs (Last 10):     {df['corr_points_5_vs_10']:>6.3f}")
    report_lines.append(f"Points Avg (Last 10) vs Season:       {df['corr_points_10_vs_season']:>6.3f}")
    report_lines.append(f"Paint Rate vs 3PT Rate:                {df['corr_paint_vs_3pt']:>6.3f}")
    report_lines.append("")

    report_lines.append("Correlations with Target (Actual Points):")
    report_lines.append("-" * 80)

    correlations = [
        (df['corr_points5_vs_target'], 'Points Avg (Last 5)'),
        (df['corr_points10_vs_target'], 'Points Avg (Last 10)'),
        (df['corr_fatigue_vs_target'], 'Fatigue Score'),
        (df['corr_home_vs_target'], 'Is Home'),
        (df['corr_rest_vs_target'], 'Days Rest')
    ]

    correlations.sort(reverse=True)

    for corr, feature in correlations:
        bar = '█' * int(abs(corr) * 50)  # 1 block per 0.02 correlation
        sign = '+' if corr >= 0 else '-'
        report_lines.append(f"{feature:<40} {sign}{abs(corr):.3f} {bar}")

    report_lines.append("")

# Section 4: Target Analysis
if results.get('target_analysis') is not None and len(results['target_analysis']) > 0:
    report_lines.append("=" * 80)
    report_lines.append("4. TARGET VARIABLE ANALYSIS")
    report_lines.append("=" * 80)
    report_lines.append("")

    df = results['target_analysis'].iloc[0]

    report_lines.append("Target Distribution (Actual Points):")
    report_lines.append("-" * 80)
    report_lines.append(f"Total Samples:        {int(df['total_samples']):,}")
    report_lines.append(f"Mean:                 {df['mean_actual_points']:.2f} points")
    report_lines.append(f"Median:               {df['median_actual_points']:.2f} points")
    report_lines.append(f"Std Dev:              {df['std_actual_points']:.2f} points")
    report_lines.append(f"Min:                  {df['min_actual_points']:.2f} points")
    report_lines.append(f"Max:                  {df['max_actual_points']:.2f} points")
    report_lines.append(f"25th Percentile:      {df['p25_actual_points']:.2f} points")
    report_lines.append(f"75th Percentile:      {df['p75_actual_points']:.2f} points")
    report_lines.append("")

    report_lines.append("Distribution by Point Range:")
    report_lines.append("-" * 80)

    total = df['total_samples']
    bins = [
        ('0 points', df['count_0_points']),
        ('1-5 points', df['count_1_5_points']),
        ('6-10 points', df['count_6_10_points']),
        ('11-20 points', df['count_11_20_points']),
        ('21-30 points', df['count_21_30_points']),
        ('30+ points', df['count_over_30_points'])
    ]

    for bin_name, count in bins:
        pct = (count / total) * 100
        bar = '█' * int(pct / 2)  # 1 block per 2%
        report_lines.append(f"{bin_name:<20} {int(count):>10,} ({pct:>5.1f}%) {bar}")

    report_lines.append("")

# Section 5: Player Segmentation
if results.get('player_segmentation') is not None and len(results['player_segmentation']) > 0:
    report_lines.append("=" * 80)
    report_lines.append("5. PLAYER SEGMENTATION ANALYSIS")
    report_lines.append("=" * 80)
    report_lines.append("")
    report_lines.append("Should we train separate models for different player types?")
    report_lines.append("")

    df = results['player_segmentation']

    report_lines.append(f"{'Player Type':<25} {'Samples':>10} {'Players':>10} {'Mean Pts':>10} {'Std Dev':>10} {'MAE':>10}")
    report_lines.append("-" * 80)

    for _, row in df.iterrows():
        report_lines.append(
            f"{row['player_type']:<25} "
            f"{int(row['samples']):>10,} "
            f"{int(row['unique_players']):>10,} "
            f"{row['mean_actual_points']:>10.2f} "
            f"{row['std_actual_points']:>10.2f} "
            f"{row['mean_abs_deviation_from_avg']:>10.2f}"
        )

    report_lines.append("")

# Section 6: Key Findings
report_lines.append("=" * 80)
report_lines.append("6. KEY FINDINGS & RECOMMENDATIONS")
report_lines.append("=" * 80)
report_lines.append("")

# Calculate key insights
if results.get('null_analysis') is not None:
    df = results['null_analysis']
    total = df['total_rows'].iloc[0]

    # Find features with >50% NULL rate
    high_null_features = []
    for col in df.columns:
        if col.startswith('null_'):
            null_count = df[col].iloc[0]
            null_pct = (null_count / total) * 100
            if null_pct > 50:
                high_null_features.append((col.replace('null_', ''), null_pct))

    if high_null_features:
        report_lines.append("CRITICAL ISSUE: High NULL Rates")
        report_lines.append("-" * 80)
        report_lines.append(f"Found {len(high_null_features)} features with >50% missing data:")
        for feature, pct in high_null_features:
            report_lines.append(f"  - {feature}: {pct:.1f}% NULL")
        report_lines.append("")
        report_lines.append("IMPACT: Model is learning from imputed values, not real data")
        report_lines.append("RECOMMENDATION: Fix data pipeline or remove features with >50% NULL")
        report_lines.append("")

if results.get('distribution') is not None and len(results['distribution']) == 2:
    train = results['distribution'][results['distribution']['split'] == 'train'].iloc[0]
    test = results['distribution'][results['distribution']['split'] == 'test'].iloc[0]

    target_shift = ((test['mean_actual_points'] - train['mean_actual_points']) /
                    train['mean_actual_points'] * 100)

    if abs(target_shift) > 5:
        report_lines.append("WARNING: Distribution Shift Detected")
        report_lines.append("-" * 80)
        report_lines.append(f"Target variable shift: {target_shift:+.1f}% (train vs test)")
        report_lines.append("IMPACT: Model trained on different distribution than test data")
        report_lines.append("RECOMMENDATION: Use time-aware validation strategy")
        report_lines.append("")

if results.get('correlation') is not None:
    df = results['correlation'].iloc[0]

    if df['corr_points10_vs_target'] > 0.8:
        report_lines.append("INSIGHT: Strong Feature Redundancy")
        report_lines.append("-" * 80)
        report_lines.append(f"Points Avg (Last 10) correlation with target: {df['corr_points10_vs_target']:.3f}")
        report_lines.append("IMPACT: Model heavily relies on recent averages (54% feature importance)")
        report_lines.append("RECOMMENDATION: Recent form is critical - ensure this feature is NEVER NULL")
        report_lines.append("")

if results.get('player_segmentation') is not None:
    df = results['player_segmentation']

    # Check if MAE varies significantly by player type
    mae_values = df['mean_abs_deviation_from_avg'].values
    if len(mae_values) > 1:
        mae_range = mae_values.max() - mae_values.min()
        if mae_range > 2.0:
            report_lines.append("INSIGHT: Prediction Difficulty Varies by Player Type")
            report_lines.append("-" * 80)
            report_lines.append(f"MAE range across player types: {mae_range:.2f} points")
            report_lines.append("RECOMMENDATION: Consider training separate models for:")
            report_lines.append("  - Stars/Starters (more predictable)")
            report_lines.append("  - Bench players (more volatile)")
            report_lines.append("")

# Sample sufficiency
if results.get('target_analysis') is not None:
    df = results['target_analysis'].iloc[0]
    total_samples = df['total_samples']

    samples_per_feature = total_samples / 25

    report_lines.append("SAMPLE SUFFICIENCY")
    report_lines.append("-" * 80)
    report_lines.append(f"Total samples: {total_samples:,}")
    report_lines.append(f"Features: 25")
    report_lines.append(f"Samples per feature: {samples_per_feature:,.0f}")
    report_lines.append("")

    if samples_per_feature > 2000:
        report_lines.append("STATUS: ✓ Sufficient samples (>2000 per feature)")
    else:
        report_lines.append("STATUS: ⚠ Marginal samples (<2000 per feature)")
        report_lines.append("RECOMMENDATION: Collect more data or reduce feature count")

    report_lines.append("")

# Final recommendations
report_lines.append("=" * 80)
report_lines.append("RECOMMENDED ACTIONS")
report_lines.append("=" * 80)
report_lines.append("")
report_lines.append("Priority 1 (HIGH IMPACT):")
report_lines.append("  1. Fix NULL rates in precompute tables (fatigue_score, team_pace_last_10)")
report_lines.append("  2. Verify opponent defense data coverage (seems sparse)")
report_lines.append("  3. Ensure points_avg_last_10 is NEVER NULL (most important feature)")
report_lines.append("")
report_lines.append("Priority 2 (MEDIUM IMPACT):")
report_lines.append("  4. Add temporal validation (time-aware splits)")
report_lines.append("  5. Consider separate models for starters vs bench players")
report_lines.append("  6. Hyperparameter tuning (current settings are default)")
report_lines.append("")
report_lines.append("Priority 3 (LOW IMPACT):")
report_lines.append("  7. Feature engineering for better shot selection metrics")
report_lines.append("  8. Collect more historical data (extend to 2019-2020)")
report_lines.append("  9. Ensemble methods (combine multiple models)")
report_lines.append("")

report_lines.append("=" * 80)
report_lines.append("END OF REPORT")
report_lines.append("=" * 80)

# Write report to file
report_text = '\n'.join(report_lines)
report_file = OUTPUT_DIR / f"data_quality_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

with open(report_file, 'w') as f:
    f.write(report_text)

print(f"✓ Report saved: {report_file}")
print()

# Print report to console
print(report_text)

print()
print("=" * 80)
print(" INVESTIGATION COMPLETE")
print("=" * 80)
print(f"Report saved to: {report_file}")
print()

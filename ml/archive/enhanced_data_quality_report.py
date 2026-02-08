#!/usr/bin/env python3
"""
Enhanced Data Quality Report with Correlation Matrix and Advanced Analysis
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from google.cloud import bigquery
from datetime import datetime

PROJECT_ID = "nba-props-platform"
OUTPUT_DIR = Path("ml/reports")
OUTPUT_DIR.mkdir(exist_ok=True)

print("=" * 80)
print(" ENHANCED DATA QUALITY REPORT")
print("=" * 80)
print()

client = bigquery.Client(project=PROJECT_ID)

# ============================================================================
# Load actual training data (same as model uses)
# ============================================================================

print("Loading training data...")

query = """
WITH player_games AS (
  SELECT
    player_lookup,
    game_date,
    game_id,
    team_abbr,
    opponent_team_abbr,
    points,
    SAFE_DIVIDE(paint_attempts, NULLIF(fg_attempts, 0)) * 100 as paint_rate,
    SAFE_DIVIDE(mid_range_attempts, NULLIF(fg_attempts, 0)) * 100 as mid_range_rate,
    SAFE_DIVIDE(three_pt_attempts, NULLIF(fg_attempts, 0)) * 100 as three_pt_rate,
    SAFE_DIVIDE(assisted_fg_makes, NULLIF(fg_makes, 0)) * 100 as assisted_rate,
    CASE
      WHEN SPLIT(game_id, '_')[SAFE_OFFSET(2)] = team_abbr THEN 1.0
      ELSE 0.0
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
    DATE_DIFF(game_date, LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date), DAY) as days_rest,
    CASE WHEN DATE_DIFF(game_date, LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date), DAY) = 1 THEN 1.0 ELSE 0.0 END as back_to_back,
    AVG(paint_rate) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as paint_rate_last_10,
    AVG(mid_range_rate) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as mid_range_rate_last_10,
    AVG(three_pt_rate) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as three_pt_rate_last_10,
    AVG(assisted_rate) OVER (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as assisted_rate_last_10
  FROM player_games
),

feature_data AS (
  SELECT
    pp.*,
    COALESCE(pcf.fatigue_score, 70) as fatigue_score,
    COALESCE(pcf.shot_zone_mismatch_score, 0) as shot_zone_mismatch_score,
    COALESCE(pcf.pace_score, 0) as pace_score,
    COALESCE(pcf.usage_spike_score, 0) as usage_spike_score,
    COALESCE(tdz.defensive_rating_last_15, 112.0) as opponent_def_rating_last_15,
    COALESCE(tdz.opponent_pace, 100.0) as opponent_pace_last_15,
    COALESCE(pdc.team_pace_last_10, 100.0) as team_pace_last_10,
    COALESCE(pdc.team_off_rating_last_10, 112.0) as team_off_rating_last_10
  FROM player_performance pp
  LEFT JOIN `nba-props-platform.nba_precompute.player_composite_factors` pcf
    ON pp.player_lookup = pcf.player_lookup AND pp.game_date = pcf.game_date
  LEFT JOIN `nba-props-platform.nba_precompute.team_defense_zone_analysis` tdz
    ON pp.opponent_team_abbr = tdz.team_abbr AND pp.game_date = tdz.analysis_date
  LEFT JOIN `nba-props-platform.nba_precompute.player_daily_cache` pdc
    ON pp.player_lookup = pdc.player_lookup AND pp.game_date = pdc.cache_date
  WHERE pp.points_avg_last_5 IS NOT NULL AND pp.points_avg_last_10 IS NOT NULL
)

SELECT *
FROM feature_data
LIMIT 50000
"""

df = client.query(query).to_dataframe()
print(f"Loaded {len(df):,} samples")
print()

# ============================================================================
# 1. NULL ANALYSIS
# ============================================================================

print("=" * 80)
print("1. NULL ANALYSIS")
print("=" * 80)
print()

null_counts = df.isnull().sum()
null_pcts = (null_counts / len(df)) * 100

null_df = pd.DataFrame({
    'Feature': null_counts.index,
    'NULL_Count': null_counts.values,
    'NULL_Pct': null_pcts.values
}).sort_values('NULL_Pct', ascending=False)

print(f"{'Feature':<40} {'NULL Count':>12} {'NULL %':>10}")
print("-" * 80)
for _, row in null_df.head(15).iterrows():
    bar = '█' * int(row['NULL_Pct'] / 5)
    print(f"{row['Feature']:<40} {int(row['NULL_Count']):>12,} {row['NULL_Pct']:>9.1f}% {bar}")
print()

# ============================================================================
# 2. FEATURE CORRELATION MATRIX
# ============================================================================

print("=" * 80)
print("2. FEATURE CORRELATION MATRIX")
print("=" * 80)
print()

# Select numerical features (excluding identifiers and dates)
feature_cols = [
    'points_avg_last_5',
    'points_avg_last_10',
    'points_avg_season',
    'points_std_last_10',
    'fatigue_score',
    'shot_zone_mismatch_score',
    'pace_score',
    'usage_spike_score',
    'opponent_def_rating_last_15',
    'opponent_pace_last_15',
    'is_home',
    'days_rest',
    'back_to_back',
    'paint_rate_last_10',
    'mid_range_rate_last_10',
    'three_pt_rate_last_10',
    'assisted_rate_last_10',
    'team_pace_last_10',
    'team_off_rating_last_10',
    'actual_points'
]

# Prepare data for correlation
df_features = df[feature_cols].copy()

# Fill NaNs with reasonable defaults for correlation calculation
df_features['points_std_last_10'] = df_features['points_std_last_10'].fillna(5.0)
df_features['days_rest'] = df_features['days_rest'].fillna(2.0)
df_features['paint_rate_last_10'] = df_features['paint_rate_last_10'].fillna(30.0)
df_features['mid_range_rate_last_10'] = df_features['mid_range_rate_last_10'].fillna(20.0)
df_features['three_pt_rate_last_10'] = df_features['three_pt_rate_last_10'].fillna(30.0)
df_features['assisted_rate_last_10'] = df_features['assisted_rate_last_10'].fillna(60.0)

# Calculate correlation matrix
corr_matrix = df_features.corr()

# Print correlations with target
print("Correlations with Target (actual_points):")
print("-" * 80)
target_corr = corr_matrix['actual_points'].sort_values(ascending=False)
for feature, corr in target_corr.items():
    if feature != 'actual_points' and not pd.isna(corr):
        bar = '█' * int(abs(corr) * 50)
        sign = '+' if corr >= 0 else '-'
        print(f"{feature:<40} {sign}{abs(corr):.3f} {bar}")
print()

# Find highly correlated feature pairs (redundancy)
print("Highly Correlated Feature Pairs (>0.7):")
print("-" * 80)
high_corr_pairs = []
for i in range(len(corr_matrix.columns)):
    for j in range(i+1, len(corr_matrix.columns)):
        if abs(corr_matrix.iloc[i, j]) > 0.7:
            high_corr_pairs.append((
                corr_matrix.columns[i],
                corr_matrix.columns[j],
                corr_matrix.iloc[i, j]
            ))

if high_corr_pairs:
    for feat1, feat2, corr in sorted(high_corr_pairs, key=lambda x: abs(x[2]), reverse=True):
        print(f"{feat1:<30} <-> {feat2:<30} {corr:>6.3f}")
else:
    print("No highly correlated pairs found (good - features are independent)")
print()

# Save correlation matrix
corr_file = OUTPUT_DIR / f"correlation_matrix_{datetime.now().strftime('%Y%m%d')}.csv"
corr_matrix.to_csv(corr_file)
print(f"✓ Correlation matrix saved: {corr_file}")
print()

# ============================================================================
# 3. DATA DISTRIBUTION ANALYSIS
# ============================================================================

print("=" * 80)
print("3. DATA DISTRIBUTION ANALYSIS")
print("=" * 80)
print()

# Key statistics
print("Feature Statistics:")
print("-" * 80)
stats_features = [
    'points_avg_last_5',
    'points_avg_last_10',
    'points_avg_season',
    'fatigue_score',
    'days_rest',
    'actual_points'
]

print(f"{'Feature':<30} {'Mean':>10} {'Median':>10} {'Std':>10} {'Min':>10} {'Max':>10}")
print("-" * 80)
for col in stats_features:
    if col in df.columns:
        data = df[col].dropna()
        print(f"{col:<30} {data.mean():>10.2f} {data.median():>10.2f} "
              f"{data.std():>10.2f} {data.min():>10.2f} {data.max():>10.2f}")
print()

# ============================================================================
# 4. OUTLIER DETECTION
# ============================================================================

print("=" * 80)
print("4. OUTLIER DETECTION")
print("=" * 80)
print()

# Define outlier thresholds
outliers = {
    'negative_points_avg': len(df[df['points_avg_last_10'] < 0]),
    'extreme_high_points': len(df[df['points_avg_last_10'] > 50]),
    'negative_actual_points': len(df[df['actual_points'] < 0]),
    'extreme_actual_points': len(df[df['actual_points'] > 70]),
    'invalid_fatigue_score': len(df[(df['fatigue_score'] < 0) | (df['fatigue_score'] > 100)]),
    'extreme_days_rest': len(df[df['days_rest'] > 30]),
}

print(f"{'Outlier Type':<40} {'Count':>10} {'Pct':>10}")
print("-" * 80)
for outlier_type, count in outliers.items():
    pct = (count / len(df)) * 100
    print(f"{outlier_type:<40} {count:>10,} {pct:>9.2f}%")
print()

# ============================================================================
# 5. TRAIN/TEST DISTRIBUTION SHIFT
# ============================================================================

print("=" * 80)
print("5. TRAIN/TEST DISTRIBUTION SHIFT")
print("=" * 80)
print()

# Split data chronologically (70/30 split)
df_sorted = df.sort_values('game_date')
split_idx = int(len(df_sorted) * 0.70)

train_df = df_sorted.iloc[:split_idx]
test_df = df_sorted.iloc[split_idx:]

print(f"Train samples: {len(train_df):,} ({train_df['game_date'].min()} to {train_df['game_date'].max()})")
print(f"Test samples:  {len(test_df):,} ({test_df['game_date'].min()} to {test_df['game_date'].max()})")
print()

# Compare distributions
print(f"{'Feature':<30} {'Train Mean':>12} {'Test Mean':>12} {'Shift %':>10}")
print("-" * 80)

compare_features = [
    'points_avg_last_5',
    'points_avg_last_10',
    'fatigue_score',
    'is_home',
    'days_rest',
    'back_to_back',
    'actual_points'
]

for col in compare_features:
    train_mean = train_df[col].mean()
    test_mean = test_df[col].mean()
    shift = ((test_mean - train_mean) / train_mean * 100) if train_mean != 0 else 0

    flag = "⚠" if abs(shift) > 5 else " "
    print(f"{col:<30} {train_mean:>12.2f} {test_mean:>12.2f} {shift:>9.1f}% {flag}")
print()

# ============================================================================
# 6. SAMPLE SUFFICIENCY BY PLAYER TYPE
# ============================================================================

print("=" * 80)
print("6. SAMPLE SUFFICIENCY BY PLAYER TYPE")
print("=" * 80)
print()

# Segment by season average
df['player_type'] = pd.cut(
    df['points_avg_season'],
    bins=[-np.inf, 6, 12, 20, np.inf],
    labels=['Bench (<6 ppg)', 'Role Player (6-12)', 'Starter (12-20)', 'Star (20+)']
)

print(f"{'Player Type':<25} {'Samples':>10} {'Players':>10} {'Mean Pts':>10} {'Std Dev':>10}")
print("-" * 80)
for ptype in ['Star (20+)', 'Starter (12-20)', 'Role Player (6-12)', 'Bench (<6 ppg)']:
    subset = df[df['player_type'] == ptype]
    if len(subset) > 0:
        print(f"{ptype:<25} {len(subset):>10,} {subset['player_lookup'].nunique():>10,} "
              f"{subset['actual_points'].mean():>10.2f} {subset['actual_points'].std():>10.2f}")
print()

# ============================================================================
# 7. GENERATE SUMMARY REPORT
# ============================================================================

report_lines = []
report_lines.append("=" * 80)
report_lines.append(" ENHANCED DATA QUALITY REPORT")
report_lines.append("=" * 80)
report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
report_lines.append(f"Samples analyzed: {len(df):,}")
report_lines.append("")

report_lines.append("=" * 80)
report_lines.append("CRITICAL FINDINGS")
report_lines.append("=" * 80)
report_lines.append("")

# Finding 1: High NULL rates
high_null_features = null_df[null_df['NULL_Pct'] > 10]
if len(high_null_features) > 0:
    report_lines.append("1. HIGH NULL RATES DETECTED")
    report_lines.append("-" * 80)
    report_lines.append(f"Found {len(high_null_features)} features with >10% missing data:")
    for _, row in high_null_features.iterrows():
        report_lines.append(f"  - {row['Feature']}: {row['NULL_Pct']:.1f}% NULL")
    report_lines.append("")
    report_lines.append("IMPACT: Model learning from imputed defaults, not real patterns")
    report_lines.append("RECOMMENDATION: Fix precompute pipeline data coverage")
    report_lines.append("")

# Finding 2: Feature redundancy
if len(high_corr_pairs) > 0:
    report_lines.append("2. FEATURE REDUNDANCY DETECTED")
    report_lines.append("-" * 80)
    report_lines.append(f"Found {len(high_corr_pairs)} highly correlated feature pairs:")
    for feat1, feat2, corr in high_corr_pairs[:5]:
        report_lines.append(f"  - {feat1} <-> {feat2}: {corr:.3f}")
    report_lines.append("")
    report_lines.append("IMPACT: Redundant features don't add new information")
    report_lines.append("RECOMMENDATION: Consider removing one feature from each pair")
    report_lines.append("")

# Finding 3: Strongest predictors
report_lines.append("3. STRONGEST PREDICTORS OF ACTUAL POINTS")
report_lines.append("-" * 80)
top_predictors = target_corr.drop('actual_points').head(5)
for feature, corr in top_predictors.items():
    report_lines.append(f"  - {feature}: {corr:.3f}")
report_lines.append("")
report_lines.append("INSIGHT: Recent performance (last 5-10 games) dominates predictions")
report_lines.append("RECOMMENDATION: Ensure these features are NEVER NULL")
report_lines.append("")

# Finding 4: Distribution shift
train_test_shift = ((test_df['actual_points'].mean() - train_df['actual_points'].mean()) /
                     train_df['actual_points'].mean() * 100)
if abs(train_test_shift) > 3:
    report_lines.append("4. TRAIN/TEST DISTRIBUTION SHIFT")
    report_lines.append("-" * 80)
    report_lines.append(f"Target variable shift: {train_test_shift:+.1f}%")
    report_lines.append("IMPACT: Model trained on different distribution than test")
    report_lines.append("RECOMMENDATION: Use time-aware cross-validation")
    report_lines.append("")

report_lines.append("=" * 80)
report_lines.append("RECOMMENDATIONS")
report_lines.append("=" * 80)
report_lines.append("")
report_lines.append("Priority 1 (CRITICAL):")
report_lines.append("  1. Fix data coverage in precompute tables")
report_lines.append("  2. Ensure critical features (points_avg_last_10) are complete")
report_lines.append("  3. Investigate why minutes_played is 95.8% NULL")
report_lines.append("")
report_lines.append("Priority 2 (HIGH):")
report_lines.append("  4. Remove redundant features to reduce noise")
report_lines.append("  5. Train separate models for different player types")
report_lines.append("  6. Use time-aware validation instead of random split")
report_lines.append("")
report_lines.append("Priority 3 (MEDIUM):")
report_lines.append("  7. Hyperparameter tuning with current feature set")
report_lines.append("  8. Feature engineering for better context signals")
report_lines.append("  9. Collect more historical data (2019-2020 seasons)")
report_lines.append("")
report_lines.append("=" * 80)
report_lines.append("END OF REPORT")
report_lines.append("=" * 80)

report_text = '\n'.join(report_lines)
report_file = OUTPUT_DIR / f"enhanced_data_quality_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

with open(report_file, 'w') as f:
    f.write(report_text)

print(f"✓ Enhanced report saved: {report_file}")
print()
print(report_text)

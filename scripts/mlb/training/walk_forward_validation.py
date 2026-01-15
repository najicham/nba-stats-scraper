#!/usr/bin/env python3
"""
Walk-Forward Validation for MLB Pitcher Strikeout Classifier

Instead of a single train/test split, this script:
1. Trains on months 1-6, tests on month 7
2. Trains on months 1-7, tests on month 8
3. Trains on months 1-8, tests on month 9
4. ... and so on

This gives us a more robust estimate of model performance across
different time periods and market conditions.

Usage:
    PYTHONPATH=. python scripts/mlb/training/walk_forward_validation.py
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
import xgboost as xgb
from google.cloud import bigquery
from sklearn.metrics import accuracy_score, roc_auc_score, log_loss

PROJECT_ID = "nba-props-platform"

print("=" * 80)
print(" WALK-FORWARD VALIDATION")
print(" MLB Pitcher Strikeout Classifier")
print("=" * 80)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================================================
# LOAD DATA
# ============================================================================

print("Loading data from BigQuery...")

client = bigquery.Client(project=PROJECT_ID)

query = """
WITH statcast_rolling AS (
    -- Get per-game rolling statcast features
    SELECT DISTINCT
        player_lookup,
        game_date,
        swstr_pct_last_3,
        swstr_pct_last_5,
        swstr_pct_season_prior,
        fb_velocity_last_3,
        fb_velocity_season_prior
    FROM `mlb_analytics.pitcher_rolling_statcast`
    WHERE statcast_games_count >= 3
)
SELECT
    bp.game_date,
    bp.player_name,
    bp.over_line,
    bp.projection_value,
    bp.actual_value,
    bp.over_odds,
    bp.perf_last_5_over,
    bp.perf_last_5_under,
    bp.perf_last_10_over,
    bp.perf_last_10_under,
    CASE WHEN bp.actual_value > bp.over_line THEN 1 ELSE 0 END as went_over,

    -- Features from pitcher_game_summary
    COALESCE(pgs.k_avg_last_3, 5.0) as f00_k_avg_last_3,
    COALESCE(pgs.k_avg_last_5, 5.0) as f01_k_avg_last_5,
    COALESCE(pgs.k_avg_last_10, 5.0) as f02_k_avg_last_10,
    COALESCE(pgs.k_std_last_10, 2.0) as f03_k_std_last_10,
    COALESCE(pgs.ip_avg_last_5, 5.5) as f04_ip_avg_last_5,
    COALESCE(pgs.season_k_per_9, 8.5) as f05_season_k_per_9,
    COALESCE(pgs.era_rolling_10, 4.0) as f06_season_era,
    COALESCE(pgs.whip_rolling_10, 1.3) as f07_season_whip,
    COALESCE(pgs.season_games_started, 5) as f08_season_games,
    COALESCE(pgs.season_strikeouts, 30) as f09_season_k_total,
    IF(pgs.is_home, 1.0, 0.0) as f10_is_home,
    COALESCE(pgs.opponent_team_k_rate, 0.22) as f15_opponent_team_k_rate,
    COALESCE(pgs.ballpark_k_factor, 1.0) as f16_ballpark_k_factor,
    COALESCE(pgs.month_of_season, 6) as f17_month_of_season,
    COALESCE(pgs.days_into_season, 90) as f18_days_into_season,
    -- SwStr% - LEADING INDICATORS (Season-level)
    COALESCE(pgs.season_swstr_pct, 0.105) as f19_season_swstr_pct,
    COALESCE(pgs.season_csw_pct, 0.29) as f19b_season_csw_pct,
    COALESCE(pgs.season_chase_pct, 0.30) as f19c_season_chase_pct,

    COALESCE(pgs.days_rest, 5) as f20_days_rest,
    pgs.games_last_30_days as f21_games_last_30_days,
    COALESCE(pgs.pitch_count_avg_last_5, 90.0) as f22_pitch_count_avg,
    COALESCE(pgs.season_innings, 50.0) as f23_season_ip_total,
    IF(pgs.is_postseason, 1.0, 0.0) as f24_is_postseason,

    -- Line-relative features
    (COALESCE(pgs.k_avg_last_5, 5.0) - bp.over_line) as f30_k_avg_vs_line,
    bp.over_line as f32_line_level,

    -- BettingPros features
    bp.projection_value as f40_bp_projection,
    (bp.projection_value - bp.over_line) as f41_projection_diff,
    SAFE_DIVIDE(bp.perf_last_5_over, (bp.perf_last_5_over + bp.perf_last_5_under)) as f42_perf_last_5_pct,
    SAFE_DIVIDE(bp.perf_last_10_over, (bp.perf_last_10_over + bp.perf_last_10_under)) as f43_perf_last_10_pct,
    CASE
        WHEN bp.over_odds < 0 THEN ABS(bp.over_odds) / (ABS(bp.over_odds) + 100.0)
        ELSE 100.0 / (bp.over_odds + 100.0)
    END as f44_over_implied_prob,

    -- NEW: Rolling Statcast Features (BACKTEST VALIDATED)
    COALESCE(sc.swstr_pct_last_3, pgs.season_swstr_pct, 0.105) as f50_swstr_pct_last_3,
    COALESCE(sc.fb_velocity_last_3, 93.0) as f51_fb_velocity_last_3,
    -- SwStr% Trend: recent - season (positive = hot streak, negative = cold)
    COALESCE(sc.swstr_pct_last_3 - sc.swstr_pct_season_prior, 0.0) as f52_swstr_trend,
    -- Velocity change: season - recent (positive = dropping, negative = gaining)
    COALESCE(sc.fb_velocity_season_prior - sc.fb_velocity_last_3, 0.0) as f53_velocity_change

FROM `mlb_raw.bp_pitcher_props` bp
JOIN `mlb_analytics.pitcher_game_summary` pgs
    ON pgs.game_date = bp.game_date
    AND LOWER(REGEXP_REPLACE(NORMALIZE(pgs.player_lookup, NFD), r'[\\W_]+', '')) = bp.player_lookup
LEFT JOIN statcast_rolling sc
    ON REPLACE(pgs.player_lookup, '_', '') = REPLACE(sc.player_lookup, '_', '')
    AND pgs.game_date = sc.game_date
WHERE bp.market_id = 285
  AND bp.actual_value IS NOT NULL
  AND bp.projection_value IS NOT NULL
  AND bp.over_line IS NOT NULL
  AND pgs.innings_pitched >= 3.0
  AND pgs.rolling_stats_games >= 3
  AND pgs.game_date >= '2024-01-01'
ORDER BY bp.game_date
"""

df = client.query(query).to_dataframe()
df['game_date'] = pd.to_datetime(df['game_date'])
df = df.sort_values('game_date').reset_index(drop=True)

print(f"Loaded {len(df):,} samples")
print(f"Date range: {df['game_date'].min().date()} to {df['game_date'].max().date()}")
print()

# ============================================================================
# DEFINE FEATURES
# ============================================================================

features = [
    'f00_k_avg_last_3', 'f01_k_avg_last_5', 'f02_k_avg_last_10',
    'f03_k_std_last_10', 'f04_ip_avg_last_5',
    'f05_season_k_per_9', 'f06_season_era', 'f07_season_whip',
    'f08_season_games', 'f09_season_k_total',
    'f10_is_home', 'f15_opponent_team_k_rate', 'f16_ballpark_k_factor',
    'f17_month_of_season', 'f18_days_into_season',
    # SwStr% - LEADING INDICATORS (Season-level)
    'f19_season_swstr_pct', 'f19b_season_csw_pct', 'f19c_season_chase_pct',
    'f20_days_rest', 'f21_games_last_30_days', 'f22_pitch_count_avg',
    'f23_season_ip_total', 'f24_is_postseason',
    'f30_k_avg_vs_line', 'f32_line_level',
    'f40_bp_projection', 'f41_projection_diff',
    'f42_perf_last_5_pct', 'f43_perf_last_10_pct',
    'f44_over_implied_prob',
    # NEW: Rolling Statcast Features (BACKTEST VALIDATED)
    'f50_swstr_pct_last_3',   # Per-game SwStr% (last 3 starts)
    'f51_fb_velocity_last_3', # Fastball velocity (last 3 starts)
    'f52_swstr_trend',        # SwStr% trend: recent - season (hot/cold indicator)
    'f53_velocity_change',    # Velocity change: season - recent (drop = fatigue/injury)
]

available_features = [f for f in features if f in df.columns]

# Prepare feature matrix
X = df[available_features].copy()
for col in X.columns:
    X[col] = pd.to_numeric(X[col], errors='coerce')
X = X.fillna(X.median())

y = df['went_over'].copy().astype(int)

# ============================================================================
# WALK-FORWARD VALIDATION
# ============================================================================

print("=" * 80)
print("WALK-FORWARD VALIDATION")
print("=" * 80)
print()

# Create monthly periods
df['year_month'] = df['game_date'].dt.to_period('M')
periods = df['year_month'].unique()

print(f"Total periods: {len(periods)}")
print(f"Periods: {periods[0]} to {periods[-1]}")
print()

# XGBoost parameters
params = {
    'max_depth': 5,
    'learning_rate': 0.03,
    'n_estimators': 300,
    'min_child_weight': 5,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'gamma': 0.2,
    'reg_alpha': 0.5,
    'reg_lambda': 2,
    'random_state': 42,
    'objective': 'binary:logistic',
    'eval_metric': 'logloss',
    'early_stopping_rounds': 20,
}

# Track results
all_results = []
fold_results = []

print("Running walk-forward folds...")
print("-" * 80)
print(f"{'Fold':<6} {'Train Period':<25} {'Test Period':<15} {'Train':>6} {'Test':>6} {'Acc':>8} {'AUC':>8}")
print("-" * 80)

# Minimum training periods before we start testing
MIN_TRAIN_PERIODS = 3

for i in range(MIN_TRAIN_PERIODS, len(periods)):
    test_period = periods[i]
    train_periods = periods[:i]

    # Get train and test indices
    train_mask = df['year_month'].isin(train_periods)
    test_mask = df['year_month'] == test_period

    X_train = X[train_mask]
    y_train = y[train_mask]
    X_test = X[test_mask]
    y_test = y[test_mask]

    if len(X_test) < 10:
        continue

    # Use last month of training as validation
    val_period = train_periods[-1]
    val_mask = df['year_month'] == val_period
    X_val = X[val_mask]
    y_val = y[val_mask]

    # Train model
    model = xgb.XGBClassifier(**params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False
    )

    # Predict
    y_proba = model.predict_proba(X_test)[:, 1]
    y_pred = (y_proba > 0.5).astype(int)

    # Metrics
    acc = accuracy_score(y_test, y_pred)
    try:
        auc = roc_auc_score(y_test, y_proba)
    except:
        auc = 0.5

    # Store predictions with metadata
    test_df = df[test_mask].copy()
    test_df['predicted_proba'] = y_proba
    test_df['predicted'] = y_pred
    test_df['correct'] = (y_pred == y_test.values).astype(int)
    all_results.append(test_df)

    # Store fold summary
    fold_results.append({
        'fold': i - MIN_TRAIN_PERIODS + 1,
        'test_period': str(test_period),
        'train_samples': len(X_train),
        'test_samples': len(X_test),
        'accuracy': acc,
        'auc': auc,
        'over_rate': y_test.mean()
    })

    train_range = f"{train_periods[0]} to {train_periods[-1]}"
    print(f"{i-MIN_TRAIN_PERIODS+1:<6} {train_range:<25} {str(test_period):<15} {len(X_train):>6} {len(X_test):>6} {acc*100:>7.1f}% {auc:>7.3f}")

print("-" * 80)

# ============================================================================
# AGGREGATE RESULTS
# ============================================================================

print("\n" + "=" * 80)
print("AGGREGATE RESULTS")
print("=" * 80)

# Combine all predictions
all_predictions = pd.concat(all_results, ignore_index=True)

# Overall metrics
overall_acc = all_predictions['correct'].mean()
overall_samples = len(all_predictions)

print(f"\nTotal test samples across all folds: {overall_samples:,}")
print(f"Overall hit rate: {overall_acc*100:.2f}%")
print()

# By period breakdown
fold_df = pd.DataFrame(fold_results)
print("Per-fold breakdown:")
print(fold_df.to_string(index=False))
print()

# Statistics
print("\nSummary Statistics:")
print(f"  Mean accuracy:   {fold_df['accuracy'].mean()*100:.2f}%")
print(f"  Std accuracy:    {fold_df['accuracy'].std()*100:.2f}%")
print(f"  Min accuracy:    {fold_df['accuracy'].min()*100:.2f}%")
print(f"  Max accuracy:    {fold_df['accuracy'].max()*100:.2f}%")
print(f"  Mean AUC:        {fold_df['auc'].mean():.4f}")
print()

# ============================================================================
# CONFIDENCE TIER ANALYSIS (ACROSS ALL FOLDS)
# ============================================================================

print("=" * 80)
print("CONFIDENCE TIER ANALYSIS (All Folds Combined)")
print("=" * 80)

def analyze_tier(df, min_prob, max_prob, direction):
    if direction == 'over':
        mask = (df['predicted_proba'] >= min_prob) & (df['predicted_proba'] < max_prob)
        correct = df.loc[mask, 'went_over'].mean() if mask.sum() > 0 else np.nan
    else:
        mask = (df['predicted_proba'] <= (1 - min_prob)) & (df['predicted_proba'] > (1 - max_prob))
        correct = (1 - df.loc[mask, 'went_over']).mean() if mask.sum() > 0 else np.nan
    return mask.sum(), correct

print()
print(f"{'Tier':<30} {'Bets':>8} {'Hit Rate':>12} {'Edge':>10}")
print("-" * 65)

tiers = [
    ('ALL BETS', 0.0, 1.01, 'all'),
    ('High Conf OVER (>60%)', 0.60, 1.01, 'over'),
    ('High Conf UNDER (<40%)', 0.60, 1.01, 'under'),
    ('Very High OVER (>65%)', 0.65, 1.01, 'over'),
    ('Very High UNDER (<35%)', 0.65, 1.01, 'under'),
]

for tier_name, min_conf, max_conf, direction in tiers:
    if direction == 'all':
        count = len(all_predictions)
        hit_rate = all_predictions['correct'].mean()
    else:
        count, hit_rate = analyze_tier(all_predictions, min_conf, max_conf, direction)

    if count > 0 and not np.isnan(hit_rate):
        edge = (hit_rate - 0.5) * 100
        print(f"{tier_name:<30} {count:>8} {hit_rate*100:>11.1f}% {edge:>+9.1f}%")
    else:
        print(f"{tier_name:<30} {count:>8} {'N/A':>12} {'N/A':>10}")

print("-" * 65)

# Combined high confidence
high_conf_mask = (all_predictions['predicted_proba'] >= 0.60) | (all_predictions['predicted_proba'] <= 0.40)
high_conf = all_predictions[high_conf_mask]
if len(high_conf) > 0:
    print(f"\nCombined High Confidence (>60% or <40%):")
    print(f"  Total bets: {len(high_conf)}")
    print(f"  Hit rate: {high_conf['correct'].mean()*100:.1f}%")

# ============================================================================
# MONTH-BY-MONTH PERFORMANCE
# ============================================================================

print("\n" + "=" * 80)
print("MONTH-BY-MONTH PERFORMANCE")
print("=" * 80)

monthly = all_predictions.groupby('year_month').agg({
    'correct': ['mean', 'count'],
    'went_over': 'mean'
}).round(3)
monthly.columns = ['hit_rate', 'bets', 'actual_over_rate']
monthly['hit_rate'] = monthly['hit_rate'] * 100

print()
print(monthly.to_string())

# ============================================================================
# COMPARISON TO SINGLE SPLIT
# ============================================================================

print("\n" + "=" * 80)
print("COMPARISON: Walk-Forward vs Single Split")
print("=" * 80)

print("""
┌─────────────────────────┬────────────────┬────────────────┐
│ Metric                  │ Single Split   │ Walk-Forward   │
├─────────────────────────┼────────────────┼────────────────┤""")
print(f"│ Test Hit Rate           │ 65.35%         │ {overall_acc*100:.2f}%         │")
print(f"│ Total Test Samples      │ 889            │ {overall_samples:<14} │")
print(f"│ Std Dev Across Folds    │ N/A            │ {fold_df['accuracy'].std()*100:.2f}%          │")
print("""└─────────────────────────┴────────────────┴────────────────┘
""")

if overall_acc > 0.55:
    print("✓ Walk-forward validation confirms model has edge!")
elif overall_acc > 0.52:
    print("~ Model shows marginal edge, needs more validation")
else:
    print("✗ Walk-forward shows model doesn't generalize well")

print()
print("=" * 80)
print(" WALK-FORWARD VALIDATION COMPLETE")
print("=" * 80)

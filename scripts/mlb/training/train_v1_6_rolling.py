#!/usr/bin/env python3
"""
Train V1.6 Classifier with Rolling Statcast Features

This is the challenger model that adds per-game rolling features:
- f50_swstr_pct_last_3: Per-game SwStr% (last 3 starts)
- f51_fb_velocity_last_3: Fastball velocity (last 3 starts)
- f52_swstr_trend: SwStr% trend (recent - season)
- f53_velocity_change: Velocity change (season - recent)

Walk-forward validation results:
- Overall: 56.4% (+0.2% vs V1.5)
- Very High OVER: 63.6% (+1.1% vs V1.5)

Usage:
    PYTHONPATH=. python scripts/mlb/training/train_v1_6_rolling.py
"""

import os
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from google.cloud import bigquery
from sklearn.metrics import accuracy_score, roc_auc_score, log_loss

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models/mlb")
MODEL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 80)
print(" MLB PITCHER STRIKEOUT V1.6 CLASSIFIER")
print(" (With Rolling Statcast Features)")
print("=" * 80)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================================================
# STEP 1: LOAD TRAINING DATA WITH ROLLING FEATURES
# ============================================================================

print("=" * 80)
print("STEP 1: LOADING TRAINING DATA")
print("=" * 80)

client = bigquery.Client(project=PROJECT_ID)

query = """
WITH statcast_rolling AS (
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
),
bp_strikeouts AS (
    SELECT
        player_lookup,
        game_date,
        over_line,
        over_odds,
        under_odds,
        projection_value,
        actual_value,
        perf_last_5_over,
        perf_last_5_under,
        perf_last_10_over,
        perf_last_10_under
    FROM `mlb_raw.bp_pitcher_props`
    WHERE market_id = 285
      AND actual_value IS NOT NULL
),
pgs_normalized AS (
    SELECT
        player_lookup,
        LOWER(REGEXP_REPLACE(NORMALIZE(player_lookup, NFD), r'[\\W_]+', '')) as player_lookup_normalized,
        game_date,
        game_id,
        team_abbr,
        season_year,
        strikeouts,
        innings_pitched,
        is_home,
        is_postseason,
        days_rest,
        k_avg_last_3,
        k_avg_last_5,
        k_avg_last_10,
        k_std_last_10,
        ip_avg_last_5,
        season_k_per_9,
        era_rolling_10,
        whip_rolling_10,
        season_games_started,
        season_strikeouts,
        season_innings,
        season_swstr_pct,
        season_csw_pct,
        season_chase_pct,
        opponent_team_k_rate,
        ballpark_k_factor,
        month_of_season,
        days_into_season,
        games_last_30_days,
        pitch_count_avg_last_5,
        data_completeness_score,
        rolling_stats_games
    FROM `mlb_analytics.pitcher_game_summary`
    WHERE game_date >= '2024-01-01'
      AND game_date <= '2025-12-31'
      AND strikeouts IS NOT NULL
      AND innings_pitched >= 3.0
      AND rolling_stats_games >= 3
)

SELECT
    pgs.player_lookup,
    pgs.game_date,
    pgs.game_id,
    pgs.team_abbr,
    pgs.season_year,

    -- Actual result
    pgs.strikeouts as actual_strikeouts,
    bp.over_line as betting_line,
    CASE WHEN pgs.strikeouts > bp.over_line THEN 1 ELSE 0 END as went_over,

    -- Features: Recent K performance
    COALESCE(pgs.k_avg_last_3, 5.0) as f00_k_avg_last_3,
    COALESCE(pgs.k_avg_last_5, 5.0) as f01_k_avg_last_5,
    COALESCE(pgs.k_avg_last_10, 5.0) as f02_k_avg_last_10,
    COALESCE(pgs.k_std_last_10, 2.0) as f03_k_std_last_10,
    COALESCE(pgs.ip_avg_last_5, 5.5) as f04_ip_avg_last_5,

    -- Features: Season baseline
    COALESCE(pgs.season_k_per_9, 8.5) as f05_season_k_per_9,
    COALESCE(pgs.era_rolling_10, 4.0) as f06_season_era,
    COALESCE(pgs.whip_rolling_10, 1.3) as f07_season_whip,
    COALESCE(pgs.season_games_started, 5) as f08_season_games,
    COALESCE(pgs.season_strikeouts, 30) as f09_season_k_total,

    -- Features: Context
    IF(pgs.is_home, 1.0, 0.0) as f10_is_home,
    COALESCE(pgs.opponent_team_k_rate, 0.22) as f15_opponent_team_k_rate,
    COALESCE(pgs.ballpark_k_factor, 1.0) as f16_ballpark_k_factor,
    COALESCE(pgs.month_of_season, 6) as f17_month_of_season,
    COALESCE(pgs.days_into_season, 90) as f18_days_into_season,

    -- Features: Season SwStr%
    COALESCE(pgs.season_swstr_pct, 0.105) as f19_season_swstr_pct,
    COALESCE(pgs.season_csw_pct, 0.29) as f19b_season_csw_pct,
    COALESCE(pgs.season_chase_pct, 0.30) as f19c_season_chase_pct,

    -- Features: Workload
    COALESCE(pgs.days_rest, 5) as f20_days_rest,
    pgs.games_last_30_days as f21_games_last_30_days,
    COALESCE(pgs.pitch_count_avg_last_5, 90.0) as f22_pitch_count_avg,
    COALESCE(pgs.season_innings, 50.0) as f23_season_ip_total,
    IF(pgs.is_postseason, 1.0, 0.0) as f24_is_postseason,

    -- Features: Line-relative
    (COALESCE(pgs.k_avg_last_5, 5.0) - bp.over_line) as f30_k_avg_vs_line,
    ((COALESCE(pgs.season_k_per_9, 8.5) / 9.0) * COALESCE(pgs.ip_avg_last_5, 5.5) - bp.over_line) as f31_projected_vs_line,
    bp.over_line as f32_line_level,

    -- Features: BettingPros
    bp.projection_value as f40_bp_projection,
    (bp.projection_value - bp.over_line) as f41_projection_diff,
    SAFE_DIVIDE(bp.perf_last_5_over, (bp.perf_last_5_over + bp.perf_last_5_under)) as f42_perf_last_5_pct,
    SAFE_DIVIDE(bp.perf_last_10_over, (bp.perf_last_10_over + bp.perf_last_10_under)) as f43_perf_last_10_pct,
    CASE
        WHEN bp.over_odds < 0 THEN ABS(bp.over_odds) / (ABS(bp.over_odds) + 100.0)
        ELSE 100.0 / (bp.over_odds + 100.0)
    END as f44_over_implied_prob,

    -- NEW V1.6: Rolling Statcast Features
    COALESCE(sc.swstr_pct_last_3, pgs.season_swstr_pct, 0.105) as f50_swstr_pct_last_3,
    COALESCE(sc.fb_velocity_last_3, 93.0) as f51_fb_velocity_last_3,
    COALESCE(sc.swstr_pct_last_3 - sc.swstr_pct_season_prior, 0.0) as f52_swstr_trend,
    COALESCE(sc.fb_velocity_season_prior - sc.fb_velocity_last_3, 0.0) as f53_velocity_change,

    -- Data quality
    pgs.data_completeness_score,
    pgs.rolling_stats_games

FROM pgs_normalized pgs
JOIN bp_strikeouts bp
    ON bp.player_lookup = pgs.player_lookup_normalized
    AND bp.game_date = pgs.game_date
LEFT JOIN statcast_rolling sc
    ON REPLACE(pgs.player_lookup, '_', '') = REPLACE(sc.player_lookup, '_', '')
    AND pgs.game_date = sc.game_date
WHERE bp.over_line IS NOT NULL
  AND bp.projection_value IS NOT NULL
ORDER BY pgs.game_date, pgs.player_lookup
"""

print("Fetching data from BigQuery...")
df = client.query(query).to_dataframe()

print(f"Loaded {len(df):,} samples")
print(f"  Date range: {df['game_date'].min()} to {df['game_date'].max()}")
print(f"  Over rate: {df['went_over'].mean()*100:.1f}%")
print(f"  Avg line: {df['betting_line'].mean():.2f}")
print()

# Check rolling feature coverage
rolling_coverage = df['f52_swstr_trend'].notna().mean() * 100
print(f"  Rolling features coverage: {rolling_coverage:.1f}%")
print()

# ============================================================================
# STEP 2: PREPARE FEATURES
# ============================================================================

print("=" * 80)
print("STEP 2: PREPARING FEATURES")
print("=" * 80)

features = [
    # Recent K performance
    'f00_k_avg_last_3', 'f01_k_avg_last_5', 'f02_k_avg_last_10',
    'f03_k_std_last_10', 'f04_ip_avg_last_5',
    # Season baseline
    'f05_season_k_per_9', 'f06_season_era', 'f07_season_whip',
    'f08_season_games', 'f09_season_k_total',
    # Context
    'f10_is_home', 'f15_opponent_team_k_rate', 'f16_ballpark_k_factor',
    'f17_month_of_season', 'f18_days_into_season',
    # Season SwStr%
    'f19_season_swstr_pct', 'f19b_season_csw_pct', 'f19c_season_chase_pct',
    # Workload
    'f20_days_rest', 'f21_games_last_30_days', 'f22_pitch_count_avg',
    'f23_season_ip_total', 'f24_is_postseason',
    # Line-relative
    'f30_k_avg_vs_line', 'f31_projected_vs_line', 'f32_line_level',
    # BettingPros
    'f40_bp_projection', 'f41_projection_diff',
    'f42_perf_last_5_pct', 'f43_perf_last_10_pct',
    'f44_over_implied_prob',
    # NEW V1.6: Rolling Statcast
    'f50_swstr_pct_last_3', 'f51_fb_velocity_last_3',
    'f52_swstr_trend', 'f53_velocity_change',
]

available_features = [f for f in features if f in df.columns]
print(f"Using {len(available_features)} features (4 new rolling features)")

target = 'went_over'

# ============================================================================
# STEP 3: CHRONOLOGICAL TRAIN/VAL/TEST SPLIT
# ============================================================================

print("=" * 80)
print("STEP 3: CHRONOLOGICAL TRAIN/VAL/TEST SPLIT")
print("=" * 80)

df_sorted = df.sort_values('game_date').reset_index(drop=True)
n = len(df_sorted)

train_end = int(n * 0.70)
val_end = int(n * 0.85)

X = df_sorted[available_features].copy()
y = df_sorted[target].copy()

for col in X.columns:
    X[col] = pd.to_numeric(X[col], errors='coerce')
X = X.fillna(X.median())
y = y.fillna(0).astype(int)

print(f"Feature matrix: {X.shape}")
print(f"Target distribution: {y.value_counts().to_dict()}")
print()

train_idx = list(range(0, train_end))
val_idx = list(range(train_end, val_end))
test_idx = list(range(val_end, n))

X_train, y_train = X.iloc[train_idx], y.iloc[train_idx]
X_val, y_val = X.iloc[val_idx], y.iloc[val_idx]
X_test, y_test = X.iloc[test_idx], y.iloc[test_idx]

test_df = df_sorted.iloc[test_idx].copy()

print(f"Training:   {len(X_train):,} samples ({df_sorted.iloc[train_idx]['game_date'].min()} to {df_sorted.iloc[train_idx]['game_date'].max()})")
print(f"Validation: {len(X_val):,} samples")
print(f"Test:       {len(X_test):,} samples ({df_sorted.iloc[test_idx]['game_date'].min()} to {df_sorted.iloc[test_idx]['game_date'].max()})")
print()

# ============================================================================
# STEP 4: TRAIN XGBOOST CLASSIFIER
# ============================================================================

print("=" * 80)
print("STEP 4: TRAINING XGBOOST CLASSIFIER")
print("=" * 80)

params = {
    'max_depth': 5,
    'learning_rate': 0.03,
    'n_estimators': 500,
    'min_child_weight': 5,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'gamma': 0.2,
    'reg_alpha': 0.5,
    'reg_lambda': 2,
    'random_state': 42,
    'objective': 'binary:logistic',
    'eval_metric': 'logloss',
    'early_stopping_rounds': 30,
    'scale_pos_weight': 1.0,
}

print("Training XGBoost Classifier...")
model = xgb.XGBClassifier(**params)
model.fit(
    X_train, y_train,
    eval_set=[(X_val, y_val)],
    verbose=50
)
print()

# ============================================================================
# STEP 5: EVALUATE MODEL
# ============================================================================

print("=" * 80)
print("STEP 5: MODEL EVALUATION")
print("=" * 80)

test_proba = model.predict_proba(X_test)[:, 1]
test_pred = (test_proba > 0.5).astype(int)

test_acc = accuracy_score(y_test, test_pred)
test_auc = roc_auc_score(y_test, test_proba)
test_ll = log_loss(y_test, test_proba)

print(f"\nTest Results:")
print(f"  Accuracy (Hit Rate): {test_acc*100:.2f}%")
print(f"  AUC-ROC: {test_auc:.4f}")
print(f"  Log Loss: {test_ll:.4f}")

# Confidence tier analysis
test_df['prob_over'] = test_proba
test_df['correct'] = (test_pred == y_test.values).astype(int)

print("\nConfidence Tier Analysis:")
print("-" * 60)

# High confidence OVER
high_over = test_df[test_df['prob_over'] >= 0.60]
if len(high_over) > 0:
    hit_rate = high_over['went_over'].mean()
    print(f"High Conf OVER (>60%): {len(high_over)} bets, {hit_rate*100:.1f}% hit rate")

# Very high confidence OVER
very_high = test_df[test_df['prob_over'] >= 0.65]
if len(very_high) > 0:
    hit_rate = very_high['went_over'].mean()
    print(f"Very High OVER (>65%): {len(very_high)} bets, {hit_rate*100:.1f}% hit rate")

# High confidence UNDER
high_under = test_df[test_df['prob_over'] <= 0.40]
if len(high_under) > 0:
    hit_rate = (1 - high_under['went_over']).mean()
    print(f"High Conf UNDER (<40%): {len(high_under)} bets, {hit_rate*100:.1f}% hit rate")

# ============================================================================
# STEP 6: FEATURE IMPORTANCE
# ============================================================================

print("\n" + "=" * 80)
print("STEP 6: FEATURE IMPORTANCE (Top 15)")
print("=" * 80)

importance = model.feature_importances_
feat_imp = pd.DataFrame({
    'feature': available_features,
    'importance': importance
}).sort_values('importance', ascending=False)

for i, (_, row) in enumerate(feat_imp.head(15).iterrows()):
    marker = "NEW" if row['feature'].startswith('f5') else "   "
    print(f"  {marker} {row['feature']:30s} {row['importance']*100:5.1f}%")

# ============================================================================
# STEP 7: SAVE MODEL
# ============================================================================

print("\n" + "=" * 80)
print("STEP 7: SAVING MODEL")
print("=" * 80)

model_id = f"mlb_pitcher_strikeouts_v1_6_rolling_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
model_path = MODEL_OUTPUT_DIR / f"{model_id}.json"

model.get_booster().save_model(str(model_path))
print(f"Model saved: {model_path}")

# Save metadata
metadata = {
    'model_id': model_id,
    'model_type': 'classifier',
    'version': 'v1.6-rolling',
    'description': 'V1.6 Challenger with rolling statcast features (SwStr% trend, velocity)',
    'trained_at': datetime.now().isoformat(),
    'samples': len(df),
    'features': available_features,
    'feature_count': len(available_features),
    'new_features': ['f50_swstr_pct_last_3', 'f51_fb_velocity_last_3', 'f52_swstr_trend', 'f53_velocity_change'],
    'test_accuracy': test_acc,
    'test_auc': test_auc,
    'test_log_loss': test_ll,
    'test_samples': len(test_df),
    'rolling_feature_coverage': rolling_coverage,
    'hyperparameters': {k: v for k, v in params.items() if k != 'early_stopping_rounds'},
    'walk_forward_results': {
        'overall_hit_rate': 0.5636,
        'very_high_over_hit_rate': 0.636,
        'high_conf_over_hit_rate': 0.615,
    }
}

metadata_path = MODEL_OUTPUT_DIR / f"{model_id}_metadata.json"
with open(metadata_path, 'w') as f:
    json.dump(metadata, f, indent=2, default=str)

print(f"Metadata saved: {metadata_path}")

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 80)
print(" V1.6 CHALLENGER TRAINING COMPLETE")
print("=" * 80)
print()
print(f"Model: {model_id}")
print(f"Test Hit Rate: {test_acc*100:.2f}%")
print(f"Test AUC-ROC: {test_auc:.4f}")
print(f"New Features: 4 rolling statcast features")
print()
print("Next steps:")
print("  1. Upload to GCS: gsutil cp {model_path} gs://nba-scraped-data/ml-models/mlb/")
print("  2. Set env var: MLB_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/{model_id}.json")
print("  3. Monitor in production as challenger")
print()

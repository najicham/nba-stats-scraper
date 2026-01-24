#!/usr/bin/env python3
"""
Train Classification Model for MLB Pitcher Strikeout Over/Under

Instead of predicting K count (regression) and deriving over/under,
this model directly predicts the over/under outcome (classification).

Hypothesis: The task IS over/under, so direct classification might:
1. Better learn the decision boundary around the line
2. Provide well-calibrated probabilities for confidence filtering
3. Avoid regression errors that don't matter (7 K vs 12 K both = over)

Usage:
    PYTHONPATH=. python scripts/mlb/training/train_pitcher_strikeouts_classifier.py
"""

import logging
import os
import sys
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from google.cloud import bigquery
from sklearn.metrics import (
    accuracy_score, log_loss, roc_auc_score,
    precision_score, recall_score, f1_score,
    classification_report, confusion_matrix
)
from sklearn.calibration import calibration_curve

logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models/mlb")
MODEL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logger.info("=" * 80)
logger.info(" MLB PITCHER STRIKEOUT CLASSIFIER")
logger.info(" (Direct Over/Under Prediction)")
logger.info("=" * 80)
logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
logger.info("")

# ============================================================================
# STEP 1: LOAD TRAINING DATA
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 1: LOADING TRAINING DATA")
logger.info("=" * 80)

client = bigquery.Client(project=PROJECT_ID)

query = """
WITH bp_strikeouts AS (
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
        perf_last_10_under,
        perf_season_over,
        perf_season_under
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
        opponent_team_abbr,
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
        home_away_k_diff,
        day_night_k_diff,
        opponent_team_k_rate,
        ballpark_k_factor,
        month_of_season,
        days_into_season,
        games_last_30_days,
        pitch_count_avg_last_5,
        data_completeness_score,
        rolling_stats_games
    FROM `mlb_analytics.pitcher_game_summary`
    WHERE game_date >= '2022-04-01'
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

    -- Actual result (for target)
    pgs.strikeouts as actual_strikeouts,
    bp.over_line as betting_line,

    -- CLASSIFICATION TARGET: Did actual go over the line?
    CASE WHEN pgs.strikeouts > bp.over_line THEN 1 ELSE 0 END as went_over,

    -- Features for classification
    -- f00-f04: Recent K performance
    COALESCE(pgs.k_avg_last_3, 5.0) as f00_k_avg_last_3,
    COALESCE(pgs.k_avg_last_5, 5.0) as f01_k_avg_last_5,
    COALESCE(pgs.k_avg_last_10, 5.0) as f02_k_avg_last_10,
    COALESCE(pgs.k_std_last_10, 2.0) as f03_k_std_last_10,
    COALESCE(pgs.ip_avg_last_5, 5.5) as f04_ip_avg_last_5,

    -- f05-f09: Season baseline
    COALESCE(pgs.season_k_per_9, 8.5) as f05_season_k_per_9,
    COALESCE(pgs.era_rolling_10, 4.0) as f06_season_era,
    COALESCE(pgs.whip_rolling_10, 1.3) as f07_season_whip,
    COALESCE(pgs.season_games_started, 5) as f08_season_games,
    COALESCE(pgs.season_strikeouts, 30) as f09_season_k_total,

    -- f10-f18: Context
    IF(pgs.is_home, 1.0, 0.0) as f10_is_home,
    COALESCE(pgs.home_away_k_diff, 0.0) as f11_home_away_k_diff,
    COALESCE(pgs.day_night_k_diff, 0.0) as f13_day_night_k_diff,
    COALESCE(pgs.opponent_team_k_rate, 0.22) as f15_opponent_team_k_rate,
    COALESCE(pgs.ballpark_k_factor, 1.0) as f16_ballpark_k_factor,
    COALESCE(pgs.month_of_season, 6) as f17_month_of_season,
    COALESCE(pgs.days_into_season, 90) as f18_days_into_season,

    -- f19: SwStr% - LEADING INDICATOR!
    COALESCE(pgs.season_swstr_pct, 0.105) as f19_season_swstr_pct,
    COALESCE(pgs.season_csw_pct, 0.29) as f19b_season_csw_pct,
    COALESCE(pgs.season_chase_pct, 0.30) as f19c_season_chase_pct,

    -- f20-f24: Workload
    COALESCE(pgs.days_rest, 5) as f20_days_rest,
    pgs.games_last_30_days as f21_games_last_30_days,
    COALESCE(pgs.pitch_count_avg_last_5, 90.0) as f22_pitch_count_avg,
    COALESCE(pgs.season_innings, 50.0) as f23_season_ip_total,
    IF(pgs.is_postseason, 1.0, 0.0) as f24_is_postseason,

    -- NEW: Line-relative features (key for classification!)
    -- f30: How far is recent K avg from the line?
    (COALESCE(pgs.k_avg_last_5, 5.0) - bp.over_line) as f30_k_avg_vs_line,

    -- f31: How far is season K/9 projected to line?
    ((COALESCE(pgs.season_k_per_9, 8.5) / 9.0) * COALESCE(pgs.ip_avg_last_5, 5.5) - bp.over_line) as f31_projected_vs_line,

    -- f32: Line level itself (different dynamics for high vs low lines)
    bp.over_line as f32_line_level,

    -- BettingPros features
    bp.projection_value as f40_bp_projection,
    (bp.projection_value - bp.over_line) as f41_projection_diff,
    SAFE_DIVIDE(bp.perf_last_5_over, (bp.perf_last_5_over + bp.perf_last_5_under)) as f42_perf_last_5_pct,
    SAFE_DIVIDE(bp.perf_last_10_over, (bp.perf_last_10_over + bp.perf_last_10_under)) as f43_perf_last_10_pct,

    -- Implied probability from odds
    CASE
        WHEN bp.over_odds < 0 THEN ABS(bp.over_odds) / (ABS(bp.over_odds) + 100.0)
        ELSE 100.0 / (bp.over_odds + 100.0)
    END as f44_over_implied_prob,

    -- Data quality
    pgs.data_completeness_score,
    pgs.rolling_stats_games

FROM pgs_normalized pgs
JOIN bp_strikeouts bp
    ON bp.player_lookup = pgs.player_lookup_normalized
    AND bp.game_date = pgs.game_date
WHERE bp.over_line IS NOT NULL
  AND bp.projection_value IS NOT NULL
ORDER BY pgs.game_date, pgs.player_lookup
"""

logger.info("Fetching data from BigQuery...")
df = client.query(query).to_dataframe()

logger.info(f"Loaded {len(df):,} samples")
logger.info(f"  Date range: {df['game_date'].min()} to {df['game_date'].max()}")
logger.info(f"  Over rate: {df['went_over'].mean()*100:.1f}%")
logger.info(f"  Avg line: {df['betting_line'].mean():.2f}")
logger.info("")

# ============================================================================
# STEP 2: PREPARE FEATURES
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 2: PREPARING FEATURES")
logger.info("=" * 80)

# All features (including new line-relative features)
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
    # SwStr% - LEADING INDICATOR
    'f19_season_swstr_pct', 'f19b_season_csw_pct', 'f19c_season_chase_pct',
    # Workload
    'f20_days_rest', 'f21_games_last_30_days', 'f22_pitch_count_avg',
    'f23_season_ip_total', 'f24_is_postseason',
    # NEW: Line-relative (key for classification!)
    'f30_k_avg_vs_line', 'f31_projected_vs_line', 'f32_line_level',
    # BettingPros
    'f40_bp_projection', 'f41_projection_diff',
    'f42_perf_last_5_pct', 'f43_perf_last_10_pct',
    'f44_over_implied_prob',
]

available_features = [f for f in features if f in df.columns]
logger.info(f"Using {len(available_features)} features")

# Target: binary over/under
target = 'went_over'

# ============================================================================
# STEP 3: CHRONOLOGICAL TRAIN/VAL/TEST SPLIT
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 3: CHRONOLOGICAL TRAIN/VAL/TEST SPLIT")
logger.info("=" * 80)

# IMPORTANT: Sort FIRST, then create X and y from sorted data
df_sorted = df.sort_values('game_date').reset_index(drop=True)
n = len(df_sorted)

train_end = int(n * 0.70)
val_end = int(n * 0.85)

# Create X and y from sorted dataframe
X = df_sorted[available_features].copy()
y = df_sorted[target].copy()

# Convert to numeric and fill NaN
for col in X.columns:
    X[col] = pd.to_numeric(X[col], errors='coerce')
X = X.fillna(X.median())
y = y.fillna(0).astype(int)

logger.info(f"Feature matrix: {X.shape}")
logger.info(f"Target distribution: {y.value_counts().to_dict()}")
logger.info("")

# Split indices
train_idx = list(range(0, train_end))
val_idx = list(range(train_end, val_end))
test_idx = list(range(val_end, n))

X_train, y_train = X.iloc[train_idx], y.iloc[train_idx]
X_val, y_val = X.iloc[val_idx], y.iloc[val_idx]
X_test, y_test = X.iloc[test_idx], y.iloc[test_idx]

test_df = df_sorted.iloc[test_idx].copy()

logger.info(f"Training:   {len(X_train):,} samples ({df_sorted.iloc[train_idx]['game_date'].min()} to {df_sorted.iloc[train_idx]['game_date'].max()})")
logger.info(f"Validation: {len(X_val):,} samples")
logger.info(f"Test:       {len(X_test):,} samples ({df_sorted.iloc[test_idx]['game_date'].min()} to {df_sorted.iloc[test_idx]['game_date'].max()})")
logger.info("")
logger.info(f"Train over rate: {y_train.mean()*100:.1f}%")
logger.info(f"Test over rate:  {y_test.mean()*100:.1f}%")
logger.info("")

# ============================================================================
# STEP 4: TRAIN XGBOOST CLASSIFIER
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 4: TRAINING XGBOOST CLASSIFIER")
logger.info("=" * 80)

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
    'scale_pos_weight': 1.0,  # Balanced classes
}

logger.info("Training XGBoost Classifier...")
model = xgb.XGBClassifier(**params)
model.fit(
    X_train, y_train,
    eval_set=[(X_val, y_val)],
    verbose=50
)
logger.info("")

# ============================================================================
# STEP 5: EVALUATE MODEL
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 5: MODEL EVALUATION")
logger.info("=" * 80)

# Get predictions and probabilities
train_proba = model.predict_proba(X_train)[:, 1]
val_proba = model.predict_proba(X_val)[:, 1]
test_proba = model.predict_proba(X_test)[:, 1]

train_pred = (train_proba > 0.5).astype(int)
val_pred = (val_proba > 0.5).astype(int)
test_pred = (test_proba > 0.5).astype(int)

def evaluate_classifier(y_true, y_pred, y_proba, name):
    acc = accuracy_score(y_true, y_pred)
    auc = roc_auc_score(y_true, y_proba)
    ll = log_loss(y_true, y_proba)

    logger.info(f"{name}:")
    logger.info(f"  Accuracy (Hit Rate): {acc*100:.2f}%")
    logger.info(f"  AUC-ROC: {auc:.4f}")
    logger.info(f"  Log Loss: {ll:.4f}")

    return {'accuracy': acc, 'auc': auc, 'log_loss': ll}

train_metrics = evaluate_classifier(y_train, train_pred, train_proba, "Training")
val_metrics = evaluate_classifier(y_val, val_pred, val_proba, "Validation")
test_metrics = evaluate_classifier(y_test, test_pred, test_proba, "Test")

# ============================================================================
# STEP 6: CONFIDENCE-BASED ANALYSIS
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 6: CONFIDENCE-BASED BETTING ANALYSIS")
logger.info("=" * 80)

test_df['prob_over'] = test_proba
test_df['pred_over'] = test_pred
test_df['correct'] = (test_df['pred_over'] == test_df['went_over']).astype(int)

# Analyze by confidence tiers
def analyze_confidence_tier(df, prob_col, min_conf, max_conf, direction):
    """Analyze hit rate for a confidence tier"""
    if direction == 'over':
        mask = (df[prob_col] >= min_conf) & (df[prob_col] < max_conf)
        correct = df.loc[mask, 'went_over'].mean() if mask.sum() > 0 else np.nan
    else:  # under
        mask = (df[prob_col] <= (1 - min_conf)) & (df[prob_col] > (1 - max_conf))
        correct = (1 - df.loc[mask, 'went_over']).mean() if mask.sum() > 0 else np.nan

    return mask.sum(), correct

logger.info("Confidence Tier Analysis:")
logger.info("-" * 70)
logger.info(f"{'Tier':<25} {'Bets':>8} {'Hit Rate':>12} {'Edge':>10}")
logger.info("-" * 70)

tiers = [
    ('ALL BETS', 0.0, 1.01, 'all'),
    ('High Conf OVER (>60%)', 0.60, 1.01, 'over'),
    ('High Conf UNDER (<40%)', 0.60, 1.01, 'under'),
    ('Very High OVER (>65%)', 0.65, 1.01, 'over'),
    ('Very High UNDER (<35%)', 0.65, 1.01, 'under'),
    ('Elite OVER (>70%)', 0.70, 1.01, 'over'),
    ('Elite UNDER (<30%)', 0.70, 1.01, 'under'),
]

for tier_name, min_conf, max_conf, direction in tiers:
    if direction == 'all':
        count = len(test_df)
        hit_rate = test_df['correct'].mean()
    else:
        count, hit_rate = analyze_confidence_tier(test_df, 'prob_over', min_conf, max_conf, direction)

    if count > 0 and not np.isnan(hit_rate):
        edge = (hit_rate - 0.5) * 100
        logger.info(f"{tier_name:<25} {count:>8} {hit_rate*100:>11.1f}% {edge:>+9.1f}%")
    else:
        logger.info(f"{tier_name:<25} {count:>8} {'N/A':>12} {'N/A':>10}")

logger.info("-" * 70)

# Combined high confidence (either direction)
high_conf_mask = (test_df['prob_over'] >= 0.60) | (test_df['prob_over'] <= 0.40)
high_conf_df = test_df[high_conf_mask]
if len(high_conf_df) > 0:
    high_conf_hit = high_conf_df['correct'].mean()
    logger.info(f"Combined High Confidence (P>60% or P<40%):")
    logger.info(f"  Bets: {len(high_conf_df)}")
    logger.info(f"  Hit Rate: {high_conf_hit*100:.1f}%")
    logger.info(f"  Edge: {(high_conf_hit - 0.5)*100:+.1f}%")

# ============================================================================
# STEP 7: PROBABILITY CALIBRATION CHECK
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 7: PROBABILITY CALIBRATION")
logger.info("=" * 80)

# Check if probabilities are well-calibrated
prob_bins = [0, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0]
test_df['prob_bin'] = pd.cut(test_df['prob_over'], bins=prob_bins)

logger.info("Calibration by probability bin:")
logger.info("-" * 50)
logger.info(f"{'Prob Bin':<15} {'Count':>8} {'Actual Over%':>15} {'Diff':>10}")
logger.info("-" * 50)

for bin_label in test_df['prob_bin'].unique():
    if pd.isna(bin_label):
        continue
    bin_df = test_df[test_df['prob_bin'] == bin_label]
    if len(bin_df) > 10:
        actual_rate = bin_df['went_over'].mean()
        expected_rate = bin_df['prob_over'].mean()
        diff = (actual_rate - expected_rate) * 100
        logger.info(f"{str(bin_label):<15} {len(bin_df):>8} {actual_rate*100:>14.1f}% {diff:>+9.1f}%")

# ============================================================================
# STEP 8: FEATURE IMPORTANCE
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 8: FEATURE IMPORTANCE")
logger.info("=" * 80)

importance = model.feature_importances_
feat_imp = pd.DataFrame({
    'feature': available_features,
    'importance': importance
}).sort_values('importance', ascending=False)

logger.info("Top 15 Features:")
for i, (_, row) in enumerate(feat_imp.head(15).iterrows()):
    bar = '*' * int(row['importance'] * 50)
    logger.info(f"  {row['feature']:30s} {row['importance']*100:5.1f}% {bar}")

# ============================================================================
# STEP 9: COMPARE WITH REGRESSION BASELINE
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 9: COMPARISON WITH V1.5 REGRESSION")
logger.info("=" * 80)

logger.info("Comparison Summary:")
logger.info("+-----------------+----------------+----------------+")
logger.info("| Metric              | V1.5 Regressor | Classifier     |")
logger.info("+-----------------+----------------+----------------+")
logger.info(f"| Test Hit Rate       | 52.98%         | {test_metrics['accuracy']*100:.2f}%         |")
logger.info(f"| Test AUC            | N/A            | {test_metrics['auc']:.4f}         |")
logger.info("+-----------------+----------------+----------------+")
logger.info("")
logger.info("Key advantages of classifier:")
logger.info("1. Direct probability output for confidence filtering")
logger.info("2. Optimizes for the actual task (O/U classification)")
logger.info("3. Can apply different thresholds for over vs under")
logger.info("")

# ============================================================================
# STEP 10: SAVE MODEL
# ============================================================================

logger.info("=" * 80)
logger.info("STEP 10: SAVING MODEL")
logger.info("=" * 80)

model_id = f"mlb_pitcher_strikeouts_classifier_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
model_path = MODEL_OUTPUT_DIR / f"{model_id}.json"

model.get_booster().save_model(str(model_path))
logger.info(f"Model saved: {model_path}")

# Save metadata
metadata = {
    'model_id': model_id,
    'model_type': 'classifier',
    'version': '2.0-classifier',
    'description': 'Direct O/U classification instead of K regression',
    'trained_at': datetime.now().isoformat(),
    'samples': len(df),
    'features': available_features,
    'test_accuracy': test_metrics['accuracy'],
    'test_auc': test_metrics['auc'],
    'test_log_loss': test_metrics['log_loss'],
    'test_samples': len(test_df),
    'hyperparameters': {k: v for k, v in params.items() if k != 'early_stopping_rounds'}
}

metadata_path = MODEL_OUTPUT_DIR / f"{model_id}_metadata.json"
with open(metadata_path, 'w') as f:
    json.dump(metadata, f, indent=2, default=str)

logger.info(f"Metadata saved: {metadata_path}")

# ============================================================================
# SUMMARY
# ============================================================================

logger.info("=" * 80)
logger.info(" CLASSIFIER TRAINING COMPLETE")
logger.info("=" * 80)
logger.info("")
logger.info(f"Model: {model_id}")
logger.info(f"Test Hit Rate: {test_metrics['accuracy']*100:.2f}%")
logger.info(f"Test AUC-ROC: {test_metrics['auc']:.4f}")
logger.info("")

if test_metrics['accuracy'] > 0.54:
    logger.info("Classifier shows improvement over baseline!")
elif test_metrics['accuracy'] > 0.52:
    logger.info("Classifier comparable to regression baseline")
else:
    logger.info("Classifier underperforms - regression may be better")

logger.info("")
logger.info("Next steps:")
logger.info("  1. Compare with V1.5 regression on identical test set")
logger.info("  2. Test different confidence thresholds")
logger.info("  3. Try ensemble of classifier + regressor")
logger.info("")

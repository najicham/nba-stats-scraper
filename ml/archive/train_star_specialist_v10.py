#!/usr/bin/env python3
"""
Star Specialist Models v10

Hypothesis: Stars (20+ ppg) have higher variance and may benefit from
specialized models trained only on star player data.

Approaches tested:
1. Tier-based models (Star, Starter, Role, Bench)
2. Individual player models for top 30 scorers
3. Star-specific ensemble with different hyperparameters

Usage:
    PYTHONPATH=. python ml/train_star_specialist_v10.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import json
from datetime import datetime
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
from sklearn.linear_model import Ridge
import catboost as cb
import warnings
warnings.filterwarnings('ignore')

PROJECT_ID = "nba-props-platform"

print("=" * 80)
print(" STAR SPECIALIST MODELS V10")
print("=" * 80)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

client = bigquery.Client(project=PROJECT_ID)

# ============================================================================
# STEP 1: LOAD ALL DATA
# ============================================================================

print("=" * 80)
print("STEP 1: LOADING DATA")
print("=" * 80)

query = """
WITH
feature_data AS (
  SELECT mf.player_lookup, mf.game_date, mf.features, mf.opponent_team_abbr
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
  WHERE mf.game_date BETWEEN '2021-11-01' AND '2026-01-08'
    AND mf.feature_count = 25 AND ARRAY_LENGTH(mf.features) = 25
),
vegas_lines AS (
  SELECT game_date, player_lookup, points_line as vegas_points_line,
         opening_line as vegas_opening_line, (points_line - opening_line) as vegas_line_move
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE bookmaker = 'BettingPros Consensus' AND bet_side = 'over'
    AND game_date BETWEEN '2021-11-01' AND '2026-01-08'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup ORDER BY processed_at DESC) = 1
),
opponent_history AS (
  SELECT pgs1.player_lookup, pgs1.game_date,
         AVG(pgs2.points) as avg_points_vs_opponent, COUNT(pgs2.points) as games_vs_opponent
  FROM `nba-props-platform.nba_analytics.player_game_summary` pgs1
  LEFT JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs2
    ON pgs1.player_lookup = pgs2.player_lookup
    AND pgs1.opponent_team_abbr = pgs2.opponent_team_abbr
    AND pgs2.game_date < pgs1.game_date
    AND pgs2.game_date >= DATE_SUB(pgs1.game_date, INTERVAL 3 YEAR)
    AND pgs2.points IS NOT NULL
  WHERE pgs1.game_date BETWEEN '2021-11-01' AND '2026-01-08'
  GROUP BY pgs1.player_lookup, pgs1.game_date, pgs1.opponent_team_abbr
),
-- Calculate player career averages for tier assignment
player_career_avg AS (
  SELECT
    player_lookup,
    AVG(points) as career_ppg,
    COUNT(*) as career_games
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN '2021-11-01' AND '2024-06-01'  -- Use training period for tier assignment
    AND points IS NOT NULL AND minutes_played > 10
  GROUP BY player_lookup
  HAVING COUNT(*) >= 20  -- At least 20 games
),
actuals AS (
  SELECT player_lookup, game_date, points as actual_points,
         AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date
                          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) as player_season_avg,
         AVG(minutes_played) OVER (PARTITION BY player_lookup ORDER BY game_date
                                   ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as minutes_avg_last_10,
         AVG(SAFE_DIVIDE(points, minutes_played)) OVER (PARTITION BY player_lookup ORDER BY game_date
                                                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as ppm_avg_last_10
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN '2021-11-01' AND '2026-01-08'
    AND points IS NOT NULL AND minutes_played > 0
)
SELECT
  fd.player_lookup, fd.game_date, fd.features,
  v.vegas_points_line, v.vegas_opening_line, v.vegas_line_move,
  CASE WHEN v.vegas_points_line IS NOT NULL THEN 1.0 ELSE 0.0 END as has_vegas_line,
  oh.avg_points_vs_opponent, COALESCE(oh.games_vs_opponent, 0) as games_vs_opponent,
  a.actual_points, a.player_season_avg, a.minutes_avg_last_10, a.ppm_avg_last_10,
  COALESCE(pca.career_ppg, 0) as career_ppg,
  COALESCE(pca.career_games, 0) as career_games,
  -- Tier assignment based on career average
  CASE
    WHEN COALESCE(pca.career_ppg, 0) >= 20 THEN 'star'
    WHEN COALESCE(pca.career_ppg, 0) >= 14 THEN 'starter'
    WHEN COALESCE(pca.career_ppg, 0) >= 8 THEN 'role'
    ELSE 'bench'
  END as player_tier
FROM feature_data fd
INNER JOIN actuals a ON fd.player_lookup = a.player_lookup AND fd.game_date = a.game_date
LEFT JOIN vegas_lines v ON fd.player_lookup = v.player_lookup AND fd.game_date = v.game_date
LEFT JOIN opponent_history oh ON fd.player_lookup = oh.player_lookup AND fd.game_date = oh.game_date
LEFT JOIN player_career_avg pca ON fd.player_lookup = pca.player_lookup
WHERE a.minutes_avg_last_10 IS NOT NULL
ORDER BY fd.game_date
"""

print("Loading data...")
df = client.query(query).to_dataframe()
print(f"Total samples: {len(df):,}")

# Split into training (2021-2024) and validation (2024-25)
df['game_date'] = pd.to_datetime(df['game_date'])
train_df = df[df['game_date'] < pd.Timestamp('2024-10-01')].copy()
val_df = df[df['game_date'] >= pd.Timestamp('2024-10-01')].copy()

print(f"Training: {len(train_df):,} (up to 2024-09)")
print(f"Validation: {len(val_df):,} (2024-10+)")
print()

# Tier distribution
print("Player tier distribution:")
print(train_df['player_tier'].value_counts())
print()

# ============================================================================
# STEP 2: PREPARE FEATURES
# ============================================================================

print("=" * 80)
print("STEP 2: PREPARING FEATURES")
print("=" * 80)

base_features = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct"
]

def prepare_features(df_in):
    df = df_in.copy()
    X_base = pd.DataFrame(df['features'].tolist(), columns=base_features)

    df['vegas_points_line_imp'] = df['vegas_points_line'].fillna(df['player_season_avg'])
    df['vegas_opening_line_imp'] = df['vegas_opening_line'].fillna(df['player_season_avg'])
    df['vegas_line_move_imp'] = df['vegas_line_move'].fillna(0)
    df['avg_points_vs_opponent_imp'] = df['avg_points_vs_opponent'].fillna(df['player_season_avg'])

    X_new = pd.DataFrame({
        'vegas_points_line': df['vegas_points_line_imp'].astype(float),
        'vegas_opening_line': df['vegas_opening_line_imp'].astype(float),
        'vegas_line_move': df['vegas_line_move_imp'].astype(float),
        'has_vegas_line': df['has_vegas_line'].astype(float),
        'avg_points_vs_opponent': df['avg_points_vs_opponent_imp'].astype(float),
        'games_vs_opponent': df['games_vs_opponent'].astype(float),
        'minutes_avg_last_10': df['minutes_avg_last_10'].astype(float),
        'ppm_avg_last_10': df['ppm_avg_last_10'].astype(float)
    })

    X = pd.concat([X_base.reset_index(drop=True), X_new.reset_index(drop=True)], axis=1)
    return X, df.reset_index(drop=True)

X_train, train_df = prepare_features(train_df)
X_val, val_df = prepare_features(val_df)

train_medians = X_train.median()
X_train = X_train.fillna(train_medians)
X_val = X_val.fillna(train_medians)

y_train = train_df['actual_points'].astype(float)
y_val = val_df['actual_points'].astype(float)

print(f"Features: {X_train.shape[1]}")
print()

# ============================================================================
# STEP 3: BASELINE - SINGLE MODEL FOR ALL
# ============================================================================

print("=" * 80)
print("STEP 3: BASELINE - SINGLE MODEL FOR ALL PLAYERS")
print("=" * 80)

# Internal train/val split for early stopping
n = len(X_train)
split_idx = int(n * 0.85)
X_tr, X_v = X_train.iloc[:split_idx], X_train.iloc[split_idx:]
y_tr, y_v = y_train.iloc[:split_idx], y_train.iloc[split_idx:]

cb_params = {
    'depth': 6, 'learning_rate': 0.07, 'l2_leaf_reg': 3.8,
    'subsample': 0.72, 'min_data_in_leaf': 16,
    'iterations': 1000, 'random_seed': 42, 'verbose': False,
    'early_stopping_rounds': 50
}

print("Training baseline model...")
baseline_model = cb.CatBoostRegressor(**cb_params)
baseline_model.fit(X_tr, y_tr, eval_set=(X_v, y_v))

baseline_pred = baseline_model.predict(X_val)
baseline_mae = mean_absolute_error(y_val, baseline_pred)
print(f"Baseline MAE: {baseline_mae:.4f}")

# MAE by tier
print("\nBaseline MAE by tier:")
for tier in ['star', 'starter', 'role', 'bench']:
    mask = val_df['player_tier'] == tier
    if mask.sum() > 0:
        tier_mae = mean_absolute_error(y_val[mask], baseline_pred[mask])
        print(f"  {tier:10s}: {tier_mae:.3f} ({mask.sum():,} games)")

# ============================================================================
# STEP 4: APPROACH 1 - TIER-SPECIFIC MODELS
# ============================================================================

print("\n" + "=" * 80)
print("STEP 4: TIER-SPECIFIC MODELS")
print("=" * 80)

tier_models = {}
tier_predictions = np.zeros(len(X_val))

for tier in ['star', 'starter', 'role', 'bench']:
    print(f"\nTraining {tier} model...")

    # Filter training data for this tier
    train_mask = train_df['player_tier'] == tier
    val_mask = val_df['player_tier'] == tier

    if train_mask.sum() < 100:
        print(f"  Skipping {tier} - not enough training data ({train_mask.sum()} samples)")
        # Use baseline for this tier
        tier_predictions[val_mask] = baseline_pred[val_mask]
        continue

    X_tier_train = X_train[train_mask]
    y_tier_train = y_train[train_mask]

    # Split for early stopping
    n_tier = len(X_tier_train)
    split = int(n_tier * 0.85)

    model = cb.CatBoostRegressor(**cb_params)
    model.fit(
        X_tier_train.iloc[:split], y_tier_train.iloc[:split],
        eval_set=(X_tier_train.iloc[split:], y_tier_train.iloc[split:])
    )
    tier_models[tier] = model

    # Predict for this tier in validation
    tier_predictions[val_mask] = model.predict(X_val[val_mask])

    tier_mae = mean_absolute_error(y_val[val_mask], tier_predictions[val_mask])
    print(f"  {tier} MAE: {tier_mae:.3f} ({val_mask.sum():,} games)")

tier_overall_mae = mean_absolute_error(y_val, tier_predictions)
print(f"\nTier-specific overall MAE: {tier_overall_mae:.4f}")
print(f"vs Baseline: {tier_overall_mae - baseline_mae:+.4f}")

# ============================================================================
# STEP 5: APPROACH 2 - INDIVIDUAL PLAYER MODELS FOR TOP SCORERS
# ============================================================================

print("\n" + "=" * 80)
print("STEP 5: INDIVIDUAL PLAYER MODELS (TOP 30)")
print("=" * 80)

# Identify top 30 scorers by career average
top_players = train_df.groupby('player_lookup').agg({
    'career_ppg': 'first',
    'actual_points': 'count'
}).rename(columns={'actual_points': 'games'})
top_players = top_players[top_players['games'] >= 100]  # At least 100 games
top_players = top_players.nlargest(30, 'career_ppg')

print(f"Top 30 scorers (100+ games each):")
print(top_players.head(10).to_string())
print("...")
print()

# Train individual models for top players
individual_predictions = baseline_pred.copy()
individual_models = {}

for player in top_players.index:
    train_mask = train_df['player_lookup'] == player
    val_mask = val_df['player_lookup'] == player

    if train_mask.sum() < 50 or val_mask.sum() == 0:
        continue

    X_player_train = X_train[train_mask]
    y_player_train = y_train[train_mask]

    # Simpler model for individual players (less data)
    player_params = {
        'depth': 4, 'learning_rate': 0.05, 'l2_leaf_reg': 5.0,
        'iterations': 500, 'random_seed': 42, 'verbose': False
    }

    model = cb.CatBoostRegressor(**player_params)
    model.fit(X_player_train, y_player_train)
    individual_models[player] = model

    # Predict for this player in validation
    individual_predictions[val_mask] = model.predict(X_val[val_mask])

print(f"Trained {len(individual_models)} individual player models")

# Evaluate
individual_mae = mean_absolute_error(y_val, individual_predictions)
print(f"Individual models overall MAE: {individual_mae:.4f}")
print(f"vs Baseline: {individual_mae - baseline_mae:+.4f}")

# Check improvement specifically for top scorers
top_player_mask = val_df['player_lookup'].isin(top_players.index)
if top_player_mask.sum() > 0:
    baseline_top_mae = mean_absolute_error(y_val[top_player_mask], baseline_pred[top_player_mask])
    individual_top_mae = mean_absolute_error(y_val[top_player_mask], individual_predictions[top_player_mask])
    print(f"\nTop 30 scorers only ({top_player_mask.sum():,} games):")
    print(f"  Baseline MAE: {baseline_top_mae:.3f}")
    print(f"  Individual MAE: {individual_top_mae:.3f}")
    print(f"  Improvement: {baseline_top_mae - individual_top_mae:+.3f}")

# ============================================================================
# STEP 6: APPROACH 3 - STAR-TUNED HYPERPARAMETERS
# ============================================================================

print("\n" + "=" * 80)
print("STEP 6: STAR-TUNED HYPERPARAMETERS")
print("=" * 80)

# Hypothesis: Stars need different hyperparameters (more regularization for high variance)
star_mask_train = train_df['player_tier'] == 'star'
star_mask_val = val_df['player_tier'] == 'star'

if star_mask_train.sum() > 500:
    print("Testing different hyperparameters for star model...")

    X_star_train = X_train[star_mask_train]
    y_star_train = y_train[star_mask_train]

    # Split for validation
    n_star = len(X_star_train)
    split = int(n_star * 0.8)

    configs = [
        {'name': 'default', 'depth': 6, 'learning_rate': 0.07, 'l2_leaf_reg': 3.8},
        {'name': 'deeper', 'depth': 8, 'learning_rate': 0.05, 'l2_leaf_reg': 3.8},
        {'name': 'more_reg', 'depth': 6, 'learning_rate': 0.07, 'l2_leaf_reg': 10.0},
        {'name': 'conservative', 'depth': 4, 'learning_rate': 0.03, 'l2_leaf_reg': 8.0},
    ]

    best_star_mae = float('inf')
    best_star_model = None

    for config in configs:
        params = {
            'depth': config['depth'],
            'learning_rate': config['learning_rate'],
            'l2_leaf_reg': config['l2_leaf_reg'],
            'subsample': 0.72, 'min_data_in_leaf': 16,
            'iterations': 500, 'random_seed': 42, 'verbose': False
        }

        model = cb.CatBoostRegressor(**params)
        model.fit(X_star_train.iloc[:split], y_star_train.iloc[:split])

        val_pred = model.predict(X_star_train.iloc[split:])
        val_mae = mean_absolute_error(y_star_train.iloc[split:], val_pred)

        print(f"  {config['name']:15s}: val MAE = {val_mae:.3f}")

        if val_mae < best_star_mae:
            best_star_mae = val_mae
            best_star_model = model
            best_config = config['name']

    print(f"\nBest config: {best_config}")

    # Use best star model for star predictions
    star_tuned_predictions = baseline_pred.copy()
    star_tuned_predictions[star_mask_val] = best_star_model.predict(X_val[star_mask_val])

    star_tuned_mae = mean_absolute_error(y_val, star_tuned_predictions)
    print(f"Star-tuned overall MAE: {star_tuned_mae:.4f}")

# ============================================================================
# STEP 7: APPROACH 4 - ENSEMBLE OF APPROACHES
# ============================================================================

print("\n" + "=" * 80)
print("STEP 7: ENSEMBLE OF APPROACHES")
print("=" * 80)

# Blend baseline with tier-specific for stars
blend_predictions = baseline_pred.copy()

# Use tier model for stars only
star_mask = val_df['player_tier'] == 'star'
if 'star' in tier_models:
    blend_predictions[star_mask] = tier_models['star'].predict(X_val[star_mask])

blend_mae = mean_absolute_error(y_val, blend_predictions)
print(f"Hybrid (baseline + star-tier): {blend_mae:.4f}")

# Blend baseline with individual for top 30
hybrid2_predictions = baseline_pred.copy()
for player, model in individual_models.items():
    mask = val_df['player_lookup'] == player
    if mask.sum() > 0:
        # Blend 50/50 with baseline
        individual_pred = model.predict(X_val[mask])
        hybrid2_predictions[mask] = 0.5 * baseline_pred[mask] + 0.5 * individual_pred

hybrid2_mae = mean_absolute_error(y_val, hybrid2_predictions)
print(f"Hybrid (baseline + individual blend): {hybrid2_mae:.4f}")

# ============================================================================
# STEP 8: FINAL COMPARISON
# ============================================================================

print("\n" + "=" * 80)
print("STEP 8: FINAL COMPARISON")
print("=" * 80)

results = {
    'Baseline (single model)': baseline_mae,
    'Tier-specific models': tier_overall_mae,
    'Individual player models': individual_mae,
    'Star-tuned model': star_tuned_mae if 'star_tuned_mae' in dir() else baseline_mae,
    'Hybrid (baseline + star)': blend_mae,
    'Hybrid (baseline + individual)': hybrid2_mae
}

print(f"\n{'Approach':<35} {'MAE':>8} {'vs Baseline':>12}")
print("-" * 57)
for name, mae in sorted(results.items(), key=lambda x: x[1]):
    diff = mae - baseline_mae
    marker = " ***" if mae == min(results.values()) else ""
    print(f"{name:<35} {mae:>8.4f} {diff:>+11.4f}{marker}")

best_approach = min(results, key=results.get)
best_mae = results[best_approach]

print(f"\nBEST: {best_approach} = {best_mae:.4f}")

# Detailed star analysis
print("\n--- Star Player Analysis ---")
for name, predictions in [
    ('Baseline', baseline_pred),
    ('Tier-specific', tier_predictions),
    ('Individual', individual_predictions)
]:
    star_mae = mean_absolute_error(y_val[star_mask], predictions[star_mask])
    print(f"{name:20s} Star MAE: {star_mae:.3f}")

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"""
2024-25 Validation Results with Star-Specific Models
=====================================================
Games: {len(val_df):,}
Star games: {star_mask.sum():,} ({star_mask.mean()*100:.1f}%)

Baseline MAE: {baseline_mae:.4f}
Best approach: {best_approach}
Best MAE: {best_mae:.4f}
Improvement: {baseline_mae - best_mae:+.4f} ({(baseline_mae - best_mae)/baseline_mae*100:+.1f}%)

Star-specific improvement:
  Baseline star MAE: {mean_absolute_error(y_val[star_mask], baseline_pred[star_mask]):.3f}
  Best star MAE: {mean_absolute_error(y_val[star_mask], tier_predictions[star_mask]):.3f}
""")
print("=" * 80)

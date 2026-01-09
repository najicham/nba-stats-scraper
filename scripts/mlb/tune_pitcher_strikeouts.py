#!/usr/bin/env python3
"""
Hyperparameter Tuning for MLB Pitcher Strikeout Model

Uses RandomizedSearchCV to find optimal XGBoost parameters.
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from google.cloud import bigquery
from sklearn.model_selection import RandomizedSearchCV, TimeSeriesSplit
from sklearn.metrics import mean_absolute_error, make_scorer

# Configuration
PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models/mlb")

print("=" * 80)
print(" MLB PITCHER STRIKEOUT HYPERPARAMETER TUNING")
print("=" * 80)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================================================
# STEP 1: LOAD DATA (same query as training script)
# ============================================================================

print("Loading data...")
client = bigquery.Client(project=PROJECT_ID)

query = """
WITH game_teams AS (
    SELECT DISTINCT game_pk, home_team_abbr, away_team_abbr
    FROM `nba-props-platform.mlb_raw.mlb_game_lineups`
    WHERE game_date >= '2024-03-01' AND game_date <= '2025-12-31'
),
pitcher_raw AS (
    SELECT game_pk, game_date, player_lookup, pitcher_team, opponent_team
    FROM (
        SELECT
            ps.game_pk, ps.game_date, ps.player_lookup,
            ps.team_abbr as pitcher_team,
            CASE WHEN ps.team_abbr = gt.home_team_abbr THEN gt.away_team_abbr
                 ELSE gt.home_team_abbr END as opponent_team,
            ROW_NUMBER() OVER (PARTITION BY ps.game_pk, ps.player_lookup ORDER BY ps.game_date) as rn
        FROM `nba-props-platform.mlb_raw.mlb_pitcher_stats` ps
        JOIN game_teams gt ON ps.game_pk = gt.game_pk
        WHERE ps.is_starter = TRUE AND ps.game_date >= '2024-03-01' AND ps.game_date <= '2025-12-31'
    ) WHERE rn = 1
),
batter_latest_stats AS (
    SELECT player_lookup, k_rate_last_10, season_k_rate
    FROM `nba-props-platform.mlb_analytics.batter_game_summary`
    QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) = 1
),
lineup_batters_deduped AS (
    SELECT game_pk, team_abbr, player_lookup, batting_order
    FROM (
        SELECT game_pk, game_date, team_abbr, player_lookup, batting_order,
            ROW_NUMBER() OVER (PARTITION BY game_pk, team_abbr, player_lookup ORDER BY batting_order) as rn
        FROM `nba-props-platform.mlb_raw.mlb_lineup_batters`
        WHERE game_date >= '2024-03-01' AND game_date <= '2025-12-31'
    ) WHERE rn = 1
),
lineup_batter_stats AS (
    SELECT pr.game_pk, pr.player_lookup as pitcher_lookup,
        COALESCE(bs.k_rate_last_10, bs.season_k_rate, 0.22) as batter_k_rate,
        CASE lb.batting_order
            WHEN 1 THEN 4.5 WHEN 2 THEN 4.3 WHEN 3 THEN 4.2 WHEN 4 THEN 4.0
            WHEN 5 THEN 3.9 WHEN 6 THEN 3.8 WHEN 7 THEN 3.7 WHEN 8 THEN 3.6 ELSE 3.5
        END as expected_pa
    FROM pitcher_raw pr
    JOIN lineup_batters_deduped lb ON pr.game_pk = lb.game_pk AND lb.team_abbr = pr.opponent_team
    LEFT JOIN batter_latest_stats bs ON lb.player_lookup = bs.player_lookup
),
lineup_aggregates AS (
    SELECT game_pk, pitcher_lookup,
        SUM(batter_k_rate * expected_pa) as bottom_up_k,
        AVG(batter_k_rate) as lineup_avg_k_rate,
        COUNTIF(batter_k_rate > 0.28) as weak_spots
    FROM lineup_batter_stats
    GROUP BY game_pk, pitcher_lookup
)
SELECT
    pgs.game_date,
    pgs.strikeouts as actual_strikeouts,
    COALESCE(pgs.k_avg_last_3, 5.0) as f00_k_avg_last_3,
    COALESCE(pgs.k_avg_last_5, 5.0) as f01_k_avg_last_5,
    COALESCE(pgs.k_avg_last_10, 5.0) as f02_k_avg_last_10,
    COALESCE(pgs.k_std_last_10, 2.0) as f03_k_std_last_10,
    COALESCE(pgs.ip_avg_last_5, 5.5) as f04_ip_avg_last_5,
    COALESCE(pgs.season_k_per_9, 8.5) as f05_season_k_per_9,
    COALESCE(SAFE_DIVIDE(pgs.earned_runs * 9, pgs.innings_pitched), 4.0) as f06_season_era,
    COALESCE(pgs.whip_rolling_10, 1.3) as f07_season_whip,
    COALESCE(pgs.season_games_started, 5) as f08_season_games,
    COALESCE(pgs.season_strikeouts, 30) as f09_season_k_total,
    IF(pgs.is_home, 1.0, 0.0) as f10_is_home,
    COALESCE(pgs.days_rest, 5) as f20_days_rest,
    COALESCE(pgs.games_last_30_days, 4) as f21_games_last_30_days,
    COALESCE(pgs.pitch_count_avg_last_5, 90.0) as f22_pitch_count_avg,
    COALESCE(pgs.season_innings, 50.0) as f23_season_ip_total,
    IF(pgs.is_postseason, 1.0, 0.0) as f24_is_postseason,
    COALESCE(la.bottom_up_k, 5.0) as f25_bottom_up_k_expected,
    COALESCE(la.lineup_avg_k_rate, 0.22) as f26_lineup_k_vs_hand,
    COALESCE(la.weak_spots, 2) as f33_lineup_weak_spots
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary` pgs
JOIN pitcher_raw pr ON pgs.player_lookup = pr.player_lookup AND pgs.game_date = pr.game_date
LEFT JOIN lineup_aggregates la ON pr.game_pk = la.game_pk AND pr.player_lookup = la.pitcher_lookup
WHERE pgs.game_date >= '2024-03-01' AND pgs.game_date <= '2025-12-31'
  AND pgs.strikeouts IS NOT NULL AND pgs.innings_pitched >= 3.0
  AND pgs.rolling_stats_games >= 3 AND pgs.season_year IN (2024, 2025)
ORDER BY pgs.game_date
"""

df = client.query(query).to_dataframe()
print(f"Loaded {len(df):,} samples")

# Prepare features
feature_cols = [
    'f00_k_avg_last_3', 'f01_k_avg_last_5', 'f02_k_avg_last_10', 'f03_k_std_last_10',
    'f04_ip_avg_last_5', 'f05_season_k_per_9', 'f06_season_era', 'f07_season_whip',
    'f08_season_games', 'f09_season_k_total', 'f10_is_home', 'f20_days_rest',
    'f21_games_last_30_days', 'f22_pitch_count_avg', 'f23_season_ip_total',
    'f24_is_postseason', 'f25_bottom_up_k_expected', 'f26_lineup_k_vs_hand',
    'f33_lineup_weak_spots'
]

X = df[feature_cols].astype(float).fillna(df[feature_cols].median())
y = df['actual_strikeouts'].astype(float)

# Time-based split (use last 15% as holdout test set)
n = len(df)
test_start = int(n * 0.85)
X_train_val, X_test = X.iloc[:test_start], X.iloc[test_start:]
y_train_val, y_test = y.iloc[:test_start], y.iloc[test_start:]

print(f"Train/Val: {len(X_train_val):,} | Test: {len(X_test):,}")
print()

# ============================================================================
# STEP 2: HYPERPARAMETER SEARCH
# ============================================================================

print("=" * 80)
print("HYPERPARAMETER SEARCH")
print("=" * 80)

# Parameter grid
param_dist = {
    'max_depth': [3, 4, 5, 6, 7, 8],
    'learning_rate': [0.01, 0.02, 0.03, 0.05, 0.08, 0.1],
    'n_estimators': [200, 300, 400, 500],
    'min_child_weight': [1, 2, 3, 5, 7],
    'subsample': [0.6, 0.7, 0.8, 0.9],
    'colsample_bytree': [0.6, 0.7, 0.8, 0.9],
    'gamma': [0, 0.05, 0.1, 0.2],
    'reg_alpha': [0, 0.01, 0.1, 0.5],
    'reg_lambda': [0.5, 1, 2, 5],
}

# Use TimeSeriesSplit for cross-validation (respects temporal order)
tscv = TimeSeriesSplit(n_splits=5)

# MAE scorer (negative because sklearn maximizes)
mae_scorer = make_scorer(mean_absolute_error, greater_is_better=False)

# Base model
base_model = xgb.XGBRegressor(
    objective='reg:squarederror',
    random_state=42,
    n_jobs=-1,
    verbosity=0
)

# Randomized search
print(f"Running RandomizedSearchCV with 100 iterations...")
print(f"Using {tscv.n_splits}-fold TimeSeriesSplit cross-validation")
print()

search = RandomizedSearchCV(
    base_model,
    param_distributions=param_dist,
    n_iter=100,
    scoring=mae_scorer,
    cv=tscv,
    verbose=1,
    random_state=42,
    n_jobs=-1
)

search.fit(X_train_val, y_train_val)

print()
print("=" * 80)
print("BEST PARAMETERS")
print("=" * 80)

best_params = search.best_params_
print(f"Best CV MAE: {-search.best_score_:.4f}")
print()
for k, v in sorted(best_params.items()):
    print(f"  {k}: {v}")

# ============================================================================
# STEP 3: TRAIN FINAL MODEL WITH BEST PARAMS
# ============================================================================

print()
print("=" * 80)
print("TRAINING FINAL MODEL")
print("=" * 80)

# Add early stopping
best_params['early_stopping_rounds'] = 30
best_params['objective'] = 'reg:squarederror'
best_params['random_state'] = 42

# Split train/val for early stopping
val_start = int(len(X_train_val) * 0.85)
X_train = X_train_val.iloc[:val_start]
y_train = y_train_val.iloc[:val_start]
X_val = X_train_val.iloc[val_start:]
y_val = y_train_val.iloc[val_start:]

final_model = xgb.XGBRegressor(**best_params)
final_model.fit(
    X_train, y_train,
    eval_set=[(X_val, y_val)],
    verbose=False
)

# ============================================================================
# STEP 4: EVALUATE
# ============================================================================

print()
print("=" * 80)
print("EVALUATION")
print("=" * 80)

def evaluate(y_true, y_pred, name):
    mae = mean_absolute_error(y_true, y_pred)
    within_1 = (np.abs(y_true - y_pred) <= 1).mean() * 100
    within_2 = (np.abs(y_true - y_pred) <= 2).mean() * 100
    print(f"{name}: MAE={mae:.4f} | Within 1K: {within_1:.1f}% | Within 2K: {within_2:.1f}%")
    return mae

train_mae = evaluate(y_train, final_model.predict(X_train), "Train")
val_mae = evaluate(y_val, final_model.predict(X_val), "Val")
test_mae = evaluate(y_test, final_model.predict(X_test), "Test")

print()
print("COMPARISON:")
print(f"  Previous v2 MAE: 1.469")
print(f"  New tuned MAE:   {test_mae:.4f}")
print(f"  Improvement:     {(1.469 - test_mae) / 1.469 * 100:+.2f}%")

# ============================================================================
# STEP 5: SAVE MODEL
# ============================================================================

print()
print("=" * 80)
print("SAVING MODEL")
print("=" * 80)

model_id = f"mlb_pitcher_strikeouts_v3_{datetime.now().strftime('%Y%m%d')}"
model_path = MODEL_OUTPUT_DIR / f"{model_id}.json"

# Retrain on full train+val set with best params
del best_params['early_stopping_rounds']
final_model_full = xgb.XGBRegressor(**best_params)
final_model_full.fit(X_train_val, y_train_val, verbose=False)

final_model_full.get_booster().save_model(str(model_path))
print(f"Model saved: {model_path}")

# Save metadata
metadata = {
    'model_id': model_id,
    'trained_at': datetime.now().isoformat(),
    'samples': len(df),
    'features': feature_cols,
    'test_mae': test_mae,
    'val_mae': val_mae,
    'best_params': {k: v for k, v in best_params.items()},
    'tuning_iterations': 100,
    'cv_folds': 5
}

metadata_path = MODEL_OUTPUT_DIR / f"{model_id}_metadata.json"
with open(metadata_path, 'w') as f:
    json.dump(metadata, f, indent=2, default=str)
print(f"Metadata saved: {metadata_path}")

# Feature importance
print()
print("TOP 10 FEATURES:")
importance = pd.DataFrame({
    'feature': feature_cols,
    'importance': final_model_full.feature_importances_
}).sort_values('importance', ascending=False)

for _, row in importance.head(10).iterrows():
    print(f"  {row['feature']:30s} {row['importance']*100:5.1f}%")

print()
print("=" * 80)
print(" TUNING COMPLETE")
print("=" * 80)

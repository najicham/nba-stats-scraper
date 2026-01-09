#!/usr/bin/env python3
"""
Final Ensemble v9 - Adding Injury Data

Features:
- 25 base features
- 4 Vegas features
- 2 opponent history features
- 2 minutes/PPM features
- 3 injury features (player status, teammate injuries, opponent injuries)
= 36 total features

Usage:
    PYTHONPATH=. python ml/train_final_ensemble_v9.py
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
import xgboost as xgb
import lightgbm as lgb
import catboost as cb

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models")

print("=" * 80)
print(" FINAL ENSEMBLE V9 - WITH INJURY DATA")
print("=" * 80)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ============================================================================
# STEP 1: LOAD DATA
# ============================================================================

print("=" * 80)
print("STEP 1: LOADING DATA")
print("=" * 80)

client = bigquery.Client(project=PROJECT_ID)

query = """
WITH
feature_data AS (
  SELECT mf.player_lookup, mf.game_date, mf.game_id, mf.features, mf.opponent_team_abbr
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
  WHERE mf.game_date BETWEEN '2021-11-01' AND '2024-06-01'
    AND mf.feature_count = 25 AND ARRAY_LENGTH(mf.features) = 25
),
vegas_lines AS (
  SELECT game_date, player_lookup, points_line as vegas_points_line,
         opening_line as vegas_opening_line, (points_line - opening_line) as vegas_line_move
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE bookmaker = 'BettingPros Consensus' AND bet_side = 'over'
    AND game_date BETWEEN '2021-11-01' AND '2024-06-01'
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
  WHERE pgs1.game_date BETWEEN '2021-11-01' AND '2024-06-01'
  GROUP BY pgs1.player_lookup, pgs1.game_date, pgs1.opponent_team_abbr
),
actuals AS (
  SELECT player_lookup, game_date, team_abbr, points as actual_points,
         AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date
                          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) as player_season_avg,
         AVG(minutes_played) OVER (PARTITION BY player_lookup ORDER BY game_date
                                   ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as minutes_avg_last_10,
         AVG(SAFE_DIVIDE(points, minutes_played)) OVER (PARTITION BY player_lookup ORDER BY game_date
                                                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) as ppm_avg_last_10
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN '2021-11-01' AND '2024-06-01'
    AND points IS NOT NULL AND minutes_played > 0
),
-- Injury report: latest status per player per game date
injury_status AS (
  SELECT
    game_date,
    player_lookup,
    -- Encode injury status: 0=healthy/available, 1=probable, 2=questionable, 3=doubtful, 4=out
    CASE injury_status
      WHEN 'available' THEN 0.0
      WHEN 'probable' THEN 0.25
      WHEN 'questionable' THEN 0.5
      WHEN 'doubtful' THEN 0.75
      WHEN 'out' THEN 1.0
      ELSE 0.0
    END as injury_risk_score
  FROM `nba-props-platform.nba_raw.nbac_injury_report`
  WHERE game_date BETWEEN '2021-11-01' AND '2024-06-01'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup ORDER BY report_hour DESC) = 1
),
-- Count team injuries per game
team_injuries AS (
  SELECT
    game_date,
    team,
    COUNT(*) as team_injury_count,
    COUNTIF(injury_status = 'out') as team_out_count
  FROM `nba-props-platform.nba_raw.nbac_injury_report`
  WHERE game_date BETWEEN '2021-11-01' AND '2024-06-01'
    AND injury_status IN ('out', 'doubtful', 'questionable')
  GROUP BY game_date, team
)

SELECT
  fd.player_lookup, fd.game_date, fd.features, fd.opponent_team_abbr,
  v.vegas_points_line, v.vegas_opening_line, v.vegas_line_move,
  CASE WHEN v.vegas_points_line IS NOT NULL THEN 1.0 ELSE 0.0 END as has_vegas_line,
  oh.avg_points_vs_opponent, COALESCE(oh.games_vs_opponent, 0) as games_vs_opponent,
  a.actual_points, a.player_season_avg, a.minutes_avg_last_10, a.ppm_avg_last_10,
  a.team_abbr,
  -- Injury features
  COALESCE(inj.injury_risk_score, 0.0) as player_injury_risk,
  COALESCE(ti_own.team_injury_count, 0) as teammate_injury_count,
  COALESCE(ti_opp.team_injury_count, 0) as opponent_injury_count

FROM feature_data fd
INNER JOIN actuals a ON fd.player_lookup = a.player_lookup AND fd.game_date = a.game_date
LEFT JOIN vegas_lines v ON fd.player_lookup = v.player_lookup AND fd.game_date = v.game_date
LEFT JOIN opponent_history oh ON fd.player_lookup = oh.player_lookup AND fd.game_date = oh.game_date
LEFT JOIN injury_status inj ON fd.player_lookup = inj.player_lookup AND fd.game_date = inj.game_date
LEFT JOIN team_injuries ti_own ON a.team_abbr = ti_own.team AND fd.game_date = ti_own.game_date
LEFT JOIN team_injuries ti_opp ON fd.opponent_team_abbr = ti_opp.team AND fd.game_date = ti_opp.game_date

WHERE a.minutes_avg_last_10 IS NOT NULL
ORDER BY fd.game_date
"""

print("Fetching data...")
df = client.query(query).to_dataframe()
print(f"Loaded {len(df):,} samples")
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

X_base = pd.DataFrame(df['features'].tolist(), columns=base_features)

# Impute and add new features
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
    'ppm_avg_last_10': df['ppm_avg_last_10'].astype(float),
    # Injury features
    'player_injury_risk': df['player_injury_risk'].astype(float),
    'teammate_injury_count': df['teammate_injury_count'].astype(float),
    'opponent_injury_count': df['opponent_injury_count'].astype(float)
})

X = pd.concat([X_base, X_new], axis=1).fillna(X_base.median())
all_features = list(X.columns)
y = df['actual_points'].astype(float)

print(f"Features: {len(all_features)}")
print(f"  Base: 25")
print(f"  Vegas: 4, Opponent: 2, Minutes/PPM: 2, Injury: 3")
print()

# Check injury coverage
injury_coverage = (df['player_injury_risk'] > 0).mean()
print(f"Player injury report coverage: {injury_coverage:.1%}")
print(f"Avg teammate injuries: {df['teammate_injury_count'].mean():.2f}")
print(f"Avg opponent injuries: {df['opponent_injury_count'].mean():.2f}")
print()

# ============================================================================
# STEP 3: SPLIT DATA
# ============================================================================

print("=" * 80)
print("STEP 3: CHRONOLOGICAL SPLIT")
print("=" * 80)

df_sorted = df.sort_values('game_date').reset_index(drop=True)
X = X.iloc[df_sorted.index].reset_index(drop=True)
y = y.iloc[df_sorted.index].reset_index(drop=True)

n = len(df)
train_end, val_end = int(n * 0.70), int(n * 0.85)

X_train, X_val, X_test = X.iloc[:train_end], X.iloc[train_end:val_end], X.iloc[val_end:]
y_train, y_val, y_test = y.iloc[:train_end], y.iloc[train_end:val_end], y.iloc[val_end:]

print(f"Train: {len(X_train):,}  Val: {len(X_val):,}  Test: {len(X_test):,}")
print()

# ============================================================================
# STEP 4: TRAIN MODELS
# ============================================================================

print("=" * 80)
print("STEP 4: TRAINING MODELS")
print("=" * 80)

results = {}

# XGBoost
print("\n[1/3] Training XGBoost...")
xgb_model = xgb.XGBRegressor(
    max_depth=6, min_child_weight=10, learning_rate=0.03, n_estimators=1000,
    subsample=0.7, colsample_bytree=0.7, gamma=0.1, reg_alpha=0.5, reg_lambda=5.0,
    random_state=42, objective='reg:squarederror', eval_metric='mae', early_stopping_rounds=50
)
xgb_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
xgb_pred = xgb_model.predict(X_test)
results['XGBoost'] = {'pred': xgb_pred, 'mae': mean_absolute_error(y_test, xgb_pred)}
print(f"    XGBoost MAE: {results['XGBoost']['mae']:.4f}")

# LightGBM
print("\n[2/3] Training LightGBM...")
lgb_model = lgb.LGBMRegressor(
    max_depth=6, min_child_weight=10, learning_rate=0.03, n_estimators=1000,
    subsample=0.7, colsample_bytree=0.7, reg_alpha=0.5, reg_lambda=5.0,
    random_state=42, verbose=-1
)
lgb_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], callbacks=[lgb.early_stopping(50, verbose=False)])
lgb_pred = lgb_model.predict(X_test)
results['LightGBM'] = {'pred': lgb_pred, 'mae': mean_absolute_error(y_test, lgb_pred)}
print(f"    LightGBM MAE: {results['LightGBM']['mae']:.4f}")

# CatBoost
print("\n[3/3] Training CatBoost...")
cb_model = cb.CatBoostRegressor(
    depth=6, learning_rate=0.07, l2_leaf_reg=3.8, subsample=0.72, min_data_in_leaf=16,
    iterations=1000, random_seed=42, verbose=False, early_stopping_rounds=50
)
cb_model.fit(X_train, y_train, eval_set=(X_val, y_val))
cb_pred = cb_model.predict(X_test)
results['CatBoost'] = {'pred': cb_pred, 'mae': mean_absolute_error(y_test, cb_pred)}
print(f"    CatBoost MAE: {results['CatBoost']['mae']:.4f}")

# ============================================================================
# STEP 5: ENSEMBLES
# ============================================================================

print("\n" + "=" * 80)
print("STEP 5: ENSEMBLE METHODS")
print("=" * 80)

# Simple average
avg_pred = (xgb_pred + lgb_pred + cb_pred) / 3
results['Simple Avg'] = {'pred': avg_pred, 'mae': mean_absolute_error(y_test, avg_pred)}
print(f"\nSimple Average: {results['Simple Avg']['mae']:.4f}")

# Stacked with Ridge
xgb_val = xgb_model.predict(X_val)
lgb_val = lgb_model.predict(X_val)
cb_val = cb_model.predict(X_val)

stack_val = np.column_stack([xgb_val, lgb_val, cb_val])
stack_test = np.column_stack([xgb_pred, lgb_pred, cb_pred])

meta = Ridge(alpha=1.0)
meta.fit(stack_val, y_val)
stacked_pred = meta.predict(stack_test)
results['Stacked'] = {'pred': stacked_pred, 'mae': mean_absolute_error(y_test, stacked_pred)}
print(f"Stacked (Ridge): {results['Stacked']['mae']:.4f}")

# ============================================================================
# STEP 6: RESULTS
# ============================================================================

print("\n" + "=" * 80)
print("STEP 6: FINAL COMPARISON")
print("=" * 80)

V6_MAE = 4.14
V7_MAE = 3.881
V8_MAE = 3.4045
MOCK_MAE = 4.80

print(f"\n{'Model':<20} {'MAE':>8} {'vs v6':>10} {'vs v8':>10} {'vs Mock':>10}")
print("-" * 60)
print(f"{'Mock v1':<20} {MOCK_MAE:>8.3f} {'+15.9%':>10} {'+41.0%':>10} {'--':>10}")
print(f"{'XGBoost v6':<20} {V6_MAE:>8.3f} {'--':>10} {'+21.6%':>10} {'-13.8%':>10}")
print(f"{'v8 Stacked':<20} {V8_MAE:>8.3f} {'-17.8%':>10} {'--':>10} {'-29.1%':>10}")
print("-" * 60)

sorted_results = sorted(results.items(), key=lambda x: x[1]['mae'])
for name, data in sorted_results:
    mae = data['mae']
    vs_v6 = ((V6_MAE - mae) / V6_MAE) * 100
    vs_v8 = ((V8_MAE - mae) / V8_MAE) * 100
    vs_mock = ((MOCK_MAE - mae) / MOCK_MAE) * 100
    marker = " ***" if name == sorted_results[0][0] else ""
    print(f"{name:<20} {mae:>8.4f} {vs_v6:>+9.1f}% {vs_v8:>+9.1f}% {vs_mock:>+9.1f}%{marker}")

best_name, best_data = sorted_results[0]
best_mae = best_data['mae']

print("\n" + "=" * 60)
print(f"BEST: {best_name} = {best_mae:.4f}")

if best_mae < V8_MAE:
    print(f"NEW RECORD! Beats v8 by {V8_MAE - best_mae:.4f}")
else:
    print(f"v8 still best (v9 diff: {best_mae - V8_MAE:+.4f})")

# ============================================================================
# STEP 7: FEATURE IMPORTANCE
# ============================================================================

print("\n" + "=" * 80)
print("STEP 7: TOP 15 FEATURE IMPORTANCE")
print("=" * 80)

importance = cb_model.get_feature_importance()
feat_imp = pd.DataFrame({'feature': all_features, 'importance': importance})
feat_imp = feat_imp.sort_values('importance', ascending=False)

print(f"\n{'Rank':<5} {'Feature':<30} {'Importance':>10}")
print("-" * 50)
for rank, (_, row) in enumerate(feat_imp.head(15).iterrows(), 1):
    new_marker = " *" if row['feature'] in ['player_injury_risk', 'teammate_injury_count', 'opponent_injury_count'] else ""
    print(f"{rank:<5} {row['feature']:<30} {row['importance']:>9.1f}%{new_marker}")

# Show injury feature rankings
print("\nInjury feature rankings:")
for feat in ['player_injury_risk', 'teammate_injury_count', 'opponent_injury_count']:
    rank = list(feat_imp['feature']).index(feat) + 1
    imp = feat_imp[feat_imp['feature'] == feat]['importance'].values[0]
    print(f"  {feat:<25} rank {rank:>2}, importance {imp:.2f}%")

# ============================================================================
# SAVE
# ============================================================================

print("\n" + "=" * 80)
print("SAVING MODELS")
print("=" * 80)

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

cb_model.save_model(str(MODEL_OUTPUT_DIR / f"catboost_v9_36features_{timestamp}.cbm"))

metadata = {
    'version': 'v9',
    'timestamp': timestamp,
    'features': all_features,
    'feature_count': len(all_features),
    'training_samples': len(df),
    'results': {name: {'mae': float(data['mae'])} for name, data in results.items()},
    'best_model': best_name,
    'best_mae': float(best_mae),
    'baselines': {'v6': V6_MAE, 'v7': V7_MAE, 'v8': V8_MAE, 'mock': MOCK_MAE}
}

with open(MODEL_OUTPUT_DIR / f"ensemble_v9_{timestamp}_metadata.json", 'w') as f:
    json.dump(metadata, f, indent=2)

print(f"Saved model and metadata")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"""
Features: {len(all_features)} (added 3 injury features)
Best: {best_name} = {best_mae:.4f}
vs v8: {((V8_MAE - best_mae) / V8_MAE) * 100:+.2f}%
""")
print("=" * 80)

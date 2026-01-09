#!/usr/bin/env python3
"""
Calculate actual betting accuracy using v8 model predictions.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
import catboost as cb

PROJECT_ID = "nba-props-platform"
client = bigquery.Client(project=PROJECT_ID)

print("=" * 70)
print("BETTING ACCURACY ANALYSIS - V8 MODEL")
print("=" * 70)

# Load data with Vegas lines
query = """
WITH
feature_data AS (
  SELECT mf.player_lookup, mf.game_date, mf.features, mf.opponent_team_abbr
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
  WHERE mf.game_date >= '2024-10-01'
    AND mf.feature_count = 25 AND ARRAY_LENGTH(mf.features) = 25
),
vegas_lines AS (
  SELECT game_date, player_lookup,
         CAST(points_line AS FLOAT64) as vegas_line
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE bookmaker = 'BettingPros Consensus' AND bet_side = 'over'
    AND game_date >= '2024-10-01'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup ORDER BY processed_at DESC) = 1
),
opponent_history AS (
  SELECT pgs1.player_lookup, pgs1.game_date,
         AVG(pgs2.points) as avg_points_vs_opponent,
         COUNT(pgs2.points) as games_vs_opponent
  FROM `nba-props-platform.nba_analytics.player_game_summary` pgs1
  LEFT JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs2
    ON pgs1.player_lookup = pgs2.player_lookup
    AND pgs1.opponent_team_abbr = pgs2.opponent_team_abbr
    AND pgs2.game_date < pgs1.game_date
    AND pgs2.game_date >= DATE_SUB(pgs1.game_date, INTERVAL 3 YEAR)
    AND pgs2.points IS NOT NULL
  WHERE pgs1.game_date >= '2024-10-01'
  GROUP BY pgs1.player_lookup, pgs1.game_date, pgs1.opponent_team_abbr
),
actuals AS (
  SELECT player_lookup, game_date,
         CAST(points AS FLOAT64) as actual_points,
         CAST(AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date
                          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS FLOAT64) as player_season_avg,
         CAST(AVG(minutes_played) OVER (PARTITION BY player_lookup ORDER BY game_date
                                   ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) AS FLOAT64) as minutes_avg_last_10,
         CAST(AVG(SAFE_DIVIDE(points, minutes_played)) OVER (PARTITION BY player_lookup ORDER BY game_date
                                                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) AS FLOAT64) as ppm_avg_last_10
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2024-10-01'
    AND points IS NOT NULL AND minutes_played > 0
)
SELECT
  fd.player_lookup,
  fd.game_date,
  fd.features,
  v.vegas_line,
  CAST(oh.avg_points_vs_opponent AS FLOAT64) as avg_points_vs_opponent,
  CAST(COALESCE(oh.games_vs_opponent, 0) AS FLOAT64) as games_vs_opponent,
  a.actual_points,
  a.player_season_avg,
  a.minutes_avg_last_10,
  a.ppm_avg_last_10
FROM feature_data fd
INNER JOIN actuals a ON fd.player_lookup = a.player_lookup AND fd.game_date = a.game_date
INNER JOIN vegas_lines v ON fd.player_lookup = v.player_lookup AND fd.game_date = v.game_date
LEFT JOIN opponent_history oh ON fd.player_lookup = oh.player_lookup AND fd.game_date = oh.game_date
WHERE a.minutes_avg_last_10 IS NOT NULL
  AND v.vegas_line IS NOT NULL
ORDER BY fd.game_date
"""

print("Loading 2024-25 data with Vegas lines...")
df = client.query(query).to_dataframe()
print(f"Games with Vegas lines: {len(df):,}")

# Prepare features (same as v8)
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

df['vegas_points_line_imp'] = df['vegas_line'].fillna(df['player_season_avg'])
df['avg_points_vs_opponent_imp'] = df['avg_points_vs_opponent'].fillna(df['player_season_avg'])

X_new = pd.DataFrame({
    'vegas_points_line': df['vegas_points_line_imp'].astype(float),
    'vegas_opening_line': df['vegas_points_line_imp'].astype(float),  # Use same as closing
    'vegas_line_move': 0.0,  # No movement data
    'has_vegas_line': 1.0,  # All have Vegas
    'avg_points_vs_opponent': df['avg_points_vs_opponent_imp'].astype(float),
    'games_vs_opponent': df['games_vs_opponent'].astype(float),
    'minutes_avg_last_10': df['minutes_avg_last_10'].astype(float),
    'ppm_avg_last_10': df['ppm_avg_last_10'].astype(float)
})

X = pd.concat([X_base.reset_index(drop=True), X_new.reset_index(drop=True)], axis=1)
X = X.fillna(X.median())

y = df['actual_points'].values
vegas = df['vegas_line'].values

# Load trained model or train a quick one
print("\nTraining v8-style model for betting analysis...")

# Load training data
train_query = """
WITH
feature_data AS (
  SELECT mf.player_lookup, mf.game_date, mf.features
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
  WHERE mf.game_date BETWEEN '2021-11-01' AND '2024-06-01'
    AND mf.feature_count = 25 AND ARRAY_LENGTH(mf.features) = 25
),
vegas_lines AS (
  SELECT game_date, player_lookup,
         CAST(points_line AS FLOAT64) as vegas_line,
         CAST(opening_line AS FLOAT64) as opening_line
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE bookmaker = 'BettingPros Consensus' AND bet_side = 'over'
    AND game_date BETWEEN '2021-11-01' AND '2024-06-01'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup ORDER BY processed_at DESC) = 1
),
opponent_history AS (
  SELECT pgs1.player_lookup, pgs1.game_date,
         AVG(pgs2.points) as avg_points_vs_opponent,
         COUNT(pgs2.points) as games_vs_opponent
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
  SELECT player_lookup, game_date,
         CAST(points AS FLOAT64) as actual_points,
         CAST(AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date
                          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS FLOAT64) as player_season_avg,
         CAST(AVG(minutes_played) OVER (PARTITION BY player_lookup ORDER BY game_date
                                   ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) AS FLOAT64) as minutes_avg_last_10,
         CAST(AVG(SAFE_DIVIDE(points, minutes_played)) OVER (PARTITION BY player_lookup ORDER BY game_date
                                                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) AS FLOAT64) as ppm_avg_last_10
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN '2021-11-01' AND '2024-06-01'
    AND points IS NOT NULL AND minutes_played > 0
)
SELECT fd.features,
       v.vegas_line, v.opening_line,
       CAST(oh.avg_points_vs_opponent AS FLOAT64) as avg_points_vs_opponent,
       CAST(COALESCE(oh.games_vs_opponent, 0) AS FLOAT64) as games_vs_opponent,
       a.actual_points, a.player_season_avg, a.minutes_avg_last_10, a.ppm_avg_last_10
FROM feature_data fd
INNER JOIN actuals a ON fd.player_lookup = a.player_lookup AND fd.game_date = a.game_date
LEFT JOIN vegas_lines v ON fd.player_lookup = v.player_lookup AND fd.game_date = v.game_date
LEFT JOIN opponent_history oh ON fd.player_lookup = oh.player_lookup AND fd.game_date = oh.game_date
WHERE a.minutes_avg_last_10 IS NOT NULL
"""

train_df = client.query(train_query).to_dataframe()
print(f"Training samples: {len(train_df):,}")

# Prepare training features
X_train_base = pd.DataFrame(train_df['features'].tolist(), columns=base_features)
train_df['vegas_imp'] = train_df['vegas_line'].fillna(train_df['player_season_avg'])
train_df['opening_imp'] = train_df['opening_line'].fillna(train_df['player_season_avg'])
train_df['opp_imp'] = train_df['avg_points_vs_opponent'].fillna(train_df['player_season_avg'])

X_train_new = pd.DataFrame({
    'vegas_points_line': train_df['vegas_imp'].astype(float),
    'vegas_opening_line': train_df['opening_imp'].astype(float),
    'vegas_line_move': (train_df['vegas_imp'] - train_df['opening_imp']).fillna(0).astype(float),
    'has_vegas_line': train_df['vegas_line'].notna().astype(float),
    'avg_points_vs_opponent': train_df['opp_imp'].astype(float),
    'games_vs_opponent': train_df['games_vs_opponent'].astype(float),
    'minutes_avg_last_10': train_df['minutes_avg_last_10'].astype(float),
    'ppm_avg_last_10': train_df['ppm_avg_last_10'].astype(float)
})

X_train = pd.concat([X_train_base.reset_index(drop=True), X_train_new.reset_index(drop=True)], axis=1)
X_train = X_train.fillna(X_train.median())
y_train = train_df['actual_points'].astype(float)

# Train model
model = cb.CatBoostRegressor(
    depth=6, learning_rate=0.07, l2_leaf_reg=3.8,
    subsample=0.72, min_data_in_leaf=16,
    iterations=500, random_seed=42, verbose=False
)
model.fit(X_train, y_train)

# Predict on 2024-25
predictions = model.predict(X)

# Calculate metrics
our_mae = mean_absolute_error(y, predictions)
vegas_mae = mean_absolute_error(y, vegas)

print(f"\n{'='*70}")
print("MAE COMPARISON")
print(f"{'='*70}")
print(f"Our model MAE:  {our_mae:.3f}")
print(f"Vegas MAE:      {vegas_mae:.3f}")
print(f"Difference:     {(1 - our_mae/vegas_mae)*100:+.1f}%")

# Betting accuracy
print(f"\n{'='*70}")
print("OVER/UNDER BETTING ACCURACY")
print(f"{'='*70}")

# Exclude pushes (exact matches to line)
is_push = y == vegas
actual_over = y > vegas
actual_under = y < vegas

we_predict_over = predictions > vegas
we_predict_under = predictions <= vegas

correct = ((we_predict_over & actual_over) | (we_predict_under & actual_under))

non_push = ~is_push
total_bets = non_push.sum()
correct_bets = correct[non_push].sum()
accuracy = correct_bets / total_bets * 100

print(f"Total games (excl. pushes): {total_bets:,}")
print(f"Correct predictions: {correct_bets:,}")
print(f"Accuracy: {accuracy:.2f}%")

# By edge size
print(f"\n{'='*70}")
print("ACCURACY BY EDGE SIZE (Our Prediction vs Vegas Line)")
print(f"{'='*70}")

edge = np.abs(predictions - vegas)
print(f"{'Edge':>10} {'Accuracy':>10} {'Games':>10} {'Profitable?':>12}")
print("-" * 45)

for threshold in [0, 1, 2, 3, 4, 5, 6, 7, 10]:
    mask = non_push & (edge > threshold)
    if mask.sum() >= 50:
        acc = correct[mask].mean() * 100
        profitable = "YES" if acc > 52.4 else "no"
        print(f">{threshold:>8} pts {acc:>9.1f}% {mask.sum():>10,} {profitable:>12}")

# When we strongly disagree
print(f"\n{'='*70}")
print("WHEN WE STRONGLY DISAGREE WITH VEGAS")
print(f"{'='*70}")

# Over predictions (we think player scores MORE than Vegas line)
strong_over = non_push & (predictions > vegas + 3)
if strong_over.sum() >= 50:
    acc = correct[strong_over].mean() * 100
    print(f"We predict 3+ pts OVER Vegas:  {acc:.1f}% ({strong_over.sum():,} games)")

strong_under = non_push & (predictions < vegas - 3)
if strong_under.sum() >= 50:
    acc = correct[strong_under].mean() * 100
    print(f"We predict 3+ pts UNDER Vegas: {acc:.1f}% ({strong_under.sum():,} games)")

# Summary
print(f"\n{'='*70}")
print("SUMMARY")
print(f"{'='*70}")
print(f"""
Overall betting accuracy: {accuracy:.1f}%
Break-even threshold:     52.4% (accounting for -110 vig)

{"✓ PROFITABLE" if accuracy > 52.4 else "✗ NOT PROFITABLE"} at current accuracy level

Key insight: MAE and betting accuracy are DIFFERENT metrics.
- MAE measures how close our predictions are to actual scores
- Betting accuracy measures if we're on the right side of the line

We have {(1 - our_mae/vegas_mae)*100:.1f}% lower MAE than Vegas,
but only {accuracy:.1f}% betting accuracy (need 52.4% to profit).

High-edge bets (>{5} pt difference) show {correct[non_push & (edge > 5)].mean()*100:.1f}% accuracy.
""")

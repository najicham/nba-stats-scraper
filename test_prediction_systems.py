#!/usr/bin/env python3
"""Quick test to see why prediction systems are failing"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from google.cloud import bigquery
from predictions.worker.prediction_systems.moving_average_baseline import MovingAverageBaseline

PROJECT_ID = "nba-props-platform"
client = bigquery.Client(project=PROJECT_ID)

# Get one sample
query = """
SELECT
  mf.player_lookup,
  mf.game_date,
  mf.features,
  pgs.points as actual_points
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
  ON mf.player_lookup = pgs.player_lookup
  AND mf.game_date = pgs.game_date
WHERE mf.game_date = '2024-01-15'
  AND mf.feature_count = 33
  AND ARRAY_LENGTH(mf.features) = 33
  AND pgs.points IS NOT NULL
LIMIT 1
"""

print("Fetching one sample...")
df = client.query(query).to_dataframe()
row = df.iloc[0]

print(f"Player: {row['player_lookup']}")
print(f"Date: {row['game_date']}")
print(f"Features length: {len(row['features'])}")
print()

# Prepare features
feature_names = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct",
    "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line",
    "avg_points_vs_opponent", "games_vs_opponent",
    "minutes_avg_last_10", "ppm_avg_last_10"
]

features = dict(zip(feature_names, row['features']))
print("Features dict created")
print(f"Sample features: {list(features.items())[:5]}")
print()

# Try Moving Average
print("Testing Moving Average...")
try:
    system = MovingAverageBaseline()
    pred, conf, rec = system.predict(
        features=features,
        player_lookup=row['player_lookup'],
        game_date=row['game_date'],
        prop_line=features.get('vegas_points_line', None)
    )
    print(f"✓ Success! Prediction: {pred}, Confidence: {conf}, Rec: {rec}")
except Exception as e:
    print(f"✗ Failed: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

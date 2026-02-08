#!/usr/bin/env python3
"""
Test Ensemble of v6 + Mock Model

Tests different weighting schemes to find optimal ensemble.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import xgboost as xgb
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error

PROJECT_ID = "nba-props-platform"

print("=" * 80)
print(" ENSEMBLE TEST: v6 + Mock")
print("=" * 80)

# Load v6 model
model_dir = Path("models")
v6_models = [f for f in model_dir.glob("xgboost_v6_*.json") if "metadata" not in f.name]
latest_model = sorted(v6_models)[-1]
model = xgb.Booster()
model.load_model(str(latest_model))
print(f"Loaded v6: {latest_model}")

# Load data
client = bigquery.Client(project=PROJECT_ID)
query = """
SELECT
  mf.player_lookup,
  mf.game_date,
  mf.features,
  pgs.points as actual_points,
  pgs.minutes_played,
  pgs.usage_rate
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
  ON mf.player_lookup = pgs.player_lookup
  AND mf.game_date = pgs.game_date
WHERE mf.game_date >= '2024-10-22'
  AND mf.game_date <= CURRENT_DATE()
  AND mf.feature_count = 25
  AND ARRAY_LENGTH(mf.features) = 25
  AND pgs.points IS NOT NULL
ORDER BY mf.game_date
"""

df = client.query(query).to_dataframe()
print(f"Loaded {len(df):,} samples")

# Feature names
feature_names = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct"
]

# Prepare features
X = pd.DataFrame(df['features'].tolist(), columns=feature_names)
X = X.fillna(X.median())
y_actual = df['actual_points'].astype(float).values

# Get v6 predictions
dmatrix = xgb.DMatrix(X, feature_names=feature_names)
v6_preds = model.predict(dmatrix)

v6_mae = mean_absolute_error(y_actual, v6_preds)
print(f"v6 MAE: {v6_mae:.3f}")

# Generate mock predictions using a simplified mock logic
# Based on the mock_xgboost_model.py patterns
print("\nGenerating mock-style predictions...")

def mock_predict(row, features):
    """Simplified mock model prediction."""
    # Baseline from rolling averages (mock uses weighted avg)
    pts_5 = features['points_avg_last_5']
    pts_10 = features['points_avg_last_10']
    pts_season = features['points_avg_season']

    baseline = pts_5 * 0.35 + pts_10 * 0.40 + pts_season * 0.25

    # Fatigue adjustment
    fatigue = features['fatigue_score']
    if fatigue < 50:
        fatigue_adj = -4.0
    elif fatigue < 60:
        fatigue_adj = -2.5
    elif fatigue < 70:
        fatigue_adj = -1.5
    elif fatigue < 80:
        fatigue_adj = -0.5
    else:
        fatigue_adj = 0.0

    # Defense adjustment
    def_rating = features['opponent_def_rating']
    if def_rating > 116:
        def_adj = 2.0
    elif def_rating > 113:
        def_adj = 1.0
    elif def_rating > 110:
        def_adj = 0.5
    elif def_rating < 106:
        def_adj = -1.5
    else:
        def_adj = 0.0

    # Home/away
    home_adj = 0.5 if features['home_away'] > 0.5 else -0.3

    # Back-to-back
    b2b_adj = -1.2 if features['back_to_back'] > 0.5 else 0.0

    prediction = baseline + fatigue_adj + def_adj + home_adj + b2b_adj
    return max(0, prediction)

mock_preds = []
for idx in range(len(df)):
    features = {name: X.iloc[idx][name] for name in feature_names}
    mock_preds.append(mock_predict(df.iloc[idx], features))

mock_preds = np.array(mock_preds)
mock_mae = mean_absolute_error(y_actual, mock_preds)
print(f"Mock MAE: {mock_mae:.3f}")

# Test ensemble weights
print("\n" + "=" * 50)
print("ENSEMBLE WEIGHTS TEST")
print("=" * 50)

results = []
for alpha in np.arange(0.0, 1.05, 0.05):
    ensemble = alpha * v6_preds + (1 - alpha) * mock_preds
    mae = mean_absolute_error(y_actual, ensemble)
    results.append({'alpha': alpha, 'mae': mae})
    marker = " <-- BEST" if len(results) == 1 or mae < min(r['mae'] for r in results[:-1]) else ""
    print(f"α={alpha:.2f} (v6={alpha:.0%}, mock={1-alpha:.0%}): MAE={mae:.3f}{marker}")

best = min(results, key=lambda x: x['mae'])
print(f"\nBest ensemble: α={best['alpha']:.2f}")
print(f"Best MAE: {best['mae']:.3f}")
print(f"v6-only MAE: {v6_mae:.3f}")
print(f"Mock-only MAE: {mock_mae:.3f}")
print(f"Improvement over v6: {v6_mae - best['mae']:.3f}")

# Segment analysis
print("\n" + "=" * 50)
print("SEGMENT-SPECIFIC ENSEMBLE")
print("=" * 50)

df['v6_pred'] = v6_preds
df['mock_pred'] = mock_preds
df['actual'] = y_actual
df['minutes_played'] = pd.to_numeric(df['minutes_played'], errors='coerce').fillna(0)

# By minutes bucket
df['minutes_bucket'] = pd.cut(df['minutes_played'],
                               bins=[0, 15, 30, 50],
                               labels=['Low (<15)', 'Med (15-30)', 'High (30+)'])

print("\nOptimal α by minutes bucket:")
for bucket in df['minutes_bucket'].dropna().unique():
    mask = df['minutes_bucket'] == bucket
    if mask.sum() < 100:
        continue

    best_mae = float('inf')
    best_alpha = 0.5
    for alpha in np.arange(0.0, 1.05, 0.1):
        ensemble = alpha * df.loc[mask, 'v6_pred'] + (1-alpha) * df.loc[mask, 'mock_pred']
        mae = mean_absolute_error(df.loc[mask, 'actual'], ensemble)
        if mae < best_mae:
            best_mae = mae
            best_alpha = alpha

    v6_only = mean_absolute_error(df.loc[mask, 'actual'], df.loc[mask, 'v6_pred'])
    print(f"  {bucket}: α={best_alpha:.1f}, MAE={best_mae:.3f} (v6-only: {v6_only:.3f})")

# Check if v6 or mock wins by segment
print("\nWho wins by segment?")
for bucket in df['minutes_bucket'].dropna().unique():
    mask = df['minutes_bucket'] == bucket
    if mask.sum() < 100:
        continue

    v6_seg = mean_absolute_error(df.loc[mask, 'actual'], df.loc[mask, 'v6_pred'])
    mock_seg = mean_absolute_error(df.loc[mask, 'actual'], df.loc[mask, 'mock_pred'])
    winner = "v6" if v6_seg < mock_seg else "Mock"
    diff = abs(v6_seg - mock_seg)
    print(f"  {bucket}: {winner} wins by {diff:.3f} (v6={v6_seg:.3f}, mock={mock_seg:.3f})")

print("\n" + "=" * 80)

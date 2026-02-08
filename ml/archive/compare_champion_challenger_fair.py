#!/usr/bin/env python3
"""
Fair Champion vs Challenger Comparison

Uses the SAME filters as production:
- High confidence picks only (90%+)
- Real prop lines only (has_prop_line=TRUE, line_value != 20)

Usage:
    PYTHONPATH=. python ml/compare_champion_challenger_fair.py
"""

from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import numpy as np
from google.cloud import bigquery
import catboost as cb

PROJECT_ID = "nba-props-platform"
MODEL_DIR = Path("models")

FEATURES = [
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

def find_model(pattern):
    matches = sorted(MODEL_DIR.glob(pattern), reverse=True)
    if not matches:
        raise FileNotFoundError(f"No model found matching {pattern}")
    return matches[0]

def main():
    print("=" * 80)
    print(" FAIR CHAMPION vs CHALLENGER COMPARISON")
    print(" (Same filters as production: 90%+ confidence, real prop lines)")
    print("=" * 80)

    # Load models
    print("\nLoading models...")
    v8_path = find_model("catboost_v8_33features_*.cbm")
    v10_path = find_model("catboost_v10_33features_*.cbm")
    print(f"  Champion (V8): {v8_path.name}")
    print(f"  Challenger (V10): {v10_path.name}")

    v8_model = cb.CatBoostRegressor()
    v8_model.load_model(str(v8_path))
    v10_model = cb.CatBoostRegressor()
    v10_model.load_model(str(v10_path))

    # Get the SAME player-games that V8 was graded on (with production filters)
    print("\nLoading test data (production filters)...")
    client = bigquery.Client(project=PROJECT_ID)

    query = """
    SELECT
      pa.player_lookup,
      pa.game_date,
      pa.line_value,
      pa.actual_points,
      pa.predicted_points as v8_predicted,
      pa.prediction_correct as v8_correct,
      pa.confidence_score as v8_confidence,
      mf.features
    FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
    INNER JOIN `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
      ON pa.player_lookup = mf.player_lookup AND pa.game_date = mf.game_date
    WHERE pa.game_date BETWEEN '2025-12-30' AND '2026-01-10'
      AND pa.system_id = 'catboost_v8'
      AND pa.recommendation IN ('OVER', 'UNDER')
      AND pa.has_prop_line = TRUE
      AND pa.line_value != 20
      AND pa.confidence_score >= 0.90
      AND mf.feature_count = 33
    """

    df = client.query(query).to_dataframe()
    print(f"  Loaded {len(df):,} high-confidence picks with real lines")

    if len(df) == 0:
        print("No data found!")
        return

    # Prepare features and run V10
    X = pd.DataFrame(df['features'].tolist(), columns=FEATURES).fillna(0)
    y = df['actual_points'].astype(float).values
    lines = df['line_value'].astype(float).values
    v8_pred = df['v8_predicted'].astype(float).values

    print("\nRunning V10 predictions...")
    v10_pred = v10_model.predict(X)

    # Calculate metrics
    v8_mae = np.mean(np.abs(v8_pred - y))
    v10_mae = np.mean(np.abs(v10_pred - y))

    # Win rates
    v8_over = v8_pred > lines
    v10_over = v10_pred > lines
    actual_over = y > lines

    v8_correct = ((v8_over & actual_over) | (~v8_over & ~actual_over))
    v10_correct = ((v10_over & actual_over) | (~v10_over & ~actual_over))

    v8_wins = v8_correct.sum()
    v10_wins = v10_correct.sum()
    v8_hit_rate = v8_wins / len(df) * 100
    v10_hit_rate = v10_wins / len(df) * 100

    # Head-to-head
    v8_closer = np.abs(v8_pred - y) < np.abs(v10_pred - y)
    v10_closer = np.abs(v10_pred - y) < np.abs(v8_pred - y)

    # Results
    print("\n" + "=" * 80)
    print(" RESULTS (High-Confidence Picks Only)")
    print("=" * 80)

    print(f"\n{'Metric':<20} {'Champion (V8)':>15} {'Challenger (V10)':>18} {'Diff':>12}")
    print("-" * 70)
    print(f"{'MAE':<20} {v8_mae:>15.3f} {v10_mae:>18.3f} {v10_mae - v8_mae:>+12.3f}")
    print(f"{'Hit Rate':<20} {v8_hit_rate:>14.1f}% {v10_hit_rate:>17.1f}% {v10_hit_rate - v8_hit_rate:>+11.1f}%")
    print(f"{'Wins':<20} {v8_wins:>15} {v10_wins:>18} {v10_wins - v8_wins:>+12}")
    print(f"{'Total Picks':<20} {len(df):>15}")

    print(f"\n{'Head-to-Head:':<20}")
    print(f"  V8 closer:  {v8_closer.sum():>5} ({v8_closer.sum()/len(df)*100:.1f}%)")
    print(f"  V10 closer: {v10_closer.sum():>5} ({v10_closer.sum()/len(df)*100:.1f}%)")

    # Per-date breakdown
    print("\n" + "-" * 70)
    print("Per-Date Comparison:")
    print("-" * 70)
    df['v10_pred'] = v10_pred
    df['v8_correct'] = v8_correct
    df['v10_correct'] = v10_correct

    for game_date in sorted(df['game_date'].unique()):
        day_df = df[df['game_date'] == game_date]
        v8_wr = day_df['v8_correct'].sum() / len(day_df) * 100
        v10_wr = day_df['v10_correct'].sum() / len(day_df) * 100
        winner = "V10" if v10_wr > v8_wr else "V8" if v8_wr > v10_wr else "TIE"
        print(f"  {game_date}: V8={v8_wr:.1f}%, V10={v10_wr:.1f}%, n={len(day_df)}, Winner={winner}")

    # Verdict
    print("\n" + "=" * 80)
    print(" VERDICT")
    print("=" * 80)

    mae_improvement = (v8_mae - v10_mae) / v8_mae * 100
    wr_advantage = v10_hit_rate - v8_hit_rate

    print(f"\nMAE: {'V10 better' if v10_mae < v8_mae else 'V8 better'} ({mae_improvement:+.1f}%)")
    print(f"Hit Rate: {'V10 better' if v10_hit_rate > v8_hit_rate else 'V8 better'} ({wr_advantage:+.1f}%)")

    print("\nPromotion Criteria:")
    met = 0
    if v10_mae < v8_mae - 0.2:
        print(f"  [x] MAE improvement >= 0.2 points ({v8_mae - v10_mae:.3f})")
        met += 1
    else:
        print(f"  [ ] MAE improvement >= 0.2 points (got {v8_mae - v10_mae:.3f})")

    if wr_advantage >= 3:
        print(f"  [x] Hit rate advantage >= 3% ({wr_advantage:+.1f}%)")
        met += 1
    else:
        print(f"  [ ] Hit rate advantage >= 3% (got {wr_advantage:+.1f}%)")

    if len(df) >= 100:
        print(f"  [x] Sample size >= 100 ({len(df)})")
        met += 1
    else:
        print(f"  [ ] Sample size >= 100 ({len(df)})")

    print(f"\nRECOMMENDATION: {'PROMOTE V10' if met >= 2 else 'KEEP V8 AS CHAMPION'}")
    print("=" * 80)

if __name__ == '__main__':
    main()

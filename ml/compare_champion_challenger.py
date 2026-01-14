#!/usr/bin/env python3
"""
Champion vs Challenger Comparison

Runs both CatBoost V8 (champion) and V10 (challenger) on the SAME games
to get a fair comparison. This eliminates the issue of different test sets.

Usage:
    PYTHONPATH=. python ml/compare_champion_challenger.py
    PYTHONPATH=. python ml/compare_champion_challenger.py --days 14
"""

import argparse
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import numpy as np
from google.cloud import bigquery
import catboost as cb

PROJECT_ID = "nba-props-platform"
MODEL_DIR = Path("models")

# Feature order (must match training)
FEATURES = [
    # Base features (indices 0-24)
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct",
    # Vegas features (indices 25-28)
    "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line",
    # Opponent history (indices 29-30)
    "avg_points_vs_opponent", "games_vs_opponent",
    # Minutes/efficiency (indices 31-32)
    "minutes_avg_last_10", "ppm_avg_last_10"
]

def find_model(pattern: str) -> Path:
    """Find most recent model matching pattern"""
    matches = sorted(MODEL_DIR.glob(pattern), reverse=True)
    if not matches:
        raise FileNotFoundError(f"No model found matching {pattern}")
    return matches[0]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=7, help='Days of data to compare')
    parser.add_argument('--end-date', type=str, default=None, help='End date (default: yesterday)')
    args = parser.parse_args()

    # Date range
    if args.end_date:
        end_date = args.end_date
    else:
        end_date = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
    start_date = (date.fromisoformat(end_date) - timedelta(days=args.days)).strftime('%Y-%m-%d')

    print("=" * 80)
    print(" CHAMPION vs CHALLENGER COMPARISON")
    print("=" * 80)
    print(f"Date range: {start_date} to {end_date}")
    print()

    # Load models
    print("Loading models...")
    v8_path = find_model("catboost_v8_33features_*.cbm")
    v10_path = find_model("catboost_v10_33features_*.cbm")
    print(f"  Champion (V8): {v8_path.name}")
    print(f"  Challenger (V10): {v10_path.name}")

    v8_model = cb.CatBoostRegressor()
    v8_model.load_model(str(v8_path))

    v10_model = cb.CatBoostRegressor()
    v10_model.load_model(str(v10_path))

    # Load test data
    print("\nLoading test data...")
    client = bigquery.Client(project=PROJECT_ID)

    query = f"""
    SELECT
      mf.player_lookup,
      mf.game_date,
      mf.features,
      pgs.points as actual_points,
      bp.points_line as betting_line
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
    INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    LEFT JOIN `nba-props-platform.nba_raw.bettingpros_player_points_props` bp
      ON mf.player_lookup = bp.player_lookup
      AND mf.game_date = bp.game_date
      AND bp.bookmaker = 'BettingPros Consensus'
      AND bp.bet_side = 'over'
    WHERE mf.game_date BETWEEN '{start_date}' AND '{end_date}'
      AND mf.feature_count = 33
      AND ARRAY_LENGTH(mf.features) = 33
      AND pgs.points IS NOT NULL
      AND pgs.minutes_played > 0
    QUALIFY ROW_NUMBER() OVER (PARTITION BY mf.player_lookup, mf.game_date ORDER BY bp.processed_at DESC) = 1
    """

    df = client.query(query).to_dataframe()
    print(f"  Loaded {len(df):,} player-games")

    if len(df) == 0:
        print("No data found!")
        return

    # Prepare features
    X = pd.DataFrame(df['features'].tolist(), columns=FEATURES)
    X = X.fillna(X.median())
    y = df['actual_points'].values
    lines = df['betting_line'].values

    # Make predictions
    print("\nMaking predictions...")
    v8_pred = v8_model.predict(X)
    v10_pred = v10_model.predict(X)

    # Calculate metrics
    v8_mae = np.mean(np.abs(v8_pred - y))
    v10_mae = np.mean(np.abs(v10_pred - y))

    # Win rate (for players with betting lines)
    has_line = ~pd.isna(lines)
    if has_line.sum() > 0:
        # V8 betting accuracy
        v8_over = v8_pred > lines
        v8_under = v8_pred < lines
        actual_over = y > lines
        v8_correct = ((v8_over & actual_over) | (v8_under & ~actual_over))
        v8_win_rate = v8_correct[has_line].sum() / has_line.sum() * 100

        # V10 betting accuracy
        v10_over = v10_pred > lines
        v10_under = v10_pred < lines
        v10_correct = ((v10_over & actual_over) | (v10_under & ~actual_over))
        v10_win_rate = v10_correct[has_line].sum() / has_line.sum() * 100

        # Head-to-head
        v8_better = np.abs(v8_pred - y) < np.abs(v10_pred - y)
        v10_better = np.abs(v10_pred - y) < np.abs(v8_pred - y)
        ties = ~v8_better & ~v10_better
    else:
        v8_win_rate = v10_win_rate = None

    # Results
    print("\n" + "=" * 80)
    print(" RESULTS")
    print("=" * 80)

    print(f"\n{'Metric':<25} {'Champion (V8)':>15} {'Challenger (V10)':>18} {'Diff':>10}")
    print("-" * 70)
    print(f"{'MAE':<25} {v8_mae:>15.3f} {v10_mae:>18.3f} {v10_mae - v8_mae:>+10.3f}")

    if v8_win_rate is not None:
        print(f"{'Win Rate':<25} {v8_win_rate:>14.1f}% {v10_win_rate:>17.1f}% {v10_win_rate - v8_win_rate:>+9.1f}%")
        print(f"{'Picks with lines':<25} {has_line.sum():>15,}")

    print(f"\n{'Head-to-Head:':<25}")
    print(f"  V8 closer to actual:   {v8_better.sum():>5} ({v8_better.sum()/len(df)*100:.1f}%)")
    print(f"  V10 closer to actual:  {v10_better.sum():>5} ({v10_better.sum()/len(df)*100:.1f}%)")
    print(f"  Ties:                  {ties.sum():>5} ({ties.sum()/len(df)*100:.1f}%)")

    # Per-date breakdown
    print("\n" + "-" * 70)
    print("Per-Date MAE Comparison:")
    print("-" * 70)
    df['v8_pred'] = v8_pred
    df['v10_pred'] = v10_pred
    df['v8_error'] = np.abs(v8_pred - y)
    df['v10_error'] = np.abs(v10_pred - y)

    daily = df.groupby('game_date').agg({
        'v8_error': 'mean',
        'v10_error': 'mean',
        'player_lookup': 'count'
    }).rename(columns={'player_lookup': 'players'})

    for game_date, row in daily.iterrows():
        winner = "V8" if row['v8_error'] < row['v10_error'] else "V10" if row['v10_error'] < row['v8_error'] else "TIE"
        print(f"  {game_date}: V8={row['v8_error']:.2f}, V10={row['v10_error']:.2f}, n={int(row['players'])}, Winner={winner}")

    # Verdict
    print("\n" + "=" * 80)
    print(" VERDICT")
    print("=" * 80)

    mae_improvement = (v8_mae - v10_mae) / v8_mae * 100
    if v8_win_rate and v10_win_rate:
        wr_advantage = v10_win_rate - v8_win_rate
    else:
        wr_advantage = 0

    print(f"\nMAE: {'V10 better' if v10_mae < v8_mae else 'V8 better'} ({mae_improvement:+.1f}%)")
    if v8_win_rate:
        print(f"Win Rate: {'V10 better' if v10_win_rate > v8_win_rate else 'V8 better'} ({wr_advantage:+.1f}%)")

    # Promotion criteria check
    print("\nPromotion Criteria:")
    criteria_met = 0
    if mae_improvement >= 5.9:  # 0.2 points on ~3.4 MAE
        print(f"  [x] MAE improvement >= 0.2 points ({mae_improvement:.1f}%)")
        criteria_met += 1
    else:
        print(f"  [ ] MAE improvement >= 0.2 points (need 5.9%, got {mae_improvement:.1f}%)")

    if v8_win_rate and wr_advantage >= 3:
        print(f"  [x] Win rate advantage >= 3% ({wr_advantage:+.1f}%)")
        criteria_met += 1
    else:
        print(f"  [ ] Win rate advantage >= 3% (got {wr_advantage:+.1f}%)")

    if len(df) >= 100:
        print(f"  [x] Sample size >= 100 ({len(df):,})")
        criteria_met += 1
    else:
        print(f"  [ ] Sample size >= 100 (got {len(df):,})")

    print(f"\nRECOMMENDATION: {'PROMOTE V10' if criteria_met >= 2 else 'KEEP V8 AS CHAMPION'}")
    print("=" * 80)

if __name__ == '__main__':
    main()

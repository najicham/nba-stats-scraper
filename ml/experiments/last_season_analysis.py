#!/usr/bin/env python3
"""
Last Season Performance Analysis

Simulates training on 2024-25 season data (similar dates to current season)
to understand how model performance evolves and when retraining helps.

This helps us predict what to expect for the 2025-26 second half.

Usage:
    # Run full analysis
    PYTHONPATH=. python ml/experiments/last_season_analysis.py

    # Quick test with one training window
    PYTHONPATH=. python ml/experiments/last_season_analysis.py --quick

    # Analyze specific aspect
    PYTHONPATH=. python ml/experiments/last_season_analysis.py --analyze-decay

Session 67 - ML Experimentation Roadmap
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import json
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
import catboost as cb

PROJECT_ID = "nba-props-platform"

# 2024-25 season dates (for comparison with 2025-26)
SEASON_2024_25 = {
    'start': '2024-10-22',
    'end': '2025-06-15',
    'trade_deadline': '2025-02-06',
    'all_star_break_start': '2025-02-14',
    'all_star_break_end': '2025-02-20',
    'playoffs_start': '2025-04-19',
}

# Training windows to simulate (equivalent to our current position)
TRAINING_WINDOWS = [
    # Initial: equivalent to our current V9 (Nov - early Jan)
    {
        'name': 'initial_jan',
        'train_start': '2024-11-02',
        'train_end': '2025-01-08',
        'description': 'Equivalent to V9 initial training'
    },
    # Monthly retrains
    {
        'name': 'retrain_jan',
        'train_start': '2024-11-02',
        'train_end': '2025-01-31',
        'description': 'January retrain'
    },
    {
        'name': 'retrain_feb',
        'train_start': '2024-11-02',
        'train_end': '2025-02-28',
        'description': 'February retrain (post trade deadline)'
    },
    {
        'name': 'retrain_mar',
        'train_start': '2024-11-02',
        'train_end': '2025-03-31',
        'description': 'March retrain'
    },
    {
        'name': 'retrain_apr',
        'train_start': '2024-11-02',
        'train_end': '2025-04-15',
        'description': 'Pre-playoffs retrain'
    },
]

# Evaluation periods to test each model on
EVAL_PERIODS = [
    {
        'name': 'jan_holdout',
        'start': '2025-01-09',
        'end': '2025-01-31',
        'description': 'January holdout (like our current eval)'
    },
    {
        'name': 'february',
        'start': '2025-02-01',
        'end': '2025-02-28',
        'description': 'February (includes trade deadline adjustment)'
    },
    {
        'name': 'march',
        'start': '2025-03-01',
        'end': '2025-03-31',
        'description': 'March (playoff push)'
    },
    {
        'name': 'april_regular',
        'start': '2025-04-01',
        'end': '2025-04-18',
        'description': 'End of regular season'
    },
    {
        'name': 'playoffs',
        'start': '2025-04-19',
        'end': '2025-06-15',
        'description': 'Playoff games'
    },
]

FEATURES = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days",
    "fatigue_score", "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back", "playoff_game",
    "pct_paint", "pct_mid_range", "pct_three", "pct_free_throw",
    "team_pace", "team_off_rating", "team_win_pct",
    "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line",
    "avg_points_vs_opponent", "games_vs_opponent",
    "minutes_avg_last_10", "ppm_avg_last_10",
]


@dataclass
class ExperimentResult:
    training_window: str
    eval_period: str
    train_samples: int
    eval_samples: int
    mae: float
    hit_rate_all: Optional[float]
    hit_rate_high_edge: Optional[float]
    hit_rate_premium: Optional[float]
    bets_all: int
    bets_high_edge: int
    bets_premium: int


def parse_args():
    parser = argparse.ArgumentParser(description='Analyze last season performance trajectory')
    parser.add_argument('--quick', action='store_true', help='Quick test with one window')
    parser.add_argument('--analyze-decay', action='store_true', help='Focus on performance decay analysis')
    parser.add_argument('--output', default=None, help='Output file for results')
    return parser.parse_args()


def load_train_data(client: bigquery.Client, start: str, end: str) -> pd.DataFrame:
    """Load training data from feature store."""
    query = f"""
    SELECT mf.features, pgs.points as actual_points
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    WHERE mf.game_date BETWEEN '{start}' AND '{end}'
      AND mf.feature_count >= 33
      AND pgs.points IS NOT NULL AND pgs.minutes_played > 0
    """
    return client.query(query).to_dataframe()


def load_eval_data(client: bigquery.Client, start: str, end: str) -> pd.DataFrame:
    """Load eval data with Vegas lines."""
    query = f"""
    WITH lines AS (
      SELECT game_date, player_lookup, points_line as line
      FROM `{PROJECT_ID}.nba_raw.bettingpros_player_points_props`
      WHERE bookmaker = 'BettingPros Consensus' AND bet_side = 'over'
        AND game_date BETWEEN '{start}' AND '{end}'
      QUALIFY ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup ORDER BY processed_at DESC) = 1
    )
    SELECT mf.features, pgs.points as actual_points, l.line as vegas_line
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    JOIN lines l ON mf.player_lookup = l.player_lookup AND mf.game_date = l.game_date
    WHERE mf.game_date BETWEEN '{start}' AND '{end}'
      AND mf.feature_count >= 33 AND pgs.points IS NOT NULL
      AND (l.line - FLOOR(l.line)) IN (0, 0.5)
    """
    return client.query(query).to_dataframe()


def prepare_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, np.ndarray]:
    """Prepare feature matrix."""
    X = pd.DataFrame([row[:33] for row in df['features'].tolist()], columns=FEATURES)
    X = X.fillna(X.median())
    y = df['actual_points'].astype(float).values
    return X, y


def compute_hit_rates(preds: np.ndarray, actuals: np.ndarray, lines: np.ndarray,
                      stds: np.ndarray) -> Dict:
    """Compute hit rates for different filters."""
    edges = preds - lines

    def calc_hit_rate(mask):
        if mask.sum() == 0:
            return None, 0
        b_actual = actuals[mask]
        b_lines = lines[mask]
        b_over = edges[mask] > 0
        wins = ((b_actual > b_lines) & b_over) | ((b_actual < b_lines) & ~b_over)
        pushes = b_actual == b_lines
        graded = len(b_actual) - pushes.sum()
        return round(wins.sum() / graded * 100, 2) if graded > 0 else None, int(graded)

    # All predictions with edge >= 1
    mask_all = np.abs(edges) >= 1
    hr_all, n_all = calc_hit_rate(mask_all)

    # High edge (5+)
    mask_high = np.abs(edges) >= 5
    hr_high, n_high = calc_hit_rate(mask_high)

    # Premium-like (edge >= 3 and std < 6)
    mask_premium = (np.abs(edges) >= 3) & (stds < 6)
    hr_prem, n_prem = calc_hit_rate(mask_premium)

    return {
        'hit_rate_all': hr_all, 'bets_all': n_all,
        'hit_rate_high_edge': hr_high, 'bets_high_edge': n_high,
        'hit_rate_premium': hr_prem, 'bets_premium': n_prem,
    }


def train_and_evaluate(client: bigquery.Client,
                       train_start: str, train_end: str,
                       eval_start: str, eval_end: str,
                       training_name: str, eval_name: str) -> Optional[ExperimentResult]:
    """Train a model and evaluate on a period."""

    # Load data
    df_train = load_train_data(client, train_start, train_end)
    if len(df_train) < 1000:
        print(f"  Skipping {training_name} -> {eval_name}: only {len(df_train)} training samples")
        return None

    df_eval = load_eval_data(client, eval_start, eval_end)
    if len(df_eval) < 50:
        print(f"  Skipping {training_name} -> {eval_name}: only {len(df_eval)} eval samples")
        return None

    # Prepare features
    X_train, y_train = prepare_features(df_train)
    X_eval, y_eval = prepare_features(df_eval)
    lines = df_eval['vegas_line'].values
    stds = X_eval['points_std_last_10'].values

    # Train model
    model = cb.CatBoostRegressor(
        iterations=500, learning_rate=0.05, depth=6,
        l2_leaf_reg=3, random_seed=42, verbose=0, early_stopping_rounds=50
    )
    model.fit(X_train, y_train, eval_set=(X_eval[:500], y_eval[:500]) if len(y_eval) > 500 else None, verbose=0)

    # Evaluate
    preds = model.predict(X_eval)
    mae = mean_absolute_error(y_eval, preds)
    hit_rates = compute_hit_rates(preds, y_eval, lines, stds)

    return ExperimentResult(
        training_window=training_name,
        eval_period=eval_name,
        train_samples=len(df_train),
        eval_samples=len(df_eval),
        mae=round(mae, 3),
        hit_rate_all=hit_rates['hit_rate_all'],
        hit_rate_high_edge=hit_rates['hit_rate_high_edge'],
        hit_rate_premium=hit_rates['hit_rate_premium'],
        bets_all=hit_rates['bets_all'],
        bets_high_edge=hit_rates['bets_high_edge'],
        bets_premium=hit_rates['bets_premium'],
    )


def analyze_performance_decay(results: List[ExperimentResult]):
    """Analyze how performance decays over time without retraining."""
    print("\n" + "=" * 70)
    print(" PERFORMANCE DECAY ANALYSIS")
    print("=" * 70)

    # Group by training window
    by_training = {}
    for r in results:
        if r.training_window not in by_training:
            by_training[r.training_window] = []
        by_training[r.training_window].append(r)

    for training, evals in by_training.items():
        print(f"\nTraining: {training}")
        print("-" * 50)
        print(f"{'Eval Period':<20} {'MAE':>6} {'HR All':>8} {'HR High':>8} {'HR Prem':>8}")
        for r in sorted(evals, key=lambda x: x.eval_period):
            hr_all = f"{r.hit_rate_all:.1f}%" if r.hit_rate_all else "N/A"
            hr_high = f"{r.hit_rate_high_edge:.1f}%" if r.hit_rate_high_edge else "N/A"
            hr_prem = f"{r.hit_rate_premium:.1f}%" if r.hit_rate_premium else "N/A"
            print(f"{r.eval_period:<20} {r.mae:>6.2f} {hr_all:>8} {hr_high:>8} {hr_prem:>8}")


def analyze_retraining_benefit(results: List[ExperimentResult]):
    """Analyze when retraining provides the most benefit."""
    print("\n" + "=" * 70)
    print(" RETRAINING BENEFIT ANALYSIS")
    print("=" * 70)

    # For each eval period, compare models trained at different times
    eval_periods = set(r.eval_period for r in results)

    for eval_period in sorted(eval_periods):
        period_results = [r for r in results if r.eval_period == eval_period]
        if len(period_results) < 2:
            continue

        print(f"\nEval: {eval_period}")
        print("-" * 50)
        best = min(period_results, key=lambda x: x.mae)
        worst = max(period_results, key=lambda x: x.mae)

        for r in sorted(period_results, key=lambda x: x.mae):
            marker = " *BEST*" if r == best else ""
            print(f"  {r.training_window:<20} MAE={r.mae:.2f}, HR={r.hit_rate_all or 'N/A'}{marker}")

        improvement = worst.mae - best.mae
        print(f"  Retraining improvement: {improvement:.2f} MAE ({improvement/worst.mae*100:.1f}%)")


def main():
    args = parse_args()
    client = bigquery.Client(project=PROJECT_ID)

    print("=" * 70)
    print(" LAST SEASON (2024-25) PERFORMANCE ANALYSIS")
    print(" Simulating model training and evaluation to predict 2025-26 trajectory")
    print("=" * 70)

    # Select windows based on mode
    if args.quick:
        windows = TRAINING_WINDOWS[:1]
        periods = EVAL_PERIODS[:2]
    else:
        windows = TRAINING_WINDOWS
        periods = EVAL_PERIODS

    results = []

    # Run all combinations
    for window in windows:
        print(f"\n--- Training Window: {window['name']} ---")
        print(f"    {window['train_start']} to {window['train_end']}")

        for period in periods:
            # Skip if eval period is before training end
            if period['start'] < window['train_end']:
                continue

            print(f"  Evaluating on {period['name']}...")
            result = train_and_evaluate(
                client,
                window['train_start'], window['train_end'],
                period['start'], period['end'],
                window['name'], period['name']
            )
            if result:
                results.append(result)
                print(f"    MAE={result.mae:.2f}, HR_all={result.hit_rate_all or 'N/A'}, "
                      f"HR_prem={result.hit_rate_premium or 'N/A'} (n={result.bets_premium})")

    # Analysis
    if results:
        analyze_performance_decay(results)
        analyze_retraining_benefit(results)

        # Summary
        print("\n" + "=" * 70)
        print(" KEY FINDINGS")
        print("=" * 70)

        # Find optimal retraining frequency
        best_by_period = {}
        for r in results:
            if r.eval_period not in best_by_period or r.mae < best_by_period[r.eval_period].mae:
                best_by_period[r.eval_period] = r

        print("\nOptimal training window for each eval period:")
        for period, best in sorted(best_by_period.items()):
            print(f"  {period}: train with {best.training_window} (MAE={best.mae:.2f})")

    # Save results
    if args.output and results:
        output_data = [vars(r) for r in results]
        with open(args.output, 'w') as f:
            json.dump(output_data, f, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()

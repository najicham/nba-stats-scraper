#!/usr/bin/env python3
"""
Quick Model Retrain - Simple Monthly Retraining Script

Designed for the /model-experiment skill and monthly retraining pipeline.
Trains a CatBoost model on recent data and evaluates against V8 baseline.

Usage:
    # Quick retrain with defaults (last 60 days training, last 7 days eval)
    PYTHONPATH=. python ml/experiments/quick_retrain.py --name "FEB_MONTHLY"

    # Custom dates
    PYTHONPATH=. python ml/experiments/quick_retrain.py \
        --name "JAN_CUSTOM" \
        --train-start 2025-12-01 --train-end 2026-01-20 \
        --eval-start 2026-01-21 --eval-end 2026-01-28

    # Use different line source (default is draftkings to match production)
    PYTHONPATH=. python ml/experiments/quick_retrain.py \
        --name "V9_VERIFY" \
        --line-source draftkings

    # Dry run
    PYTHONPATH=. python ml/experiments/quick_retrain.py --name "TEST" --dry-run

Features:
- Simple date range defaults (--train-days 60, --eval-days 7)
- Production-equivalent evaluation with configurable line source (default: DraftKings)
- Automatic comparison to V8 baseline
- Registers in ml_experiments table
- Clear recommendation output

Session 58 - Monthly Retraining Infrastructure
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import uuid
import json
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta, timezone
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split
import catboost as cb

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models")

# V8 baseline (updated from production prediction_accuracy Jan 2026)
V8_BASELINE = {
    "mae": 5.36,
    "hit_rate_all": 50.24,
    "hit_rate_premium": 78.5,  # 92+ conf, 3+ edge
    "hit_rate_high_edge": 62.8,  # 5+ edge
}

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


def parse_args():
    parser = argparse.ArgumentParser(description='Quick model retrain for monthly updates')
    parser.add_argument('--name', required=True, help='Experiment name (e.g., FEB_MONTHLY)')
    parser.add_argument('--hypothesis', default='', help='What we are testing')
    parser.add_argument('--tags', default='monthly', help='Comma-separated tags')

    # Explicit dates
    parser.add_argument('--train-start', help='Training start (YYYY-MM-DD)')
    parser.add_argument('--train-end', help='Training end (YYYY-MM-DD)')
    parser.add_argument('--eval-start', help='Eval start (YYYY-MM-DD)')
    parser.add_argument('--eval-end', help='Eval end (YYYY-MM-DD)')

    # Relative dates (defaults)
    parser.add_argument('--train-days', type=int, default=60, help='Days of training (default: 60)')
    parser.add_argument('--eval-days', type=int, default=7, help='Days of eval (default: 7)')

    # Line source for evaluation
    parser.add_argument('--line-source', choices=['draftkings', 'bettingpros', 'fanduel'],
                       default='draftkings',
                       help='Sportsbook for eval lines (default: draftkings to match production)')

    parser.add_argument('--dry-run', action='store_true', help='Show plan only')
    parser.add_argument('--skip-register', action='store_true', help='Skip ml_experiments')
    return parser.parse_args()


def get_dates(args):
    """Compute date ranges."""
    if args.train_start and args.train_end and args.eval_start and args.eval_end:
        return {
            'train_start': args.train_start,
            'train_end': args.train_end,
            'eval_start': args.eval_start,
            'eval_end': args.eval_end,
        }

    yesterday = date.today() - timedelta(days=1)
    eval_end = yesterday
    eval_start = eval_end - timedelta(days=args.eval_days - 1)
    train_end = eval_start - timedelta(days=1)
    train_start = train_end - timedelta(days=args.train_days - 1)

    return {
        'train_start': train_start.strftime('%Y-%m-%d'),
        'train_end': train_end.strftime('%Y-%m-%d'),
        'eval_start': eval_start.strftime('%Y-%m-%d'),
        'eval_end': eval_end.strftime('%Y-%m-%d'),
    }


def load_train_data(client, start, end):
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


def load_eval_data(client, start, end, line_source='draftkings'):
    """Load eval data with real prop lines.

    Args:
        client: BigQuery client
        start: Start date (YYYY-MM-DD)
        end: End date (YYYY-MM-DD)
        line_source: 'draftkings' (default, matches production), 'bettingpros', or 'fanduel'
    """
    # Configure table and filter based on line source
    if line_source == 'draftkings':
        table = f"`{PROJECT_ID}.nba_raw.odds_api_player_points_props`"
        bookmaker_filter = "bookmaker = 'draftkings'"
        line_col = "points_line"
    elif line_source == 'fanduel':
        table = f"`{PROJECT_ID}.nba_raw.odds_api_player_points_props`"
        bookmaker_filter = "bookmaker = 'fanduel'"
        line_col = "points_line"
    else:  # bettingpros
        table = f"`{PROJECT_ID}.nba_raw.bettingpros_player_points_props`"
        bookmaker_filter = "bookmaker = 'BettingPros Consensus' AND bet_side = 'over'"
        line_col = "points_line"

    query = f"""
    WITH lines AS (
      SELECT game_date, player_lookup, {line_col} as line
      FROM {table}
      WHERE {bookmaker_filter}
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


def prepare_features(df):
    """Prepare feature matrix."""
    X = pd.DataFrame([row[:33] for row in df['features'].tolist()], columns=FEATURES)
    X = X.fillna(X.median())
    y = df['actual_points'].astype(float)
    return X, y


def compute_hit_rate(preds, actuals, lines, min_edge=1.0):
    """Compute hit rate for given edge threshold."""
    edges = preds - lines
    mask = np.abs(edges) >= min_edge
    if mask.sum() == 0:
        return None, 0

    b_actual = actuals[mask]
    b_lines = lines[mask]
    b_over = edges[mask] > 0

    wins = ((b_actual > b_lines) & b_over) | ((b_actual < b_lines) & ~b_over)
    pushes = b_actual == b_lines
    graded = len(b_actual) - pushes.sum()

    return round(wins.sum() / graded * 100, 2) if graded > 0 else None, int(graded)


def main():
    args = parse_args()
    dates = get_dates(args)
    exp_id = str(uuid.uuid4())[:8]

    # Compute actual day counts from dates
    train_start_dt = datetime.strptime(dates['train_start'], '%Y-%m-%d').date()
    train_end_dt = datetime.strptime(dates['train_end'], '%Y-%m-%d').date()
    eval_start_dt = datetime.strptime(dates['eval_start'], '%Y-%m-%d').date()
    eval_end_dt = datetime.strptime(dates['eval_end'], '%Y-%m-%d').date()
    train_days_actual = (train_end_dt - train_start_dt).days + 1
    eval_days_actual = (eval_end_dt - eval_start_dt).days + 1

    print("=" * 70)
    print(f" QUICK RETRAIN: {args.name}")
    print("=" * 70)
    print(f"Training:   {dates['train_start']} to {dates['train_end']} ({train_days_actual} days)")
    print(f"Evaluation: {dates['eval_start']} to {dates['eval_end']} ({eval_days_actual} days)")
    print(f"Line Source: {args.line_source}")
    print()

    if args.dry_run:
        print("DRY RUN - would train on above dates and compare to V8 baseline")
        return

    client = bigquery.Client(project=PROJECT_ID)

    # Load data
    print("Loading training data...")
    df_train = load_train_data(client, dates['train_start'], dates['train_end'])
    print(f"  {len(df_train):,} samples")

    print("Loading evaluation data...")
    df_eval = load_eval_data(client, dates['eval_start'], dates['eval_end'], args.line_source)
    print(f"  {len(df_eval):,} samples")

    if len(df_train) < 1000 or len(df_eval) < 100:
        print("ERROR: Not enough data")
        return

    # Prepare
    X_train_full, y_train_full = prepare_features(df_train)
    X_eval, y_eval = prepare_features(df_eval)
    lines = df_eval['vegas_line'].values

    X_train, X_val, y_train, y_val = train_test_split(X_train_full, y_train_full, test_size=0.15, random_state=42)

    # Train
    print("\nTraining CatBoost...")
    model = cb.CatBoostRegressor(
        iterations=1000, learning_rate=0.05, depth=6,
        l2_leaf_reg=3, random_seed=42, verbose=100, early_stopping_rounds=50
    )
    model.fit(X_train, y_train, eval_set=(X_val, y_val), verbose=100)

    # Evaluate
    print("\nEvaluating...")
    preds = model.predict(X_eval)
    mae = mean_absolute_error(y_eval, preds)

    hr_all, bets_all = compute_hit_rate(preds, y_eval.values, lines, min_edge=1.0)
    hr_high, bets_high = compute_hit_rate(preds, y_eval.values, lines, min_edge=5.0)

    # Approximate premium (using std for high consistency)
    std = X_eval['points_std_last_10'].values
    edges = np.abs(preds - lines)
    premium_mask = (std < 6) & (edges >= 3)
    if premium_mask.sum() > 0:
        hr_prem, bets_prem = compute_hit_rate(
            preds[premium_mask], y_eval.values[premium_mask], lines[premium_mask], min_edge=0
        )
    else:
        hr_prem, bets_prem = None, 0

    # Save model
    MODEL_OUTPUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    model_path = MODEL_OUTPUT_DIR / f"catboost_retrain_{args.name}_{ts}.cbm"
    model.save_model(str(model_path))

    # Results
    print("\n" + "=" * 70)
    print(" RESULTS vs V8 BASELINE")
    print("=" * 70)

    MIN_BETS_RELIABLE = 50  # Minimum bets for statistically reliable hit rate

    def compare(name, new_val, baseline, n_bets, higher_better=True):
        if new_val is None:
            return f"{name}: N/A", None
        diff = new_val - baseline
        symbol = "+" if diff > 0 else ""
        better = (diff > 0) == higher_better

        # Add sample size warning
        size_warn = "" if n_bets >= MIN_BETS_RELIABLE else f" (n={n_bets}, LOW)"

        emoji = "✅" if better else "❌" if abs(diff) > 2 else "⚠️"
        return f"{name}: {new_val:.2f}% vs {baseline:.2f}% ({symbol}{diff:.2f}%) {emoji}{size_warn}", better

    mae_diff = mae - V8_BASELINE['mae']
    mae_emoji = "✅" if mae_diff < 0 else "❌" if mae_diff > 0.2 else "⚠️"
    print(f"MAE: {mae:.4f} vs {V8_BASELINE['mae']:.4f} ({mae_diff:+.4f}) {mae_emoji}")
    print()

    hr_all_str, hr_all_better = compare("Hit Rate (all)", hr_all, V8_BASELINE['hit_rate_all'], bets_all)
    hr_high_str, hr_high_better = compare("Hit Rate (high edge 5+)", hr_high, V8_BASELINE['hit_rate_high_edge'], bets_high)
    hr_prem_str, hr_prem_better = compare("Hit Rate (premium ~92+/3+)", hr_prem, V8_BASELINE['hit_rate_premium'], bets_prem)

    print(hr_all_str)
    print(hr_high_str)
    print(hr_prem_str)

    # Recommendation with sample size awareness
    print("\n" + "-" * 40)
    mae_better = mae < V8_BASELINE['mae']

    # Check filtered metrics only if sample size is reliable
    high_edge_reliable = bets_high >= MIN_BETS_RELIABLE
    premium_reliable = bets_prem >= MIN_BETS_RELIABLE

    # Warnings for low sample sizes
    if not high_edge_reliable or not premium_reliable:
        print(f"⚠️  LOW SAMPLE SIZE: high_edge={bets_high}, premium={bets_prem} (need {MIN_BETS_RELIABLE}+)")
        print("    Filtered hit rates are NOT statistically reliable.")
        print()

    # Core decision: MAE + overall hit rate (always reliable with enough eval data)
    if mae_better and hr_all_better:
        if high_edge_reliable and hr_high_better is False:
            print("⚠️ MIXED: Better MAE/overall but worse on high-edge filter")
        elif premium_reliable and hr_prem_better is False:
            print("⚠️ MIXED: Better MAE/overall but worse on premium filter")
        else:
            print("✅ RECOMMEND: Beats V8 on MAE and hit rate - consider shadow mode")
    elif mae_better:
        print("⚠️ MIXED: Better MAE but similar/lower hit rate")
    elif hr_all_better:
        print("⚠️ MIXED: Better hit rate but worse MAE")
    else:
        print("❌ V8 still better - try different training window")

    print(f"\nModel saved: {model_path}")

    # Register
    if not args.skip_register:
        try:
            row = {
                'experiment_id': exp_id,
                'experiment_name': args.name,
                'experiment_type': 'monthly_retrain',
                'hypothesis': args.hypothesis or f'Monthly retrain {train_days_actual}d train, {eval_days_actual}d eval',
                'config_json': json.dumps({'train_days': train_days_actual, 'eval_days': eval_days_actual, 'features': 33, 'line_source': args.line_source}),
                'train_period': {'start_date': dates['train_start'], 'end_date': dates['train_end'], 'samples': len(df_train)},
                'eval_period': {'start_date': dates['eval_start'], 'end_date': dates['eval_end'], 'samples': len(df_eval)},
                'results_json': json.dumps({
                    'mae': round(mae, 4),
                    'hit_rate_all': hr_all, 'bets_all': bets_all,
                    'hit_rate_high_edge': hr_high, 'bets_high_edge': bets_high,
                    'hit_rate_premium': hr_prem, 'bets_premium': bets_prem,
                }),
                'model_path': str(model_path),
                'status': 'completed',
                'tags': [t.strip() for t in args.tags.split(',') if t.strip()],
                'created_at': datetime.now(timezone.utc).isoformat(),
                'completed_at': datetime.now(timezone.utc).isoformat(),
            }
            errors = client.insert_rows_json(f"{PROJECT_ID}.nba_predictions.ml_experiments", [row])
            if not errors:
                print(f"Registered in ml_experiments (ID: {exp_id})")
        except Exception as e:
            print(f"Warning: Could not register: {e}")


if __name__ == "__main__":
    main()

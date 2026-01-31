#!/usr/bin/env python3
"""
January 2026 Backfill Experiment

This script runs a comprehensive experiment to test which model configurations
would have performed best during January 2026 (when V8 degraded due to feature bug).

Experiments:
  V8_BASELINE:      Production V8 training (2021-2024)
  V9_RECENT:        Train on 2023-2025 data only
  V9_RECENCY_180:   2021-2025 with 180-day recency weighting
  V9_RECENCY_90:    2021-2025 with 90-day recency weighting
  V9_CURRENT_SZN:   Train only on Oct 2025 - Jan 15 2026

Usage:
    # Run all experiments
    PYTHONPATH=. python ml/experiments/run_january_backfill_experiment.py

    # Run specific experiment
    PYTHONPATH=. python ml/experiments/run_january_backfill_experiment.py --experiment V9_RECENCY_180

    # Dry run (don't train, just show plan)
    PYTHONPATH=. python ml/experiments/run_january_backfill_experiment.py --dry-run
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import numpy as np
import pandas as pd
import json
from datetime import datetime
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
import catboost as cb

PROJECT_ID = "nba-props-platform"
RESULTS_DIR = Path(__file__).parent / "results"

# Evaluation period: January 2026 (the period that degraded)
EVAL_START = "2026-01-01"
EVAL_END = "2026-01-28"

# Feature names for 33-feature V8 model
ALL_FEATURES = [
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

# Experiment configurations
EXPERIMENTS = {
    "V8_BASELINE": {
        "description": "Production V8 baseline (2021-2024 training)",
        "train_start": "2021-11-01",
        "train_end": "2024-06-01",
        "recency_weighting": False,
        "half_life": None,
    },
    "V9_RECENT_2YR": {
        "description": "Recent 2 years only (2023-2025)",
        "train_start": "2023-10-01",
        "train_end": "2025-12-31",
        "recency_weighting": False,
        "half_life": None,
    },
    "V9_RECENCY_180": {
        "description": "Full data with 180-day half-life recency weighting",
        "train_start": "2021-11-01",
        "train_end": "2025-12-31",
        "recency_weighting": True,
        "half_life": 180,
    },
    "V9_RECENCY_90": {
        "description": "Full data with 90-day half-life recency weighting",
        "train_start": "2021-11-01",
        "train_end": "2025-12-31",
        "recency_weighting": True,
        "half_life": 90,
    },
    "V9_CURRENT_SEASON": {
        "description": "Current season only (Oct 2025 - Jan 15 2026)",
        "train_start": "2025-10-01",
        "train_end": "2025-12-31",  # Use Dec to avoid leaking Jan eval data
        "recency_weighting": False,
        "half_life": None,
    },
}

# Betting constants
WIN_PAYOUT = 100 / 110
LOSS_PAYOUT = -1.0
BREAKEVEN_HIT_RATE = 1 / (1 + WIN_PAYOUT)


def calculate_sample_weights(dates: pd.Series, half_life_days: int) -> np.ndarray:
    """Calculate exponential recency weights"""
    dates = pd.to_datetime(dates)
    max_date = dates.max()
    days_old = (max_date - dates).dt.days
    decay_rate = np.log(2) / half_life_days
    weights = np.exp(-days_old * decay_rate)
    return (weights / weights.mean()).values


def get_training_data(client: bigquery.Client, train_start: str, train_end: str) -> pd.DataFrame:
    """Fetch training data from feature store"""
    query = f"""
    SELECT
      mf.player_lookup,
      mf.game_date,
      mf.features,
      pgs.points as actual_points
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
    INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup
      AND mf.game_date = pgs.game_date
    WHERE mf.game_date BETWEEN '{train_start}' AND '{train_end}'
      AND mf.feature_count >= 33
      AND ARRAY_LENGTH(mf.features) >= 33
      AND pgs.points IS NOT NULL
    ORDER BY mf.game_date
    """
    return client.query(query).to_dataframe()


def get_evaluation_data(client: bigquery.Client, eval_start: str, eval_end: str) -> pd.DataFrame:
    """Fetch evaluation data with Vegas lines"""
    query = f"""
    SELECT
      mf.player_lookup,
      mf.game_date,
      mf.features,
      mf.features[OFFSET(25)] as vegas_points_line,
      mf.features[OFFSET(28)] as has_vegas_line,
      pgs.points as actual_points
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
    INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup
      AND mf.game_date = pgs.game_date
    WHERE mf.game_date BETWEEN '{eval_start}' AND '{eval_end}'
      AND mf.feature_count >= 33
      AND ARRAY_LENGTH(mf.features) >= 33
      AND pgs.points IS NOT NULL
    ORDER BY mf.game_date
    """
    return client.query(query).to_dataframe()


def prepare_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Unpack feature arrays into DataFrame"""
    X = pd.DataFrame(
        [row[:33] for row in df['features'].tolist()],
        columns=ALL_FEATURES
    )
    X = X.fillna(X.median())
    y = df['actual_points'].astype(float)
    return X, y


def train_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    sample_weights: np.ndarray = None,
) -> cb.CatBoostRegressor:
    """Train CatBoost with V8 hyperparameters"""
    model = cb.CatBoostRegressor(
        depth=6,
        learning_rate=0.07,
        l2_leaf_reg=3.8,
        subsample=0.72,
        min_data_in_leaf=16,
        iterations=1000,
        random_seed=42,
        verbose=False,
        early_stopping_rounds=50
    )
    model.fit(X_train, y_train, eval_set=(X_val, y_val), sample_weight=sample_weights)
    return model


def calculate_betting_metrics(predictions: np.ndarray, actuals: np.ndarray, lines: np.ndarray, min_edge: float = 1.0) -> dict:
    """Calculate betting metrics"""
    valid_mask = ~np.isnan(lines)
    if not valid_mask.any():
        return {"hit_rate": None, "bets_placed": 0}

    preds = predictions[valid_mask]
    acts = actuals[valid_mask]
    lns = lines[valid_mask]
    edges = preds - lns

    over_bets = edges >= min_edge
    under_bets = edges <= -min_edge
    bet_mask = over_bets | under_bets

    if not bet_mask.any():
        return {"hit_rate": None, "bets_placed": 0}

    bet_acts = acts[bet_mask]
    bet_lines = lns[bet_mask]
    bet_over = over_bets[bet_mask]

    over_wins = (bet_acts > bet_lines) & bet_over
    under_wins = (bet_acts < bet_lines) & ~bet_over
    pushes = bet_acts == bet_lines
    hits = over_wins | under_wins

    n_hits = hits.sum()
    n_graded = bet_mask.sum() - pushes.sum()
    hit_rate = n_hits / n_graded if n_graded > 0 else None
    profit = n_hits * WIN_PAYOUT + (n_graded - n_hits) * LOSS_PAYOUT
    roi = profit / bet_mask.sum() if bet_mask.sum() > 0 else None

    return {
        "hit_rate_pct": round(hit_rate * 100, 2) if hit_rate else None,
        "hits": int(n_hits),
        "bets_graded": int(n_graded),
        "roi_pct": round(roi * 100, 2) if roi else None,
        "profit": round(profit, 2),
    }


def run_experiment(
    client: bigquery.Client,
    exp_name: str,
    config: dict,
    eval_df: pd.DataFrame,
    dry_run: bool = False
) -> dict:
    """Run a single experiment"""
    print(f"\n{'='*60}")
    print(f"EXPERIMENT: {exp_name}")
    print(f"{'='*60}")
    print(f"Description: {config['description']}")
    print(f"Training: {config['train_start']} to {config['train_end']}")
    if config['recency_weighting']:
        print(f"Recency weighting: {config['half_life']}-day half-life")

    if dry_run:
        print("DRY RUN - skipping training")
        return {"experiment": exp_name, "status": "dry_run"}

    # Get training data
    print("\nLoading training data...")
    train_df = get_training_data(client, config['train_start'], config['train_end'])
    print(f"Loaded {len(train_df):,} training samples")

    if len(train_df) < 1000:
        print("WARNING: Too few training samples, skipping")
        return {"experiment": exp_name, "status": "skipped", "reason": "too_few_samples"}

    # Prepare features
    X_train_full, y_train_full = prepare_features(train_df)

    # Chronological split for validation
    n = len(X_train_full)
    split_idx = int(n * 0.85)
    X_train = X_train_full.iloc[:split_idx]
    X_val = X_train_full.iloc[split_idx:]
    y_train = y_train_full.iloc[:split_idx]
    y_val = y_train_full.iloc[split_idx:]

    # Calculate sample weights if needed
    sample_weights = None
    if config['recency_weighting']:
        train_dates = train_df.iloc[:split_idx]['game_date']
        sample_weights = calculate_sample_weights(train_dates, config['half_life'])
        print(f"Sample weights: min={sample_weights.min():.3f}, max={sample_weights.max():.3f}")

    # Train model
    print("\nTraining model...")
    model = train_model(X_train, y_train, X_val, y_val, sample_weights)
    print(f"Best iteration: {model.get_best_iteration()}")

    # Evaluate on January 2026
    print("\nEvaluating on January 2026...")
    X_eval, y_eval = prepare_features(eval_df)
    predictions = model.predict(X_eval)

    mae = mean_absolute_error(y_eval, predictions)
    print(f"MAE: {mae:.4f}")

    # Get Vegas lines for betting metrics
    lines = eval_df['vegas_points_line'].values.copy()
    has_real_line = eval_df['has_vegas_line'].values == 1.0
    lines[~has_real_line] = np.nan

    betting = calculate_betting_metrics(predictions, y_eval.values, lines)
    print(f"Hit Rate: {betting.get('hit_rate_pct', 'N/A')}% ({betting.get('hits', 0)}/{betting.get('bets_graded', 0)})")
    print(f"ROI: {betting.get('roi_pct', 'N/A')}%")

    # Save model
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    model_path = RESULTS_DIR / f"catboost_jan_exp_{exp_name}_{timestamp}.cbm"
    model.save_model(str(model_path))
    print(f"Saved model to {model_path}")

    return {
        "experiment": exp_name,
        "config": config,
        "training_samples": len(train_df),
        "eval_samples": len(eval_df),
        "results": {
            "mae": round(mae, 4),
            "betting": betting,
        },
        "model_path": str(model_path),
        "timestamp": timestamp,
    }


def main():
    parser = argparse.ArgumentParser(description="Run January 2026 backfill experiments")
    parser.add_argument("--experiment", type=str, help="Run specific experiment only")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without running")
    args = parser.parse_args()

    print("=" * 70)
    print(" JANUARY 2026 BACKFILL EXPERIMENT")
    print("=" * 70)
    print(f"Evaluation period: {EVAL_START} to {EVAL_END}")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if args.dry_run:
        print("\n*** DRY RUN MODE ***\n")

    # Select experiments to run
    experiments = EXPERIMENTS
    if args.experiment:
        if args.experiment not in EXPERIMENTS:
            print(f"Error: Unknown experiment '{args.experiment}'")
            print(f"Available: {list(EXPERIMENTS.keys())}")
            return
        experiments = {args.experiment: EXPERIMENTS[args.experiment]}

    print(f"\nExperiments to run: {list(experiments.keys())}")

    # Initialize
    client = bigquery.Client(project=PROJECT_ID)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load evaluation data once (shared across experiments)
    print("\nLoading January 2026 evaluation data...")
    eval_df = get_evaluation_data(client, EVAL_START, EVAL_END)
    print(f"Loaded {len(eval_df):,} evaluation samples")
    vegas_coverage = (eval_df['has_vegas_line'] == 1.0).mean()
    print(f"Vegas line coverage: {vegas_coverage:.1%}")

    # Run experiments
    all_results = []
    for exp_name, config in experiments.items():
        result = run_experiment(client, exp_name, config, eval_df, args.dry_run)
        all_results.append(result)

    # Summary
    print("\n" + "=" * 70)
    print(" RESULTS SUMMARY")
    print("=" * 70)
    print(f"\n{'Experiment':<20} {'Train Period':<25} {'MAE':>6} {'Hit%':>7} {'ROI%':>7}")
    print("-" * 70)

    for r in all_results:
        if r.get('status') in ['dry_run', 'skipped']:
            continue
        exp = r['experiment']
        cfg = r['config']
        train = f"{cfg['train_start'][:7]} - {cfg['train_end'][:7]}"
        mae = r['results']['mae']
        hit = r['results']['betting'].get('hit_rate_pct', 'N/A')
        roi = r['results']['betting'].get('roi_pct', 'N/A')
        print(f"{exp:<20} {train:<25} {mae:>6.2f} {hit:>6}% {roi:>6}%")

    # Save summary
    summary_path = RESULTS_DIR / f"january_backfill_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(summary_path, 'w') as f:
        json.dump({
            "eval_period": {"start": EVAL_START, "end": EVAL_END},
            "results": all_results,
            "timestamp": datetime.now().isoformat(),
        }, f, indent=2, default=str)
    print(f"\nSaved summary to {summary_path}")

    print("\n" + "=" * 70)
    print("EXPERIMENT COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()

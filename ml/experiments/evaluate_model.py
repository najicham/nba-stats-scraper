#!/usr/bin/env python3
"""
Model Evaluation Script for Walk-Forward Experiments

Evaluates a trained CatBoost model on a specified date range.
Calculates betting metrics (hit rate, ROI) and point prediction accuracy (MAE).

Usage:
    # Evaluate model A1 on 2022-23 season
    PYTHONPATH=. python ml/experiments/evaluate_model.py \
        --model-path ml/experiments/results/catboost_v9_exp_A1_*.cbm \
        --eval-start 2022-10-01 \
        --eval-end 2023-06-30 \
        --experiment-id A1

    # Evaluate with monthly breakdown
    PYTHONPATH=. python ml/experiments/evaluate_model.py \
        --model-path ml/experiments/results/catboost_v9_exp_A1_*.cbm \
        --eval-start 2022-10-01 \
        --eval-end 2023-06-30 \
        --experiment-id A1 \
        --monthly-breakdown
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import glob
import numpy as np
import pandas as pd
import json
from datetime import datetime
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
import catboost as cb

PROJECT_ID = "nba-props-platform"
RESULTS_DIR = Path(__file__).parent / "results"

# Feature names - must match feature store and training exactly (33 features)
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

# Betting constants
JUICE = -110  # Standard odds
WIN_PAYOUT = 100 / 110  # $0.909 profit per $1 bet on a win
LOSS_PAYOUT = -1.0  # $1 loss per $1 bet on a loss
BREAKEVEN_HIT_RATE = 1 / (1 + WIN_PAYOUT)  # ~52.4%


def get_evaluation_query(eval_start: str, eval_end: str) -> str:
    """
    Generate BigQuery SQL for fetching evaluation data.

    The feature store (ml_feature_store_v2) contains all 33 features including
    vegas_points_line which we need for betting metrics evaluation.
    """
    return f"""
SELECT
  mf.player_lookup,
  mf.game_date,
  mf.features,
  mf.feature_count,
  -- Extract vegas_points_line from features array (index 25)
  mf.features[OFFSET(25)] as vegas_points_line,
  pgs.points as actual_points
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
  ON mf.player_lookup = pgs.player_lookup
  AND mf.game_date = pgs.game_date
WHERE mf.game_date BETWEEN '{eval_start}' AND '{eval_end}'
  AND mf.feature_count = 33
  AND ARRAY_LENGTH(mf.features) = 33
  AND pgs.points IS NOT NULL
ORDER BY mf.game_date
"""


def prepare_features(df: pd.DataFrame, medians: dict = None) -> tuple[pd.DataFrame, pd.Series]:
    """
    Prepare feature matrix from raw dataframe.

    The feature store already has all 33 features, so we just need to
    unpack the features array into a DataFrame.

    Args:
        df: Raw dataframe from BigQuery
        medians: Optional median values for imputation (from training)

    Returns:
        X: Feature matrix (33 features)
        y: Target values (actual_points)
    """
    # Unpack features array into DataFrame with named columns
    X = pd.DataFrame(df['features'].tolist(), columns=ALL_FEATURES)

    # Use provided medians or compute from eval data
    if medians:
        for col, val in medians.items():
            if col in X.columns:
                X[col] = X[col].fillna(val)
        X = X.fillna(X.median())
    else:
        X = X.fillna(X.median())

    y = df['actual_points'].astype(float)

    return X, y


def calculate_betting_metrics(
    predictions: np.ndarray,
    actuals: np.ndarray,
    lines: np.ndarray,
    min_edge: float = 1.0
) -> dict:
    """
    Calculate betting metrics for predictions vs actual results

    Args:
        predictions: Model predictions
        actuals: Actual points scored
        lines: Vegas/betting lines
        min_edge: Minimum edge required to place a bet

    Returns:
        dict with hit_rate, roi, and other betting metrics
    """
    # Mask for games with valid lines (non-NaN)
    valid_mask = ~np.isnan(lines)

    if not valid_mask.any():
        return {
            "hit_rate": None,
            "hits": 0,
            "misses": 0,
            "pushes": 0,
            "bets_placed": 0,
            "roi": None,
            "profit": 0.0,
        }

    preds = predictions[valid_mask]
    acts = actuals[valid_mask]
    lns = lines[valid_mask]

    # Calculate edges
    edges = preds - lns

    # Determine bet direction (OVER if edge > min_edge, UNDER if edge < -min_edge)
    over_bets = edges >= min_edge
    under_bets = edges <= -min_edge
    bet_mask = over_bets | under_bets

    if not bet_mask.any():
        return {
            "hit_rate": None,
            "hits": 0,
            "misses": 0,
            "pushes": 0,
            "bets_placed": 0,
            "no_bets_reason": "No predictions exceeded minimum edge threshold",
            "roi": None,
            "profit": 0.0,
        }

    # Filter to only bets we would place
    bet_preds = preds[bet_mask]
    bet_acts = acts[bet_mask]
    bet_lines = lns[bet_mask]
    bet_edges = edges[bet_mask]
    bet_over = over_bets[bet_mask]

    # Determine outcomes
    # OVER bet wins if actual > line
    # UNDER bet wins if actual < line
    # Push if actual == line
    over_wins = (bet_acts > bet_lines) & bet_over
    under_wins = (bet_acts < bet_lines) & ~bet_over
    pushes = bet_acts == bet_lines
    hits = over_wins | under_wins
    misses = ~hits & ~pushes

    n_hits = hits.sum()
    n_misses = misses.sum()
    n_pushes = pushes.sum()
    n_bets = len(bet_preds) - n_pushes  # Pushes don't count

    hit_rate = n_hits / n_bets if n_bets > 0 else None

    # Calculate ROI
    profit = n_hits * WIN_PAYOUT + n_misses * LOSS_PAYOUT
    roi = profit / len(bet_preds) if len(bet_preds) > 0 else None

    return {
        "hit_rate": float(hit_rate) if hit_rate else None,
        "hit_rate_pct": round(hit_rate * 100, 2) if hit_rate else None,
        "hits": int(n_hits),
        "misses": int(n_misses),
        "pushes": int(n_pushes),
        "bets_placed": len(bet_preds),
        "bets_graded": int(n_bets),
        "roi": float(roi) if roi else None,
        "roi_pct": round(roi * 100, 2) if roi else None,
        "profit": float(profit),
        "breakeven_hit_rate": round(BREAKEVEN_HIT_RATE * 100, 2),
        "min_edge_threshold": min_edge,
    }


def calculate_confidence_metrics(
    predictions: np.ndarray,
    actuals: np.ndarray,
    lines: np.ndarray,
    min_edge: float = 1.0
) -> dict:
    """Calculate metrics by confidence/edge buckets"""
    valid_mask = ~np.isnan(lines)
    if not valid_mask.any():
        return {}

    preds = predictions[valid_mask]
    acts = actuals[valid_mask]
    lns = lines[valid_mask]

    edges = np.abs(preds - lns)

    # Define confidence buckets by edge size
    buckets = [
        ("high_5+", edges >= 5),
        ("medium_3-5", (edges >= 3) & (edges < 5)),
        ("low_1-3", (edges >= 1) & (edges < 3)),
        ("pass_<1", edges < 1),
    ]

    results = {}
    for bucket_name, mask in buckets:
        if not mask.any():
            results[bucket_name] = {"count": 0, "hit_rate": None}
            continue

        b_preds = preds[mask]
        b_acts = acts[mask]
        b_lines = lns[mask]
        b_edges = (b_preds - b_lines)

        # Determine wins
        over_bets = b_edges > 0
        over_wins = (b_acts > b_lines) & over_bets
        under_wins = (b_acts < b_lines) & ~over_bets
        pushes = b_acts == b_lines
        hits = over_wins | under_wins

        n_graded = mask.sum() - pushes.sum()
        hit_rate = hits.sum() / n_graded if n_graded > 0 else None

        results[bucket_name] = {
            "count": int(mask.sum()),
            "graded": int(n_graded),
            "hits": int(hits.sum()),
            "hit_rate": round(hit_rate * 100, 2) if hit_rate else None,
        }

    return results


def calculate_direction_metrics(
    predictions: np.ndarray,
    actuals: np.ndarray,
    lines: np.ndarray,
    min_edge: float = 1.0
) -> dict:
    """Calculate metrics by bet direction (OVER vs UNDER)"""
    valid_mask = ~np.isnan(lines)
    if not valid_mask.any():
        return {}

    preds = predictions[valid_mask]
    acts = actuals[valid_mask]
    lns = lines[valid_mask]

    edges = preds - lns

    results = {}
    for direction, mask in [("OVER", edges >= min_edge), ("UNDER", edges <= -min_edge)]:
        if not mask.any():
            results[direction] = {"count": 0, "hit_rate": None}
            continue

        d_acts = acts[mask]
        d_lines = lns[mask]

        if direction == "OVER":
            wins = d_acts > d_lines
        else:
            wins = d_acts < d_lines

        pushes = d_acts == d_lines
        n_graded = mask.sum() - pushes.sum()
        hit_rate = wins.sum() / n_graded if n_graded > 0 else None

        results[direction] = {
            "count": int(mask.sum()),
            "graded": int(n_graded),
            "hits": int(wins.sum()),
            "hit_rate": round(hit_rate * 100, 2) if hit_rate else None,
        }

    return results


def main():
    parser = argparse.ArgumentParser(description="Evaluate CatBoost model on specified date range")
    parser.add_argument("--model-path", required=True, help="Path to model file (supports glob patterns)")
    parser.add_argument("--eval-start", required=True, help="Evaluation start date (YYYY-MM-DD)")
    parser.add_argument("--eval-end", required=True, help="Evaluation end date (YYYY-MM-DD)")
    parser.add_argument("--experiment-id", required=True, help="Experiment identifier (e.g., A1, B2)")
    parser.add_argument("--min-edge", type=float, default=1.0, help="Minimum edge to place bet (default: 1.0)")
    parser.add_argument("--monthly-breakdown", action="store_true", help="Show monthly breakdown")
    args = parser.parse_args()

    # Resolve model path (supports glob patterns)
    model_paths = glob.glob(args.model_path)
    if not model_paths:
        print(f"Error: No model found matching pattern: {args.model_path}")
        sys.exit(1)
    model_path = sorted(model_paths)[-1]  # Use most recent if multiple matches
    print(f"Using model: {model_path}")

    # Load model
    model = cb.CatBoostRegressor()
    model.load_model(model_path)

    # Load training metadata if available
    metadata_path = model_path.replace('.cbm', '_metadata.json')
    train_metadata = None
    medians = None
    if Path(metadata_path).exists():
        with open(metadata_path) as f:
            train_metadata = json.load(f)
            medians = train_metadata.get('feature_medians')
        print(f"Loaded training metadata from {metadata_path}")

    print()
    print("=" * 80)
    print(f" EVALUATION: Experiment {args.experiment_id}")
    print("=" * 80)
    print(f"Evaluation period: {args.eval_start} to {args.eval_end}")
    print(f"Minimum edge threshold: {args.min_edge}")
    if train_metadata:
        print(f"Training period: {train_metadata['train_period']['start']} to {train_metadata['train_period']['end']}")
    print()

    # Load evaluation data
    print("Loading evaluation data...")
    client = bigquery.Client(project=PROJECT_ID)
    query = get_evaluation_query(args.eval_start, args.eval_end)
    df = client.query(query).to_dataframe()
    print(f"Loaded {len(df):,} samples")

    actual_start = df['game_date'].min()
    actual_end = df['game_date'].max()
    print(f"Actual date range: {actual_start} to {actual_end}")

    # Prepare features
    print("\nPreparing features...")
    X, y = prepare_features(df, medians)

    # Generate predictions
    print("Generating predictions...")
    predictions = model.predict(X)

    # Calculate MAE
    mae = mean_absolute_error(y, predictions)
    print(f"\nMAE: {mae:.4f}")

    # Get Vegas lines for betting metrics
    lines = df['vegas_points_line'].values
    vegas_coverage = (~np.isnan(lines)).mean()
    print(f"Vegas line coverage: {vegas_coverage:.1%}")

    # Calculate betting metrics
    print("\n--- Betting Metrics ---")
    betting = calculate_betting_metrics(predictions, y.values, lines, args.min_edge)
    if betting['hit_rate']:
        print(f"Hit Rate: {betting['hit_rate_pct']:.2f}% ({betting['hits']}/{betting['bets_graded']})")
        print(f"ROI: {betting['roi_pct']:.2f}%")
        print(f"Profit: ${betting['profit']:.2f} (per $1 bet on {betting['bets_placed']} bets)")
        print(f"Breakeven: {betting['breakeven_hit_rate']:.2f}%")
    else:
        print("No bets placed (no predictions exceeded edge threshold)")

    # Confidence breakdown
    print("\n--- By Confidence/Edge ---")
    confidence = calculate_confidence_metrics(predictions, y.values, lines, args.min_edge)
    for bucket, data in confidence.items():
        if data['count'] > 0 and data.get('hit_rate'):
            print(f"  {bucket}: {data['hit_rate']:.1f}% ({data['hits']}/{data['graded']})")
        elif data['count'] > 0:
            print(f"  {bucket}: N/A ({data['count']} games)")

    # Direction breakdown
    print("\n--- By Direction ---")
    direction = calculate_direction_metrics(predictions, y.values, lines, args.min_edge)
    for dir_name, data in direction.items():
        if data['count'] > 0 and data.get('hit_rate'):
            print(f"  {dir_name}: {data['hit_rate']:.1f}% ({data['hits']}/{data['graded']})")

    # Monthly breakdown if requested
    monthly_results = {}
    if args.monthly_breakdown:
        print("\n--- Monthly Breakdown ---")
        df['month'] = pd.to_datetime(df['game_date']).dt.to_period('M')
        df['prediction'] = predictions

        for month, group in df.groupby('month'):
            m_preds = group['prediction'].values
            m_acts = group['actual_points'].values
            m_lines = group['vegas_points_line'].values
            m_mae = mean_absolute_error(m_acts, m_preds)
            m_betting = calculate_betting_metrics(m_preds, m_acts, m_lines, args.min_edge)

            monthly_results[str(month)] = {
                "samples": len(group),
                "mae": round(m_mae, 4),
                "betting": m_betting,
            }

            hr_str = f"{m_betting['hit_rate_pct']:.1f}%" if m_betting.get('hit_rate_pct') else "N/A"
            print(f"  {month}: MAE={m_mae:.3f}, Hit={hr_str} ({m_betting.get('hits', 0)}/{m_betting.get('bets_graded', 0)})")

    # Save results
    results = {
        "experiment_id": args.experiment_id,
        "model_path": model_path,
        "train_period": train_metadata['train_period'] if train_metadata else None,
        "eval_period": {
            "start": args.eval_start,
            "end": args.eval_end,
            "actual_start": str(actual_start),
            "actual_end": str(actual_end),
            "samples": len(df),
            "vegas_coverage": round(vegas_coverage, 4),
        },
        "results": {
            "mae": round(mae, 4),
            "betting": betting,
            "by_confidence": confidence,
            "by_direction": direction,
        },
        "monthly": monthly_results if monthly_results else None,
        "evaluated_at": datetime.now().isoformat(),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_path = RESULTS_DIR / f"{args.experiment_id}_results.json"
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved results to {results_path}")

    # Summary
    print("\n" + "=" * 80)
    print("EVALUATION COMPLETE")
    print("=" * 80)
    print(f"""
Experiment: {args.experiment_id}
Evaluation period: {args.eval_start} to {args.eval_end}
Samples: {len(df):,}

Key Results:
  MAE: {mae:.4f}
  Hit Rate: {betting['hit_rate_pct']:.2f}% ({betting['hits']}/{betting['bets_graded']})
  ROI: {betting['roi_pct']:.2f}%
  vs Breakeven ({BREAKEVEN_HIT_RATE*100:.1f}%): {'+' if betting['hit_rate_pct'] > BREAKEVEN_HIT_RATE*100 else ''}{betting['hit_rate_pct'] - BREAKEVEN_HIT_RATE*100:.2f}%

Results saved to: {results_path}
""")

    return results


if __name__ == "__main__":
    main()

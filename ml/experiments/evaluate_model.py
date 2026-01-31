#!/usr/bin/env python3
"""
Model Evaluation Script for Walk-Forward Experiments

Evaluates a trained CatBoost model on a specified date range.
Calculates betting metrics (hit rate, ROI) and point prediction accuracy (MAE).

Two evaluation modes:
1. Standard Mode (default): Uses feature store Vegas lines
   - Good for: Model vs model comparison (relative ranking)
   - Sample size: Larger (all players with features)
   - Limitation: Hit rates may not match production

2. Production-Equivalent Mode (--production-equivalent): Uses real BettingPros lines
   - Good for: Estimating actual production performance
   - Sample size: Smaller (only players with real prop lines)
   - Benefit: Hit rates closer to actual production results

Usage:
    # Standard evaluation (for model comparison)
    PYTHONPATH=. python ml/experiments/evaluate_model.py \
        --model-path ml/experiments/results/catboost_v9_exp_A1_*.cbm \
        --eval-start 2022-10-01 \
        --eval-end 2023-06-30 \
        --experiment-id A1

    # Production-equivalent evaluation (for deployment decisions)
    PYTHONPATH=. python ml/experiments/evaluate_model.py \
        --model-path ml/experiments/results/catboost_v9_exp_A1_*.cbm \
        --eval-start 2026-01-01 \
        --eval-end 2026-01-31 \
        --experiment-id A1 \
        --production-equivalent

    # With monthly breakdown
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

# Feature names - must match feature store and training exactly
# Supports 33, 34, and 37 feature variants
ALL_FEATURES = [
    # Recent Performance (0-4)
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days",
    # Composite Factors (5-8)
    "fatigue_score", "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    # Derived Factors (9-12)
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    # Matchup Context (13-17)
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back", "playoff_game",
    # Shot Zones (18-21)
    "pct_paint", "pct_mid_range", "pct_three", "pct_free_throw",
    # Team Context (22-24)
    "team_pace", "team_off_rating", "team_win_pct",
    # Vegas Lines (25-28)
    "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line",
    # Opponent History (29-30)
    "avg_points_vs_opponent", "games_vs_opponent",
    # Minutes/Efficiency (31-32)
    "minutes_avg_last_10", "ppm_avg_last_10",
    # DNP Risk (33)
    "dnp_rate",
    # Player Trajectory (34-36)
    "pts_slope_10g", "pts_vs_season_zscore", "breakout_flag",
]

# Betting constants
JUICE = -110  # Standard odds
WIN_PAYOUT = 100 / 110  # $0.909 profit per $1 bet on a win
LOSS_PAYOUT = -1.0  # $1 loss per $1 bet on a loss
BREAKEVEN_HIT_RATE = 1 / (1 + WIN_PAYOUT)  # ~52.4%


def get_evaluation_query(eval_start: str, eval_end: str, min_feature_count: int = 33) -> str:
    """
    Generate BigQuery SQL for fetching evaluation data.

    The feature store (ml_feature_store_v2) contains feature vectors.
    We extract vegas_points_line for betting metrics evaluation.

    IMPORTANT: We also extract has_vegas_line (index 28) to filter for real lines.
    The feature store has imputed values when there's no real line, so we can't
    rely on NULL checks - we must use the has_vegas_line flag.

    Args:
        eval_start: Evaluation start date (YYYY-MM-DD)
        eval_end: Evaluation end date (YYYY-MM-DD)
        min_feature_count: Minimum feature count to accept (default: 33)
    """
    return f"""
SELECT
  mf.player_lookup,
  mf.game_date,
  mf.features,
  mf.feature_count,
  -- Extract vegas_points_line from features array (index 25)
  mf.features[OFFSET(25)] as vegas_points_line,
  -- Extract has_vegas_line flag (index 28) - 1.0 = real line, 0.0 = imputed
  mf.features[OFFSET(28)] as has_vegas_line,
  pgs.points as actual_points
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
  ON mf.player_lookup = pgs.player_lookup
  AND mf.game_date = pgs.game_date
WHERE mf.game_date BETWEEN '{eval_start}' AND '{eval_end}'
  AND mf.feature_count >= {min_feature_count}
  AND ARRAY_LENGTH(mf.features) >= {min_feature_count}
  AND pgs.points IS NOT NULL
ORDER BY mf.game_date
"""


def get_production_equivalent_query(eval_start: str, eval_end: str, min_feature_count: int = 33) -> str:
    """
    Generate BigQuery SQL for production-equivalent evaluation.

    This query joins to actual BettingPros prop lines instead of using
    the feature store Vegas lines. This gives more realistic hit rate
    estimates that match production performance.

    Key differences from standard evaluation:
    1. Uses real sportsbook lines from bettingpros_player_points_props
    2. Only includes players who had actual prop lines posted
    3. Filters to consensus lines (most reliable)

    The sample size will be smaller but results more closely match
    what you'd see in actual production betting.

    Args:
        eval_start: Evaluation start date (YYYY-MM-DD)
        eval_end: Evaluation end date (YYYY-MM-DD)
        min_feature_count: Minimum feature count to accept (default: 33)
    """
    return f"""
WITH real_prop_lines AS (
  -- Get actual BettingPros consensus lines (most recent snapshot per player/game)
  SELECT
    game_date,
    player_lookup,
    points_line as real_vegas_line
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE bookmaker = 'BettingPros Consensus'
    AND bet_side = 'over'
    AND game_date BETWEEN '{eval_start}' AND '{eval_end}'
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY game_date, player_lookup
    ORDER BY processed_at DESC
  ) = 1
)
SELECT
  mf.player_lookup,
  mf.game_date,
  mf.features,
  mf.feature_count,
  -- Use REAL line from BettingPros, not feature store
  vl.real_vegas_line as vegas_points_line,
  -- Mark all as real lines (we filtered to real lines only)
  1.0 as has_vegas_line,
  pgs.points as actual_points
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
  ON mf.player_lookup = pgs.player_lookup
  AND mf.game_date = pgs.game_date
-- INNER JOIN ensures we only include players with real prop lines
INNER JOIN real_prop_lines vl
  ON mf.player_lookup = vl.player_lookup
  AND mf.game_date = vl.game_date
WHERE mf.game_date BETWEEN '{eval_start}' AND '{eval_end}'
  AND mf.feature_count >= {min_feature_count}
  AND ARRAY_LENGTH(mf.features) >= {min_feature_count}
  AND pgs.points IS NOT NULL
  -- Additional filter: real sportsbook lines end in .5 or .0 (not estimated averages)
  AND (vl.real_vegas_line - FLOOR(vl.real_vegas_line)) IN (0, 0.5)
ORDER BY mf.game_date
"""


def prepare_features(df: pd.DataFrame, medians: dict = None, target_feature_count: int = None) -> tuple[pd.DataFrame, pd.Series, list]:
    """
    Prepare feature matrix from raw dataframe.

    The feature store contains feature vectors of variable length (33, 34, or 37).
    This function unpacks them and handles variable feature counts.

    Args:
        df: Raw dataframe from BigQuery
        medians: Optional median values for imputation (from training)
        target_feature_count: If specified, truncate/limit to this many features

    Returns:
        X: Feature matrix
        y: Target values (actual_points)
        feature_names: List of feature names used
    """
    # Detect feature count from data
    sample_features = df.iloc[0]['features']
    actual_feature_count = len(sample_features)

    # Determine how many features to use
    if target_feature_count:
        feature_count = min(actual_feature_count, target_feature_count)
    else:
        feature_count = actual_feature_count

    # Use appropriate feature names based on count
    feature_names = ALL_FEATURES[:feature_count]
    print(f"Detected {actual_feature_count} features in data, using {len(feature_names)} feature names")

    # Unpack features array into DataFrame with named columns
    # Truncate features to match feature_names length
    X = pd.DataFrame(
        [row[:len(feature_names)] for row in df['features'].tolist()],
        columns=feature_names
    )

    # Use provided medians or compute from eval data
    if medians:
        for col, val in medians.items():
            if col in X.columns:
                X[col] = X[col].fillna(val)
        X = X.fillna(X.median())
    else:
        X = X.fillna(X.median())

    y = df['actual_points'].astype(float)

    return X, y, feature_names


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
    parser = argparse.ArgumentParser(
        description="Evaluate CatBoost model on specified date range",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Evaluation Modes:
  Standard (default):     Uses feature store Vegas lines. Good for model comparison.
  Production-equivalent:  Uses real BettingPros lines. Good for production estimates.

Example:
  # Compare models (use standard mode)
  python evaluate_model.py --model-path model.cbm --eval-start 2026-01-01 --eval-end 2026-01-31 --experiment-id TEST

  # Estimate production performance (use production-equivalent mode)
  python evaluate_model.py --model-path model.cbm --eval-start 2026-01-01 --eval-end 2026-01-31 --experiment-id TEST --production-equivalent
        """
    )
    parser.add_argument("--model-path", required=True, help="Path to model file (supports glob patterns)")
    parser.add_argument("--eval-start", required=True, help="Evaluation start date (YYYY-MM-DD)")
    parser.add_argument("--eval-end", required=True, help="Evaluation end date (YYYY-MM-DD)")
    parser.add_argument("--experiment-id", required=True, help="Experiment identifier (e.g., A1, B2)")
    parser.add_argument("--min-edge", type=float, default=1.0, help="Minimum edge to place bet (default: 1.0)")
    parser.add_argument("--monthly-breakdown", action="store_true", help="Show monthly breakdown")
    parser.add_argument(
        "--production-equivalent",
        action="store_true",
        help="Use production-equivalent evaluation (real BettingPros lines, smaller sample, more realistic hit rates)"
    )
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

    # Determine evaluation mode
    eval_mode = "PRODUCTION-EQUIVALENT" if args.production_equivalent else "STANDARD"
    print(f"Evaluation mode: {eval_mode}")
    if args.production_equivalent:
        print("  -> Using real BettingPros lines (smaller sample, realistic hit rates)")
        print("  -> Good for: Estimating actual production performance")
    else:
        print("  -> Using feature store Vegas lines (larger sample)")
        print("  -> Good for: Model vs model comparison (relative ranking)")
        print("  -> NOTE: Hit rates may not match production performance")

    print(f"Evaluation period: {args.eval_start} to {args.eval_end}")
    print(f"Minimum edge threshold: {args.min_edge}")
    if train_metadata:
        print(f"Training period: {train_metadata['train_period']['start']} to {train_metadata['train_period']['end']}")
    print()

    # Get feature count from training metadata or default to 33
    target_feature_count = train_metadata.get('feature_count', 33) if train_metadata else 33
    print(f"Target feature count from training: {target_feature_count}")

    # Load evaluation data - use appropriate query based on mode
    print("Loading evaluation data...")
    client = bigquery.Client(project=PROJECT_ID)

    if args.production_equivalent:
        query = get_production_equivalent_query(args.eval_start, args.eval_end, min_feature_count=target_feature_count)
    else:
        query = get_evaluation_query(args.eval_start, args.eval_end, min_feature_count=target_feature_count)

    df = client.query(query).to_dataframe()
    print(f"Loaded {len(df):,} samples")

    if len(df) == 0:
        print("ERROR: No evaluation data found. Check date range and feature count requirements.")
        sys.exit(1)

    actual_start = df['game_date'].min()
    actual_end = df['game_date'].max()
    print(f"Actual date range: {actual_start} to {actual_end}")

    # Prepare features
    print("\nPreparing features...")
    X, y, feature_names_used = prepare_features(df, medians, target_feature_count=target_feature_count)
    print(f"Using {len(feature_names_used)} features")

    # Generate predictions
    print("Generating predictions...")
    predictions = model.predict(X)

    # Calculate MAE
    mae = mean_absolute_error(y, predictions)
    print(f"\nMAE: {mae:.4f}")

    # Get Vegas lines for betting metrics
    # IMPORTANT: Only use REAL Vegas lines (has_vegas_line = 1.0)
    # The feature store has imputed values when there's no real line,
    # so we can't rely on NaN checks - we must mask based on the flag
    lines = df['vegas_points_line'].values.copy()
    has_real_line = df['has_vegas_line'].values == 1.0
    lines[~has_real_line] = np.nan  # Mask imputed lines as NaN
    vegas_coverage = has_real_line.mean()
    print(f"Vegas line coverage: {vegas_coverage:.1%} ({has_real_line.sum():,} real lines)")

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
            m_lines = group['vegas_points_line'].values.copy()
            m_has_real = group['has_vegas_line'].values == 1.0
            m_lines[~m_has_real] = np.nan  # Mask imputed lines
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
        "evaluation_mode": eval_mode,
        "production_equivalent": args.production_equivalent,
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

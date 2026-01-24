#!/usr/bin/env python3
"""
Shadow Mode Comparison Report

Compares shadow mode predictions to actual results after games complete.
Generates accuracy metrics for mock vs v8 models.

Usage:
    # Report for specific date
    PYTHONPATH=. python predictions/shadow_mode_report.py --date 2026-01-08

    # Report for date range
    PYTHONPATH=. python predictions/shadow_mode_report.py --start 2026-01-01 --end 2026-01-08

    # Output as JSON
    PYTHONPATH=. python predictions/shadow_mode_report.py --date 2026-01-08 --json
"""

import argparse
from datetime import date, timedelta
from typing import Dict, List, Optional
import json
from google.cloud import bigquery
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"


def get_comparison_data(
    client: bigquery.Client,
    start_date: date,
    end_date: date
) -> List[Dict]:
    """Get shadow predictions joined with actual results"""
    query = """
    SELECT
        s.player_lookup,
        s.game_date,
        s.mock_predicted,
        s.mock_confidence,
        s.mock_recommendation,
        s.v8_predicted,
        s.v8_confidence,
        s.v8_recommendation,
        s.betting_line,
        s.injury_status,
        s.injury_warning,
        s.prediction_diff,
        -- Actual results
        a.points as actual_points,
        a.minutes_played as actual_minutes,
        -- Error calculations
        ABS(s.mock_predicted - a.points) as mock_error,
        ABS(s.v8_predicted - a.points) as v8_error,
        -- Betting outcomes (if line exists)
        CASE
            WHEN s.betting_line IS NULL THEN NULL
            WHEN a.points > s.betting_line THEN 'OVER'
            ELSE 'UNDER'
        END as actual_outcome,
        -- Winner determination
        CASE
            WHEN ABS(s.mock_predicted - a.points) < ABS(s.v8_predicted - a.points) THEN 'mock'
            WHEN ABS(s.v8_predicted - a.points) < ABS(s.mock_predicted - a.points) THEN 'v8'
            ELSE 'tie'
        END as closer_prediction

    FROM `nba-props-platform.nba_predictions.shadow_mode_predictions` s
    INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` a
        ON s.player_lookup = a.player_lookup
        AND s.game_date = a.game_date
    WHERE s.game_date BETWEEN @start_date AND @end_date
      AND a.points IS NOT NULL
    ORDER BY s.game_date, s.player_lookup
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    result = client.query(query, job_config=job_config).result()
    return [dict(row) for row in result]


def calculate_metrics(data: List[Dict]) -> Dict:
    """Calculate comparison metrics"""
    if not data:
        return {"error": "No data found"}

    n = len(data)

    # MAE calculations
    mock_errors = [d['mock_error'] for d in data if d['mock_error'] is not None]
    v8_errors = [d['v8_error'] for d in data if d['v8_error'] is not None]

    mock_mae = sum(mock_errors) / len(mock_errors) if mock_errors else 0
    v8_mae = sum(v8_errors) / len(v8_errors) if v8_errors else 0

    # Winner counts
    mock_wins = sum(1 for d in data if d['closer_prediction'] == 'mock')
    v8_wins = sum(1 for d in data if d['closer_prediction'] == 'v8')
    ties = sum(1 for d in data if d['closer_prediction'] == 'tie')

    # Betting accuracy (for predictions with lines)
    with_lines = [d for d in data if d['betting_line'] is not None and d['actual_outcome'] is not None]

    mock_correct = 0
    v8_correct = 0
    for d in with_lines:
        if d['mock_recommendation'] == d['actual_outcome']:
            mock_correct += 1
        if d['v8_recommendation'] == d['actual_outcome']:
            v8_correct += 1

    # Error distribution
    def percentile(values, p):
        if not values:
            return 0
        sorted_vals = sorted(values)
        idx = int(len(sorted_vals) * p / 100)
        return sorted_vals[min(idx, len(sorted_vals) - 1)]

    # Within X points
    mock_within_3 = sum(1 for e in mock_errors if e <= 3)
    mock_within_5 = sum(1 for e in mock_errors if e <= 5)
    v8_within_3 = sum(1 for e in v8_errors if e <= 3)
    v8_within_5 = sum(1 for e in v8_errors if e <= 5)

    return {
        "total_predictions": n,
        "predictions_with_lines": len(with_lines),

        "mock": {
            "mae": round(mock_mae, 3),
            "median_error": round(percentile(mock_errors, 50), 3),
            "p90_error": round(percentile(mock_errors, 90), 3),
            "within_3pts": mock_within_3,
            "within_3pts_pct": round(100 * mock_within_3 / len(mock_errors), 1) if mock_errors else 0,
            "within_5pts": mock_within_5,
            "within_5pts_pct": round(100 * mock_within_5 / len(mock_errors), 1) if mock_errors else 0,
            "betting_correct": mock_correct,
            "betting_accuracy": round(100 * mock_correct / len(with_lines), 1) if with_lines else 0,
        },

        "v8": {
            "mae": round(v8_mae, 3),
            "median_error": round(percentile(v8_errors, 50), 3),
            "p90_error": round(percentile(v8_errors, 90), 3),
            "within_3pts": v8_within_3,
            "within_3pts_pct": round(100 * v8_within_3 / len(v8_errors), 1) if v8_errors else 0,
            "within_5pts": v8_within_5,
            "within_5pts_pct": round(100 * v8_within_5 / len(v8_errors), 1) if v8_errors else 0,
            "betting_correct": v8_correct,
            "betting_accuracy": round(100 * v8_correct / len(with_lines), 1) if with_lines else 0,
        },

        "comparison": {
            "mock_wins": mock_wins,
            "v8_wins": v8_wins,
            "ties": ties,
            "v8_win_rate": round(100 * v8_wins / (mock_wins + v8_wins), 1) if (mock_wins + v8_wins) > 0 else 0,
            "mae_improvement": round(100 * (mock_mae - v8_mae) / mock_mae, 1) if mock_mae > 0 else 0,
        },

        "injury_filter": {
            "predictions_with_warning": sum(1 for d in data if d['injury_warning']),
            "dnp_caught": sum(1 for d in data if d['injury_status'] == 'out' and d['actual_minutes'] == 0),
        }
    }


def print_report(metrics: Dict, start_date: date, end_date: date):
    """Print formatted report"""
    logger.info("=" * 70)
    logger.info(f"SHADOW MODE COMPARISON REPORT: {start_date} to {end_date}")
    logger.info("=" * 70)

    logger.info(f"Total Predictions: {metrics['total_predictions']}")
    logger.info(f"Predictions with Vegas Lines: {metrics['predictions_with_lines']}")

    logger.info("-" * 70)
    logger.info("MODEL ACCURACY")
    logger.info("-" * 70)

    mock = metrics['mock']
    v8 = metrics['v8']
    comp = metrics['comparison']

    logger.info(f"{'Metric':<25} {'Mock':<15} {'V8':<15} {'Winner':<10}")
    logger.info("-" * 65)

    # MAE (lower is better)
    winner = "v8" if v8['mae'] < mock['mae'] else "mock"
    logger.info(f"{'MAE':<25} {mock['mae']:<15.3f} {v8['mae']:<15.3f} {winner:<10}")

    # Median Error
    winner = "v8" if v8['median_error'] < mock['median_error'] else "mock"
    logger.info(f"{'Median Error':<25} {mock['median_error']:<15.3f} {v8['median_error']:<15.3f} {winner:<10}")

    # P90 Error
    winner = "v8" if v8['p90_error'] < mock['p90_error'] else "mock"
    logger.info(f"{'P90 Error':<25} {mock['p90_error']:<15.3f} {v8['p90_error']:<15.3f} {winner:<10}")

    # Within 3 pts
    winner = "v8" if v8['within_3pts_pct'] > mock['within_3pts_pct'] else "mock"
    logger.info(f"{'Within 3 pts':<25} {mock['within_3pts_pct']:<14.1f}% {v8['within_3pts_pct']:<14.1f}% {winner:<10}")

    # Within 5 pts
    winner = "v8" if v8['within_5pts_pct'] > mock['within_5pts_pct'] else "mock"
    logger.info(f"{'Within 5 pts':<25} {mock['within_5pts_pct']:<14.1f}% {v8['within_5pts_pct']:<14.1f}% {winner:<10}")

    # Betting accuracy
    if metrics['predictions_with_lines'] > 0:
        winner = "v8" if v8['betting_accuracy'] > mock['betting_accuracy'] else "mock"
        logger.info(f"{'Betting Accuracy':<25} {mock['betting_accuracy']:<14.1f}% {v8['betting_accuracy']:<14.1f}% {winner:<10}")

    logger.info("-" * 70)
    logger.info("HEAD-TO-HEAD COMPARISON")
    logger.info("-" * 70)

    logger.info("Closer to Actual:")
    logger.info(f"  Mock wins:  {comp['mock_wins']} ({100 * comp['mock_wins'] / metrics['total_predictions']:.1f}%)")
    logger.info(f"  V8 wins:    {comp['v8_wins']} ({100 * comp['v8_wins'] / metrics['total_predictions']:.1f}%)")
    logger.info(f"  Ties:       {comp['ties']} ({100 * comp['ties'] / metrics['total_predictions']:.1f}%)")

    logger.info(f"V8 Win Rate: {comp['v8_win_rate']:.1f}%")
    logger.info(f"MAE Improvement: {comp['mae_improvement']:+.1f}%")

    inj = metrics['injury_filter']
    if inj['predictions_with_warning'] > 0:
        logger.info("-" * 70)
        logger.info("INJURY FILTER")
        logger.info("-" * 70)
        logger.info(f"Predictions with injury warning: {inj['predictions_with_warning']}")

    logger.info("=" * 70)

    # Verdict
    if comp['mae_improvement'] > 5:
        logger.info("VERDICT: V8 significantly outperforms mock")
    elif comp['mae_improvement'] > 0:
        logger.info("VERDICT: V8 slightly outperforms mock")
    elif comp['mae_improvement'] > -5:
        logger.info("VERDICT: Models perform similarly")
    else:
        logger.warning("VERDICT: Mock outperforms V8 (investigate)")

    logger.info("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Shadow mode comparison report")
    parser.add_argument("--date", type=str, help="Single date (YYYY-MM-DD)")
    parser.add_argument("--start", type=str, help="Start date for range")
    parser.add_argument("--end", type=str, help="End date for range")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # Parse dates
    if args.date:
        start_date = end_date = date.fromisoformat(args.date)
    elif args.start and args.end:
        start_date = date.fromisoformat(args.start)
        end_date = date.fromisoformat(args.end)
    else:
        # Default: yesterday
        end_date = date.today() - timedelta(days=1)
        start_date = end_date

    logger.info(f"Generating report for {start_date} to {end_date}")

    # Get data
    client = bigquery.Client(project=PROJECT_ID)
    data = get_comparison_data(client, start_date, end_date)

    logger.info(f"Found {len(data)} predictions with results")

    if not data:
        logger.warning("No data found for this date range")
        logger.warning("Make sure:")
        logger.warning("  1. Shadow mode runner was executed for these dates")
        logger.warning("  2. Games have been played and results are in player_game_summary")
        return

    # Calculate metrics
    metrics = calculate_metrics(data)

    # Output
    if args.json:
        logger.info(json.dumps(metrics, indent=2))
    else:
        print_report(metrics, start_date, end_date)


if __name__ == "__main__":
    main()

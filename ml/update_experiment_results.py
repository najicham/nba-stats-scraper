#!/usr/bin/env python3
"""
Update ML Experiment Results

Joins predictions with actual game results to calculate accuracy metrics.
Run this after games complete.

Usage:
    # Update yesterday's results
    PYTHONPATH=. python ml/update_experiment_results.py

    # Update specific date
    PYTHONPATH=. python ml/update_experiment_results.py --date 2026-01-08

    # Update date range
    PYTHONPATH=. python ml/update_experiment_results.py --start 2026-01-01 --end 2026-01-08
"""

import argparse
from datetime import date, timedelta
import logging
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"


def update_results(client: bigquery.Client, start_date: date, end_date: date) -> int:
    """Update prediction results with actual game outcomes"""

    query = """
    UPDATE `nba-props-platform.nba_predictions.ml_model_predictions` p
    SET
        actual_points = a.points,
        actual_minutes = a.minutes_played,
        prediction_error = ABS(p.predicted_points - a.points),
        bet_outcome = CASE
            WHEN p.betting_line IS NULL THEN NULL
            WHEN a.points > p.betting_line AND p.recommendation = 'OVER' THEN 'WIN'
            WHEN a.points < p.betting_line AND p.recommendation = 'UNDER' THEN 'WIN'
            WHEN a.points = p.betting_line THEN 'PUSH'
            WHEN p.recommendation IN ('OVER', 'UNDER') THEN 'LOSS'
            ELSE NULL
        END,
        beat_vegas = CASE
            WHEN p.betting_line IS NULL THEN NULL
            WHEN ABS(p.predicted_points - a.points) < ABS(p.betting_line - a.points) THEN TRUE
            ELSE FALSE
        END,
        result_updated_at = CURRENT_TIMESTAMP()
    FROM `nba-props-platform.nba_analytics.player_game_summary` a
    WHERE p.player_lookup = a.player_lookup
      AND p.game_date = a.game_date
      AND p.game_date BETWEEN @start_date AND @end_date
      AND p.actual_points IS NULL
      AND a.points IS NOT NULL
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    result = client.query(query, job_config=job_config).result()

    # Get rows affected
    rows_updated = result.num_dml_affected_rows if hasattr(result, 'num_dml_affected_rows') else 0

    return rows_updated


def update_baseline_comparison(client: bigquery.Client, start_date: date, end_date: date) -> int:
    """Update beat_baseline flag by comparing to baseline model"""

    # First, get the baseline model
    baseline_query = """
    SELECT model_id FROM `nba-props-platform.nba_predictions.ml_model_registry`
    WHERE is_baseline = TRUE
    LIMIT 1
    """
    baseline_result = client.query(baseline_query).result()
    baseline_rows = list(baseline_result)

    if not baseline_rows:
        logger.info("No baseline model defined, skipping baseline comparison")
        return 0

    baseline_model = baseline_rows[0].model_id

    # Update beat_baseline for all other models
    query = """
    UPDATE `nba-props-platform.nba_predictions.ml_model_predictions` p
    SET beat_baseline = (p.prediction_error < b.prediction_error)
    FROM `nba-props-platform.nba_predictions.ml_model_predictions` b
    WHERE p.player_lookup = b.player_lookup
      AND p.game_date = b.game_date
      AND p.model_id != @baseline_model
      AND b.model_id = @baseline_model
      AND p.game_date BETWEEN @start_date AND @end_date
      AND p.actual_points IS NOT NULL
      AND b.actual_points IS NOT NULL
      AND p.beat_baseline IS NULL
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("baseline_model", "STRING", baseline_model),
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    result = client.query(query, job_config=job_config).result()
    rows_updated = result.num_dml_affected_rows if hasattr(result, 'num_dml_affected_rows') else 0

    return rows_updated


def print_summary(client: bigquery.Client, start_date: date, end_date: date):
    """Print summary of results"""

    query = """
    SELECT
        model_id,
        COUNT(*) as total,
        COUNTIF(actual_points IS NOT NULL) as graded,
        ROUND(AVG(prediction_error), 2) as mae,
        COUNTIF(bet_outcome = 'WIN') as wins,
        COUNTIF(bet_outcome = 'LOSS') as losses,
        ROUND(SAFE_DIVIDE(COUNTIF(bet_outcome = 'WIN'),
              COUNTIF(bet_outcome IN ('WIN', 'LOSS'))) * 100, 1) as win_pct,
        COUNTIF(beat_vegas = TRUE) as beat_vegas,
        ROUND(SAFE_DIVIDE(COUNTIF(beat_vegas = TRUE),
              COUNTIF(beat_vegas IS NOT NULL)) * 100, 1) as beat_vegas_pct
    FROM `nba-props-platform.nba_predictions.ml_model_predictions`
    WHERE game_date BETWEEN @start_date AND @end_date
    GROUP BY model_id
    ORDER BY mae ASC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    result = client.query(query, job_config=job_config).result()
    rows = list(result)

    if not rows:
        print("No results found for this date range")
        return

    print("\n" + "=" * 80)
    print(f"ML EXPERIMENT RESULTS: {start_date} to {end_date}")
    print("=" * 80)

    print(f"\n{'Model':<20} {'Graded':<10} {'MAE':<10} {'Wins':<8} {'Losses':<8} {'Win%':<10} {'Beat Vegas':<12}")
    print("-" * 80)

    for row in rows:
        print(f"{row.model_id:<20} {row.graded:<10} {row.mae or '--':<10} "
              f"{row.wins:<8} {row.losses:<8} {row.win_pct or '--':<10} "
              f"{row.beat_vegas_pct or '--':<12}")

    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Update ML experiment results")
    parser.add_argument("--date", type=str, help="Single date (YYYY-MM-DD)")
    parser.add_argument("--start", type=str, help="Start date for range")
    parser.add_argument("--end", type=str, help="End date for range")
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

    logger.info(f"Updating results for {start_date} to {end_date}")

    client = bigquery.Client(project=PROJECT_ID)

    # Update results
    rows_updated = update_results(client, start_date, end_date)
    logger.info(f"Updated {rows_updated} predictions with actual results")

    # Update baseline comparison
    baseline_updated = update_baseline_comparison(client, start_date, end_date)
    logger.info(f"Updated {baseline_updated} baseline comparisons")

    # Print summary
    print_summary(client, start_date, end_date)


if __name__ == "__main__":
    main()

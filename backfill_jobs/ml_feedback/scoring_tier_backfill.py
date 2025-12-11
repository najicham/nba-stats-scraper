#!/usr/bin/env python3
"""
Scoring Tier Adjustments Backfill

Phase 5C ML Feedback: Backfills scoring_tier_adjustments table from
prediction_accuracy data.

Usage:
    # Compute adjustments as of latest date
    python scoring_tier_backfill.py

    # Compute adjustments for specific date
    python scoring_tier_backfill.py --as-of-date 2022-01-07

    # Backfill weekly snapshots
    python scoring_tier_backfill.py --start-date 2021-12-01 --end-date 2022-01-07 --weekly
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from google.cloud import bigquery

# Add project root to path
sys.path.insert(0, '/home/naji/code/nba-stats-scraper')

from data_processors.ml_feedback.scoring_tier_processor import ScoringTierProcessor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_latest_graded_date() -> str:
    """Get the latest date with graded predictions."""
    client = bigquery.Client()
    query = """
    SELECT MAX(game_date) as max_date
    FROM nba_predictions.prediction_accuracy
    """
    result = list(client.query(query).result())
    if result and result[0].max_date:
        return result[0].max_date.strftime('%Y-%m-%d')
    return None


def create_table_if_not_exists():
    """Create the scoring_tier_adjustments table if it doesn't exist."""
    client = bigquery.Client()

    schema = [
        bigquery.SchemaField('system_id', 'STRING', mode='REQUIRED'),
        bigquery.SchemaField('scoring_tier', 'STRING', mode='REQUIRED'),
        bigquery.SchemaField('as_of_date', 'DATE', mode='REQUIRED'),
        bigquery.SchemaField('sample_size', 'INTEGER'),
        bigquery.SchemaField('lookback_days', 'INTEGER'),
        bigquery.SchemaField('avg_signed_error', 'NUMERIC', precision=5, scale=2),
        bigquery.SchemaField('avg_absolute_error', 'NUMERIC', precision=5, scale=2),
        bigquery.SchemaField('std_signed_error', 'NUMERIC', precision=5, scale=2),
        bigquery.SchemaField('recommended_adjustment', 'NUMERIC', precision=5, scale=2),
        bigquery.SchemaField('adjustment_confidence', 'NUMERIC', precision=4, scale=3),
        bigquery.SchemaField('current_win_rate', 'NUMERIC', precision=4, scale=3),
        bigquery.SchemaField('projected_win_rate', 'NUMERIC', precision=4, scale=3),
        bigquery.SchemaField('tier_min_points', 'NUMERIC', precision=5, scale=1),
        bigquery.SchemaField('tier_max_points', 'NUMERIC', precision=5, scale=1),
        bigquery.SchemaField('computed_at', 'TIMESTAMP', mode='REQUIRED'),
        bigquery.SchemaField('model_version', 'STRING'),
    ]

    table_id = 'nba-props-platform.nba_predictions.scoring_tier_adjustments'
    table = bigquery.Table(table_id, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field='as_of_date'
    )
    table.clustering_fields = ['system_id', 'scoring_tier']

    try:
        client.create_table(table)
        logger.info(f"Created table {table_id}")
    except Exception as e:
        if 'Already Exists' in str(e):
            logger.info(f"Table {table_id} already exists")
        else:
            raise


def run_backfill(start_date: str = None, end_date: str = None,
                 weekly: bool = False, as_of_date: str = None):
    """Run the scoring tier adjustments backfill."""

    # Ensure table exists
    create_table_if_not_exists()

    processor = ScoringTierProcessor(lookback_days=30, min_sample_size=20)

    if as_of_date:
        # Single date mode
        logger.info(f"Computing adjustments as of {as_of_date}")
        result = processor.process(as_of_date)
        logger.info(f"Result: {result}")
        return

    # Date range mode
    if not start_date:
        start_date = '2021-12-05'  # Need 30 days of data after Nov 6

    if not end_date:
        end_date = get_latest_graded_date()
        if not end_date:
            logger.error("No graded predictions found")
            return

    logger.info(f"Backfilling scoring tier adjustments from {start_date} to {end_date}")

    # Parse dates
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')

    # Generate dates to process
    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime('%Y-%m-%d'))
        if weekly:
            current += timedelta(days=7)
        else:
            current += timedelta(days=1)

    logger.info(f"Processing {len(dates)} dates")

    success_count = 0
    skip_count = 0
    fail_count = 0

    for i, date in enumerate(dates):
        logger.info(f"[{i+1}/{len(dates)}] Processing {date}")
        try:
            result = processor.process(date)
            if result['status'] == 'success':
                success_count += 1
            elif result['status'] == 'skipped':
                skip_count += 1
            else:
                fail_count += 1
        except Exception as e:
            logger.error(f"  Error: {e}")
            fail_count += 1

    logger.info("=" * 60)
    logger.info(f"SCORING TIER BACKFILL COMPLETE")
    logger.info(f"  Processed: {len(dates)} dates")
    logger.info(f"  Success: {success_count}, Skipped: {skip_count}, Failed: {fail_count}")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='Backfill scoring tier adjustments')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--as-of-date', help='Single date to compute (YYYY-MM-DD)')
    parser.add_argument('--weekly', action='store_true',
                        help='Generate weekly snapshots instead of daily')
    args = parser.parse_args()

    run_backfill(
        start_date=args.start_date,
        end_date=args.end_date,
        weekly=args.weekly,
        as_of_date=args.as_of_date
    )


if __name__ == '__main__':
    main()

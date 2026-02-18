#!/usr/bin/env python3
"""
Backfill date-keyed tonight player exports.

Re-exports tonight/player/{date}/{lookup}.json for historical dates so the
frontend can fetch date-correct splits, averages, factors, and predictions
when users browse previous dates.

Does NOT overwrite the latest tonight/player/{lookup}.json files.

Usage:
    # Dry run — show dates and player counts
    PYTHONPATH=. python bin/backfill/backfill_tonight_player_exports.py --dry-run

    # Backfill a single date
    PYTHONPATH=. python bin/backfill/backfill_tonight_player_exports.py \
        --start-date 2026-02-10 --end-date 2026-02-10

    # Full season backfill (resumable, ~25 hours)
    PYTHONPATH=. python bin/backfill/backfill_tonight_player_exports.py --skip-existing

    # Resume after interruption
    PYTHONPATH=. python bin/backfill/backfill_tonight_player_exports.py --skip-existing
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime

from google.cloud import bigquery, storage

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
BUCKET_NAME = os.environ.get('GCS_API_BUCKET', 'nba-props-platform-api')
SEASON_START = '2025-10-22'


def get_game_dates(bq_client: bigquery.Client, start_date: str, end_date: str):
    """Query UPCG for distinct game dates in range."""
    query = """
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
    WHERE game_date >= @start_date
      AND game_date <= @end_date
    ORDER BY game_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('start_date', 'DATE', start_date),
            bigquery.ScalarQueryParameter('end_date', 'DATE', end_date),
        ]
    )
    results = bq_client.query(query, job_config=job_config).result()
    return [str(row.game_date) for row in results]


def get_player_count(bq_client: bigquery.Client, game_date: str) -> int:
    """Get count of players for a game date."""
    query = """
    SELECT COUNT(DISTINCT player_lookup) as cnt
    FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
    WHERE game_date = @game_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
        ]
    )
    results = list(bq_client.query(query, job_config=job_config).result())
    return results[0].cnt if results else 0


def date_already_backfilled(storage_client: storage.Client, game_date: str) -> bool:
    """Check if date-keyed folder already has files in GCS."""
    bucket = storage_client.bucket(BUCKET_NAME)
    blobs = list(bucket.list_blobs(prefix=f'v1/tonight/player/{game_date}/', max_results=1))
    return len(blobs) > 0


def main():
    parser = argparse.ArgumentParser(description='Backfill date-keyed tonight player exports')
    parser.add_argument('--start-date', default=SEASON_START,
                        help=f'Start date (default: {SEASON_START})')
    parser.add_argument('--end-date', default=None,
                        help='End date (default: yesterday)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show dates and player counts without exporting')
    parser.add_argument('--skip-existing', action='store_true',
                        help='Skip dates already backfilled in GCS (enables resume)')
    args = parser.parse_args()

    # Default end date to yesterday
    if args.end_date is None:
        from datetime import timedelta
        args.end_date = str((datetime.now() - timedelta(days=1)).date())

    logger.info(f"Backfill range: {args.start_date} to {args.end_date}")

    bq_client = bigquery.Client(project=PROJECT_ID)
    storage_client = storage.Client(project=PROJECT_ID) if args.skip_existing else None

    # Get all game dates in range
    game_dates = get_game_dates(bq_client, args.start_date, args.end_date)
    logger.info(f"Found {len(game_dates)} game dates in range")

    if not game_dates:
        logger.info("No game dates found. Exiting.")
        return

    if args.dry_run:
        logger.info("DRY RUN — showing dates and player counts:")
        for i, gd in enumerate(game_dates):
            count = get_player_count(bq_client, gd)
            logger.info(f"  [{i+1}/{len(game_dates)}] {gd}: {count} players")
        logger.info(f"Total: {len(game_dates)} dates")
        return

    # Initialize exporter
    exporter = TonightPlayerExporter()

    total_players = 0
    total_skipped = 0
    total_failed_dates = 0
    start_time = time.time()

    for i, gd in enumerate(game_dates):
        # Check if already backfilled
        if args.skip_existing and storage_client:
            if date_already_backfilled(storage_client, gd):
                logger.info(f"[{i+1}/{len(game_dates)}] {gd}: skipping (already backfilled)")
                total_skipped += 1
                continue

        date_start = time.time()
        try:
            paths = exporter.export_all_for_date(gd, update_latest=False)
            elapsed = time.time() - date_start
            total_players += len(paths)
            logger.info(
                f"[{i+1}/{len(game_dates)}] {gd}: "
                f"{len(paths)} players exported in {elapsed:.1f}s"
            )
        except Exception as e:
            elapsed = time.time() - date_start
            total_failed_dates += 1
            logger.error(
                f"[{i+1}/{len(game_dates)}] {gd}: FAILED after {elapsed:.1f}s — {e}",
                exc_info=True
            )

    total_elapsed = time.time() - start_time
    hours = total_elapsed / 3600
    logger.info(
        f"\nBackfill complete: "
        f"{len(game_dates) - total_skipped - total_failed_dates} dates processed, "
        f"{total_skipped} skipped, "
        f"{total_failed_dates} failed, "
        f"{total_players} total players exported "
        f"in {hours:.1f} hours"
    )


if __name__ == '__main__':
    main()

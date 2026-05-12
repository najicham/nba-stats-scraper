#!/usr/bin/env python3
"""
Backfill MLB pitcher history sidecar files.

The frontend MLB date picker fetches:
    gs://nba-props-platform-api/v1/mlb/pitchers/history/{date}.json
for past-date navigation. The history sidecar landed in props-platform commit
950daaf2 (2026-05-05), so files only exist for May 6+ as written by the daily
exporter on each game day. This script writes history files for older dates
that have MLB pitcher predictions in BigQuery.

Calls MlbPitcherExporter in history-only mode so the live leaderboard.json
and per-pitcher profile JSONs are NOT overwritten with historical data.

Usage:
    # Dry run — list candidate dates without exporting
    PYTHONPATH=. python bin/backfill/backfill_mlb_pitcher_history.py --dry-run

    # Single date
    PYTHONPATH=. python bin/backfill/backfill_mlb_pitcher_history.py \\
        --start-date 2026-05-04 --end-date 2026-05-04

    # Full backfill, resumable (skips dates that already have a history file)
    PYTHONPATH=. python bin/backfill/backfill_mlb_pitcher_history.py --skip-existing

    # Resume after interruption (same command, --skip-existing makes it idempotent)
    PYTHONPATH=. python bin/backfill/backfill_mlb_pitcher_history.py --skip-existing
"""

import argparse
import logging
import os
import sys
import time

from google.cloud import bigquery, storage

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from data_processors.publishing.mlb.mlb_pitcher_exporter import MlbPitcherExporter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    force=True,
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
BUCKET_NAME = os.environ.get('GCS_API_BUCKET', 'nba-props-platform-api')


def get_prediction_dates(bq_client: bigquery.Client, start_date: str, end_date: str):
    """Distinct game_dates with MLB pitcher predictions in the range."""
    query = """
    SELECT DISTINCT CAST(game_date AS STRING) AS game_date
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
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
    return [row.game_date for row in bq_client.query(query, job_config=job_config).result()]


def history_file_exists(storage_client: storage.Client, game_date: str) -> bool:
    """Check if v1/mlb/pitchers/history/{date}.json already exists in GCS."""
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(f'v1/mlb/pitchers/history/{game_date}.json')
    return blob.exists()


def main():
    parser = argparse.ArgumentParser(description='Backfill MLB pitcher history sidecar files')
    parser.add_argument('--start-date', default='2024-04-09',
                        help='Start date YYYY-MM-DD (default: 2024-04-09, earliest predictions)')
    parser.add_argument('--end-date', default=None,
                        help='End date YYYY-MM-DD (default: yesterday)')
    parser.add_argument('--dry-run', action='store_true',
                        help='List candidate dates without exporting')
    parser.add_argument('--skip-existing', action='store_true',
                        help='Skip dates that already have a history file in GCS (enables resume)')
    args = parser.parse_args()

    if args.end_date is None:
        from datetime import datetime, timedelta
        args.end_date = str((datetime.now() - timedelta(days=1)).date())

    logger.info(f"Backfill range: {args.start_date} → {args.end_date}")

    bq_client = bigquery.Client(project=PROJECT_ID)
    storage_client = storage.Client(project=PROJECT_ID) if (args.skip_existing or args.dry_run) else None

    game_dates = get_prediction_dates(bq_client, args.start_date, args.end_date)
    logger.info(f"Found {len(game_dates)} game dates with predictions in range")

    if not game_dates:
        logger.info("No prediction dates found. Exiting.")
        return

    if args.dry_run:
        logger.info("DRY RUN — candidate dates:")
        existing = 0
        for i, gd in enumerate(game_dates):
            if storage_client and history_file_exists(storage_client, gd):
                logger.info(f"  [{i+1}/{len(game_dates)}] {gd}: EXISTS")
                existing += 1
            else:
                logger.info(f"  [{i+1}/{len(game_dates)}] {gd}: would write")
        logger.info(
            f"Total: {len(game_dates)} dates ({existing} existing, "
            f"{len(game_dates) - existing} to write)"
        )
        return

    exporter = MlbPitcherExporter()

    total_written = 0
    total_skipped = 0
    total_failed = 0
    start_time = time.time()

    for i, gd in enumerate(game_dates):
        if args.skip_existing and storage_client and history_file_exists(storage_client, gd):
            logger.info(f"[{i+1}/{len(game_dates)}] {gd}: skip (exists)")
            total_skipped += 1
            continue

        date_start = time.time()
        try:
            result = exporter.export(game_date=gd, history_only=True)
            elapsed = time.time() - date_start
            total_written += 1
            logger.info(
                f"[{i+1}/{len(game_dates)}] {gd}: wrote {result['history_path']} "
                f"in {elapsed:.1f}s"
            )
        except Exception as e:
            elapsed = time.time() - date_start
            total_failed += 1
            logger.error(
                f"[{i+1}/{len(game_dates)}] {gd}: FAILED after {elapsed:.1f}s — {e}",
                exc_info=True
            )

    total_elapsed = time.time() - start_time
    minutes = total_elapsed / 60
    logger.info(
        f"\nBackfill complete: "
        f"{total_written} written, "
        f"{total_skipped} skipped, "
        f"{total_failed} failed "
        f"in {minutes:.1f} minutes"
    )


if __name__ == '__main__':
    main()

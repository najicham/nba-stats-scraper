#!/usr/bin/env python3
"""
Backfill missing late-snapshot odds data from GCS to BigQuery.

Session 298 found that daily scraper captures 7 snapshots per day
(snap-0700 through snap-0006), but Phase 2 only loaded some of them.
This leaves ~395 "late" snapshot files (snap-19xx, snap-22xx, snap-00xx)
across 18 dates (Jan 25 - Feb 12) unloaded.

Usage:
    # Dry run — preview what would be loaded
    PYTHONPATH=. python bin/backfill_daily_props_snapshots.py --dry-run

    # Single date test
    PYTHONPATH=. python bin/backfill_daily_props_snapshots.py --start-date 2026-02-10 --end-date 2026-02-10

    # Full backfill (default range: Jan 25 - Feb 12)
    PYTHONPATH=. python bin/backfill_daily_props_snapshots.py

    # Custom range
    PYTHONPATH=. python bin/backfill_daily_props_snapshots.py --start-date 2026-01-30 --end-date 2026-02-05
"""

import argparse
import json
import logging
import sys
from datetime import datetime, date, timedelta
from typing import Dict, List, Set, Tuple

from google.cloud import bigquery, storage

from data_processors.raw.oddsapi.odds_api_props_processor import OddsApiPropsProcessor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
BUCKET_NAME = 'nba-scraped-data'
TABLE_ID = f'{PROJECT_ID}.nba_raw.odds_api_player_points_props'
GCS_PREFIX = 'odds-api/player-props'

# Default date range from Session 298 analysis
DEFAULT_START = '2026-01-25'
DEFAULT_END = '2026-02-12'


def get_existing_snapshot_tags(bq_client: bigquery.Client, game_date: str) -> Set[str]:
    """Query BQ for snapshot_tags already loaded for a given date."""
    query = """
        SELECT DISTINCT snapshot_tag
        FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
        WHERE game_date = @game_date
          AND snapshot_tag IS NOT NULL
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date)
        ]
    )
    results = bq_client.query(query, job_config=job_config).result()
    return {row.snapshot_tag for row in results}


def extract_snapshot_tag_from_path(blob_name: str) -> str:
    """Extract snapshot_tag from a GCS blob path.

    Path format: odds-api/player-props/{date}/{event}/{timestamp}-snap-{tag}.json
    Returns: 'snap-{tag}' or None
    """
    filename = blob_name.split('/')[-1].replace('.json', '')
    parts = filename.split('-snap-')
    if len(parts) > 1:
        return f'snap-{parts[1]}'
    return None


def list_gcs_files_for_date(
    storage_client: storage.Client,
    game_date: str
) -> List[str]:
    """List all JSON files in GCS for a given date."""
    bucket = storage_client.bucket(BUCKET_NAME)
    prefix = f'{GCS_PREFIX}/{game_date}/'
    blobs = bucket.list_blobs(prefix=prefix)
    return [blob.name for blob in blobs if blob.name.endswith('.json')]


def get_snapshot_tag_prefix(tag: str) -> str:
    """Get the 2-digit hour prefix of a snapshot_tag.

    'snap-1905' -> 'snap-19'
    'snap-0700' -> 'snap-07'
    """
    if tag and tag.startswith('snap-') and len(tag) >= 7:
        return tag[:7]
    return tag


def process_date(
    game_date: str,
    bq_client: bigquery.Client,
    storage_client: storage.Client,
    dry_run: bool = False
) -> Dict:
    """Process a single date: find missing snapshots and load them.

    Returns summary dict with stats for this date.
    """
    summary = {
        'game_date': game_date,
        'gcs_files_total': 0,
        'existing_tags': set(),
        'new_tags': set(),
        'files_to_load': 0,
        'files_loaded': 0,
        'files_failed': 0,
        'rows_added': 0,
        'errors': []
    }

    # Step 1: Get existing snapshot_tags from BQ
    existing_tags = get_existing_snapshot_tags(bq_client, game_date)
    existing_prefixes = {get_snapshot_tag_prefix(t) for t in existing_tags}
    summary['existing_tags'] = existing_tags

    # Step 2: List all GCS files for this date
    all_files = list_gcs_files_for_date(storage_client, game_date)
    summary['gcs_files_total'] = len(all_files)

    if not all_files:
        logger.info(f"  {game_date}: No GCS files found")
        return summary

    # Step 3: Filter to files with snapshot_tags NOT already in BQ
    # Check by prefix (e.g., "snap-19") to catch variant tags (snap-1905 vs snap-1906)
    new_files = []
    for file_path in all_files:
        tag = extract_snapshot_tag_from_path(file_path)
        if tag and tag not in existing_tags:
            # Also check prefix — if snap-1905 exists, don't load snap-1906
            prefix = get_snapshot_tag_prefix(tag)
            if prefix not in existing_prefixes:
                new_files.append((file_path, tag))
                summary['new_tags'].add(tag)

    summary['files_to_load'] = len(new_files)

    if not new_files:
        logger.info(f"  {game_date}: {len(all_files)} GCS files, all {len(existing_tags)} tags already loaded")
        return summary

    unique_new_tags = sorted(summary['new_tags'])
    logger.info(
        f"  {game_date}: {len(all_files)} GCS files, {len(existing_tags)} tags in BQ, "
        f"{len(new_files)} new files ({', '.join(unique_new_tags)})"
    )

    if dry_run:
        return summary

    # Step 4: Process new files using OddsApiPropsProcessor
    # Group all rows for batch insert
    all_rows = []
    bucket = storage_client.bucket(BUCKET_NAME)

    for file_path, tag in new_files:
        try:
            blob = bucket.blob(file_path)
            json_content = blob.download_as_text()
            data = json.loads(json_content)

            processor = OddsApiPropsProcessor()
            processor.raw_data = data
            processor.opts = {
                'file_path': file_path,
                'bucket': BUCKET_NAME,
                'project_id': PROJECT_ID
            }
            processor.transform_data()

            if processor.transformed_data:
                all_rows.extend(processor.transformed_data)
                summary['files_loaded'] += 1
            else:
                logger.warning(f"    No rows from {file_path}")
                summary['files_loaded'] += 1  # Still counts as processed

        except Exception as e:
            summary['files_failed'] += 1
            summary['errors'].append(f"{file_path}: {e}")
            logger.error(f"    Failed: {file_path}: {e}")

    # Step 5: Batch append all new rows to BQ
    if all_rows:
        import datetime as dt_module
        # Convert datetime objects to ISO strings for BQ load
        for row in all_rows:
            for key, value in row.items():
                if isinstance(value, (dt_module.date, dt_module.datetime)):
                    row[key] = value.isoformat()

        try:
            target_table = bq_client.get_table(TABLE_ID)
            job_config = bigquery.LoadJobConfig(
                schema=target_table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                ignore_unknown_values=True
            )
            load_job = bq_client.load_table_from_json(
                all_rows,
                TABLE_ID,
                job_config=job_config
            )
            load_job.result(timeout=120)

            if load_job.errors:
                summary['errors'].extend([str(e) for e in load_job.errors])
                logger.error(f"    BQ load errors: {load_job.errors[:3]}")
            else:
                summary['rows_added'] = len(all_rows)
                logger.info(f"    Loaded {len(all_rows)} rows to BQ")

        except Exception as e:
            summary['errors'].append(f"BQ load failed: {e}")
            logger.error(f"    BQ batch load failed: {e}")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description='Backfill missing late-snapshot odds data from GCS to BQ'
    )
    parser.add_argument(
        '--start-date',
        default=DEFAULT_START,
        help=f'Start date YYYY-MM-DD (default: {DEFAULT_START})'
    )
    parser.add_argument(
        '--end-date',
        default=DEFAULT_END,
        help=f'End date YYYY-MM-DD (default: {DEFAULT_END})'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview what would be loaded without writing to BQ'
    )
    args = parser.parse_args()

    mode_label = 'DRY RUN' if args.dry_run else 'LIVE'
    logger.info(f"=== Backfill Late Snapshots ({mode_label}) ===")
    logger.info(f"Date range: {args.start_date} to {args.end_date}")

    bq_client = bigquery.Client(project=PROJECT_ID)
    storage_client = storage.Client(project=PROJECT_ID)

    # Generate date range
    start = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    end = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    dates = []
    current = start
    while current <= end:
        dates.append(current.isoformat())
        current += timedelta(days=1)

    logger.info(f"Processing {len(dates)} dates\n")

    # Process each date
    totals = {
        'dates_processed': 0,
        'dates_with_new_data': 0,
        'total_files_loaded': 0,
        'total_files_failed': 0,
        'total_rows_added': 0,
        'all_new_tags': set()
    }

    for game_date in dates:
        summary = process_date(game_date, bq_client, storage_client, args.dry_run)
        totals['dates_processed'] += 1
        if summary['files_to_load'] > 0:
            totals['dates_with_new_data'] += 1
        totals['total_files_loaded'] += summary['files_loaded']
        totals['total_files_failed'] += summary['files_failed']
        totals['total_rows_added'] += summary['rows_added']
        totals['all_new_tags'].update(summary['new_tags'])

    # Print summary
    logger.info(f"\n=== SUMMARY ({mode_label}) ===")
    logger.info(f"Dates processed: {totals['dates_processed']}")
    logger.info(f"Dates with new data: {totals['dates_with_new_data']}")
    logger.info(f"New snapshot tags found: {len(totals['all_new_tags'])}")
    if totals['all_new_tags']:
        logger.info(f"  Tags: {sorted(totals['all_new_tags'])}")
    if not args.dry_run:
        logger.info(f"Files loaded: {totals['total_files_loaded']}")
        logger.info(f"Files failed: {totals['total_files_failed']}")
        logger.info(f"Rows added to BQ: {totals['total_rows_added']}")


if __name__ == '__main__':
    main()

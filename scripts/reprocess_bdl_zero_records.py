#!/usr/bin/env python3
"""
Reprocess BDL Box Scores with Zero Records

This script systematically reprocesses dates that were blocked by the
0-record idempotency bug. It:
1. Queries run_history for dates with 0 records
2. Deletes those run_history entries
3. Identifies the correct GCS file (complete data, not upcoming games)
4. Triggers manual reprocessing via direct processor call

Usage:
    python scripts/reprocess_bdl_zero_records.py --start-date 2025-12-01 --end-date 2026-01-13
    python scripts/reprocess_bdl_zero_records.py --date 2026-01-12  # Single date
    python scripts/reprocess_bdl_zero_records.py --dry-run  # See what would be reprocessed
"""

import argparse
import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.utils.bigquery_utils import execute_bigquery
from google.cloud import storage
from data_processors.raw.balldontlie.bdl_boxscores_processor import BdlBoxscoresProcessor


def get_zero_record_dates(start_date: str, end_date: str) -> List[Dict]:
    """Get dates with 0-record 'success' runs."""
    query = f"""
    SELECT
        data_date,
        COUNT(*) as zero_record_runs,
        MAX(run_id) as latest_run_id
    FROM `nba-props-platform.nba_reference.processor_run_history`
    WHERE processor_name = 'BdlBoxscoresProcessor'
      AND status = 'success'
      AND records_processed = 0
      AND data_date BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY data_date
    ORDER BY data_date DESC
    """

    return execute_bigquery(query)


def get_gcs_files_for_date(date_str: str) -> List[Dict]:
    """Get all GCS files for a specific date."""
    client = storage.Client()
    bucket = client.bucket('nba-scraped-data')

    prefix = f'ball-dont-lie/boxscores/{date_str}/'
    blobs = list(bucket.list_blobs(prefix=prefix))

    files = []
    for blob in blobs:
        files.append({
            'path': f'gs://nba-scraped-data/{blob.name}',
            'size': blob.size,
            'created': blob.time_created.isoformat(),
            'name': blob.name
        })

    return files


def identify_complete_data_file(files: List[Dict]) -> Optional[Dict]:
    """
    Identify which file has complete player data (not just upcoming games).

    Complete data files are typically:
    - Larger (70KB+ vs 6KB for upcoming games)
    - Created later in the day (after games finish)
    """
    if not files:
        return None

    # Sort by size descending - complete data is much larger
    files_sorted = sorted(files, key=lambda x: x['size'], reverse=True)

    # The largest file is almost always the complete data
    largest = files_sorted[0]

    # Sanity check: complete data should be > 20KB
    if largest['size'] > 20000:
        return largest

    return None


def delete_zero_record_run_history(date_str: str, dry_run: bool = False):
    """Delete 0-record run history entries for a date."""
    query = f"""
    DELETE FROM `nba-props-platform.nba_reference.processor_run_history`
    WHERE processor_name = 'BdlBoxscoresProcessor'
      AND data_date = '{date_str}'
      AND status = 'success'
      AND records_processed = 0
    """

    if dry_run:
        print(f"  [DRY RUN] Would execute: {query}")
        return

    result = execute_bigquery(query)
    print(f"  ✅ Deleted {len(result) if result else 'N'} run history entries")


def reprocess_date(date_str: str, gcs_path: str, dry_run: bool = False):
    """Reprocess a specific date."""
    if dry_run:
        print(f"  [DRY RUN] Would reprocess: {gcs_path}")
        return

    print(f"  🔄 Processing {gcs_path}...")

    try:
        # Extract components from GCS path
        # gs://nba-scraped-data/ball-dont-lie/boxscores/2026-01-12/20260113_030517.json
        parts = gcs_path.replace('gs://nba-scraped-data/', '').split('/')
        file_path = '/'.join(parts)

        # Create processor
        processor = BdlBoxscoresProcessor()

        # Build processing options
        opts = {
            'bucket': 'nba-scraped-data',
            'file_path': file_path,
            'data_date': date_str,
            'season_year': int(date_str.split('-')[0]) - (1 if int(date_str.split('-')[1]) < 10 else 0)
        }

        # Run processor
        success = processor.run(opts)

        if success:
            print(f"  ✅ Successfully reprocessed {date_str}")
        else:
            print(f"  ❌ Failed to reprocess {date_str}")

        return success

    except Exception as e:
        print(f"  ❌ Error reprocessing {date_str}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Reprocess BDL box scores with zero records')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--date', help='Single date to reprocess (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without doing it')
    parser.add_argument('--batch-size', type=int, default=5, help='Number of dates to process at once')

    args = parser.parse_args()

    # Determine date range
    if args.date:
        start_date = args.date
        end_date = args.date
    elif args.start_date and args.end_date:
        start_date = args.start_date
        end_date = args.end_date
    else:
        # Default: last 30 days
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

    print(f"🔍 Reprocessing BDL Box Scores: {start_date} to {end_date}")
    print(f"{'[DRY RUN MODE]' if args.dry_run else '[LIVE MODE]'}")
    print()

    # Step 1: Get dates with 0-record runs
    print("Step 1: Identifying dates with 0-record runs...")
    zero_record_dates = get_zero_record_dates(start_date, end_date)

    if not zero_record_dates:
        print("✅ No dates found with 0-record runs!")
        return

    print(f"Found {len(zero_record_dates)} dates to reprocess:")
    for item in zero_record_dates:
        print(f"  - {item['data_date']}: {item['zero_record_runs']} zero-record runs")
    print()

    # Step 2: Process each date
    print("Step 2: Reprocessing dates...")
    processed = 0
    failed = 0

    for item in zero_record_dates:
        date_str = str(item['data_date'])
        print(f"\n📅 Processing {date_str}...")

        # Get GCS files for this date
        files = get_gcs_files_for_date(date_str)
        print(f"  Found {len(files)} GCS files")

        # Identify complete data file
        complete_file = identify_complete_data_file(files)

        if not complete_file:
            print(f"  ⚠️  No complete data file found (all files < 20KB, likely upcoming games)")
            continue

        print(f"  ✓ Complete data file: {complete_file['path']} ({complete_file['size']} bytes)")

        # Delete 0-record run history
        delete_zero_record_run_history(date_str, dry_run=args.dry_run)

        # Reprocess
        if reprocess_date(date_str, complete_file['path'], dry_run=args.dry_run):
            processed += 1
        else:
            failed += 1

        # Batch control
        if processed > 0 and processed % args.batch_size == 0:
            print(f"\n⏸️  Processed {processed} dates. Pausing 10 seconds before next batch...")
            if not args.dry_run:
                import time
                time.sleep(10)

    # Summary
    print(f"\n" + "=" * 60)
    print(f"✅ Reprocessing Complete!")
    print(f"   Processed: {processed}")
    print(f"   Failed: {failed}")
    print(f"   Total: {len(zero_record_dates)}")
    print("=" * 60)


if __name__ == '__main__':
    main()

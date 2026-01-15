#!/usr/bin/env python3
"""
Phase 2: Process Historical Betting Lines from GCS to BigQuery

Reads all historical pitcher props JSON files from GCS and loads them
to BigQuery using the MlbPitcherPropsProcessor.

Usage:
    # Dry-run to see what would be processed
    python scripts/mlb/historical_odds_backfill/process_historical_to_bigquery.py --dry-run

    # Process all files
    python scripts/mlb/historical_odds_backfill/process_historical_to_bigquery.py

    # Process specific date range
    python scripts/mlb/historical_odds_backfill/process_historical_to_bigquery.py \
        --start-date 2024-06-01 --end-date 2024-06-30

    # Resume from specific date
    python scripts/mlb/historical_odds_backfill/process_historical_to_bigquery.py \
        --skip-to-date 2024-07-15

GCS Input: gs://nba-scraped-data/mlb-odds-api/pitcher-props-history/{date}/{event}/...json
BigQuery Output: mlb_raw.oddsa_pitcher_props
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Set, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from google.cloud import storage, bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = 'nba-props-platform'
BUCKET_NAME = 'nba-scraped-data'
GCS_PREFIX = 'mlb-odds-api/pitcher-props-history'


class HistoricalPropsProcessor:
    """Batch processes historical pitcher props from GCS to BigQuery."""

    def __init__(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        skip_to_date: Optional[str] = None,
        dry_run: bool = False,
        batch_size: int = 50,
    ):
        self.start_date = start_date
        self.end_date = end_date
        self.skip_to_date = skip_to_date
        self.dry_run = dry_run
        self.batch_size = batch_size

        self.storage_client = storage.Client(project=PROJECT_ID)
        self.bucket = self.storage_client.bucket(BUCKET_NAME)
        self.bq_client = bigquery.Client(project=PROJECT_ID)

        # Set environment for processor
        os.environ['SPORT'] = 'mlb'
        os.environ['GCP_PROJECT_ID'] = PROJECT_ID

        # Import processor after setting environment
        from data_processors.raw.mlb.mlb_pitcher_props_processor import MlbPitcherPropsProcessor
        self.ProcessorClass = MlbPitcherPropsProcessor

        # Stats tracking
        self.stats = {
            'dates_found': 0,
            'dates_processed': 0,
            'dates_skipped': 0,
            'files_found': 0,
            'files_processed': 0,
            'files_failed': 0,
            'rows_loaded': 0,
            'start_time': None,
        }

        # Track already processed files
        self.processed_files: Set[str] = set()

    def get_gcs_dates(self) -> List[str]:
        """List all date directories in GCS."""
        dates = set()

        # List all blobs and extract dates from paths
        # Path format: mlb-odds-api/pitcher-props-history/2024-06-15/event_id/file.json
        logger.info("Scanning GCS for available dates...")
        blobs = self.bucket.list_blobs(prefix=f"{GCS_PREFIX}/")

        blob_count = 0
        for blob in blobs:
            blob_count += 1
            parts = blob.name.split('/')
            if len(parts) >= 3:
                date_str = parts[2]  # Index 2 is the date portion
                # Validate date format
                try:
                    datetime.strptime(date_str, '%Y-%m-%d')
                    dates.add(date_str)
                except ValueError:
                    continue

            # Progress indicator for large scans
            if blob_count % 5000 == 0:
                logger.info(f"  Scanned {blob_count} blobs, found {len(dates)} dates...")

        sorted_dates = sorted(dates)
        logger.info(f"Found {len(sorted_dates)} dates in GCS (from {blob_count} blobs)")

        return sorted_dates

    def filter_dates(self, dates: List[str]) -> List[str]:
        """Apply date filters."""
        filtered = dates

        # Apply start/end filters
        if self.start_date:
            filtered = [d for d in filtered if d >= self.start_date]
        if self.end_date:
            filtered = [d for d in filtered if d <= self.end_date]

        # Apply skip-to-date filter
        if self.skip_to_date:
            try:
                skip_idx = filtered.index(self.skip_to_date)
                self.stats['dates_skipped'] = skip_idx
                filtered = filtered[skip_idx:]
                logger.info(f"Skipping to {self.skip_to_date}, {len(filtered)} dates remaining")
            except ValueError:
                logger.warning(f"Skip-to-date {self.skip_to_date} not found in GCS")

        return filtered

    def get_files_for_date(self, game_date: str) -> List[str]:
        """Get all JSON files for a specific date."""
        prefix = f"{GCS_PREFIX}/{game_date}/"
        blobs = list(self.bucket.list_blobs(prefix=prefix))

        json_files = [
            blob.name for blob in blobs
            if blob.name.endswith('.json')
        ]

        return json_files

    def check_already_loaded(self, game_date: str) -> int:
        """Check how many rows already exist in BigQuery for this date."""
        query = f"""
        SELECT COUNT(*) as cnt
        FROM `{PROJECT_ID}.mlb_raw.oddsa_pitcher_props`
        WHERE game_date = '{game_date}'
          AND source_file_path LIKE '%pitcher-props-history%'
        """
        try:
            result = list(self.bq_client.query(query).result())
            return result[0].cnt if result else 0
        except Exception as e:
            logger.debug(f"Could not check existing rows: {e}")
            return 0

    def process_file(self, file_path: str) -> Dict:
        """Process a single GCS file."""
        # file_path is already relative path like: mlb-odds-api/pitcher-props-history/2024-04-09/...
        # The processor's load_json_from_gcs will prepend gs://bucket/ internally

        try:
            processor = self.ProcessorClass()
            processor.opts = {
                'bucket': BUCKET_NAME,
                'file_path': file_path,  # Don't add gs://bucket/ - processor does that
            }

            # Initialize GCP clients (required before load_data)
            processor.init_clients()

            # Run the processor
            processor.load_data()
            processor.transform_data()
            processor.save_data()

            rows = processor.stats.get('rows_inserted', 0)

            return {
                'status': 'success',
                'rows': rows,
                'file': file_path,
            }

        except Exception as e:
            logger.warning(f"Failed to process {file_path}: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'file': file_path,
            }

    def process_date(self, game_date: str, date_idx: int, total_dates: int) -> None:
        """Process all files for a single date."""
        logger.info(f"\n[{date_idx}/{total_dates}] Processing {game_date}")

        files = self.get_files_for_date(game_date)
        self.stats['files_found'] += len(files)

        if not files:
            logger.info(f"  No files found for {game_date}")
            return

        logger.info(f"  Found {len(files)} files")

        if self.dry_run:
            existing = self.check_already_loaded(game_date)
            logger.info(f"  DRY RUN: Would process {len(files)} files ({existing} rows already in BQ)")
            return

        # Process files
        date_rows = 0
        for file_path in files:
            result = self.process_file(file_path)

            if result['status'] == 'success':
                self.stats['files_processed'] += 1
                date_rows += result.get('rows', 0)
            else:
                self.stats['files_failed'] += 1

        self.stats['rows_loaded'] += date_rows
        self.stats['dates_processed'] += 1

        logger.info(f"  Loaded {date_rows} rows from {len(files)} files")

    def log_progress(self) -> None:
        """Log current progress."""
        elapsed = time.time() - self.stats['start_time']

        if self.stats['dates_processed'] > 0:
            rate = self.stats['dates_processed'] / (elapsed / 60)
            logger.info(
                f"Progress: {self.stats['dates_processed']} dates | "
                f"{self.stats['files_processed']} files | "
                f"{self.stats['rows_loaded']} rows | "
                f"{rate:.1f} dates/min"
            )

    def run(self) -> Dict:
        """Execute the batch processing."""
        self.stats['start_time'] = time.time()

        logger.info("=" * 70)
        logger.info("PHASE 2: HISTORICAL PROPS GCS → BIGQUERY")
        logger.info("=" * 70)

        # Get dates from GCS
        dates = self.get_gcs_dates()
        self.stats['dates_found'] = len(dates)

        if not dates:
            logger.warning("No dates found in GCS!")
            return self.stats

        # Filter dates
        dates = self.filter_dates(dates)

        logger.info(f"\nConfiguration:")
        logger.info(f"  Dates to process: {len(dates)}")
        logger.info(f"  Dry run: {self.dry_run}")
        logger.info(f"  Batch size: {self.batch_size}")
        logger.info("")

        # Process each date
        total_dates = len(dates)
        for i, game_date in enumerate(dates, 1):
            self.process_date(game_date, i, total_dates)

            # Log progress every 10 dates
            if i % 10 == 0:
                self.log_progress()

        # Final summary
        elapsed = time.time() - self.stats['start_time']

        logger.info("\n" + "=" * 70)
        logger.info("PHASE 2 COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Total time: {elapsed/60:.1f} minutes")
        logger.info(f"Dates in GCS: {self.stats['dates_found']}")
        logger.info(f"Dates processed: {self.stats['dates_processed']}")
        logger.info(f"Dates skipped: {self.stats['dates_skipped']}")
        logger.info(f"Files found: {self.stats['files_found']}")
        logger.info(f"Files processed: {self.stats['files_processed']}")
        logger.info(f"Files failed: {self.stats['files_failed']}")
        logger.info(f"Rows loaded to BigQuery: {self.stats['rows_loaded']}")

        if not self.dry_run and self.stats['rows_loaded'] > 0:
            logger.info("\n" + "-" * 70)
            logger.info("NEXT STEPS:")
            logger.info("-" * 70)
            logger.info("1. Run Phase 3 - Match betting lines to predictions:")
            logger.info("   python scripts/mlb/historical_odds_backfill/match_lines_to_predictions.py")
            logger.info("")
            logger.info("2. Run Phase 4 - Grade predictions:")
            logger.info("   python scripts/mlb/historical_odds_backfill/grade_historical_predictions.py")

        return self.stats


def main():
    parser = argparse.ArgumentParser(
        description='Process historical pitcher props from GCS to BigQuery',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        '--start-date',
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        help='End date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--skip-to-date',
        help='Skip to this date (for resuming)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be processed without loading to BigQuery'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=50,
        help='Number of files to process in each batch'
    )

    args = parser.parse_args()

    processor = HistoricalPropsProcessor(
        start_date=args.start_date,
        end_date=args.end_date,
        skip_to_date=args.skip_to_date,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
    )

    try:
        stats = processor.run()

        if stats['files_failed'] > 0 and stats['files_processed'] == 0:
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("\n\nProcessing interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Processing failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

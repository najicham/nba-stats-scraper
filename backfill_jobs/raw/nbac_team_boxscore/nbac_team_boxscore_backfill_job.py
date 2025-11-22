#!/usr/bin/env python3
"""
File: backfill_jobs/raw/nbac_team_boxscore/nbac_team_boxscore_backfill_job.py
Description: Backfill job for processing NBA.com team boxscore data from GCS to BigQuery

Processes team-level statistics from NBA.com API for historical date ranges.
Supports smart idempotency to skip unchanged data and reduce BigQuery costs.

Usage:
    # Dry run
    python nbac_team_boxscore_backfill_job.py --dry-run --limit=10

    # Date range
    python nbac_team_boxscore_backfill_job.py --start-date=2024-11-01 --end-date=2024-11-30

    # Single day
    python nbac_team_boxscore_backfill_job.py --start-date=2024-11-20 --end-date=2024-11-20
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List
from google.cloud import storage

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from data_processors.raw.nbacom.nbac_team_boxscore_processor import NbacTeamBoxscoreProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TeamBoxscoreBackfill:
    """
    Backfill processor for NBA.com team boxscore data.

    Handles historical data processing from GCS to BigQuery with smart idempotency.
    Each game produces exactly 2 records (one per team).
    """

    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        """
        Initialize backfill processor.

        Args:
            bucket_name: GCS bucket containing scraped data
        """
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = NbacTeamBoxscoreProcessor()
        self.base_path = 'nba-com/team-boxscore'

        logger.info(f"Initialized Team Boxscore Backfill")
        logger.info(f"  Bucket: {bucket_name}")
        logger.info(f"  Base path: {self.base_path}")

    def list_files(
        self,
        start_date: date,
        end_date: date,
        limit: int = None
    ) -> List[str]:
        """
        List team boxscore files in date range.

        Uses smart path discovery to find latest file for each date.
        Path format: gs://nba-scraped-data/nba-com/team-boxscore/YYYYMMDD/game_id/*.json

        Args:
            start_date: First date to process
            end_date: Last date to process (inclusive)
            limit: Maximum number of files to return

        Returns:
            List of GCS file paths (gs://bucket/path/to/file.json)
        """
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []

        current_date = start_date
        while current_date <= end_date:
            # Try YYYYMMDD format (matches GCS structure)
            date_str = current_date.strftime('%Y%m%d')
            prefix = f"{self.base_path}/{date_str}/"

            try:
                blobs = bucket.list_blobs(prefix=prefix)

                # Group files by game_id directory
                game_files = {}
                for blob in blobs:
                    if blob.name.endswith('.json'):
                        # Extract game_id from path: nba-com/team-boxscore/20241120/0022400259/file.json
                        path_parts = blob.name.split('/')
                        if len(path_parts) >= 4:
                            game_id = path_parts[3]  # 0022400259
                            if game_id not in game_files:
                                game_files[game_id] = []
                            file_path = f"gs://{self.bucket_name}/{blob.name}"
                            game_files[game_id].append((blob.time_created, file_path))

                # Use latest file for each game
                for game_id, files in game_files.items():
                    files.sort(reverse=True)  # Sort by time_created descending
                    all_files.append(files[0][1])  # Take latest file
                    logger.debug(
                        f"Date {date_str}, Game {game_id}: "
                        f"Found {len(files)} files, using latest"
                    )

                if game_files:
                    logger.info(f"Found {len(game_files)} games for {date_str}")

            except Exception as e:
                logger.debug(f"No files found for {date_str}: {e}")
                continue

            current_date += timedelta(days=1)

            if limit and len(all_files) >= limit:
                all_files = all_files[:limit]
                logger.info(f"Limiting to {limit} files")
                break

        logger.info(f"Total files to process: {len(all_files)}")
        return all_files

    def process_file(self, file_path: str) -> Dict:
        """
        Process a single team boxscore file.

        Args:
            file_path: GCS path to file (gs://bucket/path/to/file.json)

        Returns:
            Dict with processing results:
                - status: 'success', 'skipped', 'validation_failed', or 'error'
                - rows: Number of rows processed (if successful)
                - error: Error message (if failed)
                - skipped: True if smart idempotency skipped write
        """
        try:
            # Extract bucket and path
            if not file_path.startswith('gs://'):
                raise ValueError(f"Invalid GCS path: {file_path}")

            path_parts = file_path.replace('gs://', '').split('/', 1)
            if len(path_parts) != 2:
                raise ValueError(f"Could not parse GCS path: {file_path}")

            bucket = path_parts[0]
            blob_path = path_parts[1]

            # Run processor
            result = self.processor.run({
                'bucket': bucket,
                'file_path': blob_path
            })

            # Check for smart idempotency skip
            stats = self.processor.get_idempotency_stats()
            if stats.get('rows_skipped', 0) > 0:
                logger.info(f"✓ Skipped (unchanged): {stats['rows_skipped']} rows")
                return {
                    'file_path': file_path,
                    'status': 'skipped',
                    'rows': 0,
                    'skipped': True
                }

            # Success
            logger.info(f"✓ Success: Processed 2 teams")
            return {
                'file_path': file_path,
                'status': 'success',
                'rows': 2,  # Always 2 teams per game
                'skipped': False
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"✗ Error: {error_msg}")
            return {
                'file_path': file_path,
                'status': 'error',
                'error': error_msg,
                'skipped': False
            }

    def run_backfill(
        self,
        start_date: date,
        end_date: date,
        dry_run: bool = False,
        limit: int = None
    ):
        """
        Run the backfill process.

        Args:
            start_date: First date to process
            end_date: Last date to process (inclusive)
            dry_run: If True, list files but don't process
            limit: Maximum number of files to process
        """
        logger.info("=" * 70)
        logger.info(f"NBA.com Team Boxscore Backfill")
        logger.info(f"Date range: {start_date} to {end_date}")
        if limit:
            logger.info(f"File limit: {limit}")
        if dry_run:
            logger.info("DRY RUN MODE - no data will be processed")
        logger.info("=" * 70)

        # List files
        files = self.list_files(start_date, end_date, limit)

        if not files:
            logger.warning("No files found to process")
            return

        if dry_run:
            logger.info(f"\nDRY RUN: Would process {len(files)} files:")
            for i, file_path in enumerate(files, 1):
                logger.info(f"  {i:3d}. {file_path}")
            return

        # Process files
        results = {
            'success': 0,
            'skipped': 0,
            'error': 0,
            'total_rows': 0
        }

        for i, file_path in enumerate(files, 1):
            logger.info(f"\nProcessing {i}/{len(files)}: {file_path}")

            result = self.process_file(file_path)
            status = result['status']

            if status == 'success':
                results['success'] += 1
                results['total_rows'] += result.get('rows', 0)
            elif status == 'skipped':
                results['skipped'] += 1
            else:
                results['error'] += 1

        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("BACKFILL SUMMARY:")
        logger.info(f"  Success: {results['success']} games")
        logger.info(f"  Skipped (smart idempotency): {results['skipped']} games")
        logger.info(f"  Errors: {results['error']} games")
        logger.info(f"  Total Teams Processed: {results['total_rows']}")

        # Calculate skip rate
        total_attempted = results['success'] + results['skipped']
        if total_attempted > 0:
            skip_rate = (results['skipped'] / total_attempted) * 100
            logger.info(f"  Skip Rate: {skip_rate:.1f}% (cost savings!)")

        logger.info("=" * 70)


def main():
    """Main entry point for backfill job."""
    parser = argparse.ArgumentParser(
        description='Backfill NBA.com team boxscore data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to see what would be processed
  python nbac_team_boxscore_backfill_job.py --dry-run --limit=10

  # Process single day
  python nbac_team_boxscore_backfill_job.py --start-date=2024-11-20 --end-date=2024-11-20

  # Process date range
  python nbac_team_boxscore_backfill_job.py --start-date=2024-11-01 --end-date=2024-11-30

  # Process with limit
  python nbac_team_boxscore_backfill_job.py --limit=10
        """
    )
    parser.add_argument(
        '--start-date',
        type=str,
        help='Start date (YYYY-MM-DD). Default: 30 days ago'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        help='End date (YYYY-MM-DD). Default: today'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='List files without processing'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of files processed'
    )

    args = parser.parse_args()

    # Default date range
    if args.start_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    else:
        start_date = date.today() - timedelta(days=30)

    if args.end_date:
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    else:
        end_date = date.today()

    # Run backfill
    backfiller = TeamBoxscoreBackfill()
    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()

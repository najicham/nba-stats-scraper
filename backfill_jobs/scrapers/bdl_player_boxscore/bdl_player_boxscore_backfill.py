#!/usr/bin/env python3
"""
BallDontLie Player Boxscore Backfill Script
============================================

This script backfills player boxscore data using the BallDontLie API
for dates that failed when using NBA.com API.

Usage:
    python backfill_jobs/scrapers/bdl_player_boxscore/bdl_player_boxscore_backfill.py \
        --dates-file /tmp/failed_dates_from_nbac.txt \
        --workers 6 \
        --batch-size 7

Options:
    --dates-file    File containing dates to backfill (one per line, YYYY-MM-DD format)
    --workers       Number of parallel workers (default: 6)
    --batch-size    Number of dates per batch/API call (default: 7 days)
    --timeout       Timeout per batch in seconds (default: 120)
    --dry-run       Show what would be done without executing
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parents[3]))

from scrapers.balldontlie.bdl_player_box_scores import BdlPlayerBoxScoresScraper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class BdlBackfillRunner:
    """Manages backfill execution using BallDontLie API"""

    def __init__(self, dates_file: str, workers: int = 6, batch_size: int = 7,
                 timeout: int = 120, dry_run: bool = False):
        self.dates_file = dates_file
        self.workers = workers
        self.batch_size = batch_size
        self.timeout = timeout
        self.dry_run = dry_run

        # Stats
        self.total_dates = 0
        self.total_batches = 0
        self.succeeded = []
        self.failed = []
        self.skipped = []

        # Load dates
        self.dates = self._load_dates()
        self.batches = self._create_batches()

    def _load_dates(self) -> List[str]:
        """Load dates from file"""
        with open(self.dates_file, 'r') as f:
            dates = [line.strip() for line in f if line.strip()]

        # Validate and sort
        dates = sorted(set(dates))
        self.total_dates = len(dates)
        logger.info(f"Loaded {self.total_dates} unique dates from {self.dates_file}")
        return dates

    def _create_batches(self) -> List[Tuple[str, str, int]]:
        """Create date range batches for API calls"""
        batches = []
        for i in range(0, len(self.dates), self.batch_size):
            batch_dates = self.dates[i:i + self.batch_size]
            start_date = batch_dates[0]
            end_date = batch_dates[-1]
            batch_num = i // self.batch_size + 1
            batches.append((start_date, end_date, len(batch_dates)))

        self.total_batches = len(batches)
        logger.info(f"Created {self.total_batches} batches (batch size: {self.batch_size} dates)")
        return batches

    def _scrape_batch(self, batch_info: Tuple[str, str, int], batch_num: int) -> dict:
        """Scrape a single batch of dates"""
        start_date, end_date, num_dates = batch_info

        try:
            logger.info(f"[{batch_num}/{self.total_batches}] Scraping {start_date} to {end_date} ({num_dates} dates)")

            if self.dry_run:
                logger.info(f"  [DRY RUN] Would scrape: {start_date} to {end_date}")
                return {
                    'status': 'dry_run',
                    'start_date': start_date,
                    'end_date': end_date,
                    'num_dates': num_dates
                }

            # Create scraper instance
            scraper = BdlPlayerBoxScoresScraper()

            # Set options
            scraper.opts = {
                'startDate': start_date,
                'endDate': end_date,
                'perPage': 100,
                'api_key': os.getenv('BDL_API_KEY')
            }

            # Set export groups to prod (GCS export)
            scraper.export_groups = ['prod', 'gcs']

            # Run scraper
            start_time = time.time()
            scraper.scrape()
            duration = time.time() - start_time

            # Get stats
            stats = scraper.get_scraper_stats()
            row_count = stats.get('rowCount', 0)

            logger.info(f"  ✅ Scraped {row_count} player boxscore rows in {duration:.1f}s")

            return {
                'status': 'success',
                'start_date': start_date,
                'end_date': end_date,
                'num_dates': num_dates,
                'row_count': row_count,
                'duration': duration
            }

        except Exception as e:
            error_msg = str(e)
            logger.warning(f"  ❌ Failed {start_date} to {end_date}: {error_msg}")

            return {
                'status': 'failed',
                'start_date': start_date,
                'end_date': end_date,
                'num_dates': num_dates,
                'error': error_msg
            }

    def run(self):
        """Execute backfill with parallel workers"""
        logger.info("=" * 70)
        logger.info("BallDontLie Player Boxscore Backfill")
        logger.info(f"  Total dates: {self.total_dates}")
        logger.info(f"  Total batches: {self.total_batches}")
        logger.info(f"  Workers: {self.workers}")
        logger.info(f"  Batch size: {self.batch_size} dates")
        logger.info(f"  Timeout: {self.timeout}s per batch")
        if self.dry_run:
            logger.info("  MODE: DRY RUN")
        logger.info("=" * 70)

        start_time = time.time()

        # Process batches in parallel
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self._scrape_batch, batch, i + 1): (batch, i + 1)
                for i, batch in enumerate(self.batches)
            }

            completed = 0
            for future in as_completed(futures):
                result = future.result()
                completed += 1

                if result['status'] == 'success':
                    self.succeeded.append(result)
                elif result['status'] == 'failed':
                    self.failed.append(result)
                elif result['status'] == 'dry_run':
                    logger.info(f"  [DRY RUN] Batch {completed}/{self.total_batches}")

                # Progress update every 10 batches
                if completed % 10 == 0:
                    success_count = len(self.succeeded)
                    fail_count = len(self.failed)
                    success_rate = (success_count / completed * 100) if completed > 0 else 0
                    logger.info(f"📊 Progress: {completed}/{self.total_batches} batches | "
                              f"✅ {success_count} | ❌ {fail_count} | "
                              f"{success_rate:.1f}% success rate")

        # Final summary
        duration = time.time() - start_time
        self._print_summary(duration)

        # Save failed batches
        if self.failed and not self.dry_run:
            self._save_failed()

    def _print_summary(self, duration: float):
        """Print final summary"""
        logger.info("=" * 70)
        logger.info("BACKFILL COMPLETE")
        logger.info(f"Total batches: {self.total_batches}")
        logger.info(f"✅ Succeeded: {len(self.succeeded)}")
        logger.info(f"❌ Failed: {len(self.failed)}")
        logger.info(f"Time: {duration / 60:.1f} minutes")
        logger.info(f"Rate: {self.total_batches / (duration / 60):.1f} batches/min")

        if self.succeeded:
            total_rows = sum(r.get('row_count', 0) for r in self.succeeded)
            logger.info(f"Total player boxscore rows: {total_rows:,}")

        logger.info("=" * 70)

    def _save_failed(self):
        """Save failed batches to file"""
        if not self.failed:
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        failed_file = Path(self.dates_file).parent / f"bdl_failed_batches_{timestamp}.json"

        output = {
            'timestamp': datetime.now().isoformat(),
            'total_failed': len(self.failed),
            'failed_batches': self.failed
        }

        with open(failed_file, 'w') as f:
            json.dump(output, f, indent=2)

        logger.info(f"💾 Failed batches saved to: {failed_file}")


def main():
    parser = argparse.ArgumentParser(description='Backfill player boxscores using BallDontLie API')
    parser.add_argument('--dates-file', required=True, help='File with dates to backfill')
    parser.add_argument('--workers', type=int, default=6, help='Number of parallel workers')
    parser.add_argument('--batch-size', type=int, default=7, help='Number of dates per batch')
    parser.add_argument('--timeout', type=int, default=120, help='Timeout per batch (seconds)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')

    args = parser.parse_args()

    # Check BDL API key
    if not args.dry_run and not os.getenv('BDL_API_KEY'):
        logger.error("❌ BDL_API_KEY environment variable not set!")
        logger.error("   Get your API key from https://www.balldontlie.io/")
        sys.exit(1)

    # Check dates file exists
    if not Path(args.dates_file).exists():
        logger.error(f"❌ Dates file not found: {args.dates_file}")
        sys.exit(1)

    # Run backfill
    runner = BdlBackfillRunner(
        dates_file=args.dates_file,
        workers=args.workers,
        batch_size=args.batch_size,
        timeout=args.timeout,
        dry_run=args.dry_run
    )

    runner.run()


if __name__ == '__main__':
    main()

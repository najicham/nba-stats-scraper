#!/usr/bin/env python3
"""
NBA.com Player Boxscore Scraper Backfill Job (v2 - Fixed)
==========================================================

Backfills player boxscore data from NBA.com for all historical game dates.
This script calls the scraper service to fetch data and save to GCS.

FIXES from v1:
- Uses POST /scrape endpoint (not GET)
- Correct parameter format: {"scraper": "nbac_player_boxscore", "gamedate": "YYYYMMDD", "export_groups": "prod"}
- Added multi-worker support for parallel processing

Usage:
  # Dry run (see what would be processed):
  python nbac_player_boxscore_scraper_backfill_v2.py --dry-run --limit=10

  # Process all dates with 12 concurrent workers:
  python nbac_player_boxscore_scraper_backfill_v2.py \
    --service-url=https://nba-phase1-scrapers-756957797294.us-west2.run.app \
    --workers=12

  # Process specific season:
  python nbac_player_boxscore_scraper_backfill_v2.py --season=2024 --workers=12

  # Resume from specific date:
  python nbac_player_boxscore_scraper_backfill_v2.py --start-date=2024-01-01
"""

import argparse
import csv
import json
import logging
import os
import requests
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from google.cloud import storage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NbacPlayerBoxscoreScraperBackfill:
    """Backfill job for NBA.com player boxscore data."""

    def __init__(
        self,
        scraper_service_url: str,
        bucket_name: str = "nba-scraped-data",
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        season: Optional[int] = None,
        workers: int = 1,
        timeout: int = 60
    ):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.bucket_name = bucket_name
        self.limit = limit
        self.start_date = start_date
        self.season = season
        self.workers = workers
        self.timeout = timeout

        # Initialize GCS client
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)

        # Thread-safe counters
        self._lock = threading.Lock()
        self.total_dates = 0
        self.processed_count = 0
        self.skipped_count = 0
        self.failed_dates = []
        self.success_dates = []

        # Output directory for logs
        self.output_dir = Path(__file__).parent
        self.failed_dates_file = self.output_dir / f"failed_dates_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        # GCS path for player boxscores
        self.gcs_base_path = "nba-com/player-boxscores"

        logger.info("NBA.com Player Boxscore Scraper Backfill (v2) initialized")
        logger.info(f"  Scraper service: {self.scraper_service_url}")
        logger.info(f"  GCS bucket: {self.bucket_name}")
        logger.info(f"  Workers: {self.workers}")
        logger.info(f"  Timeout: {self.timeout}s")
        if self.limit:
            logger.info(f"  Limit: {self.limit} dates")
        if self.start_date:
            logger.info(f"  Start date: {self.start_date}")
        if self.season:
            logger.info(f"  Season filter: {self.season}")

    def load_game_dates(self, csv_path: str) -> List[str]:
        """Load game dates from CSV file."""
        dates = []

        with open(csv_path, 'r') as f:
            # Check if first line is header
            first_line = f.readline().strip()
            if first_line and not first_line.startswith('20'):
                pass  # Skip header
            else:
                f.seek(0)  # No header, reset to beginning

            for line in f:
                game_date = line.strip()
                if not game_date:
                    continue

                # Apply filters
                if self.start_date and game_date < self.start_date:
                    continue

                if self.season:
                    # Filter by season (Oct-Jun)
                    year = int(game_date[:4])
                    month = int(game_date[5:7])
                    game_season = year if month >= 10 else year - 1
                    if game_season != self.season:
                        continue

                dates.append(game_date)

        # Apply limit
        if self.limit:
            dates = dates[:self.limit]

        return dates

    def date_already_scraped(self, game_date: str) -> bool:
        """Check if date data already exists in GCS."""
        try:
            # Format: nba-com/player-boxscores/YYYY-MM-DD/
            prefix = f"{self.gcs_base_path}/{game_date}/"

            blobs = list(self.bucket.list_blobs(prefix=prefix, max_results=1))
            return len(blobs) > 0

        except Exception as e:
            logger.debug(f"Error checking if date {game_date} exists: {e}")
            return False

    def scrape_date(self, game_date: str) -> Dict:
        """Scrape a single date via the scraper service. Returns result dict."""
        result = {
            'game_date': game_date,
            'status': 'unknown',
            'error': None
        }

        try:
            # Convert YYYY-MM-DD to YYYYMMDD for the API
            gamedate_formatted = game_date.replace('-', '')

            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": "nbac_player_boxscore",
                    "gamedate": gamedate_formatted,
                    "export_groups": "prod"
                },
                timeout=self.timeout
            )

            if response.status_code == 200:
                result['status'] = 'success'
                logger.info(f"  ✅ Scraped {game_date}")
            else:
                result['status'] = 'failed'
                result['error'] = f"HTTP {response.status_code}"
                logger.warning(f"  ❌ Failed {game_date}: HTTP {response.status_code}")

        except requests.exceptions.Timeout:
            result['status'] = 'timeout'
            result['error'] = f"Timeout after {self.timeout}s"
            logger.warning(f"  ❌ Timeout {game_date}")

        except Exception as e:
            result['status'] = 'error'
            result['error'] = str(e)
            logger.warning(f"  ❌ Error {game_date}: {e}")

        return result

    def process_date(self, game_date: str, progress_info: Dict) -> Dict:
        """Process a single date (check if exists, scrape if needed)."""
        # Check if already scraped (skip if exists)
        if self.date_already_scraped(game_date):
            with self._lock:
                self.skipped_count += 1
            logger.debug(f"  ⏭️  Skipped {game_date} (already exists)")
            return {'game_date': game_date, 'status': 'skipped'}

        # Scrape the date
        result = self.scrape_date(game_date)

        # Update counters
        with self._lock:
            if result['status'] == 'success':
                self.processed_count += 1
                self.success_dates.append(game_date)
            else:
                self.failed_dates.append(result)

            # Progress logging every 50 dates
            total_done = self.processed_count + self.skipped_count + len(self.failed_dates)
            if total_done % 50 == 0:
                elapsed = (datetime.now() - progress_info['start_time']).total_seconds()
                rate = total_done / elapsed if elapsed > 0 else 0
                remaining = self.total_dates - total_done
                eta_minutes = (remaining / rate / 60) if rate > 0 else 0
                logger.info(
                    f"📊 Progress: {total_done}/{self.total_dates} "
                    f"({total_done/self.total_dates*100:.1f}%) | "
                    f"✅ {self.processed_count} | ⏭️ {self.skipped_count} | "
                    f"❌ {len(self.failed_dates)} | ETA: {eta_minutes:.0f}min"
                )

        return result

    def save_failed_dates(self):
        """Save failed dates to JSON file for retry."""
        if self.failed_dates:
            with open(self.failed_dates_file, 'w') as f:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'total_failed': len(self.failed_dates),
                    'failed_dates': self.failed_dates
                }, f, indent=2)
            logger.info(f"💾 Failed dates saved to: {self.failed_dates_file}")

    def run(self, csv_path: str, dry_run: bool = False):
        """Execute the backfill job."""
        start_time = datetime.now()

        logger.info("=" * 70)
        logger.info("NBA.com Player Boxscore Scraper Backfill (v2)")
        logger.info(f"Workers: {self.workers} | Timeout: {self.timeout}s")
        if dry_run:
            logger.info("DRY RUN MODE - no scraping will be performed")
        logger.info("=" * 70)

        # Load dates from CSV
        dates = self.load_game_dates(csv_path)
        self.total_dates = len(dates)
        logger.info(f"Loaded {self.total_dates} dates from {csv_path}")

        if dry_run:
            logger.info("DRY RUN - Sample dates:")
            for i, game_date in enumerate(dates[:10], 1):
                logger.info(f"  {i}. {game_date}")
            logger.info("DRY RUN complete. Use without --dry-run to execute.")
            return

        # Process dates with worker pool
        progress_info = {'start_time': datetime.now()}

        if self.workers == 1:
            # Single-threaded mode
            for i, game_date in enumerate(dates, 1):
                logger.info(f"[{i}/{self.total_dates}] Processing {game_date}")
                self.process_date(game_date, progress_info)
        else:
            # Multi-threaded mode
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                future_to_date = {}
                for i, game_date in enumerate(dates, 1):
                    future = executor.submit(self.process_date, game_date, progress_info)
                    future_to_date[future] = game_date
                    logger.info(f"[{i}/{self.total_dates}] Queued {game_date}")

                # Wait for completion
                for future in as_completed(future_to_date):
                    game_date = future_to_date[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        logger.error(f"Exception processing {game_date}: {e}")
                        self.failed_dates.append({
                            'game_date': game_date,
                            'status': 'exception',
                            'error': str(e)
                        })

        # Final stats
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info("=" * 70)
        logger.info("BACKFILL COMPLETE")
        logger.info(f"Total dates: {self.total_dates}")
        logger.info(f"✅ Processed: {self.processed_count}")
        logger.info(f"⏭️  Skipped: {self.skipped_count}")
        logger.info(f"❌ Failed: {len(self.failed_dates)}")
        logger.info(f"Time: {elapsed/60:.1f} minutes")
        logger.info(f"Rate: {self.total_dates/elapsed*60:.1f} dates/min")
        logger.info("=" * 70)

        # Save failed dates if any
        self.save_failed_dates()


def main():
    parser = argparse.ArgumentParser(description="Backfill NBA.com Player Boxscore data")
    parser.add_argument(
        '--csv',
        default=str(Path(__file__).parent / 'game_dates_to_scrape.csv'),
        help='Path to CSV file with game dates'
    )
    parser.add_argument(
        '--service-url',
        required=True,
        help='URL of the scraper service'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=1,
        help='Number of concurrent workers (default: 1)'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=60,
        help='Request timeout in seconds (default: 60)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Don't actually scrape, just show what would be done"
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of dates to process'
    )
    parser.add_argument(
        '--start-date',
        help='Start from this date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--season',
        type=int,
        help='Filter to specific season (e.g., 2024 for 2024-25)'
    )

    args = parser.parse_args()

    backfill = NbacPlayerBoxscoreScraperBackfill(
        scraper_service_url=args.service_url,
        limit=args.limit,
        start_date=args.start_date,
        season=args.season,
        workers=args.workers,
        timeout=args.timeout
    )

    backfill.run(args.csv, dry_run=args.dry_run)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
NBA.com Player Boxscore Scraper Backfill Job
=============================================
Backfills player boxscore data from NBA.com for all historical game dates.
This script calls the scraper service to fetch data and save to GCS.

Usage:
  # Dry run (see what would be processed):
  python nbac_player_boxscore_scraper_backfill.py --dry-run --limit=20

  # Full backfill with service URL:
  python nbac_player_boxscore_scraper_backfill.py \
    --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app

  # Backfill specific season (2024 = 2024-25 season):
  python nbac_player_boxscore_scraper_backfill.py \
    --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app \
    --season=2024

  # Backfill from specific date:
  python nbac_player_boxscore_scraper_backfill.py \
    --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app \
    --start-date=2024-01-01
"""

import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

import requests
from shared.clients.http_pool import get_http_session
from google.cloud import storage

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NbacPlayerBoxscoreBackfill:
    """Backfill player boxscore data from NBA.com."""

    def __init__(
        self,
        service_url: str = "https://placeholder",
        rate_limit: float = 1.0,
        dry_run: bool = False,
        start_date: Optional[str] = None,
        season: Optional[int] = None,
    ):
        self.service_url = service_url.rstrip('/')
        self.rate_limit = rate_limit
        self.dry_run = dry_run
        self.start_date = start_date
        self.season = season

        # GCS paths
        self.gcs_bucket = "nba-scraped-data"
        self.gcs_base_path = "nba-com/player-boxscores"

        # Stats
        self.processed_dates = []
        self.skipped_dates = []
        self.failed_dates = []

        logger.info("NBA.com Player Boxscore Scraper Backfill initialized")
        logger.info(f"  Scraper service: {self.service_url}")
        logger.info(f"  Rate limit: {self.rate_limit}s between requests")
        logger.info(f"  Dry run: {self.dry_run}")
        if self.start_date:
            logger.info(f"  Start date: {self.start_date}")
        if self.season:
            logger.info(f"  Season filter: {self.season}-{self.season+1}")

    def load_game_dates(self, csv_path: str) -> List[str]:
        """Load unique game dates from CSV file."""
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

                # Apply start date filter
                if self.start_date and game_date < self.start_date:
                    continue

                # Apply season filter
                if self.season:
                    year = int(game_date[:4])
                    month = int(game_date[5:7])
                    # Season starts in October (month 10)
                    game_season = year if month >= 10 else year - 1
                    if game_season != self.season:
                        continue

                dates.append(game_date)

        return sorted(set(dates))

    def date_already_scraped(self, game_date: str) -> bool:
        """Check if a date has already been scraped to GCS."""
        try:
            client = storage.Client()
            bucket = client.bucket(self.gcs_bucket)
            # Format: nba-com/player-boxscores/YYYY-MM-DD/
            date_formatted = game_date  # Already in YYYY-MM-DD format
            prefix = f"{self.gcs_base_path}/{date_formatted}/"
            blobs = list(bucket.list_blobs(prefix=prefix, max_results=1))
            return len(blobs) > 0
        except Exception as e:
            logger.debug(f"Error checking if date {game_date} exists: {e}")
            return False

    def scrape_date(self, game_date: str) -> bool:
        """Call the scraper service to scrape a date."""
        if self.dry_run:
            return True

        try:
            # Convert YYYY-MM-DD to YYYYMMDD for the scraper
            gamedate_formatted = game_date.replace('-', '')

            response = get_http_session().get(
                f"{self.service_url}/nbac_player_boxscore",
                params={
                    "gamedate": gamedate_formatted,
                },
                timeout=60
            )

            if response.status_code == 200:
                logger.info(f"  ✅ Scraped {game_date}")
                return True
            else:
                logger.warning(f"  ❌ Failed {game_date}: HTTP {response.status_code}")
                return False

        except requests.exceptions.Timeout:
            logger.warning(f"  ❌ Timeout scraping {game_date}")
            return False
        except Exception as e:
            logger.warning(f"  ❌ Error scraping {game_date}: {e}")
            return False

    def run(self, csv_path: str, limit: Optional[int] = None):
        """Run the backfill job."""
        logger.info(f"Loading game dates from {csv_path}")
        dates = self.load_game_dates(csv_path)

        if limit:
            dates = dates[:limit]

        total = len(dates)
        logger.info(f"Processing {total} game dates")

        if self.dry_run:
            logger.info("DRY RUN - No actual scraping will occur")
            logger.info(f"Sample dates to process:")
            for i, date in enumerate(dates[:20], 1):
                logger.info(f"  {i}. {date}")
            if total > 20:
                logger.info(f"  ... and {total - 20} more")
            return

        for i, game_date in enumerate(dates, 1):
            logger.info(f"[{i}/{total}] Processing {game_date}")

            # Check if already scraped
            if self.date_already_scraped(game_date):
                self.skipped_dates.append(game_date)
                logger.debug(f"  ⏭️ Skipping {game_date} (already exists)")
                continue

            # Scrape the date
            if self.scrape_date(game_date):
                self.processed_dates.append(game_date)
            else:
                self.failed_dates.append(game_date)

            # Rate limiting
            if i < total:
                time.sleep(self.rate_limit)

        # Summary
        logger.info("=" * 50)
        logger.info("BACKFILL COMPLETE")
        logger.info(f"  Processed: {len(self.processed_dates)}")
        logger.info(f"  Skipped (existing): {len(self.skipped_dates)}")
        logger.info(f"  Failed: {len(self.failed_dates)}")

        if self.failed_dates:
            logger.info(f"Failed dates: {self.failed_dates[:10]}")


def main():
    parser = argparse.ArgumentParser(description="Backfill NBA.com Player Boxscore data")
    parser.add_argument(
        "--csv",
        default=str(Path(__file__).parent / "game_dates_to_scrape.csv"),
        help="Path to CSV file with game dates (one per line)"
    )
    parser.add_argument(
        "--service-url",
        default="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app",
        help="URL of the scraper service"
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=1.0,
        help="Seconds between requests (default: 1.0)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually scrape, just show what would be done"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of dates to process"
    )
    parser.add_argument(
        "--start-date",
        help="Start from this date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--season",
        type=int,
        help="Filter to specific season (e.g., 2024 for 2024-25)"
    )

    args = parser.parse_args()

    backfill = NbacPlayerBoxscoreBackfill(
        service_url=args.service_url,
        rate_limit=args.rate_limit,
        dry_run=args.dry_run,
        start_date=args.start_date,
        season=args.season,
    )

    backfill.run(args.csv, limit=args.limit)


if __name__ == "__main__":
    main()

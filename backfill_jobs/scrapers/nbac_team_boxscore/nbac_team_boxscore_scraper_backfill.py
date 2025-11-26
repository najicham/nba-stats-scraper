#!/usr/bin/env python3
"""
NBA.com Team Boxscore Scraper Backfill Job
==========================================

Backfills team boxscore data from NBA.com for all historical games.
This script calls the scraper service to fetch data and save to GCS.

Usage:
  # Dry run (see what would be processed):
  python nbac_team_boxscore_scraper_backfill.py --dry-run --limit=10

  # Process all games:
  python nbac_team_boxscore_scraper_backfill.py --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app

  # Process specific season:
  python nbac_team_boxscore_scraper_backfill.py --season=2024

  # Resume from specific date:
  python nbac_team_boxscore_scraper_backfill.py --start-date=2024-01-01
"""

import csv
import logging
import os
import requests
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set
import argparse

from google.cloud import storage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NbacTeamBoxscoreScraperBackfill:
    """Backfill job for NBA.com team boxscore data."""

    def __init__(
        self,
        scraper_service_url: str,
        bucket_name: str = "nba-scraped-data",
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        season: Optional[int] = None
    ):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.bucket_name = bucket_name
        self.limit = limit
        self.start_date = start_date
        self.season = season

        # Initialize GCS client
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)

        # Job tracking
        self.total_games = 0
        self.processed_games = 0
        self.failed_games = []
        self.skipped_games = []

        # Rate limiting - NBA.com: be respectful, use 1s delay
        self.RATE_LIMIT_DELAY = 1.0

        # GCS path for team boxscores
        self.gcs_base_path = "nba-com/team-boxscore"

        logger.info("NBA.com Team Boxscore Scraper Backfill initialized")
        logger.info(f"  Scraper service: {self.scraper_service_url}")
        logger.info(f"  GCS bucket: {self.bucket_name}")
        logger.info(f"  Rate limit: {self.RATE_LIMIT_DELAY}s between calls")
        if self.limit:
            logger.info(f"  Limit: {self.limit} games")
        if self.start_date:
            logger.info(f"  Start date: {self.start_date}")
        if self.season:
            logger.info(f"  Season filter: {self.season}")

    def load_game_ids(self, csv_path: str) -> List[Dict]:
        """Load game IDs from CSV file."""
        games = []

        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                game_id = row['game_id']
                game_date = row['game_date']

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

                games.append({
                    'game_id': game_id,
                    'game_date': game_date
                })

        # Apply limit
        if self.limit:
            games = games[:self.limit]

        return games

    def game_already_scraped(self, game_id: str, game_date: str) -> bool:
        """Check if game data already exists in GCS."""
        try:
            # Format: nba-com/team-boxscore/YYYYMMDD/game_id/
            date_str = game_date.replace('-', '')
            prefix = f"{self.gcs_base_path}/{date_str}/{game_id}/"

            blobs = list(self.bucket.list_blobs(prefix=prefix, max_results=1))
            return len(blobs) > 0

        except Exception as e:
            logger.debug(f"Error checking if game {game_id} exists: {e}")
            return False

    def scrape_game(self, game_id: str, game_date: str) -> bool:
        """Scrape a single game via the scraper service."""
        try:
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": "nbac_team_boxscore",
                    "game_id": game_id,
                    "game_date": game_date,
                    "export_groups": "prod"
                },
                timeout=120
            )

            if response.status_code == 200:
                logger.info(f"  ✅ Scraped {game_id} ({game_date})")
                return True
            else:
                logger.warning(f"  ❌ Failed {game_id}: HTTP {response.status_code}")
                return False

        except requests.exceptions.Timeout:
            logger.warning(f"  ❌ Timeout scraping {game_id}")
            return False
        except Exception as e:
            logger.warning(f"  ❌ Error scraping {game_id}: {e}")
            return False

    def run(self, csv_path: str, dry_run: bool = False):
        """Execute the backfill job."""
        start_time = datetime.now()

        logger.info("=" * 70)
        logger.info("NBA.com Team Boxscore Scraper Backfill")
        if dry_run:
            logger.info("DRY RUN MODE - no scraping will be performed")
        logger.info("=" * 70)

        # Load games from CSV
        logger.info(f"Loading games from: {csv_path}")
        games = self.load_game_ids(csv_path)
        self.total_games = len(games)

        logger.info(f"Total games to process: {self.total_games}")

        if self.total_games == 0:
            logger.warning("No games found to process")
            return

        # Estimate time
        estimated_minutes = (self.total_games * self.RATE_LIMIT_DELAY) / 60
        logger.info(f"Estimated duration: {estimated_minutes:.1f} minutes")

        if dry_run:
            logger.info("\nDRY RUN - Would process these games:")
            for i, game in enumerate(games[:20], 1):
                logger.info(f"  {i}. {game['game_id']} ({game['game_date']})")
            if len(games) > 20:
                logger.info(f"  ... and {len(games) - 20} more games")
            return

        # Process games
        for i, game in enumerate(games, 1):
            game_id = game['game_id']
            game_date = game['game_date']

            # Progress logging
            if i % 50 == 0 or i == 1:
                elapsed = (datetime.now() - start_time).total_seconds()
                rate = i / elapsed if elapsed > 0 else 0
                remaining = self.total_games - i
                eta_minutes = (remaining / rate / 60) if rate > 0 else 0
                logger.info(f"Progress: {i}/{self.total_games} ({i/self.total_games*100:.1f}%), ETA: {eta_minutes:.1f} min")

            # Check if already scraped (resume logic)
            if self.game_already_scraped(game_id, game_date):
                self.skipped_games.append(game_id)
                logger.debug(f"  ⏭️ Skipping {game_id} (already exists)")
                continue

            # Scrape the game
            if self.scrape_game(game_id, game_date):
                self.processed_games += 1
            else:
                self.failed_games.append(game_id)

            # Rate limiting
            time.sleep(self.RATE_LIMIT_DELAY)

        # Final summary
        duration = datetime.now() - start_time
        logger.info("\n" + "=" * 70)
        logger.info("BACKFILL COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Total games: {self.total_games}")
        logger.info(f"Processed: {self.processed_games}")
        logger.info(f"Skipped (already exist): {len(self.skipped_games)}")
        logger.info(f"Failed: {len(self.failed_games)}")
        logger.info(f"Duration: {duration}")

        if self.failed_games:
            logger.warning(f"Failed games (first 20): {self.failed_games[:20]}")


def main():
    parser = argparse.ArgumentParser(description="NBA.com Team Boxscore Scraper Backfill")
    parser.add_argument(
        "--service-url",
        help="Cloud Run scraper service URL (or set SCRAPER_SERVICE_URL env var)"
    )
    parser.add_argument(
        "--csv",
        default=str(Path(__file__).parent / "game_ids_to_scrape.csv"),
        help="Path to CSV file with game_id,game_date columns"
    )
    parser.add_argument(
        "--bucket",
        default="nba-scraped-data",
        help="GCS bucket name"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without scraping"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of games to process (for testing)"
    )
    parser.add_argument(
        "--start-date",
        help="Skip games before this date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--season",
        type=int,
        help="Only process games from this season (e.g., 2024 for 2024-25)"
    )

    args = parser.parse_args()

    # Get service URL
    service_url = args.service_url or os.environ.get('SCRAPER_SERVICE_URL')
    if not service_url and not args.dry_run:
        logger.error("ERROR: --service-url required or set SCRAPER_SERVICE_URL env var")
        sys.exit(1)

    # Use placeholder for dry run
    if args.dry_run and not service_url:
        service_url = "https://placeholder-for-dry-run"

    # Create and run job
    job = NbacTeamBoxscoreScraperBackfill(
        scraper_service_url=service_url,
        bucket_name=args.bucket,
        limit=args.limit,
        start_date=args.start_date,
        season=args.season
    )

    job.run(csv_path=args.csv, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

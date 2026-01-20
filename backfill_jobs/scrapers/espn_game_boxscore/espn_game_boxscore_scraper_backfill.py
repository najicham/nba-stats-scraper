#!/usr/bin/env python3
"""
ESPN Game Boxscore Scraper Backfill Job
=======================================
Backfills boxscore data from ESPN for all historical games.
This script calls the scraper service to fetch data and save to GCS.

Note: ESPN uses different game IDs than NBA.com. This script uses NBA.com
game_ids and relies on the scraper to resolve them to ESPN game IDs.

Usage:
  # Dry run (see what would be processed):
  python espn_game_boxscore_scraper_backfill.py --dry-run --limit=20

  # Full backfill with service URL:
  python espn_game_boxscore_scraper_backfill.py \
    --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app

  # Backfill specific season (2024 = 2024-25 season):
  python espn_game_boxscore_scraper_backfill.py \
    --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app \
    --season=2024

  # Backfill from specific date:
  python espn_game_boxscore_scraper_backfill.py \
    --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app \
    --start-date=2024-01-01
"""

import argparse
import csv
import logging
import time
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


class EspnBoxscoreBackfill:
    """Backfill boxscore data from ESPN."""

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
        self.gcs_base_path = "espn/boxscores"

        # Stats
        self.processed_games = []
        self.skipped_games = []
        self.failed_games = []

        logger.info("ESPN Game Boxscore Scraper Backfill initialized")
        logger.info(f"  Scraper service: {self.service_url}")
        logger.info(f"  Rate limit: {self.rate_limit}s between requests")
        logger.info(f"  Dry run: {self.dry_run}")
        if self.start_date:
            logger.info(f"  Start date: {self.start_date}")
        if self.season:
            logger.info(f"  Season filter: {self.season}-{self.season+1}")

    def load_game_ids(self, csv_path: str) -> List[Dict]:
        """Load game IDs and dates from CSV file."""
        games = []
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                game_id = row['game_id']
                game_date = row['game_date']

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

                games.append({
                    'game_id': game_id,
                    'game_date': game_date
                })

        return games

    def game_already_scraped(self, game_id: str, game_date: str) -> bool:
        """Check if a game has already been scraped to GCS."""
        try:
            client = storage.Client()
            bucket = client.bucket(self.gcs_bucket)
            # Format: espn/boxscores/{date}/
            # Note: ESPN uses different game IDs, so we check by date prefix
            prefix = f"{self.gcs_base_path}/{game_date}/"
            blobs = list(bucket.list_blobs(prefix=prefix, max_results=1))
            # This is a simplistic check - a date folder existing doesn't mean
            # this specific game was scraped. Consider improving if needed.
            return len(blobs) > 0
        except Exception as e:
            logger.debug(f"Error checking if game {game_id} exists: {e}")
            return False

    def scrape_game(self, game_id: str, game_date: str) -> bool:
        """Call the scraper service to scrape a game."""
        if self.dry_run:
            return True

        try:
            # Note: ESPN scraper uses game_id parameter
            # The scraper may need to resolve NBA.com game_id to ESPN game_id
            response = get_http_session().get(
                f"{self.service_url}/espn_game_boxscore",
                params={
                    "game_id": game_id,  # NBA.com game_id
                    "gamedate": game_date.replace('-', ''),
                },
                timeout=120  # ESPN scraping can be slow
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

    def run(self, csv_path: str, limit: Optional[int] = None):
        """Run the backfill job."""
        logger.info(f"Loading game IDs from {csv_path}")
        games = self.load_game_ids(csv_path)

        if limit:
            games = games[:limit]

        total = len(games)
        logger.info(f"Processing {total} games")

        if self.dry_run:
            logger.info("DRY RUN - No actual scraping will occur")
            logger.info(f"Sample games to process:")
            for i, game in enumerate(games[:20], 1):
                logger.info(f"  {i}. {game['game_id']} ({game['game_date']})")
            if total > 20:
                logger.info(f"  ... and {total - 20} more")
            return

        for i, game in enumerate(games, 1):
            game_id = game['game_id']
            game_date = game['game_date']

            logger.info(f"[{i}/{total}] Processing {game_id} ({game_date})")

            # Check if already scraped (simplified check)
            # if self.game_already_scraped(game_id, game_date):
            #     self.skipped_games.append(game_id)
            #     logger.debug(f"  ⏭️ Skipping {game_id} (already exists)")
            #     continue

            # Scrape the game
            if self.scrape_game(game_id, game_date):
                self.processed_games.append(game_id)
            else:
                self.failed_games.append(game_id)

            # Rate limiting
            if i < total:
                time.sleep(self.rate_limit)

        # Summary
        logger.info("=" * 50)
        logger.info("BACKFILL COMPLETE")
        logger.info(f"  Processed: {len(self.processed_games)}")
        logger.info(f"  Skipped (existing): {len(self.skipped_games)}")
        logger.info(f"  Failed: {len(self.failed_games)}")

        if self.failed_games:
            logger.info(f"Failed games: {self.failed_games[:10]}")


def main():
    parser = argparse.ArgumentParser(description="Backfill ESPN Game Boxscore data")
    parser.add_argument(
        "--csv",
        default=str(Path(__file__).parent / "game_ids_to_scrape.csv"),
        help="Path to CSV file with game_id,game_date columns"
    )
    parser.add_argument(
        "--service-url",
        default="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app",
        help="URL of the scraper service"
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=1.5,  # ESPN may need more time between requests
        help="Seconds between requests (default: 1.5)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually scrape, just show what would be done"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of games to process"
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

    backfill = EspnBoxscoreBackfill(
        service_url=args.service_url,
        rate_limit=args.rate_limit,
        dry_run=args.dry_run,
        start_date=args.start_date,
        season=args.season,
    )

    backfill.run(args.csv, limit=args.limit)


if __name__ == "__main__":
    main()

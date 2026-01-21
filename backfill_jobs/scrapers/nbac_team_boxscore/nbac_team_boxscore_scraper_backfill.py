#!/usr/bin/env python3
"""
NBA.com Team Boxscore Scraper Backfill Job
==========================================

Backfills team boxscore data from NBA.com for all historical games.
This script calls the scraper service to fetch data and save to GCS.

Usage:
  # Dry run (see what would be processed):
  python nbac_team_boxscore_scraper_backfill.py --dry-run --limit=10

  # Process all games with 15 concurrent workers:
  python nbac_team_boxscore_scraper_backfill.py \
    --service-url=https://nba-phase1-scrapers-756957797294.us-west2.run.app \
    --workers=15

  # Process specific season:
  python nbac_team_boxscore_scraper_backfill.py --season=2024 --workers=15

  # Resume from specific date:
  python nbac_team_boxscore_scraper_backfill.py --start-date=2024-01-01
"""

import csv
import json
import logging
import os
import requests
from shared.clients.http_pool import get_http_session
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
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
        season: Optional[int] = None,
        workers: int = 1,
        timeout: int = 300
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
        self.total_games = 0
        self.processed_count = 0
        self.skipped_count = 0
        self.failed_games = []
        self.success_games = []

        # Output directory for logs
        self.output_dir = Path(__file__).parent
        self.failed_games_file = self.output_dir / f"failed_games_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        # GCS path for team boxscores
        self.gcs_base_path = "nba-com/team-boxscore"

        logger.info("NBA.com Team Boxscore Scraper Backfill initialized")
        logger.info(f"  Scraper service: {self.scraper_service_url}")
        logger.info(f"  GCS bucket: {self.bucket_name}")
        logger.info(f"  Workers: {self.workers}")
        logger.info(f"  Timeout: {self.timeout}s")
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

    def scrape_game(self, game: Dict) -> Dict:
        """Scrape a single game via the scraper service. Returns result dict."""
        game_id = game['game_id']
        game_date = game['game_date']

        result = {
            'game_id': game_id,
            'game_date': game_date,
            'status': 'unknown',
            'error': None
        }

        try:
            response = get_http_session().post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": "nbac_team_boxscore",
                    "game_id": game_id,
                    "game_date": game_date,
                    "export_groups": "prod"
                },
                timeout=self.timeout
            )

            if response.status_code == 200:
                result['status'] = 'success'
                logger.info(f"  ✅ Scraped {game_id} ({game_date})")
            else:
                result['status'] = 'failed'
                result['error'] = f"HTTP {response.status_code}"
                logger.warning(f"  ❌ Failed {game_id}: HTTP {response.status_code}")

        except requests.exceptions.Timeout:
            result['status'] = 'timeout'
            result['error'] = f"Timeout after {self.timeout}s"
            logger.warning(f"  ⏱️ Timeout {game_id} (may still succeed server-side)")
        except Exception as e:
            result['status'] = 'error'
            result['error'] = str(e)
            logger.warning(f"  ❌ Error {game_id}: {e}")

        return result

    def process_game(self, game: Dict, progress_info: Dict) -> Dict:
        """Process a single game with skip check."""
        game_id = game['game_id']
        game_date = game['game_date']

        # Check if already scraped (resume logic)
        if self.game_already_scraped(game_id, game_date):
            with self._lock:
                self.skipped_count += 1
            return {'game_id': game_id, 'game_date': game_date, 'status': 'skipped'}

        # Scrape the game
        result = self.scrape_game(game)

        # Update counters
        with self._lock:
            if result['status'] == 'success':
                self.processed_count += 1
                self.success_games.append(game_id)
            else:
                self.failed_games.append(result)

            # Progress logging every 50 games
            total_done = self.processed_count + self.skipped_count + len(self.failed_games)
            if total_done % 50 == 0:
                elapsed = (datetime.now() - progress_info['start_time']).total_seconds()
                rate = total_done / elapsed if elapsed > 0 else 0
                remaining = self.total_games - total_done
                eta_minutes = (remaining / rate / 60) if rate > 0 else 0
                logger.info(
                    f"📊 Progress: {total_done}/{self.total_games} "
                    f"({total_done/self.total_games*100:.1f}%) | "
                    f"✅ {self.processed_count} | ⏭️ {self.skipped_count} | "
                    f"❌ {len(self.failed_games)} | ETA: {eta_minutes:.0f}min"
                )

        return result

    def save_failed_games(self):
        """Save failed games to JSON file for retry."""
        if self.failed_games:
            with open(self.failed_games_file, 'w') as f:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'total_failed': len(self.failed_games),
                    'failed_games': self.failed_games
                }, f, indent=2)
            logger.info(f"💾 Failed games saved to: {self.failed_games_file}")

    def run(self, csv_path: str, dry_run: bool = False):
        """Execute the backfill job."""
        start_time = datetime.now()

        logger.info("=" * 70)
        logger.info("NBA.com Team Boxscore Scraper Backfill")
        logger.info(f"Workers: {self.workers} | Timeout: {self.timeout}s")
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

        # Estimate time (assuming ~55s per game with proxy)
        estimated_hours = (self.total_games * 55) / self.workers / 3600
        logger.info(f"Estimated duration: {estimated_hours:.1f} hours (with {self.workers} workers)")

        if dry_run:
            logger.info("\nDRY RUN - Would process these games:")
            for i, game in enumerate(games[:20], 1):
                logger.info(f"  {i}. {game['game_id']} ({game['game_date']})")
            if len(games) > 20:
                logger.info(f"  ... and {len(games) - 20} more games")
            return

        # Process games with thread pool
        progress_info = {'start_time': start_time}

        logger.info(f"🚀 Starting backfill with {self.workers} concurrent workers...")

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self.process_game, game, progress_info): game
                for game in games
            }

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    game = futures[future]
                    logger.error(f"Unexpected error processing {game['game_id']}: {e}")

        # Save failed games to file
        self.save_failed_games()

        # Final summary
        duration = datetime.now() - start_time
        hours, remainder = divmod(duration.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)

        logger.info("\n" + "=" * 70)
        logger.info("🏁 BACKFILL COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Total games:    {self.total_games}")
        logger.info(f"✅ Processed:   {self.processed_count}")
        logger.info(f"⏭️ Skipped:     {self.skipped_count}")
        logger.info(f"❌ Failed:      {len(self.failed_games)}")
        logger.info(f"⏱️ Duration:    {int(hours)}h {int(minutes)}m {int(seconds)}s")

        if self.failed_games:
            logger.info(f"\n📁 Failed games saved to: {self.failed_games_file}")
            logger.info("   Re-run the script to retry failed games (resume logic will skip successes)")

            # Show summary of failure types
            failure_types = {}
            for f in self.failed_games:
                status = f.get('status', 'unknown')
                failure_types[status] = failure_types.get(status, 0) + 1
            logger.info(f"   Failure breakdown: {failure_types}")


def main():
    parser = argparse.ArgumentParser(description="NBA.com Team Boxscore Scraper Backfill")
    parser.add_argument(
        "--service-url",
        default="https://nba-phase1-scrapers-756957797294.us-west2.run.app",
        help="Cloud Run scraper service URL"
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
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of concurrent workers (default: 1, recommended: 15)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Request timeout in seconds (default: 300)"
    )

    args = parser.parse_args()

    # Create and run job
    job = NbacTeamBoxscoreScraperBackfill(
        scraper_service_url=args.service_url,
        bucket_name=args.bucket,
        limit=args.limit,
        start_date=args.start_date,
        season=args.season,
        workers=args.workers,
        timeout=args.timeout
    )

    job.run(csv_path=args.csv, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

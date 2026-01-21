#!/usr/bin/env python3
"""
Ball Don't Lie Standings Scraper Backfill Job
=============================================
Backfills standings data from Ball Don't Lie API for historical seasons.
This script calls the scraper service to fetch data and save to GCS.

Usage:
  # Dry run (see what would be processed):
  python bdl_standings_scraper_backfill.py --dry-run

  # Full backfill with service URL:
  python bdl_standings_scraper_backfill.py \
    --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app

  # Backfill specific season:
  python bdl_standings_scraper_backfill.py \
    --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app \
    --season=2023
"""

import argparse
import logging
import time
from typing import List, Optional

import requests
from shared.clients.http_pool import get_http_session
from google.cloud import storage

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BdlStandingsBackfill:
    """Backfill standings data from Ball Don't Lie API."""

    # Seasons to backfill (currently missing: 2021, 2022, 2023)
    MISSING_SEASONS = [2021, 2022, 2023]

    def __init__(
        self,
        service_url: str = "https://placeholder",
        rate_limit: float = 2.0,
        dry_run: bool = False,
        season: Optional[int] = None,
    ):
        self.service_url = service_url.rstrip('/')
        self.rate_limit = rate_limit
        self.dry_run = dry_run
        self.season = season

        # GCS paths
        self.gcs_bucket = "nba-scraped-data"
        self.gcs_base_path = "ball-dont-lie/standings"

        # Stats
        self.processed_seasons = []
        self.skipped_seasons = []
        self.failed_seasons = []

        logger.info("Ball Don't Lie Standings Scraper Backfill initialized")
        logger.info(f"  Scraper service: {self.service_url}")
        logger.info(f"  Rate limit: {self.rate_limit}s between requests")
        logger.info(f"  Dry run: {self.dry_run}")
        if self.season:
            logger.info(f"  Season filter: {self.season}")

    def get_seasons_to_backfill(self) -> List[int]:
        """Get list of seasons to backfill."""
        if self.season:
            return [self.season]
        return self.MISSING_SEASONS

    def season_already_scraped(self, season: int) -> bool:
        """Check if a season has already been scraped to GCS."""
        try:
            client = storage.Client()
            bucket = client.bucket(self.gcs_bucket)
            # Format: ball-dont-lie/standings/{season}-{season+1}/
            season_str = f"{season}-{str(season + 1)[-2:]}"
            prefix = f"{self.gcs_base_path}/{season_str}/"
            blobs = list(bucket.list_blobs(prefix=prefix, max_results=1))
            return len(blobs) > 0
        except Exception as e:
            logger.debug(f"Error checking if season {season} exists: {e}")
            return False

    def scrape_season(self, season: int) -> bool:
        """Call the scraper service to scrape a season."""
        if self.dry_run:
            return True

        try:
            response = get_http_session().get(
                f"{self.service_url}/bdl_standings",
                params={
                    "season": season,
                },
                timeout=60
            )

            if response.status_code == 200:
                logger.info(f"  ✅ Scraped season {season}")
                return True
            else:
                logger.warning(f"  ❌ Failed season {season}: HTTP {response.status_code}")
                return False

        except requests.exceptions.Timeout:
            logger.warning(f"  ❌ Timeout scraping season {season}")
            return False
        except Exception as e:
            logger.warning(f"  ❌ Error scraping season {season}: {e}")
            return False

    def run(self):
        """Run the backfill job."""
        seasons = self.get_seasons_to_backfill()

        total = len(seasons)
        logger.info(f"Processing {total} seasons: {seasons}")

        if self.dry_run:
            logger.info("DRY RUN - No actual scraping will occur")
            logger.info(f"Seasons to process:")
            for season in seasons:
                logger.info(f"  - {season}-{str(season + 1)[-2:]}")
            return

        for i, season in enumerate(seasons, 1):
            logger.info(f"[{i}/{total}] Processing season {season}-{str(season + 1)[-2:]}")

            # Check if already scraped
            if self.season_already_scraped(season):
                self.skipped_seasons.append(season)
                logger.info(f"  ⏭️ Skipping season {season} (already exists)")
                continue

            # Scrape the season
            if self.scrape_season(season):
                self.processed_seasons.append(season)
            else:
                self.failed_seasons.append(season)

            # Rate limiting
            if i < total:
                time.sleep(self.rate_limit)

        # Summary
        logger.info("=" * 50)
        logger.info("BACKFILL COMPLETE")
        logger.info(f"  Processed: {len(self.processed_seasons)}")
        logger.info(f"  Skipped (existing): {len(self.skipped_seasons)}")
        logger.info(f"  Failed: {len(self.failed_seasons)}")

        if self.failed_seasons:
            logger.info(f"Failed seasons: {self.failed_seasons}")


def main():
    parser = argparse.ArgumentParser(description="Backfill Ball Don't Lie Standings data")
    parser.add_argument(
        "--service-url",
        default="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app",
        help="URL of the scraper service"
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=2.0,
        help="Seconds between requests (default: 2.0)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually scrape, just show what would be done"
    )
    parser.add_argument(
        "--season",
        type=int,
        help="Backfill specific season only (e.g., 2023 for 2023-24)"
    )

    args = parser.parse_args()

    backfill = BdlStandingsBackfill(
        service_url=args.service_url,
        rate_limit=args.rate_limit,
        dry_run=args.dry_run,
        season=args.season,
    )

    backfill.run()


if __name__ == "__main__":
    main()

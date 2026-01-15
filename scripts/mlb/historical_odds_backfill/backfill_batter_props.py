#!/usr/bin/env python3
"""
MLB Historical Batter Props Backfill

Scrapes historical batter prop betting lines from The Odds API.
Uses the same event IDs from pitcher props backfill.

Markets collected:
- batter_strikeouts (CRITICAL for bottom-up K model)
- batter_hits
- batter_walks
- batter_total_bases
- batter_home_runs
- batter_rbis

Usage:
    # Full backfill with resume
    python scripts/mlb/historical_odds_backfill/backfill_batter_props.py --resume

    # Specific date range
    python scripts/mlb/historical_odds_backfill/backfill_batter_props.py \
        --start-date 2024-06-01 --end-date 2024-06-30

    # Dry-run
    python scripts/mlb/historical_odds_backfill/backfill_batter_props.py --dry-run

GCS Output: gs://nba-scraped-data/mlb-odds-api/batter-props-history/{date}/{event_id}-{teams}/...
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from google.cloud import bigquery, storage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
BUCKET_NAME = 'nba-scraped-data'
GCS_PREFIX = 'mlb-odds-api/batter-props-history'
PITCHER_GCS_PREFIX = 'mlb-odds-api/pitcher-props-history'
SNAPSHOT_TIME = "18:00:00Z"
RATE_LIMIT_DELAY = 0.2


class MLBBatterPropsBackfill:
    """Backfills historical batter prop lines from Odds API."""

    def __init__(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        resume: bool = True,
        dry_run: bool = False,
        delay: float = RATE_LIMIT_DELAY,
    ):
        self.start_date = start_date or '2024-04-09'
        self.end_date = end_date or '2025-09-28'
        self.resume = resume
        self.dry_run = dry_run
        self.delay = delay

        self.storage_client = storage.Client(project=PROJECT_ID)
        self.bucket = self.storage_client.bucket(BUCKET_NAME)

        self.stats = {
            'dates_processed': 0,
            'events_found': 0,
            'events_scraped': 0,
            'events_skipped': 0,
            'events_failed': 0,
            'api_calls': 0,
            'start_time': None,
        }

        self.existing_events: Set[str] = set()

    def get_dates_from_pitcher_gcs(self) -> List[str]:
        """Get dates that have pitcher props (we'll scrape batter props for same events)."""
        logger.info("Scanning pitcher props GCS for available dates...")
        dates = set()

        for blob in self.bucket.list_blobs(prefix=f"{PITCHER_GCS_PREFIX}/"):
            parts = blob.name.split('/')
            if len(parts) >= 3:
                date_str = parts[2]
                if len(date_str) == 10 and date_str[4] == '-':
                    if date_str >= self.start_date and date_str <= self.end_date:
                        dates.add(date_str)

        sorted_dates = sorted(dates)
        logger.info(f"Found {len(sorted_dates)} dates with pitcher props")
        return sorted_dates

    def get_events_for_date(self, game_date: str) -> List[Dict]:
        """Get event IDs from pitcher props GCS for a date."""
        events = []
        prefix = f"{PITCHER_GCS_PREFIX}/{game_date}/"

        seen_events = set()
        for blob in self.bucket.list_blobs(prefix=prefix):
            parts = blob.name.split('/')
            if len(parts) >= 4:
                event_folder = parts[3]  # e.g., "abc123-BOSNYYY"
                if '-' in event_folder:
                    event_id = event_folder.split('-')[0]
                    teams = event_folder.split('-')[1] if len(event_folder.split('-')) > 1 else ''

                    if event_id not in seen_events:
                        seen_events.add(event_id)
                        events.append({
                            'id': event_id,
                            'teams': teams,
                        })

        return events

    def scan_existing_batter_events(self, dates: List[str]) -> None:
        """Scan GCS for existing batter prop files."""
        if not self.resume:
            return

        logger.info("Scanning for existing batter prop files...")
        for blob in self.bucket.list_blobs(prefix=f"{GCS_PREFIX}/"):
            parts = blob.name.split('/')
            if len(parts) >= 4:
                date_str = parts[2]
                event_folder = parts[3]
                event_id = event_folder.split('-')[0] if '-' in event_folder else event_folder
                self.existing_events.add(f"{date_str}:{event_id}")

        logger.info(f"Found {len(self.existing_events)} existing batter prop events")

    def scrape_batter_props(self, event_id: str, game_date: str, teams: str) -> Dict:
        """Scrape batter props for an event."""
        snapshot_timestamp = f"{game_date}T{SNAPSHOT_TIME}"

        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scrapers/mlb/oddsapi/mlb_batter_props_his.py"),
            "--event_id", event_id,
            "--game_date", game_date,
            "--snapshot_timestamp", snapshot_timestamp,
            "--group", "gcs"
        ]

        env = os.environ.copy()
        env["SPORT"] = "mlb"

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180,
                env=env
            )
            self.stats['api_calls'] += 1

            if result.returncode != 0:
                if "404" in result.stderr or "not found" in result.stderr.lower():
                    return {'status': 'not_found', 'event_id': event_id}
                return {'status': 'error', 'event_id': event_id, 'error': result.stderr[:100]}

            return {'status': 'success', 'event_id': event_id}

        except subprocess.TimeoutExpired:
            return {'status': 'timeout', 'event_id': event_id}
        except Exception as e:
            return {'status': 'exception', 'event_id': event_id, 'error': str(e)}

    def process_date(self, game_date: str, date_idx: int, total_dates: int) -> None:
        """Process all events for a date."""
        events = self.get_events_for_date(game_date)
        self.stats['events_found'] += len(events)

        if not events:
            logger.info(f"[{date_idx}/{total_dates}] {game_date}: No events found")
            return

        # Filter to events we need to scrape
        events_to_scrape = []
        for event in events:
            key = f"{game_date}:{event['id']}"
            if key in self.existing_events:
                self.stats['events_skipped'] += 1
            else:
                events_to_scrape.append(event)

        if not events_to_scrape:
            logger.info(f"[{date_idx}/{total_dates}] {game_date}: {len(events)} events (all exist)")
            return

        if self.dry_run:
            logger.info(f"[{date_idx}/{total_dates}] {game_date}: Would scrape {len(events_to_scrape)} batter props")
            return

        logger.info(f"[{date_idx}/{total_dates}] {game_date}: Scraping {len(events_to_scrape)} events...")

        for event in events_to_scrape:
            result = self.scrape_batter_props(event['id'], game_date, event.get('teams', ''))

            if result['status'] == 'success':
                self.stats['events_scraped'] += 1
            else:
                self.stats['events_failed'] += 1

            time.sleep(self.delay)

        self.stats['dates_processed'] += 1

    def run(self) -> Dict:
        """Execute the backfill."""
        self.stats['start_time'] = time.time()

        logger.info("=" * 70)
        logger.info("MLB HISTORICAL BATTER PROPS BACKFILL")
        logger.info("=" * 70)
        logger.info(f"Date range: {self.start_date} to {self.end_date}")
        logger.info(f"Resume: {self.resume}")
        logger.info(f"Delay: {self.delay}s")
        logger.info("")

        # Get dates from pitcher props
        dates = self.get_dates_from_pitcher_gcs()

        if not dates:
            logger.warning("No dates found!")
            return self.stats

        # Scan existing
        self.scan_existing_batter_events(dates)

        logger.info(f"\nDates to process: {len(dates)}")

        # Process each date
        for i, game_date in enumerate(dates, 1):
            self.process_date(game_date, i, len(dates))

            if i % 10 == 0:
                elapsed = time.time() - self.stats['start_time']
                rate = self.stats['dates_processed'] / (elapsed / 60) if elapsed > 0 else 0
                logger.info(f"  Progress: {self.stats['dates_processed']} dates, "
                           f"{self.stats['events_scraped']} events, {rate:.1f} dates/min")

        # Summary
        elapsed = time.time() - self.stats['start_time']

        logger.info("\n" + "=" * 70)
        logger.info("BATTER PROPS BACKFILL COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Time: {elapsed/60:.1f} minutes")
        logger.info(f"Dates processed: {self.stats['dates_processed']}")
        logger.info(f"Events scraped: {self.stats['events_scraped']}")
        logger.info(f"Events skipped: {self.stats['events_skipped']}")
        logger.info(f"Events failed: {self.stats['events_failed']}")
        logger.info(f"API calls: {self.stats['api_calls']}")

        return self.stats


def main():
    parser = argparse.ArgumentParser(description='Backfill MLB batter props')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--resume', action='store_true', default=True)
    parser.add_argument('--no-resume', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--delay', type=float, default=RATE_LIMIT_DELAY)

    args = parser.parse_args()

    backfill = MLBBatterPropsBackfill(
        start_date=args.start_date,
        end_date=args.end_date,
        resume=not args.no_resume,
        dry_run=args.dry_run,
        delay=args.delay,
    )

    try:
        backfill.run()
    except KeyboardInterrupt:
        logger.info("\nInterrupted")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

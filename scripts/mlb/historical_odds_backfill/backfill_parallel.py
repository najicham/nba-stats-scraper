#!/usr/bin/env python3
"""
MLB Historical Betting Lines - PARALLEL Backfill

Parallelized version for users with high Odds API rate limits.
Processes multiple events concurrently for much faster backfill.

Usage:
    # Run with 5 parallel workers (default)
    python scripts/mlb/historical_odds_backfill/backfill_parallel.py

    # Run with 10 parallel workers (for higher rate limits)
    python scripts/mlb/historical_odds_backfill/backfill_parallel.py --workers 10

    # Process specific date range
    python scripts/mlb/historical_odds_backfill/backfill_parallel.py \
        --start-date 2024-09-19 --end-date 2025-09-28 --workers 8

    # Dry-run to see what would be processed
    python scripts/mlb/historical_odds_backfill/backfill_parallel.py --dry-run

Performance:
    - Sequential (old): ~8 dates/hour (1 sec delay between calls)
    - Parallel (5 workers): ~40 dates/hour
    - Parallel (10 workers): ~80 dates/hour
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from google.cloud import bigquery, storage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = 'nba-props-platform'
BUCKET_NAME = 'nba-scraped-data'
GCS_PREFIX = 'mlb-odds-api/pitcher-props-history'
SNAPSHOT_TIME = "18:00:00Z"


class ParallelBackfill:
    """Parallel backfill of historical betting lines."""

    def __init__(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        workers: int = 5,
        delay: float = 0.1,  # Minimal delay for paid API
        dry_run: bool = False,
    ):
        self.start_date = start_date or '2024-04-09'
        self.end_date = end_date or '2025-09-28'
        self.workers = workers
        self.delay = delay
        self.dry_run = dry_run

        self.bq_client = bigquery.Client(project=PROJECT_ID)
        self.storage_client = storage.Client(project=PROJECT_ID)
        self.bucket = self.storage_client.bucket(BUCKET_NAME)

        self.existing_events: Set[str] = set()
        self.stats = {
            'dates_total': 0,
            'dates_processed': 0,
            'events_scraped': 0,
            'events_skipped': 0,
            'events_failed': 0,
            'api_calls': 0,
            'start_time': None,
        }

    def get_prediction_dates(self) -> List[str]:
        """Get dates with predictions."""
        query = f"""
        SELECT DISTINCT game_date
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
        ORDER BY game_date
        """
        results = self.bq_client.query(query).result()
        return [row.game_date.strftime('%Y-%m-%d') for row in results]

    def get_dates_already_in_gcs(self) -> Set[str]:
        """Get dates that already have data in GCS."""
        dates = set()
        for blob in self.bucket.list_blobs(prefix=f"{GCS_PREFIX}/"):
            parts = blob.name.split('/')
            if len(parts) >= 3:
                date_str = parts[2]
                if len(date_str) == 10 and date_str[4] == '-':
                    dates.add(date_str)
        return dates

    def scan_existing_events(self, dates: List[str]) -> None:
        """Scan GCS for existing event files."""
        logger.info("Scanning GCS for existing events...")
        for date in dates:
            prefix = f"{GCS_PREFIX}/{date}/"
            for blob in self.bucket.list_blobs(prefix=prefix, max_results=500):
                parts = blob.name.split('/')
                if len(parts) >= 4:
                    event_dir = parts[3]
                    event_id = event_dir.split('-')[0] if '-' in event_dir else event_dir
                    self.existing_events.add(f"{date}:{event_id}")
        logger.info(f"Found {len(self.existing_events)} existing events")

    def scrape_events_for_date(self, game_date: str) -> List[Dict]:
        """Get list of events for a date."""
        snapshot_timestamp = f"{game_date}T{SNAPSHOT_TIME}"
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scrapers/mlb/oddsapi/mlb_events_his.py"),
            "--game_date", game_date,
            "--snapshot_timestamp", snapshot_timestamp,
            "--group", "dev"
        ]
        env = os.environ.copy()
        env["SPORT"] = "mlb"

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
            self.stats['api_calls'] += 1

            output_file = f"/tmp/mlb_events_his_{game_date}.json"
            if os.path.exists(output_file):
                with open(output_file) as f:
                    data = json.load(f)
                return data.get('events', [])
        except Exception as e:
            logger.warning(f"Failed to get events for {game_date}: {e}")
        return []

    def scrape_single_event(self, event_id: str, game_date: str, teams: str) -> Dict:
        """Scrape props for a single event."""
        # Check if exists
        if f"{game_date}:{event_id}" in self.existing_events:
            return {'status': 'skipped', 'event_id': event_id}

        snapshot_timestamp = f"{game_date}T{SNAPSHOT_TIME}"
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scrapers/mlb/oddsapi/mlb_pitcher_props_his.py"),
            "--event_id", event_id,
            "--game_date", game_date,
            "--snapshot_timestamp", snapshot_timestamp,
            "--group", "gcs"
        ]
        env = os.environ.copy()
        env["SPORT"] = "mlb"

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
            self.stats['api_calls'] += 1
            time.sleep(self.delay)  # Small delay between calls

            if result.returncode == 0:
                return {'status': 'success', 'event_id': event_id, 'teams': teams}
            else:
                return {'status': 'failed', 'event_id': event_id, 'error': result.stderr[:100]}
        except Exception as e:
            return {'status': 'error', 'event_id': event_id, 'error': str(e)}

    def process_date_parallel(self, game_date: str, date_idx: int, total: int) -> Tuple[int, int, int]:
        """Process all events for a date using parallel workers."""
        events = self.scrape_events_for_date(game_date)
        if not events:
            return 0, 0, 0

        # Filter to events we need to scrape
        events_to_scrape = []
        skipped = 0
        for event in events:
            event_id = event['id']
            if f"{game_date}:{event_id}" in self.existing_events:
                skipped += 1
            else:
                teams = f"{event.get('away_team', '?')} @ {event.get('home_team', '?')}"
                events_to_scrape.append((event_id, game_date, teams))

        if not events_to_scrape:
            logger.info(f"[{date_idx}/{total}] {game_date}: {len(events)} events (all exist, skipped)")
            return 0, skipped, 0

        if self.dry_run:
            logger.info(f"[{date_idx}/{total}] {game_date}: Would scrape {len(events_to_scrape)}, skip {skipped}")
            return 0, skipped, 0

        # Scrape in parallel
        scraped = 0
        failed = 0

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self.scrape_single_event, eid, gd, teams): (eid, teams)
                for eid, gd, teams in events_to_scrape
            }

            for future in as_completed(futures):
                result = future.result()
                if result['status'] == 'success':
                    scraped += 1
                elif result['status'] == 'skipped':
                    skipped += 1
                else:
                    failed += 1

        logger.info(f"[{date_idx}/{total}] {game_date}: {scraped} scraped, {skipped} skipped, {failed} failed")
        return scraped, skipped, failed

    def run(self) -> Dict:
        """Execute parallel backfill."""
        self.stats['start_time'] = time.time()

        logger.info("=" * 70)
        logger.info("MLB HISTORICAL BACKFILL - PARALLEL MODE")
        logger.info("=" * 70)
        logger.info(f"Workers: {self.workers}")
        logger.info(f"Date range: {self.start_date} to {self.end_date}")
        logger.info(f"Delay between calls: {self.delay}s")
        logger.info("")

        # Get dates to process
        all_dates = self.get_prediction_dates()
        existing_dates = self.get_dates_already_in_gcs()

        # Filter to dates not fully processed
        # For simplicity, we'll process all dates but skip existing events
        dates_to_process = [d for d in all_dates if d >= self.start_date and d <= self.end_date]

        logger.info(f"Total prediction dates: {len(all_dates)}")
        logger.info(f"Dates in range: {len(dates_to_process)}")
        logger.info(f"Dates already in GCS: {len(existing_dates)}")

        if not dates_to_process:
            logger.info("No dates to process!")
            return self.stats

        # Scan existing events for resume capability
        self.scan_existing_events(dates_to_process)

        self.stats['dates_total'] = len(dates_to_process)

        # Process each date
        for i, game_date in enumerate(dates_to_process, 1):
            scraped, skipped, failed = self.process_date_parallel(game_date, i, len(dates_to_process))

            self.stats['events_scraped'] += scraped
            self.stats['events_skipped'] += skipped
            self.stats['events_failed'] += failed
            self.stats['dates_processed'] += 1

            # Progress every 10 dates
            if i % 10 == 0:
                elapsed = time.time() - self.stats['start_time']
                rate = self.stats['dates_processed'] / (elapsed / 60)
                logger.info(f"  Progress: {self.stats['dates_processed']}/{len(dates_to_process)} dates, "
                           f"{self.stats['events_scraped']} events, {rate:.1f} dates/min")

        # Summary
        elapsed = time.time() - self.stats['start_time']

        logger.info("\n" + "=" * 70)
        logger.info("PARALLEL BACKFILL COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Time: {elapsed/60:.1f} minutes")
        logger.info(f"Dates processed: {self.stats['dates_processed']}")
        logger.info(f"Events scraped: {self.stats['events_scraped']}")
        logger.info(f"Events skipped: {self.stats['events_skipped']}")
        logger.info(f"Events failed: {self.stats['events_failed']}")
        logger.info(f"API calls: {self.stats['api_calls']}")
        logger.info(f"Rate: {self.stats['dates_processed'] / (elapsed / 60):.1f} dates/min")

        return self.stats


def main():
    parser = argparse.ArgumentParser(description='Parallel MLB historical backfill')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--workers', type=int, default=5, help='Parallel workers (default: 5)')
    parser.add_argument('--delay', type=float, default=0.1, help='Delay between API calls (default: 0.1s)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be processed')

    args = parser.parse_args()

    backfill = ParallelBackfill(
        start_date=args.start_date,
        end_date=args.end_date,
        workers=args.workers,
        delay=args.delay,
        dry_run=args.dry_run,
    )

    try:
        backfill.run()
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Backfill failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

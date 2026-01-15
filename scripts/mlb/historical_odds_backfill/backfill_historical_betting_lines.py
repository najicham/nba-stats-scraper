#!/usr/bin/env python3
"""
MLB Historical Betting Lines Backfill

Scrapes historical pitcher prop betting lines from The Odds API for all
prediction dates. Uses existing MLB scrapers (mlb_events_his, mlb_pitcher_props_his)
with GCS storage for downstream BigQuery processing.

Usage:
    # Dry-run to see what would be processed
    python scripts/mlb/historical_odds_backfill/backfill_historical_betting_lines.py --dry-run

    # Test on small date range
    python scripts/mlb/historical_odds_backfill/backfill_historical_betting_lines.py \
        --start-date 2024-06-01 --end-date 2024-06-07

    # Full backfill (use --resume to skip existing)
    python scripts/mlb/historical_odds_backfill/backfill_historical_betting_lines.py --resume

    # Resume from specific date
    python scripts/mlb/historical_odds_backfill/backfill_historical_betting_lines.py \
        --skip-to-date 2024-07-15 --resume

Process:
1. Query BigQuery for unique prediction dates
2. For each date, scrape historical events (game IDs)
3. For each event, scrape pitcher props and save to GCS
4. After completion, run the processor to load to BigQuery

GCS Output: gs://nba-scraped-data/mlb-odds-api/pitcher-props-history/{date}/{event_id}-{teams}/...
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Set

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
SNAPSHOT_TIME = "18:00:00Z"  # 2 PM ET - optimal for MLB evening games
RATE_LIMIT_DELAY = 1.0  # seconds between API calls


class MLBHistoricalBettingLinesBackfill:
    """Backfills historical betting lines from Odds API for MLB pitcher strikeout predictions."""

    def __init__(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        skip_to_date: Optional[str] = None,
        resume: bool = True,
        dry_run: bool = False,
        delay: float = RATE_LIMIT_DELAY,
    ):
        self.start_date = start_date
        self.end_date = end_date
        self.skip_to_date = skip_to_date
        self.resume = resume
        self.dry_run = dry_run
        self.delay = delay

        self.bq_client = bigquery.Client(project=PROJECT_ID)
        self.storage_client = storage.Client(project=PROJECT_ID)
        self.bucket = self.storage_client.bucket(BUCKET_NAME)

        # Stats tracking
        self.stats = {
            'dates_processed': 0,
            'dates_skipped': 0,
            'events_found': 0,
            'events_scraped': 0,
            'events_skipped_existing': 0,
            'events_failed': 0,
            'strikeout_lines_found': 0,
            'api_calls': 0,
            'start_time': None,
        }

        # Track processed events for resume
        self.existing_events: Set[str] = set()

    def get_prediction_dates(self) -> List[str]:
        """Get unique dates with predictions from BigQuery."""
        query = """
        SELECT DISTINCT game_date
        FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
        WHERE game_date BETWEEN @start_date AND @end_date
        ORDER BY game_date
        """

        # Default date range if not specified
        start = self.start_date or '2024-04-09'
        end = self.end_date or '2025-09-28'

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start),
                bigquery.ScalarQueryParameter("end_date", "DATE", end),
            ]
        )

        logger.info(f"Querying prediction dates from {start} to {end}...")
        results = self.bq_client.query(query, job_config=job_config).result()

        dates = [row.game_date.strftime('%Y-%m-%d') for row in results]
        logger.info(f"Found {len(dates)} dates with predictions")

        return dates

    def scan_existing_gcs_files(self, dates: List[str]) -> None:
        """Scan GCS for existing files to enable resume capability."""
        if not self.resume:
            logger.info("Resume disabled - will re-scrape all events")
            return

        logger.info("Scanning GCS for existing files...")

        for date in dates:
            prefix = f"{GCS_PREFIX}/{date}/"
            blobs = list(self.bucket.list_blobs(prefix=prefix, max_results=1000))

            for blob in blobs:
                # Extract event_id from path: pitcher-props-history/2024-06-15/eventid-TEAMS/...
                parts = blob.name.split('/')
                if len(parts) >= 4:
                    event_dir = parts[3]  # e.g., "abc123-MINOAK"
                    event_id = event_dir.split('-')[0] if '-' in event_dir else event_dir
                    self.existing_events.add(f"{date}:{event_id}")

        logger.info(f"Found {len(self.existing_events)} existing event files in GCS")

    def event_exists_in_gcs(self, date: str, event_id: str) -> bool:
        """Check if props data already exists for this event."""
        if not self.resume:
            return False
        return f"{date}:{event_id}" in self.existing_events

    def scrape_events(self, game_date: str) -> List[Dict]:
        """Scrape historical events for a date."""
        snapshot_timestamp = f"{game_date}T{SNAPSHOT_TIME}"

        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scrapers/mlb/oddsapi/mlb_events_his.py"),
            "--game_date", game_date,
            "--snapshot_timestamp", snapshot_timestamp,
            "--group", "dev"  # Write to /tmp for parsing
        ]

        env = os.environ.copy()
        env["SPORT"] = "mlb"

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=env
            )
            self.stats['api_calls'] += 1

            # Read output file
            output_file = f"/tmp/mlb_events_his_{game_date}.json"
            if not os.path.exists(output_file):
                logger.warning(f"Events output file not found: {output_file}")
                return []

            with open(output_file) as f:
                data = json.load(f)

            events = data.get('events', [])
            return events

        except subprocess.TimeoutExpired:
            logger.error(f"Events scraper timed out for {game_date}")
            return []
        except Exception as e:
            logger.error(f"Events scraper failed for {game_date}: {e}")
            return []

    def scrape_pitcher_props(self, event_id: str, game_date: str) -> Dict:
        """Scrape pitcher props for an event and save to GCS."""
        snapshot_timestamp = f"{game_date}T{SNAPSHOT_TIME}"

        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scrapers/mlb/oddsapi/mlb_pitcher_props_his.py"),
            "--event_id", event_id,
            "--game_date", game_date,
            "--snapshot_timestamp", snapshot_timestamp,
            "--group", "gcs"  # Write to GCS for processing
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

            # Parse output for stats
            if "strikeout lines" in result.stdout.lower() or "strikeoutlinecount" in result.stdout.lower():
                # Extract strikeout count from logs
                import re
                match = re.search(r'(\d+)\s*strikeout\s*lines', result.stdout, re.IGNORECASE)
                if match:
                    count = int(match.group(1))
                    self.stats['strikeout_lines_found'] += count

            if result.returncode != 0:
                # Check for expected errors
                if "404" in result.stderr or "not found" in result.stderr.lower():
                    logger.debug(f"Event {event_id[:12]}... not available at snapshot")
                    return {'status': 'not_found', 'event_id': event_id}

                logger.warning(f"Props scraper failed for {event_id[:12]}...: {result.stderr[:100]}")
                return {'status': 'error', 'event_id': event_id, 'error': result.stderr[:200]}

            return {'status': 'success', 'event_id': event_id}

        except subprocess.TimeoutExpired:
            logger.warning(f"Props scraper timed out for {event_id[:12]}...")
            return {'status': 'timeout', 'event_id': event_id}
        except Exception as e:
            logger.error(f"Props scraper exception for {event_id[:12]}...: {e}")
            return {'status': 'exception', 'event_id': event_id, 'error': str(e)}

    def process_date(self, game_date: str, date_idx: int, total_dates: int) -> None:
        """Process all events for a single date."""
        logger.info(f"\n[{date_idx}/{total_dates}] Processing {game_date}")

        # Get events
        events = self.scrape_events(game_date)
        self.stats['events_found'] += len(events)

        if not events:
            logger.info(f"  No events found for {game_date}")
            return

        logger.info(f"  Found {len(events)} events")

        if self.dry_run:
            # Count how many would be scraped
            would_scrape = sum(1 for e in events if not self.event_exists_in_gcs(game_date, e['id']))
            would_skip = len(events) - would_scrape
            logger.info(f"  DRY RUN: Would scrape {would_scrape}, skip {would_skip} (existing)")
            return

        # Process each event
        for event in events:
            event_id = event['id']
            home_team = event.get('home_team', 'Unknown')
            away_team = event.get('away_team', 'Unknown')

            # Check if already exists
            if self.event_exists_in_gcs(game_date, event_id):
                logger.debug(f"  Skipping {away_team} @ {home_team} (exists)")
                self.stats['events_skipped_existing'] += 1
                continue

            logger.info(f"  Scraping {away_team} @ {home_team}...")

            result = self.scrape_pitcher_props(event_id, game_date)

            if result['status'] == 'success':
                self.stats['events_scraped'] += 1
            else:
                self.stats['events_failed'] += 1

            # Rate limiting
            time.sleep(self.delay)

        self.stats['dates_processed'] += 1

    def log_progress(self) -> None:
        """Log current progress with ETA."""
        elapsed = time.time() - self.stats['start_time']

        total_processed = self.stats['dates_processed'] + self.stats['dates_skipped']
        if total_processed > 0 and elapsed > 0:
            rate = total_processed / elapsed
            # Rough estimate of remaining
            # This is an approximation since we don't know total dates upfront in all modes
            logger.info(
                f"Progress: {self.stats['dates_processed']} dates | "
                f"{self.stats['events_scraped']} events scraped | "
                f"{self.stats['events_skipped_existing']} skipped | "
                f"{self.stats['strikeout_lines_found']} K-lines found | "
                f"{self.stats['api_calls']} API calls"
            )

    def run(self) -> Dict:
        """Execute the backfill."""
        self.stats['start_time'] = time.time()

        logger.info("=" * 70)
        logger.info("MLB HISTORICAL BETTING LINES BACKFILL")
        logger.info("=" * 70)

        # Get prediction dates
        dates = self.get_prediction_dates()

        if not dates:
            logger.warning("No prediction dates found!")
            return self.stats

        # Apply skip-to-date filter
        if self.skip_to_date:
            try:
                skip_idx = dates.index(self.skip_to_date)
                skipped = dates[:skip_idx]
                dates = dates[skip_idx:]
                self.stats['dates_skipped'] = len(skipped)
                logger.info(f"Skipping to {self.skip_to_date}, {len(dates)} dates remaining")
            except ValueError:
                logger.warning(f"Skip-to-date {self.skip_to_date} not found in predictions")

        # Scan GCS for existing files
        self.scan_existing_gcs_files(dates)

        logger.info(f"\nConfiguration:")
        logger.info(f"  Dates to process: {len(dates)}")
        logger.info(f"  Resume mode: {self.resume}")
        logger.info(f"  Dry run: {self.dry_run}")
        logger.info(f"  Rate limit: {self.delay}s")
        logger.info(f"  Snapshot time: {SNAPSHOT_TIME}")
        logger.info("")

        # Process each date
        total_dates = len(dates)
        for i, game_date in enumerate(dates, 1):
            self.process_date(game_date, i, total_dates)

            # Log progress every 10 dates
            if i % 10 == 0:
                self.log_progress()

        # Final summary
        elapsed = time.time() - self.stats['start_time']

        logger.info("\n" + "=" * 70)
        logger.info("BACKFILL COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Total time: {elapsed/60:.1f} minutes")
        logger.info(f"Dates processed: {self.stats['dates_processed']}")
        logger.info(f"Dates skipped (resume): {self.stats['dates_skipped']}")
        logger.info(f"Events found: {self.stats['events_found']}")
        logger.info(f"Events scraped: {self.stats['events_scraped']}")
        logger.info(f"Events skipped (existing): {self.stats['events_skipped_existing']}")
        logger.info(f"Events failed: {self.stats['events_failed']}")
        logger.info(f"Strikeout lines found: {self.stats['strikeout_lines_found']}")
        logger.info(f"Total API calls: {self.stats['api_calls']}")

        if not self.dry_run and self.stats['events_scraped'] > 0:
            logger.info("\n" + "-" * 70)
            logger.info("NEXT STEPS:")
            logger.info("-" * 70)
            logger.info("1. Run the processor to load GCS data to BigQuery:")
            logger.info("   python data_processors/raw/mlb/mlb_pitcher_props_processor.py --backfill")
            logger.info("")
            logger.info("2. Match betting lines to predictions (SQL in Phase 5)")
            logger.info("")
            logger.info("3. Grade predictions:")
            logger.info("   python data_processors/grading/mlb/mlb_prediction_grading_processor.py")

        return self.stats


def main():
    parser = argparse.ArgumentParser(
        description='Backfill MLB historical betting lines from Odds API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run to see what would be processed
  python backfill_historical_betting_lines.py --dry-run

  # Test on small date range
  python backfill_historical_betting_lines.py --start-date 2024-06-01 --end-date 2024-06-07

  # Full backfill with resume (skip existing)
  python backfill_historical_betting_lines.py --resume

  # Force re-scrape (no resume)
  python backfill_historical_betting_lines.py --no-resume

  # Resume from specific date
  python backfill_historical_betting_lines.py --skip-to-date 2024-07-15
        """
    )

    parser.add_argument(
        '--start-date',
        help='Start date (YYYY-MM-DD). Default: 2024-04-09'
    )
    parser.add_argument(
        '--end-date',
        help='End date (YYYY-MM-DD). Default: 2025-09-28'
    )
    parser.add_argument(
        '--skip-to-date',
        help='Skip to this date (for resuming interrupted runs)'
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        default=True,
        help='Skip events that already exist in GCS (default: True)'
    )
    parser.add_argument(
        '--no-resume',
        action='store_true',
        help='Force re-scrape all events (ignore existing GCS files)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be processed without making API calls'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=RATE_LIMIT_DELAY,
        help=f'Delay between API calls in seconds (default: {RATE_LIMIT_DELAY})'
    )

    args = parser.parse_args()

    # Handle --no-resume flag
    resume = not args.no_resume

    backfill = MLBHistoricalBettingLinesBackfill(
        start_date=args.start_date,
        end_date=args.end_date,
        skip_to_date=args.skip_to_date,
        resume=resume,
        dry_run=args.dry_run,
        delay=args.delay,
    )

    try:
        stats = backfill.run()

        # Exit with error if there were failures
        if stats['events_failed'] > 0 and stats['events_scraped'] == 0:
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("\n\nBackfill interrupted by user")
        logger.info("Resume with: --skip-to-date <last_date>")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Backfill failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

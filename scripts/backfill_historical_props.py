#!/usr/bin/env python3
"""
Historical Props Backfill Script

Scrapes historical player props from Odds API for a date range.
Uses the historical events and player props endpoints.

Usage:
    python scripts/backfill_historical_props.py --start-date 2025-10-22 --end-date 2025-11-13

Process:
1. For each date, get historical events (game IDs)
2. For each event, scrape player props
3. Props are saved to GCS by the scrapers
4. After scraping, run scripts/backfill_odds_api_props.py to load to BigQuery
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def get_game_dates(start_date: str, end_date: str) -> list:
    """Generate list of dates between start and end."""
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')

    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)

    return dates


def scrape_historical_events(game_date: str, snapshot_time: str = "18:00:00Z") -> list:
    """Scrape historical events for a date and return event IDs."""
    snapshot_timestamp = f"{game_date}T{snapshot_time}"

    logger.info(f"Fetching events for {game_date}...")

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scrapers/oddsapi/oddsa_events_his.py"),
        "--game_date", game_date,
        "--snapshot_timestamp", snapshot_timestamp,
        "--group", "dev"  # Write to /tmp file for inspection (group 'dev' matches exporter config)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        logger.error(f"Events scraper failed: {result.stderr}")
        return []

    # Read the output file
    output_file = f"/tmp/oddsapi_hist_events_{game_date}.json"
    if not os.path.exists(output_file):
        logger.error(f"Events output file not found: {output_file}")
        return []

    with open(output_file) as f:
        data = json.load(f)

    events = data.get('events', [])
    logger.info(f"Found {len(events)} events for {game_date}")

    return events


def scrape_player_props_for_event(event_id: str, game_date: str, snapshot_time: str = "18:00:00Z") -> bool:
    """Scrape player props for a specific event."""
    snapshot_timestamp = f"{game_date}T{snapshot_time}"

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scrapers/oddsapi/oddsa_player_props_his.py"),
        "--event_id", event_id,
        "--game_date", game_date,
        "--snapshot_timestamp", snapshot_timestamp,
        "--markets", "player_points",
        "--group", "gcs"  # Write to GCS for processing
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        # Check if it's a 404 (event not available at timestamp)
        if "404" in result.stderr or "not found" in result.stderr.lower():
            logger.warning(f"Event {event_id} not available at {snapshot_timestamp}")
            return False
        logger.error(f"Props scraper failed for {event_id}: {result.stderr[:200]}")
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description='Backfill historical props from Odds API')
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--delay', type=float, default=1.0, help='Delay between API calls (seconds)')
    parser.add_argument('--dry-run', action='store_true', help='Only fetch events, don\'t scrape props')
    parser.add_argument('--skip-to-date', help='Skip to this date (for resuming)')
    parser.add_argument('--snapshot-time', default='18:00:00Z',
                        help='UTC snapshot time for historical data (default: 18:00:00Z = 2PM ET peak)')

    args = parser.parse_args()

    dates = get_game_dates(args.start_date, args.end_date)
    logger.info(f"Processing {len(dates)} dates from {args.start_date} to {args.end_date}")

    # Skip dates if resuming
    if args.skip_to_date:
        skip_idx = dates.index(args.skip_to_date) if args.skip_to_date in dates else 0
        dates = dates[skip_idx:]
        logger.info(f"Skipping to {args.skip_to_date}, {len(dates)} dates remaining")

    stats = {
        'dates_processed': 0,
        'events_found': 0,
        'props_scraped': 0,
        'props_failed': 0
    }

    for i, game_date in enumerate(dates):
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing date {i+1}/{len(dates)}: {game_date}")
        logger.info(f"{'='*60}")

        # Get events for this date
        events = scrape_historical_events(game_date, snapshot_time=args.snapshot_time)
        stats['events_found'] += len(events)

        if not events:
            logger.warning(f"No events found for {game_date}")
            continue

        if args.dry_run:
            logger.info(f"DRY RUN: Would scrape {len(events)} events")
            stats['dates_processed'] += 1
            continue

        # Scrape props for each event
        for j, event in enumerate(events):
            event_id = event['id']
            home_team = event.get('home_team', 'Unknown')
            away_team = event.get('away_team', 'Unknown')

            logger.info(f"  Event {j+1}/{len(events)}: {away_team} @ {home_team}")

            success = scrape_player_props_for_event(event_id, game_date, snapshot_time=args.snapshot_time)

            if success:
                stats['props_scraped'] += 1
            else:
                stats['props_failed'] += 1

            # Rate limiting
            time.sleep(args.delay)

        stats['dates_processed'] += 1

        # Progress update
        logger.info(f"\nProgress: {stats}")

    # Final summary
    logger.info("\n" + "="*60)
    logger.info("HISTORICAL PROPS BACKFILL COMPLETE")
    logger.info("="*60)
    logger.info(f"Dates processed: {stats['dates_processed']}")
    logger.info(f"Events found: {stats['events_found']}")
    logger.info(f"Props scraped: {stats['props_scraped']}")
    logger.info(f"Props failed: {stats['props_failed']}")

    if not args.dry_run and stats['props_scraped'] > 0:
        logger.info("\nNext step: Run GCS → BigQuery loader:")
        logger.info(f"  python scripts/backfill_odds_api_props.py --start-date {args.start_date} --end-date {args.end_date}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Direct Historical Props Backfill — calls Odds API directly, writes to GCS.
Bypasses scraper infrastructure (no SES, no notifications, no subprocess overhead).

Usage:
    export ODDS_API_KEY=$(gcloud secrets versions access latest --secret=ODDS_API_KEY --project=nba-props-platform)
    PYTHONPATH=. python scripts/backfill_historical_props_direct.py \
        --start-date 2025-11-01 --end-date 2026-02-12 \
        --snapshot-time 18:00:00Z --delay 1.0

Then load to BQ:
    PYTHONPATH=. python scripts/backfill_odds_api_props.py \
        --start-date 2025-11-01 --end-date 2026-02-12 --historical
"""

import argparse
import json
import logging
import os
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests
from google.cloud import storage

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

API_BASE = "https://api.the-odds-api.com/v4/historical/sports/basketball_nba"
GCS_BUCKET = os.environ.get("GCS_BUCKET_RAW", "nba-scraped-data")
BOOKMAKERS = "draftkings,fanduel,betmgm,williamhill_us,betrivers,bovada,espnbet,hardrockbet,betonlineag,fliff,betparx,ballybet"


def snap_to_5min(timestamp_str: str) -> str:
    """Snap timestamp to nearest 5-minute boundary (API requirement)."""
    dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
    minute = (dt.minute // 5) * 5
    dt = dt.replace(minute=minute, second=0, microsecond=0)
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def get_events(api_key: str, game_date: str, snapshot_time: str) -> list:
    """Fetch historical events for a date."""
    snapshot = snap_to_5min(f"{game_date}T{snapshot_time}")
    params = {"apiKey": api_key, "date": snapshot}
    url = f"{API_BASE}/events?{urlencode(params)}"

    resp = requests.get(url, timeout=30)
    if resp.status_code == 404:
        return []
    if resp.status_code == 204:
        return []
    resp.raise_for_status()

    data = resp.json()
    remaining = resp.headers.get('x-requests-remaining', '?')
    logger.info(f"  API quota remaining: {remaining}")
    return data.get('data', [])


def get_player_props(api_key: str, event_id: str, game_date: str, snapshot_time: str) -> dict | None:
    """Fetch historical player props for an event."""
    snapshot = snap_to_5min(f"{game_date}T{snapshot_time}")
    params = {
        "apiKey": api_key,
        "date": snapshot,
        "regions": "us",
        "markets": "player_points",
        "bookmakers": BOOKMAKERS,
    }
    url = f"{API_BASE}/events/{event_id}/odds?{urlencode(params)}"

    resp = requests.get(url, timeout=30)
    if resp.status_code in (404, 204):
        return None
    resp.raise_for_status()

    return resp.json()


def extract_teams(event_data: dict) -> str:
    """Extract team suffix from event data."""
    data = event_data.get('data', event_data)
    home = data.get('home_team', '')
    away = data.get('away_team', '')
    # Take last word of each team name as abbreviation
    h = home.split()[-1][:3].upper() if home else 'UNK'
    a = away.split()[-1][:3].upper() if away else 'UNK'
    return f"{a}{h}"


def upload_to_gcs(bucket_name: str, path: str, data: dict) -> str:
    """Upload JSON data to GCS."""
    client = storage.Client(project='nba-props-platform')
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(path)
    blob.upload_from_string(json.dumps(data), content_type='application/json')
    return f"gs://{bucket_name}/{path}"


def main():
    parser = argparse.ArgumentParser(description='Direct historical props backfill')
    parser.add_argument('--start-date', required=True)
    parser.add_argument('--end-date', required=True)
    parser.add_argument('--snapshot-time', default='18:00:00Z')
    parser.add_argument('--delay', type=float, default=1.0)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--skip-to-date', help='Resume from this date')
    args = parser.parse_args()

    api_key = os.environ.get('ODDS_API_KEY')
    if not api_key:
        logger.error("ODDS_API_KEY not set")
        return

    # Generate dates
    start = datetime.strptime(args.start_date, '%Y-%m-%d')
    end = datetime.strptime(args.end_date, '%Y-%m-%d')
    dates = []
    cur = start
    while cur <= end:
        dates.append(cur.strftime('%Y-%m-%d'))
        cur += timedelta(days=1)

    if args.skip_to_date and args.skip_to_date in dates:
        dates = dates[dates.index(args.skip_to_date):]
        logger.info(f"Resuming from {args.skip_to_date}, {len(dates)} dates remaining")

    logger.info(f"Processing {len(dates)} dates from {args.start_date} to {args.end_date}")

    stats = {'dates': 0, 'events': 0, 'props_ok': 0, 'props_fail': 0, 'no_games': 0}

    for i, game_date in enumerate(dates):
        logger.info(f"\n[{i+1}/{len(dates)}] {game_date}")

        try:
            events = get_events(api_key, game_date, args.snapshot_time)
        except Exception as e:
            logger.error(f"  Events fetch failed: {e}")
            continue

        if not events:
            logger.info(f"  No events (no games or off-day)")
            stats['no_games'] += 1
            continue

        logger.info(f"  {len(events)} events found")
        stats['events'] += len(events)

        if args.dry_run:
            for ev in events:
                logger.info(f"    {ev.get('away_team', '?')} @ {ev.get('home_team', '?')}")
            stats['dates'] += 1
            continue

        for j, event in enumerate(events):
            event_id = event['id']
            home = event.get('home_team', 'Unknown')
            away = event.get('away_team', 'Unknown')
            logger.info(f"  [{j+1}/{len(events)}] {away} @ {home}")

            try:
                props = get_player_props(api_key, event_id, game_date, args.snapshot_time)
            except Exception as e:
                logger.error(f"    Props fetch failed: {e}")
                stats['props_fail'] += 1
                time.sleep(args.delay)
                continue

            if not props:
                logger.warning(f"    No props available")
                stats['props_fail'] += 1
                time.sleep(args.delay)
                continue

            # Build GCS path matching scraper convention
            teams = extract_teams(props)
            snap_hour = args.snapshot_time[:2] + args.snapshot_time[3:5]
            ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            gcs_path = f"odds-api/player-props-history/{game_date}/{event_id}-{teams}/{ts}-snap-{snap_hour}.json"

            try:
                gcs_uri = upload_to_gcs(GCS_BUCKET, gcs_path, props)
                logger.info(f"    Uploaded: {gcs_uri}")
                stats['props_ok'] += 1
            except Exception as e:
                logger.error(f"    GCS upload failed: {e}")
                stats['props_fail'] += 1

            time.sleep(args.delay)

        stats['dates'] += 1

        # Progress every 10 dates
        if (i + 1) % 10 == 0:
            logger.info(f"\n--- Progress: {stats} ---\n")

    logger.info(f"\n{'='*60}")
    logger.info(f"BACKFILL COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"Dates processed: {stats['dates']}")
    logger.info(f"No-game days: {stats['no_games']}")
    logger.info(f"Events found: {stats['events']}")
    logger.info(f"Props scraped: {stats['props_ok']}")
    logger.info(f"Props failed: {stats['props_fail']}")
    logger.info(f"\nNext: PYTHONPATH=. python scripts/backfill_odds_api_props.py --start-date {args.start_date} --end-date {args.end_date} --historical")


if __name__ == "__main__":
    main()

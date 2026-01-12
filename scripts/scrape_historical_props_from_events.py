#!/usr/bin/env python3
"""
Scrape historical player props from event files.

Reads event files created by oddsa_events_his scraper and scrapes
player props for each event.

Usage:
    python scripts/scrape_historical_props_from_events.py
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

# Dates with events
# Starting from Oct 24 (Oct 22-23 already done)
DATES = [
    "2025-10-24", "2025-10-25", "2025-10-26",
    "2025-10-27", "2025-10-28", "2025-10-29", "2025-10-30", "2025-10-31",
    "2025-11-01", "2025-11-02", "2025-11-03", "2025-11-04", "2025-11-05",
    "2025-11-06", "2025-11-07", "2025-11-08", "2025-11-09", "2025-11-10",
    "2025-11-11", "2025-11-12", "2025-11-13"
]

def main():
    total_events = 0
    success_count = 0
    fail_count = 0

    for game_date in DATES:
        events_file = f"/tmp/oddsapi_hist_events_{game_date}.json"

        if not os.path.exists(events_file):
            print(f"SKIP: No events file for {game_date}")
            continue

        with open(events_file) as f:
            data = json.load(f)

        events = data.get('events', [])
        snapshot = data.get('snapshot_timestamp', f"{game_date}T04:00:00Z")

        print(f"\n{'='*60}")
        print(f"Processing {game_date}: {len(events)} events")
        print(f"{'='*60}")

        for i, event in enumerate(events):
            event_id = event['id']
            home = event.get('home_team', 'Unknown')[:15]
            away = event.get('away_team', 'Unknown')[:15]

            print(f"  [{i+1}/{len(events)}] {away} @ {home}...", end=" ", flush=True)

            cmd = [
                sys.executable,
                "scrapers/oddsapi/oddsa_player_props_his.py",
                "--event_id", event_id,
                "--game_date", game_date,
                "--snapshot_timestamp", snapshot,
                "--markets", "player_points",
                "--group", "gcs"
            ]

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=180  # Increased to 3 min
                )
            except subprocess.TimeoutExpired:
                print("TIMEOUT")
                fail_count += 1
                total_events += 1
                continue

            total_events += 1

            if result.returncode == 0:
                # Check for success in output
                if "rowCount" in result.stdout or "success" in result.stdout.lower():
                    print("OK")
                    success_count += 1
                else:
                    print("OK (empty?)")
                    success_count += 1
            else:
                if "404" in result.stderr or "not found" in result.stderr.lower():
                    print("SKIP (404)")
                else:
                    print(f"FAIL")
                fail_count += 1

            # Rate limiting - be gentle with API
            time.sleep(0.5)

        # Progress summary per date
        print(f"  Progress: {success_count}/{total_events} success, {fail_count} failed")

    print(f"\n{'='*60}")
    print("COMPLETE")
    print(f"{'='*60}")
    print(f"Total events: {total_events}")
    print(f"Success: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"\nNext: Run BigQuery loader:")
    print(f"  python scripts/backfill_odds_api_props.py --start-date 2025-10-22 --end-date 2025-11-13")

if __name__ == "__main__":
    main()

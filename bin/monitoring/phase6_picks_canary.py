#!/usr/bin/env python3
"""
Phase 6 Export Canary Check

Validates that critical Phase 6 export files exist AND are fresh.
Checks both date-specific files and latest.json freshness.

Usage:
    python bin/monitoring/phase6_picks_canary.py [--date YYYY-MM-DD]

Integration:
    Run via Cloud Scheduler every 2 hours between 12 PM - 11 PM ET
    Alert to #phase6-alerts Slack channel if files missing or stale
"""

import argparse
import json
from datetime import date, datetime, timezone, timedelta
from google.cloud import storage
import sys

# Critical files that must exist for today's date
CRITICAL_FILES = [
    'picks/{date}.json',
    'signals/{date}.json',
    'predictions/{date}.json',
]

# Optional files (warn but don't alert)
OPTIONAL_FILES = [
    'best-bets/{date}.json',
    'tonight/all-players.json',
    'calendar/game-counts.json',
]

# Latest files that should be fresh (not more than max_age_hours old)
FRESHNESS_FILES = [
    {'path': 'results/latest.json', 'max_age_hours': 30, 'date_field': 'game_date'},
    {'path': 'tonight/all-players.json', 'max_age_hours': 6, 'date_field': 'game_date'},
]


def check_file_exists(bucket_name: str, blob_path: str) -> tuple:
    """Check if a file exists in GCS. Returns (exists, message, blob_or_none)."""
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)

        if blob.exists():
            blob.reload()
            size = blob.size
            updated = blob.updated
            return True, f"OK {blob_path} ({size:,} bytes, updated {updated})", blob
        else:
            return False, f"MISSING {blob_path} - FILE NOT FOUND", None
    except Exception as e:
        return False, f"ERROR {blob_path} - {e}", None


def check_freshness(bucket_name: str, file_config: dict) -> tuple:
    """Check if a latest.json file is fresh enough based on its content date."""
    blob_path = f"v1/{file_config['path']}"
    max_age_hours = file_config['max_age_hours']
    date_field = file_config['date_field']

    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)

        if not blob.exists():
            return False, f"MISSING {blob_path} - FILE NOT FOUND"

        blob.reload()
        # Check file modification time
        now = datetime.now(timezone.utc)
        age = now - blob.updated
        age_hours = age.total_seconds() / 3600

        if age_hours > max_age_hours:
            return False, (
                f"STALE {blob_path} - last updated {age_hours:.1f}h ago "
                f"(threshold: {max_age_hours}h)"
            )

        # Also check content date if possible
        try:
            content = blob.download_as_string()
            data = json.loads(content)
            content_date = data.get(date_field)
            if content_date:
                return True, (
                    f"OK {blob_path} (date={content_date}, "
                    f"age={age_hours:.1f}h, {blob.size:,} bytes)"
                )
        except Exception:
            pass

        return True, f"OK {blob_path} (age={age_hours:.1f}h, {blob.size:,} bytes)"

    except Exception as e:
        return False, f"ERROR {blob_path} - {e}"


def main():
    parser = argparse.ArgumentParser(description='Check Phase 6 export files exist and are fresh')
    parser.add_argument('--date', help='Date to check (YYYY-MM-DD), defaults to today')
    parser.add_argument('--bucket', default='nba-props-platform-api', help='GCS bucket name')
    args = parser.parse_args()

    check_date = args.date if args.date else date.today().isoformat()

    print(f"=== Phase 6 Export Canary for {check_date} ===\n")

    # Check critical files
    critical_missing = []
    critical_results = []

    for file_template in CRITICAL_FILES:
        file_path = f"v1/{file_template.format(date=check_date)}"
        exists, message, _ = check_file_exists(args.bucket, file_path)
        critical_results.append(message)
        if not exists:
            critical_missing.append(file_path)

    # Check optional files
    optional_missing = []
    optional_results = []

    for file_template in OPTIONAL_FILES:
        if '{date}' in file_template:
            file_path = f"v1/{file_template.format(date=check_date)}"
        else:
            file_path = f"v1/{file_template}"
        exists, message, _ = check_file_exists(args.bucket, file_path)
        optional_results.append(message)
        if not exists:
            optional_missing.append(file_path)

    # Check freshness of latest files
    stale_files = []
    freshness_results = []

    for file_config in FRESHNESS_FILES:
        fresh, message = check_freshness(args.bucket, file_config)
        freshness_results.append(message)
        if not fresh:
            stale_files.append(file_config['path'])

    # Print results
    print("CRITICAL FILES:")
    for result in critical_results:
        print(f"  {result}")

    print("\nOPTIONAL FILES:")
    for result in optional_results:
        print(f"  {result}")

    print("\nFRESHNESS:")
    for result in freshness_results:
        print(f"  {result}")

    # Summary
    print("\n=== SUMMARY ===")
    has_alerts = False

    if critical_missing:
        has_alerts = True
        print(f"ALERT: {len(critical_missing)} critical file(s) missing!")
        for file_path in critical_missing:
            print(f"   - {file_path}")
        print("\nREMEDIATION:")
        print(f"   gcloud scheduler jobs run phase6-tonight-picks --location=us-west2")

    if stale_files:
        has_alerts = True
        print(f"ALERT: {len(stale_files)} file(s) stale!")
        for file_path in stale_files:
            print(f"   - {file_path}")
        print("\nREMEDIATION:")
        print("   PYTHONPATH=. python backfill_jobs/publishing/daily_export.py "
              "--date $(date -d yesterday +%Y-%m-%d) --only results,live-grading")

    if not has_alerts:
        print("All critical files present and fresh")

    if optional_missing:
        print(f"Warning: {len(optional_missing)} optional file(s) missing")

    sys.exit(1 if has_alerts else 0)


if __name__ == '__main__':
    main()

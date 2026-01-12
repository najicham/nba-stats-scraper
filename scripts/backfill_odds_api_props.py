#!/usr/bin/env python3
"""
Backfill Odds API player props data from GCS to BigQuery.
Calls Phase 2 processor for each GCS file.

Usage:
    # Dry run to see what would be processed
    python scripts/backfill_odds_api_props.py --start-date 2025-11-14 --end-date 2025-11-14 --dry-run

    # Process a single date
    python scripts/backfill_odds_api_props.py --start-date 2025-11-14 --end-date 2025-11-14

    # Process full date range
    python scripts/backfill_odds_api_props.py --start-date 2025-11-14 --end-date 2025-12-31

    # With parallelism
    python scripts/backfill_odds_api_props.py --start-date 2025-11-14 --end-date 2025-12-31 --parallel 5

    # Load HISTORICAL props (from odds-api/player-props-history/ instead of odds-api/player-props/)
    python scripts/backfill_odds_api_props.py --start-date 2025-10-22 --end-date 2025-11-13 --historical

Created: 2026-01-11
Purpose: Recover 47 dates of prop data that was scraped to GCS but never loaded to BigQuery
"""

import argparse
import base64
import json
import subprocess
import requests
from datetime import datetime, timedelta
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

PHASE2_URL = "https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process"
GCS_BUCKET = "nba-scraped-data"
GCS_PREFIX = "odds-api/player-props"
GCS_PREFIX_HISTORICAL = "odds-api/player-props-history"


def get_identity_token():
    """Get identity token for Cloud Run authentication."""
    result = subprocess.run(
        ["gcloud", "auth", "print-identity-token"],
        capture_output=True,
        text=True
    )
    return result.stdout.strip()


def list_gcs_files(date_str: str, historical: bool = False) -> list:
    """List all JSON files for a given date.

    Args:
        date_str: Date in YYYY-MM-DD format
        historical: If True, read from player-props-history/ instead of player-props/
    """
    prefix = GCS_PREFIX_HISTORICAL if historical else GCS_PREFIX
    path = f"gs://{GCS_BUCKET}/{prefix}/{date_str}/**"
    result = subprocess.run(
        ["gsutil", "ls", "-r", path],
        capture_output=True,
        text=True
    )
    files = [f for f in result.stdout.strip().split('\n') if f.endswith('.json')]
    return files


def call_phase2(gcs_path: str, token: str) -> dict:
    """Call Phase 2 processor with simulated Pub/Sub message."""
    # Build Scraper Completion format message
    message_data = {
        "gcs_path": gcs_path,
        "status": "success",
        "scraper_name": "oddsa_player_props_backfill"
    }

    # Encode as Pub/Sub envelope
    encoded_data = base64.b64encode(json.dumps(message_data).encode()).decode()
    envelope = {
        "message": {
            "data": encoded_data,
            "messageId": f"backfill-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "publishTime": datetime.utcnow().isoformat() + "Z"
        }
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(PHASE2_URL, json=envelope, headers=headers, timeout=120)
        return {"status_code": response.status_code, "body": response.text[:500], "success": response.status_code in [200, 204]}
    except Exception as e:
        return {"status_code": -1, "body": str(e), "success": False}


def process_file(args):
    """Process a single file - used for parallel processing."""
    gcs_path, token, verbose = args
    result = call_phase2(gcs_path, token)
    if verbose:
        status = "✓" if result["success"] else "✗"
        print(f"  {status} {gcs_path.split('/')[-1]}: {result['status_code']}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Backfill Odds API player props")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="List files without processing")
    parser.add_argument("--parallel", type=int, default=1, help="Number of parallel requests (default: 1)")
    parser.add_argument("--verbose", action="store_true", help="Show per-file status")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between sequential requests (seconds)")
    parser.add_argument("--historical", action="store_true",
                        help="Read from odds-api/player-props-history/ instead of odds-api/player-props/")
    args = parser.parse_args()

    start = datetime.strptime(args.start_date, "%Y-%m-%d")
    end = datetime.strptime(args.end_date, "%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"Odds API Props Backfill: {args.start_date} to {args.end_date}")
    if args.historical:
        print(f"Source: {GCS_PREFIX_HISTORICAL}/ (historical)")
    else:
        print(f"Source: {GCS_PREFIX}/")
    print(f"{'='*60}")

    # Get auth token
    if not args.dry_run:
        token = get_identity_token()
        if not token:
            print("ERROR: Could not get identity token")
            return 1
        print(f"✓ Got identity token")
    else:
        token = None
        print("DRY RUN - no files will be processed")

    total_files = 0
    success_count = 0
    error_count = 0
    dates_processed = 0

    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        files = list_gcs_files(date_str, historical=args.historical)

        if not files or files == ['']:
            print(f"\n{date_str}: No files found")
            current += timedelta(days=1)
            continue

        print(f"\n{date_str}: {len(files)} files")
        dates_processed += 1
        total_files += len(files)

        if args.dry_run:
            for f in files[:3]:
                print(f"  - {f.split('/')[-1]}")
            if len(files) > 3:
                print(f"  ... and {len(files) - 3} more")
            current += timedelta(days=1)
            continue

        # Process files
        if args.parallel > 1:
            # Parallel processing
            with ThreadPoolExecutor(max_workers=args.parallel) as executor:
                futures = [executor.submit(process_file, (f, token, args.verbose)) for f in files]
                for future in as_completed(futures):
                    result = future.result()
                    if result["success"]:
                        success_count += 1
                    else:
                        error_count += 1
        else:
            # Sequential processing
            for f in files:
                result = call_phase2(f, token)
                if result["success"]:
                    success_count += 1
                    if args.verbose:
                        print(f"  ✓ {f.split('/')[-1]}")
                else:
                    error_count += 1
                    print(f"  ✗ {f.split('/')[-1]}: {result['status_code']} - {result['body'][:100]}")
                time.sleep(args.delay)

        print(f"  Progress: {success_count}/{total_files} successful, {error_count} errors")
        current += timedelta(days=1)

    # Summary
    print(f"\n{'='*60}")
    print(f"Summary")
    print(f"{'='*60}")
    print(f"Dates processed: {dates_processed}")
    print(f"Total files:     {total_files}")
    if not args.dry_run:
        print(f"Successful:      {success_count}")
        print(f"Errors:          {error_count}")
        print(f"Success rate:    {(success_count/total_files*100):.1f}%" if total_files > 0 else "N/A")

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

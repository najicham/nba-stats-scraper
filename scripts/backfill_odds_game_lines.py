#!/usr/bin/env python3
"""
Backfill odds game lines data from GCS to BigQuery.
Calls Phase 2 processor for each GCS file.

Usage:
    python scripts/backfill_odds_game_lines.py --start-date 2025-12-01 --end-date 2025-12-19
"""

import argparse
import base64
import json
import subprocess
import requests
from datetime import datetime, timedelta
import time

PHASE2_URL = "https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process"
GCS_BUCKET = "nba-scraped-data"
GCS_PREFIX = "odds-api/game-lines"


def get_identity_token():
    """Get identity token for Cloud Run authentication."""
    result = subprocess.run(
        ["gcloud", "auth", "print-identity-token"],
        capture_output=True,
        text=True
    )
    return result.stdout.strip()


def list_gcs_files(date_str: str) -> list:
    """List all JSON files for a given date."""
    path = f"gs://{GCS_BUCKET}/{GCS_PREFIX}/{date_str}/**"
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
        "scraper_name": "oddsa_game_lines_backfill"
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

    response = requests.post(PHASE2_URL, json=envelope, headers=headers, timeout=60)
    return {"status_code": response.status_code, "body": response.text[:200]}


def main():
    parser = argparse.ArgumentParser(description="Backfill odds game lines")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="List files without processing")
    args = parser.parse_args()

    start = datetime.strptime(args.start_date, "%Y-%m-%d")
    end = datetime.strptime(args.end_date, "%Y-%m-%d")

    # Get auth token
    token = get_identity_token()
    if not token:
        print("ERROR: Could not get identity token")
        return

    total_files = 0
    success_count = 0
    error_count = 0

    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        files = list_gcs_files(date_str)

        print(f"\n=== {date_str}: {len(files)} files ===")

        if args.dry_run:
            for f in files[:3]:
                print(f"  Would process: {f}")
            if len(files) > 3:
                print(f"  ... and {len(files) - 3} more")
        else:
            for i, gcs_path in enumerate(files):
                total_files += 1
                try:
                    result = call_phase2(gcs_path, token)
                    if result["status_code"] == 200:
                        success_count += 1
                        print(f"  [{i+1}/{len(files)}] OK: {gcs_path.split('/')[-2]}/{gcs_path.split('/')[-1][:20]}")
                    else:
                        error_count += 1
                        print(f"  [{i+1}/{len(files)}] ERR {result['status_code']}: {result['body'][:100]}")
                except Exception as e:
                    error_count += 1
                    print(f"  [{i+1}/{len(files)}] EXCEPTION: {e}")

                # Small delay to avoid overwhelming the service
                time.sleep(0.1)

        current += timedelta(days=1)

    print(f"\n=== Summary ===")
    print(f"Total files: {total_files}")
    print(f"Success: {success_count}")
    print(f"Errors: {error_count}")


if __name__ == "__main__":
    main()

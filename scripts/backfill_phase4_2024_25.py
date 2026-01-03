#!/usr/bin/env python3
"""
Phase 4 Backfill Script - 2024-25 Season

Fills missing dates in Phase 4 (precompute) by calling Phase 4 service directly.
Gap: 235 dates from Oct 22, 2024 to Jan 2, 2026

Root cause: Phase 3→4 orchestrator only triggers for live data, not backfill.
This script calls /process-date endpoint to manually trigger Phase 4 processing.
"""

import requests
import subprocess
import time
import csv
from typing import List, Tuple
from datetime import datetime

# Configuration
PHASE4_URL = "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date"
PROJECT_ID = "nba-props-platform"
MISSING_DATES_FILE = "/tmp/phase4_missing_dates_full.csv"

def get_auth_token() -> str:
    """Get GCP auth token for Cloud Run."""
    result = subprocess.run(
        ['gcloud', 'auth', 'print-identity-token'],
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout.strip()

def load_missing_dates() -> List[str]:
    """Load missing dates from CSV file."""
    dates = []
    with open(MISSING_DATES_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            dates.append(row['date'])
    return dates

def process_date(date_str: str, token: str) -> Tuple[int, str, dict]:
    """
    Process a single date through Phase 4.
    Returns (status_code, message, results)
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "analysis_date": date_str,
        "backfill_mode": True,
        "processors": []  # Empty = all processors
    }

    try:
        response = requests.post(PHASE4_URL, json=payload, headers=headers, timeout=300)

        if response.status_code == 200:
            data = response.json()
            results = data.get('results', [])
            return (response.status_code, "Success", results)
        else:
            return (response.status_code, response.text[:200], {})

    except requests.exceptions.Timeout:
        return (0, "Request timeout (300s)", {})
    except Exception as e:
        return (0, str(e), {})

def main():
    """Main backfill execution."""
    print("=" * 80)
    print(" PHASE 4 BACKFILL - 2024-25 SEASON")
    print("=" * 80)
    print()

    # Get auth token
    print("🔐 Getting auth token...")
    try:
        token = get_auth_token()
        print("✅ Auth token obtained\n")
    except Exception as e:
        print(f"❌ Failed to get auth token: {e}")
        return 1

    # Load missing dates
    print("📅 Loading missing dates...")
    try:
        dates = load_missing_dates()
        print(f"✅ Loaded {len(dates)} missing dates\n")
    except Exception as e:
        print(f"❌ Failed to load dates: {e}")
        return 1

    # Process each date
    print("-" * 80)
    print(f"Starting backfill at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 80)
    print()

    success_count = 0
    fail_count = 0
    processor_stats = {
        "TeamDefenseZoneAnalysisProcessor": {"success": 0, "error": 0},
        "PlayerShotZoneAnalysisProcessor": {"success": 0, "error": 0},
        "PlayerDailyCacheProcessor": {"success": 0, "error": 0},
        "PlayerCompositeFactorsProcessor": {"success": 0, "error": 0},
        "MLFeatureStoreProcessor": {"success": 0, "error": 0},
    }

    for i, date_str in enumerate(dates, 1):
        print(f"[{i}/{len(dates)}] {date_str} ", end='', flush=True)

        status_code, message, results = process_date(date_str, token)

        if status_code == 200:
            # Count processor successes
            success_processors = 0
            for result in results:
                proc_name = result.get('processor')
                proc_status = result.get('status')
                if proc_name in processor_stats:
                    if proc_status == 'success':
                        processor_stats[proc_name]['success'] += 1
                        success_processors += 1
                    else:
                        processor_stats[proc_name]['error'] += 1

            print(f"✅ {success_processors}/5 processors succeeded")
            success_count += 1
        else:
            print(f"❌ FAILED ({status_code}): {message}")
            fail_count += 1

        # Rate limiting: wait 2 seconds between requests
        if i < len(dates):
            time.sleep(2)

        # Progress update every 20 dates
        if i % 20 == 0:
            print(f"\n--- Progress: {i}/{len(dates)} ({100*i//len(dates)}%) ---\n")

    # Final summary
    print()
    print("=" * 80)
    print(" BACKFILL COMPLETE")
    print("=" * 80)
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n✅ Successful dates: {success_count}")
    print(f"❌ Failed dates:     {fail_count}")
    print(f"\nProcessor Success Rates:")
    for proc_name, stats in processor_stats.items():
        total = stats['success'] + stats['error']
        if total > 0:
            pct = 100 * stats['success'] / total
            print(f"  {proc_name:40s} {stats['success']:3d}/{total:3d} ({pct:5.1f}%)")
    print()

    if fail_count == 0:
        print("🎉 All dates processed successfully!")
        print("\nNext step: Validate Phase 4 coverage with:")
        print("  bq query --use_legacy_sql=false 'SELECT COUNT(DISTINCT game_id) FROM nba_precompute.player_composite_factors WHERE game_date >= \"2024-10-01\"'")
        return 0
    else:
        print(f"⚠️  {fail_count} dates failed - check logs for details")
        return 1

if __name__ == "__main__":
    exit(main())

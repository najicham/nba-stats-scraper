#!/usr/bin/env python3
"""
MLB BettingPros Backfill Progress Monitor
=========================================

Checks the progress of the MLB historical props backfill by scanning
GCS for completed files.

Usage:
    python scripts/mlb/historical_bettingpros_backfill/check_progress.py

    # Show details for specific market
    python scripts/mlb/historical_bettingpros_backfill/check_progress.py --market_id 285

    # Show missing dates
    python scripts/mlb/historical_bettingpros_backfill/check_progress.py --show-missing

Created: 2026-01-14
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Set

from google.cloud import storage

# Configuration
PROJECT_ID = 'nba-props-platform'
BUCKET_NAME = 'nba-scraped-data'
GCS_PREFIX = 'bettingpros-mlb/historical'

# Market definitions
MLB_MARKETS = {
    285: 'pitcher-strikeouts',
    290: 'pitcher-earned-runs-allowed',
    287: 'batter-hits',
    288: 'batter-runs',
    289: 'batter-rbis',
    291: 'batter-doubles',
    292: 'batter-triples',
    293: 'batter-total-bases',
    294: 'batter-stolen-bases',
    295: 'batter-singles',
    299: 'batter-home-runs',
}

PITCHER_MARKETS = [285, 290]
BATTER_MARKETS = [287, 288, 289, 291, 292, 293, 294, 295, 299]

# Season date ranges
MLB_SEASONS = {
    2022: ('2022-04-07', '2022-10-05'),
    2023: ('2023-03-30', '2023-10-01'),
    2024: ('2024-03-28', '2024-09-29'),
    2025: ('2025-03-27', '2025-09-28'),
}


def get_all_expected_dates() -> List[str]:
    """Get all dates that should have data (within season boundaries)."""
    dates = []

    for season, (start, end) in MLB_SEASONS.items():
        start_date = datetime.strptime(start, '%Y-%m-%d')
        end_date = datetime.strptime(end, '%Y-%m-%d')

        current = start_date
        while current <= end_date:
            dates.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)

    return dates


def scan_gcs_files(bucket) -> Dict[int, Dict[str, dict]]:
    """Scan GCS and return completed files by market."""
    results = defaultdict(dict)

    for market_id, market_name in MLB_MARKETS.items():
        prefix = f"{GCS_PREFIX}/{market_name}/"

        try:
            blobs = bucket.list_blobs(prefix=prefix)
            for blob in blobs:
                parts = blob.name.split('/')
                if len(parts) >= 4 and parts[-1] == 'props.json':
                    date = parts[-2]
                    results[market_id][date] = {
                        'path': blob.name,
                        'size': blob.size,
                        'updated': blob.updated,
                    }
        except Exception as e:
            print(f"Error scanning {market_name}: {e}")

    return dict(results)


def get_props_count(bucket, blob_path: str) -> int:
    """Get props count from a GCS file."""
    try:
        blob = bucket.blob(blob_path)
        content = blob.download_as_string()
        data = json.loads(content)
        return data.get('meta', {}).get('total_props', 0)
    except Exception:
        return -1


def main():
    parser = argparse.ArgumentParser(description='Check MLB BettingPros backfill progress')
    parser.add_argument('--market_id', type=int, help='Show details for specific market')
    parser.add_argument('--show-missing', action='store_true', help='Show missing dates')
    parser.add_argument('--sample-props', action='store_true', help='Sample prop counts from files')
    args = parser.parse_args()

    # Initialize GCS
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(BUCKET_NAME)

    print("=" * 75)
    print("MLB BETTINGPROS BACKFILL PROGRESS")
    print("=" * 75)
    print()

    # Get expected dates
    expected_dates = set(get_all_expected_dates())
    print(f"Expected total dates: {len(expected_dates)}")
    print()

    # Scan GCS
    print("Scanning GCS for completed files...")
    completed = scan_gcs_files(bucket)
    print()

    # Calculate totals
    total_files = sum(len(dates) for dates in completed.values())
    total_expected = len(expected_dates) * len(MLB_MARKETS)

    # Per-market summary
    print(f"{'Market':<30} | {'Complete':<12} | {'Props':<10} | {'Status':<10}")
    print("-" * 75)

    total_props = 0
    for market_id in sorted(MLB_MARKETS.keys()):
        market_name = MLB_MARKETS[market_id]
        market_dates = completed.get(market_id, {})
        complete_count = len(market_dates)

        # Sample props count if requested
        if args.sample_props and market_dates:
            sample_date = list(market_dates.keys())[0]
            props = get_props_count(bucket, market_dates[sample_date]['path'])
            props_str = f"~{props}" if props >= 0 else "?"
        else:
            props_str = "-"

        pct = (complete_count / len(expected_dates) * 100) if expected_dates else 0

        if pct >= 100:
            status = "DONE"
        elif pct >= 50:
            status = f"{pct:.0f}%"
        elif pct > 0:
            status = f"{pct:.0f}%"
        else:
            status = "NOT STARTED"

        is_pitcher = market_id in PITCHER_MARKETS
        category = "P" if is_pitcher else "B"

        print(f"[{category}] {market_name:<26} | {complete_count:>5}/{len(expected_dates):<5} | {props_str:<10} | {status}")

    print("-" * 75)
    overall_pct = (total_files / total_expected * 100) if total_expected > 0 else 0
    print(f"{'TOTAL':<30} | {total_files:>5}/{total_expected:<5} | {'-':<10} | {overall_pct:.1f}%")
    print()

    # Show missing dates for specific market
    if args.market_id:
        market_id = args.market_id
        if market_id not in MLB_MARKETS:
            print(f"Unknown market_id: {market_id}")
            return

        market_name = MLB_MARKETS[market_id]
        market_dates = set(completed.get(market_id, {}).keys())
        missing = sorted(expected_dates - market_dates)

        print(f"\nDetails for {market_name} ({market_id}):")
        print(f"  Complete: {len(market_dates)}")
        print(f"  Missing: {len(missing)}")

        if args.show_missing and missing:
            print(f"\n  Missing dates (first 20):")
            for date in missing[:20]:
                print(f"    - {date}")
            if len(missing) > 20:
                print(f"    ... and {len(missing) - 20} more")

    # Show overall missing summary
    if args.show_missing and not args.market_id:
        print("\nMissing dates summary by market:")
        for market_id in sorted(MLB_MARKETS.keys()):
            market_name = MLB_MARKETS[market_id]
            market_dates = set(completed.get(market_id, {}).keys())
            missing = expected_dates - market_dates
            if missing:
                # Group by year
                years = defaultdict(int)
                for date in missing:
                    years[date[:4]] += 1
                year_str = ", ".join(f"{y}:{c}" for y, c in sorted(years.items()))
                print(f"  {market_name}: {len(missing)} missing ({year_str})")


if __name__ == "__main__":
    main()

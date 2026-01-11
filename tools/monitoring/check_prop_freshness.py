#!/usr/bin/env python3
"""
Prop Data Freshness Monitor

Checks prop line data freshness in both GCS and BigQuery.
Designed to catch prop data gaps early before they affect predictions.

Usage:
    # Check current status
    python tools/monitoring/check_prop_freshness.py

    # Check specific date range
    python tools/monitoring/check_prop_freshness.py --start-date 2025-12-01 --end-date 2025-12-10

    # JSON output for integration
    python tools/monitoring/check_prop_freshness.py --output json

Created: 2026-01-11
Purpose: Prevent prop data gaps from going undetected (like Oct-Dec 2025 incident)
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from google.cloud import bigquery


def get_bq_prop_coverage(bq_client: bigquery.Client, start_date: str, end_date: str) -> List[Dict]:
    """Get prop line coverage from BigQuery by date."""
    query = f"""
    WITH dates AS (
      SELECT CAST(day AS DATE) as game_date
      FROM UNNEST(GENERATE_DATE_ARRAY('{start_date}', '{end_date}')) as day
    ),
    props AS (
      SELECT
        game_date,
        COUNT(*) as records,
        COUNT(DISTINCT player_lookup) as players,
        COUNT(DISTINCT game_id) as games,
        COUNT(DISTINCT bookmaker) as bookmakers,
        MAX(snapshot_timestamp) as latest_snapshot
      FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
      WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      GROUP BY game_date
    )
    SELECT
      d.game_date,
      COALESCE(p.records, 0) as records,
      COALESCE(p.players, 0) as players,
      COALESCE(p.games, 0) as games,
      COALESCE(p.bookmakers, 0) as bookmakers,
      p.latest_snapshot,
      CASE
        WHEN p.records IS NULL THEN 'MISSING'
        WHEN p.players < 50 THEN 'LOW_COVERAGE'
        ELSE 'OK'
      END as status
    FROM dates d
    LEFT JOIN props p ON d.game_date = p.game_date
    ORDER BY d.game_date
    """

    result = bq_client.query(query).result()
    return [dict(row) for row in result]


def get_gcs_prop_dates(start_date: str, end_date: str) -> List[str]:
    """Get dates with data in GCS."""
    result = subprocess.run(
        ["gsutil", "ls", "gs://nba-scraped-data/odds-api/player-props/"],
        capture_output=True,
        text=True
    )

    dates = []
    for line in result.stdout.strip().split('\n'):
        if line and '/' in line:
            # Extract date from path like gs://bucket/odds-api/player-props/2025-11-14/
            parts = line.rstrip('/').split('/')
            if len(parts) >= 4:
                date_str = parts[-1]
                if date_str >= start_date and date_str <= end_date:
                    dates.append(date_str)

    return sorted(dates)


def check_prop_freshness(
    start_date: str,
    end_date: str,
    output_format: str = "text"
) -> Dict:
    """
    Check prop data freshness and identify gaps.

    Returns:
        Dict with status, summary, and detailed results
    """
    bq_client = bigquery.Client(project="nba-props-platform")

    # Get BigQuery coverage
    bq_coverage = get_bq_prop_coverage(bq_client, start_date, end_date)

    # Get GCS dates
    gcs_dates = set(get_gcs_prop_dates(start_date, end_date))

    # Analyze results
    missing_in_bq = []
    low_coverage = []
    ok_dates = []
    gcs_not_in_bq = []

    for row in bq_coverage:
        date_str = row['game_date'].strftime('%Y-%m-%d') if hasattr(row['game_date'], 'strftime') else str(row['game_date'])

        if row['status'] == 'MISSING':
            missing_in_bq.append(date_str)
            if date_str in gcs_dates:
                gcs_not_in_bq.append(date_str)
        elif row['status'] == 'LOW_COVERAGE':
            low_coverage.append(date_str)
        else:
            ok_dates.append(date_str)

    # Calculate overall status
    total_dates = len(bq_coverage)
    missing_count = len(missing_in_bq)

    if missing_count == 0:
        overall_status = "OK"
    elif missing_count / total_dates < 0.1:
        overall_status = "WARNING"
    else:
        overall_status = "CRITICAL"

    result = {
        "status": overall_status,
        "date_range": {"start": start_date, "end": end_date},
        "summary": {
            "total_dates": total_dates,
            "ok_dates": len(ok_dates),
            "missing_dates": missing_count,
            "low_coverage_dates": len(low_coverage),
            "gcs_not_in_bq": len(gcs_not_in_bq),  # Data exists in GCS but not loaded
        },
        "issues": {
            "missing_in_bq": missing_in_bq,
            "low_coverage": low_coverage,
            "gcs_not_in_bq": gcs_not_in_bq,  # Action needed: run processor
        },
        "detailed_coverage": bq_coverage if output_format == "json" else None,
    }

    return result


def print_text_report(result: Dict) -> None:
    """Print human-readable report."""
    print("\n" + "=" * 60)
    print("PROP DATA FRESHNESS REPORT")
    print("=" * 60)
    print(f"\nDate Range: {result['date_range']['start']} to {result['date_range']['end']}")
    print(f"Status: {result['status']}")

    summary = result['summary']
    print(f"\nSummary:")
    print(f"  Total dates checked:  {summary['total_dates']}")
    print(f"  OK:                   {summary['ok_dates']}")
    print(f"  Missing in BigQuery:  {summary['missing_dates']}")
    print(f"  Low coverage:         {summary['low_coverage_dates']}")
    print(f"  In GCS, not in BQ:    {summary['gcs_not_in_bq']}")

    issues = result['issues']

    if issues['gcs_not_in_bq']:
        print(f"\n⚠️  ACTION NEEDED: Data in GCS but not loaded to BigQuery:")
        for date in issues['gcs_not_in_bq'][:10]:
            print(f"    - {date}")
        if len(issues['gcs_not_in_bq']) > 10:
            print(f"    ... and {len(issues['gcs_not_in_bq']) - 10} more")
        print("\n  Fix: Run the props processor backfill:")
        print("    python scripts/backfill_odds_api_props.py \\")
        print(f"      --start-date {issues['gcs_not_in_bq'][0]} \\")
        print(f"      --end-date {issues['gcs_not_in_bq'][-1]}")

    if issues['missing_in_bq'] and not issues['gcs_not_in_bq']:
        print(f"\n❌  MISSING DATA (not in GCS either - may need historical scrape):")
        for date in issues['missing_in_bq'][:10]:
            print(f"    - {date}")

    if issues['low_coverage']:
        print(f"\n⚠️  LOW COVERAGE (<50 players):")
        for date in issues['low_coverage'][:5]:
            print(f"    - {date}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Check prop data freshness")
    parser.add_argument(
        "--start-date",
        default=(datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'),
        help="Start date (YYYY-MM-DD), default: 7 days ago"
    )
    parser.add_argument(
        "--end-date",
        default=datetime.now().strftime('%Y-%m-%d'),
        help="End date (YYYY-MM-DD), default: today"
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format"
    )
    args = parser.parse_args()

    result = check_prop_freshness(args.start_date, args.end_date, args.output)

    if args.output == "json":
        # Convert dates in detailed_coverage to strings
        if result.get('detailed_coverage'):
            for row in result['detailed_coverage']:
                if hasattr(row.get('game_date'), 'strftime'):
                    row['game_date'] = row['game_date'].strftime('%Y-%m-%d')
                if row.get('latest_snapshot'):
                    row['latest_snapshot'] = row['latest_snapshot'].isoformat()
        print(json.dumps(result, indent=2, default=str))
    else:
        print_text_report(result)

    # Return exit code based on status
    return 0 if result['status'] == 'OK' else 1


if __name__ == "__main__":
    sys.exit(main())

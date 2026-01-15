#!/usr/bin/env python3
"""
Live System Health Check

Checks for downtime and gaps in the live scoring system.
Run this at the end of the day to verify data collection was complete.

Usage:
    python scripts/check_live_system_health.py
    python scripts/check_live_system_health.py --date 2026-01-14
    python scripts/check_live_system_health.py --days 7

Features:
- Detects gaps in live boxscores collection
- Shows coverage during game hours
- Calculates uptime percentage
- Identifies missing game data

Created: 2026-01-15 (Session 48)
"""

import argparse
import sys
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict
from google.cloud import bigquery
from zoneinfo import ZoneInfo

# Game hours in ET (4 PM - 1 AM)
GAME_HOURS_START = 16  # 4 PM ET
GAME_HOURS_END = 25    # 1 AM ET (next day)
EXPECTED_RUN_INTERVAL_MINUTES = 5  # Expected max gap between runs
GAP_THRESHOLD_MINUTES = 15  # Alert if gap exceeds this


def get_et_now():
    """Get current time in ET."""
    return datetime.now(ZoneInfo('America/New_York'))


def check_live_processor_gaps(
    bq_client: bigquery.Client,
    target_date: str,
    gap_threshold: int = GAP_THRESHOLD_MINUTES
) -> Dict:
    """
    Check for gaps in live processor runs for a specific date.

    Returns:
        Dict with gap analysis results
    """
    query = f"""
    WITH runs AS (
      SELECT
        started_at,
        LAG(started_at) OVER (ORDER BY started_at) as prev_run,
        status,
        records_processed,
        duration_seconds
      FROM nba_reference.processor_run_history
      WHERE processor_name = 'BdlLiveBoxscoresProcessor'
        AND DATE(started_at, 'America/New_York') = '{target_date}'
        AND status = 'success'
    ),
    gaps AS (
      SELECT
        started_at,
        prev_run,
        TIMESTAMP_DIFF(started_at, prev_run, MINUTE) as gap_minutes,
        records_processed
      FROM runs
      WHERE prev_run IS NOT NULL
    )
    SELECT
      started_at,
      prev_run,
      gap_minutes,
      records_processed
    FROM gaps
    WHERE gap_minutes > {gap_threshold}
    ORDER BY gap_minutes DESC
    """

    results = list(bq_client.query(query).result())

    return {
        'gaps_over_threshold': len(results),
        'threshold_minutes': gap_threshold,
        'gaps': [
            {
                'started_at': str(row.started_at),
                'prev_run': str(row.prev_run),
                'gap_minutes': row.gap_minutes,
                'records': row.records_processed
            }
            for row in results
        ]
    }


def get_run_summary(bq_client: bigquery.Client, target_date: str) -> Dict:
    """
    Get summary of live processor runs for a date.
    """
    query = f"""
    SELECT
      COUNT(*) as total_runs,
      COUNTIF(status = 'success') as success_runs,
      COUNTIF(status = 'failed') as failed_runs,
      MIN(started_at) as first_run,
      MAX(started_at) as last_run,
      ROUND(AVG(CASE WHEN status = 'success' THEN records_processed END), 0) as avg_records,
      SUM(CASE WHEN status = 'success' THEN records_processed ELSE 0 END) as total_records
    FROM nba_reference.processor_run_history
    WHERE processor_name = 'BdlLiveBoxscoresProcessor'
      AND DATE(started_at, 'America/New_York') = '{target_date}'
    """

    result = list(bq_client.query(query).result())[0]

    return {
        'total_runs': result.total_runs or 0,
        'success_runs': result.success_runs or 0,
        'failed_runs': result.failed_runs or 0,
        'first_run': str(result.first_run) if result.first_run else None,
        'last_run': str(result.last_run) if result.last_run else None,
        'avg_records': int(result.avg_records) if result.avg_records else 0,
        'total_records': result.total_records or 0
    }


def get_game_info(bq_client: bigquery.Client, target_date: str) -> Dict:
    """
    Get game info for a date to correlate with collection.
    """
    query = f"""
    SELECT
      COUNT(*) as games_scheduled,
      MIN(game_date_est) as first_game,
      MAX(game_date_est) as last_game
    FROM nba_raw.nbac_schedule
    WHERE game_date = '{target_date}'
    """

    result = list(bq_client.query(query).result())[0]

    return {
        'games_scheduled': result.games_scheduled or 0,
        'first_game': str(result.first_game) if result.first_game else None,
        'last_game': str(result.last_game) if result.last_game else None
    }


def calculate_uptime(gaps: List[Dict], game_hours: int = 9) -> float:
    """
    Calculate uptime percentage based on gaps.

    Args:
        gaps: List of gap info dicts
        game_hours: Total expected game hours (default 9 = 4PM-1AM)

    Returns:
        Uptime percentage (0-100)
    """
    total_minutes = game_hours * 60
    downtime_minutes = sum(g['gap_minutes'] for g in gaps)

    if total_minutes == 0:
        return 100.0

    uptime = max(0, (total_minutes - downtime_minutes) / total_minutes * 100)
    return round(uptime, 1)


def check_live_boxscores_data(bq_client: bigquery.Client, target_date: str) -> Dict:
    """
    Check actual live boxscores data collected.
    """
    query = f"""
    SELECT
      COUNT(*) as total_records,
      COUNT(DISTINCT game_id) as games_covered,
      COUNT(DISTINCT player_lookup) as players_covered,
      MIN(processed_at) as first_poll,
      MAX(processed_at) as last_poll,
      COUNT(DISTINCT DATE_TRUNC(processed_at, HOUR)) as hours_with_data
    FROM nba_raw.bdl_live_boxscores
    WHERE game_date = '{target_date}'
    """

    result = list(bq_client.query(query).result())[0]

    return {
        'total_records': result.total_records or 0,
        'games_covered': result.games_covered or 0,
        'players_covered': result.players_covered or 0,
        'first_poll': str(result.first_poll) if result.first_poll else None,
        'last_poll': str(result.last_poll) if result.last_poll else None,
        'hours_with_data': result.hours_with_data or 0
    }


def print_report(
    target_date: str,
    summary: Dict,
    gaps: Dict,
    games: Dict,
    data: Dict,
    uptime: float
):
    """Print formatted health report."""
    print("\n" + "=" * 60)
    print(f"🏀 LIVE SYSTEM HEALTH REPORT - {target_date}")
    print("=" * 60)

    # Uptime
    status_emoji = "✅" if uptime >= 95 else "⚠️" if uptime >= 80 else "❌"
    print(f"\n{status_emoji} UPTIME: {uptime}%")

    # Games
    print(f"\n📅 GAMES:")
    print(f"   Scheduled: {games['games_scheduled']}")
    if games['first_game']:
        print(f"   First game: {games['first_game']}")
    if games['last_game']:
        print(f"   Last game: {games['last_game']}")

    # Processor Runs
    print(f"\n⚙️  PROCESSOR RUNS:")
    print(f"   Total: {summary['total_runs']}")
    print(f"   Success: {summary['success_runs']}")
    print(f"   Failed: {summary['failed_runs']}")
    if summary['first_run']:
        print(f"   First run: {summary['first_run']}")
    if summary['last_run']:
        print(f"   Last run: {summary['last_run']}")
    print(f"   Avg records/run: {summary['avg_records']}")

    # Data Collected
    print(f"\n📊 DATA COLLECTED:")
    print(f"   Total records: {data['total_records']:,}")
    print(f"   Games covered: {data['games_covered']}")
    print(f"   Players tracked: {data['players_covered']}")
    print(f"   Hours with data: {data['hours_with_data']}")

    # Gaps
    if gaps['gaps']:
        print(f"\n⚠️  GAPS DETECTED (>{gaps['threshold_minutes']} min):")
        for g in gaps['gaps'][:5]:  # Show top 5
            print(f"   • {g['gap_minutes']} min gap: {g['prev_run']} → {g['started_at']}")
        if len(gaps['gaps']) > 5:
            print(f"   ... and {len(gaps['gaps']) - 5} more gaps")
    else:
        print(f"\n✅ NO SIGNIFICANT GAPS (>{gaps['threshold_minutes']} min)")

    # Summary
    print("\n" + "-" * 60)
    if uptime >= 95 and gaps['gaps_over_threshold'] == 0:
        print("✅ HEALTHY: Live system performed well today")
    elif uptime >= 80:
        print("⚠️  WARNING: Some gaps detected, data may be incomplete")
    else:
        print("❌ CRITICAL: Significant downtime, investigate logs")

    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description='Check live system health')
    parser.add_argument('--date', help='Target date (YYYY-MM-DD)', default=None)
    parser.add_argument('--days', type=int, help='Check last N days', default=1)
    parser.add_argument('--gap-threshold', type=int, default=GAP_THRESHOLD_MINUTES,
                        help=f'Gap threshold in minutes (default: {GAP_THRESHOLD_MINUTES})')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    bq_client = bigquery.Client()

    # Determine dates to check
    if args.date:
        dates = [args.date]
    else:
        today = get_et_now().date()
        dates = [(today - timedelta(days=i)).isoformat() for i in range(args.days)]

    all_results = []

    for target_date in dates:
        # Gather data
        summary = get_run_summary(bq_client, target_date)
        gaps = check_live_processor_gaps(bq_client, target_date, args.gap_threshold)
        games = get_game_info(bq_client, target_date)
        data = check_live_boxscores_data(bq_client, target_date)
        uptime = calculate_uptime(gaps['gaps'])

        result = {
            'date': target_date,
            'uptime_pct': uptime,
            'summary': summary,
            'gaps': gaps,
            'games': games,
            'data': data
        }
        all_results.append(result)

        if not args.json:
            print_report(target_date, summary, gaps, games, data, uptime)

    if args.json:
        import json
        print(json.dumps(all_results, indent=2, default=str))

    # Exit with error code if any day had issues
    if any(r['uptime_pct'] < 80 for r in all_results):
        sys.exit(2)  # Critical
    elif any(r['uptime_pct'] < 95 for r in all_results):
        sys.exit(1)  # Warning
    sys.exit(0)  # Healthy


if __name__ == '__main__':
    main()

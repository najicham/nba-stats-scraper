#!/usr/bin/env python3
"""
Cascade Detection Tool for Historical Completeness

Finds features that would be affected by backfilling a specific date,
or finds incomplete features in a date range.

This tool is part of the Data Cascade Architecture and uses the
historical_completeness metadata stored in ml_feature_store_v2.

Usage:
    # Find features affected by backfilling a specific date
    python bin/check_cascade.py --backfill-date 2026-01-01

    # Find incomplete features in a date range
    python bin/check_cascade.py --incomplete --start 2026-01-01 --end 2026-01-21

    # Show daily completeness summary (last 30 days)
    python bin/check_cascade.py --summary

    # Show daily completeness summary with custom days
    python bin/check_cascade.py --summary --days 7

    # Output as JSON (for scripting)
    python bin/check_cascade.py --backfill-date 2026-01-01 --json

    # Dry run - show SQL without executing
    python bin/check_cascade.py --backfill-date 2026-01-01 --dry-run

Created: January 22, 2026
Architecture: Data Cascade Architecture Project
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_bq_client():
    """Get BigQuery client."""
    from google.cloud import bigquery
    return bigquery.Client()


def find_affected_by_backfill(backfill_date: date, forward_days: int = 21, dry_run: bool = False) -> Dict:
    """
    Find features affected by backfilling a specific date.

    After backfilling data for a date, features that used that date in their
    rolling window calculation may need to be reprocessed.

    Args:
        backfill_date: The date that was/will be backfilled
        forward_days: How many days forward to look (default: 21)
        dry_run: If True, just return the SQL without executing

    Returns:
        Dict with affected features and counts
    """
    query = f"""
    -- Find features affected by backfilling {backfill_date}
    SELECT
        game_date,
        player_lookup,
        historical_completeness.games_found,
        historical_completeness.games_expected,
        historical_completeness.is_complete,
        historical_completeness.is_bootstrap
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE DATE('{backfill_date}') IN UNNEST(historical_completeness.contributing_game_dates)
      AND game_date > DATE('{backfill_date}')
      AND game_date <= DATE_ADD(DATE('{backfill_date}'), INTERVAL {forward_days} DAY)
    ORDER BY game_date, player_lookup
    """

    if dry_run:
        return {'sql': query, 'affected': [], 'count': 0}

    client = get_bq_client()
    result = client.query(query).to_dataframe()

    affected = []
    for _, row in result.iterrows():
        affected.append({
            'game_date': str(row['game_date']),
            'player_lookup': row['player_lookup'],
            'games_found': int(row['games_found']) if row['games_found'] else 0,
            'games_expected': int(row['games_expected']) if row['games_expected'] else 0,
            'is_complete': bool(row['is_complete']),
            'is_bootstrap': bool(row['is_bootstrap'])
        })

    return {
        'backfill_date': str(backfill_date),
        'forward_days': forward_days,
        'affected': affected,
        'count': len(affected),
        'unique_dates': len(set(a['game_date'] for a in affected)),
        'unique_players': len(set(a['player_lookup'] for a in affected))
    }


def find_incomplete_features(start_date: date, end_date: date, dry_run: bool = False) -> Dict:
    """
    Find incomplete features (data gaps, not bootstrap) in a date range.

    Args:
        start_date: Start of date range
        end_date: End of date range
        dry_run: If True, just return the SQL without executing

    Returns:
        Dict with incomplete features
    """
    query = f"""
    -- Find incomplete features (not bootstrap) in date range
    SELECT
        game_date,
        player_lookup,
        historical_completeness.games_found,
        historical_completeness.games_expected,
        historical_completeness.games_expected - historical_completeness.games_found as games_missing
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE game_date BETWEEN DATE('{start_date}') AND DATE('{end_date}')
      AND NOT historical_completeness.is_complete
      AND NOT historical_completeness.is_bootstrap
      AND historical_completeness IS NOT NULL
    ORDER BY game_date DESC, games_missing DESC
    """

    if dry_run:
        return {'sql': query, 'incomplete': [], 'count': 0}

    client = get_bq_client()
    result = client.query(query).to_dataframe()

    incomplete = []
    for _, row in result.iterrows():
        incomplete.append({
            'game_date': str(row['game_date']),
            'player_lookup': row['player_lookup'],
            'games_found': int(row['games_found']) if row['games_found'] else 0,
            'games_expected': int(row['games_expected']) if row['games_expected'] else 0,
            'games_missing': int(row['games_missing']) if row['games_missing'] else 0
        })

    return {
        'start_date': str(start_date),
        'end_date': str(end_date),
        'incomplete': incomplete,
        'count': len(incomplete),
        'unique_dates': len(set(i['game_date'] for i in incomplete)),
        'unique_players': len(set(i['player_lookup'] for i in incomplete)),
        'total_games_missing': sum(i['games_missing'] for i in incomplete)
    }


def get_daily_summary(days_back: int = 30, dry_run: bool = False) -> Dict:
    """
    Get daily completeness summary.

    Args:
        days_back: Number of days to look back
        dry_run: If True, just return the SQL without executing

    Returns:
        Dict with daily summary
    """
    query = f"""
    SELECT
        game_date,
        COUNT(*) as total_features,
        COUNTIF(historical_completeness.is_complete) as complete,
        COUNTIF(NOT historical_completeness.is_complete AND NOT historical_completeness.is_bootstrap) as incomplete,
        COUNTIF(historical_completeness.is_bootstrap) as bootstrap,
        ROUND(COUNTIF(historical_completeness.is_complete) / COUNT(*) * 100, 1) as complete_pct
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days_back} DAY)
      AND historical_completeness IS NOT NULL
    GROUP BY game_date
    ORDER BY game_date DESC
    """

    if dry_run:
        return {'sql': query, 'daily': [], 'count': 0}

    client = get_bq_client()
    result = client.query(query).to_dataframe()

    daily = []
    for _, row in result.iterrows():
        daily.append({
            'game_date': str(row['game_date']),
            'total_features': int(row['total_features']),
            'complete': int(row['complete']),
            'incomplete': int(row['incomplete']),
            'bootstrap': int(row['bootstrap']),
            'complete_pct': float(row['complete_pct'])
        })

    return {
        'days_back': days_back,
        'daily': daily,
        'count': len(daily)
    }


def parse_date(date_str: str) -> date:
    """Parse date string to date object."""
    if date_str.lower() == 'today':
        return date.today()
    elif date_str.lower() == 'yesterday':
        return date.today() - timedelta(days=1)
    else:
        return datetime.strptime(date_str, '%Y-%m-%d').date()


def format_terminal_output(result: Dict, mode: str) -> str:
    """Format result for terminal output."""
    lines = []

    if mode == 'backfill':
        lines.append(f"\n{'='*60}")
        lines.append(f"CASCADE DETECTION: Features affected by backfilling {result['backfill_date']}")
        lines.append(f"{'='*60}")
        lines.append(f"Forward window: {result['forward_days']} days")
        lines.append(f"Total affected: {result['count']} features")
        lines.append(f"Unique dates: {result['unique_dates']}")
        lines.append(f"Unique players: {result['unique_players']}")

        if result['affected']:
            lines.append(f"\n{'Date':<12} {'Player':<30} {'Games':<10} {'Status':<12}")
            lines.append("-" * 64)
            for a in result['affected'][:20]:  # Show first 20
                status = "COMPLETE" if a['is_complete'] else ("BOOTSTRAP" if a['is_bootstrap'] else "INCOMPLETE")
                games = f"{a['games_found']}/{a['games_expected']}"
                lines.append(f"{a['game_date']:<12} {a['player_lookup']:<30} {games:<10} {status:<12}")

            if len(result['affected']) > 20:
                lines.append(f"... and {len(result['affected']) - 20} more")

    elif mode == 'incomplete':
        lines.append(f"\n{'='*60}")
        lines.append(f"INCOMPLETE FEATURES: {result['start_date']} to {result['end_date']}")
        lines.append(f"{'='*60}")
        lines.append(f"Total incomplete: {result['count']} features")
        lines.append(f"Unique dates: {result['unique_dates']}")
        lines.append(f"Unique players: {result['unique_players']}")
        lines.append(f"Total games missing: {result['total_games_missing']}")

        if result['incomplete']:
            lines.append(f"\n{'Date':<12} {'Player':<30} {'Games':<10} {'Missing':<8}")
            lines.append("-" * 60)
            for i in result['incomplete'][:20]:  # Show first 20
                games = f"{i['games_found']}/{i['games_expected']}"
                lines.append(f"{i['game_date']:<12} {i['player_lookup']:<30} {games:<10} {i['games_missing']:<8}")

            if len(result['incomplete']) > 20:
                lines.append(f"... and {len(result['incomplete']) - 20} more")

    elif mode == 'summary':
        lines.append(f"\n{'='*60}")
        lines.append(f"DAILY COMPLETENESS SUMMARY (Last {result['days_back']} days)")
        lines.append(f"{'='*60}")

        if result['daily']:
            lines.append(f"\n{'Date':<12} {'Total':<8} {'Complete':<10} {'Incomplete':<12} {'Bootstrap':<10} {'%':<6}")
            lines.append("-" * 58)
            for d in result['daily']:
                lines.append(
                    f"{d['game_date']:<12} {d['total_features']:<8} "
                    f"{d['complete']:<10} {d['incomplete']:<12} {d['bootstrap']:<10} {d['complete_pct']:<6.1f}"
                )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Cascade Detection Tool for Historical Completeness',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Find features affected by backfilling a specific date
    python bin/check_cascade.py --backfill-date 2026-01-01

    # Find incomplete features in a date range
    python bin/check_cascade.py --incomplete --start 2026-01-01 --end 2026-01-21

    # Show daily completeness summary
    python bin/check_cascade.py --summary

    # Output as JSON
    python bin/check_cascade.py --backfill-date 2026-01-01 --json
        """
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--backfill-date', '-b', type=str,
                           help='Find features affected by backfilling this date (YYYY-MM-DD)')
    mode_group.add_argument('--incomplete', '-i', action='store_true',
                           help='Find incomplete features in date range')
    mode_group.add_argument('--summary', '-s', action='store_true',
                           help='Show daily completeness summary')

    # Options
    parser.add_argument('--start', type=str, help='Start date for incomplete mode (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End date for incomplete mode (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, default=30, help='Days to look back for summary (default: 30)')
    parser.add_argument('--forward-days', type=int, default=21,
                       help='Forward window for backfill mode (default: 21)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--dry-run', action='store_true', help='Show SQL without executing')

    args = parser.parse_args()

    try:
        if args.backfill_date:
            backfill_date = parse_date(args.backfill_date)
            result = find_affected_by_backfill(backfill_date, args.forward_days, args.dry_run)
            mode = 'backfill'

        elif args.incomplete:
            if not args.start or not args.end:
                # Default to last 30 days
                end_date = date.today()
                start_date = end_date - timedelta(days=30)
            else:
                start_date = parse_date(args.start)
                end_date = parse_date(args.end)

            result = find_incomplete_features(start_date, end_date, args.dry_run)
            mode = 'incomplete'

        elif args.summary:
            result = get_daily_summary(args.days, args.dry_run)
            mode = 'summary'

        # Output
        if args.dry_run:
            print("\n" + "="*60)
            print("DRY RUN - SQL Query:")
            print("="*60)
            print(result['sql'])
        elif args.json:
            print(json.dumps(result, indent=2))
        else:
            print(format_terminal_output(result, mode))

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

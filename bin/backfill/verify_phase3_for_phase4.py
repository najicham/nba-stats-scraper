#!/usr/bin/env python3
"""
Phase 3 Verification for Phase 4 Backfill Readiness

Verifies that Phase 3 data is complete and ready before running Phase 4 backfills.
Checks all 5 Phase 3 analytics tables for coverage in the requested date range.

Usage:
    # Check Phase 3 readiness for full 4-year backfill
    python bin/backfill/verify_phase3_for_phase4.py --start-date 2021-10-19 --end-date 2025-06-22

    # Check specific date range
    python bin/backfill/verify_phase3_for_phase4.py --start-date 2024-01-01 --end-date 2024-03-31

    # Verbose output (show missing dates)
    python bin/backfill/verify_phase3_for_phase4.py --start-date 2024-01-01 --end-date 2024-03-31 --verbose
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple

# Add parent directories to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.cloud import bigquery
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# Phase 3 tables that Phase 4 depends on
PHASE3_TABLES = {
    'player_game_summary': {
        'table': 'nba-props-platform.nba_analytics.player_game_summary',
        'date_field': 'game_date',
        'description': 'Player performance data',
        'required_by': ['All Phase 4 processors']
    },
    'team_defense_game_summary': {
        'table': 'nba-props-platform.nba_analytics.team_defense_game_summary',
        'date_field': 'game_date',
        'description': 'Team defensive stats',
        'required_by': ['team_defense_zone_analysis']
    },
    'team_offense_game_summary': {
        'table': 'nba-props-platform.nba_analytics.team_offense_game_summary',
        'date_field': 'game_date',
        'description': 'Team offensive stats',
        'required_by': ['player_daily_cache']
    },
    'upcoming_player_game_context': {
        'table': 'nba-props-platform.nba_analytics.upcoming_player_game_context',
        'date_field': 'game_date',
        'description': 'Player game context with prop lines',
        'required_by': ['player_composite_factors']
    },
    'upcoming_team_game_context': {
        'table': 'nba-props-platform.nba_analytics.upcoming_team_game_context',
        'date_field': 'game_date',
        'description': 'Team game context with betting lines',
        'required_by': ['player_composite_factors']
    }
}


def is_bootstrap_date(check_date: date) -> bool:
    """Check if date falls within bootstrap period (first 14 days of season)."""
    season_year = get_season_year_from_date(check_date)
    return is_early_season(check_date, season_year)  # Uses default BOOTSTRAP_DAYS=14


def get_dates_with_data(bq_client: bigquery.Client, table: str, date_field: str,
                        start_date: date, end_date: date) -> set:
    """Get all dates that have data in a table."""
    query = f"""
    SELECT DISTINCT {date_field} as data_date
    FROM `{table}`
    WHERE {date_field} >= '{start_date}'
      AND {date_field} <= '{end_date}'
    ORDER BY data_date
    """

    try:
        result = bq_client.query(query).to_dataframe()
        if result.empty:
            return set()
        # Handle both datetime and date types from BigQuery
        dates = result['data_date']
        if hasattr(dates.iloc[0], 'date'):
            # datetime type - extract date
            return set(d.date() for d in dates)
        else:
            # Already date type or string - convert
            import pandas as pd
            return set(pd.to_datetime(dates).dt.date)
    except Exception as e:
        logger.error(f"Error querying {table}: {e}", exc_info=True)
        return set()


def get_expected_game_dates(bq_client: bigquery.Client, start_date: date, end_date: date) -> set:
    """Get all dates that should have games from schedule or actual data."""
    # Try schedule table first (may not exist in all regions)
    schedule_query = f"""
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_reference.nba_schedule`
    WHERE game_date >= '{start_date}'
      AND game_date <= '{end_date}'
      AND season_type IN ('Regular Season', 'Playoffs')
    ORDER BY game_date
    """

    try:
        result = bq_client.query(schedule_query).to_dataframe()
        if not result.empty:
            dates = result['game_date']
            if hasattr(dates.iloc[0], 'date'):
                return set(d.date() for d in dates)
            else:
                import pandas as pd
                return set(pd.to_datetime(dates).dt.date)
    except Exception as e:
        logger.error(f"Error querying schedule: {e}", exc_info=True)

    # Fallback: Get dates from player_game_summary (authoritative source)
    logger.info("Falling back to player_game_summary for expected dates")
    fallback_query = f"""
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= '{start_date}'
      AND game_date <= '{end_date}'
    ORDER BY game_date
    """

    try:
        result = bq_client.query(fallback_query).to_dataframe()
        if result.empty:
            return set()
        dates = result['game_date']
        if hasattr(dates.iloc[0], 'date'):
            return set(d.date() for d in dates)
        else:
            import pandas as pd
            return set(pd.to_datetime(dates).dt.date)
    except Exception as e:
        logger.error(f"Error querying player_game_summary fallback: {e}", exc_info=True)
        return set()


def verify_phase3_readiness(start_date: date, end_date: date, verbose: bool = False) -> Dict:
    """
    Verify Phase 3 data is ready for Phase 4 backfill.

    Returns:
        Dict with verification results including coverage stats and any gaps.
    """
    bq_client = bigquery.Client()

    logger.info(f"Verifying Phase 3 readiness for {start_date} to {end_date}")

    # Get expected game dates from schedule
    expected_dates = get_expected_game_dates(bq_client, start_date, end_date)

    # Filter out bootstrap dates (Phase 4 intentionally skips these)
    bootstrap_dates = {d for d in expected_dates if is_bootstrap_date(d)}
    non_bootstrap_dates = expected_dates - bootstrap_dates

    logger.info(f"Expected game dates: {len(expected_dates)}")
    logger.info(f"  Bootstrap dates (skipped): {len(bootstrap_dates)}")
    logger.info(f"  Non-bootstrap dates: {len(non_bootstrap_dates)}")

    results = {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'expected_game_dates': len(expected_dates),
        'bootstrap_dates': len(bootstrap_dates),
        'non_bootstrap_dates': len(non_bootstrap_dates),
        'tables': {}
    }

    # Check each Phase 3 table
    print(f"\n{'='*70}")
    print("PHASE 3 TABLE COVERAGE")
    print(f"{'='*70}")

    all_ready = True

    for table_name, config in PHASE3_TABLES.items():
        logger.info(f"Checking {table_name}...")

        actual_dates = get_dates_with_data(
            bq_client,
            config['table'],
            config['date_field'],
            start_date,
            end_date
        )

        # Calculate coverage (against non-bootstrap dates only)
        missing_dates = non_bootstrap_dates - actual_dates
        coverage = len(actual_dates.intersection(non_bootstrap_dates)) / len(non_bootstrap_dates) * 100 if non_bootstrap_dates else 0

        is_ready = coverage >= 95.0  # 95% threshold
        if not is_ready:
            all_ready = False

        results['tables'][table_name] = {
            'dates_with_data': len(actual_dates),
            'expected_dates': len(non_bootstrap_dates),
            'coverage_pct': coverage,
            'missing_dates': len(missing_dates),
            'is_ready': is_ready
        }

        status = "✅" if is_ready else "⚠️"
        print(f"\n{status} {table_name}")
        print(f"   Description: {config['description']}")
        print(f"   Coverage: {len(actual_dates.intersection(non_bootstrap_dates))}/{len(non_bootstrap_dates)} ({coverage:.1f}%)")
        print(f"   Missing dates: {len(missing_dates)}")
        print(f"   Required by: {', '.join(config['required_by'])}")

        if verbose and missing_dates and len(missing_dates) <= 20:
            sorted_missing = sorted(missing_dates)
            print(f"   Missing: {', '.join(str(d) for d in sorted_missing[:10])}")
            if len(sorted_missing) > 10:
                print(f"            ... and {len(sorted_missing) - 10} more")

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")

    if all_ready:
        print(f"\n✅ PHASE 3 IS READY for Phase 4 backfill")
        print(f"   All tables have >95% coverage for the requested date range.")
    else:
        print(f"\n⚠️ PHASE 3 HAS GAPS that may affect Phase 4 backfill")
        print(f"   Some tables have <95% coverage. Review details above.")
        print(f"\n   Recommendation: Run Phase 3 backfill for missing dates first.")

        # Show which tables are not ready
        not_ready = [name for name, info in results['tables'].items() if not info['is_ready']]
        if not_ready:
            print(f"\n   Tables needing attention:")
            for name in not_ready:
                info = results['tables'][name]
                print(f"     - {name}: {info['coverage_pct']:.1f}% ({info['missing_dates']} dates missing)")

    print(f"\n{'='*70}")

    results['all_ready'] = all_ready
    return results


def main():
    parser = argparse.ArgumentParser(
        description='Verify Phase 3 data is ready for Phase 4 backfill',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check full 4-year backfill readiness
  %(prog)s --start-date 2021-10-19 --end-date 2025-06-22

  # Check specific date range with verbose output
  %(prog)s --start-date 2024-01-01 --end-date 2024-03-31 --verbose

This script checks all 5 Phase 3 analytics tables that Phase 4 depends on:
  - player_game_summary
  - team_defense_game_summary
  - team_offense_game_summary
  - upcoming_player_game_context
  - upcoming_team_game_context

If coverage is <95%, consider running Phase 3 backfill before Phase 4.
        """
    )
    parser.add_argument('--start-date', type=str, required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show missing dates')

    args = parser.parse_args()

    try:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    except ValueError as e:
        logger.error(f"Invalid date format: {e}", exc_info=True)
        sys.exit(1)

    if start_date > end_date:
        logger.error("Start date must be before end date")
        sys.exit(1)

    results = verify_phase3_readiness(start_date, end_date, verbose=args.verbose)

    # Exit with error code if not ready
    sys.exit(0 if results['all_ready'] else 1)


if __name__ == "__main__":
    main()

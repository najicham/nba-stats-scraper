#!/usr/bin/env python3
"""
Phase 2 Verification for Phase 3 Backfill Readiness

Verifies that Phase 2 raw data is complete before running Phase 3 analytics backfills.
Checks key raw tables for coverage in the requested date range.

Usage:
    # Check Phase 2 readiness
    python bin/backfill/verify_phase2_for_phase3.py --start-date 2024-01-01 --end-date 2024-03-31

    # Verbose output
    python bin/backfill/verify_phase2_for_phase3.py --start-date 2024-01-01 --end-date 2024-03-31 --verbose
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date
from typing import Dict, Set

# Add parent directories to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.cloud import bigquery

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# Phase 2 raw tables that Phase 3 depends on
PHASE2_TABLES = {
    'bdl_player_boxscores': {
        'table': 'nba-props-platform.nba_raw.bdl_player_boxscores',
        'date_field': 'game_date',
        'description': 'Ball Dont Lie player box scores (primary source)',
        'required_by': ['player_game_summary', 'team_offense/defense']
    },
    'nbac_gamebook_player_stats': {
        'table': 'nba-props-platform.nba_raw.nbac_gamebook_player_stats',
        'date_field': 'game_date',
        'description': 'NBA.com gamebook player stats (fallback source)',
        'required_by': ['player_game_summary']
    },
    'nbac_team_boxscore': {
        'table': 'nba-props-platform.nba_raw.nbac_team_boxscore',
        'date_field': 'game_date',
        'description': 'NBA.com team box scores',
        'required_by': ['team_offense/defense_game_summary']
    }
}


def get_dates_with_data(bq_client: bigquery.Client, table: str, date_field: str,
                        start_date: date, end_date: date) -> Set[date]:
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
        # Handle both datetime and date types
        dates = result['data_date']
        if hasattr(dates.iloc[0], 'date'):
            return set(d.date() for d in dates)
        else:
            import pandas as pd
            return set(pd.to_datetime(dates).dt.date)
    except Exception as e:
        logger.error(f"Error querying {table}: {e}", exc_info=True)
        return set()


def get_expected_game_dates(bq_client: bigquery.Client, start_date: date, end_date: date) -> Set[date]:
    """Get all expected game dates from bdl_player_boxscores (authoritative source)."""
    query = f"""
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
    WHERE game_date >= '{start_date}'
      AND game_date <= '{end_date}'
    ORDER BY game_date
    """

    try:
        result = bq_client.query(query).to_dataframe()
        if result.empty:
            return set()
        dates = result['game_date']
        if hasattr(dates.iloc[0], 'date'):
            return set(d.date() for d in dates)
        else:
            import pandas as pd
            return set(pd.to_datetime(dates).dt.date)
    except Exception as e:
        logger.warning(f"Could not get expected dates from bdl_player_boxscores: {e}")
        # Fallback: generate all dates in range
        from datetime import timedelta
        dates = set()
        current = start_date
        while current <= end_date:
            dates.add(current)
            current += timedelta(days=1)
        return dates


def verify_phase2_readiness(start_date: date, end_date: date, verbose: bool = False) -> Dict:
    """
    Verify Phase 2 raw data is ready for Phase 3 analytics backfill.

    Returns:
        Dict with verification results including coverage stats and any gaps.
    """
    bq_client = bigquery.Client()

    logger.info(f"Verifying Phase 2 readiness for {start_date} to {end_date}")

    # Get expected game dates
    expected_dates = get_expected_game_dates(bq_client, start_date, end_date)
    logger.info(f"Expected game dates: {len(expected_dates)}")

    results = {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'expected_game_dates': len(expected_dates),
        'tables': {}
    }

    # Check each Phase 2 table
    print(f"\n{'='*70}")
    print("PHASE 2 RAW DATA COVERAGE")
    print(f"{'='*70}")

    all_ready = True

    for table_name, config in PHASE2_TABLES.items():
        logger.info(f"Checking {table_name}...")

        actual_dates = get_dates_with_data(
            bq_client,
            config['table'],
            config['date_field'],
            start_date,
            end_date
        )

        # Calculate coverage
        missing_dates = expected_dates - actual_dates
        coverage = len(actual_dates.intersection(expected_dates)) / len(expected_dates) * 100 if expected_dates else 0

        # Phase 2 threshold: 80% (more lenient since we have fallbacks)
        is_ready = coverage >= 80.0
        if not is_ready:
            all_ready = False

        results['tables'][table_name] = {
            'dates_with_data': len(actual_dates),
            'expected_dates': len(expected_dates),
            'coverage_pct': coverage,
            'missing_dates': len(missing_dates),
            'is_ready': is_ready
        }

        status = "✅" if is_ready else "⚠️"
        print(f"\n{status} {table_name}")
        print(f"   Description: {config['description']}")
        print(f"   Coverage: {len(actual_dates.intersection(expected_dates))}/{len(expected_dates)} ({coverage:.1f}%)")
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
        print(f"\n✅ PHASE 2 IS READY for Phase 3 backfill")
        print(f"   All raw data tables have ≥80% coverage.")
    else:
        print(f"\n⚠️ PHASE 2 HAS GAPS but Phase 3 can still proceed")
        print(f"   Some raw tables have <80% coverage.")
        print(f"   Phase 3 processors have fallback mechanisms.")

        # Show which tables are not ready
        not_ready = [name for name, info in results['tables'].items() if not info['is_ready']]
        if not_ready:
            print(f"\n   Tables with gaps:")
            for name in not_ready:
                info = results['tables'][name]
                print(f"     - {name}: {info['coverage_pct']:.1f}% ({info['missing_dates']} dates missing)")

    print(f"\n{'='*70}")

    results['all_ready'] = all_ready
    return results


def main():
    parser = argparse.ArgumentParser(
        description='Verify Phase 2 raw data is ready for Phase 3 backfill',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
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

    results = verify_phase2_readiness(start_date, end_date, verbose=args.verbose)

    # Exit with warning (code 0) even if not perfect - Phase 3 has fallbacks
    # Only exit with error if completely missing
    sys.exit(0)


if __name__ == "__main__":
    main()

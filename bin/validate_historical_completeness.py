#!/usr/bin/env python3
"""
Historical Completeness Validation Script

Local sandbox for testing and validating the historical completeness feature.
Can run against real BigQuery data or use mock data for local testing.

Usage:
    # Quick validation against BigQuery (default)
    python bin/validate_historical_completeness.py

    # Validate specific date
    python bin/validate_historical_completeness.py --date 2026-01-21

    # Run unit tests only (no BigQuery)
    python bin/validate_historical_completeness.py --unit-tests

    # Full validation with verbose output
    python bin/validate_historical_completeness.py --verbose

    # Dry run - show what would be checked without querying
    python bin/validate_historical_completeness.py --dry-run

Created: January 22, 2026
Purpose: Validate historical completeness feature implementation
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_unit_tests() -> bool:
    """
    Run unit tests for historical completeness module.
    Returns True if all tests pass.
    """
    print("\n" + "="*60)
    print("UNIT TESTS: Historical Completeness Module")
    print("="*60 + "\n")

    from shared.validation.historical_completeness import (
        assess_historical_completeness,
        should_skip_feature_generation,
        HistoricalCompletenessResult,
        WINDOW_SIZE,
        MINIMUM_GAMES_THRESHOLD,
    )

    tests_passed = 0
    tests_failed = 0

    def test(name: str, condition: bool, details: str = ""):
        nonlocal tests_passed, tests_failed
        if condition:
            print(f"  ✅ {name}")
            tests_passed += 1
        else:
            print(f"  ❌ {name}")
            if details:
                print(f"     {details}")
            tests_failed += 1

    # Test 1: Complete veteran player
    result = assess_historical_completeness(games_found=10, games_available=50)
    test("Complete veteran (10/10 games)",
         result.is_complete and not result.is_bootstrap,
         f"Got: is_complete={result.is_complete}, is_bootstrap={result.is_bootstrap}")

    # Test 2: Data gap - missing games
    result = assess_historical_completeness(games_found=8, games_available=50)
    test("Data gap (8/10 games)",
         not result.is_complete and not result.is_bootstrap and result.is_data_gap,
         f"Got: is_complete={result.is_complete}, is_data_gap={result.is_data_gap}")

    # Test 3: Bootstrap - new player
    result = assess_historical_completeness(games_found=5, games_available=5)
    test("Bootstrap (5/5 games, new player)",
         result.is_complete and result.is_bootstrap,
         f"Got: is_complete={result.is_complete}, is_bootstrap={result.is_bootstrap}")

    # Test 4: Brand new player
    result = assess_historical_completeness(games_found=0, games_available=0)
    test("Brand new player (0/0 games)",
         result.is_complete and result.is_bootstrap,
         f"Got: is_complete={result.is_complete}, is_bootstrap={result.is_bootstrap}")

    # Test 5: Skip threshold
    test("Skip below minimum (4 games)",
         should_skip_feature_generation(4),
         f"Got: {should_skip_feature_generation(4)}")

    test("Don't skip at minimum (5 games)",
         not should_skip_feature_generation(5),
         f"Got: {should_skip_feature_generation(5)}")

    # Test 6: BigQuery struct conversion
    result = assess_historical_completeness(
        games_found=10,
        games_available=50,
        contributing_dates=[date(2026, 1, 15), date(2026, 1, 13)]
    )
    bq_struct = result.to_bq_struct()
    test("BQ struct conversion",
         bq_struct['games_found'] == 10 and len(bq_struct['contributing_game_dates']) == 2,
         f"Got: {bq_struct}")

    # Test 7: Completeness percentage
    result = assess_historical_completeness(games_found=8, games_available=50)
    test("Completeness percentage (80%)",
         result.completeness_pct == 80.0,
         f"Got: {result.completeness_pct}")

    # Test 8: Constants
    test("Window size is 10",
         WINDOW_SIZE == 10,
         f"Got: {WINDOW_SIZE}")

    test("Minimum threshold is 5",
         MINIMUM_GAMES_THRESHOLD == 5,
         f"Got: {MINIMUM_GAMES_THRESHOLD}")

    print(f"\n{'='*60}")
    print(f"UNIT TESTS: {tests_passed} passed, {tests_failed} failed")
    print(f"{'='*60}\n")

    return tests_failed == 0


def validate_bigquery_schema() -> bool:
    """
    Validate that BigQuery schema has the historical_completeness column.
    """
    print("\n" + "="*60)
    print("SCHEMA VALIDATION: BigQuery Column Check")
    print("="*60 + "\n")

    try:
        from google.cloud import bigquery
        client = bigquery.Client()

        table_id = "nba-props-platform.nba_predictions.ml_feature_store_v2"
        table = client.get_table(table_id)

        # Find the historical_completeness column
        found = False
        for field in table.schema:
            if field.name == 'historical_completeness':
                found = True
                print(f"  ✅ Found column: historical_completeness")
                print(f"     Type: {field.field_type}")
                if field.fields:
                    print(f"     Nested fields:")
                    for nested in field.fields:
                        print(f"       - {nested.name}: {nested.field_type}")
                break

        if not found:
            print(f"  ❌ Column 'historical_completeness' NOT FOUND in schema")
            return False

        return True

    except Exception as e:
        print(f"  ❌ Error checking schema: {e}")
        return False


def validate_data_population(game_date: date, verbose: bool = False) -> bool:
    """
    Validate that historical_completeness is populated for a given date.
    """
    print("\n" + "="*60)
    print(f"DATA VALIDATION: {game_date}")
    print("="*60 + "\n")

    try:
        from google.cloud import bigquery
        client = bigquery.Client()

        # Query to check data
        query = f"""
        SELECT
            COUNT(*) as total,
            COUNTIF(historical_completeness IS NOT NULL) as with_completeness,
            COUNTIF(historical_completeness.is_complete) as complete,
            COUNTIF(NOT historical_completeness.is_complete AND NOT historical_completeness.is_bootstrap) as incomplete,
            COUNTIF(historical_completeness.is_bootstrap) as bootstrap,
            AVG(historical_completeness.games_found) as avg_games_found,
            AVG(historical_completeness.games_expected) as avg_games_expected
        FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
        WHERE game_date = '{game_date}'
        """

        result = list(client.query(query).result(timeout=60))[0]

        total = result.total
        with_completeness = result.with_completeness
        complete = result.complete or 0
        incomplete = result.incomplete or 0
        bootstrap = result.bootstrap or 0

        print(f"  Total records: {total}")
        print(f"  With completeness: {with_completeness}")

        if with_completeness > 0:
            print(f"    - Complete: {complete}")
            print(f"    - Incomplete (data gap): {incomplete}")
            print(f"    - Bootstrap: {bootstrap}")
            print(f"    - Avg games found: {result.avg_games_found:.1f}")
            print(f"    - Avg games expected: {result.avg_games_expected:.1f}")

            # Validation checks
            all_passed = True

            if with_completeness == total:
                print(f"\n  ✅ All records have completeness data")
            else:
                print(f"\n  ⚠️  {total - with_completeness} records missing completeness (may be from older runs)")

            if incomplete == 0:
                print(f"  ✅ No data gaps detected")
            else:
                print(f"  ⚠️  {incomplete} records have data gaps")
                all_passed = False

            return all_passed
        else:
            print(f"\n  ⚠️  No records with historical_completeness found")
            print(f"      This may be because the date hasn't been processed since the feature was deployed")
            return False

    except Exception as e:
        print(f"  ❌ Error querying data: {e}")
        return False


def validate_monitoring_views() -> bool:
    """
    Validate that monitoring views exist and return data.
    """
    print("\n" + "="*60)
    print("VIEW VALIDATION: Monitoring Views")
    print("="*60 + "\n")

    try:
        from google.cloud import bigquery
        client = bigquery.Client()

        views_ok = True

        # Test v_historical_completeness_daily
        try:
            query = "SELECT COUNT(*) as cnt FROM `nba-props-platform.nba_predictions.v_historical_completeness_daily`"
            result = list(client.query(query).result(timeout=60))[0]
            print(f"  ✅ v_historical_completeness_daily: {result.cnt} rows")
        except Exception as e:
            print(f"  ❌ v_historical_completeness_daily: {e}")
            views_ok = False

        # Test v_incomplete_features
        try:
            query = "SELECT COUNT(*) as cnt FROM `nba-props-platform.nba_predictions.v_incomplete_features`"
            result = list(client.query(query).result(timeout=60))[0]
            print(f"  ✅ v_incomplete_features: {result.cnt} rows")
        except Exception as e:
            print(f"  ❌ v_incomplete_features: {e}")
            views_ok = False

        return views_ok

    except Exception as e:
        print(f"  ❌ Error checking views: {e}")
        return False


def validate_cli_tool() -> bool:
    """
    Validate that the check_cascade.py CLI tool works.
    """
    print("\n" + "="*60)
    print("CLI VALIDATION: check_cascade.py")
    print("="*60 + "\n")

    import subprocess

    try:
        # Test --dry-run mode (doesn't require BigQuery)
        result = subprocess.run(
            ["python", "bin/check_cascade.py", "--summary", "--dry-run"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

        if result.returncode == 0:
            print(f"  ✅ CLI tool runs successfully")
            print(f"     (dry-run mode)")
            return True
        else:
            print(f"  ❌ CLI tool failed: {result.stderr}")
            return False

    except Exception as e:
        print(f"  ❌ Error running CLI tool: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Validate Historical Completeness Feature',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Quick validation
    python bin/validate_historical_completeness.py

    # Validate specific date
    python bin/validate_historical_completeness.py --date 2026-01-21

    # Run only unit tests (no BigQuery)
    python bin/validate_historical_completeness.py --unit-tests

    # Full validation with verbose output
    python bin/validate_historical_completeness.py --verbose
        """
    )

    parser.add_argument('--date', type=str, default=None,
                       help='Date to validate (YYYY-MM-DD, default: yesterday)')
    parser.add_argument('--unit-tests', action='store_true',
                       help='Run only unit tests (no BigQuery)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose output')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be checked without querying')

    args = parser.parse_args()

    print("\n" + "="*60)
    print("HISTORICAL COMPLETENESS VALIDATION")
    print("="*60)

    if args.dry_run:
        print("\n[DRY RUN MODE - No BigQuery queries will be executed]\n")
        print("Would validate:")
        print("  1. Unit tests for historical_completeness.py")
        print("  2. BigQuery schema (historical_completeness column)")
        print("  3. Data population for specified date")
        print("  4. Monitoring views (v_historical_completeness_daily, v_incomplete_features)")
        print("  5. CLI tool (check_cascade.py)")
        return

    all_passed = True

    # Always run unit tests
    if not run_unit_tests():
        all_passed = False

    # If --unit-tests flag, stop here
    if args.unit_tests:
        if all_passed:
            print("✅ All unit tests passed!")
            sys.exit(0)
        else:
            print("❌ Some unit tests failed!")
            sys.exit(1)

    # Validate BigQuery schema
    if not validate_bigquery_schema():
        all_passed = False

    # Validate data population
    if args.date:
        game_date = datetime.strptime(args.date, '%Y-%m-%d').date()
    else:
        game_date = date.today() - timedelta(days=1)

    if not validate_data_population(game_date, args.verbose):
        all_passed = False

    # Validate monitoring views
    if not validate_monitoring_views():
        all_passed = False

    # Validate CLI tool
    if not validate_cli_tool():
        all_passed = False

    # Final summary
    print("\n" + "="*60)
    if all_passed:
        print("✅ ALL VALIDATIONS PASSED")
    else:
        print("⚠️  SOME VALIDATIONS FAILED - Review output above")
    print("="*60 + "\n")

    sys.exit(0 if all_passed else 1)


if __name__ == '__main__':
    main()

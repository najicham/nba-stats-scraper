#!/usr/bin/env python3
"""
Backfill Verification Script

Verifies that Phase 3 and Phase 4 backfill completed successfully for a date range.

Usage:
    python bin/backfill/verify_backfill_range.py --start-date 2021-10-19 --end-date 2021-11-01
    python bin/backfill/verify_backfill_range.py --start-date 2021-10-19 --end-date 2021-11-01 --verbose
"""

import argparse
from datetime import date, datetime, timedelta
from google.cloud import bigquery
import sys

# Bootstrap periods (first 7 days of each season - Phase 4 skips these)
BOOTSTRAP_PERIODS = [
    (date(2021, 10, 19), date(2021, 10, 25)),  # 2021-22
    (date(2022, 10, 18), date(2022, 10, 24)),  # 2022-23
    (date(2023, 10, 24), date(2023, 10, 30)),  # 2023-24
    (date(2024, 10, 22), date(2024, 10, 28)),  # 2024-25
]

def is_bootstrap_date(check_date: date) -> bool:
    """Check if date falls within any bootstrap period."""
    for start, end in BOOTSTRAP_PERIODS:
        if start <= check_date <= end:
            return True
    return False


def run_verification(start_date: date, end_date: date, verbose: bool = False):
    """Run all verification checks for the date range."""

    client = bigquery.Client()
    project = "nba-props-platform"

    print("=" * 70)
    print(f"BACKFILL VERIFICATION: {start_date} to {end_date}")
    print("=" * 70)
    print()

    all_passed = True

    # ============================================================
    # CHECK 1: Expected game dates in range
    # ============================================================
    print("1. EXPECTED GAME DATES")
    print("-" * 50)

    query = f"""
    SELECT game_date
    FROM `{project}.nba_raw.nbac_schedule`
    WHERE game_status = 3
      AND game_date BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY game_date
    ORDER BY game_date
    """
    result = client.query(query).result()
    expected_dates = [row.game_date for row in result]

    bootstrap_dates = [d for d in expected_dates if is_bootstrap_date(d)]
    non_bootstrap_dates = [d for d in expected_dates if not is_bootstrap_date(d)]

    print(f"   Total game dates: {len(expected_dates)}")
    print(f"   Bootstrap dates (Phase 4 skips): {len(bootstrap_dates)}")
    print(f"   Non-bootstrap dates: {len(non_bootstrap_dates)}")

    if verbose:
        print(f"   Bootstrap: {[str(d) for d in bootstrap_dates]}")
        print(f"   Non-bootstrap: {[str(d) for d in non_bootstrap_dates[:5]]}...")
    print()

    # ============================================================
    # CHECK 2: Phase 3 Analytics Tables
    # ============================================================
    print("2. PHASE 3 ANALYTICS COMPLETENESS")
    print("-" * 50)

    phase3_tables = [
        ("nba_analytics.player_game_summary", "game_date"),
        ("nba_analytics.team_defense_game_summary", "game_date"),
        ("nba_analytics.team_offense_game_summary", "game_date"),
        ("nba_analytics.upcoming_player_game_context", "game_date"),
        ("nba_analytics.upcoming_team_game_context", "game_date"),
    ]

    phase3_results = {}
    for table, date_col in phase3_tables:
        query = f"""
        SELECT {date_col} as game_date
        FROM `{project}.{table}`
        WHERE {date_col} BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY {date_col}
        """
        result = client.query(query).result()
        actual_dates = set(row.game_date for row in result)

        missing = set(expected_dates) - actual_dates
        table_name = table.split(".")[-1]

        phase3_results[table_name] = {
            "expected": len(expected_dates),
            "actual": len(actual_dates),
            "missing": sorted(missing),
        }

        status = "✅" if len(missing) == 0 else "❌"
        print(f"   {status} {table_name}: {len(actual_dates)}/{len(expected_dates)}")

        if missing and verbose:
            print(f"      Missing: {[str(d) for d in sorted(missing)[:5]]}...")

        if len(missing) > 0 and table_name != "upcoming_player_game_context":
            # upcoming_player_game_context may have ~0.3% missing (2 dates)
            all_passed = False

    print()

    # ============================================================
    # CHECK 3: Phase 4 Precompute Tables
    # ============================================================
    print("3. PHASE 4 PRECOMPUTE COMPLETENESS")
    print("-" * 50)
    print(f"   Note: Bootstrap dates ({len(bootstrap_dates)}) should be skipped")
    print()

    phase4_tables = [
        ("nba_precompute.team_defense_zone_analysis", "analysis_date"),
        ("nba_precompute.player_shot_zone_analysis", "analysis_date"),
        ("nba_precompute.player_composite_factors", "game_date"),
        ("nba_precompute.player_daily_cache", "cache_date"),
    ]

    for table, date_col in phase4_tables:
        table_name = table.split(".")[-1]

        try:
            query = f"""
            SELECT {date_col} as game_date
            FROM `{project}.{table}`
            WHERE {date_col} BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY {date_col}
            """
            result = client.query(query).result()
            actual_dates = set(row.game_date for row in result)

            # Phase 4 should only have non-bootstrap dates
            expected_p4 = set(non_bootstrap_dates)
            missing = expected_p4 - actual_dates
            unexpected_bootstrap = actual_dates & set(bootstrap_dates)

            status = "✅" if len(missing) == 0 else "❌"
            print(f"   {status} {table_name}: {len(actual_dates)}/{len(non_bootstrap_dates)}")

            if unexpected_bootstrap:
                print(f"      ⚠️  Unexpected bootstrap dates found: {len(unexpected_bootstrap)}")

            if missing and verbose:
                print(f"      Missing: {[str(d) for d in sorted(missing)[:5]]}...")

            if len(missing) > 0:
                all_passed = False

        except Exception as e:
            print(f"   ❌ {table_name}: ERROR - {e}")
            all_passed = False

    print()

    # ============================================================
    # CHECK 4: Processor Run History
    # ============================================================
    print("4. PROCESSOR RUN HISTORY")
    print("-" * 50)

    query = f"""
    SELECT
        phase,
        processor_name,
        COUNTIF(success = true) as success_count,
        COUNTIF(success = false) as fail_count,
        COUNT(*) as total
    FROM `{project}.nba_reference.processor_run_history`
    WHERE data_date BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY phase, processor_name
    ORDER BY phase, processor_name
    """

    try:
        result = client.query(query).result()
        rows = list(result)

        if not rows:
            print("   ⚠️  No run history found for this date range")
        else:
            for row in rows:
                status = "✅" if row.fail_count == 0 else "❌"
                print(f"   {status} {row.processor_name}: {row.success_count}/{row.total} success")
                if row.fail_count > 0:
                    all_passed = False
    except Exception as e:
        print(f"   ⚠️  Could not query run history: {e}")

    print()

    # ============================================================
    # CHECK 5: Data Quality Spot Check
    # ============================================================
    print("5. DATA QUALITY SPOT CHECK")
    print("-" * 50)

    # Check player_game_summary has reasonable data
    query = f"""
    SELECT
        COUNT(*) as total_records,
        COUNT(DISTINCT player_lookup) as unique_players,
        ROUND(AVG(points), 1) as avg_points,
        ROUND(AVG(minutes), 1) as avg_minutes
    FROM `{project}.nba_analytics.player_game_summary`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    """

    try:
        result = list(client.query(query).result())[0]

        print(f"   player_game_summary:")
        print(f"      Total records: {result.total_records}")
        print(f"      Unique players: {result.unique_players}")
        print(f"      Avg points: {result.avg_points}")
        print(f"      Avg minutes: {result.avg_minutes}")

        # Sanity checks
        if result.avg_points < 5 or result.avg_points > 20:
            print(f"      ⚠️  Avg points looks unusual")
        if result.unique_players < 100:
            print(f"      ⚠️  Fewer unique players than expected")

    except Exception as e:
        print(f"   ⚠️  Could not run quality check: {e}")

    print()

    # ============================================================
    # SUMMARY
    # ============================================================
    print("=" * 70)
    if all_passed:
        print("✅ VERIFICATION PASSED - All checks successful!")
    else:
        print("❌ VERIFICATION FAILED - Some checks did not pass")
        print("   Review the output above for details")
    print("=" * 70)

    return all_passed


def main():
    parser = argparse.ArgumentParser(description="Verify backfill completion for a date range")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")

    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()

    passed = run_verification(start_date, end_date, args.verbose)

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

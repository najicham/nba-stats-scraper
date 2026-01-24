#!/usr/bin/env python3
"""
Backfill Pre-Flight Check

Comprehensive check of data availability across all phases for a date range.
Shows what's scraped, what's processed, and identifies gaps.

Usage:
    python bin/backfill/preflight_check.py --start-date 2021-10-19 --end-date 2021-11-01
    python bin/backfill/preflight_check.py --date 2021-10-25
    python bin/backfill/preflight_check.py --start-date 2021-10-19 --end-date 2021-11-01 --phase 2
    python bin/backfill/preflight_check.py --start-date 2021-10-19 --end-date 2021-11-01 --verbose
"""

import argparse
import os
from datetime import date, datetime, timedelta
from google.cloud import bigquery
from google.cloud import storage
import sys
from collections import defaultdict

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
GCS_BUCKET = "nba-scraped-data"

# Phase 1: Scraper -> GCS paths
SCRAPER_PATHS = {
    "nbac_team_boxscore": "events/{date}/nbac-team-boxscore/",
    "nbac_gamebook_player_stats": "events/{date}/nbac-gamebook-player-stats/",
    "nbac_play_by_play": "events/{date}/nbac-play-by-play/",
    "bdl_standings": "events/{date}/bdl-standings/",
    "odds_api_player_props": "player-props/{date}/odds-api/",
    "bettingpros_player_props": "player-props/{date}/bettingpros/",
}

# Phase 2: Raw BigQuery tables
PHASE2_TABLES = {
    "nbac_team_boxscore": ("nba_raw.nbac_team_boxscore", "game_date"),
    "nbac_gamebook_player_stats": ("nba_raw.nbac_gamebook_player_stats", "game_date"),
    "nbac_play_by_play": ("nba_raw.nbac_play_by_play", "game_date"),
    "bdl_player_boxscores": ("nba_raw.bdl_player_boxscores", "game_date"),
    "bdl_standings": ("nba_raw.bdl_standings", "scrape_date"),
    "odds_api_player_points_props": ("nba_raw.odds_api_player_points_props", "game_date"),
    "bettingpros_player_props": ("nba_raw.bettingpros_player_points_props", "game_date"),
    "nbac_schedule": ("nba_raw.nbac_schedule", "game_date"),
}

# Phase 3: Analytics BigQuery tables
PHASE3_TABLES = {
    "player_game_summary": ("nba_analytics.player_game_summary", "game_date"),
    "team_defense_game_summary": ("nba_analytics.team_defense_game_summary", "game_date"),
    "team_offense_game_summary": ("nba_analytics.team_offense_game_summary", "game_date"),
    "upcoming_player_game_context": ("nba_analytics.upcoming_player_game_context", "game_date"),
    "upcoming_team_game_context": ("nba_analytics.upcoming_team_game_context", "game_date"),
}

# Phase 4: Precompute BigQuery tables
PHASE4_TABLES = {
    "team_defense_zone_analysis": ("nba_precompute.team_defense_zone_analysis", "analysis_date"),
    "player_shot_zone_analysis": ("nba_precompute.player_shot_zone_analysis", "analysis_date"),
    "player_composite_factors": ("nba_precompute.player_composite_factors", "game_date"),
    "player_daily_cache": ("nba_precompute.player_daily_cache", "cache_date"),
}


def get_game_dates_from_schedule(client: bigquery.Client, start_date: date, end_date: date) -> list:
    """Get expected game dates from schedule."""
    query = f"""
    SELECT game_date, COUNT(*) as games
    FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
    WHERE game_status = 3
      AND game_date BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY game_date
    ORDER BY game_date
    """
    result = client.query(query).result(timeout=60)
    return [(row.game_date, row.games) for row in result]


def check_gcs_files(storage_client, date_str: str) -> dict:
    """Check GCS for scraped files on a specific date."""
    bucket = storage_client.bucket(GCS_BUCKET)
    results = {}

    for scraper_name, path_template in SCRAPER_PATHS.items():
        path = path_template.format(date=date_str)
        blobs = list(bucket.list_blobs(prefix=path, max_results=100))
        results[scraper_name] = len(blobs)

    return results


def check_bigquery_table(client: bigquery.Client, table: str, date_col: str,
                          start_date: date, end_date: date) -> dict:
    """Check BigQuery table for data in date range."""
    try:
        query = f"""
        SELECT
            {date_col} as game_date,
            COUNT(*) as records
        FROM `{PROJECT_ID}.{table}`
        WHERE {date_col} BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY {date_col}
        ORDER BY {date_col}
        """
        result = client.query(query).result(timeout=60)
        return {row.game_date: row.records for row in result}
    except Exception as e:
        return {"error": str(e)}


def print_phase_summary(phase_name: str, tables_data: dict, expected_dates: list, verbose: bool = False):
    """Print summary for a phase."""
    print(f"\n{'=' * 70}")
    print(f"  {phase_name}")
    print(f"{'=' * 70}")

    expected_date_set = set(d for d, _ in expected_dates)

    for table_name, data in tables_data.items():
        if isinstance(data, dict) and "error" in data:
            print(f"\n  ❌ {table_name}: ERROR - {data['error'][:50]}...")
            continue

        if isinstance(data, dict):
            dates_with_data = set(data.keys())
            missing = expected_date_set - dates_with_data
            total_records = sum(data.values())

            coverage = len(dates_with_data) / len(expected_date_set) * 100 if expected_date_set else 0
            status = "✅" if coverage >= 99 else "⚠️" if coverage >= 80 else "❌"

            print(f"\n  {status} {table_name}")
            print(f"     Dates: {len(dates_with_data)}/{len(expected_date_set)} ({coverage:.1f}%)")
            print(f"     Records: {total_records:,}")

            if missing and verbose:
                missing_sorted = sorted(missing)[:10]
                print(f"     Missing: {[str(d) for d in missing_sorted]}" +
                      ("..." if len(missing) > 10 else ""))

            if verbose and data:
                # Show per-date breakdown
                print(f"     Per date (first 5):")
                for d, count in list(data.items())[:5]:
                    print(f"        {d}: {count:,} records")


def print_gcs_summary(gcs_data: dict, expected_dates: list, verbose: bool = False):
    """Print GCS scraper summary."""
    print(f"\n{'=' * 70}")
    print(f"  PHASE 1: GCS Scraped Files")
    print(f"{'=' * 70}")

    # Aggregate by scraper
    scraper_totals = defaultdict(lambda: {"dates_with_data": 0, "total_files": 0})

    for date_str, scrapers in gcs_data.items():
        for scraper_name, file_count in scrapers.items():
            if file_count > 0:
                scraper_totals[scraper_name]["dates_with_data"] += 1
                scraper_totals[scraper_name]["total_files"] += file_count

    for scraper_name in SCRAPER_PATHS.keys():
        data = scraper_totals.get(scraper_name, {"dates_with_data": 0, "total_files": 0})
        coverage = data["dates_with_data"] / len(expected_dates) * 100 if expected_dates else 0
        status = "✅" if coverage >= 99 else "⚠️" if coverage >= 50 else "❌"

        print(f"\n  {status} {scraper_name}")
        print(f"     Dates: {data['dates_with_data']}/{len(expected_dates)} ({coverage:.1f}%)")
        print(f"     Files: {data['total_files']:,}")


def run_preflight_check(start_date: date, end_date: date,
                        phase_filter: int = None, verbose: bool = False):
    """Run comprehensive pre-flight check."""

    print("=" * 70)
    print(f"  BACKFILL PRE-FLIGHT CHECK")
    print(f"  Date Range: {start_date} to {end_date}")
    print(f"  Days: {(end_date - start_date).days + 1}")
    print("=" * 70)

    # Initialize clients
    bq_client = bigquery.Client()
    storage_client = storage.Client()

    # Get expected game dates
    print("\nFetching expected game dates from schedule...")
    expected_dates = get_game_dates_from_schedule(bq_client, start_date, end_date)
    print(f"Found {len(expected_dates)} game dates with {sum(g for _, g in expected_dates)} total games")

    if verbose:
        print("\nGame dates:")
        for d, games in expected_dates[:10]:
            print(f"  {d}: {games} games")
        if len(expected_dates) > 10:
            print(f"  ... and {len(expected_dates) - 10} more")

    # Phase 1: GCS Check (optional - can be slow)
    if phase_filter is None or phase_filter == 1:
        print("\n" + "-" * 50)
        print("Checking GCS scraped files (this may take a moment)...")
        gcs_data = {}
        for game_date, _ in expected_dates:
            date_str = game_date.strftime("%Y-%m-%d")
            gcs_data[date_str] = check_gcs_files(storage_client, date_str)
        print_gcs_summary(gcs_data, expected_dates, verbose)

    # Phase 2: Raw BigQuery Tables
    if phase_filter is None or phase_filter == 2:
        print("\n" + "-" * 50)
        print("Checking Phase 2 Raw BigQuery tables...")
        phase2_data = {}
        for table_name, (table_path, date_col) in PHASE2_TABLES.items():
            phase2_data[table_name] = check_bigquery_table(
                bq_client, table_path, date_col, start_date, end_date
            )
        print_phase_summary("PHASE 2: Raw Data (BigQuery)", phase2_data, expected_dates, verbose)

    # Phase 3: Analytics BigQuery Tables
    if phase_filter is None or phase_filter == 3:
        print("\n" + "-" * 50)
        print("Checking Phase 3 Analytics BigQuery tables...")
        phase3_data = {}
        for table_name, (table_path, date_col) in PHASE3_TABLES.items():
            phase3_data[table_name] = check_bigquery_table(
                bq_client, table_path, date_col, start_date, end_date
            )
        print_phase_summary("PHASE 3: Analytics (BigQuery)", phase3_data, expected_dates, verbose)

    # Phase 4: Precompute BigQuery Tables
    if phase_filter is None or phase_filter == 4:
        print("\n" + "-" * 50)
        print("Checking Phase 4 Precompute BigQuery tables...")
        phase4_data = {}
        for table_name, (table_path, date_col) in PHASE4_TABLES.items():
            phase4_data[table_name] = check_bigquery_table(
                bq_client, table_path, date_col, start_date, end_date
            )
        print_phase_summary("PHASE 4: Precompute (BigQuery)", phase4_data, expected_dates, verbose)

    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"\n  Date range: {start_date} to {end_date}")
    print(f"  Expected game dates: {len(expected_dates)}")
    print("\n  Next steps:")
    print("    1. Review any ❌ or ⚠️ items above")
    print("    2. Phase 2 should be ~100% before running Phase 3 backfill")
    print("    3. Phase 3 should be ~100% before running Phase 4 backfill")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Pre-flight check for backfill")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--date", help="Single date (YYYY-MM-DD) - shortcut for start=end")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3, 4],
                        help="Check only specific phase (1=GCS, 2=Raw, 3=Analytics, 4=Precompute)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")

    args = parser.parse_args()

    # Handle date arguments
    if args.date:
        start_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        end_date = start_date
    elif args.start_date and args.end_date:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    else:
        parser.error("Either --date or both --start-date and --end-date required")

    run_preflight_check(start_date, end_date, args.phase, args.verbose)


if __name__ == "__main__":
    main()

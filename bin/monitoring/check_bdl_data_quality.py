#!/usr/bin/env python3
"""
BDL Data Quality Monitor

Compares BDL (Ball Don't Lie) API data against NBA.com gamebook data
to track data quality over time.

Created: 2026-01-28
Reason: BDL API was found to return incorrect data (~50% of actual minutes/points)
        for many players. This script monitors if/when BDL data quality improves.

Usage:
    python bin/monitoring/check_bdl_data_quality.py [--date YYYY-MM-DD] [--days N]

Examples:
    # Check today's data
    python bin/monitoring/check_bdl_data_quality.py

    # Check specific date
    python bin/monitoring/check_bdl_data_quality.py --date 2026-01-27

    # Check last 7 days
    python bin/monitoring/check_bdl_data_quality.py --days 7
"""

import argparse
import sys
from datetime import date, timedelta
from google.cloud import bigquery


def check_bdl_quality(game_date: str) -> dict:
    """Compare BDL data against NBA.com gamebook for a specific date."""

    client = bigquery.Client()

    query = f"""
    WITH gamebook AS (
        SELECT
            player_lookup,
            SAFE_CAST(REGEXP_EXTRACT(minutes, r'^([0-9]+)') AS INT64) as minutes_int,
            points
        FROM nba_raw.nbac_gamebook_player_stats
        WHERE game_date = '{game_date}'
          AND player_status = 'active'
    ),
    bdl AS (
        SELECT
            player_lookup,
            SAFE_CAST(minutes AS INT64) as minutes_int,
            points
        FROM nba_raw.bdl_player_boxscores
        WHERE game_date = '{game_date}'
    ),
    comparison AS (
        SELECT
            g.player_lookup,
            g.minutes_int as gamebook_min,
            g.points as gamebook_pts,
            b.minutes_int as bdl_min,
            b.points as bdl_pts,
            ABS(COALESCE(g.minutes_int, 0) - COALESCE(b.minutes_int, 0)) as minutes_diff,
            ABS(COALESCE(g.points, 0) - COALESCE(b.points, 0)) as points_diff
        FROM gamebook g
        LEFT JOIN bdl b ON g.player_lookup = b.player_lookup
    )
    SELECT
        COUNT(*) as total_players,
        COUNTIF(bdl_min IS NOT NULL) as bdl_coverage,
        COUNTIF(minutes_diff = 0) as minutes_exact_match,
        COUNTIF(minutes_diff <= 2) as minutes_close_match,
        COUNTIF(minutes_diff > 5) as minutes_major_mismatch,
        COUNTIF(points_diff = 0) as points_exact_match,
        COUNTIF(points_diff <= 2) as points_close_match,
        COUNTIF(points_diff > 5) as points_major_mismatch,
        AVG(minutes_diff) as avg_minutes_diff,
        AVG(points_diff) as avg_points_diff,
        MAX(minutes_diff) as max_minutes_diff,
        MAX(points_diff) as max_points_diff
    FROM comparison
    """

    result = client.query(query).result()
    row = list(result)[0]

    return {
        'date': game_date,
        'total_players': row.total_players,
        'bdl_coverage': row.bdl_coverage,
        'bdl_coverage_pct': round(100 * row.bdl_coverage / row.total_players, 1) if row.total_players > 0 else 0,
        'minutes_exact_match': row.minutes_exact_match,
        'minutes_exact_pct': round(100 * row.minutes_exact_match / row.total_players, 1) if row.total_players > 0 else 0,
        'minutes_major_mismatch': row.minutes_major_mismatch,
        'minutes_mismatch_pct': round(100 * row.minutes_major_mismatch / row.total_players, 1) if row.total_players > 0 else 0,
        'points_exact_match': row.points_exact_match,
        'points_exact_pct': round(100 * row.points_exact_match / row.total_players, 1) if row.total_players > 0 else 0,
        'points_major_mismatch': row.points_major_mismatch,
        'avg_minutes_diff': round(row.avg_minutes_diff, 1) if row.avg_minutes_diff else 0,
        'avg_points_diff': round(row.avg_points_diff, 1) if row.avg_points_diff else 0,
        'max_minutes_diff': row.max_minutes_diff or 0,
        'max_points_diff': row.max_points_diff or 0,
    }


def get_worst_mismatches(game_date: str, limit: int = 10) -> list:
    """Get the worst BDL vs NBA.com mismatches for a date."""

    client = bigquery.Client()

    query = f"""
    WITH gamebook AS (
        SELECT
            player_lookup,
            player_name as player_full_name,
            SAFE_CAST(REGEXP_EXTRACT(minutes, r'^([0-9]+)') AS INT64) as minutes_int,
            points
        FROM nba_raw.nbac_gamebook_player_stats
        WHERE game_date = '{game_date}'
          AND player_status = 'active'
    ),
    bdl AS (
        SELECT
            player_lookup,
            SAFE_CAST(minutes AS INT64) as minutes_int,
            points
        FROM nba_raw.bdl_player_boxscores
        WHERE game_date = '{game_date}'
    )
    SELECT
        g.player_full_name,
        g.minutes_int as gamebook_min,
        b.minutes_int as bdl_min,
        g.points as gamebook_pts,
        b.points as bdl_pts,
        ABS(COALESCE(g.minutes_int, 0) - COALESCE(b.minutes_int, 0)) as minutes_diff
    FROM gamebook g
    LEFT JOIN bdl b ON g.player_lookup = b.player_lookup
    WHERE g.minutes_int > 0  -- Only players who played
    ORDER BY minutes_diff DESC
    LIMIT {limit}
    """

    result = client.query(query).result()
    return [dict(row) for row in result]


def print_report(stats: dict, mismatches: list = None):
    """Print a formatted quality report."""

    print(f"\n{'='*60}")
    print(f"BDL Data Quality Report - {stats['date']}")
    print(f"{'='*60}")

    print(f"\nCoverage:")
    print(f"  Total players (NBA.com): {stats['total_players']}")
    print(f"  BDL coverage: {stats['bdl_coverage']} ({stats['bdl_coverage_pct']}%)")

    print(f"\nMinutes Accuracy:")
    print(f"  Exact match: {stats['minutes_exact_match']} ({stats['minutes_exact_pct']}%)")
    print(f"  Major mismatch (>5 min): {stats['minutes_major_mismatch']} ({stats['minutes_mismatch_pct']}%)")
    print(f"  Avg difference: {stats['avg_minutes_diff']} min")
    print(f"  Max difference: {stats['max_minutes_diff']} min")

    print(f"\nPoints Accuracy:")
    print(f"  Exact match: {stats['points_exact_match']} ({stats['points_exact_pct']}%)")
    print(f"  Avg difference: {stats['avg_points_diff']} pts")
    print(f"  Max difference: {stats['max_points_diff']} pts")

    # Quality grade
    if stats['minutes_mismatch_pct'] > 20:
        grade = "❌ POOR - Do not use BDL data"
    elif stats['minutes_mismatch_pct'] > 10:
        grade = "⚠️  FAIR - Use with caution"
    elif stats['minutes_mismatch_pct'] > 5:
        grade = "✓ GOOD - Consider re-enabling"
    else:
        grade = "✅ EXCELLENT - Safe to use"

    print(f"\nOverall Grade: {grade}")

    if mismatches:
        print(f"\n{'─'*60}")
        print("Worst Mismatches:")
        print(f"{'─'*60}")
        print(f"{'Player':<25} {'GB Min':>7} {'BDL Min':>8} {'GB Pts':>7} {'BDL Pts':>8}")
        print(f"{'─'*60}")
        for m in mismatches[:10]:
            print(f"{m['player_full_name'][:24]:<25} {m['gamebook_min'] or 'N/A':>7} {m['bdl_min'] or 'N/A':>8} {m['gamebook_pts'] or 'N/A':>7} {m['bdl_pts'] or 'N/A':>8}")

    print()


def main():
    parser = argparse.ArgumentParser(description='Check BDL data quality against NBA.com')
    parser.add_argument('--date', type=str, help='Specific date to check (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, default=1, help='Number of days to check')
    parser.add_argument('--no-details', action='store_true', help='Skip mismatch details')
    args = parser.parse_args()

    if args.date:
        dates = [args.date]
    else:
        today = date.today()
        dates = [(today - timedelta(days=i)).isoformat() for i in range(args.days)]

    for game_date in dates:
        try:
            stats = check_bdl_quality(game_date)
            mismatches = None if args.no_details else get_worst_mismatches(game_date)
            print_report(stats, mismatches)
        except Exception as e:
            print(f"\n❌ Error checking {game_date}: {e}")

    # Summary recommendation
    if len(dates) == 1:
        stats = check_bdl_quality(dates[0])
        if stats['minutes_mismatch_pct'] > 10:
            print("\n⚠️  Recommendation: Keep BDL disabled (USE_BDL_DATA = False)")
            print("   BDL data quality is still below acceptable threshold.")
            sys.exit(1)
        else:
            print("\n✅ Recommendation: Consider re-enabling BDL (USE_BDL_DATA = True)")
            print("   BDL data quality has improved.")
            sys.exit(0)


if __name__ == '__main__':
    main()

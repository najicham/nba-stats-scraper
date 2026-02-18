#!/usr/bin/env python3
"""Backfill f47 (teammate_usage_available) and f50 (multi_book_line_std) columns.

These features were implemented in Session 287 but never computed historically.
All existing rows have source='default' and value=NULL for both features.

This script computes real values from source data and updates ml_feature_store_v2.

Source data availability:
  f47: nbac_injury_report (Jan-Feb 2026 only, no Nov-Dec data)
       + player_game_summary (full season)
  f50: odds_api_player_points_props (full season, avg 80-93 players/day with 2+ books)

Usage:
  # Dry run (preview what would be updated)
  PYTHONPATH=. python bin/backfill_f47_f50.py --dry-run

  # Backfill f50 only (full season)
  PYTHONPATH=. python bin/backfill_f47_f50.py --feature 50

  # Backfill f47 only (Jan-Feb 2026)
  PYTHONPATH=. python bin/backfill_f47_f50.py --feature 47

  # Backfill both
  PYTHONPATH=. python bin/backfill_f47_f50.py --feature both

  # Custom date range
  PYTHONPATH=. python bin/backfill_f47_f50.py --feature 50 --start-date 2026-01-01 --end-date 2026-02-12
"""

import argparse
import sys
from datetime import date, datetime, timedelta

from google.cloud import bigquery

PROJECT_ID = 'nba-props-platform'
DATASET = 'nba_predictions'
TABLE = 'ml_feature_store_v2'
FULL_TABLE = f'{PROJECT_ID}.{DATASET}.{TABLE}'

# f47 injury data only available from Jan 2026
F47_EARLIEST = date(2026, 1, 1)
# Full season start
SEASON_START = date(2025, 11, 4)
# Don't backfill future dates
SEASON_LATEST = date(2026, 2, 12)  # Last game day before All-Star break

BATCH_DAYS = 7  # Process one week at a time to avoid DML limits


def backfill_f50(client: bigquery.Client, start_date: date, end_date: date, dry_run: bool = False) -> int:
    """Backfill f50 (multi_book_line_std) from odds_api data.

    Computes STDDEV(points_line) across bookmakers for each player/game_date.
    Requires >= 2 distinct bookmakers. Players with only 1 book remain NULL.
    """
    print(f"\n{'='*60}")
    print(f"BACKFILL f50 (multi_book_line_std): {start_date} to {end_date}")
    print(f"{'='*60}")

    total_updated = 0
    current = start_date

    while current <= end_date:
        batch_end = min(current + timedelta(days=BATCH_DAYS - 1), end_date)

        if dry_run:
            # Count how many rows would be affected
            count_query = f"""
            WITH latest_per_book AS (
                SELECT
                    player_lookup,
                    game_date,
                    bookmaker,
                    points_line,
                    ROW_NUMBER() OVER (
                        PARTITION BY game_date, player_lookup, bookmaker
                        ORDER BY snapshot_timestamp DESC
                    ) as rn
                FROM `{PROJECT_ID}.nba_raw.odds_api_player_points_props`
                WHERE game_date BETWEEN '{current}' AND '{batch_end}'
                    AND points_line IS NOT NULL
                    AND points_line > 0
            ),
            computed AS (
                SELECT
                    player_lookup,
                    game_date,
                    STDDEV(points_line) as line_std
                FROM latest_per_book
                WHERE rn = 1
                GROUP BY player_lookup, game_date
                HAVING COUNT(DISTINCT bookmaker) >= 2
            )
            SELECT
                COUNT(*) as match_count
            FROM computed c
            JOIN `{FULL_TABLE}` t
                ON c.player_lookup = t.player_lookup
                AND c.game_date = t.game_date
            WHERE t.game_date BETWEEN '{current}' AND '{batch_end}'
                AND t.feature_50_value IS NULL
            """
            result = client.query(count_query).result()
            count = list(result)[0].match_count
            print(f"  DRY RUN {current} to {batch_end}: would update {count} rows")
            total_updated += count
        else:
            merge_query = f"""
            MERGE INTO `{FULL_TABLE}` target
            USING (
                WITH latest_per_book AS (
                    SELECT
                        player_lookup,
                        game_date,
                        bookmaker,
                        points_line,
                        ROW_NUMBER() OVER (
                            PARTITION BY game_date, player_lookup, bookmaker
                            ORDER BY snapshot_timestamp DESC
                        ) as rn
                    FROM `{PROJECT_ID}.nba_raw.odds_api_player_points_props`
                    WHERE game_date BETWEEN '{current}' AND '{batch_end}'
                        AND points_line IS NOT NULL
                        AND points_line > 0
                )
                SELECT
                    player_lookup,
                    game_date,
                    STDDEV(points_line) as line_std
                FROM latest_per_book
                WHERE rn = 1
                GROUP BY player_lookup, game_date
                HAVING COUNT(DISTINCT bookmaker) >= 2
            ) source
            ON target.player_lookup = source.player_lookup
                AND target.game_date = source.game_date
                AND target.game_date BETWEEN '{current}' AND '{batch_end}'
                AND target.feature_50_value IS NULL
            WHEN MATCHED THEN UPDATE SET
                target.feature_50_value = source.line_std,
                target.feature_50_source = 'vegas',
                target.feature_50_quality = 80.0
            """
            job = client.query(merge_query)
            job.result()  # Wait for completion
            affected = job.num_dml_affected_rows or 0
            print(f"  {current} to {batch_end}: updated {affected} rows")
            total_updated += affected

        current = batch_end + timedelta(days=1)

    print(f"\nf50 total: {'would update' if dry_run else 'updated'} {total_updated} rows")
    return total_updated


def backfill_f47(client: bigquery.Client, start_date: date, end_date: date, dry_run: bool = False) -> int:
    """Backfill f47 (teammate_usage_available) from injury report + usage data.

    For each team with OUT/DOUBTFUL players, sums the 30-day avg usage_rate
    of those injured players. Each healthy player on that team gets this value.

    Players on teams with no injured players remain NULL (no freed usage signal).
    Injured players themselves are excluded (they won't play).
    """
    print(f"\n{'='*60}")
    print(f"BACKFILL f47 (teammate_usage_available): {start_date} to {end_date}")
    print(f"{'='*60}")

    if start_date < F47_EARLIEST:
        print(f"  WARNING: No injury report data before {F47_EARLIEST}. Adjusting start date.")
        start_date = F47_EARLIEST

    if start_date > end_date:
        print("  No date range to process. Skipping f47.")
        return 0

    total_updated = 0
    current = start_date

    while current <= end_date:
        batch_end = min(current + timedelta(days=BATCH_DAYS - 1), end_date)

        # Core CTE: compute freed usage per team per game_date
        freed_usage_cte = f"""
            WITH injured_players AS (
                SELECT DISTINCT
                    ir.report_date as game_date,
                    ir.player_lookup,
                    ir.team
                FROM `{PROJECT_ID}.nba_raw.nbac_injury_report` ir
                WHERE ir.report_date BETWEEN '{current}' AND '{batch_end}'
                    AND LOWER(ir.injury_status) IN ('out', 'doubtful')
                    AND ir.player_lookup IS NOT NULL
            ),
            injured_usage AS (
                SELECT
                    ip.game_date,
                    ip.player_lookup,
                    ip.team,
                    AVG(pgs.usage_rate) as avg_usage_rate
                FROM injured_players ip
                JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
                    ON ip.player_lookup = pgs.player_lookup
                WHERE pgs.game_date >= DATE_SUB(ip.game_date, INTERVAL 30 DAY)
                    AND pgs.game_date < ip.game_date
                    AND pgs.usage_rate IS NOT NULL
                    AND pgs.minutes_played > 10
                GROUP BY ip.game_date, ip.player_lookup, ip.team
            ),
            team_freed_usage AS (
                SELECT
                    game_date,
                    team,
                    SUM(avg_usage_rate) as total_freed_usage
                FROM injured_usage
                GROUP BY game_date, team
            ),
            player_teams AS (
                SELECT DISTINCT pgs.player_lookup, pgs.game_date, pgs.team_abbr
                FROM `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
                WHERE pgs.game_date BETWEEN '{current}' AND '{batch_end}'
            ),
            eligible_players AS (
                SELECT
                    pt.player_lookup,
                    pt.game_date,
                    MAX(tfu.total_freed_usage) as total_freed_usage
                FROM player_teams pt
                JOIN team_freed_usage tfu
                    ON pt.team_abbr = tfu.team
                    AND pt.game_date = tfu.game_date
                LEFT JOIN injured_players ip
                    ON pt.player_lookup = ip.player_lookup
                    AND pt.game_date = ip.game_date
                WHERE ip.player_lookup IS NULL
                GROUP BY pt.player_lookup, pt.game_date
            )"""

        if dry_run:
            count_query = f"""
            {freed_usage_cte}
            SELECT COUNT(*) as match_count
            FROM eligible_players ep
            JOIN `{FULL_TABLE}` t
                ON ep.player_lookup = t.player_lookup
                AND ep.game_date = t.game_date
            WHERE t.game_date BETWEEN '{current}' AND '{batch_end}'
                AND t.feature_47_value IS NULL
            """
            result = client.query(count_query).result()
            count = list(result)[0].match_count
            print(f"  DRY RUN {current} to {batch_end}: would update {count} rows")
            total_updated += count
        else:
            # BQ requires CTEs inside the USING clause for MERGE statements
            merge_query = f"""
            MERGE INTO `{FULL_TABLE}` target
            USING (
                {freed_usage_cte}
                SELECT player_lookup, game_date, total_freed_usage
                FROM eligible_players
            ) source
            ON target.player_lookup = source.player_lookup
                AND target.game_date = source.game_date
                AND target.game_date BETWEEN '{current}' AND '{batch_end}'
                AND target.feature_47_value IS NULL
            WHEN MATCHED THEN UPDATE SET
                target.feature_47_value = source.total_freed_usage,
                target.feature_47_source = 'injury_context',
                target.feature_47_quality = 80.0
            """
            job = client.query(merge_query)
            job.result()
            affected = job.num_dml_affected_rows or 0
            print(f"  {current} to {batch_end}: updated {affected} rows")
            total_updated += affected

        current = batch_end + timedelta(days=1)

    print(f"\nf47 total: {'would update' if dry_run else 'updated'} {total_updated} rows")
    return total_updated


def verify_backfill(client: bigquery.Client):
    """Post-backfill verification: check population rates."""
    print(f"\n{'='*60}")
    print("POST-BACKFILL VERIFICATION")
    print(f"{'='*60}")

    query = f"""
    SELECT
        FORMAT_DATE('%Y-%m', game_date) as month,
        COUNT(*) as total_rows,
        COUNTIF(feature_47_value IS NOT NULL) as f47_populated,
        ROUND(100.0 * COUNTIF(feature_47_value IS NOT NULL) / COUNT(*), 1) as f47_pct,
        COUNTIF(feature_50_value IS NOT NULL) as f50_populated,
        ROUND(100.0 * COUNTIF(feature_50_value IS NOT NULL) / COUNT(*), 1) as f50_pct
    FROM `{FULL_TABLE}`
    WHERE game_date >= '2025-11-01'
    GROUP BY 1
    ORDER BY 1
    """
    result = client.query(query).result()
    print(f"\n{'Month':<10} {'Total':>6} {'f47 Pop':>8} {'f47%':>6} {'f50 Pop':>8} {'f50%':>6}")
    print("-" * 50)
    for row in result:
        print(f"{row.month:<10} {row.total_rows:>6} {row.f47_populated:>8} {row.f47_pct:>5.1f}% {row.f50_populated:>8} {row.f50_pct:>5.1f}%")


def main():
    parser = argparse.ArgumentParser(description='Backfill f47 and f50 feature columns')
    parser.add_argument('--feature', choices=['47', '50', 'both'], default='both',
                        help='Which feature to backfill (default: both)')
    parser.add_argument('--start-date', type=str, default=None,
                        help='Start date (YYYY-MM-DD). Default: season start for f50, Jan 2026 for f47')
    parser.add_argument('--end-date', type=str, default=None,
                        help='End date (YYYY-MM-DD). Default: last pre-ASB game day')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview changes without writing')
    parser.add_argument('--verify-only', action='store_true',
                        help='Only run verification query')
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    if args.verify_only:
        verify_backfill(client)
        return

    end_date = date.fromisoformat(args.end_date) if args.end_date else SEASON_LATEST

    print(f"Backfill f47/f50 — {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"Target: {FULL_TABLE}")
    print(f"End date: {end_date}")

    if args.feature in ('50', 'both'):
        start = date.fromisoformat(args.start_date) if args.start_date else SEASON_START
        backfill_f50(client, start, end_date, dry_run=args.dry_run)

    if args.feature in ('47', 'both'):
        start = date.fromisoformat(args.start_date) if args.start_date else F47_EARLIEST
        backfill_f47(client, start, end_date, dry_run=args.dry_run)

    # Always verify after backfill
    verify_backfill(client)

    if args.dry_run:
        print("\n*** DRY RUN — no changes were made. Remove --dry-run to execute. ***")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Cleanup Duplicate Team Records

Session 103: Created to fix duplicate team_offense_game_summary and
team_defense_game_summary records caused by different game_id formats.

Problem:
- Evening processing created records with AWAY_HOME game_id format
- Morning processing created records with HOME_AWAY game_id format
- MERGE saw different keys → created duplicates instead of updating
- 51% of duplicates had different stats (partial vs full game data)

Solution:
- Keep the record with highest possessions (most complete data)
- Delete the duplicate with lower possessions

Usage:
    # Preview what would be deleted
    python bin/maintenance/cleanup_team_duplicates.py --dry-run

    # Execute cleanup
    python bin/maintenance/cleanup_team_duplicates.py --execute

    # Cleanup specific date range
    python bin/maintenance/cleanup_team_duplicates.py --execute --start-date 2026-01-01 --end-date 2026-02-03

Created: 2026-02-03 (Session 103)
"""

import argparse
import logging
from datetime import date, datetime
from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def find_duplicates(client: bigquery.Client, table: str, team_field: str,
                   quality_field: str, stat_field: str,
                   start_date: str, end_date: str) -> list:
    """Find duplicate records with different stats."""

    query = f"""
    WITH duplicates AS (
        SELECT
            game_date,
            {team_field} as team_abbr,
            COUNT(*) as record_count,
            MAX({quality_field}) as max_quality,
            MIN({quality_field}) as min_quality,
            MAX({stat_field}) - MIN({stat_field}) as stat_spread
        FROM `nba-props-platform.nba_analytics.{table}`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY game_date, {team_field}
        HAVING COUNT(*) > 1
    )
    SELECT
        game_date,
        team_abbr,
        record_count,
        max_quality,
        min_quality,
        stat_spread
    FROM duplicates
    ORDER BY game_date DESC, team_abbr
    """

    results = list(client.query(query).result())
    return results


def preview_cleanup(client: bigquery.Client, table: str, team_field: str,
                   quality_field: str, stat_field: str,
                   start_date: str, end_date: str) -> int:
    """Preview what records would be deleted."""

    query = f"""
    WITH ranked AS (
        SELECT
            game_id,
            game_date,
            {team_field} as team_abbr,
            {quality_field} as quality_value,
            {stat_field} as stat_value,
            ROW_NUMBER() OVER (
                PARTITION BY game_date, {team_field}
                ORDER BY {quality_field} DESC
            ) as rn
        FROM `nba-props-platform.nba_analytics.{table}`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    )
    SELECT
        game_id,
        game_date,
        team_abbr,
        quality_value,
        stat_value,
        rn
    FROM ranked
    WHERE rn > 1  -- Would be deleted
    ORDER BY game_date DESC, team_abbr
    """

    results = list(client.query(query).result())

    if results:
        logger.info(f"\n{table}: {len(results)} records would be deleted:")
        for row in results[:20]:  # Show first 20
            logger.info(f"  {row.game_date} | {row.team_abbr} | game_id={row.game_id} | {quality_field}={row.quality_value} | {stat_field}={row.stat_value}")
        if len(results) > 20:
            logger.info(f"  ... and {len(results) - 20} more")
    else:
        logger.info(f"\n{table}: No duplicates found")

    return len(results)


def execute_cleanup(client: bigquery.Client, table: str, team_field: str,
                   quality_field: str, start_date: str, end_date: str) -> int:
    """Delete duplicate records, keeping the one with highest quality value."""

    # BigQuery requires DELETE with inline subquery, not CTE
    query = f"""
    DELETE FROM `nba-props-platform.nba_analytics.{table}` t
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND game_id IN (
          SELECT game_id FROM (
              SELECT
                  game_id,
                  ROW_NUMBER() OVER (
                      PARTITION BY game_date, {team_field}
                      ORDER BY {quality_field} DESC
                  ) as rn
              FROM `nba-props-platform.nba_analytics.{table}`
              WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
          )
          WHERE rn > 1
      )
    """

    try:
        job = client.query(query)
        job.result()  # Wait for completion
        deleted = job.num_dml_affected_rows or 0
        logger.info(f"{table}: Deleted {deleted} duplicate records")
        return deleted
    except Exception as e:
        logger.error(f"{table}: Error during cleanup: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description='Cleanup duplicate team records')
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview what would be deleted without making changes')
    parser.add_argument('--execute', action='store_true',
                       help='Execute the cleanup')
    parser.add_argument('--start-date', type=str, default='2026-01-01',
                       help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str,
                       default=date.today().isoformat(),
                       help='End date (YYYY-MM-DD)')

    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        logger.error("Must specify either --dry-run or --execute")
        return 1

    client = bigquery.Client(project='nba-props-platform')

    # Table configs: (table_name, team_field, quality_field, stat_field)
    # quality_field: used to determine which record to keep (higher = better)
    # stat_field: used to show difference between duplicates
    tables = [
        ('team_offense_game_summary', 'team_abbr', 'possessions', 'fg_attempts'),
        ('team_defense_game_summary', 'defending_team_abbr', 'opp_fg_attempts', 'points_allowed'),
    ]

    logger.info(f"Date range: {args.start_date} to {args.end_date}")

    total_affected = 0

    for table, team_field, quality_field, stat_field in tables:
        # First find duplicates
        duplicates = find_duplicates(client, table, team_field, quality_field, stat_field,
                                    args.start_date, args.end_date)

        if duplicates:
            logger.info(f"\n{table}: Found {len(duplicates)} team-dates with duplicates")
            problematic = [d for d in duplicates if d.stat_spread > 0]
            if problematic:
                logger.info(f"  - {len(problematic)} have different stats ({stat_field} spread > 0)")

        if args.dry_run:
            count = preview_cleanup(client, table, team_field, quality_field, stat_field,
                                   args.start_date, args.end_date)
            total_affected += count
        else:
            count = execute_cleanup(client, table, team_field, quality_field,
                                   args.start_date, args.end_date)
            total_affected += count

    logger.info(f"\n{'Would delete' if args.dry_run else 'Deleted'} {total_affected} total duplicate records")

    if args.dry_run:
        logger.info("\nTo execute cleanup, run with --execute flag")

    return 0


if __name__ == '__main__':
    exit(main())

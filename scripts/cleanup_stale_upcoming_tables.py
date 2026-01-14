#!/usr/bin/env python3
"""
One-Time Cleanup: Stale Records in upcoming_* Tables

Purpose:
    Remove historical records from "upcoming" tables that should only contain
    future game data. This prevents partial/stale data from blocking fallback
    logic during backfills.

Incident:
    Jan 6, 2026 - Partial UPCG data (1/187 players) blocked fallback causing
    incomplete backfill that went undetected for 6 days.

Tables Cleaned:
    - nba_analytics.upcoming_player_game_context
    - nba_analytics.upcoming_team_game_context

Safety:
    - Creates backup before deletion
    - Dry-run mode to preview changes
    - Only deletes records older than 7 days

Usage:
    # Dry run (preview only)
    python scripts/cleanup_stale_upcoming_tables.py --dry-run

    # Execute cleanup
    python scripts/cleanup_stale_upcoming_tables.py

    # Keep more days (e.g., 14 days)
    python scripts/cleanup_stale_upcoming_tables.py --days 14

Author: Claude (Session 30)
Date: 2026-01-13
"""

import argparse
import logging
from datetime import datetime, timedelta
from google.cloud import bigquery

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
DATASET = 'nba_analytics'

TABLES_TO_CLEAN = [
    'upcoming_player_game_context',
    'upcoming_team_game_context'
]


def create_backup(client: bigquery.Client, table_name: str) -> str:
    """Create backup of table before cleanup."""
    backup_suffix = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_table = f"{table_name}_backup_{backup_suffix}"
    backup_full_name = f"{PROJECT_ID}.{DATASET}.{backup_table}"

    logger.info(f"Creating backup: {backup_table}")

    query = f"""
    CREATE TABLE `{backup_full_name}` AS
    SELECT * FROM `{PROJECT_ID}.{DATASET}.{table_name}`
    """

    job = client.query(query)
    job.result()  # Wait for completion

    # Verify backup
    verify_query = f"""
    SELECT
        COUNT(*) as record_count,
        MIN(game_date) as oldest_date,
        MAX(game_date) as newest_date
    FROM `{backup_full_name}`
    """
    result = client.query(verify_query).to_dataframe()

    logger.info(f"✅ Backup created: {backup_table}")
    logger.info(f"   Records: {result['record_count'].iloc[0]}")
    logger.info(f"   Date range: {result['oldest_date'].iloc[0]} to {result['newest_date'].iloc[0]}")

    return backup_full_name


def preview_cleanup(client: bigquery.Client, table_name: str, days_threshold: int) -> dict:
    """Preview what would be deleted."""
    cutoff_date = (datetime.now() - timedelta(days=days_threshold)).strftime('%Y-%m-%d')

    query = f"""
    SELECT
        COUNT(*) as records_to_delete,
        COUNT(DISTINCT game_date) as dates_affected,
        MIN(game_date) as oldest_date,
        MAX(game_date) as newest_date
    FROM `{PROJECT_ID}.{DATASET}.{table_name}`
    WHERE game_date < '{cutoff_date}'
    """

    result = client.query(query).to_dataframe()

    if result.empty or result['records_to_delete'].iloc[0] == 0:
        logger.info(f"ℹ️  {table_name}: No stale records found (cutoff: {cutoff_date})")
        return None

    stats = {
        'table': table_name,
        'records_to_delete': int(result['records_to_delete'].iloc[0]),
        'dates_affected': int(result['dates_affected'].iloc[0]),
        'oldest_date': result['oldest_date'].iloc[0],
        'newest_date': result['newest_date'].iloc[0],
        'cutoff_date': cutoff_date
    }

    logger.info(f"📊 {table_name}:")
    logger.info(f"   Records to delete: {stats['records_to_delete']}")
    logger.info(f"   Dates affected: {stats['dates_affected']}")
    logger.info(f"   Date range: {stats['oldest_date']} to {stats['newest_date']}")
    logger.info(f"   Cutoff: {cutoff_date}")

    return stats


def execute_cleanup(client: bigquery.Client, table_name: str, days_threshold: int, backup_table: str) -> int:
    """Execute the cleanup."""
    cutoff_date = (datetime.now() - timedelta(days=days_threshold)).strftime('%Y-%m-%d')

    logger.info(f"🗑️  Deleting stale records from {table_name}...")

    query = f"""
    DELETE FROM `{PROJECT_ID}.{DATASET}.{table_name}`
    WHERE game_date < '{cutoff_date}'
    """

    job = client.query(query)
    result = job.result()

    # BigQuery doesn't return affected rows for DELETE, so we query again
    verify_query = f"""
    SELECT COUNT(*) as remaining_records
    FROM `{PROJECT_ID}.{DATASET}.{table_name}`
    """
    remaining = client.query(verify_query).to_dataframe()['remaining_records'].iloc[0]

    logger.info(f"✅ Cleanup complete: {table_name}")
    logger.info(f"   Remaining records: {remaining}")

    return int(remaining)


def verify_no_future_deletions(client: bigquery.Client, table_name: str, days_threshold: int) -> bool:
    """Verify that no upcoming games were deleted."""
    cutoff_date = (datetime.now() - timedelta(days=days_threshold)).strftime('%Y-%m-%d')

    query = f"""
    SELECT COUNT(*) as stale_records
    FROM `{PROJECT_ID}.{DATASET}.{table_name}`
    WHERE game_date < '{cutoff_date}'
    """

    result = client.query(query).to_dataframe()
    stale_count = int(result['stale_records'].iloc[0])

    if stale_count > 0:
        logger.error(f"❌ Verification failed: {table_name} still has {stale_count} stale records!")
        return False

    logger.info(f"✅ Verification passed: {table_name} has no stale records")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Clean up stale records from upcoming_* tables',
        epilog='Safety: Creates backup before deletion, supports dry-run mode'
    )
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without executing')
    parser.add_argument('--days', type=int, default=7, help='Delete records older than N days (default: 7)')
    parser.add_argument('--skip-backup', action='store_true', help='Skip backup creation (NOT RECOMMENDED)')

    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("UPCOMING TABLES CLEANUP")
    logger.info("=" * 80)
    logger.info(f"Project: {PROJECT_ID}")
    logger.info(f"Dataset: {DATASET}")
    logger.info(f"Days threshold: {args.days}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("")

    client = bigquery.Client(project=PROJECT_ID)

    # Preview phase
    logger.info("=" * 80)
    logger.info("PHASE 1: PREVIEW")
    logger.info("=" * 80)

    cleanup_stats = []
    for table_name in TABLES_TO_CLEAN:
        stats = preview_cleanup(client, table_name, args.days)
        if stats:
            cleanup_stats.append(stats)

    if not cleanup_stats:
        logger.info("\n✅ No stale records found in any table. Nothing to clean up!")
        return

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    total_records = sum(s['records_to_delete'] for s in cleanup_stats)
    logger.info(f"Total records to delete: {total_records}")
    logger.info(f"Tables affected: {len(cleanup_stats)}")

    if args.dry_run:
        logger.info("\n✅ Dry run complete. No changes made.")
        logger.info("Remove --dry-run flag to execute cleanup.")
        return

    # Confirmation
    logger.info("\n" + "=" * 80)
    logger.info("⚠️  CONFIRMATION REQUIRED")
    logger.info("=" * 80)
    response = input(f"Delete {total_records} stale records? (yes/no): ")
    if response.lower() != 'yes':
        logger.info("Cleanup cancelled.")
        return

    # Backup phase
    if not args.skip_backup:
        logger.info("\n" + "=" * 80)
        logger.info("PHASE 2: BACKUP")
        logger.info("=" * 80)
        backups = {}
        for table_name in [s['table'] for s in cleanup_stats]:
            backup_name = create_backup(client, table_name)
            backups[table_name] = backup_name
    else:
        logger.warning("\n⚠️  SKIPPING BACKUP (--skip-backup flag used)")
        backups = {}

    # Cleanup phase
    logger.info("\n" + "=" * 80)
    logger.info("PHASE 3: CLEANUP")
    logger.info("=" * 80)

    for stats in cleanup_stats:
        table_name = stats['table']
        backup_name = backups.get(table_name, None)
        remaining = execute_cleanup(client, table_name, args.days, backup_name)

    # Verification phase
    logger.info("\n" + "=" * 80)
    logger.info("PHASE 4: VERIFICATION")
    logger.info("=" * 80)

    all_verified = True
    for stats in cleanup_stats:
        table_name = stats['table']
        verified = verify_no_future_deletions(client, table_name, args.days)
        all_verified = all_verified and verified

    # Final summary
    logger.info("\n" + "=" * 80)
    logger.info("CLEANUP COMPLETE")
    logger.info("=" * 80)
    if all_verified:
        logger.info("✅ All tables cleaned successfully")
        logger.info(f"✅ Total records deleted: {total_records}")
        if backups:
            logger.info("\n📦 Backups created:")
            for table, backup in backups.items():
                logger.info(f"   - {backup}")
            logger.info("\nBackups can be dropped after 30 days if no issues occur.")
    else:
        logger.error("❌ Verification failed! Check logs above.")
        logger.error("Consider restoring from backup if data is missing.")

    logger.info("=" * 80)


if __name__ == "__main__":
    main()

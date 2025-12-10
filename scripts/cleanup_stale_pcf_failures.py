#!/usr/bin/env python3
"""
Clean up stale PCF (PlayerCompositeFactorsProcessor) failure records.

This script removes obsolete failure records from nba_processing.precompute_failures
that were created during a failed run that was later successfully re-run. These are
identified by:
- processor_name = 'PlayerCompositeFactorsProcessor'
- failure_category = 'calculation_error'
- failure_reason containing 'hash_utils' (import error that was fixed)
- Date range where PCF table has actual data

Usage:
    # Dry run (show what would be deleted)
    python scripts/cleanup_stale_pcf_failures.py --dry-run

    # Actually delete the records
    python scripts/cleanup_stale_pcf_failures.py

    # Custom date range
    python scripts/cleanup_stale_pcf_failures.py --start-date 2021-12-01 --end-date 2021-12-06
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


def parse_args():
    parser = argparse.ArgumentParser(description='Clean up stale PCF failure records')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without actually deleting')
    parser.add_argument('--start-date', type=str, default='2021-12-01', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, default='2021-12-06', help='End date (YYYY-MM-DD)')
    parser.add_argument('--project-id', type=str, default='nba-props-platform', help='GCP project ID')
    return parser.parse_args()


def verify_pcf_data_exists(bq_client: bigquery.Client, start_date: str, end_date: str) -> dict:
    """Verify that PCF table has data for the date range."""

    query = f"""
    SELECT analysis_date, COUNT(*) as player_count
    FROM nba_warehouse.player_composite_factors
    WHERE analysis_date >= '{start_date}' AND analysis_date <= '{end_date}'
    GROUP BY analysis_date
    ORDER BY analysis_date
    """

    logger.info("Verifying PCF data exists for date range...")
    result = bq_client.query(query).result()

    data_by_date = {}
    for row in result:
        data_by_date[str(row.analysis_date)] = row.player_count
        logger.info(f"  {row.analysis_date}: {row.player_count} players")

    return data_by_date


def count_stale_failures(bq_client: bigquery.Client, start_date: str, end_date: str) -> int:
    """Count the number of stale failure records that match the criteria."""

    query = f"""
    SELECT COUNT(*) as failure_count
    FROM nba_processing.precompute_failures
    WHERE processor_name = 'PlayerCompositeFactorsProcessor'
      AND failure_category = 'calculation_error'
      AND failure_reason LIKE '%hash_utils%'
      AND analysis_date >= '{start_date}'
      AND analysis_date <= '{end_date}'
    """

    logger.info("Counting stale failure records...")
    result = bq_client.query(query).result()
    count = list(result)[0].failure_count
    logger.info(f"  Found {count} stale failure records")

    return count


def get_sample_failures(bq_client: bigquery.Client, start_date: str, end_date: str, limit: int = 5):
    """Get a sample of the failure records to be deleted."""

    query = f"""
    SELECT
        analysis_date,
        entity_id,
        failure_reason,
        created_at
    FROM nba_processing.precompute_failures
    WHERE processor_name = 'PlayerCompositeFactorsProcessor'
      AND failure_category = 'calculation_error'
      AND failure_reason LIKE '%hash_utils%'
      AND analysis_date >= '{start_date}'
      AND analysis_date <= '{end_date}'
    ORDER BY analysis_date, entity_id
    LIMIT {limit}
    """

    logger.info(f"\nSample of {limit} records to be deleted:")
    result = bq_client.query(query).result()

    for row in result:
        # Truncate failure_reason for display
        reason_preview = row.failure_reason[:80] + "..." if len(row.failure_reason) > 80 else row.failure_reason
        logger.info(f"  Date: {row.analysis_date}, Entity: {row.entity_id}, Created: {row.created_at}")
        logger.info(f"    Reason: {reason_preview}")


def delete_stale_failures(bq_client: bigquery.Client, start_date: str, end_date: str, dry_run: bool = False) -> int:
    """Delete the stale failure records."""

    delete_query = f"""
    DELETE FROM nba_processing.precompute_failures
    WHERE processor_name = 'PlayerCompositeFactorsProcessor'
      AND failure_category = 'calculation_error'
      AND failure_reason LIKE '%hash_utils%'
      AND analysis_date >= '{start_date}'
      AND analysis_date <= '{end_date}'
    """

    if dry_run:
        logger.info("\n[DRY RUN] Would execute DELETE query:")
        logger.info(delete_query)
        return 0

    logger.info("\nExecuting DELETE query...")
    result = bq_client.query(delete_query).result()

    # BigQuery DELETE doesn't return row count directly, so we need to check
    logger.info("DELETE query completed successfully")

    return result.total_rows if hasattr(result, 'total_rows') else 0


def verify_deletion(bq_client: bigquery.Client, start_date: str, end_date: str) -> int:
    """Verify that the deletion was successful by counting remaining records."""

    logger.info("\nVerifying deletion...")
    remaining = count_stale_failures(bq_client, start_date, end_date)

    if remaining == 0:
        logger.info("  SUCCESS: All stale failure records have been deleted")
    else:
        logger.warning(f"  WARNING: {remaining} failure records still remain")

    return remaining


def main():
    args = parse_args()

    logger.info("=" * 70)
    logger.info("STALE PCF FAILURE CLEANUP SCRIPT")
    logger.info("=" * 70)
    logger.info(f"Date range: {args.start_date} to {args.end_date}")

    if args.dry_run:
        logger.info("DRY RUN MODE - No deletions will be made")

    logger.info("")

    # Initialize BigQuery client
    bq_client = bigquery.Client(project=args.project_id)

    # Step 1: Verify PCF data exists
    logger.info("STEP 1: Verify PCF table has data for the date range")
    logger.info("-" * 70)
    pcf_data = verify_pcf_data_exists(bq_client, args.start_date, args.end_date)

    if not pcf_data:
        logger.error("ERROR: No PCF data found for this date range. Aborting cleanup.")
        return

    logger.info(f"  Confirmed PCF data exists for {len(pcf_data)} dates")

    # Step 2: Count stale failure records
    logger.info("\nSTEP 2: Count stale failure records")
    logger.info("-" * 70)
    before_count = count_stale_failures(bq_client, args.start_date, args.end_date)

    if before_count == 0:
        logger.info("No stale failure records found. Nothing to clean up.")
        return

    # Show sample records
    get_sample_failures(bq_client, args.start_date, args.end_date)

    # Step 3: Delete stale failure records
    logger.info("\nSTEP 3: Delete stale failure records")
    logger.info("-" * 70)
    delete_stale_failures(bq_client, args.start_date, args.end_date, dry_run=args.dry_run)

    # Step 4: Verify deletion (only if not dry run)
    if not args.dry_run:
        logger.info("\nSTEP 4: Verify deletion")
        logger.info("-" * 70)
        after_count = verify_deletion(bq_client, args.start_date, args.end_date)

        # Final summary
        logger.info("\n" + "=" * 70)
        logger.info("CLEANUP COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Records before:  {before_count}")
        logger.info(f"Records after:   {after_count}")
        logger.info(f"Records deleted: {before_count - after_count}")
        logger.info("=" * 70)
    else:
        logger.info("\n" + "=" * 70)
        logger.info("DRY RUN COMPLETE - No changes made")
        logger.info(f"Would delete {before_count} records")
        logger.info("Run without --dry-run to actually delete these records")
        logger.info("=" * 70)


if __name__ == '__main__':
    main()

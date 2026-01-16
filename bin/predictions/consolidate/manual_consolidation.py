#!/usr/bin/env python3
"""
Manual consolidation trigger script
Consolidates staging tables for a specific batch into the main predictions table

Usage:
    # Consolidate with cleanup (default)
    python manual_consolidation.py --batch-id batch_2025-12-31_1767227776 --game-date 2025-12-31

    # Consolidate without cleanup (keep staging tables)
    python manual_consolidation.py --batch-id batch_2025-12-31_1767227776 --game-date 2025-12-31 --no-cleanup

    # Dry run (show what would happen)
    python manual_consolidation.py --batch-id batch_2025-12-31_1767227776 --game-date 2025-12-31 --dry-run
"""

import argparse
import sys
sys.path.insert(0, '/home/naji/code/nba-stats-scraper/predictions/worker')

from batch_staging_writer import BatchConsolidator
from google.cloud import bigquery


def main():
    parser = argparse.ArgumentParser(
        description="Manually trigger consolidation for a specific batch"
    )
    parser.add_argument(
        "--batch-id", "-b",
        required=True,
        help="Batch ID to consolidate (e.g., batch_2025-12-31_1767227776)"
    )
    parser.add_argument(
        "--game-date", "-d",
        required=True,
        help="Game date for the batch (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--project", "-p",
        default="nba-props-platform",
        help="GCP project ID (default: nba-props-platform)"
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Keep staging tables after consolidation"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes"
    )
    args = parser.parse_args()

    print(f"Manually triggering consolidation for batch: {args.batch_id}")
    print(f"   Game date: {args.game_date}")
    print(f"   Project: {args.project}")
    print(f"   Cleanup: {not args.no_cleanup}")
    print(f"   Dry run: {args.dry_run}")
    print()

    if args.dry_run:
        print("DRY RUN - No changes will be made")
        print()

    # Create BigQuery client and consolidator
    client = bigquery.Client(project=args.project)
    consolidator = BatchConsolidator(client, args.project)

    # Run consolidation
    print("Running consolidation...")
    result = consolidator.consolidate_batch(
        batch_id=args.batch_id,
        game_date=args.game_date,
        cleanup=not args.no_cleanup
    )

    # Display results
    print()
    if result.success:
        print("Consolidation SUCCEEDED!")
        print(f"   Rows affected: {result.rows_affected}")
        print(f"   Staging tables merged: {result.staging_tables_merged}")
        print(f"   Staging tables cleaned: {result.staging_tables_cleaned}")
        return 0
    else:
        print("Consolidation FAILED!")
        print(f"   Error: {result.error_message}")
        return 1


if __name__ == '__main__':
    sys.exit(main())

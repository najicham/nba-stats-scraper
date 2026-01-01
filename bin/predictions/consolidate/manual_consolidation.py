#!/usr/bin/env python3
"""
Manual consolidation trigger script
Consolidates staging tables for a specific batch into the main predictions table
"""

import sys
sys.path.insert(0, '/home/naji/code/nba-stats-scraper/predictions/worker')

from batch_staging_writer import BatchConsolidator
from google.cloud import bigquery

PROJECT_ID = 'nba-props-platform'
BATCH_ID = 'batch_2025-12-31_1767227776'
GAME_DATE = '2025-12-31'

def main():
    print(f"🔧 Manually triggering consolidation for batch: {BATCH_ID}")
    print(f"   Game date: {GAME_DATE}")
    print(f"   Project: {PROJECT_ID}")
    print()

    # Create BigQuery client and consolidator
    client = bigquery.Client(project=PROJECT_ID)
    consolidator = BatchConsolidator(client, PROJECT_ID)

    # Run consolidation
    print("🚀 Running consolidation...")
    result = consolidator.consolidate_batch(
        batch_id=BATCH_ID,
        game_date=GAME_DATE,
        cleanup=True  # Delete staging tables after successful merge
    )

    # Display results
    print()
    if result.success:
        print(f"✅ Consolidation SUCCEEDED!")
        print(f"   Rows affected: {result.rows_affected}")
        print(f"   Staging tables merged: {result.staging_tables_merged}")
        print(f"   Staging tables cleaned: {result.staging_tables_cleaned}")
        return 0
    else:
        print(f"❌ Consolidation FAILED!")
        print(f"   Error: {result.error_message}")
        return 1

if __name__ == '__main__':
    sys.exit(main())

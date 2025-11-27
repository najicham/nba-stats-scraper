#!/usr/bin/env python3
"""
Migration: Add tracing columns to prediction_worker_runs table

Adds columns for improved tracing and debugging:
- Trigger tracking (pubsub message ID)
- Cloud Run metadata
- Retry tracking

Usage:
    python scripts/migrations/add_phase5_tracing_columns.py [--dry-run]

Version: 1.0
Created: 2025-11-27
"""

import argparse
import logging
import sys
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Table to modify
PROJECT_ID = 'nba-props-platform'
TABLE_ID = f'{PROJECT_ID}.nba_predictions.prediction_worker_runs'

# New columns to add
NEW_COLUMNS = [
    # Trigger tracking
    {'name': 'trigger_source', 'type': 'STRING', 'description': 'What triggered this run (pubsub, scheduler, manual, api)'},
    {'name': 'trigger_message_id', 'type': 'STRING', 'description': 'Pub/Sub message ID for correlation'},

    # Cloud Run metadata
    {'name': 'cloud_run_service', 'type': 'STRING', 'description': 'K_SERVICE environment variable'},
    {'name': 'cloud_run_revision', 'type': 'STRING', 'description': 'K_REVISION environment variable'},

    # Retry tracking
    {'name': 'retry_attempt', 'type': 'INTEGER', 'description': 'Which retry attempt (1, 2, 3...)'},

    # Parent correlation
    {'name': 'batch_id', 'type': 'STRING', 'description': 'Batch ID if part of bulk prediction request'},
]


def get_existing_columns(client: bigquery.Client, table_id: str) -> set:
    """Get set of existing column names."""
    try:
        table = client.get_table(table_id)
        return {field.name for field in table.schema}
    except Exception as e:
        logger.error(f"Failed to get table schema: {e}")
        raise


def add_columns(client: bigquery.Client, table_id: str, dry_run: bool = False) -> list:
    """
    Add new columns to the table.

    Args:
        client: BigQuery client
        table_id: Full table ID
        dry_run: If True, only show what would be done

    Returns:
        List of columns added
    """
    existing_columns = get_existing_columns(client, table_id)
    logger.info(f"Existing columns: {len(existing_columns)}")

    columns_to_add = []
    for col in NEW_COLUMNS:
        if col['name'] not in existing_columns:
            columns_to_add.append(col)
        else:
            logger.info(f"  Column '{col['name']}' already exists - skipping")

    if not columns_to_add:
        logger.info("No new columns to add - schema is up to date")
        return []

    logger.info(f"\nColumns to add: {len(columns_to_add)}")
    for col in columns_to_add:
        logger.info(f"  + {col['name']:30} {col['type']:10} - {col['description']}")

    if dry_run:
        logger.info("\n[DRY RUN] No changes made")
        return columns_to_add

    # Get current table and schema
    table = client.get_table(table_id)
    original_schema = list(table.schema)

    # Add new columns to schema
    new_schema = original_schema.copy()
    for col in columns_to_add:
        new_field = bigquery.SchemaField(
            name=col['name'],
            field_type=col['type'],
            mode='NULLABLE',
            description=col['description']
        )
        new_schema.append(new_field)

    # Update table schema
    table.schema = new_schema
    client.update_table(table, ['schema'])

    logger.info(f"\nSuccessfully added {len(columns_to_add)} columns to {table_id}")
    return columns_to_add


def main():
    parser = argparse.ArgumentParser(description='Add tracing columns to prediction_worker_runs table')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--project', default=PROJECT_ID, help='GCP project ID')
    args = parser.parse_args()

    table_id = f'{args.project}.nba_predictions.prediction_worker_runs'

    logger.info(f"Migration: Add Phase 5 tracing columns")
    logger.info(f"Table: {table_id}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("")

    try:
        client = bigquery.Client(project=args.project)
        added = add_columns(client, table_id, dry_run=args.dry_run)

        if added and not args.dry_run:
            logger.info("\nVerifying new schema...")
            new_columns = get_existing_columns(client, table_id)
            logger.info(f"Total columns now: {len(new_columns)}")

        return 0

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""
Migration: Create Phase Completions BigQuery Tables

Creates BigQuery tables for tracking phase completion status as backup to Firestore:
1. phase_completions - Individual processor completion records
2. phase_completion_status - Aggregated status per phase/date

This provides resilient phase tracking with:
- BigQuery backup when Firestore is unavailable
- Analytics and monitoring capabilities
- Historical completion data for debugging

Usage:
    python scripts/migrations/create_phase_completions_tables.py [--dry-run]
    python scripts/migrations/create_phase_completions_tables.py --project=nba-props-platform

Version: 1.0
Created: 2026-01-23
"""

import argparse
import logging
import sys
from google.cloud import bigquery
from google.cloud.exceptions import NotFound, Conflict

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Configuration
DEFAULT_PROJECT_ID = 'nba-props-platform'
DATASET_ID = 'nba_orchestration'

# Individual completion records table
COMPLETIONS_TABLE = 'phase_completions'
COMPLETIONS_SCHEMA = [
    bigquery.SchemaField("phase", "STRING", mode="REQUIRED",
                        description="Phase name (phase2, phase3, phase4, phase5)"),
    bigquery.SchemaField("game_date", "DATE", mode="REQUIRED",
                        description="Game date being processed"),
    bigquery.SchemaField("processor_name", "STRING", mode="REQUIRED",
                        description="Processor that completed"),
    bigquery.SchemaField("status", "STRING", mode="REQUIRED",
                        description="Completion status (success, partial, failed)"),
    bigquery.SchemaField("record_count", "INTEGER", mode="NULLABLE",
                        description="Number of records processed"),
    bigquery.SchemaField("correlation_id", "STRING", mode="NULLABLE",
                        description="Correlation ID for tracing"),
    bigquery.SchemaField("execution_id", "STRING", mode="NULLABLE",
                        description="Execution ID"),
    bigquery.SchemaField("completed_at", "TIMESTAMP", mode="REQUIRED",
                        description="When processor completed"),
    bigquery.SchemaField("is_incremental", "BOOLEAN", mode="NULLABLE",
                        description="Whether this was incremental processing"),
    bigquery.SchemaField("entities_changed", "STRING", mode="REPEATED",
                        description="Entities that changed (for incremental)"),
    bigquery.SchemaField("metadata", "JSON", mode="NULLABLE",
                        description="Additional metadata as JSON"),
    bigquery.SchemaField("inserted_at", "TIMESTAMP", mode="REQUIRED",
                        description="When record was inserted"),
]

# Aggregated status table
STATUS_TABLE = 'phase_completion_status'
STATUS_SCHEMA = [
    bigquery.SchemaField("phase", "STRING", mode="REQUIRED",
                        description="Phase name"),
    bigquery.SchemaField("game_date", "DATE", mode="REQUIRED",
                        description="Game date"),
    bigquery.SchemaField("completed_count", "INTEGER", mode="REQUIRED",
                        description="Number of processors completed"),
    bigquery.SchemaField("expected_count", "INTEGER", mode="REQUIRED",
                        description="Expected number of processors"),
    bigquery.SchemaField("completed_processors", "STRING", mode="REPEATED",
                        description="List of completed processor names"),
    bigquery.SchemaField("missing_processors", "STRING", mode="REPEATED",
                        description="List of missing processor names"),
    bigquery.SchemaField("is_triggered", "BOOLEAN", mode="REQUIRED",
                        description="Whether next phase was triggered"),
    bigquery.SchemaField("triggered_at", "TIMESTAMP", mode="NULLABLE",
                        description="When next phase was triggered"),
    bigquery.SchemaField("trigger_reason", "STRING", mode="NULLABLE",
                        description="Reason for triggering (all_complete, timeout, etc.)"),
    bigquery.SchemaField("mode", "STRING", mode="NULLABLE",
                        description="Orchestration mode (overnight, same_day, tomorrow)"),
    bigquery.SchemaField("first_completion_at", "TIMESTAMP", mode="NULLABLE",
                        description="When first processor completed"),
    bigquery.SchemaField("last_completion_at", "TIMESTAMP", mode="NULLABLE",
                        description="When last processor completed"),
    bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED",
                        description="When record was last updated"),
]


def create_dataset_if_not_exists(client: bigquery.Client, project_id: str,
                                  dataset_id: str, dry_run: bool = False) -> bool:
    """
    Create dataset if it doesn't exist.

    Args:
        client: BigQuery client
        project_id: GCP project ID
        dataset_id: Dataset name
        dry_run: If True, only show what would be done

    Returns:
        True if dataset exists or was created
    """
    dataset_ref = f"{project_id}.{dataset_id}"

    try:
        client.get_dataset(dataset_ref)
        logger.info(f"Dataset {dataset_ref} already exists")
        return True
    except NotFound:
        if dry_run:
            logger.info(f"[DRY RUN] Would create dataset: {dataset_ref}")
            return True

        logger.info(f"Creating dataset: {dataset_ref}")
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US"
        dataset.description = "Orchestration tracking and monitoring data"

        client.create_dataset(dataset, exists_ok=True)
        logger.info(f"Created dataset: {dataset_ref}")
        return True


def create_table(client: bigquery.Client, project_id: str, dataset_id: str,
                 table_id: str, schema: list, partition_field: str = None,
                 clustering_fields: list = None, dry_run: bool = False) -> bool:
    """
    Create a BigQuery table with the given schema.

    Args:
        client: BigQuery client
        project_id: GCP project ID
        dataset_id: Dataset name
        table_id: Table name
        schema: Table schema
        partition_field: Field to partition by (optional)
        clustering_fields: Fields to cluster by (optional)
        dry_run: If True, only show what would be done

    Returns:
        True if table exists or was created
    """
    full_table_id = f"{project_id}.{dataset_id}.{table_id}"

    # Check if table exists
    try:
        existing_table = client.get_table(full_table_id)
        logger.info(f"Table {full_table_id} already exists ({existing_table.num_rows} rows)")

        # Check if schema needs updating
        existing_fields = {f.name for f in existing_table.schema}
        new_fields = [f for f in schema if f.name not in existing_fields]

        if new_fields:
            if dry_run:
                logger.info(f"[DRY RUN] Would add {len(new_fields)} new columns to {full_table_id}")
                for f in new_fields:
                    logger.info(f"  + {f.name}: {f.field_type}")
            else:
                # Add new columns
                updated_schema = list(existing_table.schema) + new_fields
                existing_table.schema = updated_schema
                client.update_table(existing_table, ['schema'])
                logger.info(f"Added {len(new_fields)} new columns to {full_table_id}")

        return True

    except NotFound:
        pass  # Table doesn't exist, will create

    if dry_run:
        logger.info(f"[DRY RUN] Would create table: {full_table_id}")
        logger.info(f"  Schema: {len(schema)} fields")
        if partition_field:
            logger.info(f"  Partition by: {partition_field}")
        if clustering_fields:
            logger.info(f"  Cluster by: {clustering_fields}")
        return True

    # Create table
    logger.info(f"Creating table: {full_table_id}")

    table = bigquery.Table(full_table_id, schema=schema)
    table.description = f"Phase completion tracking - {table_id}"

    # Configure partitioning
    if partition_field:
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field=partition_field
        )

    # Configure clustering
    if clustering_fields:
        table.clustering_fields = clustering_fields

    try:
        client.create_table(table)
        logger.info(f"Created table: {full_table_id}")
        return True
    except Conflict:
        logger.info(f"Table {full_table_id} already exists (race condition)")
        return True
    except Exception as e:
        logger.error(f"Failed to create table {full_table_id}: {e}")
        return False


def create_views(client: bigquery.Client, project_id: str, dataset_id: str,
                 dry_run: bool = False) -> bool:
    """
    Create useful views for monitoring.

    Args:
        client: BigQuery client
        project_id: GCP project ID
        dataset_id: Dataset name
        dry_run: If True, only show what would be done

    Returns:
        True if views created successfully
    """
    views = [
        {
            "name": "v_phase_completion_summary",
            "description": "Summary of phase completions by date",
            "query": f"""
                SELECT
                    game_date,
                    phase,
                    completed_count,
                    expected_count,
                    ROUND(completed_count / NULLIF(expected_count, 0) * 100, 1) as completion_pct,
                    is_triggered,
                    trigger_reason,
                    mode,
                    TIMESTAMP_DIFF(last_completion_at, first_completion_at, MINUTE) as duration_minutes,
                    updated_at
                FROM `{project_id}.{dataset_id}.phase_completion_status`
                ORDER BY game_date DESC, phase
            """
        },
        {
            "name": "v_recent_completions",
            "description": "Recent phase completions (last 7 days)",
            "query": f"""
                SELECT
                    phase,
                    game_date,
                    processor_name,
                    status,
                    record_count,
                    completed_at,
                    correlation_id
                FROM `{project_id}.{dataset_id}.phase_completions`
                WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
                ORDER BY completed_at DESC
            """
        },
        {
            "name": "v_incomplete_phases",
            "description": "Phases that haven't triggered (potentially stuck)",
            "query": f"""
                SELECT
                    phase,
                    game_date,
                    completed_count,
                    expected_count,
                    ARRAY_TO_STRING(missing_processors, ', ') as missing,
                    first_completion_at,
                    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), first_completion_at, MINUTE) as waiting_minutes,
                    updated_at
                FROM `{project_id}.{dataset_id}.phase_completion_status`
                WHERE is_triggered = FALSE
                    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
                ORDER BY first_completion_at ASC
            """
        },
    ]

    for view_def in views:
        view_id = f"{project_id}.{dataset_id}.{view_def['name']}"

        if dry_run:
            logger.info(f"[DRY RUN] Would create view: {view_id}")
            continue

        view = bigquery.Table(view_id)
        view.view_query = view_def["query"]
        view.description = view_def["description"]

        try:
            # Delete existing view if it exists
            try:
                client.delete_table(view_id)
            except NotFound:
                pass

            client.create_table(view)
            logger.info(f"Created view: {view_id}")
        except Exception as e:
            logger.error(f"Failed to create view {view_id}: {e}")
            return False

    return True


def main():
    parser = argparse.ArgumentParser(
        description='Create phase completions BigQuery tables'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--project',
        default=DEFAULT_PROJECT_ID,
        help='GCP project ID'
    )
    parser.add_argument(
        '--skip-views',
        action='store_true',
        help='Skip creating views'
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Migration: Create Phase Completions BigQuery Tables")
    logger.info("=" * 60)
    logger.info(f"Project: {args.project}")
    logger.info(f"Dataset: {DATASET_ID}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("")

    try:
        client = bigquery.Client(project=args.project)

        # 1. Create dataset
        logger.info("Step 1: Ensure dataset exists")
        if not create_dataset_if_not_exists(client, args.project, DATASET_ID, args.dry_run):
            return 1
        logger.info("")

        # 2. Create completions table
        logger.info("Step 2: Create phase_completions table")
        if not create_table(
            client, args.project, DATASET_ID,
            COMPLETIONS_TABLE, COMPLETIONS_SCHEMA,
            partition_field="game_date",
            clustering_fields=["phase", "processor_name"],
            dry_run=args.dry_run
        ):
            return 1
        logger.info("")

        # 3. Create status table
        logger.info("Step 3: Create phase_completion_status table")
        if not create_table(
            client, args.project, DATASET_ID,
            STATUS_TABLE, STATUS_SCHEMA,
            partition_field="game_date",
            clustering_fields=["phase"],
            dry_run=args.dry_run
        ):
            return 1
        logger.info("")

        # 4. Create views (optional)
        if not args.skip_views:
            logger.info("Step 4: Create monitoring views")
            if not create_views(client, args.project, DATASET_ID, args.dry_run):
                return 1
            logger.info("")

        logger.info("=" * 60)
        logger.info("Migration completed successfully!")
        logger.info("=" * 60)

        if not args.dry_run:
            logger.info("")
            logger.info("Tables created:")
            logger.info(f"  - {args.project}.{DATASET_ID}.{COMPLETIONS_TABLE}")
            logger.info(f"  - {args.project}.{DATASET_ID}.{STATUS_TABLE}")
            if not args.skip_views:
                logger.info("")
                logger.info("Views created:")
                logger.info(f"  - {args.project}.{DATASET_ID}.v_phase_completion_summary")
                logger.info(f"  - {args.project}.{DATASET_ID}.v_recent_completions")
                logger.info(f"  - {args.project}.{DATASET_ID}.v_incomplete_phases")

        return 0

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())

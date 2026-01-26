#!/usr/bin/env python3
"""
Create phase_completions table in BigQuery.

This table is required by the CompletionTracker to record processor completions.
Schema is defined in orchestration/shared/utils/completion_tracker.py

Usage:
    python bin/maintenance/create_phase_completions_table.py
"""

from google.cloud import bigquery

def create_phase_completions_table():
    """Create phase_completions table with proper schema."""

    # Initialize client
    client = bigquery.Client(project="nba-props-platform")

    # Define table ID
    table_id = "nba-props-platform.nba_orchestration.phase_completions"

    # Check if table already exists
    try:
        client.get_table(table_id)
        print(f"✓ Table already exists: {table_id}")
        return
    except Exception:
        print(f"Table does not exist, creating: {table_id}")

    # Define schema (from completion_tracker.py)
    schema = [
        bigquery.SchemaField("phase", "STRING", mode="REQUIRED", description="Phase name (phase2, phase3, phase4, phase5)"),
        bigquery.SchemaField("game_date", "DATE", mode="REQUIRED", description="Game date being processed"),
        bigquery.SchemaField("processor_name", "STRING", mode="REQUIRED", description="Processor that completed"),
        bigquery.SchemaField("status", "STRING", mode="REQUIRED", description="Completion status (success, partial, failed)"),
        bigquery.SchemaField("record_count", "INTEGER", mode="NULLABLE", description="Number of records processed"),
        bigquery.SchemaField("correlation_id", "STRING", mode="NULLABLE", description="Correlation ID for tracing"),
        bigquery.SchemaField("execution_id", "STRING", mode="NULLABLE", description="Execution ID"),
        bigquery.SchemaField("completed_at", "TIMESTAMP", mode="REQUIRED", description="When processor completed"),
        bigquery.SchemaField("is_incremental", "BOOLEAN", mode="NULLABLE", description="Whether this was incremental processing"),
        bigquery.SchemaField("entities_changed", "STRING", mode="REPEATED", description="Entities that changed (for incremental)"),
        bigquery.SchemaField("metadata", "JSON", mode="NULLABLE", description="Additional metadata as JSON"),
        bigquery.SchemaField("inserted_at", "TIMESTAMP", mode="REQUIRED", description="When record was inserted"),
    ]

    # Create table with partitioning on game_date for efficient queries
    table = bigquery.Table(table_id, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="game_date",
        expiration_ms=None,  # No expiration
    )

    # Cluster by phase and processor_name for efficient filtering
    table.clustering_fields = ["phase", "processor_name"]

    # Add table description
    table.description = "Phase completion tracking - records when each processor completes for each phase/date"

    # Create table
    table = client.create_table(table)

    print(f"✅ Created table: {table.project}.{table.dataset_id}.{table.table_id}")
    print(f"   Partitioned by: game_date (DAY)")
    print(f"   Clustered by: phase, processor_name")
    print(f"   Schema fields: {len(schema)}")

    return table


if __name__ == "__main__":
    create_phase_completions_table()

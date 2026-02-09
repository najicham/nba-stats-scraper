# predictions/shared/batch_staging_writer.py

"""
Batch Staging Writer - Eliminates BigQuery DML Concurrency Issues

This module implements a two-phase write pattern that avoids BigQuery's
DML concurrency limits (20 concurrent DML operations per table):

Phase 1 (Workers): Each worker writes to its own staging table using
batch INSERT (load_table_from_json). This is NOT a DML operation and
has no concurrency limits.

Phase 2 (Coordinator): A single MERGE operation consolidates all staging
tables into the main predictions table, then cleans up staging tables.

CRITICAL FIX (Session 92): Added distributed locking to prevent race conditions
that caused duplicate rows with different prediction_ids.

Race Condition Bug:
- When two consolidations run concurrently for the same game_date
- Both check main table for existing business keys
- Both find "NOT MATCHED" (before either commits)
- Both INSERT → duplicate rows with different prediction_ids
- Evidence: 5 duplicates on Jan 11, 2026 (timestamps 0.4s apart)

Architecture:
- BatchStagingWriter: Used by workers to write to individual staging tables
- BatchConsolidator: Used by coordinator to merge all staging tables
- DistributedLock: Distributed lock (Firestore) to prevent concurrent merges

Benefits:
- No DML concurrency errors (workers use INSERT, not MERGE)
- No race condition duplicates (distributed lock on game_date)
- Single MERGE per batch (coordinator only)
- Proper deduplication via ROW_NUMBER
- Clean separation of concerns
"""

import logging
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import numpy as np

from google.cloud import bigquery
from google.api_core import exceptions as gcp_exceptions


def convert_numpy_types(obj: Any) -> Any:
    """
    Convert numpy types to Python native types for JSON serialization.

    BigQuery load_table_from_json fails if numpy types (np.float64, np.int64, etc.)
    are present in the data because they don't serialize to JSON correctly.
    Also converts NaN/Inf floats to None since BigQuery rejects these values.

    Args:
        obj: Any value that might contain numpy types

    Returns:
        The same value with numpy types converted to Python natives
    """
    import math

    if isinstance(obj, dict):
        return {k: convert_numpy_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        val = float(obj)
        # Convert NaN/Inf to None (BigQuery rejects these)
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    elif isinstance(obj, float):
        # Also handle Python floats with NaN/Inf
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, np.ndarray):
        return [convert_numpy_types(x) for x in obj.tolist()]
    elif isinstance(obj, np.bool_):
        return bool(obj)
    else:
        return obj

# Import distributed lock to prevent race conditions
from predictions.shared.distributed_lock import DistributedLock, LockAcquisitionError

# Import retry decorators for resilience
from shared.utils.bigquery_retry import retry_on_quota_exceeded, retry_on_serialization

logger = logging.getLogger(__name__)

# Constants
STAGING_DATASET = "nba_predictions"
MAIN_PREDICTIONS_TABLE = "player_prop_predictions"

# Session 81: Edge-based filtering WAS here but REMOVED in Session 102
# Edge filtering now happens at QUERY TIME, not write time
# All predictions are stored; use edge >= 3 filter in queries for betting decisions
# Analysis shows: edge >= 3 has 65% hit rate, +24% ROI; edge < 3 has ~50% hit rate
import os
# Legacy constant kept for reference but no longer used in MERGE
MIN_EDGE_THRESHOLD = float(os.environ.get('MIN_EDGE_THRESHOLD', '3.0'))


@dataclass
class StagingWriteResult:
    """Result of writing to a staging table."""
    staging_table_name: str
    rows_written: int
    success: bool
    error_message: Optional[str] = None


@dataclass
class ConsolidationResult:
    """Result of consolidating staging tables."""
    rows_affected: int
    staging_tables_merged: int
    staging_tables_cleaned: int
    success: bool
    error_message: Optional[str] = None


class BatchStagingWriter:
    """
    Writes predictions to individual staging tables using batch INSERT.

    Used by workers to avoid DML concurrency limits. Each worker writes
    to its own staging table using load_table_from_json (not MERGE).

    Usage:
        writer = BatchStagingWriter(bq_client, project_id)
        result = writer.write_to_staging(predictions, batch_id, worker_id)
        if result.success:
            # Staging table ready for consolidation
            print(f"Wrote {result.rows_written} rows to {result.staging_table_name}")
    """

    def __init__(self, bq_client: bigquery.Client, project_id: str, dataset_prefix: str = ''):
        """
        Initialize the staging writer.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
            dataset_prefix: Optional dataset prefix for test isolation (e.g., "test")
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.dataset_prefix = dataset_prefix
        # Construct dataset name with optional prefix
        self.staging_dataset = f"{dataset_prefix}_nba_predictions" if dataset_prefix else "nba_predictions"
        self._main_table_schema: Optional[List[bigquery.SchemaField]] = None
        self._schema_validated: bool = False

    def _get_main_table_schema(self) -> List[bigquery.SchemaField]:
        """
        Get the schema from the main predictions table (cached).

        Returns:
            List of SchemaField objects
        """
        if self._main_table_schema is None:
            main_table_id = f"{self.project_id}.{self.staging_dataset}.{MAIN_PREDICTIONS_TABLE}"
            main_table = self.bq_client.get_table(main_table_id)
            self._main_table_schema = main_table.schema
            logger.debug(f"Cached main table schema with {len(self._main_table_schema)} fields")
        return self._main_table_schema

    def validate_output_schema(self, sample_record_keys: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Validate that all fields the worker writes exist in the BQ table schema.

        Session 159: Prevents schema mismatch errors that caused 100% write failures
        for Feb 7-8 2026 (vegas_line_source and required_default_count missing from BQ).

        Args:
            sample_record_keys: Optional list of field names the worker writes.
                If not provided, fetches schema only and returns column list.

        Returns:
            Dict with:
                - valid: bool (True if all record keys exist in BQ)
                - bq_columns: set of column names in BQ table
                - missing_from_bq: list of fields in record but not in BQ
                - extra_in_bq: list of fields in BQ but not in record
        """
        try:
            schema = self._get_main_table_schema()
            bq_columns = {field.name for field in schema}

            if sample_record_keys is None:
                return {
                    'valid': True,
                    'bq_columns': bq_columns,
                    'missing_from_bq': [],
                    'extra_in_bq': [],
                }

            record_keys = set(sample_record_keys)
            missing_from_bq = sorted(record_keys - bq_columns)
            extra_in_bq = sorted(bq_columns - record_keys)

            if missing_from_bq:
                logger.critical(
                    f"SCHEMA MISMATCH: Worker writes fields that don't exist in BQ table! "
                    f"Missing from BQ: {missing_from_bq}. "
                    f"Fix: ALTER TABLE {self.project_id}.{self.staging_dataset}.{MAIN_PREDICTIONS_TABLE} "
                    f"ADD COLUMN <name> <type> for each missing field."
                )

            return {
                'valid': len(missing_from_bq) == 0,
                'bq_columns': bq_columns,
                'missing_from_bq': missing_from_bq,
                'extra_in_bq': extra_in_bq,
            }

        except Exception as e:
            logger.error(f"Schema validation failed: {e}", exc_info=True)
            return {
                'valid': False,
                'bq_columns': set(),
                'missing_from_bq': [],
                'extra_in_bq': [],
                'error': str(e),
            }

    def _generate_staging_table_name(self, batch_id: str, worker_id: str) -> str:
        """
        Generate a unique staging table name.

        Format: _staging_{batch_id}_{worker_id}

        Args:
            batch_id: Unique identifier for the batch
            worker_id: Unique identifier for the worker

        Returns:
            Full table ID including project and dataset
        """
        # Sanitize batch_id and worker_id for table naming
        safe_batch_id = batch_id.replace("-", "_")
        safe_worker_id = worker_id.replace("-", "_")

        table_name = f"_staging_{safe_batch_id}_{safe_worker_id}"
        return f"{self.project_id}.{self.staging_dataset}.{table_name}"

    @retry_on_quota_exceeded
    def write_to_staging(
        self,
        predictions: List[Dict[str, Any]],
        batch_id: str,
        worker_id: str
    ) -> StagingWriteResult:
        """
        Write predictions to an individual staging table using batch INSERT.

        This method uses load_table_from_json with WRITE_APPEND, which is NOT
        a DML operation and therefore has no concurrency limits.

        Args:
            predictions: List of prediction dictionaries
            batch_id: Unique identifier for the batch (e.g., "20231215_143022")
            worker_id: Unique identifier for the worker (e.g., "worker_1", instance ID)

        Returns:
            StagingWriteResult with staging table name and status
        """
        staging_table_id = self._generate_staging_table_name(batch_id, worker_id)

        if not predictions:
            logger.warning(f"No predictions to write for batch={batch_id}, worker={worker_id}")
            return StagingWriteResult(
                staging_table_name=staging_table_id,
                rows_written=0,
                success=True,
                error_message=None
            )

        start_time = time.time()

        try:
            # Get schema from main table
            schema = self._get_main_table_schema()

            # Session 159: Validate schema on first write to catch mismatches early
            if not self._schema_validated and predictions:
                record_keys = list(predictions[0].keys())
                validation = self.validate_output_schema(record_keys)
                self._schema_validated = True

                if not validation['valid']:
                    missing = validation['missing_from_bq']
                    error_msg = (
                        f"SCHEMA MISMATCH: Worker output has {len(missing)} fields not in BQ table: "
                        f"{missing}. All writes will fail. Fix the BQ schema before retrying."
                    )
                    logger.critical(error_msg)
                    return StagingWriteResult(
                        staging_table_name=staging_table_id,
                        rows_written=0,
                        success=False,
                        error_message=error_msg
                    )
                else:
                    logger.info(
                        f"Schema validation passed: {len(record_keys)} worker fields match BQ table"
                    )

            # Configure the load job
            # WRITE_APPEND allows multiple workers to write without conflict
            # CREATE_IF_NEEDED creates the table on first write
            job_config = bigquery.LoadJobConfig(
                schema=schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED
            )

            # Convert numpy types to Python native types for JSON serialization
            # This fixes "JSON table encountered too many errors" caused by np.float64/np.int64
            serializable_predictions = [convert_numpy_types(p) for p in predictions]

            # Validate JSON serialization before sending to BigQuery
            # This helps identify non-serializable values that would cause silent failures
            import json
            for i, pred in enumerate(serializable_predictions):
                for key, value in pred.items():
                    try:
                        json.dumps(value)
                    except TypeError as e:
                        logger.error(
                            f"Non-JSON-serializable value in prediction {i}, field '{key}': "
                            f"type={type(value).__name__}, value={repr(value)[:100]}, error={e}"
                        )
                        raise ValueError(f"Field '{key}' is not JSON-serializable: {type(value).__name__}")

            # Load predictions to staging table (NOT a DML operation)
            load_job = self.bq_client.load_table_from_json(
                serializable_predictions,
                staging_table_id,
                job_config=job_config
            )

            # Wait for the job to complete with detailed error handling
            try:
                load_job.result(timeout=300)
            except Exception as load_error:
                # Log detailed job errors if available
                if hasattr(load_job, 'errors') and load_job.errors:
                    for error in load_job.errors:
                        logger.error(f"BigQuery load job error detail: {error}")
                raise load_error

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"Staging write complete: {len(predictions)} rows to {staging_table_id} "
                f"in {elapsed_ms:.1f}ms (batch={batch_id}, worker={worker_id})"
            )

            return StagingWriteResult(
                staging_table_name=staging_table_id,
                rows_written=len(predictions),
                success=True,
                error_message=None
            )

        except gcp_exceptions.BadRequest as e:
            error_msg = f"Invalid request writing to staging: {e}"
            logger.error(error_msg, exc_info=True)
            return StagingWriteResult(
                staging_table_name=staging_table_id,
                rows_written=0,
                success=False,
                error_message=error_msg
            )

        except gcp_exceptions.NotFound as e:
            error_msg = f"Table or dataset not found: {e}"
            logger.error(error_msg, exc_info=True)
            return StagingWriteResult(
                staging_table_name=staging_table_id,
                rows_written=0,
                success=False,
                error_message=error_msg
            )

        except Exception as e:
            error_msg = f"Unexpected error writing to staging: {type(e).__name__}: {e}"
            logger.error(error_msg, exc_info=True)
            return StagingWriteResult(
                staging_table_name=staging_table_id,
                rows_written=0,
                success=False,
                error_message=error_msg
            )


class BatchConsolidator:
    """
    Consolidates all staging tables for a batch into the main predictions table.

    Used by the coordinator after all workers have completed. Executes a single
    MERGE operation with ROW_NUMBER deduplication, then cleans up staging tables.

    Usage:
        consolidator = BatchConsolidator(bq_client, project_id)
        result = consolidator.consolidate_batch(batch_id, game_date)
        if result.success:
            print(f"Merged {result.rows_affected} rows from {result.staging_tables_merged} tables")
    """

    def __init__(self, bq_client: bigquery.Client, project_id: str, dataset_prefix: str = ''):
        """
        Initialize the batch consolidator.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
            dataset_prefix: Optional dataset prefix for test isolation (e.g., "test")
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.dataset_prefix = dataset_prefix
        # Construct dataset name with optional prefix
        self.staging_dataset = f"{dataset_prefix}_nba_predictions" if dataset_prefix else "nba_predictions"

    def _get_staging_columns(self, staging_table_id: str) -> List[str]:
        """
        Get column names from a staging table.

        SESSION 39 FIX: Staging tables may have fewer columns than the main table
        if the worker code predates schema additions. We need to use only the
        columns that exist in staging to avoid MERGE failures.

        Args:
            staging_table_id: Full table ID (project.dataset.table)

        Returns:
            List of column names in the staging table
        """
        try:
            table = self.bq_client.get_table(staging_table_id)
            return [field.name for field in table.schema]
        except Exception as e:
            logger.error(f"Failed to get schema for staging table {staging_table_id}: {e}")
            raise

    def _find_staging_tables(self, batch_id: str) -> List[str]:
        """
        Find all staging tables for a given batch.

        Args:
            batch_id: Batch identifier

        Returns:
            List of full table IDs for staging tables
        """
        safe_batch_id = batch_id.replace("-", "_")
        prefix = f"_staging_{safe_batch_id}_"

        dataset_ref = bigquery.DatasetReference(self.project_id, self.staging_dataset)
        tables = list(self.bq_client.list_tables(dataset_ref))

        staging_tables = []
        for table in tables:
            if table.table_id.startswith(prefix):
                full_table_id = f"{self.project_id}.{self.staging_dataset}.{table.table_id}"
                staging_tables.append(full_table_id)

        logger.info(f"Found {len(staging_tables)} staging tables for batch={batch_id}")
        return staging_tables

    def _build_merge_query(
        self,
        staging_tables: List[str],
        game_date: str,
        staging_columns: Optional[List[str]] = None
    ) -> str:
        """
        Build the MERGE query with ROW_NUMBER deduplication.

        The merge key is: game_id + player_lookup + system_id + current_points_line

        P1-DATA-1 FIX: Changed from game_date to game_id for more precise matching,
        and use COALESCE for current_points_line to handle NULL values properly
        (NULL = NULL evaluates to NULL in SQL, causing duplicate insertions).

        SESSION 39 FIX: Uses explicit column list instead of SELECT * and INSERT ROW
        to handle schema mismatches between staging tables and main table. Staging
        tables may have fewer columns if created by older worker code.

        Uses ROW_NUMBER to handle duplicates, keeping the most recent prediction
        based on created_at timestamp.

        Args:
            staging_tables: List of staging table IDs
            game_date: Game date for filtering (YYYY-MM-DD format)
            staging_columns: Optional list of columns in staging tables. If not provided,
                             will be fetched from the first staging table.

        Returns:
            MERGE SQL query string
        """
        main_table = f"{self.project_id}.{self.staging_dataset}.{MAIN_PREDICTIONS_TABLE}"

        # Get staging columns if not provided
        if staging_columns is None and staging_tables:
            staging_columns = self._get_staging_columns(staging_tables[0])
            logger.info(f"Detected {len(staging_columns)} columns in staging tables")

        # Build explicit column list for SELECT (excluding row_num which we add)
        column_list = ", ".join(staging_columns)

        # Build UNION ALL of all staging tables with explicit columns
        union_parts = [f"SELECT {column_list} FROM `{table}`" for table in staging_tables]
        union_query = " UNION ALL ".join(union_parts)

        # Build UPDATE SET clause only for columns that exist in staging
        # Exclude merge key columns and special columns from UPDATE
        merge_key_columns = {'game_id', 'player_lookup', 'system_id', 'current_points_line', 'game_date'}
        # Never update: prediction_id (preserve original ID), created_at (preserve original timestamp)
        # updated_at is set explicitly to CURRENT_TIMESTAMP() below
        special_columns = {'prediction_id', 'created_at', 'updated_at'}

        update_columns = [
            col for col in staging_columns
            if col not in merge_key_columns and col not in special_columns
        ]
        update_set_clause = ",\n            ".join([
            f"{col} = S.{col}" for col in update_columns
        ])
        # Always update updated_at to current timestamp
        update_set_clause += ",\n            updated_at = CURRENT_TIMESTAMP()"

        # Build INSERT column list and values
        insert_columns = ", ".join(staging_columns)
        insert_values = ", ".join([f"S.{col}" for col in staging_columns])

        # Session 81: Edge-based filtering was here but REMOVED in Session 102
        # Rationale: Store ALL predictions, filter at query time for betting decisions
        # The is_actionable field can be used to mark low-edge predictions if needed
        # Edge analysis (High 5+, Medium 3-5, Low <3) happens at query time, not write time

        # The MERGE query with ROW_NUMBER deduplication
        # Keeps the most recent prediction per unique key
        # P1-DATA-1: Use game_id (not game_date) and COALESCE for NULL-safe comparison
        # COALESCE uses -1 as sentinel for NULL since prop lines are always positive
        merge_query = f"""
        MERGE `{main_table}` T
        USING (
            SELECT {column_list}
            FROM (
                SELECT {column_list},
                    ROW_NUMBER() OVER (
                        PARTITION BY game_id, player_lookup, system_id, CAST(COALESCE(current_points_line, -1) AS INT64)
                        ORDER BY created_at DESC
                    ) AS row_num
                FROM ({union_query})
            )
            WHERE row_num = 1
        ) S
        ON T.game_id = S.game_id
           AND T.player_lookup = S.player_lookup
           AND T.system_id = S.system_id
           AND CAST(COALESCE(T.current_points_line, -1) AS INT64) = CAST(COALESCE(S.current_points_line, -1) AS INT64)
        WHEN MATCHED THEN
          UPDATE SET
            {update_set_clause}
        WHEN NOT MATCHED THEN
          INSERT ({insert_columns})
          VALUES ({insert_values})
        """

        return merge_query

    def _deactivate_older_predictions(self, game_date: str) -> int:
        """
        Deactivate older predictions for the same player/game, keeping only the newest.

        SESSION 13 FIX: Handles cases where multiple model versions or batches create
        duplicate predictions for the same player/game combination. Only the newest
        prediction (by created_at) remains active.

        Args:
            game_date: Game date to process (YYYY-MM-DD)

        Returns:
            Number of predictions deactivated
        """
        main_table = f"{self.project_id}.{self.staging_dataset}.{MAIN_PREDICTIONS_TABLE}"

        # Deactivate all but the newest prediction per player/game
        # Uses ROW_NUMBER to identify the newest by created_at
        deactivation_query = f"""
        UPDATE `{main_table}` T
        SET is_active = FALSE,
            updated_at = CURRENT_TIMESTAMP()
        WHERE game_date = '{game_date}'
          AND is_active = TRUE
          AND prediction_id IN (
            SELECT prediction_id
            FROM (
              SELECT
                prediction_id,
                ROW_NUMBER() OVER (
                  -- SESSION 78 FIX: Include system_id so each system keeps its latest prediction active
                  PARTITION BY game_id, player_lookup, system_id
                  ORDER BY created_at DESC
                ) as row_num
              FROM `{main_table}`
              WHERE game_date = '{game_date}'
                AND is_active = TRUE
            )
            WHERE row_num > 1
          )
        """

        try:
            query_job = self.bq_client.query(deactivation_query)
            query_job.result(timeout=60)
            deactivated = query_job.num_dml_affected_rows or 0

            if deactivated > 0:
                logger.info(
                    f"SESSION 13: Deactivated {deactivated} older predictions for game_date={game_date}"
                )
            return deactivated

        except Exception as e:
            logger.error(f"Failed to deactivate older predictions: {e}", exc_info=True)
            return 0

    def _check_for_duplicates(self, game_date: str) -> int:
        """
        Check for duplicate business keys in the main predictions table.

        SESSION 92 FIX: Post-consolidation validation to detect duplicates.

        Queries the main table for the given game_date and checks if any
        business keys (game_id, player_lookup, system_id, current_points_line)
        appear more than once.

        This should return 0 if the distributed lock worked correctly.
        If > 0, it indicates a race condition or lock failure.

        Args:
            game_date: Game date to check (YYYY-MM-DD)

        Returns:
            Number of duplicate business keys found (0 = validation passed)
        """
        main_table = f"{self.project_id}.{self.staging_dataset}.{MAIN_PREDICTIONS_TABLE}"

        # Query to find duplicate business keys
        # Business key: game_id + player_lookup + system_id + current_points_line
        # Use COALESCE(-1) for NULL lines (same as MERGE logic)
        validation_query = f"""
        SELECT COUNT(*) as duplicate_count
        FROM (
            SELECT
                game_id,
                player_lookup,
                system_id,
                CAST(COALESCE(current_points_line, -1) AS INT64) as line,
                COUNT(*) as occurrence_count
            FROM `{main_table}`
            WHERE game_date = '{game_date}'
            GROUP BY game_id, player_lookup, system_id, line
            HAVING COUNT(*) > 1
        )
        """

        try:
            query_job = self.bq_client.query(validation_query)
            result = query_job.result(timeout=30)

            # Get the count
            row = next(iter(result), None)
            duplicate_count = (row.duplicate_count or 0) if row else 0

            if duplicate_count > 0:
                # Log details of duplicates for investigation
                logger.error(
                    f"Found {duplicate_count} duplicate business keys for game_date={game_date}"
                )

                # Get details of the duplicates
                details_query = f"""
                SELECT
                    game_id,
                    player_lookup,
                    system_id,
                    current_points_line,
                    COUNT(*) as count,
                    STRING_AGG(prediction_id, ', ') as prediction_ids
                FROM `{main_table}`
                WHERE game_date = '{game_date}'
                GROUP BY game_id, player_lookup, system_id, current_points_line
                HAVING COUNT(*) > 1
                LIMIT 10
                """

                details_job = self.bq_client.query(details_query)
                details_result = details_job.result(timeout=30)

                logger.error("First 10 duplicate business keys:", exc_info=True)
                for row in details_result:
                    logger.error(
                        f"  - {row.player_lookup} / {row.system_id} / line={row.current_points_line}: "
                        f"{row.count}x (prediction_ids: {row.prediction_ids})"
                    )

            return duplicate_count

        except gcp_exceptions.BadRequest as e:
            logger.error(f"BigQuery syntax error checking for duplicates: {e}", exc_info=True)
            return -1
        except gcp_exceptions.NotFound as e:
            logger.error(f"BigQuery table not found checking for duplicates: {e}", exc_info=True)
            return -1
        except (gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded) as e:
            logger.error(f"BigQuery timeout/unavailable checking for duplicates: {e}", exc_info=True)
            return -1
        except Exception as e:
            logger.error(f"Unexpected error checking for duplicates ({type(e).__name__}): {e}", exc_info=True)
            # Return -1 to indicate validation error (not the same as 0 duplicates)
            return -1

    def cleanup_duplicate_predictions(
        self,
        game_date: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Deactivate duplicate predictions for a game date (streaming buffer safe).

        SESSION 28 FIX: This method should be called 2+ hours after predictions
        to allow BigQuery's streaming buffer to clear. The immediate deactivation
        in consolidate_batch() fails silently because rows are in the streaming buffer.

        The streaming buffer locks rows for 30-90 minutes after DML operations.
        This delayed cleanup ensures rows are modifiable.

        Args:
            game_date: Game date to clean up (YYYY-MM-DD)
            dry_run: If True, only count duplicates without deactivating

        Returns:
            Dict with:
                - duplicates_found: Number of duplicate predictions
                - duplicates_deactivated: Number deactivated (0 if dry_run)
                - dry_run: Whether this was a dry run
                - game_date: The game date processed
        """
        main_table = f"{self.project_id}.{self.staging_dataset}.{MAIN_PREDICTIONS_TABLE}"

        # First, count duplicates
        count_query = f"""
        SELECT COUNT(*) as duplicate_count
        FROM (
            SELECT prediction_id
            FROM (
                SELECT
                    prediction_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY game_id, player_lookup, system_id
                        ORDER BY created_at DESC
                    ) as row_num
                FROM `{main_table}`
                WHERE game_date = '{game_date}'
                  AND is_active = TRUE
            )
            WHERE row_num > 1
        )
        """

        try:
            count_job = self.bq_client.query(count_query)
            count_result = count_job.result(timeout=60)
            row = next(iter(count_result), None)
            duplicates_found = (row.duplicate_count or 0) if row else 0

            logger.info(f"Found {duplicates_found} duplicate predictions for game_date={game_date}")

            if dry_run or duplicates_found == 0:
                return {
                    'duplicates_found': duplicates_found,
                    'duplicates_deactivated': 0,
                    'dry_run': dry_run,
                    'game_date': game_date
                }

            # Perform the deactivation
            deactivate_start = time.time()
            deactivated = self._deactivate_older_predictions(game_date)
            deactivate_ms = (time.time() - deactivate_start) * 1000
            logger.info(
                f"Cleanup deactivation: {deactivated} predictions deactivated "
                f"for game_date={game_date} in {deactivate_ms:.1f}ms"
            )

            return {
                'duplicates_found': duplicates_found,
                'duplicates_deactivated': deactivated,
                'dry_run': False,
                'game_date': game_date
            }

        except Exception as e:
            logger.error(f"Error in cleanup_duplicate_predictions for {game_date}: {e}", exc_info=True)
            return {
                'duplicates_found': -1,
                'duplicates_deactivated': 0,
                'dry_run': dry_run,
                'game_date': game_date,
                'error': str(e)
            }

    def _cleanup_staging_tables(self, batch_id: str) -> int:
        """
        Delete all staging tables for a batch.

        Args:
            batch_id: Batch identifier

        Returns:
            Number of tables deleted
        """
        staging_tables = self._find_staging_tables(batch_id)
        deleted_count = 0

        for table_id in staging_tables:
            try:
                self.bq_client.delete_table(table_id, not_found_ok=True)
                deleted_count += 1
                logger.debug(f"Deleted staging table: {table_id}")
            except gcp_exceptions.Forbidden as e:
                logger.warning(f"Permission denied deleting staging table {table_id}: {e}")
            except gcp_exceptions.ServiceUnavailable as e:
                logger.warning(f"Service unavailable deleting staging table {table_id}: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error deleting staging table {table_id} ({type(e).__name__}): {e}")

        logger.info(f"Cleaned up {deleted_count}/{len(staging_tables)} staging tables for batch={batch_id}")
        return deleted_count

    def consolidate_batch(
        self,
        batch_id: str,
        game_date: str,
        cleanup: bool = True,
        use_lock: bool = True
    ) -> ConsolidationResult:
        """
        Merge all staging tables for a batch into the main predictions table.

        CRITICAL FIX (Session 92): Uses distributed lock to prevent race conditions
        that caused duplicate rows with different prediction_ids.

        When two consolidations run concurrently for the same game_date:
        1. Without lock: Both find "NOT MATCHED" and INSERT → duplicates
        2. With lock: Second waits for first to complete, then finds "MATCHED" and UPDATEs

        Executes a single MERGE operation with ROW_NUMBER deduplication,
        then optionally cleans up staging tables.

        Args:
            batch_id: Unique batch identifier
            game_date: Game date (YYYY-MM-DD format)
            cleanup: Whether to delete staging tables after merge (default: True)
            use_lock: Whether to use distributed lock (default: True, disable for testing only)

        Returns:
            ConsolidationResult with rows affected and status
        """
        start_time = time.time()

        # SESSION 92 FIX: Acquire distributed lock to prevent race conditions
        # Lock is scoped to game_date (not batch_id) because multiple batches
        # can target the same game_date and cause duplicate INSERTs
        if use_lock:
            try:
                lock = DistributedLock(project_id=self.project_id, lock_type="consolidation")
                logger.info(
                    f"Acquiring consolidation lock for game_date={game_date}, batch={batch_id}"
                )

                with lock.acquire(game_date=game_date, operation_id=batch_id):
                    # Lock acquired - run consolidation inside locked context
                    return self._consolidate_with_lock(
                        batch_id=batch_id,
                        game_date=game_date,
                        cleanup=cleanup,
                        start_time=start_time
                    )

            except LockAcquisitionError as e:
                # Failed to acquire lock after max retries
                error_msg = f"Cannot acquire consolidation lock: {e}"
                logger.error(f"Lock acquisition failed: {error_msg}", exc_info=True)
                return ConsolidationResult(
                    rows_affected=0,
                    staging_tables_merged=0,
                    staging_tables_cleaned=0,
                    success=False,
                    error_message=error_msg
                )
        else:
            # Lock disabled (testing only)
            logger.warning(
                f"Distributed lock DISABLED for batch={batch_id} - "
                f"race conditions possible!"
            )
            return self._consolidate_with_lock(
                batch_id=batch_id,
                game_date=game_date,
                cleanup=cleanup,
                start_time=start_time
            )

    @retry_on_serialization
    def _consolidate_with_lock(
        self,
        batch_id: str,
        game_date: str,
        cleanup: bool,
        start_time: float
    ) -> ConsolidationResult:
        """
        Internal consolidation logic (runs inside lock context).

        This method contains the actual MERGE logic and should only be called
        within a distributed lock context to prevent race conditions.

        Args:
            batch_id: Unique batch identifier
            game_date: Game date (YYYY-MM-DD format)
            cleanup: Whether to delete staging tables after merge
            start_time: Start time for duration tracking

        Returns:
            ConsolidationResult with rows affected and status
        """
        # Find all staging tables for this batch
        staging_tables = self._find_staging_tables(batch_id)

        logger.info(f"Found {len(staging_tables)} staging tables for batch={batch_id}")
        if not staging_tables:
            logger.warning(f"No staging tables found for batch={batch_id}")
            return ConsolidationResult(
                rows_affected=0,
                staging_tables_merged=0,
                staging_tables_cleaned=0,
                success=True,
                error_message=None
            )

        try:
            # Session 102: Edge filtering REMOVED - store all predictions, filter at query time
            # Previously Session 81 filtered edge < 3 at write time, but this caused orphan
            # superseded predictions during regeneration. Now all predictions are stored
            # and edge filtering happens at query time for betting decisions.
            logger.info(
                f"Session 102: All predictions will be stored (edge filtering at query time, not write time)"
            )

            # Build and execute the MERGE query
            merge_query = self._build_merge_query(staging_tables, game_date)

            logger.info(
                f"Executing consolidation MERGE for batch={batch_id} with {len(staging_tables)} staging tables"
            )

            merge_job = self.bq_client.query(merge_query)
            merge_job.result(timeout=300)

            rows_affected = merge_job.num_dml_affected_rows or 0

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"MERGE complete: {rows_affected} rows affected in {elapsed_ms:.1f}ms (batch={batch_id})"
            )
            # Structured log for Cloud Logging parsing and metrics dashboards
            logger.info(
                f"CONSOLIDATION_METRICS: {rows_affected} rows merged in {elapsed_ms:.0f}ms "
                f"for batch {batch_id}, staging_tables={len(staging_tables)}"
            )

            # SESSION 13 FIX: Deactivate older predictions after MERGE
            # This ensures only the newest prediction per player/game is active,
            # handling multiple model versions and duplicate batches
            deactivate_start = time.time()
            deactivated = self._deactivate_older_predictions(game_date)
            deactivate_ms = (time.time() - deactivate_start) * 1000
            if deactivated > 0:
                logger.info(
                    f"Deactivated {deactivated} older predictions for game_date={game_date} "
                    f"in {deactivate_ms:.1f}ms"
                )
            else:
                logger.debug(
                    f"Deactivation check completed in {deactivate_ms:.1f}ms "
                    f"(0 predictions deactivated for game_date={game_date})"
                )

            # CRITICAL: Check if MERGE actually wrote data
            if rows_affected == 0:
                logger.error(
                    f"MERGE returned 0 rows for batch={batch_id}! Staging tables had {len(staging_tables)} tables. "
                    f"NOT cleaning up for investigation. "
                    f"This suggests data loss - staging tables NOT cleaned up for investigation."
                )
                return ConsolidationResult(
                    rows_affected=0,
                    staging_tables_merged=len(staging_tables),
                    staging_tables_cleaned=0,
                    success=False,  # Mark as failure
                    error_message=f"MERGE returned 0 rows but {len(staging_tables)} staging tables exist"
                )

            # SESSION 92 FIX: Post-consolidation validation to detect duplicates
            # This catches any duplicates that might slip through despite the lock
            logger.info(f"Running post-consolidation validation for game_date={game_date}...")
            duplicate_count = self._check_for_duplicates(game_date)

            if duplicate_count > 0:
                error_msg = (
                    f"POST-CONSOLIDATION VALIDATION FAILED: Found {duplicate_count} duplicate "
                    f"business keys for game_date={game_date} after MERGE. "
                    f"This indicates a race condition or lock failure. "
                    f"NOT cleaning up staging tables for investigation."
                )
                logger.error(error_msg)
                return ConsolidationResult(
                    rows_affected=rows_affected,
                    staging_tables_merged=len(staging_tables),
                    staging_tables_cleaned=0,
                    success=False,  # Mark as failure - duplicates detected!
                    error_message=f"Duplicate business keys detected: {duplicate_count}"
                )
            else:
                logger.info(f"Post-consolidation validation PASSED: 0 duplicates for game_date={game_date}")

            # Clean up staging tables if requested AND rows were merged AND validation passed
            cleaned_count = 0
            if cleanup:
                logger.info(f"Cleaning up {len(staging_tables)} staging tables...")
                cleaned_count = self._cleanup_staging_tables(batch_id)
                logger.info(f"Cleaned up {cleaned_count}/{len(staging_tables)} staging tables")

            return ConsolidationResult(
                rows_affected=rows_affected,
                staging_tables_merged=len(staging_tables),
                staging_tables_cleaned=cleaned_count,
                success=True,
                error_message=None
            )

        except gcp_exceptions.BadRequest as e:
            error_msg = f"Invalid MERGE query: {e}"
            logger.error(f"BadRequest error in MERGE: {error_msg}", exc_info=True)
            return ConsolidationResult(
                rows_affected=0,
                staging_tables_merged=0,
                staging_tables_cleaned=0,
                success=False,
                error_message=error_msg
            )

        except gcp_exceptions.Conflict as e:
            error_msg = f"DML conflict during consolidation: {e}"
            logger.error(f"Conflict error in MERGE: {error_msg}", exc_info=True)
            return ConsolidationResult(
                rows_affected=0,
                staging_tables_merged=0,
                staging_tables_cleaned=0,
                success=False,
                error_message=error_msg
            )

        except Exception as e:
            error_msg = f"Unexpected error during consolidation: {type(e).__name__}: {e}"
            logger.error(f"Unexpected error in consolidation: {error_msg}", exc_info=True)
            return ConsolidationResult(
                rows_affected=0,
                staging_tables_merged=0,
                staging_tables_cleaned=0,
                success=False,
                error_message=error_msg
            )

    def cleanup_orphaned_staging_tables(self, max_age_hours: int = 24, dry_run: bool = False) -> dict:
        """
        Clean up orphaned staging tables older than the specified age.

        Useful for cleaning up tables from failed batches or incomplete runs.

        Args:
            max_age_hours: Maximum age of staging tables to keep (default: 24)
            dry_run: If True, only count tables without deleting (default: False)

        Returns:
            Dictionary with cleanup results:
            - tables_found: Total staging tables found
            - tables_deleted: Number of tables deleted (0 if dry_run)
            - tables_skipped: Tables not old enough
            - errors: List of tables that failed to delete
        """
        import datetime

        dataset_ref = bigquery.DatasetReference(self.project_id, self.staging_dataset)
        tables = list(self.bq_client.list_tables(dataset_ref))

        cutoff_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=max_age_hours)

        tables_found = 0
        deleted_count = 0
        skipped_count = 0
        errors = []

        for table in tables:
            if table.table_id.startswith("_staging_"):
                tables_found += 1
                try:
                    # Get table metadata to check creation time
                    full_table = self.bq_client.get_table(
                        f"{self.project_id}.{self.staging_dataset}.{table.table_id}"
                    )

                    if full_table.created < cutoff_time:
                        if dry_run:
                            logger.info(
                                f"[DRY RUN] Would delete staging table: {table.table_id} "
                                f"(created: {full_table.created})"
                            )
                            deleted_count += 1
                        else:
                            self.bq_client.delete_table(full_table, not_found_ok=True)
                            deleted_count += 1
                            logger.info(
                                f"Deleted orphaned staging table: {table.table_id} "
                                f"(created: {full_table.created})"
                            )
                    else:
                        skipped_count += 1

                except gcp_exceptions.NotFound:
                    logger.debug(f"Staging table already deleted: {table.table_id}")
                except gcp_exceptions.Forbidden as e:
                    logger.warning(f"Permission denied checking/deleting table {table.table_id}: {e}")
                    errors.append({"table": table.table_id, "error": str(e)})
                except gcp_exceptions.ServiceUnavailable as e:
                    logger.warning(f"Service unavailable checking/deleting table {table.table_id}: {e}")
                    errors.append({"table": table.table_id, "error": str(e)})
                except Exception as e:
                    logger.warning(f"Unexpected error checking/deleting table {table.table_id} ({type(e).__name__}): {e}")
                    errors.append({"table": table.table_id, "error": str(e)})

        action = "would delete" if dry_run else "deleted"
        logger.info(f"Staging cleanup: {action} {deleted_count}/{tables_found} tables, skipped {skipped_count}")

        return {
            "tables_found": tables_found,
            "tables_deleted": deleted_count,
            "tables_skipped": skipped_count,
            "errors": errors,
            "dry_run": dry_run,
            "max_age_hours": max_age_hours
        }


# Convenience functions for common usage patterns

def create_batch_id() -> str:
    """
    Generate a unique batch ID based on current timestamp.

    Returns:
        Batch ID string in format: YYYYMMDD_HHMMSS_microseconds
    """
    from datetime import datetime
    now = datetime.utcnow()
    return now.strftime("%Y%m%d_%H%M%S_%f")


def get_worker_id() -> str:
    """
    Get a unique worker ID for the current instance.

    Uses Cloud Run instance ID if available, otherwise generates a random ID.

    Returns:
        Worker ID string
    """
    import os
    import uuid

    # Try Cloud Run instance ID
    instance_id = os.environ.get("K_REVISION")
    if instance_id:
        # Add a random suffix for uniqueness within the same revision
        return f"{instance_id}_{uuid.uuid4().hex[:8]}"

    # Fallback to random ID
    return f"worker_{uuid.uuid4().hex[:12]}"

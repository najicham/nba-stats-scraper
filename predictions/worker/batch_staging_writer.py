# predictions/worker/batch_staging_writer.py

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

from google.cloud import bigquery
from google.api_core import exceptions as gcp_exceptions

# Import distributed lock to prevent race conditions
from predictions.worker.distributed_lock import DistributedLock, LockAcquisitionError

logger = logging.getLogger(__name__)

# Constants
STAGING_DATASET = "nba_predictions"
MAIN_PREDICTIONS_TABLE = "player_prop_predictions"


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

            # Configure the load job
            # WRITE_APPEND allows multiple workers to write without conflict
            # CREATE_IF_NEEDED creates the table on first write
            job_config = bigquery.LoadJobConfig(
                schema=schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED
            )

            # Load predictions to staging table (NOT a DML operation)
            load_job = self.bq_client.load_table_from_json(
                predictions,
                staging_table_id,
                job_config=job_config
            )

            # Wait for the job to complete
            load_job.result(timeout=300)

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
            logger.error(error_msg)
            return StagingWriteResult(
                staging_table_name=staging_table_id,
                rows_written=0,
                success=False,
                error_message=error_msg
            )

        except gcp_exceptions.NotFound as e:
            error_msg = f"Table or dataset not found: {e}"
            logger.error(error_msg)
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
        game_date: str
    ) -> str:
        """
        Build the MERGE query with ROW_NUMBER deduplication.

        The merge key is: game_id + player_lookup + system_id + current_points_line

        P1-DATA-1 FIX: Changed from game_date to game_id for more precise matching,
        and use COALESCE for current_points_line to handle NULL values properly
        (NULL = NULL evaluates to NULL in SQL, causing duplicate insertions).

        Uses ROW_NUMBER to handle duplicates, keeping the most recent prediction
        based on created_at timestamp.

        Args:
            staging_tables: List of staging table IDs
            game_date: Game date for filtering (YYYY-MM-DD format)

        Returns:
            MERGE SQL query string
        """
        main_table = f"{self.project_id}.{self.staging_dataset}.{MAIN_PREDICTIONS_TABLE}"

        # Build UNION ALL of all staging tables with deduplication
        union_parts = [f"SELECT * FROM `{table}`" for table in staging_tables]
        union_query = " UNION ALL ".join(union_parts)

        # The MERGE query with ROW_NUMBER deduplication
        # Keeps the most recent prediction per unique key
        # P1-DATA-1: Use game_id (not game_date) and COALESCE for NULL-safe comparison
        # COALESCE uses -1 as sentinel for NULL since prop lines are always positive
        merge_query = f"""
        MERGE `{main_table}` T
        USING (
            SELECT * EXCEPT(row_num)
            FROM (
                SELECT *,
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
            prediction_id = S.prediction_id,
            universal_player_id = S.universal_player_id,
            game_id = S.game_id,
            prediction_version = S.prediction_version,
            predicted_points = S.predicted_points,
            confidence_score = S.confidence_score,
            recommendation = S.recommendation,
            line_margin = S.line_margin,
            is_active = S.is_active,
            updated_at = CURRENT_TIMESTAMP(),
            superseded_by = S.superseded_by,
            similarity_baseline = S.similarity_baseline,
            similar_games_count = S.similar_games_count,
            avg_similarity_score = S.avg_similarity_score,
            min_similarity_score = S.min_similarity_score,
            fatigue_adjustment = S.fatigue_adjustment,
            shot_zone_adjustment = S.shot_zone_adjustment,
            pace_adjustment = S.pace_adjustment,
            usage_spike_adjustment = S.usage_spike_adjustment,
            home_away_adjustment = S.home_away_adjustment,
            feature_importance = S.feature_importance,
            model_version = S.model_version,
            expected_games_count = S.expected_games_count,
            actual_games_count = S.actual_games_count,
            completeness_percentage = S.completeness_percentage,
            missing_games_count = S.missing_games_count,
            is_production_ready = S.is_production_ready,
            data_quality_issues = S.data_quality_issues,
            last_reprocess_attempt_at = S.last_reprocess_attempt_at,
            reprocess_attempt_count = S.reprocess_attempt_count,
            circuit_breaker_active = S.circuit_breaker_active,
            circuit_breaker_until = S.circuit_breaker_until,
            manual_override_required = S.manual_override_required,
            season_boundary_detected = S.season_boundary_detected,
            backfill_bootstrap_mode = S.backfill_bootstrap_mode,
            processing_decision_reason = S.processing_decision_reason,
            has_prop_line = S.has_prop_line,
            line_source = S.line_source,
            estimated_line_value = S.estimated_line_value,
            estimation_method = S.estimation_method,
            scoring_tier = S.scoring_tier,
            tier_adjustment = S.tier_adjustment,
            adjusted_points = S.adjusted_points,
            is_actionable = S.is_actionable,
            filter_reason = S.filter_reason
        WHEN NOT MATCHED THEN
          INSERT ROW
        """

        return merge_query

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
            row = next(iter(result))
            duplicate_count = row.duplicate_count or 0

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

                logger.error("First 10 duplicate business keys:")
                for row in details_result:
                    logger.error(
                        f"  - {row.player_lookup} / {row.system_id} / line={row.current_points_line}: "
                        f"{row.count}x (prediction_ids: {row.prediction_ids})"
                    )

            return duplicate_count

        except Exception as e:
            logger.error(f"Error checking for duplicates: {e}")
            # Return -1 to indicate validation error (not the same as 0 duplicates)
            return -1

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
            except Exception as e:
                logger.warning(f"Failed to delete staging table {table_id}: {e}")

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
                    f"🔒 Acquiring consolidation lock for game_date={game_date}, batch={batch_id}"
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
                logger.error(f"❌ Lock acquisition failed: {error_msg}")
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
                f"⚠️  Distributed lock DISABLED for batch={batch_id} - "
                f"race conditions possible!"
            )
            return self._consolidate_with_lock(
                batch_id=batch_id,
                game_date=game_date,
                cleanup=cleanup,
                start_time=start_time
            )

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

        logger.info(f"🔍 Found {len(staging_tables)} staging tables for batch={batch_id}")
        if not staging_tables:
            logger.warning(f"⚠️ No staging tables found for batch={batch_id}")
            return ConsolidationResult(
                rows_affected=0,
                staging_tables_merged=0,
                staging_tables_cleaned=0,
                success=True,
                error_message=None
            )

        try:
            # Build and execute the MERGE query
            merge_query = self._build_merge_query(staging_tables, game_date)

            logger.info(
                f"🔄 Executing consolidation MERGE for batch={batch_id} with {len(staging_tables)} staging tables"
            )

            merge_job = self.bq_client.query(merge_query)
            merge_job.result(timeout=300)

            rows_affected = merge_job.num_dml_affected_rows or 0

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"✅ MERGE complete: {rows_affected} rows affected in {elapsed_ms:.1f}ms (batch={batch_id})"
            )

            # CRITICAL: Check if MERGE actually wrote data
            if rows_affected == 0:
                logger.error(
                    f"⚠️ MERGE returned 0 rows for batch={batch_id}! Staging tables had {len(staging_tables)} tables. "
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
            logger.info(f"🔍 Running post-consolidation validation for game_date={game_date}...")
            duplicate_count = self._check_for_duplicates(game_date)

            if duplicate_count > 0:
                error_msg = (
                    f"❌ POST-CONSOLIDATION VALIDATION FAILED: Found {duplicate_count} duplicate "
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
                logger.info(f"✅ Post-consolidation validation PASSED: 0 duplicates for game_date={game_date}")

            # Clean up staging tables if requested AND rows were merged AND validation passed
            cleaned_count = 0
            if cleanup:
                logger.info(f"🧹 Cleaning up {len(staging_tables)} staging tables...")
                cleaned_count = self._cleanup_staging_tables(batch_id)
                logger.info(f"✅ Cleaned up {cleaned_count}/{len(staging_tables)} staging tables")

            return ConsolidationResult(
                rows_affected=rows_affected,
                staging_tables_merged=len(staging_tables),
                staging_tables_cleaned=cleaned_count,
                success=True,
                error_message=None
            )

        except gcp_exceptions.BadRequest as e:
            error_msg = f"Invalid MERGE query: {e}"
            logger.error(f"❌ BadRequest error in MERGE: {error_msg}")
            return ConsolidationResult(
                rows_affected=0,
                staging_tables_merged=0,
                staging_tables_cleaned=0,
                success=False,
                error_message=error_msg
            )

        except gcp_exceptions.Conflict as e:
            error_msg = f"DML conflict during consolidation: {e}"
            logger.error(f"❌ Conflict error in MERGE: {error_msg}")
            return ConsolidationResult(
                rows_affected=0,
                staging_tables_merged=0,
                staging_tables_cleaned=0,
                success=False,
                error_message=error_msg
            )

        except Exception as e:
            error_msg = f"Unexpected error during consolidation: {type(e).__name__}: {e}"
            logger.error(f"❌ Unexpected error in consolidation: {error_msg}", exc_info=True)
            return ConsolidationResult(
                rows_affected=0,
                staging_tables_merged=0,
                staging_tables_cleaned=0,
                success=False,
                error_message=error_msg
            )

    def cleanup_orphaned_staging_tables(self, max_age_hours: int = 24) -> int:
        """
        Clean up orphaned staging tables older than the specified age.

        Useful for cleaning up tables from failed batches or incomplete runs.

        Args:
            max_age_hours: Maximum age of staging tables to keep (default: 24)

        Returns:
            Number of tables deleted
        """
        import datetime

        dataset_ref = bigquery.DatasetReference(self.project_id, self.staging_dataset)
        tables = list(self.bq_client.list_tables(dataset_ref))

        cutoff_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=max_age_hours)
        deleted_count = 0

        for table in tables:
            if table.table_id.startswith("_staging_"):
                try:
                    # Get table metadata to check creation time
                    full_table = self.bq_client.get_table(
                        f"{self.project_id}.{self.staging_dataset}.{table.table_id}"
                    )

                    if full_table.created < cutoff_time:
                        self.bq_client.delete_table(full_table, not_found_ok=True)
                        deleted_count += 1
                        logger.info(
                            f"Deleted orphaned staging table: {table.table_id} "
                            f"(created: {full_table.created})"
                        )

                except Exception as e:
                    logger.warning(f"Error checking/deleting table {table.table_id}: {e}")

        logger.info(f"Cleaned up {deleted_count} orphaned staging tables")
        return deleted_count


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

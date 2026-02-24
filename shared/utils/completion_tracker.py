"""
Completion Tracker - Dual-Write to Firestore and BigQuery

Provides resilient phase completion tracking with:
- Dual-write to both Firestore (primary) and BigQuery (backup)
- Fallback read from BigQuery if Firestore unavailable
- BigQuery table schema for phase_completions

Usage:
    from shared.utils.completion_tracker import CompletionTracker

    tracker = CompletionTracker()  # Uses default from shared.config.gcp_config

    # Record completion (writes to both Firestore and BigQuery)
    tracker.record_completion(
        phase="phase3",
        game_date="2026-01-23",
        processor_name="player_game_summary",
        completion_data={
            "status": "success",
            "record_count": 450,
            "correlation_id": "abc-123"
        }
    )

    # Get completion status (reads from Firestore, falls back to BigQuery)
    status = tracker.get_completion_status(phase="phase3", game_date="2026-01-23")

Version: 1.0
Created: 2026-01-23
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple, Any

from google.cloud import bigquery, firestore
from google.cloud.exceptions import GoogleCloudError

from shared.clients import get_bigquery_client, get_firestore_client
from shared.utils.retry_with_jitter import retry_with_jitter

logger = logging.getLogger(__name__)


class CompletionTracker:
    """
    Dual-write completion tracker with Firestore primary and BigQuery backup.

    Provides resilient phase completion tracking with automatic fallback
    to BigQuery when Firestore is unavailable.

    Attributes:
        project_id: GCP project ID
        bq_dataset: BigQuery dataset for completion tracking (default: nba_orchestration)
        bq_table: BigQuery table for completions (default: phase_completions)
    """

    # BigQuery table schema for phase_completions
    SCHEMA = [
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

    # Aggregated status table schema
    AGGREGATE_SCHEMA = [
        bigquery.SchemaField("phase", "STRING", mode="REQUIRED", description="Phase name"),
        bigquery.SchemaField("game_date", "DATE", mode="REQUIRED", description="Game date"),
        bigquery.SchemaField("completed_count", "INTEGER", mode="REQUIRED", description="Number of processors completed"),
        bigquery.SchemaField("expected_count", "INTEGER", mode="REQUIRED", description="Expected number of processors"),
        bigquery.SchemaField("completed_processors", "STRING", mode="REPEATED", description="List of completed processor names"),
        bigquery.SchemaField("missing_processors", "STRING", mode="REPEATED", description="List of missing processor names"),
        bigquery.SchemaField("is_triggered", "BOOLEAN", mode="REQUIRED", description="Whether next phase was triggered"),
        bigquery.SchemaField("triggered_at", "TIMESTAMP", mode="NULLABLE", description="When next phase was triggered"),
        bigquery.SchemaField("trigger_reason", "STRING", mode="NULLABLE", description="Reason for triggering (all_complete, timeout, etc.)"),
        bigquery.SchemaField("mode", "STRING", mode="NULLABLE", description="Orchestration mode (overnight, same_day, tomorrow)"),
        bigquery.SchemaField("first_completion_at", "TIMESTAMP", mode="NULLABLE", description="When first processor completed"),
        bigquery.SchemaField("last_completion_at", "TIMESTAMP", mode="NULLABLE", description="When last processor completed"),
        bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED", description="When record was last updated"),
    ]

    def __init__(
        self,
        project_id: str,
        bq_dataset: str = "nba_orchestration",
        bq_table: str = "phase_completions",
        aggregate_table: str = "phase_completion_status"
    ):
        """
        Initialize CompletionTracker.

        Args:
            project_id: GCP project ID
            bq_dataset: BigQuery dataset name
            bq_table: BigQuery table name for individual completions
            aggregate_table: BigQuery table name for aggregated status
        """
        self.project_id = project_id
        self.bq_dataset = bq_dataset
        self.bq_table = bq_table
        self.aggregate_table = aggregate_table

        # Lazy initialization of clients (Session 335: thread-safe)
        self._firestore_client: Optional[firestore.Client] = None
        self._bq_client: Optional[bigquery.Client] = None
        self._init_lock = threading.Lock()

        # Track Firestore availability
        self._firestore_available = True
        self._last_firestore_check = None
        self._firestore_check_interval_seconds = 10  # Session 335: reduced from 30s

        # Circuit breaker (Session 335): back off after consecutive failures
        self._firestore_consecutive_failures = 0
        self._firestore_circuit_breaker_threshold = 5
        self._firestore_circuit_breaker_cooldown = 300  # 5 minutes

    @property
    def firestore_client(self):
        """Get or create Firestore client (thread-safe lazy initialization)."""
        if self._firestore_client is None:
            with self._init_lock:
                if self._firestore_client is None:
                    self._firestore_client = get_firestore_client(self.project_id)
        return self._firestore_client

    @property
    def bq_client(self) -> bigquery.Client:
        """Get or create BigQuery client (thread-safe lazy initialization)."""
        if self._bq_client is None:
            with self._init_lock:
                if self._bq_client is None:
                    self._bq_client = get_bigquery_client(self.project_id)
        return self._bq_client

    def _get_firestore_collection(self, phase: str) -> str:
        """Get Firestore collection name for a phase."""
        return f"{phase}_completion"

    def _get_bq_table_id(self) -> str:
        """Get fully qualified BigQuery table ID."""
        return f"{self.project_id}.{self.bq_dataset}.{self.bq_table}"

    def _get_aggregate_table_id(self) -> str:
        """Get fully qualified BigQuery aggregate table ID."""
        return f"{self.project_id}.{self.bq_dataset}.{self.aggregate_table}"

    def _is_firestore_available(self) -> bool:
        """
        Check if Firestore is available.

        Uses a cached check with periodic refresh to avoid hammering
        Firestore when it's down. Session 335: Circuit breaker backs off
        to 5-minute interval after 5 consecutive failures.
        """
        now = datetime.now(timezone.utc)

        # If we've checked recently, use cached result
        if self._last_firestore_check is not None:
            elapsed = (now - self._last_firestore_check).total_seconds()
            # Circuit breaker: use longer cooldown after repeated failures
            check_interval = (
                self._firestore_circuit_breaker_cooldown
                if self._firestore_consecutive_failures >= self._firestore_circuit_breaker_threshold
                else self._firestore_check_interval_seconds
            )
            if elapsed < check_interval:
                return self._firestore_available

        # Perform actual check
        try:
            # Simple read to verify connectivity
            self.firestore_client.collection("_health_check").document("ping").get()
            self._firestore_available = True
            self._firestore_consecutive_failures = 0
        except Exception as e:
            logger.warning(f"Firestore unavailable: {e}")
            self._firestore_available = False
            self._firestore_consecutive_failures += 1
            if self._firestore_consecutive_failures >= self._firestore_circuit_breaker_threshold:
                logger.error(
                    f"CIRCUIT_BREAKER: Firestore down {self._firestore_consecutive_failures} "
                    f"consecutive checks. Backing off to {self._firestore_circuit_breaker_cooldown}s."
                )

        self._last_firestore_check = now
        return self._firestore_available

    def record_completion(
        self,
        phase: str,
        game_date: str,
        processor_name: str,
        completion_data: Dict[str, Any],
        expected_processors: Optional[List[str]] = None
    ) -> Tuple[bool, bool]:
        """
        Record processor completion to both Firestore and BigQuery.

        Writes to Firestore first (for atomic transactions), then to BigQuery
        (for backup and analytics). If Firestore fails, still attempts BigQuery write.

        Args:
            phase: Phase name (e.g., "phase3", "phase4")
            game_date: Game date string (YYYY-MM-DD)
            processor_name: Name of the processor that completed
            completion_data: Dict with status, record_count, correlation_id, etc.
            expected_processors: Optional list of expected processors for this phase

        Returns:
            Tuple of (firestore_success, bigquery_success)
        """
        firestore_success = False
        bigquery_success = False

        # Write to Firestore (primary)
        try:
            firestore_success = self._write_to_firestore(
                phase, game_date, processor_name, completion_data
            )
        except Exception as e:
            logger.error(f"Firestore write failed for {phase}/{game_date}/{processor_name}: {e}", exc_info=True)
            self._firestore_available = False

        # Write to BigQuery (backup) - always attempt even if Firestore fails
        try:
            bigquery_success = self._write_to_bigquery(
                phase, game_date, processor_name, completion_data
            )
        except Exception as e:
            logger.error(f"BigQuery write failed for {phase}/{game_date}/{processor_name}: {e}", exc_info=True)

        # Log outcome
        if firestore_success and bigquery_success:
            logger.debug(f"Dual-write success for {phase}/{game_date}/{processor_name}")
        elif firestore_success:
            logger.warning(f"BigQuery backup failed for {phase}/{game_date}/{processor_name}")
        elif bigquery_success:
            logger.warning(f"Firestore primary failed, BigQuery backup succeeded for {phase}/{game_date}/{processor_name}")
        else:
            logger.error(f"Both Firestore and BigQuery writes failed for {phase}/{game_date}/{processor_name}", exc_info=True)

        return (firestore_success, bigquery_success)

    @retry_with_jitter(
        max_attempts=3,
        base_delay=1.0,
        max_delay=10.0,
        exceptions=(GoogleCloudError,)
    )
    def _write_to_firestore(
        self,
        phase: str,
        game_date: str,
        processor_name: str,
        completion_data: Dict[str, Any]
    ) -> bool:
        """Write completion to Firestore with retry logic."""
        collection = self._get_firestore_collection(phase)
        doc_ref = self.firestore_client.collection(collection).document(game_date)

        # Build completion record
        record = {
            "completed_at": firestore.SERVER_TIMESTAMP,
            "status": completion_data.get("status", "success"),
            "record_count": completion_data.get("record_count", 0),
            "correlation_id": completion_data.get("correlation_id"),
            "execution_id": completion_data.get("execution_id"),
            "is_incremental": completion_data.get("is_incremental", False),
            "entities_changed": completion_data.get("entities_changed", []),
        }

        # Use update with merge to add processor without overwriting others
        doc_ref.set({processor_name: record}, merge=True)

        return True

    def _write_to_bigquery(
        self,
        phase: str,
        game_date: str,
        processor_name: str,
        completion_data: Dict[str, Any]
    ) -> bool:
        """Write completion to BigQuery."""
        import json

        table_id = self._get_bq_table_id()
        now = datetime.now(timezone.utc)

        # Build row for BigQuery
        row = {
            "phase": phase,
            "game_date": game_date,
            "processor_name": processor_name,
            "status": completion_data.get("status", "success"),
            "record_count": completion_data.get("record_count"),
            "correlation_id": completion_data.get("correlation_id"),
            "execution_id": completion_data.get("execution_id"),
            "completed_at": now.isoformat(),
            "is_incremental": completion_data.get("is_incremental", False),
            "entities_changed": completion_data.get("entities_changed", []),
            "metadata": json.dumps(completion_data.get("metadata", {})),
            "inserted_at": now.isoformat(),
        }

        # Insert row using batch loading instead of streaming inserts
        # to avoid 90-minute streaming buffer that blocks DML operations
        from shared.utils.bigquery_utils import insert_bigquery_rows
        short_table_id = f"{self.bq_dataset}.{self.bq_table}"
        success = insert_bigquery_rows(short_table_id, [row], project_id=self.project_id)

        if not success:
            logger.error(f"Failed to insert completion record to BigQuery")
            return False

        return True

    @retry_with_jitter(
        max_attempts=3,
        base_delay=1.0,
        max_delay=15.0,
        exceptions=(GoogleCloudError,)
    )
    def update_aggregate_status(
        self,
        phase: str,
        game_date: str,
        completed_processors: List[str],
        expected_processors: List[str],
        is_triggered: bool = False,
        trigger_reason: Optional[str] = None,
        mode: Optional[str] = None
    ) -> bool:
        """
        Update aggregated completion status in BigQuery with retry logic.

        This provides a single-row view of completion status for each phase/date,
        useful for monitoring dashboards and analytics.

        Args:
            phase: Phase name
            game_date: Game date string
            completed_processors: List of processors that have completed
            expected_processors: List of expected processors
            is_triggered: Whether next phase was triggered
            trigger_reason: Reason for triggering
            mode: Orchestration mode

        Returns:
            True if update succeeded
        """
        table_id = self._get_aggregate_table_id()
        now = datetime.now(timezone.utc)

        # Calculate missing processors
        completed_set = set(completed_processors)
        expected_set = set(expected_processors)
        missing_processors = list(expected_set - completed_set)

        # Build MERGE statement for upsert
        query = f"""
        MERGE `{table_id}` T
        USING (SELECT @phase as phase, @game_date as game_date) S
        ON T.phase = S.phase AND T.game_date = S.game_date
        WHEN MATCHED THEN
            UPDATE SET
                completed_count = @completed_count,
                expected_count = @expected_count,
                completed_processors = @completed_processors,
                missing_processors = @missing_processors,
                is_triggered = @is_triggered,
                triggered_at = IF(@is_triggered AND triggered_at IS NULL, @now, triggered_at),
                trigger_reason = COALESCE(@trigger_reason, trigger_reason),
                mode = COALESCE(@mode, mode),
                last_completion_at = @now,
                updated_at = @now
        WHEN NOT MATCHED THEN
            INSERT (phase, game_date, completed_count, expected_count,
                    completed_processors, missing_processors, is_triggered,
                    triggered_at, trigger_reason, mode, first_completion_at,
                    last_completion_at, updated_at)
            VALUES (@phase, @game_date, @completed_count, @expected_count,
                    @completed_processors, @missing_processors, @is_triggered,
                    IF(@is_triggered, @now, NULL), @trigger_reason, @mode, @now, @now, @now)
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("phase", "STRING", phase),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("completed_count", "INT64", len(completed_processors)),
                bigquery.ScalarQueryParameter("expected_count", "INT64", len(expected_processors)),
                bigquery.ArrayQueryParameter("completed_processors", "STRING", completed_processors),
                bigquery.ArrayQueryParameter("missing_processors", "STRING", missing_processors),
                bigquery.ScalarQueryParameter("is_triggered", "BOOL", is_triggered),
                bigquery.ScalarQueryParameter("trigger_reason", "STRING", trigger_reason),
                bigquery.ScalarQueryParameter("mode", "STRING", mode),
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
            ]
        )

        try:
            job = self.bq_client.query(query, job_config=job_config)
            job.result(timeout=30)
            return True
        except Exception as e:
            logger.error(f"Failed to update aggregate status: {e}", exc_info=True)
            return False

    def get_completion_status(
        self,
        phase: str,
        game_date: str,
        expected_processors: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Get completion status, with fallback from Firestore to BigQuery.

        Tries Firestore first (for real-time data), falls back to BigQuery
        if Firestore is unavailable.

        Args:
            phase: Phase name
            game_date: Game date string
            expected_processors: Optional list of expected processors

        Returns:
            Dict with completion status
        """
        # Try Firestore first
        if self._is_firestore_available():
            try:
                return self._get_status_from_firestore(phase, game_date, expected_processors)
            except Exception as e:
                logger.warning(f"Firestore read failed, falling back to BigQuery: {e}")
                self._firestore_available = False

        # Fallback to BigQuery
        return self._get_status_from_bigquery(phase, game_date, expected_processors)

    def _get_status_from_firestore(
        self,
        phase: str,
        game_date: str,
        expected_processors: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Get completion status from Firestore."""
        collection = self._get_firestore_collection(phase)
        doc_ref = self.firestore_client.collection(collection).document(game_date)
        doc = doc_ref.get()

        if not doc.exists:
            return {
                "phase": phase,
                "game_date": game_date,
                "status": "not_started",
                "completed_count": 0,
                "expected_count": len(expected_processors) if expected_processors else 0,
                "completed_processors": [],
                "missing_processors": list(expected_processors) if expected_processors else [],
                "is_triggered": False,
                "source": "firestore"
            }

        data = doc.to_dict()

        # Extract processor names (exclude metadata fields starting with _)
        completed_processors = [k for k in data.keys() if not k.startswith("_")]
        completed_count = len(completed_processors)

        # Calculate missing
        expected_set = set(expected_processors) if expected_processors else set()
        missing_processors = list(expected_set - set(completed_processors))

        return {
            "phase": phase,
            "game_date": game_date,
            "status": "triggered" if data.get("_triggered") else "in_progress",
            "completed_count": completed_count,
            "expected_count": len(expected_processors) if expected_processors else completed_count,
            "completed_processors": completed_processors,
            "missing_processors": missing_processors,
            "is_triggered": data.get("_triggered", False),
            "triggered_at": data.get("_triggered_at"),
            "trigger_reason": data.get("_trigger_reason"),
            "mode": data.get("_mode"),
            "source": "firestore"
        }

    def _get_status_from_bigquery(
        self,
        phase: str,
        game_date: str,
        expected_processors: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Get completion status from BigQuery (fallback)."""
        # First try the aggregate table
        aggregate_table_id = self._get_aggregate_table_id()

        query = f"""
        SELECT *
        FROM `{aggregate_table_id}`
        WHERE phase = @phase AND game_date = @game_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("phase", "STRING", phase),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        try:
            result = list(self.bq_client.query(query, job_config=job_config).result())

            if result:
                row = result[0]
                return {
                    "phase": phase,
                    "game_date": game_date,
                    "status": "triggered" if row.is_triggered else "in_progress",
                    "completed_count": row.completed_count,
                    "expected_count": row.expected_count,
                    "completed_processors": list(row.completed_processors) if row.completed_processors else [],
                    "missing_processors": list(row.missing_processors) if row.missing_processors else [],
                    "is_triggered": row.is_triggered,
                    "triggered_at": row.triggered_at,
                    "trigger_reason": row.trigger_reason,
                    "mode": row.mode,
                    "source": "bigquery_aggregate"
                }
        except Exception as e:
            logger.warning(f"Aggregate table query failed: {e}")

        # Fall back to querying individual completions
        table_id = self._get_bq_table_id()

        query = f"""
        SELECT DISTINCT processor_name
        FROM `{table_id}`
        WHERE phase = @phase AND game_date = @game_date
        """

        try:
            result = list(self.bq_client.query(query, job_config=job_config).result())
            completed_processors = [row.processor_name for row in result]
            completed_count = len(completed_processors)

            expected_set = set(expected_processors) if expected_processors else set()
            missing_processors = list(expected_set - set(completed_processors))

            return {
                "phase": phase,
                "game_date": game_date,
                "status": "in_progress" if completed_count > 0 else "not_started",
                "completed_count": completed_count,
                "expected_count": len(expected_processors) if expected_processors else completed_count,
                "completed_processors": completed_processors,
                "missing_processors": missing_processors,
                "is_triggered": False,  # Can't determine from individual records
                "source": "bigquery_individual"
            }
        except Exception as e:
            logger.error(f"BigQuery fallback query failed: {e}", exc_info=True)

            return {
                "phase": phase,
                "game_date": game_date,
                "status": "unknown",
                "completed_count": 0,
                "expected_count": len(expected_processors) if expected_processors else 0,
                "completed_processors": [],
                "missing_processors": list(expected_processors) if expected_processors else [],
                "is_triggered": False,
                "error": str(e),
                "source": "error"
            }

    def mark_triggered(
        self,
        phase: str,
        game_date: str,
        trigger_reason: str = "all_complete",
        mode: Optional[str] = None,
        completed_processors: Optional[List[str]] = None,
        expected_processors: Optional[List[str]] = None
    ) -> Tuple[bool, bool]:
        """
        Mark a phase as triggered (next phase started).

        Updates both Firestore and BigQuery aggregate table.

        Args:
            phase: Phase name
            game_date: Game date string
            trigger_reason: Why the phase was triggered
            mode: Orchestration mode
            completed_processors: List of completed processors
            expected_processors: List of expected processors

        Returns:
            Tuple of (firestore_success, bigquery_success)
        """
        firestore_success = False
        bigquery_success = False
        now = datetime.now(timezone.utc)

        # Update Firestore
        try:
            collection = self._get_firestore_collection(phase)
            doc_ref = self.firestore_client.collection(collection).document(game_date)

            doc_ref.update({
                "_triggered": True,
                "_triggered_at": firestore.SERVER_TIMESTAMP,
                "_trigger_reason": trigger_reason,
                "_mode": mode,
            })
            firestore_success = True
        except Exception as e:
            logger.error(f"Failed to mark triggered in Firestore: {e}", exc_info=True)

        # Update BigQuery aggregate table
        if completed_processors and expected_processors:
            try:
                bigquery_success = self.update_aggregate_status(
                    phase=phase,
                    game_date=game_date,
                    completed_processors=completed_processors,
                    expected_processors=expected_processors,
                    is_triggered=True,
                    trigger_reason=trigger_reason,
                    mode=mode
                )
            except Exception as e:
                logger.error(f"Failed to mark triggered in BigQuery: {e}", exc_info=True)

        return (firestore_success, bigquery_success)


# Module-level singleton instance (lazy initialization)
_tracker_instance: Optional[CompletionTracker] = None


def get_completion_tracker(project_id: Optional[str] = None) -> CompletionTracker:
    """
    Get singleton CompletionTracker instance.

    Args:
        project_id: Optional project ID (uses default if not provided)

    Returns:
        CompletionTracker instance
    """
    global _tracker_instance

    if _tracker_instance is None:
        if project_id is None:
            from shared.config.gcp_config import get_project_id
            project_id = get_project_id()

        _tracker_instance = CompletionTracker(project_id=project_id)

    return _tracker_instance

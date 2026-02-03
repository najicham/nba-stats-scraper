# predictions/worker/execution_logger.py

"""
Execution Logger for Phase 5 Prediction Worker

Logs worker execution to prediction_worker_runs table for:
- Monitoring and debugging
- Performance tracking
- Data quality analysis
- Circuit breaker support
- Pattern #4: Processing Metadata
- Trigger tracing (Pub/Sub correlation)

Tracks:
- Which prediction systems ran (and which succeeded/failed)
- Data quality metrics (feature_quality_score, missing features)
- Performance breakdown (data load, compute, write times)
- Circuit breaker triggers
- Error details
- Trigger source and Pub/Sub message ID for tracing

Version: 1.2
Date: 2026-01-28

IMPORTANT: Uses buffered writes to avoid BigQuery partition modification quota limits.
Each Cloud Run instance buffers log entries and flushes them periodically or when
the buffer reaches a threshold. This reduces partition modifications from 300+/batch
to just 1-5/batch.

Quota Issue Fixed (2026-01-28):
- Old behavior: 1 load_table_from_json per player = 300+ partition modifications
- New behavior: Buffer logs, flush at threshold/time = 1-5 partition modifications
- BigQuery limit: ~5000 partition modifications per table per day
"""

import logging
import json
import os
import uuid
import threading
import atexit
from datetime import datetime, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Buffer configuration
BUFFER_FLUSH_THRESHOLD = 50  # Flush when buffer reaches this size
BUFFER_FLUSH_INTERVAL_SECONDS = 30  # Also flush every N seconds (via manual calls)

# Global buffer for log entries (thread-safe)
_log_buffer: List[Dict] = []
_buffer_lock = threading.Lock()


class ExecutionLogger:
    """
    Logs Phase 5 prediction worker execution to BigQuery with buffered writes.

    Each worker request generates one log entry with:
    - Request details (player, game, lines)
    - Execution results (success, duration, predictions generated)
    - System-specific results (which systems succeeded/failed)
    - Data quality metrics
    - Performance breakdown
    - Error tracking

    IMPORTANT: Uses buffered writes to avoid BigQuery partition modification quotas.
    Log entries are buffered in memory and flushed when:
    - Buffer reaches BUFFER_FLUSH_THRESHOLD (default: 50 entries)
    - flush_buffer() is explicitly called (e.g., at end of batch)
    - Process exits (via atexit handler)
    """

    def __init__(self, bq_client: bigquery.Client, project_id: str, worker_version: str = "1.0"):
        """
        Initialize execution logger.

        Args:
            bq_client: BigQuery client
            project_id: GCP project ID
            worker_version: Worker code version
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.worker_version = worker_version
        self.table_id = f'{project_id}.nba_predictions.prediction_worker_runs'
        self._table_schema = None  # Cached schema

        # Capture Cloud Run metadata from environment
        self.cloud_run_service = os.environ.get('K_SERVICE')
        self.cloud_run_revision = os.environ.get('K_REVISION')

        # Register cleanup handler to flush buffer on exit
        atexit.register(self._flush_on_exit)

        logger.info(f"Initialized ExecutionLogger for {self.table_id} (buffered mode)")

    def _flush_on_exit(self):
        """Flush any remaining buffered entries on process exit."""
        try:
            self.flush_buffer()
        except Exception as e:
            logger.error(f"Error flushing buffer on exit: {e}")

    def _get_table_schema(self):
        """Get and cache the table schema."""
        if self._table_schema is None:
            table = self.bq_client.get_table(self.table_id)
            self._table_schema = table.schema
        return self._table_schema

    def flush_buffer(self) -> int:
        """
        Flush all buffered log entries to BigQuery.

        Returns:
            Number of entries flushed
        """
        global _log_buffer

        with _buffer_lock:
            if not _log_buffer:
                return 0

            entries_to_flush = _log_buffer.copy()
            _log_buffer = []

        if not entries_to_flush:
            return 0

        try:
            schema = self._get_table_schema()

            job_config = bigquery.LoadJobConfig(
                schema=schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED
            )

            load_job = self.bq_client.load_table_from_json(
                entries_to_flush,
                self.table_id,
                job_config=job_config
            )

            load_job.result(timeout=120)
            logger.info(f"Flushed {len(entries_to_flush)} execution log entries to BigQuery")
            return len(entries_to_flush)

        except Exception as e:
            # Extract detailed errors from BigQuery load job if available
            error_details = str(e)
            if hasattr(e, '__cause__') and hasattr(e.__cause__, 'errors'):
                error_details = f"{e} - Details: {e.__cause__.errors}"
            elif 'load_job' in dir() and load_job.errors:
                error_details = f"{e} - BigQuery errors: {load_job.errors}"

            logger.error(f"Error flushing execution log buffer: {error_details}", exc_info=True)

            # Log sample of problematic data for debugging
            if entries_to_flush:
                sample_entry = entries_to_flush[0]
                logger.error(f"Sample entry game_date={sample_entry.get('game_date')}, "
                           f"player={sample_entry.get('player_lookup')}")

            # Re-add entries to buffer on failure (best effort)
            # Sanitize REPEATED fields to prevent perpetual failures
            sanitized_entries = []
            for entry in entries_to_flush:
                # Ensure REPEATED fields are never null (BigQuery requirement)
                entry['line_values_requested'] = entry.get('line_values_requested') or []
                entry['systems_attempted'] = entry.get('systems_attempted') or []
                entry['systems_succeeded'] = entry.get('systems_succeeded') or []
                entry['systems_failed'] = entry.get('systems_failed') or []
                entry['missing_features'] = entry.get('missing_features') or []
                entry['circuits_opened'] = entry.get('circuits_opened') or []
                sanitized_entries.append(entry)

            with _buffer_lock:
                _log_buffer = sanitized_entries + _log_buffer
            return 0

    def _add_to_buffer(self, log_entry: Dict) -> None:
        """
        Add a log entry to the buffer and flush if threshold reached.

        Args:
            log_entry: The log entry dictionary
        """
        global _log_buffer

        # Sanitize REPEATED fields BEFORE adding to buffer
        # BigQuery REPEATED fields cannot be NULL - must be empty list
        log_entry['line_values_requested'] = log_entry.get('line_values_requested') or []
        log_entry['systems_attempted'] = log_entry.get('systems_attempted') or []
        log_entry['systems_succeeded'] = log_entry.get('systems_succeeded') or []
        log_entry['systems_failed'] = log_entry.get('systems_failed') or []
        log_entry['missing_features'] = log_entry.get('missing_features') or []
        log_entry['circuits_opened'] = log_entry.get('circuits_opened') or []

        with _buffer_lock:
            _log_buffer.append(log_entry)
            buffer_size = len(_log_buffer)

        # Flush if we've reached the threshold
        if buffer_size >= BUFFER_FLUSH_THRESHOLD:
            logger.debug(f"Buffer reached threshold ({buffer_size}), flushing...")
            self.flush_buffer()

    def log_execution(
        self,
        # Request details
        player_lookup: str,
        universal_player_id: Optional[str],
        game_date: str,  # ISO format string
        game_id: str,
        line_values_requested: List[float],

        # Execution results
        success: bool,
        duration_seconds: float,
        predictions_generated: int,

        # Pattern support
        skip_reason: Optional[str] = None,

        # System results
        systems_attempted: Optional[List[str]] = None,
        systems_succeeded: Optional[List[str]] = None,
        systems_failed: Optional[List[str]] = None,
        system_errors: Optional[Dict[str, str]] = None,

        # Data quality
        feature_quality_score: Optional[float] = None,
        missing_features: Optional[List[str]] = None,
        feature_load_time_seconds: Optional[float] = None,

        # Historical data
        historical_games_count: Optional[int] = None,
        historical_load_time_seconds: Optional[float] = None,

        # Error tracking
        error_message: Optional[str] = None,
        error_system: Optional[str] = None,
        error_type: Optional[str] = None,

        # Performance breakdown
        data_load_seconds: Optional[float] = None,
        prediction_compute_seconds: Optional[float] = None,
        write_bigquery_seconds: Optional[float] = None,
        pubsub_publish_seconds: Optional[float] = None,

        # Circuit breaker
        circuit_breaker_triggered: bool = False,
        circuits_opened: Optional[List[str]] = None,

        # NEW: Tracing fields
        trigger_source: Optional[str] = None,
        trigger_message_id: Optional[str] = None,
        retry_attempt: Optional[int] = None,
        batch_id: Optional[str] = None
    ) -> None:
        """
        Log worker execution to BigQuery.

        Args:
            See prediction_worker_runs schema for field descriptions
        """
        try:
            # Generate unique request ID
            request_id = str(uuid.uuid4())

            # Build log entry
            log_entry = {
                # Execution identifiers
                'request_id': request_id,
                'worker_id': os.environ.get('CLOUD_RUN_REVISION', 'unknown'),
                'run_date': datetime.now(timezone.utc).isoformat(),

                # Request details
                'player_lookup': player_lookup,
                'universal_player_id': universal_player_id,
                'game_date': game_date,
                'game_id': game_id,
                # REQUIRED: REPEATED fields cannot be NULL in BigQuery
                # Convert any falsy value (None, [], "") to empty list
                'line_values_requested': [float(v) for v in line_values_requested] if line_values_requested else [],

                # Execution results
                'success': success,
                'duration_seconds': duration_seconds,
                'predictions_generated': predictions_generated,

                # Pattern support
                'skip_reason': skip_reason,

                # System results
                'systems_attempted': systems_attempted or [],
                'systems_succeeded': systems_succeeded or [],
                'systems_failed': systems_failed or [],
                'system_errors': system_errors,  # Pass dict directly - BigQuery JSON type handles conversion

                # Data quality
                'feature_quality_score': feature_quality_score,
                'missing_features': missing_features or [],
                'feature_load_time_seconds': feature_load_time_seconds,

                # Historical data
                'historical_games_count': historical_games_count,
                'historical_load_time_seconds': historical_load_time_seconds,

                # Error tracking
                'error_message': error_message,
                'error_system': error_system,
                'error_type': error_type,

                # Performance breakdown
                'data_load_seconds': data_load_seconds,
                'prediction_compute_seconds': prediction_compute_seconds,
                'write_bigquery_seconds': write_bigquery_seconds,
                'pubsub_publish_seconds': pubsub_publish_seconds,

                # Circuit breaker
                'circuit_breaker_triggered': circuit_breaker_triggered,
                'circuits_opened': circuits_opened or [],

                # Metadata
                'worker_version': self.worker_version,
                'created_at': datetime.now(timezone.utc).isoformat(),

                # NEW: Tracing fields
                'trigger_source': trigger_source,
                'trigger_message_id': trigger_message_id,
                'cloud_run_service': self.cloud_run_service,
                'cloud_run_revision': self.cloud_run_revision,
                'retry_attempt': retry_attempt,
                'batch_id': batch_id
            }

            # Add to buffer instead of writing directly
            # This avoids BigQuery partition modification quota limits
            # Buffer will auto-flush when it reaches BUFFER_FLUSH_THRESHOLD
            self._add_to_buffer(log_entry)
            logger.debug(f"Buffered execution log for {player_lookup} (request_id={request_id})")

        except Exception as e:
            logger.error(f"Error logging execution: {e}", exc_info=True)
            # Don't fail the request on logging errors

    def log_success(
        self,
        player_lookup: str,
        universal_player_id: Optional[str],
        game_date: str,
        game_id: str,
        line_values: List[float],
        duration_seconds: float,
        predictions_generated: int,
        systems_succeeded: List[str],
        systems_failed: List[str],
        system_errors: Dict[str, str],
        feature_quality_score: float,
        historical_games_count: int,
        performance_breakdown: Dict[str, float]
    ) -> None:
        """
        Convenience method to log successful execution.

        Args:
            See log_execution for parameter descriptions
        """
        self.log_execution(
            player_lookup=player_lookup,
            universal_player_id=universal_player_id,
            game_date=game_date,
            game_id=game_id,
            line_values_requested=line_values,
            success=True,
            duration_seconds=duration_seconds,
            predictions_generated=predictions_generated,
            systems_attempted=['moving_average', 'zone_matchup_v1', 'similarity_balanced_v1', 'xgboost_v1', 'ensemble_v1'],
            systems_succeeded=systems_succeeded,
            systems_failed=systems_failed,
            system_errors=system_errors if system_errors else None,
            feature_quality_score=feature_quality_score,
            historical_games_count=historical_games_count,
            data_load_seconds=performance_breakdown.get('data_load'),
            prediction_compute_seconds=performance_breakdown.get('prediction_compute'),
            write_bigquery_seconds=performance_breakdown.get('write_bigquery'),
            pubsub_publish_seconds=performance_breakdown.get('pubsub_publish')
        )

    def log_failure(
        self,
        player_lookup: str,
        universal_player_id: Optional[str],
        game_date: str,
        game_id: str,
        line_values: List[float],
        duration_seconds: float,
        error_message: str,
        error_type: str,
        skip_reason: Optional[str] = None,
        systems_attempted: Optional[List[str]] = None,
        systems_failed: Optional[List[str]] = None,
        circuit_breaker_triggered: bool = False,
        circuits_opened: Optional[List[str]] = None
    ) -> None:
        """
        Convenience method to log failed execution.

        Args:
            See log_execution for parameter descriptions
        """
        self.log_execution(
            player_lookup=player_lookup,
            universal_player_id=universal_player_id,
            game_date=game_date,
            game_id=game_id,
            line_values_requested=line_values,
            success=False,
            duration_seconds=duration_seconds,
            predictions_generated=0,
            skip_reason=skip_reason,
            systems_attempted=systems_attempted,
            systems_succeeded=[],
            systems_failed=systems_failed,
            error_message=error_message,
            error_type=error_type,
            circuit_breaker_triggered=circuit_breaker_triggered,
            circuits_opened=circuits_opened
        )

    def get_buffer_size(self) -> int:
        """Get the current number of entries in the buffer."""
        global _log_buffer
        with _buffer_lock:
            return len(_log_buffer)

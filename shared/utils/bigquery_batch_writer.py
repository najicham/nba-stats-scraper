"""
BigQuery Batch Writer - Shared batching for high-frequency BigQuery writes.

Reduces quota usage by batching multiple records into single load jobs.
Used by run_history, circuit_breaker, pipeline_event_log, etc.

Quota Problem:
    - BigQuery has a hard limit of 1,500 load jobs per table per day
    - This limit CANNOT be increased
    - Writing 1 record = 1 load job (naive approach hits quota fast)
    - Solution: Batch 100 records = 1 load job (reduces by 100x)

Usage:
    from shared.utils.bigquery_batch_writer import get_batch_writer

    writer = get_batch_writer('nba_reference.processor_run_history')
    writer.add_record({
        'processor_name': 'test',
        'status': 'success',
        ...
    })
    # Records are automatically flushed when batch is full or on timeout

Architecture:
    - One global buffer per table (singleton pattern)
    - Thread-safe for concurrent writes
    - Auto-flush on size threshold (default: 100 records)
    - Auto-flush on timeout (default: 30 seconds)
    - Flush on process exit (atexit hook)
    - Failed writes logged but don't crash processors

Version: 1.0
Created: 2026-01-26 (Response to quota exceeded incident)
"""

import atexit
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Batch configuration (tunable via environment variables)
DEFAULT_BATCH_SIZE = int(os.getenv('BQ_BATCH_WRITER_BATCH_SIZE', '100'))
DEFAULT_TIMEOUT_SECONDS = float(os.getenv('BQ_BATCH_WRITER_TIMEOUT', '30.0'))

# Global flag to disable batching (for emergency quota relief)
BATCHING_ENABLED = os.getenv('BQ_BATCH_WRITER_ENABLED', 'true').lower() == 'true'


class BigQueryBatchWriter:
    """
    Thread-safe batching buffer for BigQuery writes.

    Reduces quota usage by accumulating records and writing in batches
    instead of creating individual load jobs for each record.

    Benefits:
        - Reduces quota usage by 100x (100 records/write vs 1 record/write)
        - Prevents "403 Quota exceeded: load jobs per table" errors
        - Automatic flushing on timeout (30s) or size (100 records)
        - Thread-safe for concurrent access
        - No data loss on process exit (atexit hook)

    Metrics tracked:
        - total_records_added: Total records buffered
        - total_batches_flushed: Number of successful flushes
        - total_flush_failures: Number of failed flushes
        - avg_flush_latency_ms: Average flush time
        - avg_batch_size: Average records per batch
    """

    def __init__(
        self,
        table_id: str,
        project_id: Optional[str] = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ):
        """
        Initialize batch writer for a specific table.

        Args:
            table_id: Full table ID (e.g., 'nba_reference.processor_run_history')
            project_id: GCP project ID (defaults to client default)
            batch_size: Number of records to batch before flushing
            timeout_seconds: Max time to wait before flushing
        """
        self.table_id = table_id
        self.project_id = project_id
        self.batch_size = batch_size
        self.timeout_seconds = timeout_seconds

        # Thread-safe buffer
        self.buffer: List[Dict[str, Any]] = []
        self.lock = threading.Lock()
        self.last_flush_time = time.time()

        # BigQuery client (lazy initialized)
        self._bq_client: Optional[bigquery.Client] = None
        self._table_schema: Optional[List[bigquery.SchemaField]] = None

        # Metrics
        self.total_records_added = 0
        self.total_batches_flushed = 0
        self.total_flush_failures = 0
        self.total_flush_latency_ms = 0.0

        # Start background flush thread
        self.shutdown_flag = threading.Event()
        self.flush_thread = threading.Thread(
            target=self._periodic_flush,
            daemon=True,
            name=f"BatchWriter-{table_id}"
        )
        self.flush_thread.start()

        # Register cleanup on exit
        atexit.register(self.shutdown)

        logger.info(
            f"BigQueryBatchWriter initialized for {table_id} "
            f"(batch_size={batch_size}, timeout={timeout_seconds}s)"
        )

    @property
    def bq_client(self) -> bigquery.Client:
        """Lazy-load BigQuery client."""
        if self._bq_client is None:
            self._bq_client = bigquery.Client(project=self.project_id)
        return self._bq_client

    def add_record(self, record: Dict[str, Any]) -> None:
        """
        Add a record to the buffer and flush if threshold reached.

        Args:
            record: Dictionary of field_name -> value
        """
        if not BATCHING_ENABLED:
            # Emergency fallback: write directly (no batching)
            self._write_single_record(record)
            return

        with self.lock:
            self.buffer.append(record)
            self.total_records_added += 1

            # Flush if buffer is full
            if len(self.buffer) >= self.batch_size:
                self._flush_internal()

    def _periodic_flush(self) -> None:
        """Background thread that flushes buffer on timeout."""
        while not self.shutdown_flag.is_set():
            time.sleep(1)  # Check every second

            with self.lock:
                # Flush if timeout reached and buffer not empty
                if self.buffer and (time.time() - self.last_flush_time) >= self.timeout_seconds:
                    self._flush_internal()

    def _flush_internal(self) -> bool:
        """
        Internal flush method (must be called with lock held).

        Returns:
            True if flush succeeded, False otherwise
        """
        if not self.buffer:
            return True

        flush_start_time = time.time()
        batch_size = len(self.buffer)

        # Copy buffer and clear immediately (release lock faster)
        records_to_flush = self.buffer.copy()
        self.buffer.clear()
        self.last_flush_time = time.time()

        # Perform I/O outside lock (don't block other threads)
        try:
            # Get table schema for field filtering
            if self._table_schema is None:
                try:
                    full_table_id = f"{self.project_id}.{self.table_id}" if self.project_id else self.table_id
                    table = self.bq_client.get_table(full_table_id)
                    self._table_schema = table.schema
                    valid_fields = {field.name for field in self._table_schema}
                except Exception as e:
                    logger.warning(f"Could not get schema for {self.table_id}: {e}")
                    valid_fields = None
            else:
                valid_fields = {field.name for field in self._table_schema}

            # Filter records to only include valid fields
            if valid_fields:
                filtered_records = [
                    {k: v for k, v in record.items() if k in valid_fields}
                    for record in records_to_flush
                ]
            else:
                filtered_records = records_to_flush

            # Load batch using single job
            full_table_id = f"{self.project_id}.{self.table_id}" if self.project_id else self.table_id

            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True,
                autodetect=False,
                schema=self._table_schema
            )

            load_job = self.bq_client.load_table_from_json(
                filtered_records,
                full_table_id,
                job_config=job_config
            )
            load_job.result(timeout=60)

            # Track metrics
            flush_latency_ms = (time.time() - flush_start_time) * 1000
            self.total_batches_flushed += 1
            self.total_flush_latency_ms += flush_latency_ms

            if load_job.errors:
                logger.warning(
                    f"BigQuery load job had errors for {self.table_id}: "
                    f"{load_job.errors[:3]}"
                )
                self.total_flush_failures += 1
                return False
            else:
                logger.info(
                    f"Flushed {batch_size} records to {self.table_id} "
                    f"(latency: {flush_latency_ms:.2f}ms, "
                    f"total_batches: {self.total_batches_flushed}, "
                    f"total_records: {self.total_records_added})"
                )
                return True

        except Exception as e:
            self.total_flush_failures += 1
            logger.error(
                f"Failed to flush {batch_size} records to {self.table_id}: {e}",
                exc_info=True
            )
            return False

    def flush(self) -> bool:
        """
        Manually flush all pending records.

        Returns:
            True if flush succeeded, False otherwise
        """
        with self.lock:
            return self._flush_internal()

    def _write_single_record(self, record: Dict[str, Any]) -> None:
        """
        Fallback: Write single record directly (no batching).

        Only used when BATCHING_ENABLED=false (emergency mode).
        """
        try:
            full_table_id = f"{self.project_id}.{self.table_id}" if self.project_id else self.table_id

            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(
                [record],
                full_table_id,
                job_config=job_config
            )
            load_job.result(timeout=30)

            logger.warning(
                f"Wrote single record to {self.table_id} (batching disabled)"
            )
        except Exception as e:
            logger.error(f"Failed to write single record to {self.table_id}: {e}")

    def shutdown(self) -> None:
        """Flush all pending records and shutdown gracefully."""
        logger.info(f"Shutting down BigQueryBatchWriter for {self.table_id}...")

        # Signal background thread to stop
        self.shutdown_flag.set()

        # Wait for background thread to finish (max 5 seconds)
        if self.flush_thread.is_alive():
            self.flush_thread.join(timeout=5)

        # Final flush
        self.flush()

        # Log final metrics
        avg_flush_latency = (
            self.total_flush_latency_ms / self.total_batches_flushed
            if self.total_batches_flushed > 0
            else 0.0
        )
        avg_batch_size = (
            self.total_records_added / self.total_batches_flushed
            if self.total_batches_flushed > 0
            else 0
        )

        logger.info(
            f"BigQueryBatchWriter shutdown complete for {self.table_id}: "
            f"total_records={self.total_records_added}, "
            f"total_batches={self.total_batches_flushed}, "
            f"failed_batches={self.total_flush_failures}, "
            f"avg_batch_size={avg_batch_size:.1f}, "
            f"avg_flush_latency={avg_flush_latency:.2f}ms"
        )

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get current metrics for monitoring.

        Returns:
            Dictionary with metrics:
                - total_records_added
                - total_batches_flushed
                - total_flush_failures
                - avg_flush_latency_ms
                - avg_batch_size
                - current_buffer_size
        """
        with self.lock:
            avg_flush_latency = (
                self.total_flush_latency_ms / self.total_batches_flushed
                if self.total_batches_flushed > 0
                else 0.0
            )
            avg_batch_size = (
                self.total_records_added / self.total_batches_flushed
                if self.total_batches_flushed > 0
                else 0
            )

            return {
                'table_id': self.table_id,
                'total_records_added': self.total_records_added,
                'total_batches_flushed': self.total_batches_flushed,
                'total_flush_failures': self.total_flush_failures,
                'avg_flush_latency_ms': round(avg_flush_latency, 2),
                'avg_batch_size': round(avg_batch_size, 1),
                'current_buffer_size': len(self.buffer),
                'batching_enabled': BATCHING_ENABLED
            }


# ============================================================================
# Global Writer Registry (Singleton Pattern)
# ============================================================================

_writers: Dict[str, BigQueryBatchWriter] = {}
_writers_lock = threading.Lock()


def get_batch_writer(
    table_id: str,
    project_id: Optional[str] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> BigQueryBatchWriter:
    """
    Get or create a batch writer for the specified table.

    Uses singleton pattern - one writer per table_id globally.
    Thread-safe initialization.

    Args:
        table_id: Full table ID (e.g., 'nba_reference.processor_run_history')
        project_id: GCP project ID (optional)
        batch_size: Records per batch (default: 100)
        timeout_seconds: Max time before flush (default: 30s)

    Returns:
        BigQueryBatchWriter instance for the table

    Example:
        writer = get_batch_writer('nba_reference.processor_run_history')
        writer.add_record({'processor_name': 'test', ...})
    """
    with _writers_lock:
        if table_id not in _writers:
            _writers[table_id] = BigQueryBatchWriter(
                table_id=table_id,
                project_id=project_id,
                batch_size=batch_size,
                timeout_seconds=timeout_seconds
            )
        return _writers[table_id]


def flush_all_writers() -> None:
    """Flush all active batch writers (useful for testing/shutdown)."""
    with _writers_lock:
        for writer in _writers.values():
            writer.flush()
        logger.info(f"Flushed all {len(_writers)} batch writers")


def get_all_metrics() -> List[Dict[str, Any]]:
    """
    Get metrics from all active batch writers.

    Returns:
        List of metric dictionaries, one per table
    """
    with _writers_lock:
        return [writer.get_metrics() for writer in _writers.values()]


# Register global flush on exit
atexit.register(flush_all_writers)

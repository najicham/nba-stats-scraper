"""
Pipeline Event Logger - Comprehensive audit logging for pipeline events.

Logs all pipeline events to BigQuery for observability, debugging, and auto-retry.
Supports processor start/complete, errors, retries, and phase transitions.

Usage:
    from shared.utils.pipeline_logger import log_pipeline_event, PipelineEventType

    # At processor start
    log_pipeline_event(
        event_type=PipelineEventType.PROCESSOR_START,
        phase='phase_3',
        processor_name='player_game_summary',
        game_date='2026-01-24',
        correlation_id='abc-123',
        trigger_source='scheduled'
    )

    # On success
    log_pipeline_event(
        event_type=PipelineEventType.PROCESSOR_COMPLETE,
        phase='phase_3',
        processor_name='player_game_summary',
        game_date='2026-01-24',
        correlation_id='abc-123',
        duration_seconds=45.2,
        records_processed=281
    )

    # On error
    log_pipeline_event(
        event_type=PipelineEventType.ERROR,
        phase='phase_3',
        processor_name='player_game_summary',
        game_date='2026-01-24',
        error_type='transient',
        error_message='Connection timeout',
        stack_trace=traceback.format_exc()
    )

BigQuery Table: nba_orchestration.pipeline_event_log
Created: January 2026
Part of: Pipeline Resilience Improvements
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class PipelineEventType(str, Enum):
    """Types of pipeline events that can be logged."""
    PHASE_START = 'phase_start'
    PHASE_COMPLETE = 'phase_complete'
    PROCESSOR_START = 'processor_start'
    PROCESSOR_COMPLETE = 'processor_complete'
    ERROR = 'error'
    RETRY = 'retry'
    RECOVERY = 'recovery'
    BACKFILL_START = 'backfill_start'
    BACKFILL_COMPLETE = 'backfill_complete'


class ErrorType(str, Enum):
    """Classification of errors for retry decision."""
    TRANSIENT = 'transient'  # Auto-retry eligible (timeout, rate limit, OOM)
    PERMANENT = 'permanent'  # Requires manual intervention (schema mismatch, code bug)


# Module-level BigQuery client (lazy initialized)
_bq_client = None


def _get_bq_client():
    """Get or create BigQuery client (singleton)."""
    global _bq_client
    if _bq_client is None:
        from google.cloud import bigquery
        from shared.config.gcp_config import get_project_id
        _bq_client = bigquery.Client(project=get_project_id())
    return _bq_client


def log_pipeline_event(
    event_type: PipelineEventType,
    phase: Optional[str] = None,
    processor_name: Optional[str] = None,
    game_date: Optional[str] = None,
    correlation_id: Optional[str] = None,
    trigger_source: Optional[str] = None,
    parent_event_id: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    records_processed: Optional[int] = None,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
    stack_trace: Optional[str] = None,
    resolution_action: Optional[str] = None,
    resolution_by: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    dry_run: bool = False
) -> Optional[str]:
    """
    Log a pipeline event to BigQuery.

    Args:
        event_type: Type of event (use PipelineEventType enum)
        phase: Pipeline phase (e.g., 'phase_2', 'phase_3')
        processor_name: Name of the processor (e.g., 'player_game_summary')
        game_date: Date being processed (YYYY-MM-DD)
        correlation_id: Trace ID linking related events
        trigger_source: What triggered this event ('scheduled', 'manual', 'retry', 'backfill')
        parent_event_id: ID of parent event (for retry chains)
        duration_seconds: How long the operation took
        records_processed: Number of records processed
        error_type: 'transient' or 'permanent' (for error events)
        error_message: Error description
        stack_trace: Full stack trace (for error events)
        resolution_action: What action was taken to resolve
        resolution_by: 'auto' or 'manual'
        metadata: Additional context as dict (stored as JSON)
        dry_run: If True, log but don't write to BigQuery

    Returns:
        str: The event_id if logged successfully, None if failed

    Example:
        event_id = log_pipeline_event(
            event_type=PipelineEventType.PROCESSOR_COMPLETE,
            phase='phase_3',
            processor_name='player_game_summary',
            game_date='2026-01-24',
            duration_seconds=45.2,
            records_processed=281
        )
    """
    try:
        # Generate event ID
        event_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)

        # Convert event_type to string if enum
        if isinstance(event_type, PipelineEventType):
            event_type_str = event_type.value
        else:
            event_type_str = str(event_type)

        # Build row
        row = {
            'event_id': event_id,
            'timestamp': timestamp.isoformat(),
            'event_type': event_type_str,
            'phase': phase,
            'processor_name': processor_name,
            'game_date': game_date,
            'correlation_id': correlation_id,
            'trigger_source': trigger_source,
            'parent_event_id': parent_event_id,
            'duration_seconds': duration_seconds,
            'records_processed': records_processed,
            'error_type': error_type,
            'error_message': error_message,
            'stack_trace': stack_trace,
            'resolution_action': resolution_action,
            'resolution_by': resolution_by,
            'metadata': json.dumps(metadata) if metadata else None,
        }

        # Log locally
        log_msg = f"Pipeline event: {event_type_str}"
        if processor_name:
            log_msg += f" - {processor_name}"
        if game_date:
            log_msg += f" for {game_date}"
        if error_message:
            log_msg += f" - {error_message}"
        if duration_seconds:
            log_msg += f" ({duration_seconds:.2f}s)"

        if error_type:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        # Write to BigQuery
        # Use batch loading instead of streaming inserts to avoid 90-minute
        # streaming buffer that blocks DML operations (MERGE/UPDATE/DELETE)
        if not dry_run:
            from shared.config.gcp_config import get_project_id
            from shared.utils.bigquery_utils import insert_bigquery_rows

            project_id = get_project_id()
            dataset = os.environ.get('ORCHESTRATION_DATASET', 'nba_orchestration')
            table = 'pipeline_event_log'
            table_id = f"{dataset}.{table}"

            success = insert_bigquery_rows(table_id, [row], project_id=project_id)

            if not success:
                logger.error(f"Failed to log event to {table_id}")
                return None
            else:
                logger.debug(f"Event logged to {table_id}: {event_id}")
                return event_id
        else:
            logger.info(f"DRY RUN: Would log event: {row}")
            return event_id

    except Exception as e:
        # Don't fail the processor if logging fails
        logger.warning(f"Failed to log pipeline event: {e}")
        return None


def log_processor_start(
    phase: str,
    processor_name: str,
    game_date: str,
    correlation_id: Optional[str] = None,
    trigger_source: str = 'scheduled',
    metadata: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Convenience function to log processor start.

    Returns:
        str: The event_id (use as parent_event_id for completion event)
    """
    return log_pipeline_event(
        event_type=PipelineEventType.PROCESSOR_START,
        phase=phase,
        processor_name=processor_name,
        game_date=game_date,
        correlation_id=correlation_id,
        trigger_source=trigger_source,
        metadata=metadata
    )


def log_processor_complete(
    phase: str,
    processor_name: str,
    game_date: str,
    duration_seconds: float,
    records_processed: int,
    correlation_id: Optional[str] = None,
    parent_event_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Convenience function to log processor completion.
    """
    return log_pipeline_event(
        event_type=PipelineEventType.PROCESSOR_COMPLETE,
        phase=phase,
        processor_name=processor_name,
        game_date=game_date,
        correlation_id=correlation_id,
        parent_event_id=parent_event_id,
        duration_seconds=duration_seconds,
        records_processed=records_processed,
        metadata=metadata
    )


def log_processor_error(
    phase: str,
    processor_name: str,
    game_date: str,
    error_message: str,
    error_type: str = 'transient',
    stack_trace: Optional[str] = None,
    correlation_id: Optional[str] = None,
    parent_event_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Convenience function to log processor error.

    Also queues for retry if error_type is 'transient'.
    """
    event_id = log_pipeline_event(
        event_type=PipelineEventType.ERROR,
        phase=phase,
        processor_name=processor_name,
        game_date=game_date,
        correlation_id=correlation_id,
        parent_event_id=parent_event_id,
        error_type=error_type,
        error_message=error_message,
        stack_trace=stack_trace,
        metadata=metadata
    )

    # Queue for retry if transient
    if error_type == 'transient':
        try:
            queue_for_retry(
                phase=phase,
                processor_name=processor_name,
                game_date=game_date,
                error_message=error_message,
                error_type=error_type,
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.warning(f"Failed to queue for retry: {e}")

    return event_id


def queue_for_retry(
    phase: str,
    processor_name: str,
    game_date: str,
    error_message: str,
    error_type: str = 'transient',
    correlation_id: Optional[str] = None,
    max_retries: int = 3,
    retry_delay_minutes: int = 15
) -> bool:
    """
    Add a failed processor to the retry queue.

    Includes deduplication: if an active entry (pending/retrying) already exists
    for the same processor+game_date+phase, it updates the existing entry
    instead of creating a duplicate.

    Args:
        phase: Pipeline phase
        processor_name: Name of the processor
        game_date: Date being processed
        error_message: Error description
        error_type: 'transient' or 'permanent'
        correlation_id: Trace ID
        max_retries: Maximum retry attempts (default: 3)
        retry_delay_minutes: Minutes until next retry (default: 15)

    Returns:
        bool: True if queued successfully
    """
    try:
        from google.cloud import bigquery
        from shared.config.gcp_config import get_project_id
        from shared.utils.bigquery_utils import insert_bigquery_rows

        project_id = get_project_id()
        dataset = os.environ.get('ORCHESTRATION_DATASET', 'nba_orchestration')
        table = 'failed_processor_queue'
        full_table_id = f"{project_id}.{dataset}.{table}"
        short_table_id = f"{dataset}.{table}"

        client = _get_bq_client()
        now = datetime.now(timezone.utc)
        next_retry = now + __import__('datetime').timedelta(minutes=retry_delay_minutes)

        # Check for existing active entry (deduplication)
        # Use parameterized query to avoid SQL injection
        dedup_query = f"""
        SELECT id, retry_count FROM `{full_table_id}`
        WHERE phase = @phase
          AND processor_name = @processor_name
          AND game_date = DATE(@game_date)
          AND status IN ('pending', 'retrying')
        LIMIT 1
        """

        dedup_job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("phase", "STRING", phase),
                bigquery.ScalarQueryParameter("processor_name", "STRING", processor_name),
                bigquery.ScalarQueryParameter("game_date", "STRING", game_date),
            ]
        )
        existing = list(client.query(dedup_query, job_config=dedup_job_config).result())
        if existing:
            # Update existing entry instead of creating duplicate
            existing_id = existing[0].id
            existing_retry_count = existing[0].retry_count
            logger.info(f"Existing queue entry found for {processor_name}/{game_date}, updating instead of duplicating")

            # Use parameterized query to avoid SQL injection and syntax errors
            update_query = f"""
            UPDATE `{full_table_id}`
            SET
                error_message = @error_message,
                next_retry_at = TIMESTAMP(@next_retry_at),
                status = 'pending',
                updated_at = CURRENT_TIMESTAMP()
            WHERE id = @existing_id
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("error_message", "STRING", error_message[:4000] if error_message else None),
                    bigquery.ScalarQueryParameter("next_retry_at", "STRING", next_retry.isoformat()),
                    bigquery.ScalarQueryParameter("existing_id", "STRING", existing_id),
                ]
            )
            client.query(update_query, job_config=job_config).result()
            logger.info(f"Updated existing queue entry {existing_id} for {processor_name}")
            return True

        # No existing entry - create new one
        # Use batch loading instead of streaming inserts to avoid 90-minute
        # streaming buffer that blocks DML operations (MERGE/UPDATE/DELETE)
        row = {
            'id': str(uuid.uuid4()),
            'game_date': game_date,
            'phase': phase,
            'processor_name': processor_name,
            'error_message': error_message[:4000] if error_message else None,
            'error_type': error_type,
            'retry_count': 0,
            'max_retries': max_retries,
            'first_failure_at': now.isoformat(),
            'next_retry_at': next_retry.isoformat(),
            'status': 'pending',
            'correlation_id': correlation_id,
            'created_at': now.isoformat(),
        }

        success = insert_bigquery_rows(short_table_id, [row], project_id=project_id)

        if not success:
            logger.error(f"Failed to queue for retry")
            return False
        else:
            logger.info(f"Queued {processor_name} for retry at {next_retry}")
            return True

    except Exception as e:
        logger.warning(f"Failed to queue for retry: {e}")
        return False


def classify_error(exception: Exception) -> str:
    """
    Classify an exception as transient or permanent.

    Args:
        exception: The exception to classify

    Returns:
        str: 'transient' or 'permanent'
    """
    error_str = str(exception).lower()
    exception_type = type(exception).__name__

    # Transient errors (auto-retry eligible)
    transient_patterns = [
        'timeout', 'timed out', 'connection', 'network',
        'rate limit', '429', '503', '504', '502',
        'temporary', 'retry', 'unavailable',
        'memory', 'oom', 'killed'
    ]

    for pattern in transient_patterns:
        if pattern in error_str:
            return 'transient'

    # Permanent errors (require manual intervention)
    permanent_patterns = [
        'schema', 'not found', 'permission', 'forbidden',
        'invalid', 'syntax', 'attribute', 'type error',
        'key error', 'name error', 'import error'
    ]

    for pattern in permanent_patterns:
        if pattern in error_str:
            return 'permanent'

    # Default to transient (safer for auto-retry)
    return 'transient'


def mark_retry_succeeded(
    phase: str,
    processor_name: str,
    game_date: str
) -> bool:
    """
    Mark a queue entry as succeeded after a retry completes successfully.

    Call this from processors when they complete successfully to clear
    any pending retry entries.

    Args:
        phase: Pipeline phase
        processor_name: Name of the processor
        game_date: Date that was processed

    Returns:
        bool: True if entry was found and updated
    """
    try:
        from google.cloud import bigquery
        from shared.config.gcp_config import get_project_id

        project_id = get_project_id()
        dataset = os.environ.get('ORCHESTRATION_DATASET', 'nba_orchestration')
        table = 'failed_processor_queue'
        table_id = f"{project_id}.{dataset}.{table}"

        client = _get_bq_client()

        # Update any pending/retrying entries for this processor
        # Use parameterized query to avoid SQL injection
        update_query = f"""
        UPDATE `{table_id}`
        SET
            status = 'succeeded',
            resolution_notes = 'Completed successfully after retry',
            updated_at = CURRENT_TIMESTAMP()
        WHERE phase = @phase
          AND processor_name = @processor_name
          AND game_date = DATE(@game_date)
          AND status IN ('pending', 'retrying')
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("phase", "STRING", phase),
                bigquery.ScalarQueryParameter("processor_name", "STRING", processor_name),
                bigquery.ScalarQueryParameter("game_date", "STRING", game_date),
            ]
        )
        result = client.query(update_query, job_config=job_config).result()
        # BigQuery DML doesn't return affected rows easily, so we just log
        logger.info(f"Marked retry entries as succeeded for {processor_name}/{game_date}")
        return True

    except Exception as e:
        logger.warning(f"Failed to mark retry as succeeded: {e}")
        return False


def cleanup_stale_retrying_entries(max_age_hours: int = 2) -> int:
    """
    Clean up stale 'retrying' entries that have been stuck for too long.

    Entries stuck in 'retrying' status for more than max_age_hours are
    reset to 'pending' to allow re-processing.

    Args:
        max_age_hours: Maximum hours an entry can stay in 'retrying' status

    Returns:
        int: Number of entries cleaned up
    """
    try:
        from google.cloud import bigquery
        from shared.config.gcp_config import get_project_id

        project_id = get_project_id()
        dataset = os.environ.get('ORCHESTRATION_DATASET', 'nba_orchestration')
        table = 'failed_processor_queue'
        table_id = f"{project_id}.{dataset}.{table}"

        client = _get_bq_client()

        # Reset stale 'retrying' entries to 'pending'
        cleanup_query = f"""
        UPDATE `{table_id}`
        SET
            status = 'pending',
            resolution_notes = CONCAT(IFNULL(resolution_notes, ''), ' | Reset from stale retrying status'),
            updated_at = CURRENT_TIMESTAMP()
        WHERE status = 'retrying'
          AND last_retry_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {max_age_hours} HOUR)
        """

        result = client.query(cleanup_query).result()
        logger.info(f"Cleaned up stale 'retrying' entries older than {max_age_hours} hours")
        return 0  # BigQuery doesn't easily return affected row count

    except Exception as e:
        logger.warning(f"Failed to cleanup stale retrying entries: {e}")
        return 0


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    print("Demo: Pipeline Event Logger\n")
    print("=" * 60)

    # Log processor start (dry run)
    event_id = log_processor_start(
        phase='phase_3',
        processor_name='player_game_summary',
        game_date='2026-01-24',
        correlation_id='demo-123',
        trigger_source='manual'
    )
    print(f"Start event ID: {event_id}")

    # Log processor complete (dry run)
    complete_id = log_processor_complete(
        phase='phase_3',
        processor_name='player_game_summary',
        game_date='2026-01-24',
        duration_seconds=45.2,
        records_processed=281,
        correlation_id='demo-123',
        parent_event_id=event_id
    )
    print(f"Complete event ID: {complete_id}")

    # Test error classification
    print("\nError Classification Examples:")
    print(f"  'Connection timeout': {classify_error(Exception('Connection timeout'))}")
    print(f"  'AttributeError: x': {classify_error(AttributeError('x'))}")
    print(f"  'Rate limit exceeded': {classify_error(Exception('Rate limit exceeded'))}")

    print("\nDemo complete!")

"""
BigQuery Retry Logic for Serialization Errors and Quota Limits

This module provides retry decorators for handling BigQuery errors:
1. Serialization errors from concurrent MERGE/UPDATE operations
2. Quota exceeded errors from too many concurrent DML operations

Error Examples:
    400 Could not serialize access to table nba-props-platform:nba_raw.br_rosters_current
        due to concurrent update

    403 Quota exceeded: Your table exceeded quota for total number of dml jobs
        writing to a table, pending + running

Usage:
    from orchestration.shared.utils.bigquery_retry import SERIALIZATION_RETRY, QUOTA_RETRY

    query_job = bq_client.query(query)

    @SERIALIZATION_RETRY
    def execute_with_retry():
        return query_job.result(timeout=60)

    execute_with_retry()
"""

from google.api_core import retry
from google.api_core.exceptions import BadRequest, Forbidden, ServiceUnavailable, DeadlineExceeded
import logging
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def extract_table_name(error_message: str) -> Optional[str]:
    """
    Extract BigQuery table name from error message.

    Example error message:
        "400 Could not serialize access to table nba-props-platform:nba_raw.br_rosters_current due to concurrent update"

    Returns:
        Table name (e.g., "nba_raw.br_rosters_current") or None if not found
    """
    # Pattern: "table PROJECT:DATASET.TABLE" or "table DATASET.TABLE"
    pattern = r'table\s+(?:[^:]+:)?([^\s]+(?:\.[^\s]+)?)'
    match = re.search(pattern, error_message)
    if match:
        return match.group(1)
    return None


def is_serialization_error(exc):
    """
    Predicate function to identify BigQuery serialization errors.

    Args:
        exc: Exception to check

    Returns:
        bool: True if the exception is a serialization error
    """
    if not isinstance(exc, BadRequest):
        return False

    error_message = str(exc)
    serialization_indicators = [
        "Could not serialize access",
        "due to concurrent update",
        "concurrent DML statements"
    ]

    is_serialization = any(indicator in error_message for indicator in serialization_indicators)

    if is_serialization:
        table_name = extract_table_name(error_message)

        # Structured logging for retry metrics
        logger.warning(
            "BigQuery serialization conflict detected - will retry",
            extra={
                'event_type': 'bigquery_serialization_conflict',
                'table_name': table_name,
                'error_message': error_message[:200],  # Truncate long messages
                'timestamp': datetime.utcnow().isoformat(),
                'retry_triggered': True
            }
        )

    return is_serialization


# Retry configuration for BigQuery serialization errors
#
# Retry strategy:
# - Initial delay: 1 second
# - Maximum delay: 32 seconds
# - Multiplier: 2.0 (exponential backoff)
# - Total deadline: 120 seconds (2 minutes)
#
# Retry sequence: 1s, 2s, 4s, 8s, 16s, 32s (max ~60s total)
SERIALIZATION_RETRY = retry.Retry(
    predicate=is_serialization_error,
    initial=1.0,      # 1 second initial delay
    maximum=32.0,     # 32 seconds maximum delay between retries
    multiplier=2.0,   # Exponential backoff multiplier
    deadline=120.0    # 2 minute total timeout
)


def retry_on_serialization(func):
    """
    Decorator to automatically retry a function on BigQuery serialization errors.

    This decorator adds structured logging to track retry attempts, successes,
    and failures for BigQuery serialization conflicts.

    Usage:
        @retry_on_serialization
        def execute_query():
            query_job = bq_client.query(query)
            return query_job.result(timeout=60)

        result = execute_query()

    Args:
        func: Function to wrap with retry logic

    Returns:
        Wrapped function with retry behavior
    """
    def wrapper(*args, **kwargs):
        start_time = datetime.utcnow()
        attempt_successful = False
        error_info = None

        try:
            @SERIALIZATION_RETRY
            def _execute():
                return func(*args, **kwargs)

            result = _execute()
            attempt_successful = True

            # Log successful execution (may have retried)
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            logger.info(
                "BigQuery operation completed successfully",
                extra={
                    'event_type': 'bigquery_retry_success',
                    'function_name': func.__name__,
                    'duration_ms': duration_ms,
                    'timestamp': datetime.utcnow().isoformat()
                }
            )

            return result

        except Exception as e:
            # Log retry exhaustion or non-retryable error
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            error_info = str(e)
            table_name = extract_table_name(error_info) if isinstance(e, BadRequest) else None

            logger.error(
                "BigQuery operation failed after retries" if is_serialization_error(e) else "BigQuery operation failed",
                extra={
                    'event_type': 'bigquery_retry_exhausted' if is_serialization_error(e) else 'bigquery_operation_failed',
                    'function_name': func.__name__,
                    'table_name': table_name,
                    'error_message': error_info[:200],
                    'duration_ms': duration_ms,
                    'timestamp': datetime.utcnow().isoformat()
                },
                exc_info=True
            )

            raise

    return wrapper


def is_quota_exceeded_error(exc):
    """
    Predicate function to identify BigQuery quota exceeded errors.

    These occur when too many concurrent DML operations target the same table,
    exceeding BigQuery's per-table concurrent DML operation limit (~10-15).

    Args:
        exc: Exception to check

    Returns:
        bool: True if the exception is a quota exceeded error
    """
    if not isinstance(exc, Forbidden):
        return False

    error_message = str(exc)
    quota_indicators = [
        "Quota exceeded",
        "quota for total number of dml jobs",
        "pending + running"
    ]

    is_quota_error = any(indicator in error_message for indicator in quota_indicators)

    if is_quota_error:
        table_name = extract_table_name(error_message)

        # Structured logging for retry metrics
        logger.warning(
            "BigQuery quota exceeded - too many concurrent DML operations - will retry",
            extra={
                'event_type': 'bigquery_quota_exceeded',
                'table_name': table_name,
                'error_message': error_message[:200],
                'timestamp': datetime.utcnow().isoformat(),
                'retry_triggered': True,
                'recommendation': 'Consider implementing table-level semaphore to limit concurrent operations'
            }
        )

    return is_quota_error


# Retry configuration for BigQuery quota exceeded errors
#
# Retry strategy (more aggressive backoff than serialization):
# - Initial delay: 2 seconds (give time for other operations to complete)
# - Maximum delay: 120 seconds (2 minutes)
# - Multiplier: 2.0 (exponential backoff)
# - Total deadline: 600 seconds (10 minutes)
#
# Retry sequence: 2s, 4s, 8s, 16s, 32s, 64s, 120s, 120s... (max ~10min total)
#
# Why longer than serialization retry:
# - Quota errors indicate sustained high load, not just transient conflicts
# - Need more time for concurrent operations to complete
# - Operations are queued rather than conflicting
QUOTA_RETRY = retry.Retry(
    predicate=is_quota_exceeded_error,
    initial=2.0,       # 2 second initial delay
    maximum=120.0,     # 120 seconds maximum delay between retries
    multiplier=2.0,    # Exponential backoff multiplier
    deadline=600.0     # 10 minute total timeout
)


def retry_on_quota_exceeded(func):
    """
    Decorator to automatically retry a function on BigQuery quota exceeded errors.

    This decorator handles cases where too many concurrent DML operations
    target the same BigQuery table, causing quota limit errors.

    Usage:
        @retry_on_quota_exceeded
        def execute_merge():
            query_job = bq_client.query(merge_query)
            return query_job.result(timeout=120)

        result = execute_merge()

    Args:
        func: Function to wrap with retry logic

    Returns:
        Wrapped function with retry behavior
    """
    def wrapper(*args, **kwargs):
        start_time = datetime.utcnow()
        attempt_successful = False
        error_info = None

        try:
            @QUOTA_RETRY
            def _execute():
                return func(*args, **kwargs)

            result = _execute()
            attempt_successful = True

            # Log successful execution (may have retried)
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            logger.info(
                "BigQuery operation completed successfully after quota retry",
                extra={
                    'event_type': 'bigquery_quota_retry_success',
                    'function_name': func.__name__,
                    'duration_ms': duration_ms,
                    'timestamp': datetime.utcnow().isoformat()
                }
            )

            return result

        except Exception as e:
            # Log retry exhaustion or non-retryable error
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            error_info = str(e)
            table_name = extract_table_name(error_info) if isinstance(e, (BadRequest, Forbidden)) else None

            logger.error(
                "BigQuery operation failed after quota retries" if is_quota_exceeded_error(e) else "BigQuery operation failed",
                extra={
                    'event_type': 'bigquery_quota_retry_exhausted' if is_quota_exceeded_error(e) else 'bigquery_operation_failed',
                    'function_name': func.__name__,
                    'table_name': table_name,
                    'error_message': error_info[:200],
                    'duration_ms': duration_ms,
                    'timestamp': datetime.utcnow().isoformat(),
                    'recommendation': 'Implement table-level semaphore or reduce concurrent operations' if is_quota_exceeded_error(e) else None
                },
                exc_info=True
            )

            raise

    return wrapper


def is_transient_error(exc):
    """
    Predicate function to identify transient BigQuery errors.

    These are temporary errors that should resolve on retry:
    - ServiceUnavailable (503): BigQuery service temporarily unavailable
    - DeadlineExceeded: Query timeout (may succeed on retry with less load)

    Args:
        exc: Exception to check

    Returns:
        bool: True if the exception is a transient error
    """
    is_transient = isinstance(exc, (ServiceUnavailable, DeadlineExceeded))

    if is_transient:
        error_type = type(exc).__name__
        error_message = str(exc)

        # Structured logging for retry metrics
        logger.warning(
            f"BigQuery transient error ({error_type}) - will retry",
            extra={
                'event_type': 'bigquery_transient_error',
                'error_type': error_type,
                'error_message': error_message[:200],
                'timestamp': datetime.utcnow().isoformat(),
                'retry_triggered': True
            }
        )

    return is_transient


# Retry configuration for BigQuery transient errors
#
# Retry strategy:
# - Initial delay: 1 second
# - Maximum delay: 30 seconds
# - Multiplier: 2.0 (exponential backoff)
# - Total deadline: 180 seconds (3 minutes)
#
# Retry sequence: 1s, 2s, 4s, 8s, 16s, 30s (max ~60s between, ~3min total)
#
# Why 3 minutes:
# - Transient errors usually resolve within seconds
# - Don't want to hold up batch processing too long
# - Worker has overall timeout of 4 hours
TRANSIENT_RETRY = retry.Retry(
    predicate=is_transient_error,
    initial=1.0,       # 1 second initial delay
    maximum=30.0,      # 30 seconds maximum delay between retries
    multiplier=2.0,    # Exponential backoff multiplier
    deadline=180.0     # 3 minute total timeout
)


def retry_on_transient(func):
    """
    Decorator to automatically retry a function on transient BigQuery errors.

    Handles ServiceUnavailable and DeadlineExceeded errors with exponential
    backoff. These errors are often caused by temporary service issues or
    high load and typically resolve on retry.

    Usage:
        @retry_on_transient
        def execute_query():
            query_job = bq_client.query(query)
            return query_job.result(timeout=120)

        result = execute_query()

    Args:
        func: Function to wrap with retry logic

    Returns:
        Wrapped function with retry behavior
    """
    def wrapper(*args, **kwargs):
        start_time = datetime.utcnow()

        try:
            @TRANSIENT_RETRY
            def _execute():
                return func(*args, **kwargs)

            result = _execute()

            # Log successful execution (may have retried)
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            logger.debug(
                "BigQuery operation completed successfully",
                extra={
                    'event_type': 'bigquery_transient_retry_success',
                    'function_name': func.__name__,
                    'duration_ms': duration_ms,
                    'timestamp': datetime.utcnow().isoformat()
                }
            )

            return result

        except Exception as e:
            # Log retry exhaustion or non-retryable error
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            error_info = str(e)
            error_type = type(e).__name__

            logger.error(
                f"BigQuery operation failed after transient retries ({error_type})" if is_transient_error(e) else f"BigQuery operation failed ({error_type})",
                extra={
                    'event_type': 'bigquery_transient_retry_exhausted' if is_transient_error(e) else 'bigquery_operation_failed',
                    'function_name': func.__name__,
                    'error_type': error_type,
                    'error_message': error_info[:200],
                    'duration_ms': duration_ms,
                    'timestamp': datetime.utcnow().isoformat()
                },
                exc_info=True
            )

            raise

    return wrapper

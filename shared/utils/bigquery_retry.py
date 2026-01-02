"""
BigQuery Retry Logic for Serialization Errors

This module provides retry decorators for handling BigQuery serialization errors
that occur when multiple Cloud Run instances execute concurrent MERGE/UPDATE
operations on the same BigQuery partition.

Error Example:
    400 Could not serialize access to table nba-props-platform:nba_raw.br_rosters_current
    due to concurrent update

Usage:
    from shared.utils.bigquery_retry import SERIALIZATION_RETRY

    query_job = bq_client.query(query)

    @SERIALIZATION_RETRY
    def execute_with_retry():
        return query_job.result(timeout=60)

    execute_with_retry()
"""

from google.api_core import retry
from google.api_core.exceptions import BadRequest
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
                }
            )

            raise

    return wrapper

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

logger = logging.getLogger(__name__)


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
        logger.warning(f"Detected serialization error: {error_message}")

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

    This is an alternative to using the SERIALIZATION_RETRY decorator directly.

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
        @SERIALIZATION_RETRY
        def _execute():
            return func(*args, **kwargs)
        return _execute()

    return wrapper

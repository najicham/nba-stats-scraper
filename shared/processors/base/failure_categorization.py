"""
Failure Categorization Utilities for Processors

This module provides standardized failure categorization for all processors
(analytics, precompute, raw). It enables:
- 90%+ reduction in false alerts by distinguishing expected vs real errors
- Consistent error classification across all phases
- Better monitoring and alerting

Categories:
- no_data_available: Expected - no data to process (don't alert)
- upstream_failure: Dependency failed or missing
- processing_error: Real error in processing logic (alert!)
- timeout: Operation timed out
- configuration_error: Missing required options
- unknown: Unclassified error

Usage:
    from shared.processors.base import categorize_failure, FailureCategory

    try:
        # processing logic
    except Exception as e:
        category = categorize_failure(e, step='transform')
        if category == FailureCategory.PROCESSING_ERROR:
            send_alert(...)

Created: 2026-01-24 (Session 12 - Extracted from analytics_base.py)
"""

from enum import Enum
from typing import Optional, Dict


class FailureCategory(str, Enum):
    """Enumeration of processor failure categories."""
    NO_DATA_AVAILABLE = 'no_data_available'
    UPSTREAM_FAILURE = 'upstream_failure'
    PROCESSING_ERROR = 'processing_error'
    TIMEOUT = 'timeout'
    CONFIGURATION_ERROR = 'configuration_error'
    UNKNOWN = 'unknown'


# Error patterns for each category
NO_DATA_PATTERNS = [
    'no data loaded',
    'no data available',
    'no games scheduled',
    'no records found',
    'file not found',
    'no data to process',
    'empty response',
    'no results',
    'off-season',
    'off season',
    'no players',
    'no prop lines',
    'no betting',
]

NO_DATA_ERROR_TYPES = [
    'FileNotFoundError',
    'NoDataAvailableError',
    'NoDataAvailableSuccess',
    'EmptyDataFrameError',
]

DEPENDENCY_PATTERNS = [
    'dependency',
    'upstream',
    'missing dependency',
    'stale dependency',
    'dependency check failed',
    'prerequisite',
]

DEPENDENCY_ERROR_TYPES = [
    'DependencyError',
    'UpstreamDependencyError',
    'DataTooStaleError',
    'PrerequisiteError',
]

TIMEOUT_PATTERNS = [
    'timeout',
    'timed out',
    'deadline exceeded',
    'operation timed out',
]

TIMEOUT_ERROR_TYPES = [
    'TimeoutError',
    'DeadlineExceeded',
    'TimeoutException',
    'asyncio.TimeoutError',
]


def categorize_failure(
    error: Exception,
    step: str = 'unknown',
    stats: Optional[Dict] = None
) -> str:
    """
    Categorize a processor failure for monitoring and alerting.

    This function determines whether a failure is expected (no_data_available)
    or a real error (processing_error), enabling alert filtering to reduce
    noise by 90%+.

    Args:
        error: The exception that caused the failure
        step: Current processing step (initialization, load, transform, save)
        stats: Optional processor stats dict (for additional context)

    Returns:
        str: Failure category (one of FailureCategory values)
            - 'no_data_available': Expected - no data to process
            - 'upstream_failure': Dependency failed or missing
            - 'processing_error': Real error in processing logic
            - 'timeout': Operation timed out
            - 'configuration_error': Missing required options
            - 'unknown': Unclassified error

    Examples:
        >>> categorize_failure(FileNotFoundError("no data"), "load")
        'no_data_available'

        >>> categorize_failure(DependencyError("stale"), "check")
        'upstream_failure'

        >>> categorize_failure(ValueError("invalid data"), "transform")
        'processing_error'
    """
    error_type = type(error).__name__
    error_msg = str(error).lower()

    # Configuration errors (early in lifecycle)
    if error_type == 'ValueError' and step == 'initialization':
        if 'missing required option' in error_msg or 'missing' in error_msg:
            return FailureCategory.CONFIGURATION_ERROR.value

    # No data available scenarios (EXPECTED - don't alert)
    if any(pattern in error_msg for pattern in NO_DATA_PATTERNS):
        return FailureCategory.NO_DATA_AVAILABLE.value

    if error_type in NO_DATA_ERROR_TYPES:
        return FailureCategory.NO_DATA_AVAILABLE.value

    # Upstream/dependency failures
    if any(pattern in error_msg for pattern in DEPENDENCY_PATTERNS):
        return FailureCategory.UPSTREAM_FAILURE.value

    if error_type in DEPENDENCY_ERROR_TYPES:
        return FailureCategory.UPSTREAM_FAILURE.value

    # Timeout errors
    if any(pattern in error_msg for pattern in TIMEOUT_PATTERNS):
        return FailureCategory.TIMEOUT.value

    if error_type in TIMEOUT_ERROR_TYPES:
        return FailureCategory.TIMEOUT.value

    # BigQuery-specific errors
    if 'bigquery' in error_msg or error_type.startswith('Google'):
        if 'streaming buffer' in error_msg:
            return FailureCategory.NO_DATA_AVAILABLE.value  # Transient, will self-heal
        return FailureCategory.PROCESSING_ERROR.value

    # Default: real processing error (ALERT!)
    return FailureCategory.PROCESSING_ERROR.value


def should_alert(category: str) -> bool:
    """
    Determine if a failure category should trigger an alert.

    Args:
        category: Failure category string

    Returns:
        True if this failure should trigger an alert
    """
    alertable = {
        FailureCategory.PROCESSING_ERROR.value,
        FailureCategory.CONFIGURATION_ERROR.value,
        FailureCategory.UNKNOWN.value,
    }
    return category in alertable


def get_severity(category: str) -> str:
    """
    Get alert severity for a failure category.

    Args:
        category: Failure category string

    Returns:
        Severity level: 'critical', 'warning', or 'info'
    """
    severity_map = {
        FailureCategory.PROCESSING_ERROR.value: 'critical',
        FailureCategory.CONFIGURATION_ERROR.value: 'critical',
        FailureCategory.TIMEOUT.value: 'warning',
        FailureCategory.UPSTREAM_FAILURE.value: 'warning',
        FailureCategory.NO_DATA_AVAILABLE.value: 'info',
        FailureCategory.UNKNOWN.value: 'warning',
    }
    return severity_map.get(category, 'warning')

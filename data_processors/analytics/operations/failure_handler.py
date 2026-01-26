"""
Failure categorization and handling utilities for analytics processors.

This module provides utilities for categorizing and handling processor failures,
enabling intelligent error classification and retry logic.

Version: 1.0
Created: 2026-01-25
"""

from typing import Optional, Dict


def categorize_failure(error: Exception, step: str, stats: Optional[Dict] = None) -> str:
    """
    Categorize a processor failure for monitoring and alerting.

    This function determines whether a failure is expected (no_data_available)
    or a real error (processing_error), enabling alert filtering to reduce
    noise by 90%+.

    Args:
        error: The exception that caused the failure
        step: Current processing step (initialization, load, transform, save)
        stats: Optional processor stats dict

    Returns:
        str: Failure category
            - 'no_data_available': Expected - no data to process
            - 'upstream_failure': Dependency failed or missing
            - 'processing_error': Real error in processing logic
            - 'timeout': Operation timed out
            - 'configuration_error': Missing required options
            - 'unknown': Unclassified error
    """
    error_type = type(error).__name__
    error_msg = str(error).lower()

    # Configuration errors
    if error_type == 'ValueError' and step == 'initialization':
        if 'missing required option' in error_msg or 'missing' in error_msg:
            return 'configuration_error'

    # No data available scenarios (EXPECTED - don't alert)
    no_data_patterns = [
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
    ]
    if any(pattern in error_msg for pattern in no_data_patterns):
        return 'no_data_available'

    if error_type in ['FileNotFoundError', 'NoDataAvailableError', 'NoDataAvailableSuccess']:
        return 'no_data_available'

    # Upstream/dependency failures
    dependency_patterns = [
        'dependency',
        'upstream',
        'missing dependency',
        'stale dependency',
        'dependency check failed',
    ]
    if any(pattern in error_msg for pattern in dependency_patterns):
        return 'upstream_failure'

    if error_type in ['DependencyError', 'UpstreamDependencyError', 'DataTooStaleError']:
        return 'upstream_failure'

    # Timeout errors
    timeout_patterns = [
        'timeout',
        'timed out',
        'deadline exceeded',
    ]
    if any(pattern in error_msg for pattern in timeout_patterns):
        return 'timeout'

    if error_type in ['TimeoutError', 'DeadlineExceeded']:
        return 'timeout'

    # BigQuery-specific errors
    if 'bigquery' in error_msg or error_type.startswith('Google'):
        if 'streaming buffer' in error_msg:
            return 'no_data_available'  # Transient, will self-heal
        return 'processing_error'

    # Default: real processing error (ALERT!)
    return 'processing_error'

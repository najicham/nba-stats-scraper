"""
Retry Configuration
===================
Centralized configuration for retry strategies across the platform.

Provides standard retry profiles that can be used consistently across:
- HTTP requests
- BigQuery queries
- API calls
- Pub/Sub operations

Usage:
    from shared.config.retry_config import RetryConfig, get_retry_config

    # Get config for a specific operation type
    config = get_retry_config('bigquery')
    result = client.query(query).result(timeout=config.timeout)

    # Use with decorators
    from shared.config.retry_config import RETRY_PROFILES
    @retry(**RETRY_PROFILES['standard'])
    def my_function():
        ...

Version: 1.0
Created: 2026-01-24
"""

import os
from dataclasses import dataclass
from typing import Dict, Tuple
from datetime import timedelta


@dataclass
class RetryProfile:
    """Configuration for a retry strategy."""
    max_attempts: int
    base_delay_seconds: float
    max_delay_seconds: float
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: Tuple = ()
    retryable_status_codes: Tuple = (429, 500, 502, 503, 504)


@dataclass
class TimeoutConfig:
    """Timeout configuration for different operation types."""
    # HTTP/API timeouts
    http_connect: int = 10
    http_read: int = 30
    api_call: int = 60

    # BigQuery timeouts
    bigquery_query: int = 60
    bigquery_query_large: int = 300
    bigquery_load: int = 600
    bigquery_extract: int = 300

    # Pub/Sub timeouts
    pubsub_publish: int = 30
    pubsub_pull: int = 60

    # Cloud Run/Function timeouts
    cloud_function: int = 540  # 9 minutes (max is 9 min for 1st gen)
    cloud_run: int = 3600  # 1 hour


# Pre-defined retry profiles
RETRY_PROFILES: Dict[str, dict] = {
    # Fast retry for quick operations (API calls, cache lookups)
    'fast': {
        'max_attempts': 3,
        'base_delay': 0.5,
        'max_delay': 2.0,
        'exponential_base': 2.0,
    },

    # Standard retry for most operations
    'standard': {
        'max_attempts': 3,
        'base_delay': 1.0,
        'max_delay': 10.0,
        'exponential_base': 2.0,
    },

    # Patient retry for operations that may take time to recover
    'patient': {
        'max_attempts': 5,
        'base_delay': 2.0,
        'max_delay': 30.0,
        'exponential_base': 2.0,
    },

    # Aggressive retry for critical operations
    'aggressive': {
        'max_attempts': 10,
        'base_delay': 1.0,
        'max_delay': 60.0,
        'exponential_base': 1.5,
    },

    # BigQuery specific (longer delays, fewer attempts)
    'bigquery': {
        'max_attempts': 3,
        'base_delay': 5.0,
        'max_delay': 30.0,
        'exponential_base': 2.0,
    },

    # Pub/Sub specific
    'pubsub': {
        'max_attempts': 3,
        'base_delay': 1.0,
        'max_delay': 10.0,
        'exponential_base': 2.0,
    },
}

# Default timeout configuration
_timeout_config = TimeoutConfig()


def get_timeout_config() -> TimeoutConfig:
    """Get the global timeout configuration."""
    return _timeout_config


def get_retry_profile(profile_name: str = 'standard') -> dict:
    """
    Get a retry profile by name.

    Args:
        profile_name: One of 'fast', 'standard', 'patient', 'aggressive', 'bigquery', 'pubsub'

    Returns:
        Dict with retry configuration
    """
    return RETRY_PROFILES.get(profile_name, RETRY_PROFILES['standard'])


def get_timeout(operation_type: str) -> int:
    """
    Get timeout for a specific operation type.

    Args:
        operation_type: One of:
            - 'http_connect', 'http_read', 'api_call'
            - 'bigquery_query', 'bigquery_query_large', 'bigquery_load', 'bigquery_extract'
            - 'pubsub_publish', 'pubsub_pull'
            - 'cloud_function', 'cloud_run'

    Returns:
        Timeout in seconds
    """
    return getattr(_timeout_config, operation_type, 60)


# Environment variable overrides
def _load_env_overrides():
    """Load timeout overrides from environment variables."""
    global _timeout_config

    env_mappings = {
        'TIMEOUT_HTTP_CONNECT': 'http_connect',
        'TIMEOUT_HTTP_READ': 'http_read',
        'TIMEOUT_API_CALL': 'api_call',
        'TIMEOUT_BIGQUERY_QUERY': 'bigquery_query',
        'TIMEOUT_BIGQUERY_QUERY_LARGE': 'bigquery_query_large',
        'TIMEOUT_BIGQUERY_LOAD': 'bigquery_load',
        'TIMEOUT_PUBSUB_PUBLISH': 'pubsub_publish',
    }

    for env_var, attr_name in env_mappings.items():
        value = os.environ.get(env_var)
        if value:
            try:
                setattr(_timeout_config, attr_name, int(value))
            except ValueError:
                pass  # Invalid value, keep default


# Load overrides on module import
_load_env_overrides()


# Convenience constants for common timeouts
TIMEOUT_BIGQUERY_QUERY = _timeout_config.bigquery_query
TIMEOUT_BIGQUERY_LOAD = _timeout_config.bigquery_load
TIMEOUT_HTTP_REQUEST = _timeout_config.http_read
TIMEOUT_API_CALL = _timeout_config.api_call
TIMEOUT_PUBSUB_PUBLISH = _timeout_config.pubsub_publish

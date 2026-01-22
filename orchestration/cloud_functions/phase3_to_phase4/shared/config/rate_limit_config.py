"""
Rate Limit Configuration

Central configuration for rate limit handling across all scrapers and API clients.

Environment Variables:
    Core Rate Limiting:
    - RATE_LIMIT_MAX_RETRIES: Maximum retry attempts for 429 errors (default: 5)
    - RATE_LIMIT_BASE_BACKOFF: Base backoff in seconds for exponential backoff (default: 2.0)
    - RATE_LIMIT_MAX_BACKOFF: Maximum backoff in seconds (default: 120.0)

    Circuit Breaker:
    - RATE_LIMIT_CB_THRESHOLD: Consecutive 429s before circuit breaker trips (default: 10)
    - RATE_LIMIT_CB_TIMEOUT: Circuit breaker cooldown in seconds (default: 300)

    Feature Flags:
    - RATE_LIMIT_CB_ENABLED: Enable circuit breaker (default: true)
    - RATE_LIMIT_RETRY_AFTER_ENABLED: Enable Retry-After header parsing (default: true)

    HTTP Pool & Scraper Config:
    - HTTP_POOL_BACKOFF_FACTOR: Backoff factor for http_pool (default: 0.5)
    - SCRAPER_BACKOFF_FACTOR: Backoff factor for scrapers (default: 3.0)

Usage:
    # In Cloud Run service configuration:
    gcloud run services update SERVICE_NAME \\
        --set-env-vars=RATE_LIMIT_MAX_RETRIES=5 \\
        --set-env-vars=RATE_LIMIT_CB_ENABLED=true

    # In .env file:
    RATE_LIMIT_MAX_RETRIES=5
    RATE_LIMIT_BASE_BACKOFF=2.0
    RATE_LIMIT_CB_THRESHOLD=10

Created: January 21, 2026
Part of: Robustness Improvements Implementation
"""

import os
from typing import Dict, Any


# Default configuration values
DEFAULTS = {
    # Core rate limiting
    'RATE_LIMIT_MAX_RETRIES': 5,
    'RATE_LIMIT_BASE_BACKOFF': 2.0,
    'RATE_LIMIT_MAX_BACKOFF': 120.0,

    # Circuit breaker
    'RATE_LIMIT_CB_THRESHOLD': 10,
    'RATE_LIMIT_CB_TIMEOUT': 300,  # 5 minutes

    # Feature flags
    'RATE_LIMIT_CB_ENABLED': True,
    'RATE_LIMIT_RETRY_AFTER_ENABLED': True,

    # HTTP pool & scraper
    'HTTP_POOL_BACKOFF_FACTOR': 0.5,
    'SCRAPER_BACKOFF_FACTOR': 3.0,
}


def get_rate_limit_config() -> Dict[str, Any]:
    """
    Get current rate limit configuration from environment variables.

    Returns:
        Dictionary with all rate limit configuration values
    """
    config = {}

    for key, default_value in DEFAULTS.items():
        env_value = os.getenv(key)

        if env_value is None:
            config[key] = default_value
        else:
            # Parse based on default type
            if isinstance(default_value, bool):
                config[key] = env_value.lower() in ('true', '1', 'yes')
            elif isinstance(default_value, int):
                config[key] = int(env_value)
            elif isinstance(default_value, float):
                config[key] = float(env_value)
            else:
                config[key] = env_value

    return config


def validate_config(config: Dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Validate rate limit configuration values.

    Args:
        config: Configuration dictionary to validate

    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []

    # Validate positive numbers
    positive_int_keys = ['RATE_LIMIT_MAX_RETRIES', 'RATE_LIMIT_CB_THRESHOLD']
    for key in positive_int_keys:
        if key in config and config[key] <= 0:
            errors.append(f"{key} must be positive, got {config[key]}")

    positive_float_keys = [
        'RATE_LIMIT_BASE_BACKOFF',
        'RATE_LIMIT_MAX_BACKOFF',
        'RATE_LIMIT_CB_TIMEOUT',
        'HTTP_POOL_BACKOFF_FACTOR',
        'SCRAPER_BACKOFF_FACTOR'
    ]
    for key in positive_float_keys:
        if key in config and config[key] <= 0:
            errors.append(f"{key} must be positive, got {config[key]}")

    # Validate logical relationships
    if config.get('RATE_LIMIT_MAX_BACKOFF', 0) < config.get('RATE_LIMIT_BASE_BACKOFF', 0):
        errors.append(
            f"RATE_LIMIT_MAX_BACKOFF ({config['RATE_LIMIT_MAX_BACKOFF']}) "
            f"must be >= RATE_LIMIT_BASE_BACKOFF ({config['RATE_LIMIT_BASE_BACKOFF']})"
        )

    return len(errors) == 0, errors


def print_config_summary():
    """
    Print current rate limit configuration (useful for debugging).
    """
    config = get_rate_limit_config()
    is_valid, errors = validate_config(config)

    print("=" * 70)
    print("RATE LIMIT CONFIGURATION")
    print("=" * 70)

    print("\nCore Rate Limiting:")
    print(f"  Max Retries:         {config['RATE_LIMIT_MAX_RETRIES']}")
    print(f"  Base Backoff:        {config['RATE_LIMIT_BASE_BACKOFF']}s")
    print(f"  Max Backoff:         {config['RATE_LIMIT_MAX_BACKOFF']}s")

    print("\nCircuit Breaker:")
    print(f"  Threshold:           {config['RATE_LIMIT_CB_THRESHOLD']} consecutive 429s")
    print(f"  Timeout:             {config['RATE_LIMIT_CB_TIMEOUT']}s ({config['RATE_LIMIT_CB_TIMEOUT']/60:.1f} minutes)")
    print(f"  Enabled:             {config['RATE_LIMIT_CB_ENABLED']}")

    print("\nFeature Flags:")
    print(f"  Retry-After:         {config['RATE_LIMIT_RETRY_AFTER_ENABLED']}")

    print("\nHTTP Configuration:")
    print(f"  HTTP Pool Backoff:   {config['HTTP_POOL_BACKOFF_FACTOR']}s")
    print(f"  Scraper Backoff:     {config['SCRAPER_BACKOFF_FACTOR']}s")

    print("\nConfiguration Status:")
    if is_valid:
        print("  ✓ Valid")
    else:
        print("  ✗ Invalid:")
        for error in errors:
            print(f"    - {error}")

    print("=" * 70)


# Metrics collection helper
class RateLimitMetrics:
    """
    Helper class for collecting and reporting rate limit metrics.

    This integrates with Cloud Monitoring / BigQuery for tracking rate limit behavior.
    """

    @staticmethod
    def format_for_bigquery(metrics: Dict[str, Any], timestamp: str = None) -> Dict[str, Any]:
        """
        Format rate limit metrics for BigQuery insertion.

        Args:
            metrics: Metrics from RateLimitHandler.get_metrics()
            timestamp: ISO timestamp (defaults to now)

        Returns:
            Dictionary formatted for BigQuery
        """
        from datetime import datetime, timezone

        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()

        # Flatten 429 counts by domain
        rate_limit_events = []
        for domain, count in metrics.get('429_count', {}).items():
            rate_limit_events.append({
                'timestamp': timestamp,
                'domain': domain,
                'event_type': 'rate_limit_429',
                'count': count
            })

        # Flatten circuit breaker trips
        for domain, count in metrics.get('circuit_breaker_trips', {}).items():
            rate_limit_events.append({
                'timestamp': timestamp,
                'domain': domain,
                'event_type': 'circuit_breaker_trip',
                'count': count
            })

        # Add summary metrics
        rate_limit_events.append({
            'timestamp': timestamp,
            'domain': 'all',
            'event_type': 'retry_after_respected',
            'count': metrics.get('retry_after_respected', 0)
        })

        rate_limit_events.append({
            'timestamp': timestamp,
            'domain': 'all',
            'event_type': 'retry_after_missing',
            'count': metrics.get('retry_after_missing', 0)
        })

        return {
            'timestamp': timestamp,
            'events': rate_limit_events,
            'circuit_breaker_states': metrics.get('circuit_breaker_states', {})
        }

    @staticmethod
    def format_for_cloud_monitoring(metrics: Dict[str, Any]) -> list[Dict[str, Any]]:
        """
        Format rate limit metrics for Cloud Monitoring (Stackdriver).

        Args:
            metrics: Metrics from RateLimitHandler.get_metrics()

        Returns:
            List of metric points for Cloud Monitoring
        """
        metric_points = []

        # Total 429 count across all domains
        total_429s = sum(metrics.get('429_count', {}).values())
        metric_points.append({
            'metric': 'rate_limit.429_total',
            'value': total_429s,
            'type': 'counter'
        })

        # 429 count by domain
        for domain, count in metrics.get('429_count', {}).items():
            metric_points.append({
                'metric': 'rate_limit.429_by_domain',
                'value': count,
                'labels': {'domain': domain},
                'type': 'counter'
            })

        # Circuit breaker trips
        total_cb_trips = sum(metrics.get('circuit_breaker_trips', {}).values())
        metric_points.append({
            'metric': 'rate_limit.circuit_breaker_trips',
            'value': total_cb_trips,
            'type': 'counter'
        })

        # Retry-After header metrics
        metric_points.append({
            'metric': 'rate_limit.retry_after_respected',
            'value': metrics.get('retry_after_respected', 0),
            'type': 'counter'
        })

        metric_points.append({
            'metric': 'rate_limit.retry_after_missing',
            'value': metrics.get('retry_after_missing', 0),
            'type': 'counter'
        })

        # Open circuit breakers (gauge)
        open_circuits = sum(
            1 for state in metrics.get('circuit_breaker_states', {}).values()
            if state.get('is_open', False)
        )
        metric_points.append({
            'metric': 'rate_limit.circuit_breakers_open',
            'value': open_circuits,
            'type': 'gauge'
        })

        return metric_points


if __name__ == '__main__':
    # Print configuration when run directly
    print_config_summary()

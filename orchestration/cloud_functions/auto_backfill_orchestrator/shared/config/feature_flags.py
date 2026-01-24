"""
Feature Flags Configuration for Week 1-4 Improvements

This module provides centralized feature flag management for safe,
gradual rollout of all improvements.

Usage:
    from shared.config.feature_flags import FeatureFlags

    flags = FeatureFlags()
    if flags.enable_idempotency_keys:
        # New behavior
    else:
        # Old behavior
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class FeatureFlags:
    """
    Centralized feature flags for Week 1-4 improvements.

    All flags default to False (disabled) for safety.
    Enable via environment variables in production.
    """

    # ========================================
    # Week 1 Feature Flags
    # ========================================

    # Day 1: Critical Scalability
    enable_phase2_completion_deadline: bool = False
    phase2_completion_timeout_minutes: int = 30

    enable_subcollection_completions: bool = False
    dual_write_mode: bool = True  # Write to both old and new
    use_subcollection_reads: bool = False  # Read from new structure

    # Day 2: Cost Optimization
    enable_query_caching: bool = False
    query_cache_ttl_seconds: int = 3600

    # Day 3: Data Integrity
    enable_idempotency_keys: bool = False
    dedup_ttl_days: int = 7

    # Day 4: Configuration
    enable_parallel_config: bool = False
    enable_centralized_timeouts: bool = False

    # Day 5: Observability
    enable_structured_logging: bool = False
    enable_health_check_metrics: bool = False

    # ========================================
    # Week 2 Feature Flags (Placeholder)
    # ========================================
    enable_prometheus_metrics: bool = False
    enable_universal_retry: bool = False
    enable_async_phase1: bool = False

    # ========================================
    # Week 3 Feature Flags (Placeholder)
    # ========================================
    enable_async_complete: bool = False
    enable_integration_tests: bool = False

    def __init__(self):
        """Initialize feature flags from environment variables."""
        # Week 1 Flags
        self.enable_phase2_completion_deadline = self._get_bool_env(
            'ENABLE_PHASE2_COMPLETION_DEADLINE', False
        )
        self.phase2_completion_timeout_minutes = self._get_int_env(
            'PHASE2_COMPLETION_TIMEOUT_MINUTES', 30
        )

        self.enable_subcollection_completions = self._get_bool_env(
            'ENABLE_SUBCOLLECTION_COMPLETIONS', False
        )
        self.dual_write_mode = self._get_bool_env('DUAL_WRITE_MODE', True)
        self.use_subcollection_reads = self._get_bool_env(
            'USE_SUBCOLLECTION_READS', False
        )

        self.enable_query_caching = self._get_bool_env('ENABLE_QUERY_CACHING', False)
        self.query_cache_ttl_seconds = self._get_int_env(
            'QUERY_CACHE_TTL_SECONDS', 3600
        )

        self.enable_idempotency_keys = self._get_bool_env(
            'ENABLE_IDEMPOTENCY_KEYS', False
        )
        self.dedup_ttl_days = self._get_int_env('DEDUP_TTL_DAYS', 7)

        self.enable_parallel_config = self._get_bool_env(
            'ENABLE_PARALLEL_CONFIG', False
        )
        self.enable_centralized_timeouts = self._get_bool_env(
            'ENABLE_CENTRALIZED_TIMEOUTS', False
        )

        self.enable_structured_logging = self._get_bool_env(
            'ENABLE_STRUCTURED_LOGGING', False
        )
        self.enable_health_check_metrics = self._get_bool_env(
            'ENABLE_HEALTH_CHECK_METRICS', False
        )

        # Week 2-3 Flags (Placeholder)
        self.enable_prometheus_metrics = self._get_bool_env(
            'ENABLE_PROMETHEUS_METRICS', False
        )
        self.enable_universal_retry = self._get_bool_env(
            'ENABLE_UNIVERSAL_RETRY', False
        )
        self.enable_async_phase1 = self._get_bool_env('ENABLE_ASYNC_PHASE1', False)
        self.enable_async_complete = self._get_bool_env(
            'ENABLE_ASYNC_COMPLETE', False
        )
        self.enable_integration_tests = self._get_bool_env(
            'ENABLE_INTEGRATION_TESTS', False
        )

    @staticmethod
    def _get_bool_env(key: str, default: bool) -> bool:
        """Get boolean environment variable."""
        value = os.getenv(key, str(default)).lower()
        return value in ('true', '1', 'yes', 'on')

    @staticmethod
    def _get_int_env(key: str, default: int) -> int:
        """Get integer environment variable."""
        try:
            return int(os.getenv(key, str(default)))
        except ValueError:
            return default

    def get_status_report(self) -> dict:
        """
        Get current status of all feature flags.

        Returns:
            dict: Flag names and their current values
        """
        return {
            # Week 1
            'phase2_completion_deadline': self.enable_phase2_completion_deadline,
            'subcollection_completions': self.enable_subcollection_completions,
            'dual_write_mode': self.dual_write_mode,
            'use_subcollection_reads': self.use_subcollection_reads,
            'query_caching': self.enable_query_caching,
            'idempotency_keys': self.enable_idempotency_keys,
            'parallel_config': self.enable_parallel_config,
            'centralized_timeouts': self.enable_centralized_timeouts,
            'structured_logging': self.enable_structured_logging,
            'health_check_metrics': self.enable_health_check_metrics,
            # Week 2-3
            'prometheus_metrics': self.enable_prometheus_metrics,
            'universal_retry': self.enable_universal_retry,
            'async_phase1': self.enable_async_phase1,
            'async_complete': self.enable_async_complete,
            'integration_tests': self.enable_integration_tests,
        }

    def __repr__(self) -> str:
        """String representation of feature flags."""
        enabled = [k for k, v in self.get_status_report().items() if v]
        disabled = [k for k, v in self.get_status_report().items() if not v]
        return (
            f"FeatureFlags(enabled={len(enabled)}, disabled={len(disabled)})\n"
            f"Enabled: {', '.join(enabled) if enabled else 'None'}\n"
            f"Disabled: {', '.join(disabled) if disabled else 'None'}"
        )


# Global instance for easy import
feature_flags = FeatureFlags()


# Convenience functions for common patterns
def is_feature_enabled(flag_name: str) -> bool:
    """
    Check if a feature flag is enabled.

    Args:
        flag_name: Name of the flag (e.g., 'enable_idempotency_keys')

    Returns:
        bool: True if enabled, False otherwise
    """
    return getattr(feature_flags, flag_name, False)


def require_feature(flag_name: str) -> None:
    """
    Raise exception if feature flag is not enabled.

    Args:
        flag_name: Name of the flag

    Raises:
        RuntimeError: If flag is not enabled
    """
    if not is_feature_enabled(flag_name):
        raise RuntimeError(
            f"Feature '{flag_name}' is not enabled. "
            f"Set environment variable to enable."
        )


# Example usage and testing
if __name__ == '__main__':
    # Display current feature flag status
    flags = FeatureFlags()
    print(flags)
    print("\nDetailed status:")
    for name, value in flags.get_status_report().items():
        status = "✅ ENABLED" if value else "❌ DISABLED"
        print(f"  {name:30s} {status}")

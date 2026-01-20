"""
Centralized Timeout Configuration

This module consolidates all timeout values across the codebase into
a single source of truth. Previously, 1,070+ timeout values were
scattered across files.

Usage:
    from shared.config.timeout_config import TimeoutConfig

    timeout = TimeoutConfig.SCRAPER_HTTP_TIMEOUT
    response = requests.post(url, timeout=timeout)
"""

from dataclasses import dataclass
import os


@dataclass
class TimeoutConfig:
    """
    Centralized timeout configuration for all components.

    All values are in seconds unless otherwise specified.
    Can be overridden via environment variables.
    """

    # ========================================
    # HTTP Timeouts
    # ========================================

    # Scraper HTTP calls (3 minutes)
    SCRAPER_HTTP_TIMEOUT: int = 180

    # Future timeout for parallel execution
    # Should be slightly higher than HTTP timeout for overhead
    FUTURE_TIMEOUT: int = 190  # SCRAPER_HTTP_TIMEOUT + 10

    # Health check endpoint timeout (10 seconds)
    HEALTH_CHECK_TIMEOUT: int = 10

    # Internal service-to-service calls (30 seconds)
    INTERNAL_SERVICE_TIMEOUT: int = 30

    # External API calls (general) (60 seconds)
    EXTERNAL_API_TIMEOUT: int = 60

    # ========================================
    # BigQuery Timeouts
    # ========================================

    # Standard BigQuery query timeout (60 seconds)
    BIGQUERY_QUERY_TIMEOUT: int = 60

    # Long-running analytics query (5 minutes)
    BIGQUERY_LONG_QUERY_TIMEOUT: int = 300

    # BigQuery job completion wait (10 minutes)
    BIGQUERY_JOB_TIMEOUT: int = 600

    # ========================================
    # Firestore Timeouts
    # ========================================

    # Standard Firestore operations (30 seconds)
    FIRESTORE_OPERATION_TIMEOUT: int = 30

    # Batch write operations (60 seconds)
    FIRESTORE_BATCH_TIMEOUT: int = 60

    # Transaction timeout (60 seconds)
    FIRESTORE_TRANSACTION_TIMEOUT: int = 60

    # Distributed lock acquisition (30 seconds)
    FIRESTORE_LOCK_TIMEOUT: int = 30

    # Lock polling interval (10 seconds)
    FIRESTORE_LOCK_POLL_INTERVAL: int = 10

    # ========================================
    # Orchestration Timeouts
    # ========================================

    # Workflow execution timeout (10 minutes)
    WORKFLOW_EXECUTION_TIMEOUT: int = 600

    # Phase transition timeout (10 minutes)
    PHASE_TRANSITION_TIMEOUT: int = 600

    # Phase 2 completion deadline (30 minutes)
    PHASE2_COMPLETION_TIMEOUT: int = 1800

    # Phase 4→5 Tiered timeouts (in seconds)
    PHASE4_TIER1_TIMEOUT: int = 1800  # 30 min (all 5 processors)
    PHASE4_TIER2_TIMEOUT: int = 3600  # 1 hour (4/5 processors)
    PHASE4_TIER3_TIMEOUT: int = 7200  # 2 hours (3/5 processors)
    PHASE4_MAX_TIMEOUT: int = 14400   # 4 hours (fallback)

    # Coordinator stall detection (10 minutes after 95% complete)
    COORDINATOR_STALL_TIMEOUT: int = 600

    # ========================================
    # Retry & Circuit Breaker Timeouts
    # ========================================

    # Circuit breaker timeout (5 minutes)
    CIRCUIT_BREAKER_TIMEOUT: int = 300

    # Retry base delay (1 second)
    RETRY_BASE_DELAY: float = 1.0

    # Retry max delay (60 seconds)
    RETRY_MAX_DELAY: float = 60.0

    # ========================================
    # Cloud Run Timeouts
    # ========================================

    # Cloud Run request timeout (maximum: 60 minutes)
    CLOUD_RUN_REQUEST_TIMEOUT: int = 3600  # 1 hour

    # Cloud Run startup probe timeout
    CLOUD_RUN_STARTUP_TIMEOUT: int = 240  # 4 minutes

    # Cloud Run liveness probe timeout
    CLOUD_RUN_LIVENESS_TIMEOUT: int = 60  # 1 minute

    # ========================================
    # Pub/Sub Timeouts
    # ========================================

    # Pub/Sub acknowledge deadline (10 minutes)
    PUBSUB_ACK_DEADLINE: int = 600

    # Pub/Sub message retention (7 days in seconds)
    PUBSUB_MESSAGE_RETENTION: int = 604800

    # ========================================
    # Testing Timeouts
    # ========================================

    # Unit test timeout (5 seconds)
    UNIT_TEST_TIMEOUT: int = 5

    # Integration test timeout (60 seconds)
    INTEGRATION_TEST_TIMEOUT: int = 60

    # Load test timeout (5 minutes)
    LOAD_TEST_TIMEOUT: int = 300

    @classmethod
    def from_env(cls):
        """
        Create TimeoutConfig with values from environment variables.

        Environment variables override defaults.
        Variable names: TIMEOUT_<CONSTANT_NAME>

        Example:
            TIMEOUT_SCRAPER_HTTP_TIMEOUT=240
        """
        config = cls()

        # Iterate over all class attributes
        for attr_name in dir(config):
            if attr_name.isupper():  # Only process constants
                env_var = f"TIMEOUT_{attr_name}"
                env_value = os.getenv(env_var)

                if env_value:
                    try:
                        # Try integer first
                        setattr(config, attr_name, int(env_value))
                    except ValueError:
                        try:
                            # Try float
                            setattr(config, attr_name, float(env_value))
                        except ValueError:
                            # Keep default
                            pass

        return config

    @classmethod
    def get_all_timeouts(cls) -> dict:
        """
        Get all timeout values as a dictionary.

        Returns:
            dict: All timeout constants and their values
        """
        config = cls()
        return {
            attr_name: getattr(config, attr_name)
            for attr_name in dir(config)
            if attr_name.isupper()
        }

    @classmethod
    def validate(cls) -> list:
        """
        Validate timeout configuration.

        Returns:
            list: List of validation warnings/errors
        """
        warnings = []
        config = cls()

        # Validation: Future timeout should be > HTTP timeout
        if config.FUTURE_TIMEOUT <= config.SCRAPER_HTTP_TIMEOUT:
            warnings.append(
                f"FUTURE_TIMEOUT ({config.FUTURE_TIMEOUT}s) should be greater than "
                f"SCRAPER_HTTP_TIMEOUT ({config.SCRAPER_HTTP_TIMEOUT}s)"
            )

        # Validation: Tiered timeouts should be ascending
        if not (
            config.PHASE4_TIER1_TIMEOUT
            < config.PHASE4_TIER2_TIMEOUT
            < config.PHASE4_TIER3_TIMEOUT
            < config.PHASE4_MAX_TIMEOUT
        ):
            warnings.append("Phase 4 tiered timeouts should be in ascending order")

        # Validation: Cloud Run timeout should accommodate longest operation
        max_operation_timeout = max(
            config.WORKFLOW_EXECUTION_TIMEOUT,
            config.BIGQUERY_JOB_TIMEOUT,
            config.PHASE_TRANSITION_TIMEOUT,
        )
        if config.CLOUD_RUN_REQUEST_TIMEOUT < max_operation_timeout:
            warnings.append(
                f"CLOUD_RUN_REQUEST_TIMEOUT ({config.CLOUD_RUN_REQUEST_TIMEOUT}s) "
                f"is less than longest operation ({max_operation_timeout}s)"
            )

        return warnings


# Global instance for easy import
timeout_config = TimeoutConfig()


# Convenience function
def get_timeout(timeout_name: str, default: int = 30) -> int:
    """
    Get timeout value by name.

    Args:
        timeout_name: Name of timeout constant (e.g., 'SCRAPER_HTTP_TIMEOUT')
        default: Default value if not found

    Returns:
        int: Timeout value in seconds
    """
    return getattr(timeout_config, timeout_name, default)


# Example usage and testing
if __name__ == '__main__':
    # Display all timeouts
    print("=== Centralized Timeout Configuration ===\n")

    config = TimeoutConfig()

    # Group by category
    categories = {
        'HTTP': [
            'SCRAPER_HTTP_TIMEOUT',
            'FUTURE_TIMEOUT',
            'HEALTH_CHECK_TIMEOUT',
            'INTERNAL_SERVICE_TIMEOUT',
            'EXTERNAL_API_TIMEOUT',
        ],
        'BigQuery': [
            'BIGQUERY_QUERY_TIMEOUT',
            'BIGQUERY_LONG_QUERY_TIMEOUT',
            'BIGQUERY_JOB_TIMEOUT',
        ],
        'Firestore': [
            'FIRESTORE_OPERATION_TIMEOUT',
            'FIRESTORE_BATCH_TIMEOUT',
            'FIRESTORE_TRANSACTION_TIMEOUT',
            'FIRESTORE_LOCK_TIMEOUT',
            'FIRESTORE_LOCK_POLL_INTERVAL',
        ],
        'Orchestration': [
            'WORKFLOW_EXECUTION_TIMEOUT',
            'PHASE_TRANSITION_TIMEOUT',
            'PHASE2_COMPLETION_TIMEOUT',
            'PHASE4_TIER1_TIMEOUT',
            'PHASE4_TIER2_TIMEOUT',
            'PHASE4_TIER3_TIMEOUT',
            'PHASE4_MAX_TIMEOUT',
            'COORDINATOR_STALL_TIMEOUT',
        ],
    }

    for category, timeouts in categories.items():
        print(f"{category} Timeouts:")
        for timeout_name in timeouts:
            value = getattr(config, timeout_name)
            if value >= 60:
                display = f"{value}s ({value//60}m)"
            else:
                display = f"{value}s"
            print(f"  {timeout_name:35s} {display}")
        print()

    # Validate configuration
    warnings = TimeoutConfig.validate()
    if warnings:
        print("⚠️  Validation Warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("✅ All timeout validations passed")

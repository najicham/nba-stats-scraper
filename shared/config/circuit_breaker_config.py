"""
Circuit Breaker Configuration
=============================
Centralized configuration for circuit breaker thresholds across all processors.

Allows tuning via environment variables without code changes:
- CIRCUIT_BREAKER_THRESHOLD: Number of failures before opening (default: 5)
- CIRCUIT_BREAKER_TIMEOUT_MINUTES: Minutes to stay open (default: 30)

Usage in processors:
    from shared.config.circuit_breaker_config import (
        CIRCUIT_BREAKER_THRESHOLD,
        CIRCUIT_BREAKER_TIMEOUT
    )

    class MyProcessor(CircuitBreakerMixin, ProcessorBase):
        CIRCUIT_BREAKER_THRESHOLD = CIRCUIT_BREAKER_THRESHOLD
        CIRCUIT_BREAKER_TIMEOUT = CIRCUIT_BREAKER_TIMEOUT

Version: 1.1
Created: 2026-01-24
Updated: 2026-01-24 - Import defaults from shared.constants.resilience
"""

import os
from datetime import timedelta

# Import centralized defaults from resilience constants
from shared.constants.resilience import (
    CIRCUIT_BREAKER_THRESHOLD as BASE_THRESHOLD,
    CIRCUIT_BREAKER_TIMEOUT_MINUTES as BASE_TIMEOUT_MINUTES,
)


def _get_env_int(key: str, default: int) -> int:
    """Get integer from environment variable with default."""
    value = os.environ.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_env_float(key: str, default: float) -> float:
    """Get float from environment variable with default."""
    value = os.environ.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


# ============================================================
# CIRCUIT BREAKER DEFAULTS (with env var override support)
# ============================================================

# Number of consecutive failures before opening circuit
# Higher = more tolerant of transient failures
# Lower = faster failure detection
# Base default from: shared.constants.resilience
CIRCUIT_BREAKER_THRESHOLD = _get_env_int('CIRCUIT_BREAKER_THRESHOLD', BASE_THRESHOLD)

# Minutes to keep circuit open before trying half-open state
# Higher = longer recovery time, less load on failing systems
# Lower = faster recovery attempts
# Base default from: shared.constants.resilience
CIRCUIT_BREAKER_TIMEOUT_MINUTES = _get_env_int('CIRCUIT_BREAKER_TIMEOUT_MINUTES', BASE_TIMEOUT_MINUTES)
CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=CIRCUIT_BREAKER_TIMEOUT_MINUTES)


# ============================================================
# PROCESSOR-SPECIFIC OVERRIDES
# ============================================================
# Some processors may need different thresholds based on their
# criticality and typical failure patterns.

class ProcessorCircuitConfig:
    """
    Per-processor circuit breaker configuration.

    Processors can look up their specific config or use defaults.
    """

    # Default config (used if processor not in overrides)
    DEFAULT = {
        'threshold': CIRCUIT_BREAKER_THRESHOLD,
        'timeout_minutes': CIRCUIT_BREAKER_TIMEOUT_MINUTES,
    }

    # Processor-specific overrides
    # Format: 'ProcessorClassName': {'threshold': N, 'timeout_minutes': M}
    OVERRIDES = {
        # Phase 5 predictions are critical - fail faster, recover faster
        'PredictionCoordinator': {
            'threshold': 3,
            'timeout_minutes': 15,
        },
        # ML Feature Store is end of Phase 4 - can be more tolerant
        'MLFeatureStoreProcessor': {
            'threshold': 5,
            'timeout_minutes': 30,
        },
        # Scrapers may have transient issues - be more tolerant
        # (Scrapers don't use circuit breaker mixin, but included for reference)
    }

    @classmethod
    def get_threshold(cls, processor_name: str) -> int:
        """Get threshold for a processor."""
        if processor_name in cls.OVERRIDES:
            return cls.OVERRIDES[processor_name].get(
                'threshold',
                cls.DEFAULT['threshold']
            )
        return cls.DEFAULT['threshold']

    @classmethod
    def get_timeout(cls, processor_name: str) -> timedelta:
        """Get timeout for a processor."""
        if processor_name in cls.OVERRIDES:
            minutes = cls.OVERRIDES[processor_name].get(
                'timeout_minutes',
                cls.DEFAULT['timeout_minutes']
            )
        else:
            minutes = cls.DEFAULT['timeout_minutes']
        return timedelta(minutes=minutes)

    @classmethod
    def get_config(cls, processor_name: str) -> dict:
        """Get full config for a processor."""
        return {
            'threshold': cls.get_threshold(processor_name),
            'timeout': cls.get_timeout(processor_name),
            'timeout_minutes': cls.get_timeout(processor_name).total_seconds() / 60,
        }


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

def get_circuit_breaker_config(processor_name: str = None) -> dict:
    """
    Get circuit breaker configuration.

    Args:
        processor_name: Optional processor class name for specific config

    Returns:
        Dict with 'threshold' and 'timeout' keys
    """
    if processor_name:
        return ProcessorCircuitConfig.get_config(processor_name)

    return {
        'threshold': CIRCUIT_BREAKER_THRESHOLD,
        'timeout': CIRCUIT_BREAKER_TIMEOUT,
        'timeout_minutes': CIRCUIT_BREAKER_TIMEOUT_MINUTES,
    }

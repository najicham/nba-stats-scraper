"""
External Service Circuit Breaker

Provides circuit breaker pattern for external service calls including:
- HTTP API calls (third-party APIs)
- Cloud service calls (GCS, Pub/Sub)
- Slack/Email notifications
- Any external dependency

This module complements the existing circuit breaker implementations:
- CircuitBreakerMixin: For processor-level circuit breakers (Phase 3/4/5)
- SystemCircuitBreaker: For prediction system-level circuit breakers (Phase 5)
- RateLimitHandler: For rate-limit specific circuit breaking

This module provides a generic circuit breaker for any external service call.

Usage:
    from shared.utils.external_service_circuit_breaker import (
        ExternalServiceCircuitBreaker,
        get_service_circuit_breaker,
        call_with_circuit_breaker,
    )

    # Option 1: Use decorator
    @circuit_breaker_protected("slack_api")
    def send_slack_message(message):
        requests.post(SLACK_WEBHOOK, json={"text": message})

    # Option 2: Use context manager
    cb = get_service_circuit_breaker("gcs_upload")
    with cb:
        blob.upload_from_string(data)

    # Option 3: Use wrapper function
    result = call_with_circuit_breaker(
        "external_api",
        lambda: requests.get("https://api.example.com/data")
    )

Configuration:
    Environment variables (with defaults from shared/constants/resilience.py):
    - EXTERNAL_CB_THRESHOLD: Failures before opening (default: 5)
    - EXTERNAL_CB_TIMEOUT_SECONDS: Seconds to stay open (default: 300)
    - EXTERNAL_CB_HALF_OPEN_MAX_CALLS: Max calls in half-open state (default: 3)

Version: 1.0
Created: 2026-01-23
"""

import os
import time
import logging
import threading
import functools
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, TypeVar, Union
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# Import centralized resilience constants
try:
    from shared.constants.resilience import (
        CIRCUIT_BREAKER_THRESHOLD,
        CIRCUIT_BREAKER_TIMEOUT_MINUTES,
    )
    DEFAULT_THRESHOLD = CIRCUIT_BREAKER_THRESHOLD
    DEFAULT_TIMEOUT_SECONDS = CIRCUIT_BREAKER_TIMEOUT_MINUTES * 60
except ImportError:
    DEFAULT_THRESHOLD = 5
    DEFAULT_TIMEOUT_SECONDS = 300


# Type variable for generic return type
T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "CLOSED"      # Normal operation, requests pass through
    OPEN = "OPEN"          # Circuit tripped, requests fail fast
    HALF_OPEN = "HALF_OPEN"  # Testing if service recovered


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open and call is rejected."""

    def __init__(self, service_name: str, opened_at: datetime, timeout_remaining: float):
        self.service_name = service_name
        self.opened_at = opened_at
        self.timeout_remaining = timeout_remaining
        super().__init__(
            f"Circuit breaker OPEN for service '{service_name}'. "
            f"Opened at {opened_at.isoformat()}. "
            f"Timeout remaining: {timeout_remaining:.1f}s"
        )


@dataclass
class CircuitBreakerConfig:
    """Configuration for external service circuit breaker."""
    threshold: int = field(
        default_factory=lambda: int(os.getenv('EXTERNAL_CB_THRESHOLD', str(DEFAULT_THRESHOLD)))
    )
    timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv('EXTERNAL_CB_TIMEOUT_SECONDS', str(DEFAULT_TIMEOUT_SECONDS)))
    )
    half_open_max_calls: int = field(
        default_factory=lambda: int(os.getenv('EXTERNAL_CB_HALF_OPEN_MAX_CALLS', '3'))
    )
    # Exception types that should trigger circuit breaker
    # Default: connection errors, timeouts, server errors
    trigger_exceptions: tuple = field(default_factory=lambda: (
        ConnectionError,
        TimeoutError,
        OSError,
    ))


@dataclass
class CircuitBreakerState:
    """State tracking for a circuit breaker."""
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    consecutive_successes: int = 0  # For half-open recovery
    last_failure_time: Optional[float] = None
    last_failure_error: Optional[str] = None
    opened_at: Optional[float] = None
    half_open_calls: int = 0  # Track calls in half-open state
    total_failures: int = 0
    total_successes: int = 0


class ExternalServiceCircuitBreaker:
    """
    Circuit breaker for external service calls.

    Provides protection against cascading failures when external services
    are unavailable or degraded.

    States:
    - CLOSED: Normal operation. Calls pass through. Track failures.
    - OPEN: Service is failing. Calls fail fast without attempting.
    - HALF_OPEN: Testing recovery. Allow limited calls through.

    Transitions:
    - CLOSED -> OPEN: When consecutive_failures >= threshold
    - OPEN -> HALF_OPEN: After timeout_seconds have elapsed
    - HALF_OPEN -> CLOSED: After consecutive_successes >= half_open_max_calls
    - HALF_OPEN -> OPEN: On any failure during half-open

    Example:
        cb = ExternalServiceCircuitBreaker("slack_api")

        try:
            result = cb.call(lambda: requests.post(url, json=data))
        except CircuitBreakerError:
            # Service is down, use fallback
            logger.warning("Slack unavailable, using fallback")
    """

    def __init__(
        self,
        service_name: str,
        config: Optional[CircuitBreakerConfig] = None
    ):
        """
        Initialize circuit breaker for a service.

        Args:
            service_name: Identifier for the service (e.g., "slack_api", "gcs_upload")
            config: Optional configuration override
        """
        self.service_name = service_name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitBreakerState()
        self._lock = threading.Lock()

        logger.info(
            f"ExternalServiceCircuitBreaker initialized for '{service_name}': "
            f"threshold={self.config.threshold}, "
            f"timeout={self.config.timeout_seconds}s, "
            f"half_open_max={self.config.half_open_max_calls}"
        )

    @property
    def state(self) -> CircuitState:
        """Get current circuit state with auto-transition from OPEN to HALF_OPEN."""
        with self._lock:
            return self._get_state_with_transition()

    def _get_state_with_transition(self) -> CircuitState:
        """
        Get current state and handle automatic transitions.

        Must be called with lock held.
        """
        if self._state.state == CircuitState.OPEN:
            # Check if timeout has expired
            if self._state.opened_at:
                time_open = time.time() - self._state.opened_at
                if time_open >= self.config.timeout_seconds:
                    # Transition to half-open
                    logger.info(
                        f"Circuit breaker '{self.service_name}' transitioning "
                        f"OPEN -> HALF_OPEN after {time_open:.1f}s timeout"
                    )
                    self._state.state = CircuitState.HALF_OPEN
                    self._state.half_open_calls = 0
                    self._state.consecutive_successes = 0

        return self._state.state

    def is_available(self) -> bool:
        """
        Check if service is available (circuit not OPEN).

        Returns:
            True if calls can proceed, False if circuit is OPEN
        """
        return self.state != CircuitState.OPEN

    def call(self, func: Callable[[], T], *args, **kwargs) -> T:
        """
        Execute a function with circuit breaker protection.

        Args:
            func: Callable to execute
            *args, **kwargs: Arguments to pass to func

        Returns:
            Result of func()

        Raises:
            CircuitBreakerError: If circuit is OPEN
            Exception: Any exception raised by func (after recording failure)
        """
        current_state = self.state

        # If circuit is OPEN, fail fast
        if current_state == CircuitState.OPEN:
            timeout_remaining = self.config.timeout_seconds
            if self._state.opened_at:
                timeout_remaining = max(
                    0,
                    self.config.timeout_seconds - (time.time() - self._state.opened_at)
                )

            opened_at = datetime.fromtimestamp(
                self._state.opened_at or time.time(),
                tz=timezone.utc
            )

            raise CircuitBreakerError(
                self.service_name,
                opened_at,
                timeout_remaining
            )

        # Execute the call
        try:
            result = func(*args, **kwargs)
            self._record_success()
            return result
        except self.config.trigger_exceptions as e:
            self._record_failure(e)
            raise
        except Exception as e:
            # Check if this is a requests/httpx exception that indicates service failure
            error_type = type(e).__name__
            if any(pattern in error_type.lower() for pattern in ['timeout', 'connection', 'http']):
                self._record_failure(e)
            raise

    def _record_success(self):
        """Record a successful call."""
        with self._lock:
            self._state.total_successes += 1
            self._state.consecutive_failures = 0

            if self._state.state == CircuitState.HALF_OPEN:
                self._state.consecutive_successes += 1
                self._state.half_open_calls += 1

                if self._state.consecutive_successes >= self.config.half_open_max_calls:
                    # Recovery complete, close circuit
                    logger.info(
                        f"Circuit breaker '{self.service_name}' CLOSING after "
                        f"{self._state.consecutive_successes} consecutive successes"
                    )
                    self._state.state = CircuitState.CLOSED
                    self._state.opened_at = None
                    self._state.half_open_calls = 0

    def _record_failure(self, error: Exception):
        """Record a failed call."""
        with self._lock:
            self._state.total_failures += 1
            self._state.consecutive_failures += 1
            self._state.consecutive_successes = 0
            self._state.last_failure_time = time.time()
            self._state.last_failure_error = str(error)[:200]

            if self._state.state == CircuitState.HALF_OPEN:
                # Any failure in half-open immediately opens circuit
                logger.warning(
                    f"Circuit breaker '{self.service_name}' RE-OPENING after "
                    f"failure during half-open: {error}"
                )
                self._state.state = CircuitState.OPEN
                self._state.opened_at = time.time()

            elif self._state.state == CircuitState.CLOSED:
                if self._state.consecutive_failures >= self.config.threshold:
                    # Threshold reached, open circuit
                    logger.error(
                        f"Circuit breaker '{self.service_name}' OPENING after "
                        f"{self._state.consecutive_failures} consecutive failures. "
                        f"Last error: {error}"
                    )
                    self._state.state = CircuitState.OPEN
                    self._state.opened_at = time.time()
                else:
                    logger.warning(
                        f"Circuit breaker '{self.service_name}' failure "
                        f"{self._state.consecutive_failures}/{self.config.threshold}: {error}"
                    )

    def reset(self):
        """Manually reset circuit breaker to CLOSED state."""
        with self._lock:
            logger.info(f"Circuit breaker '{self.service_name}' manually reset")
            self._state = CircuitBreakerState()

    def get_status(self) -> Dict[str, Any]:
        """Get current circuit breaker status for monitoring."""
        with self._lock:
            state = self._get_state_with_transition()

            status = {
                'service_name': self.service_name,
                'state': state.value,
                'consecutive_failures': self._state.consecutive_failures,
                'consecutive_successes': self._state.consecutive_successes,
                'total_failures': self._state.total_failures,
                'total_successes': self._state.total_successes,
                'threshold': self.config.threshold,
                'timeout_seconds': self.config.timeout_seconds,
                'last_failure_error': self._state.last_failure_error,
            }

            if self._state.opened_at:
                status['opened_at'] = datetime.fromtimestamp(
                    self._state.opened_at, tz=timezone.utc
                ).isoformat()
                status['time_in_open'] = time.time() - self._state.opened_at
                status['timeout_remaining'] = max(
                    0,
                    self.config.timeout_seconds - (time.time() - self._state.opened_at)
                )

            return status

    def __enter__(self):
        """Context manager entry - check if available."""
        if not self.is_available():
            timeout_remaining = self.config.timeout_seconds
            if self._state.opened_at:
                timeout_remaining = max(
                    0,
                    self.config.timeout_seconds - (time.time() - self._state.opened_at)
                )

            opened_at = datetime.fromtimestamp(
                self._state.opened_at or time.time(),
                tz=timezone.utc
            )

            raise CircuitBreakerError(
                self.service_name,
                opened_at,
                timeout_remaining
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - record success or failure."""
        if exc_type is None:
            self._record_success()
        elif exc_type in self.config.trigger_exceptions:
            self._record_failure(exc_val)
        return False  # Don't suppress exceptions


# =============================================================================
# Global Registry for Service Circuit Breakers
# =============================================================================

_circuit_breaker_registry: Dict[str, ExternalServiceCircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_service_circuit_breaker(
    service_name: str,
    config: Optional[CircuitBreakerConfig] = None
) -> ExternalServiceCircuitBreaker:
    """
    Get or create a circuit breaker for a service.

    Uses singleton pattern to ensure one circuit breaker per service.

    Args:
        service_name: Identifier for the service
        config: Optional configuration (only used on first call)

    Returns:
        ExternalServiceCircuitBreaker instance for the service
    """
    if service_name in _circuit_breaker_registry:
        return _circuit_breaker_registry[service_name]

    with _registry_lock:
        # Double-check after acquiring lock
        if service_name in _circuit_breaker_registry:
            return _circuit_breaker_registry[service_name]

        cb = ExternalServiceCircuitBreaker(service_name, config)
        _circuit_breaker_registry[service_name] = cb
        return cb


def call_with_circuit_breaker(
    service_name: str,
    func: Callable[[], T],
    *args,
    **kwargs
) -> T:
    """
    Convenience function to call with circuit breaker protection.

    Args:
        service_name: Identifier for the service
        func: Callable to execute
        *args, **kwargs: Arguments to pass to func

    Returns:
        Result of func()

    Raises:
        CircuitBreakerError: If circuit is OPEN
        Exception: Any exception raised by func

    Example:
        result = call_with_circuit_breaker(
            "external_api",
            lambda: requests.get("https://api.example.com/data")
        )
    """
    cb = get_service_circuit_breaker(service_name)
    return cb.call(func, *args, **kwargs)


def circuit_breaker_protected(
    service_name: str,
    config: Optional[CircuitBreakerConfig] = None
) -> Callable:
    """
    Decorator to protect a function with circuit breaker.

    Args:
        service_name: Identifier for the service
        config: Optional configuration override

    Returns:
        Decorator function

    Example:
        @circuit_breaker_protected("slack_api")
        def send_slack_message(message):
            requests.post(SLACK_WEBHOOK, json={"text": message})
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            cb = get_service_circuit_breaker(service_name, config)
            return cb.call(lambda: func(*args, **kwargs))
        return wrapper
    return decorator


def get_all_circuit_breaker_status() -> Dict[str, Dict[str, Any]]:
    """
    Get status of all registered circuit breakers.

    Returns:
        Dict mapping service_name to status dict
    """
    with _registry_lock:
        return {
            name: cb.get_status()
            for name, cb in _circuit_breaker_registry.items()
        }


def reset_circuit_breaker(service_name: str) -> bool:
    """
    Reset a specific circuit breaker.

    Args:
        service_name: Service to reset

    Returns:
        True if reset, False if service not found
    """
    if service_name in _circuit_breaker_registry:
        _circuit_breaker_registry[service_name].reset()
        return True
    return False


def reset_all_circuit_breakers():
    """Reset all registered circuit breakers."""
    with _registry_lock:
        for cb in _circuit_breaker_registry.values():
            cb.reset()

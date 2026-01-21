"""
Circuit Breaker Pattern for Scraper Reliability

Prevents wasting resources on consistently failing scrapers by "opening the circuit"
after a threshold of failures. Once open, requests fail fast without attempting
the operation. After a timeout period, enters "half-open" state to test recovery.

States:
- CLOSED: Normal operation (all requests attempted)
- OPEN: Circuit breaker triggered (requests fail fast)
- HALF_OPEN: Testing if service recovered (limited requests)

Use Case:
- Scraper consistently returns HTTP 500 (5 failures in a row)
- Circuit opens → subsequent calls fail immediately for 5 minutes
- After 5 minutes → circuit half-opens, tries 3 test requests
- If tests succeed → circuit closes (normal operation)
- If tests fail → circuit re-opens for another 5 minutes

Benefits:
- Stops retry loops on permanently broken services
- Reduces API costs and wasted compute time
- Faster failures (no timeout waits)
- Automatic recovery testing

Reference:
- Martin Fowler: https://martinfowler.com/bliki/CircuitBreaker.html
- Config: shared/config/orchestration_config.py CIRCUIT_BREAKER_CONFIG
"""

import logging
import time
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Optional, Callable, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"          # Normal operation
    OPEN = "open"              # Blocking all requests
    HALF_OPEN = "half_open"    # Testing recovery


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and operation is blocked."""
    pass


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""
    max_failures: int = 5              # Failures before opening circuit
    timeout_seconds: int = 300         # Time to wait before testing recovery (5 min)
    half_open_attempts: int = 3        # Successful tests needed to close circuit
    failure_threshold_window: int = 60 # Time window for counting failures (seconds)


class CircuitBreaker:
    """
    Circuit breaker for preventing cascading failures.

    Tracks failure rates and blocks operations when a service is consistently
    failing. Automatically tests for recovery after a timeout period.

    Example:
        # Create circuit breaker for a scraper
        breaker = CircuitBreaker(
            name="oddsa_events",
            config=CircuitBreakerConfig(max_failures=5, timeout_seconds=300)
        )

        # Use circuit breaker
        try:
            result = breaker.call(scraper_function, *args, **kwargs)
        except CircuitBreakerOpenError:
            logger.info("Circuit breaker is open, skipping scraper")
            return ScraperExecution(status='skipped', error='Circuit breaker open')
    """

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        """
        Initialize circuit breaker.

        Args:
            name: Identifier for this circuit breaker (e.g., scraper name)
            config: Circuit breaker configuration (uses defaults if None)
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED

        # Failure tracking
        self.failure_count = 0
        self.failure_timestamps = []  # Track when failures occurred
        self.last_failure_time: Optional[float] = None

        # State transition tracking
        self.state_since: float = time.time()
        self.last_state_change: Optional[float] = None

        # Half-open state tracking
        self.half_open_successes = 0
        self.half_open_failures = 0

        logger.info(
            f"Initialized CircuitBreaker '{name}': "
            f"max_failures={self.config.max_failures}, "
            f"timeout={self.config.timeout_seconds}s, "
            f"half_open_attempts={self.config.half_open_attempts}"
        )

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Result from func(*args, **kwargs)

        Raises:
            CircuitBreakerOpenError: If circuit is open and blocking requests
            Exception: Any exception raised by func (after recording failure)
        """
        # Check if we should transition states
        self._check_state_transition()

        # If circuit is open, fail fast
        if self.state == CircuitState.OPEN:
            elapsed = time.time() - self.state_since
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self.name}' is OPEN "
                f"(failures={self.failure_count}, "
                f"elapsed={int(elapsed)}s/{self.config.timeout_seconds}s)"
            )

        # Attempt operation
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result

        except Exception as e:
            self._on_failure(e)
            raise

    def _check_state_transition(self):
        """Check if circuit breaker should transition to a different state."""
        current_time = time.time()
        elapsed = current_time - self.state_since

        if self.state == CircuitState.OPEN:
            # Check if timeout has elapsed → transition to HALF_OPEN
            if elapsed >= self.config.timeout_seconds:
                self._transition_to(CircuitState.HALF_OPEN)
                logger.info(
                    f"🔄 Circuit breaker '{self.name}' entering HALF_OPEN state "
                    f"after {int(elapsed)}s. Testing recovery..."
                )

    def _on_success(self):
        """Record successful operation."""
        if self.state == CircuitState.HALF_OPEN:
            # In half-open state, count successes
            self.half_open_successes += 1
            logger.info(
                f"✅ Half-open success {self.half_open_successes}/"
                f"{self.config.half_open_attempts} for '{self.name}'"
            )

            if self.half_open_successes >= self.config.half_open_attempts:
                # Enough successes → close circuit
                self._transition_to(CircuitState.CLOSED)
                self.failure_count = 0
                self.failure_timestamps = []
                logger.info(
                    f"🟢 Circuit breaker '{self.name}' CLOSED after successful recovery"
                )

        elif self.state == CircuitState.CLOSED:
            # Normal operation - reset failure tracking on success
            # Only reset if we had recent failures
            if self.failure_count > 0:
                logger.debug(
                    f"Success for '{self.name}', resetting failure count "
                    f"from {self.failure_count} to 0"
                )
                self.failure_count = 0
                self.failure_timestamps = []

    def _on_failure(self, exception: Exception):
        """Record failed operation."""
        current_time = time.time()
        self.last_failure_time = current_time
        self.failure_timestamps.append(current_time)

        # Clean up old failure timestamps outside the window
        cutoff_time = current_time - self.config.failure_threshold_window
        self.failure_timestamps = [
            ts for ts in self.failure_timestamps if ts >= cutoff_time
        ]

        if self.state == CircuitState.HALF_OPEN:
            # Failure in half-open → immediately re-open circuit
            self.half_open_failures += 1
            logger.warning(
                f"❌ Half-open test failed for '{self.name}': {exception}. "
                f"Re-opening circuit."
            )
            self._transition_to(CircuitState.OPEN)

        elif self.state == CircuitState.CLOSED:
            # Count failures in the time window
            recent_failures = len(self.failure_timestamps)
            self.failure_count = recent_failures

            logger.warning(
                f"⚠️  Failure {self.failure_count}/{self.config.max_failures} "
                f"for '{self.name}': {exception}"
            )

            # Check if we should open circuit
            if self.failure_count >= self.config.max_failures:
                self._transition_to(CircuitState.OPEN)
                logger.error(
                    f"🔴 Circuit breaker '{self.name}' OPENED after "
                    f"{self.failure_count} failures in "
                    f"{self.config.failure_threshold_window}s window"
                )

    def _transition_to(self, new_state: CircuitState):
        """Transition to a new state."""
        old_state = self.state
        self.state = new_state
        self.state_since = time.time()
        self.last_state_change = time.time()

        # Reset half-open counters when entering half-open state
        if new_state == CircuitState.HALF_OPEN:
            self.half_open_successes = 0
            self.half_open_failures = 0

        logger.info(
            f"Circuit breaker '{self.name}' transitioned: "
            f"{old_state.value} → {new_state.value}"
        )

    def get_state(self) -> Dict[str, Any]:
        """
        Get current circuit breaker state for monitoring.

        Returns:
            Dict with state information
        """
        elapsed = time.time() - self.state_since
        return {
            'name': self.name,
            'state': self.state.value,
            'failure_count': self.failure_count,
            'state_elapsed_seconds': int(elapsed),
            'half_open_successes': self.half_open_successes if self.state == CircuitState.HALF_OPEN else None,
            'last_failure_time': (
                datetime.fromtimestamp(self.last_failure_time).isoformat()
                if self.last_failure_time else None
            )
        }

    def reset(self):
        """
        Manually reset circuit breaker to CLOSED state.

        USE WITH CAUTION: Only call this if you know the underlying
        service has been fixed and you want to bypass the timeout.
        """
        logger.warning(f"⚠️  Manually resetting circuit breaker '{self.name}'")
        self._transition_to(CircuitState.CLOSED)
        self.failure_count = 0
        self.failure_timestamps = []
        self.half_open_successes = 0
        self.half_open_failures = 0


class CircuitBreakerManager:
    """
    Manages multiple circuit breakers (one per entity like scraper).

    Centralizes circuit breaker creation and lookup to ensure
    only one circuit breaker exists per entity.

    Example:
        manager = CircuitBreakerManager(config=CircuitBreakerConfig(...))

        # Get or create circuit breaker for a scraper
        breaker = manager.get_breaker("oddsa_events")

        # Use circuit breaker
        try:
            result = breaker.call(scraper_func)
        except CircuitBreakerOpenError:
            logger.info("Circuit open, skipping")
    """

    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        """
        Initialize circuit breaker manager.

        Args:
            config: Default configuration for all circuit breakers
        """
        self.config = config or CircuitBreakerConfig()
        self.breakers: Dict[str, CircuitBreaker] = {}
        logger.info(f"Initialized CircuitBreakerManager with config: {self.config}")

    def get_breaker(self, name: str) -> CircuitBreaker:
        """
        Get or create circuit breaker for a named entity.

        Args:
            name: Entity identifier (e.g., scraper name)

        Returns:
            CircuitBreaker instance
        """
        if name not in self.breakers:
            self.breakers[name] = CircuitBreaker(name, self.config)
            logger.debug(f"Created new circuit breaker for '{name}'")

        return self.breakers[name]

    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """
        Get state of all circuit breakers.

        Returns:
            Dict mapping entity name to circuit breaker state
        """
        return {
            name: breaker.get_state()
            for name, breaker in self.breakers.items()
        }

    def reset_all(self):
        """Reset all circuit breakers to CLOSED state."""
        logger.warning("⚠️  Resetting ALL circuit breakers")
        for breaker in self.breakers.values():
            breaker.reset()

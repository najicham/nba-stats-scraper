"""
Unit tests for Circuit Breaker Pattern

Tests state transitions, failure threshold, auto-reset after timeout,
and entity-level lockout functionality.

Usage:
    pytest tests/unit/utils/test_circuit_breaker.py -v
"""

import pytest
import time
from unittest.mock import Mock, patch
from shared.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerManager,
    CircuitBreakerConfig,
    CircuitState,
    CircuitBreakerOpenError
)


class TestCircuitBreakerConfig:
    """Test CircuitBreakerConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CircuitBreakerConfig()

        assert config.max_failures == 5
        assert config.timeout_seconds == 300
        assert config.half_open_attempts == 3
        assert config.failure_threshold_window == 60

    def test_custom_config(self):
        """Test custom configuration values."""
        config = CircuitBreakerConfig(
            max_failures=3,
            timeout_seconds=60,
            half_open_attempts=2,
            failure_threshold_window=30
        )

        assert config.max_failures == 3
        assert config.timeout_seconds == 60
        assert config.half_open_attempts == 2
        assert config.failure_threshold_window == 30


class TestCircuitBreakerBasics:
    """Test basic circuit breaker functionality."""

    def test_circuit_breaker_initialization(self):
        """Test circuit breaker is initialized in CLOSED state."""
        breaker = CircuitBreaker(name="test_breaker")

        assert breaker.name == "test_breaker"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.half_open_successes == 0

    def test_circuit_breaker_with_custom_config(self):
        """Test circuit breaker with custom configuration."""
        config = CircuitBreakerConfig(max_failures=3)
        breaker = CircuitBreaker(name="test_breaker", config=config)

        assert breaker.config.max_failures == 3

    def test_successful_call(self):
        """Test successful function call through circuit breaker."""
        breaker = CircuitBreaker(name="test_breaker")

        def successful_function():
            return "success"

        result = breaker.call(successful_function)

        assert result == "success"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_failed_call_records_failure(self):
        """Test that failed call records failure."""
        config = CircuitBreakerConfig(max_failures=3)
        breaker = CircuitBreaker(name="test_breaker", config=config)

        def failing_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            breaker.call(failing_function)

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 1

    def test_get_state(self):
        """Test getting circuit breaker state."""
        breaker = CircuitBreaker(name="test_breaker")
        state = breaker.get_state()

        assert state["name"] == "test_breaker"
        assert state["state"] == CircuitState.CLOSED.value
        assert state["failure_count"] == 0
        assert "state_elapsed_seconds" in state


class TestCircuitBreakerStateTransitions:
    """Test circuit breaker state transitions."""

    def test_closed_to_open_after_max_failures(self):
        """Test circuit opens after max failures reached."""
        config = CircuitBreakerConfig(max_failures=3, failure_threshold_window=60)
        breaker = CircuitBreaker(name="test_breaker", config=config)

        def failing_function():
            raise ValueError("Test error")

        # Fail 3 times (max_failures)
        for i in range(3):
            with pytest.raises(ValueError):
                breaker.call(failing_function)

        # Circuit should now be OPEN
        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 3

    def test_open_circuit_fails_fast(self):
        """Test that open circuit fails immediately without calling function."""
        config = CircuitBreakerConfig(max_failures=2)
        breaker = CircuitBreaker(name="test_breaker", config=config)

        call_count = {"count": 0}

        def failing_function():
            call_count["count"] += 1
            raise ValueError("Test error")

        # Fail twice to open circuit
        for i in range(2):
            with pytest.raises(ValueError):
                breaker.call(failing_function)

        assert breaker.state == CircuitState.OPEN
        assert call_count["count"] == 2

        # Next call should fail fast without calling function
        with pytest.raises(CircuitBreakerOpenError):
            breaker.call(failing_function)

        # Function should not have been called
        assert call_count["count"] == 2

    def test_open_to_half_open_after_timeout(self):
        """Test circuit transitions to HALF_OPEN after timeout."""
        config = CircuitBreakerConfig(max_failures=2, timeout_seconds=1)
        breaker = CircuitBreaker(name="test_breaker", config=config)

        def failing_function():
            raise ValueError("Test error")

        # Open the circuit
        for i in range(2):
            with pytest.raises(ValueError):
                breaker.call(failing_function)

        assert breaker.state == CircuitState.OPEN

        # Wait for timeout
        time.sleep(1.1)

        # Next call should check state and transition to HALF_OPEN
        # We'll use a successful function to test the transition
        def successful_function():
            return "success"

        result = breaker.call(successful_function)

        assert result == "success"
        assert breaker.state == CircuitState.HALF_OPEN

    def test_half_open_to_closed_after_successful_attempts(self):
        """Test circuit closes after successful attempts in HALF_OPEN state."""
        config = CircuitBreakerConfig(
            max_failures=2,
            timeout_seconds=1,
            half_open_attempts=3
        )
        breaker = CircuitBreaker(name="test_breaker", config=config)

        def failing_function():
            raise ValueError("Test error")

        def successful_function():
            return "success"

        # Open the circuit
        for i in range(2):
            with pytest.raises(ValueError):
                breaker.call(failing_function)

        assert breaker.state == CircuitState.OPEN

        # Wait for timeout and transition to HALF_OPEN
        time.sleep(1.1)

        # Make successful calls (half_open_attempts)
        for i in range(3):
            result = breaker.call(successful_function)
            assert result == "success"

        # Circuit should now be CLOSED
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_half_open_to_open_on_failure(self):
        """Test circuit re-opens if failure occurs in HALF_OPEN state."""
        config = CircuitBreakerConfig(
            max_failures=2,
            timeout_seconds=1,
            half_open_attempts=3
        )
        breaker = CircuitBreaker(name="test_breaker", config=config)

        def failing_function():
            raise ValueError("Test error")

        def successful_function():
            return "success"

        # Open the circuit
        for i in range(2):
            with pytest.raises(ValueError):
                breaker.call(failing_function)

        assert breaker.state == CircuitState.OPEN

        # Wait for timeout and make one successful call
        time.sleep(1.1)
        result = breaker.call(successful_function)
        assert breaker.state == CircuitState.HALF_OPEN

        # Fail in half-open state
        with pytest.raises(ValueError):
            breaker.call(failing_function)

        # Circuit should re-open
        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerFailureWindow:
    """Test failure counting within time window."""

    def test_failures_outside_window_not_counted(self):
        """Test that failures outside the window don't count toward threshold."""
        config = CircuitBreakerConfig(
            max_failures=3,
            failure_threshold_window=2  # 2 second window
        )
        breaker = CircuitBreaker(name="test_breaker", config=config)

        def failing_function():
            raise ValueError("Test error")

        # Fail once
        with pytest.raises(ValueError):
            breaker.call(failing_function)

        assert breaker.failure_count == 1

        # Wait for window to expire
        time.sleep(2.1)

        # Fail again - should reset count
        with pytest.raises(ValueError):
            breaker.call(failing_function)

        # Should only count recent failure
        assert breaker.failure_count == 1
        assert breaker.state == CircuitState.CLOSED

    def test_failures_within_window_counted(self):
        """Test that failures within the window count toward threshold."""
        config = CircuitBreakerConfig(
            max_failures=3,
            failure_threshold_window=10  # 10 second window
        )
        breaker = CircuitBreaker(name="test_breaker", config=config)

        def failing_function():
            raise ValueError("Test error")

        # Fail 3 times quickly
        for i in range(3):
            with pytest.raises(ValueError):
                breaker.call(failing_function)
            time.sleep(0.1)  # Small delay but within window

        # Should have opened circuit
        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 3


class TestCircuitBreakerReset:
    """Test manual reset functionality."""

    def test_manual_reset(self):
        """Test manually resetting circuit breaker."""
        config = CircuitBreakerConfig(max_failures=2)
        breaker = CircuitBreaker(name="test_breaker", config=config)

        def failing_function():
            raise ValueError("Test error")

        # Open the circuit
        for i in range(2):
            with pytest.raises(ValueError):
                breaker.call(failing_function)

        assert breaker.state == CircuitState.OPEN

        # Manually reset
        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.half_open_successes == 0

    def test_reset_clears_failure_timestamps(self):
        """Test that reset clears failure timestamps."""
        breaker = CircuitBreaker(name="test_breaker")

        def failing_function():
            raise ValueError("Test error")

        # Record a failure
        with pytest.raises(ValueError):
            breaker.call(failing_function)

        assert len(breaker.failure_timestamps) == 1

        # Reset
        breaker.reset()

        assert len(breaker.failure_timestamps) == 0


class TestCircuitBreakerSuccessReset:
    """Test that successes reset failure count."""

    def test_success_resets_failure_count_in_closed_state(self):
        """Test that a success resets failure count when in CLOSED state."""
        config = CircuitBreakerConfig(max_failures=3)
        breaker = CircuitBreaker(name="test_breaker", config=config)

        def failing_function():
            raise ValueError("Test error")

        def successful_function():
            return "success"

        # Fail twice
        for i in range(2):
            with pytest.raises(ValueError):
                breaker.call(failing_function)

        assert breaker.failure_count == 2
        assert breaker.state == CircuitState.CLOSED

        # Succeed once
        result = breaker.call(successful_function)
        assert result == "success"

        # Failure count should be reset
        assert breaker.failure_count == 0


class TestCircuitBreakerManager:
    """Test CircuitBreakerManager for managing multiple circuit breakers."""

    def test_manager_initialization(self):
        """Test circuit breaker manager initialization."""
        config = CircuitBreakerConfig(max_failures=3)
        manager = CircuitBreakerManager(config=config)

        assert len(manager.breakers) == 0
        assert manager.config.max_failures == 3

    def test_get_breaker_creates_new_breaker(self):
        """Test that get_breaker creates a new breaker if it doesn't exist."""
        manager = CircuitBreakerManager()

        breaker = manager.get_breaker("scraper1")

        assert breaker.name == "scraper1"
        assert len(manager.breakers) == 1

    def test_get_breaker_returns_existing_breaker(self):
        """Test that get_breaker returns existing breaker."""
        manager = CircuitBreakerManager()

        breaker1 = manager.get_breaker("scraper1")
        breaker2 = manager.get_breaker("scraper1")

        assert breaker1 is breaker2
        assert len(manager.breakers) == 1

    def test_get_breaker_creates_separate_breakers_per_entity(self):
        """Test that each entity gets its own circuit breaker."""
        manager = CircuitBreakerManager()

        breaker1 = manager.get_breaker("scraper1")
        breaker2 = manager.get_breaker("scraper2")

        assert breaker1 is not breaker2
        assert breaker1.name == "scraper1"
        assert breaker2.name == "scraper2"
        assert len(manager.breakers) == 2

    def test_get_all_states(self):
        """Test getting states of all circuit breakers."""
        manager = CircuitBreakerManager()

        breaker1 = manager.get_breaker("scraper1")
        breaker2 = manager.get_breaker("scraper2")

        states = manager.get_all_states()

        assert len(states) == 2
        assert "scraper1" in states
        assert "scraper2" in states
        assert states["scraper1"]["state"] == CircuitState.CLOSED.value
        assert states["scraper2"]["state"] == CircuitState.CLOSED.value

    def test_reset_all(self):
        """Test resetting all circuit breakers."""
        config = CircuitBreakerConfig(max_failures=1)
        manager = CircuitBreakerManager(config=config)

        def failing_function():
            raise ValueError("Test error")

        # Open both breakers
        breaker1 = manager.get_breaker("scraper1")
        breaker2 = manager.get_breaker("scraper2")

        with pytest.raises(ValueError):
            breaker1.call(failing_function)
        with pytest.raises(ValueError):
            breaker2.call(failing_function)

        assert breaker1.state == CircuitState.OPEN
        assert breaker2.state == CircuitState.OPEN

        # Reset all
        manager.reset_all()

        assert breaker1.state == CircuitState.CLOSED
        assert breaker2.state == CircuitState.CLOSED


class TestCircuitBreakerEntityLevelLockout:
    """Test entity-level circuit breaker isolation."""

    def test_entities_have_independent_circuit_breakers(self):
        """Test that failures in one entity don't affect another."""
        manager = CircuitBreakerManager(
            config=CircuitBreakerConfig(max_failures=2)
        )

        def failing_function():
            raise ValueError("Test error")

        def successful_function():
            return "success"

        breaker1 = manager.get_breaker("scraper1")
        breaker2 = manager.get_breaker("scraper2")

        # Open circuit for scraper1
        for i in range(2):
            with pytest.raises(ValueError):
                breaker1.call(failing_function)

        assert breaker1.state == CircuitState.OPEN

        # scraper2 should still work
        result = breaker2.call(successful_function)
        assert result == "success"
        assert breaker2.state == CircuitState.CLOSED

        # scraper1 should fail fast
        with pytest.raises(CircuitBreakerOpenError):
            breaker1.call(successful_function)


class TestCircuitBreakerEdgeCases:
    """Test edge cases and error conditions."""

    def test_call_with_args_and_kwargs(self):
        """Test calling function with arguments and keyword arguments."""
        breaker = CircuitBreaker(name="test_breaker")

        def function_with_args(a, b, c=None):
            return f"{a}-{b}-{c}"

        result = breaker.call(function_with_args, "arg1", "arg2", c="kwarg3")

        assert result == "arg1-arg2-kwarg3"

    def test_exception_propagation(self):
        """Test that exceptions are properly propagated."""
        breaker = CircuitBreaker(name="test_breaker")

        class CustomError(Exception):
            pass

        def function_with_custom_error():
            raise CustomError("Custom error message")

        with pytest.raises(CustomError, match="Custom error message"):
            breaker.call(function_with_custom_error)

    def test_zero_max_failures(self):
        """Test circuit breaker with zero max failures (always open)."""
        config = CircuitBreakerConfig(max_failures=0)
        breaker = CircuitBreaker(name="test_breaker", config=config)

        def failing_function():
            raise ValueError("Test error")

        # First failure should immediately open circuit
        with pytest.raises(ValueError):
            breaker.call(failing_function)

        assert breaker.state == CircuitState.OPEN

    def test_last_failure_time_recorded(self):
        """Test that last failure time is recorded."""
        breaker = CircuitBreaker(name="test_breaker")

        def failing_function():
            raise ValueError("Test error")

        assert breaker.last_failure_time is None

        with pytest.raises(ValueError):
            breaker.call(failing_function)

        assert breaker.last_failure_time is not None
        assert isinstance(breaker.last_failure_time, float)

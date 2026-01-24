"""
Unit Tests for ExternalServiceCircuitBreaker

Tests the circuit breaker pattern for external service calls.

Usage:
    pytest tests/unit/shared/utils/test_external_service_circuit_breaker.py -v
"""

import time
import pytest
import threading
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

from shared.utils.external_service_circuit_breaker import (
    ExternalServiceCircuitBreaker,
    CircuitBreakerError,
    CircuitState,
    CircuitBreakerConfig,
    get_service_circuit_breaker,
    call_with_circuit_breaker,
    circuit_breaker_protected,
    get_all_circuit_breaker_status,
    reset_circuit_breaker,
    reset_all_circuit_breakers,
    _circuit_breaker_registry,
)


class TestCircuitBreakerStates:
    """Test circuit breaker state transitions."""

    def setup_method(self):
        """Reset registry before each test."""
        _circuit_breaker_registry.clear()

    def test_initial_state_is_closed(self):
        """Circuit starts in CLOSED state."""
        cb = ExternalServiceCircuitBreaker("test_service")
        assert cb.state == CircuitState.CLOSED

    def test_is_available_when_closed(self):
        """Service is available when circuit is CLOSED."""
        cb = ExternalServiceCircuitBreaker("test_service")
        assert cb.is_available() is True

    def test_transitions_to_open_after_threshold_failures(self):
        """Circuit opens after consecutive failures reach threshold."""
        config = CircuitBreakerConfig(threshold=3, timeout_seconds=60)
        cb = ExternalServiceCircuitBreaker("test_service", config)

        # Simulate 3 failures
        for _ in range(3):
            cb._record_failure(ConnectionError("Connection refused"))

        assert cb.state == CircuitState.OPEN
        assert cb.is_available() is False

    def test_not_available_when_open(self):
        """Service is not available when circuit is OPEN."""
        config = CircuitBreakerConfig(threshold=1, timeout_seconds=60)
        cb = ExternalServiceCircuitBreaker("test_service", config)

        cb._record_failure(ConnectionError("Connection refused"))

        assert cb.state == CircuitState.OPEN
        assert cb.is_available() is False

    def test_transitions_to_half_open_after_timeout(self):
        """Circuit transitions to HALF_OPEN after timeout expires."""
        config = CircuitBreakerConfig(threshold=1, timeout_seconds=0.1)
        cb = ExternalServiceCircuitBreaker("test_service", config)

        # Open circuit
        cb._record_failure(ConnectionError("Connection refused"))
        assert cb.state == CircuitState.OPEN

        # Wait for timeout
        time.sleep(0.15)

        # Check state (triggers auto-transition)
        assert cb.state == CircuitState.HALF_OPEN

    def test_closes_from_half_open_after_successes(self):
        """Circuit closes from HALF_OPEN after consecutive successes."""
        config = CircuitBreakerConfig(
            threshold=1,
            timeout_seconds=0.1,
            half_open_max_calls=2
        )
        cb = ExternalServiceCircuitBreaker("test_service", config)

        # Open circuit
        cb._record_failure(ConnectionError("Connection refused"))
        time.sleep(0.15)

        # Should be half-open now
        assert cb.state == CircuitState.HALF_OPEN

        # Record successes
        cb._record_success()
        assert cb.state == CircuitState.HALF_OPEN  # Not yet closed

        cb._record_success()
        assert cb.state == CircuitState.CLOSED  # Now closed

    def test_reopens_from_half_open_on_failure(self):
        """Circuit re-opens from HALF_OPEN on any failure."""
        config = CircuitBreakerConfig(threshold=1, timeout_seconds=0.1)
        cb = ExternalServiceCircuitBreaker("test_service", config)

        # Open circuit
        cb._record_failure(ConnectionError("Connection refused"))
        time.sleep(0.15)

        # Should be half-open now
        assert cb.state == CircuitState.HALF_OPEN

        # Record failure
        cb._record_failure(ConnectionError("Still failing"))

        # Should be open again
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        """Success resets consecutive failure count."""
        config = CircuitBreakerConfig(threshold=3)
        cb = ExternalServiceCircuitBreaker("test_service", config)

        # 2 failures
        cb._record_failure(ConnectionError("Fail 1"))
        cb._record_failure(ConnectionError("Fail 2"))
        assert cb._state.consecutive_failures == 2

        # Success resets
        cb._record_success()
        assert cb._state.consecutive_failures == 0

        # Another failure starts fresh
        cb._record_failure(ConnectionError("Fail 3"))
        assert cb._state.consecutive_failures == 1
        assert cb.state == CircuitState.CLOSED


class TestCallMethod:
    """Test the call() method that wraps function execution."""

    def setup_method(self):
        """Reset registry before each test."""
        _circuit_breaker_registry.clear()

    def test_call_succeeds_when_closed(self):
        """Call succeeds when circuit is CLOSED."""
        cb = ExternalServiceCircuitBreaker("test_service")

        result = cb.call(lambda: "success")
        assert result == "success"

    def test_call_raises_circuit_breaker_error_when_open(self):
        """Call raises CircuitBreakerError when circuit is OPEN."""
        config = CircuitBreakerConfig(threshold=1, timeout_seconds=60)
        cb = ExternalServiceCircuitBreaker("test_service", config)

        # Open circuit
        cb._record_failure(ConnectionError("Connection refused"))

        with pytest.raises(CircuitBreakerError) as exc_info:
            cb.call(lambda: "should not execute")

        assert exc_info.value.service_name == "test_service"
        assert exc_info.value.timeout_remaining > 0

    def test_call_records_success_on_function_success(self):
        """Successful function call records success."""
        cb = ExternalServiceCircuitBreaker("test_service")

        cb.call(lambda: "success")

        assert cb._state.total_successes == 1
        assert cb._state.consecutive_failures == 0

    def test_call_records_failure_on_trigger_exception(self):
        """Function raising trigger exception records failure."""
        config = CircuitBreakerConfig(threshold=5)
        cb = ExternalServiceCircuitBreaker("test_service", config)

        def failing_func():
            raise ConnectionError("Connection refused")

        with pytest.raises(ConnectionError):
            cb.call(failing_func)

        assert cb._state.consecutive_failures == 1
        assert cb._state.total_failures == 1


class TestContextManager:
    """Test context manager usage."""

    def setup_method(self):
        """Reset registry before each test."""
        _circuit_breaker_registry.clear()

    def test_context_manager_success(self):
        """Context manager records success on clean exit."""
        cb = ExternalServiceCircuitBreaker("test_service")

        with cb:
            pass  # No exception

        assert cb._state.total_successes == 1

    def test_context_manager_raises_when_open(self):
        """Context manager raises CircuitBreakerError when OPEN."""
        config = CircuitBreakerConfig(threshold=1)
        cb = ExternalServiceCircuitBreaker("test_service", config)
        cb._record_failure(ConnectionError("fail"))

        with pytest.raises(CircuitBreakerError):
            with cb:
                pass

    def test_context_manager_records_failure_on_exception(self):
        """Context manager records failure on exception."""
        config = CircuitBreakerConfig(threshold=5)
        cb = ExternalServiceCircuitBreaker("test_service", config)

        try:
            with cb:
                raise ConnectionError("Connection failed")
        except ConnectionError:
            pass

        assert cb._state.consecutive_failures == 1


class TestRegistry:
    """Test global circuit breaker registry."""

    def setup_method(self):
        """Reset registry before each test."""
        _circuit_breaker_registry.clear()

    def test_get_service_creates_new_circuit_breaker(self):
        """get_service_circuit_breaker creates new CB for unknown service."""
        cb = get_service_circuit_breaker("new_service")
        assert cb.service_name == "new_service"
        assert "new_service" in _circuit_breaker_registry

    def test_get_service_returns_same_instance(self):
        """get_service_circuit_breaker returns same instance for same service."""
        cb1 = get_service_circuit_breaker("test_service")
        cb2 = get_service_circuit_breaker("test_service")
        assert cb1 is cb2

    def test_get_all_status(self):
        """get_all_circuit_breaker_status returns status for all registered CBs."""
        get_service_circuit_breaker("service_a")
        get_service_circuit_breaker("service_b")

        status = get_all_circuit_breaker_status()

        assert "service_a" in status
        assert "service_b" in status
        assert status["service_a"]["state"] == "CLOSED"

    def test_reset_circuit_breaker(self):
        """reset_circuit_breaker resets specific CB."""
        cb = get_service_circuit_breaker("test_service")
        cb._record_failure(ConnectionError("fail"))
        cb._record_failure(ConnectionError("fail"))

        assert cb._state.consecutive_failures == 2

        result = reset_circuit_breaker("test_service")

        assert result is True
        assert cb._state.consecutive_failures == 0

    def test_reset_unknown_circuit_breaker(self):
        """reset_circuit_breaker returns False for unknown service."""
        result = reset_circuit_breaker("unknown_service")
        assert result is False

    def test_reset_all_circuit_breakers(self):
        """reset_all_circuit_breakers resets all registered CBs."""
        cb1 = get_service_circuit_breaker("service_a")
        cb2 = get_service_circuit_breaker("service_b")

        cb1._record_failure(ConnectionError("fail"))
        cb2._record_failure(ConnectionError("fail"))

        reset_all_circuit_breakers()

        assert cb1._state.consecutive_failures == 0
        assert cb2._state.consecutive_failures == 0


class TestDecorator:
    """Test circuit_breaker_protected decorator."""

    def setup_method(self):
        """Reset registry before each test."""
        _circuit_breaker_registry.clear()

    def test_decorator_protects_function(self):
        """Decorator adds circuit breaker protection."""

        @circuit_breaker_protected("decorated_service")
        def my_function():
            return "success"

        result = my_function()
        assert result == "success"
        assert "decorated_service" in _circuit_breaker_registry

    def test_decorator_fails_fast_when_open(self):
        """Decorated function fails fast when circuit is open."""
        config = CircuitBreakerConfig(threshold=1)

        @circuit_breaker_protected("failing_service", config)
        def my_function():
            raise ConnectionError("fail")

        # First call fails and opens circuit
        with pytest.raises(ConnectionError):
            my_function()

        # Second call fails fast
        with pytest.raises(CircuitBreakerError):
            my_function()


class TestConvenienceFunction:
    """Test call_with_circuit_breaker convenience function."""

    def setup_method(self):
        """Reset registry before each test."""
        _circuit_breaker_registry.clear()

    def test_call_with_circuit_breaker_success(self):
        """call_with_circuit_breaker returns function result."""
        result = call_with_circuit_breaker("test_service", lambda: 42)
        assert result == 42

    def test_call_with_circuit_breaker_uses_registry(self):
        """call_with_circuit_breaker uses global registry."""
        call_with_circuit_breaker("test_service", lambda: None)
        assert "test_service" in _circuit_breaker_registry


class TestThreadSafety:
    """Test thread safety of circuit breaker."""

    def setup_method(self):
        """Reset registry before each test."""
        _circuit_breaker_registry.clear()

    def test_concurrent_registry_access(self):
        """Multiple threads can safely access registry."""
        results = []
        errors = []

        def get_cb(name):
            try:
                cb = get_service_circuit_breaker(name)
                results.append(cb)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=get_cb, args=(f"service_{i % 3}",))
            for i in range(30)
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 30
        # Should have 3 unique services
        assert len(_circuit_breaker_registry) == 3

    def test_concurrent_state_updates(self):
        """Multiple threads can safely update circuit state."""
        cb = ExternalServiceCircuitBreaker("concurrent_test")
        errors = []

        def record_success():
            try:
                for _ in range(100):
                    cb._record_success()
            except Exception as e:
                errors.append(e)

        def record_failure():
            try:
                for _ in range(100):
                    cb._record_failure(ConnectionError("test"))
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=record_success),
            threading.Thread(target=record_failure),
            threading.Thread(target=record_success),
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0


class TestGetStatus:
    """Test get_status method."""

    def setup_method(self):
        """Reset registry before each test."""
        _circuit_breaker_registry.clear()

    def test_status_includes_service_name(self):
        """Status includes service name."""
        cb = ExternalServiceCircuitBreaker("status_test")
        status = cb.get_status()
        assert status["service_name"] == "status_test"

    def test_status_includes_state(self):
        """Status includes current state."""
        cb = ExternalServiceCircuitBreaker("status_test")
        status = cb.get_status()
        assert status["state"] == "CLOSED"

    def test_status_includes_counters(self):
        """Status includes failure and success counters."""
        cb = ExternalServiceCircuitBreaker("status_test")
        cb._record_success()
        cb._record_failure(ConnectionError("fail"))

        status = cb.get_status()

        assert status["total_successes"] == 1
        assert status["total_failures"] == 1
        assert status["consecutive_failures"] == 1

    def test_status_includes_timeout_when_open(self):
        """Status includes timeout info when circuit is OPEN."""
        config = CircuitBreakerConfig(threshold=1, timeout_seconds=60)
        cb = ExternalServiceCircuitBreaker("status_test", config)
        cb._record_failure(ConnectionError("fail"))

        status = cb.get_status()

        assert "opened_at" in status
        assert "time_in_open" in status
        assert "timeout_remaining" in status
        assert status["timeout_remaining"] > 0


class TestManualReset:
    """Test manual reset functionality."""

    def setup_method(self):
        """Reset registry before each test."""
        _circuit_breaker_registry.clear()

    def test_reset_clears_all_state(self):
        """reset() clears all circuit state."""
        config = CircuitBreakerConfig(threshold=1)
        cb = ExternalServiceCircuitBreaker("reset_test", config)

        # Open circuit
        cb._record_failure(ConnectionError("fail"))
        assert cb.state == CircuitState.OPEN

        # Reset
        cb.reset()

        assert cb.state == CircuitState.CLOSED
        assert cb._state.consecutive_failures == 0
        assert cb._state.total_failures == 0
        assert cb._state.total_successes == 0

"""
Unit tests for RateLimitHandler

Tests the centralized rate limiting logic including:
- Retry-After header parsing (seconds and HTTP-date formats)
- Exponential backoff calculation with jitter
- Circuit breaker state management
- should_retry() decision logic
- Metrics collection
"""

import pytest
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock

from shared.utils.rate_limit_handler import (
    RateLimitHandler,
    RateLimitConfig,
    CircuitBreakerState,
    get_rate_limit_handler,
    reset_rate_limit_handler
)


class MockResponse:
    """Mock HTTP response for testing"""
    def __init__(self, status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class TestRateLimitHandler:
    """Test RateLimitHandler functionality"""

    def setup_method(self):
        """Reset handler before each test"""
        reset_rate_limit_handler()

    def teardown_method(self):
        """Reset handler after each test"""
        reset_rate_limit_handler()

    # ========== Retry-After Header Parsing Tests ==========

    def test_parse_retry_after_seconds(self):
        """Test parsing Retry-After header as seconds"""
        handler = RateLimitHandler()

        # Test with integer seconds
        response = MockResponse(headers={'Retry-After': '120'})
        wait_time = handler.parse_retry_after(response)

        assert wait_time == 120.0

    def test_parse_retry_after_seconds_string(self):
        """Test parsing Retry-After header as string seconds"""
        handler = RateLimitHandler()

        # Test with string seconds
        response = MockResponse(headers={'Retry-After': '60'})
        wait_time = handler.parse_retry_after(response)

        assert wait_time == 60.0

    def test_parse_retry_after_http_date(self):
        """Test parsing Retry-After header as HTTP-date"""
        handler = RateLimitHandler()

        # Create a time 2 minutes in the future
        future_time = datetime.now(timezone.utc) + timedelta(minutes=2)
        http_date = future_time.strftime('%a, %d %b %Y %H:%M:%S GMT')

        response = MockResponse(headers={'Retry-After': http_date})
        wait_time = handler.parse_retry_after(response)

        # Should be approximately 120 seconds (allow some variance for test execution time)
        assert wait_time is not None
        assert 115 <= wait_time <= 125

    def test_parse_retry_after_http_date_past(self):
        """Test parsing Retry-After header with past HTTP-date"""
        handler = RateLimitHandler()

        # Create a time in the past
        past_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        http_date = past_time.strftime('%a, %d %b %Y %H:%M:%S GMT')

        response = MockResponse(headers={'Retry-After': http_date})
        wait_time = handler.parse_retry_after(response)

        # Should return 0 or small positive value, not negative
        assert wait_time is not None
        assert wait_time >= 0

    def test_parse_retry_after_missing(self):
        """Test handling missing Retry-After header"""
        handler = RateLimitHandler()

        response = MockResponse(headers={})
        wait_time = handler.parse_retry_after(response)

        assert wait_time is None

    def test_parse_retry_after_invalid(self):
        """Test handling invalid Retry-After header"""
        handler = RateLimitHandler()

        response = MockResponse(headers={'Retry-After': 'invalid-value'})
        wait_time = handler.parse_retry_after(response)

        # Should return None for invalid format
        assert wait_time is None

    def test_parse_retry_after_case_insensitive(self):
        """Test Retry-After header is case-insensitive"""
        handler = RateLimitHandler()

        # Test lowercase
        response = MockResponse(headers={'retry-after': '30'})
        wait_time = handler.parse_retry_after(response)

        assert wait_time == 30.0

    # ========== Backoff Calculation Tests ==========

    def test_calculate_backoff_exponential(self):
        """Test exponential backoff calculation"""
        handler = RateLimitHandler()

        backoff0 = handler.calculate_backoff(0)
        backoff1 = handler.calculate_backoff(1)
        backoff2 = handler.calculate_backoff(2)
        backoff3 = handler.calculate_backoff(3)

        # Should increase exponentially (with jitter variance)
        # Attempt 0: base_backoff * (2^0) = 2.0
        # Attempt 1: base_backoff * (2^1) = 4.0
        # Attempt 2: base_backoff * (2^2) = 8.0
        # Attempt 3: base_backoff * (2^3) = 16.0
        # With jitter (±50%), expect these ranges
        assert 1.0 <= backoff0 <= 3.0
        assert 2.0 <= backoff1 <= 6.0
        assert 4.0 <= backoff2 <= 12.0
        assert 8.0 <= backoff3 <= 24.0

    def test_calculate_backoff_with_retry_after(self):
        """Test backoff respects Retry-After"""
        handler = RateLimitHandler()

        backoff = handler.calculate_backoff(0, retry_after=60.0)

        # Should be close to 60 (with jitter ±10%)
        assert 54.0 <= backoff <= 66.0

    def test_calculate_backoff_retry_after_overrides_exponential(self):
        """Test Retry-After overrides exponential backoff"""
        handler = RateLimitHandler()

        # High attempt would normally give large backoff
        backoff = handler.calculate_backoff(10, retry_after=5.0)

        # Should use Retry-After instead of exponential
        assert 4.5 <= backoff <= 5.5

    def test_calculate_backoff_max_cap(self):
        """Test backoff respects max_backoff"""
        config = RateLimitConfig(max_backoff=10.0)
        handler = RateLimitHandler(config)

        # Very high attempt should still cap at max_backoff
        backoff = handler.calculate_backoff(100)

        assert backoff <= 10.0

    def test_calculate_backoff_custom_base(self):
        """Test backoff with custom base_backoff"""
        config = RateLimitConfig(base_backoff=5.0)
        handler = RateLimitHandler(config)

        backoff0 = handler.calculate_backoff(0)

        # Attempt 0: base_backoff * (2^0) = 5.0 with jitter (±50%)
        assert 2.5 <= backoff0 <= 7.5

    # ========== Circuit Breaker Tests ==========

    def test_circuit_breaker_opens(self):
        """Test circuit breaker opens after threshold"""
        config = RateLimitConfig(circuit_breaker_threshold=3)
        handler = RateLimitHandler(config)

        domain = "api.test.com"
        response = MockResponse(status_code=429, headers={'Retry-After': '60'})

        # Should not be open initially
        assert handler.is_circuit_open(domain) is False

        # Record 2 failures - should not open yet
        handler.record_rate_limit(domain, response)
        handler.record_rate_limit(domain, response)
        assert handler.is_circuit_open(domain) is False

        # Record 3rd failure - should open
        handler.record_rate_limit(domain, response)
        assert handler.is_circuit_open(domain) is True

    def test_circuit_breaker_disabled(self):
        """Test circuit breaker can be disabled"""
        config = RateLimitConfig(
            circuit_breaker_threshold=1,
            circuit_breaker_enabled=False
        )
        handler = RateLimitHandler(config)

        domain = "api.test.com"
        response = MockResponse(status_code=429)

        # Record multiple failures
        for _ in range(10):
            handler.record_rate_limit(domain, response)

        # Circuit breaker should never open when disabled
        assert handler.is_circuit_open(domain) is False

    def test_circuit_breaker_closes_after_timeout(self):
        """Test circuit breaker auto-closes after timeout"""
        config = RateLimitConfig(
            circuit_breaker_threshold=1,
            circuit_breaker_timeout=0.1  # 100ms
        )
        handler = RateLimitHandler(config)

        domain = "api.test.com"
        response = MockResponse(status_code=429)

        # Open circuit breaker
        handler.record_rate_limit(domain, response)
        assert handler.is_circuit_open(domain) is True

        # Wait for timeout
        time.sleep(0.15)

        # Should auto-close
        assert handler.is_circuit_open(domain) is False

    def test_circuit_breaker_per_domain(self):
        """Test circuit breaker maintains separate state per domain"""
        config = RateLimitConfig(circuit_breaker_threshold=2)
        handler = RateLimitHandler(config)

        domain1 = "api.domain1.com"
        domain2 = "api.domain2.com"
        response = MockResponse(status_code=429)

        # Open circuit for domain1
        handler.record_rate_limit(domain1, response)
        handler.record_rate_limit(domain1, response)

        # domain1 should be open, domain2 should be closed
        assert handler.is_circuit_open(domain1) is True
        assert handler.is_circuit_open(domain2) is False

    def test_record_success_resets_circuit_breaker(self):
        """Test successful request resets circuit breaker"""
        config = RateLimitConfig(circuit_breaker_threshold=5)
        handler = RateLimitHandler(config)

        domain = "api.test.com"
        response = MockResponse(status_code=429)

        # Record some failures
        handler.record_rate_limit(domain, response)
        handler.record_rate_limit(domain, response)

        assert handler.circuit_breakers[domain].consecutive_failures == 2

        # Record success
        handler.record_success(domain)

        # Should reset counter
        assert handler.circuit_breakers[domain].consecutive_failures == 0
        assert handler.is_circuit_open(domain) is False

    def test_record_success_closes_open_circuit(self):
        """Test successful request closes open circuit breaker"""
        config = RateLimitConfig(circuit_breaker_threshold=1)
        handler = RateLimitHandler(config)

        domain = "api.test.com"
        response = MockResponse(status_code=429)

        # Open circuit breaker
        handler.record_rate_limit(domain, response)
        assert handler.is_circuit_open(domain) is True

        # Record success
        handler.record_success(domain)

        # Should close circuit and reset
        assert handler.is_circuit_open(domain) is False
        assert handler.circuit_breakers[domain].consecutive_failures == 0

    # ========== should_retry() Tests ==========

    def test_should_retry_under_max_retries(self):
        """Test should_retry returns True under max retries"""
        config = RateLimitConfig(max_retries=5)
        handler = RateLimitHandler(config)

        domain = "api.test.com"
        response = MockResponse(status_code=429)

        should_retry, wait_time = handler.should_retry(response, attempt=2, domain=domain)

        assert should_retry is True
        assert wait_time > 0

    def test_should_retry_exceeds_max_retries(self):
        """Test should_retry returns False when max retries exceeded"""
        config = RateLimitConfig(max_retries=3)
        handler = RateLimitHandler(config)

        domain = "api.test.com"
        response = MockResponse(status_code=429)

        should_retry, wait_time = handler.should_retry(response, attempt=3, domain=domain)

        assert should_retry is False
        assert wait_time == 0

    def test_should_retry_circuit_breaker_open(self):
        """Test should_retry returns False when circuit breaker open"""
        config = RateLimitConfig(circuit_breaker_threshold=1)
        handler = RateLimitHandler(config)

        domain = "api.test.com"
        response = MockResponse(status_code=429)

        # Open circuit breaker
        handler.record_rate_limit(domain, response)

        # Should not retry
        should_retry, wait_time = handler.should_retry(response, attempt=0, domain=domain)

        assert should_retry is False
        assert wait_time == 0

    def test_should_retry_uses_retry_after(self):
        """Test should_retry uses Retry-After header for wait time"""
        config = RateLimitConfig(retry_after_enabled=True)
        handler = RateLimitHandler(config)

        domain = "api.test.com"
        response = MockResponse(status_code=429, headers={'Retry-After': '30'})

        should_retry, wait_time = handler.should_retry(response, attempt=0, domain=domain)

        assert should_retry is True
        # Should be close to 30 (with jitter)
        assert 27.0 <= wait_time <= 33.0

    def test_should_retry_retry_after_disabled(self):
        """Test should_retry ignores Retry-After when disabled"""
        config = RateLimitConfig(
            retry_after_enabled=False,
            base_backoff=2.0
        )
        handler = RateLimitHandler(config)

        domain = "api.test.com"
        response = MockResponse(status_code=429, headers={'Retry-After': '120'})

        should_retry, wait_time = handler.should_retry(response, attempt=0, domain=domain)

        assert should_retry is True
        # Should use exponential backoff, not Retry-After
        # Attempt 0: base_backoff * (2^0) = 2.0 with jitter
        assert wait_time < 10.0  # Much less than 120

    def test_should_retry_records_rate_limit(self):
        """Test should_retry records rate limit for circuit breaker"""
        config = RateLimitConfig(circuit_breaker_threshold=2)
        handler = RateLimitHandler(config)

        domain = "api.test.com"
        response = MockResponse(status_code=429)

        # First retry
        handler.should_retry(response, attempt=0, domain=domain)
        assert handler.circuit_breakers[domain].consecutive_failures == 1

        # Second retry - should trip circuit breaker
        handler.should_retry(response, attempt=1, domain=domain)
        assert handler.is_circuit_open(domain) is True

    # ========== Metrics Tests ==========

    def test_get_metrics_initial_state(self):
        """Test get_metrics returns empty state initially"""
        handler = RateLimitHandler()

        metrics = handler.get_metrics()

        assert '429_count' in metrics
        assert 'retry_after_respected' in metrics
        assert 'circuit_breaker_trips' in metrics
        assert 'retry_after_missing' in metrics
        assert 'circuit_breaker_states' in metrics
        assert metrics['retry_after_respected'] == 0
        assert metrics['retry_after_missing'] == 0
        assert isinstance(metrics['429_count'], dict)
        assert isinstance(metrics['circuit_breaker_trips'], dict)

    def test_get_metrics_tracks_429_count(self):
        """Test metrics track 429 responses per domain"""
        handler = RateLimitHandler()

        domain = "api.test.com"
        response = MockResponse(status_code=429)

        # Record multiple rate limits
        handler.should_retry(response, attempt=0, domain=domain)
        handler.should_retry(response, attempt=1, domain=domain)
        handler.should_retry(response, attempt=2, domain=domain)

        metrics = handler.get_metrics()

        assert metrics['429_count'][domain] == 3

    def test_get_metrics_tracks_retry_after(self):
        """Test metrics track Retry-After header usage"""
        handler = RateLimitHandler()

        domain = "api.test.com"
        response_with_retry_after = MockResponse(status_code=429, headers={'Retry-After': '60'})
        response_without = MockResponse(status_code=429)

        # Record rate limits
        handler.should_retry(response_with_retry_after, attempt=0, domain=domain)
        handler.should_retry(response_without, attempt=1, domain=domain)

        metrics = handler.get_metrics()

        # Only one had Retry-After
        assert metrics['retry_after_respected'] == 1

    def test_get_metrics_tracks_circuit_breaker_trips(self):
        """Test metrics track circuit breaker trips"""
        config = RateLimitConfig(circuit_breaker_threshold=2)
        handler = RateLimitHandler(config)

        domain = "api.test.com"
        response = MockResponse(status_code=429)

        # Trip circuit breaker
        handler.should_retry(response, attempt=0, domain=domain)
        handler.should_retry(response, attempt=1, domain=domain)

        metrics = handler.get_metrics()

        # circuit_breaker_trips is a dict with domain keys
        assert metrics['circuit_breaker_trips'][domain] == 1

    def test_get_metrics_tracks_retries_per_domain(self):
        """Test metrics track retry attempts per domain"""
        handler = RateLimitHandler()

        domain1 = "api.domain1.com"
        domain2 = "api.domain2.com"
        response = MockResponse(status_code=429)

        # Record retries across domains
        handler.should_retry(response, attempt=0, domain=domain1)
        handler.should_retry(response, attempt=1, domain=domain1)
        handler.should_retry(response, attempt=0, domain=domain2)

        metrics = handler.get_metrics()

        # Each domain tracks its own count
        assert metrics['429_count'][domain1] == 2
        assert metrics['429_count'][domain2] == 1

    # ========== Singleton Tests ==========

    def test_get_rate_limit_handler_singleton(self):
        """Test get_rate_limit_handler returns singleton instance"""
        handler1 = get_rate_limit_handler()
        handler2 = get_rate_limit_handler()

        assert handler1 is handler2

    def test_reset_rate_limit_handler_clears_state(self):
        """Test reset clears handler state"""
        handler = get_rate_limit_handler()

        domain = "api.test.com"
        response = MockResponse(status_code=429)

        # Add some state
        handler.should_retry(response, attempt=0, domain=domain)

        # Reset
        reset_rate_limit_handler()

        # Get new handler
        new_handler = get_rate_limit_handler()

        # State should be cleared
        metrics = new_handler.get_metrics()
        assert len(metrics['429_count']) == 0
        assert metrics['retry_after_respected'] == 0

    # ========== Config Tests ==========

    def test_rate_limit_config_defaults(self):
        """Test RateLimitConfig default values"""
        config = RateLimitConfig()

        assert config.max_retries == 5
        assert config.base_backoff == 2.0
        assert config.max_backoff == 120.0
        assert config.circuit_breaker_threshold == 10
        assert config.circuit_breaker_timeout == 300.0
        assert config.retry_after_enabled is True
        assert config.circuit_breaker_enabled is True

    def test_rate_limit_config_custom_values(self):
        """Test RateLimitConfig with custom values"""
        config = RateLimitConfig(
            max_retries=10,
            base_backoff=5.0,
            max_backoff=300.0,
            circuit_breaker_threshold=5,
            circuit_breaker_timeout=600.0,
            retry_after_enabled=False,
            circuit_breaker_enabled=False
        )

        assert config.max_retries == 10
        assert config.base_backoff == 5.0
        assert config.max_backoff == 300.0
        assert config.circuit_breaker_threshold == 5
        assert config.circuit_breaker_timeout == 600.0
        assert config.retry_after_enabled is False
        assert config.circuit_breaker_enabled is False

    # ========== Edge Cases ==========

    def test_multiple_domains_independent(self):
        """Test multiple domains maintain independent state"""
        config = RateLimitConfig(circuit_breaker_threshold=2)
        handler = RateLimitHandler(config)

        domain1 = "api.domain1.com"
        domain2 = "api.domain2.com"
        domain3 = "api.domain3.com"
        response = MockResponse(status_code=429)

        # Trip circuit for domain1
        handler.should_retry(response, attempt=0, domain=domain1)
        handler.should_retry(response, attempt=1, domain=domain1)

        # domain1 should be open
        assert handler.is_circuit_open(domain1) is True
        assert handler.is_circuit_open(domain2) is False
        assert handler.is_circuit_open(domain3) is False

        # Other domains should still be able to retry
        should_retry, _ = handler.should_retry(response, attempt=0, domain=domain2)
        assert should_retry is True

    def test_zero_max_retries(self):
        """Test handler with max_retries=0"""
        config = RateLimitConfig(max_retries=0)
        handler = RateLimitHandler(config)

        domain = "api.test.com"
        response = MockResponse(status_code=429)

        should_retry, wait_time = handler.should_retry(response, attempt=0, domain=domain)

        # Should not retry with max_retries=0
        assert should_retry is False
        assert wait_time == 0

    def test_very_large_retry_after(self):
        """Test handling very large Retry-After values"""
        config = RateLimitConfig(max_backoff=120.0)
        handler = RateLimitHandler(config)

        domain = "api.test.com"
        response = MockResponse(status_code=429, headers={'Retry-After': '86400'})  # 24 hours

        should_retry, wait_time = handler.should_retry(response, attempt=0, domain=domain)

        # Should cap at max_backoff
        assert should_retry is True
        assert wait_time <= 120.0

    def test_concurrent_requests_same_domain(self):
        """Test handler behavior with concurrent requests to same domain"""
        config = RateLimitConfig(circuit_breaker_threshold=3)
        handler = RateLimitHandler(config)

        domain = "api.test.com"
        response = MockResponse(status_code=429)

        # Simulate concurrent failures
        handler.record_rate_limit(domain, response)
        handler.record_rate_limit(domain, response)
        handler.record_rate_limit(domain, response)

        # Circuit breaker should trip
        assert handler.is_circuit_open(domain) is True

        # All concurrent requests should see circuit open
        should_retry, _ = handler.should_retry(response, attempt=0, domain=domain)
        assert should_retry is False


class TestCircuitBreakerState:
    """Test CircuitBreakerState dataclass"""

    def test_circuit_breaker_state_defaults(self):
        """Test CircuitBreakerState default values"""
        state = CircuitBreakerState()

        assert state.consecutive_failures == 0
        assert state.is_open is False
        assert state.opened_at is None
        assert state.last_failure_time is None

    def test_circuit_breaker_state_custom_values(self):
        """Test CircuitBreakerState with custom values"""
        now = time.time()
        state = CircuitBreakerState(
            consecutive_failures=5,
            is_open=True,
            opened_at=now,
            last_failure_time=now
        )

        assert state.consecutive_failures == 5
        assert state.is_open is True
        assert state.opened_at == now
        assert state.last_failure_time == now

"""
Tests for shared.utils.rate_limiter module.

Verifies token bucket algorithm, sliding window tracking,
rate limit header parsing, and backoff behavior.
"""

import time
import threading
import pytest
from unittest.mock import Mock, patch

from shared.utils.rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    RateLimitState,
    get_rate_limiter,
    get_rate_limiter_for_url,
    reset_all_rate_limiters,
    get_all_rate_limiter_stats,
    rate_limited,
    PREDEFINED_CONFIGS,
)


class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""

    def test_default_config_values(self):
        """Test default configuration values."""
        config = RateLimitConfig()
        assert config.requests_per_minute == 60
        assert config.burst_size == 10
        assert config.backoff_threshold == 0.8
        assert config.max_backoff_seconds == 30.0
        assert config.min_request_interval == 0.0
        assert config.enabled is True
        assert config.source == "default"

    def test_custom_config_values(self):
        """Test custom configuration values."""
        config = RateLimitConfig(
            requests_per_minute=30,
            burst_size=5,
            backoff_threshold=0.7,
            min_request_interval=1.0,
            source="test.api.com"
        )
        assert config.requests_per_minute == 30
        assert config.burst_size == 5
        assert config.backoff_threshold == 0.7
        assert config.min_request_interval == 1.0
        assert config.source == "test.api.com"

    def test_from_env_default(self):
        """Test configuration from environment with defaults."""
        config = RateLimitConfig.from_env("test.source")
        assert config.source == "test.source"
        assert config.enabled is True

    @patch.dict('os.environ', {'RATE_LIMIT_ENABLED': 'false'})
    def test_from_env_disabled(self):
        """Test rate limiting can be disabled via environment."""
        config = RateLimitConfig.from_env("test.source")
        assert config.enabled is False

    @patch.dict('os.environ', {'RATE_LIMIT_TEST_SOURCE_RPM': '120'})
    def test_from_env_source_override(self):
        """Test source-specific RPM override from environment."""
        config = RateLimitConfig.from_env("test.source")
        assert config.requests_per_minute == 120


class TestPredefinedConfigs:
    """Tests for predefined rate limit configurations."""

    def test_stats_nba_com_config(self):
        """Test stats.nba.com configuration exists and is conservative."""
        assert "stats.nba.com" in PREDEFINED_CONFIGS
        config = PREDEFINED_CONFIGS["stats.nba.com"]
        assert config.requests_per_minute == 30
        assert config.min_request_interval == 1.0

    def test_odds_api_config(self):
        """Test odds API configuration exists."""
        assert "api.the-odds-api.com" in PREDEFINED_CONFIGS
        config = PREDEFINED_CONFIGS["api.the-odds-api.com"]
        assert config.requests_per_minute == 30
        assert config.min_request_interval == 2.0

    def test_basketball_reference_config(self):
        """Test basketball-reference configuration is very conservative."""
        assert "www.basketball-reference.com" in PREDEFINED_CONFIGS
        config = PREDEFINED_CONFIGS["www.basketball-reference.com"]
        assert config.requests_per_minute == 10
        assert config.min_request_interval == 5.0


class TestRateLimiter:
    """Tests for RateLimiter class."""

    @pytest.fixture
    def limiter(self):
        """Create a rate limiter for testing."""
        config = RateLimitConfig(
            requests_per_minute=60,
            burst_size=5,
            backoff_threshold=0.8,
            source="test"
        )
        return RateLimiter(config)

    @pytest.fixture
    def fast_limiter(self):
        """Create a fast rate limiter for timing tests."""
        config = RateLimitConfig(
            requests_per_minute=600,  # 10 per second
            burst_size=10,
            min_request_interval=0.0,
            source="fast_test"
        )
        return RateLimiter(config)

    def test_initialization(self, limiter):
        """Test limiter initializes correctly."""
        assert limiter.config.source == "test"
        assert limiter.state.tokens == 5.0  # burst_size
        assert limiter.state.total_requests == 0

    def test_acquire_immediate_success(self, limiter):
        """Test acquire succeeds immediately when tokens available."""
        assert limiter.acquire(timeout=0.1) is True
        assert limiter.state.tokens == 4.0
        assert limiter.state.total_requests == 1

    def test_acquire_consumes_tokens(self, limiter):
        """Test acquire consumes tokens from bucket."""
        for i in range(5):
            assert limiter.acquire(timeout=0.1) is True
        # Tokens may be slightly above 0 due to refill during execution
        assert limiter.state.tokens < 0.1
        assert limiter.state.total_requests == 5

    def test_acquire_waits_for_refill(self):
        """Test acquire waits when tokens exhausted."""
        # Create a limiter with very high RPM to test refill quickly
        # Important: set backoff_threshold to 1.0 to avoid extra backoff delay
        config = RateLimitConfig(
            requests_per_minute=6000,  # 100 per second
            burst_size=5,
            backoff_threshold=1.0,  # Disable backoff for this test
            min_request_interval=0.0,
            max_backoff_seconds=0.0,  # No backoff
            source="refill_test"
        )
        limiter = RateLimiter(config)

        # Exhaust tokens
        for _ in range(5):
            limiter.acquire(timeout=0.5)

        # Tokens should be nearly exhausted
        assert limiter.state.tokens < 0.5

        # Next acquire should wait for refill
        start = time.monotonic()
        assert limiter.acquire(timeout=1.0) is True
        elapsed = time.monotonic() - start

        # Should have waited some time for token refill
        assert elapsed >= 0.005  # At least a few ms delay

    def test_acquire_timeout(self, limiter):
        """Test acquire returns False on timeout."""
        # Exhaust tokens
        for _ in range(5):
            limiter.acquire(timeout=0.1)

        # Very short timeout should fail
        assert limiter.acquire(timeout=0.001) is False

    def test_acquire_disabled(self):
        """Test acquire succeeds immediately when disabled."""
        config = RateLimitConfig(enabled=False)
        limiter = RateLimiter(config)

        for _ in range(100):
            assert limiter.acquire(timeout=0) is True

    def test_token_refill(self, fast_limiter):
        """Test tokens refill over time."""
        # Exhaust some tokens
        for _ in range(5):
            fast_limiter.acquire(timeout=0.1)

        initial_tokens = fast_limiter.state.tokens

        # Wait for refill
        time.sleep(0.2)

        # Trigger refill check
        fast_limiter.acquire(timeout=0.1)

        # Tokens should have increased (minus 1 for acquire)
        assert fast_limiter.state.tokens > initial_tokens - 1

    def test_min_request_interval(self):
        """Test minimum request interval is enforced."""
        config = RateLimitConfig(
            requests_per_minute=600,
            burst_size=10,
            min_request_interval=0.1,
            source="interval_test"
        )
        limiter = RateLimiter(config)

        # First request immediate
        start = time.monotonic()
        limiter.acquire(timeout=1.0)
        first_time = time.monotonic() - start
        assert first_time < 0.05

        # Second request should wait for interval
        start = time.monotonic()
        limiter.acquire(timeout=1.0)
        second_time = time.monotonic() - start
        assert second_time >= 0.08  # Allow some slack

    def test_get_stats(self, limiter):
        """Test get_stats returns expected structure."""
        limiter.acquire(timeout=0.1)

        stats = limiter.get_stats()

        assert stats['source'] == "test"
        assert stats['enabled'] is True
        assert 'config' in stats
        assert 'state' in stats
        assert 'statistics' in stats
        assert stats['statistics']['total_requests'] == 1

    def test_reset(self, limiter):
        """Test reset clears state."""
        # Make some requests
        for _ in range(3):
            limiter.acquire(timeout=0.1)

        assert limiter.state.total_requests == 3

        # Reset
        limiter.reset()

        assert limiter.state.tokens == 5.0
        assert limiter.state.total_requests == 0


class TestRateLimiterResponseHandling:
    """Tests for rate limit header parsing and response handling."""

    @pytest.fixture
    def limiter(self):
        """Create a rate limiter for testing."""
        config = RateLimitConfig(
            requests_per_minute=60,
            burst_size=10,
            source="response_test"
        )
        return RateLimiter(config)

    def test_update_from_response_with_rate_limit_headers(self, limiter):
        """Test rate limit headers are parsed correctly."""
        response = Mock()
        response.status_code = 200
        response.headers = {
            'X-RateLimit-Limit': '100',
            'X-RateLimit-Remaining': '50',
            'X-RateLimit-Reset': '1640000000'
        }

        limiter.update_from_response(response)

        assert limiter.state.limit_from_headers == 100
        assert limiter.state.remaining_from_headers == 50
        assert limiter.state.reset_time_from_headers == 1640000000.0

    def test_update_from_429_response(self, limiter):
        """Test 429 response triggers backoff."""
        response = Mock()
        response.status_code = 429
        response.headers = {'Retry-After': '5'}

        limiter.update_from_response(response)

        assert limiter.state.consecutive_rate_limits == 1
        assert limiter.state.current_backoff == 5.0

    def test_update_from_429_without_retry_after(self, limiter):
        """Test 429 without Retry-After uses exponential backoff."""
        response = Mock()
        response.status_code = 429
        response.headers = {}

        limiter.update_from_response(response)

        assert limiter.state.consecutive_rate_limits == 1
        assert limiter.state.current_backoff == 2.0  # 2^1

    def test_consecutive_429_exponential_backoff(self, limiter):
        """Test consecutive 429s increase backoff exponentially."""
        response = Mock()
        response.status_code = 429
        response.headers = {}

        for i in range(3):
            limiter.update_from_response(response)

        assert limiter.state.consecutive_rate_limits == 3
        assert limiter.state.current_backoff == 8.0  # 2^3

    def test_success_resets_backoff(self, limiter):
        """Test successful response resets backoff state."""
        # First trigger backoff
        response_429 = Mock()
        response_429.status_code = 429
        response_429.headers = {}
        limiter.update_from_response(response_429)

        assert limiter.state.consecutive_rate_limits == 1
        initial_backoff = limiter.state.current_backoff

        # Then success
        response_200 = Mock()
        response_200.status_code = 200
        response_200.headers = {}
        limiter.update_from_response(response_200)

        assert limiter.state.consecutive_rate_limits == 0
        # Backoff is halved on success
        assert limiter.state.current_backoff == initial_backoff * 0.5


class TestRateLimiterRegistry:
    """Tests for global rate limiter registry functions."""

    def setup_method(self):
        """Reset registry before each test."""
        reset_all_rate_limiters()

    def teardown_method(self):
        """Reset registry after each test."""
        reset_all_rate_limiters()

    def test_get_rate_limiter_creates_instance(self):
        """Test get_rate_limiter creates new instance."""
        limiter = get_rate_limiter("test.example.com")

        assert limiter is not None
        assert limiter.config.source == "test.example.com"

    def test_get_rate_limiter_returns_same_instance(self):
        """Test get_rate_limiter returns cached instance."""
        limiter1 = get_rate_limiter("test.example.com")
        limiter2 = get_rate_limiter("test.example.com")

        assert limiter1 is limiter2

    def test_get_rate_limiter_uses_predefined_config(self):
        """Test get_rate_limiter uses predefined config for known sources."""
        limiter = get_rate_limiter("stats.nba.com")

        assert limiter.config.requests_per_minute == 30
        assert limiter.config.min_request_interval == 1.0

    def test_get_rate_limiter_for_url(self):
        """Test get_rate_limiter_for_url extracts domain correctly."""
        limiter = get_rate_limiter_for_url("https://stats.nba.com/stats/playergamelog")

        assert limiter.config.source == "stats.nba.com"

    def test_get_rate_limiter_normalizes_url(self):
        """Test URL with different paths returns same limiter."""
        limiter1 = get_rate_limiter_for_url("https://api.espn.com/v1/scoreboard")
        limiter2 = get_rate_limiter_for_url("https://api.espn.com/v2/boxscore")

        assert limiter1 is limiter2

    def test_get_all_rate_limiter_stats(self):
        """Test get_all_rate_limiter_stats returns all limiters."""
        get_rate_limiter("source1.com")
        get_rate_limiter("source2.com")

        stats = get_all_rate_limiter_stats()

        assert "source1.com" in stats
        assert "source2.com" in stats

    def test_reset_all_rate_limiters(self):
        """Test reset_all_rate_limiters clears registry."""
        limiter = get_rate_limiter("test.com")
        limiter.acquire(timeout=0.1)

        reset_all_rate_limiters()

        # New limiter should be fresh
        new_limiter = get_rate_limiter("test.com")
        assert new_limiter.state.total_requests == 0


class TestRateLimitedDecorator:
    """Tests for rate_limited decorator."""

    def setup_method(self):
        """Reset registry before each test."""
        reset_all_rate_limiters()

    def teardown_method(self):
        """Reset registry after each test."""
        reset_all_rate_limiters()

    def test_decorator_applies_rate_limiting(self):
        """Test decorator applies rate limiting to function."""
        call_count = 0

        @rate_limited("decorator.test.com")
        def my_function():
            nonlocal call_count
            call_count += 1
            return "result"

        result = my_function()

        assert result == "result"
        assert call_count == 1

        # Check limiter was used
        limiter = get_rate_limiter("decorator.test.com")
        assert limiter.state.total_requests == 1


class TestThreadSafety:
    """Tests for thread safety of rate limiter."""

    def setup_method(self):
        """Reset registry before each test."""
        reset_all_rate_limiters()

    def teardown_method(self):
        """Reset registry after each test."""
        reset_all_rate_limiters()

    def test_concurrent_acquire(self):
        """Test multiple threads can safely acquire tokens."""
        config = RateLimitConfig(
            requests_per_minute=6000,  # High limit to avoid delays
            burst_size=100,
            source="thread_test"
        )
        limiter = RateLimiter(config)
        results = []
        threads = []

        def worker():
            for _ in range(10):
                result = limiter.acquire(timeout=1.0)
                results.append(result)

        # Start 5 threads
        for _ in range(5):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # All acquires should succeed
        assert len(results) == 50
        assert all(results)
        assert limiter.state.total_requests == 50

    def test_concurrent_registry_access(self):
        """Test multiple threads can safely access registry."""
        results = []
        threads = []

        def worker(source_id):
            limiter = get_rate_limiter(f"source{source_id}.com")
            limiter.acquire(timeout=0.1)
            results.append(limiter.config.source)

        # Start threads with different sources
        for i in range(10):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        assert len(results) == 10
        assert len(set(results)) == 10  # All unique sources

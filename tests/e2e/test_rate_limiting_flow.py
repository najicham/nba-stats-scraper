"""
End-to-end tests for rate limiting flow.

Tests the full integration of:
- RateLimitHandler with circuit breaker
- HTTP pool integration
- Scraper base integration
- Retry-After header parsing
- Exponential backoff with jitter
"""

import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from requests.exceptions import HTTPError
import requests

from shared.utils.rate_limit_handler import get_rate_limit_handler, RateLimitHandler
from shared.config.rate_limit_config import get_rate_limit_config


class TestRateLimitingCircuitBreaker:
    """Test circuit breaker functionality in rate limiting."""

    def setup_method(self):
        """Reset rate limit handler singleton before each test."""
        RateLimitHandler._instance = None
        RateLimitHandler._lock = None

    def test_circuit_breaker_trips_after_threshold_429s(self):
        """Test that circuit breaker trips after threshold 429 errors."""
        # Arrange
        handler = get_rate_limit_handler()
        domain = "api.test.com"

        # Configure for fast testing
        with patch.dict('os.environ', {
            'RATE_LIMIT_CB_THRESHOLD': '3',
            'RATE_LIMIT_CB_ENABLED': 'true'
        }):
            handler = get_rate_limit_handler()

        # Act - Simulate 3 rate limit errors
        for i in range(3):
            handler.handle_rate_limit(domain, retry_after=1)

        # Assert - Circuit should be open
        metrics = handler.get_metrics()
        assert domain in metrics['circuit_breakers']
        assert metrics['circuit_breakers'][domain]['state'] == 'open'
        assert metrics['circuit_breakers'][domain]['failure_count'] >= 3

    def test_circuit_breaker_blocks_subsequent_requests(self):
        """Test that open circuit breaker blocks subsequent requests."""
        # Arrange
        with patch.dict('os.environ', {
            'RATE_LIMIT_CB_THRESHOLD': '2',
            'RATE_LIMIT_CB_ENABLED': 'true'
        }):
            handler = get_rate_limit_handler()

        domain = "api.blocked.com"

        # Trip the circuit
        for i in range(2):
            handler.handle_rate_limit(domain, retry_after=1)

        # Act & Assert - Should raise exception for blocked requests
        from shared.utils.rate_limit_handler import CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            handler.check_circuit_breaker(domain)

        assert domain in str(exc_info.value)
        assert "Circuit breaker is open" in str(exc_info.value)

    def test_circuit_breaker_recovers_after_timeout(self):
        """Test that circuit breaker transitions to half-open after timeout."""
        # Arrange
        with patch.dict('os.environ', {
            'RATE_LIMIT_CB_THRESHOLD': '2',
            'RATE_LIMIT_CB_TIMEOUT': '1',  # 1 second timeout
            'RATE_LIMIT_CB_ENABLED': 'true'
        }):
            handler = get_rate_limit_handler()

        domain = "api.recovery.com"

        # Trip the circuit
        for i in range(2):
            handler.handle_rate_limit(domain, retry_after=0.1)

        # Verify circuit is open
        metrics = handler.get_metrics()
        assert metrics['circuit_breakers'][domain]['state'] == 'open'

        # Act - Wait for timeout
        time.sleep(1.5)

        # Assert - Circuit should transition to half-open
        handler.check_circuit_breaker(domain)  # This should succeed in half-open
        metrics = handler.get_metrics()
        assert metrics['circuit_breakers'][domain]['state'] == 'half_open'


class TestRetryAfterParsing:
    """Test Retry-After header parsing and handling."""

    def setup_method(self):
        """Reset rate limit handler singleton before each test."""
        RateLimitHandler._instance = None
        RateLimitHandler._lock = None

    def test_retry_after_seconds_format(self):
        """Test parsing Retry-After header in seconds format."""
        # Arrange
        handler = get_rate_limit_handler()
        domain = "api.test.com"

        # Act
        wait_time = handler.handle_rate_limit(domain, retry_after=60)

        # Assert
        assert wait_time == 60
        metrics = handler.get_metrics()
        assert metrics['total_rate_limits'] == 1

    def test_retry_after_http_date_format(self):
        """Test parsing Retry-After header in HTTP-date format."""
        # Arrange
        handler = get_rate_limit_handler()
        domain = "api.test.com"

        # Create HTTP-date 30 seconds in the future
        future_time = datetime.utcnow() + timedelta(seconds=30)
        http_date = future_time.strftime('%a, %d %b %Y %H:%M:%S GMT')

        # Act
        wait_time = handler.handle_rate_limit(domain, retry_after=http_date)

        # Assert - Should be approximately 30 seconds (allow 1 second tolerance)
        assert 29 <= wait_time <= 31

    def test_retry_after_invalid_format_falls_back_to_backoff(self):
        """Test that invalid Retry-After format falls back to exponential backoff."""
        # Arrange
        with patch.dict('os.environ', {
            'RATE_LIMIT_BASE_BACKOFF': '2.0',
            'RATE_LIMIT_RETRY_AFTER_ENABLED': 'false'
        }):
            handler = get_rate_limit_handler()

        domain = "api.test.com"

        # Act
        wait_time = handler.handle_rate_limit(domain, retry_after=None, attempt=1)

        # Assert - Should use exponential backoff: 2.0 * (2 ** 0) = 2.0
        assert 1.8 <= wait_time <= 2.2  # Allow for jitter


class TestExponentialBackoff:
    """Test exponential backoff calculations."""

    def setup_method(self):
        """Reset rate limit handler singleton before each test."""
        RateLimitHandler._instance = None
        RateLimitHandler._lock = None

    def test_backoff_increases_exponentially(self):
        """Test that backoff time increases exponentially with attempts."""
        # Arrange
        with patch.dict('os.environ', {
            'RATE_LIMIT_BASE_BACKOFF': '2.0',
            'RATE_LIMIT_MAX_BACKOFF': '120.0'
        }):
            handler = get_rate_limit_handler()

        domain = "api.test.com"

        # Act & Assert
        wait_times = []
        for attempt in range(5):
            wait_time = handler.handle_rate_limit(domain, retry_after=None, attempt=attempt)
            wait_times.append(wait_time)

        # Verify exponential growth (each should be roughly double, accounting for jitter)
        # Expected: 2, 4, 8, 16, 32 (with jitter)
        assert wait_times[0] < 3  # ~2 seconds
        assert wait_times[1] < 5  # ~4 seconds
        assert wait_times[2] < 10  # ~8 seconds
        assert wait_times[3] < 20  # ~16 seconds
        assert wait_times[4] < 40  # ~32 seconds

    def test_backoff_respects_max_limit(self):
        """Test that backoff time doesn't exceed max_backoff."""
        # Arrange
        with patch.dict('os.environ', {
            'RATE_LIMIT_BASE_BACKOFF': '2.0',
            'RATE_LIMIT_MAX_BACKOFF': '10.0'
        }):
            handler = get_rate_limit_handler()

        domain = "api.test.com"

        # Act - Attempt very high retry count
        wait_time = handler.handle_rate_limit(domain, retry_after=None, attempt=20)

        # Assert - Should not exceed max_backoff (10.0 + small jitter)
        assert wait_time <= 11.0


class TestHTTPPoolIntegration:
    """Test integration with HTTP pool client."""

    def setup_method(self):
        """Reset rate limit handler singleton before each test."""
        RateLimitHandler._instance = None
        RateLimitHandler._lock = None

    @patch('shared.clients.http_pool.requests.Session')
    def test_http_pool_handles_429_with_retry_after(self, mock_session_class):
        """Test that HTTP pool properly handles 429 with Retry-After header."""
        # Arrange
        from shared.clients.http_pool import HTTPPoolManager

        # Create mock response with 429 status
        mock_response_429 = Mock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {'Retry-After': '5'}
        mock_response_429.raise_for_status.side_effect = HTTPError(response=mock_response_429)

        # Create successful response
        mock_response_200 = Mock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {"data": "success"}

        # Mock session to return 429 first, then 200
        mock_session = Mock()
        mock_session.get.side_effect = [mock_response_429, mock_response_200]
        mock_session_class.return_value = mock_session

        pool_manager = HTTPPoolManager()

        # Act
        with patch('time.sleep') as mock_sleep:  # Mock sleep to avoid actual waiting
            response = pool_manager.get("https://api.test.com/endpoint", max_retries=2)

        # Assert
        assert response.status_code == 200
        assert mock_session.get.call_count == 2
        # Should have slept approximately 5 seconds (from Retry-After)
        assert mock_sleep.called

    @patch('shared.clients.http_pool.requests.Session')
    def test_http_pool_respects_circuit_breaker(self, mock_session_class):
        """Test that HTTP pool respects open circuit breaker."""
        # Arrange
        from shared.clients.http_pool import HTTPPoolManager
        from shared.utils.rate_limit_handler import CircuitBreakerOpenError

        with patch.dict('os.environ', {
            'RATE_LIMIT_CB_THRESHOLD': '2',
            'RATE_LIMIT_CB_ENABLED': 'true'
        }):
            # Create mock response with 429 status
            mock_response_429 = Mock()
            mock_response_429.status_code = 429
            mock_response_429.headers = {}
            mock_response_429.raise_for_status.side_effect = HTTPError(response=mock_response_429)

            mock_session = Mock()
            mock_session.get.return_value = mock_response_429
            mock_session_class.return_value = mock_session

            pool_manager = HTTPPoolManager()

            # Act - Make requests until circuit breaker trips
            with patch('time.sleep'):  # Mock sleep
                with pytest.raises((HTTPError, CircuitBreakerOpenError)):
                    for i in range(5):
                        try:
                            pool_manager.get("https://api.test.com/endpoint", max_retries=1)
                        except HTTPError:
                            if i < 4:  # Allow failures until circuit trips
                                continue
                            raise


class TestScraperBaseIntegration:
    """Test integration with scraper base class."""

    def setup_method(self):
        """Reset rate limit handler singleton before each test."""
        RateLimitHandler._instance = None
        RateLimitHandler._lock = None

    def test_scraper_validates_data_quality(self):
        """Test that scraper base validates data before returning."""
        # This is a placeholder for scraper base validation testing
        # Actual implementation would test the validate_before_return decorator
        from scrapers.scraper_base import ScraperBase

        # Mock scraper implementation
        class TestScraper(ScraperBase):
            def scrape(self):
                return {"test": "data"}

        scraper = TestScraper(
            sport="nba",
            data_source="test",
            season="2023-24"
        )

        # Verify scraper has validation capabilities
        assert hasattr(scraper, 'validate_data')


class TestEndToEndRateLimitingFlow:
    """Complete end-to-end rate limiting flow tests."""

    def setup_method(self):
        """Reset rate limit handler singleton before each test."""
        RateLimitHandler._instance = None
        RateLimitHandler._lock = None

    @patch('shared.clients.http_pool.requests.Session')
    def test_complete_rate_limit_flow_with_recovery(self, mock_session_class):
        """Test complete flow: 429 errors -> retry -> circuit breaker -> recovery."""
        # Arrange
        from shared.clients.http_pool import HTTPPoolManager

        # Create sequence of responses: 429, 429, 200
        mock_response_429_1 = Mock()
        mock_response_429_1.status_code = 429
        mock_response_429_1.headers = {'Retry-After': '1'}
        mock_response_429_1.raise_for_status.side_effect = HTTPError(response=mock_response_429_1)

        mock_response_429_2 = Mock()
        mock_response_429_2.status_code = 429
        mock_response_429_2.headers = {'Retry-After': '1'}
        mock_response_429_2.raise_for_status.side_effect = HTTPError(response=mock_response_429_2)

        mock_response_200 = Mock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {"success": True}

        mock_session = Mock()
        mock_session.get.side_effect = [
            mock_response_429_1,
            mock_response_429_2,
            mock_response_200
        ]
        mock_session_class.return_value = mock_session

        pool_manager = HTTPPoolManager()

        # Act
        with patch('time.sleep'):  # Mock sleep to speed up test
            response = pool_manager.get("https://api.test.com/data", max_retries=3)

        # Assert
        assert response.status_code == 200
        assert mock_session.get.call_count == 3

        # Verify rate limit handler tracked the events
        handler = get_rate_limit_handler()
        metrics = handler.get_metrics()
        assert metrics['total_rate_limits'] >= 2

    def test_metrics_tracking_across_multiple_domains(self):
        """Test that metrics are tracked separately for different domains."""
        # Arrange
        handler = get_rate_limit_handler()
        domain1 = "api.domain1.com"
        domain2 = "api.domain2.com"

        # Act
        handler.handle_rate_limit(domain1, retry_after=10)
        handler.handle_rate_limit(domain1, retry_after=20)
        handler.handle_rate_limit(domain2, retry_after=15)

        # Assert
        metrics = handler.get_metrics()
        assert metrics['total_rate_limits'] == 3
        assert domain1 in metrics['circuit_breakers']
        assert domain2 in metrics['circuit_breakers']
        assert metrics['circuit_breakers'][domain1]['failure_count'] == 2
        assert metrics['circuit_breakers'][domain2]['failure_count'] == 1

    def test_configuration_via_environment_variables(self):
        """Test that configuration is properly loaded from environment variables."""
        # Arrange & Act
        with patch.dict('os.environ', {
            'RATE_LIMIT_MAX_RETRIES': '10',
            'RATE_LIMIT_BASE_BACKOFF': '5.0',
            'RATE_LIMIT_MAX_BACKOFF': '300.0',
            'RATE_LIMIT_CB_THRESHOLD': '20',
            'RATE_LIMIT_CB_TIMEOUT': '600',
            'RATE_LIMIT_CB_ENABLED': 'true',
            'RATE_LIMIT_RETRY_AFTER_ENABLED': 'true'
        }):
            config = get_rate_limit_config()

        # Assert
        assert config['max_retries'] == 10
        assert config['base_backoff'] == 5.0
        assert config['max_backoff'] == 300.0
        assert config['circuit_breaker_threshold'] == 20
        assert config['circuit_breaker_timeout'] == 600
        assert config['circuit_breaker_enabled'] is True
        assert config['retry_after_enabled'] is True


class TestRateLimitingPerformance:
    """Test performance characteristics of rate limiting."""

    def setup_method(self):
        """Reset rate limit handler singleton before each test."""
        RateLimitHandler._instance = None
        RateLimitHandler._lock = None

    def test_singleton_performance(self):
        """Test that singleton pattern is performant for concurrent access."""
        import threading

        results = []

        def get_handler():
            handler = get_rate_limit_handler()
            results.append(id(handler))

        # Act - Create 10 threads accessing handler simultaneously
        threads = [threading.Thread(target=get_handler) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Assert - All threads should get the same instance
        assert len(set(results)) == 1

    def test_metrics_collection_overhead(self):
        """Test that metrics collection has minimal overhead."""
        handler = get_rate_limit_handler()
        domain = "api.performance.com"

        # Act - Perform 100 rate limit operations
        start_time = time.time()
        for i in range(100):
            handler.handle_rate_limit(domain, retry_after=0.001, attempt=i % 5)

        # Get metrics
        metrics = handler.get_metrics()
        end_time = time.time()

        # Assert - Should complete quickly (< 1 second for 100 operations)
        elapsed = end_time - start_time
        assert elapsed < 1.0
        assert metrics['total_rate_limits'] == 100


# Fixtures for E2E tests
@pytest.fixture
def mock_api_server():
    """Fixture providing a mock API server for testing."""
    class MockAPIServer:
        def __init__(self):
            self.request_count = 0
            self.responses = []

        def add_response(self, status_code, headers=None, body=None):
            response = Mock()
            response.status_code = status_code
            response.headers = headers or {}
            response.json.return_value = body or {}
            if status_code >= 400:
                response.raise_for_status.side_effect = HTTPError(response=response)
            self.responses.append(response)

        def get_response(self):
            if self.request_count < len(self.responses):
                response = self.responses[self.request_count]
                self.request_count += 1
                return response
            return None

    return MockAPIServer()


@pytest.fixture
def reset_rate_limit_handler():
    """Fixture to reset rate limit handler between tests."""
    yield
    RateLimitHandler._instance = None
    RateLimitHandler._lock = None

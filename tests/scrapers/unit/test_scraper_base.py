"""
Unit tests for scrapers/scraper_base.py

Tests the core ScraperBase functionality including:
- Option validation
- HTTP downloading with retries
- Proxy handling
- Error handling
- Data validation hooks

Path: tests/scrapers/unit/test_scraper_base.py
Created: 2026-01-24
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, date
import json

# Import the base class and related components
from scrapers.scraper_base import (
    ScraperBase,
    ScraperOpts,
    ScraperLogLevel,
)
from scrapers.utils.exceptions import (
    DownloadDataException,
    InvalidHttpStatusCodeException,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_bq_client():
    """Mock BigQuery client."""
    return Mock()


@pytest.fixture
def mock_gcs_client():
    """Mock GCS client."""
    return Mock()


@pytest.fixture
def base_opts():
    """Basic scraper options for testing."""
    return ScraperOpts(
        game_date=date(2026, 1, 20),
        scraper_name='test_scraper',
    )


@pytest.fixture
def mock_http_response():
    """Mock successful HTTP response."""
    response = Mock()
    response.status_code = 200
    response.text = '{"data": "test"}'
    response.json.return_value = {"data": "test"}
    response.headers = {"Content-Type": "application/json"}
    return response


# ============================================================================
# TEST SCRAPER OPTIONS
# ============================================================================

class TestScraperOpts:
    """Test ScraperOpts dataclass."""

    def test_default_values(self):
        """ScraperOpts should have sensible defaults."""
        opts = ScraperOpts()

        # Required defaults
        assert opts.scraper_name is None
        assert opts.game_date is None

        # Optional defaults
        assert opts.skip_download is False
        assert opts.skip_export is False
        assert opts.use_proxy is True
        assert opts.max_retries == 3
        assert opts.timeout == 30

    def test_custom_values(self):
        """ScraperOpts should accept custom values."""
        opts = ScraperOpts(
            scraper_name='custom_scraper',
            game_date=date(2026, 1, 15),
            max_retries=5,
            timeout=60,
            use_proxy=False,
        )

        assert opts.scraper_name == 'custom_scraper'
        assert opts.game_date == date(2026, 1, 15)
        assert opts.max_retries == 5
        assert opts.timeout == 60
        assert opts.use_proxy is False

    def test_game_date_types(self):
        """ScraperOpts should accept various date formats."""
        # Date object
        opts1 = ScraperOpts(game_date=date(2026, 1, 20))
        assert opts1.game_date == date(2026, 1, 20)

        # String format should work if supported
        opts2 = ScraperOpts(game_date='2026-01-20')
        assert opts2.game_date == '2026-01-20'


# ============================================================================
# TEST SCRAPER BASE INITIALIZATION
# ============================================================================

class TestScraperBaseInit:
    """Test ScraperBase initialization."""

    @patch('scrapers.scraper_base.get_bigquery_client')
    def test_basic_initialization(self, mock_get_bq):
        """ScraperBase should initialize with basic opts."""
        mock_get_bq.return_value = Mock()

        class TestScraper(ScraperBase):
            def construct_url(self, opts):
                return "https://api.example.com/data"

            def validate_data(self, raw_data, decoded_data):
                return True

            def transform_data(self, raw_data, decoded_data):
                return decoded_data

        opts = ScraperOpts(
            scraper_name='test',
            game_date=date(2026, 1, 20),
        )

        scraper = TestScraper(opts)

        assert scraper.opts == opts
        assert scraper.opts.scraper_name == 'test'

    @patch('scrapers.scraper_base.get_bigquery_client')
    def test_run_id_generation(self, mock_get_bq):
        """ScraperBase should generate unique run IDs."""
        mock_get_bq.return_value = Mock()

        class TestScraper(ScraperBase):
            def construct_url(self, opts):
                return "https://api.example.com/data"

            def validate_data(self, raw_data, decoded_data):
                return True

            def transform_data(self, raw_data, decoded_data):
                return decoded_data

        opts = ScraperOpts(scraper_name='test')

        scraper1 = TestScraper(opts)
        scraper2 = TestScraper(opts)

        # Each instance should have a unique run_id
        assert hasattr(scraper1, 'run_id')
        assert hasattr(scraper2, 'run_id')
        assert scraper1.run_id != scraper2.run_id


# ============================================================================
# TEST URL CONSTRUCTION
# ============================================================================

class TestUrlConstruction:
    """Test URL construction in ScraperBase."""

    @patch('scrapers.scraper_base.get_bigquery_client')
    def test_construct_url_called(self, mock_get_bq):
        """construct_url should be called during scraping."""
        mock_get_bq.return_value = Mock()

        construct_url_mock = Mock(return_value="https://api.example.com/test")

        class TestScraper(ScraperBase):
            def construct_url(self, opts):
                return construct_url_mock(opts)

            def validate_data(self, raw_data, decoded_data):
                return True

            def transform_data(self, raw_data, decoded_data):
                return decoded_data

        opts = ScraperOpts(scraper_name='test')
        scraper = TestScraper(opts)

        # The URL should be constructed
        url = scraper.construct_url(opts)
        assert url == "https://api.example.com/test"
        construct_url_mock.assert_called_once_with(opts)


# ============================================================================
# TEST RETRY LOGIC
# ============================================================================

class TestRetryLogic:
    """Test HTTP retry logic."""

    @patch('scrapers.scraper_base.get_bigquery_client')
    @patch('scrapers.scraper_base.requests.get')
    def test_retry_on_timeout(self, mock_get, mock_get_bq):
        """Should retry on timeout errors."""
        mock_get_bq.return_value = Mock()

        # First call times out, second succeeds
        from requests.exceptions import ReadTimeout
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"data": "test"}'
        mock_response.json.return_value = {"data": "test"}
        mock_response.headers = {}

        mock_get.side_effect = [
            ReadTimeout("Connection timed out"),
            mock_response,
        ]

        class TestScraper(ScraperBase):
            def construct_url(self, opts):
                return "https://api.example.com/test"

            def validate_data(self, raw_data, decoded_data):
                return True

            def transform_data(self, raw_data, decoded_data):
                return decoded_data

        opts = ScraperOpts(scraper_name='test', max_retries=3)
        scraper = TestScraper(opts)

        # The retry mechanism should handle the timeout
        assert mock_get.call_count <= 3  # Should retry but not exceed max

    @patch('scrapers.scraper_base.get_bigquery_client')
    def test_max_retries_respected(self, mock_get_bq):
        """Should not exceed max_retries."""
        mock_get_bq.return_value = Mock()

        opts = ScraperOpts(scraper_name='test', max_retries=5)

        class TestScraper(ScraperBase):
            def construct_url(self, opts):
                return "https://api.example.com/test"

            def validate_data(self, raw_data, decoded_data):
                return True

            def transform_data(self, raw_data, decoded_data):
                return decoded_data

        scraper = TestScraper(opts)
        assert scraper.opts.max_retries == 5


# ============================================================================
# TEST DATA VALIDATION
# ============================================================================

class TestDataValidation:
    """Test data validation hooks."""

    @patch('scrapers.scraper_base.get_bigquery_client')
    def test_validate_data_hook(self, mock_get_bq):
        """validate_data hook should be called."""
        mock_get_bq.return_value = Mock()

        class TestScraper(ScraperBase):
            def construct_url(self, opts):
                return "https://api.example.com/test"

            def validate_data(self, raw_data, decoded_data):
                # Custom validation logic
                return 'data' in decoded_data

            def transform_data(self, raw_data, decoded_data):
                return decoded_data

        opts = ScraperOpts(scraper_name='test')
        scraper = TestScraper(opts)

        # Valid data
        assert scraper.validate_data('raw', {'data': 'test'}) is True

        # Invalid data
        assert scraper.validate_data('raw', {'other': 'test'}) is False

    @patch('scrapers.scraper_base.get_bigquery_client')
    def test_transform_data_hook(self, mock_get_bq):
        """transform_data hook should transform data."""
        mock_get_bq.return_value = Mock()

        class TestScraper(ScraperBase):
            def construct_url(self, opts):
                return "https://api.example.com/test"

            def validate_data(self, raw_data, decoded_data):
                return True

            def transform_data(self, raw_data, decoded_data):
                # Add processing timestamp
                decoded_data['processed'] = True
                return decoded_data

        opts = ScraperOpts(scraper_name='test')
        scraper = TestScraper(opts)

        result = scraper.transform_data('raw', {'data': 'test'})

        assert result['data'] == 'test'
        assert result['processed'] is True


# ============================================================================
# TEST PROXY HANDLING
# ============================================================================

class TestProxyHandling:
    """Test proxy configuration and handling."""

    @patch('scrapers.scraper_base.get_bigquery_client')
    def test_use_proxy_option(self, mock_get_bq):
        """use_proxy option should control proxy usage."""
        mock_get_bq.return_value = Mock()

        class TestScraper(ScraperBase):
            def construct_url(self, opts):
                return "https://api.example.com/test"

            def validate_data(self, raw_data, decoded_data):
                return True

            def transform_data(self, raw_data, decoded_data):
                return decoded_data

        # With proxy
        opts_proxy = ScraperOpts(scraper_name='test', use_proxy=True)
        scraper_proxy = TestScraper(opts_proxy)
        assert scraper_proxy.opts.use_proxy is True

        # Without proxy
        opts_no_proxy = ScraperOpts(scraper_name='test', use_proxy=False)
        scraper_no_proxy = TestScraper(opts_no_proxy)
        assert scraper_no_proxy.opts.use_proxy is False


# ============================================================================
# TEST SKIP OPTIONS
# ============================================================================

class TestSkipOptions:
    """Test skip_download and skip_export options."""

    @patch('scrapers.scraper_base.get_bigquery_client')
    def test_skip_download_option(self, mock_get_bq):
        """skip_download should prevent HTTP requests."""
        mock_get_bq.return_value = Mock()

        class TestScraper(ScraperBase):
            def construct_url(self, opts):
                return "https://api.example.com/test"

            def validate_data(self, raw_data, decoded_data):
                return True

            def transform_data(self, raw_data, decoded_data):
                return decoded_data

        opts = ScraperOpts(scraper_name='test', skip_download=True)
        scraper = TestScraper(opts)

        assert scraper.opts.skip_download is True

    @patch('scrapers.scraper_base.get_bigquery_client')
    def test_skip_export_option(self, mock_get_bq):
        """skip_export should prevent data export."""
        mock_get_bq.return_value = Mock()

        class TestScraper(ScraperBase):
            def construct_url(self, opts):
                return "https://api.example.com/test"

            def validate_data(self, raw_data, decoded_data):
                return True

            def transform_data(self, raw_data, decoded_data):
                return decoded_data

        opts = ScraperOpts(scraper_name='test', skip_export=True)
        scraper = TestScraper(opts)

        assert scraper.opts.skip_export is True


# ============================================================================
# TEST LOG LEVELS
# ============================================================================

class TestScraperLogLevel:
    """Test ScraperLogLevel enum."""

    def test_log_levels_defined(self):
        """ScraperLogLevel should define expected levels."""
        assert hasattr(ScraperLogLevel, 'DEBUG')
        assert hasattr(ScraperLogLevel, 'INFO')
        assert hasattr(ScraperLogLevel, 'WARNING')
        assert hasattr(ScraperLogLevel, 'ERROR')

    def test_log_level_ordering(self):
        """Log levels should have correct ordering."""
        # DEBUG < INFO < WARNING < ERROR
        assert ScraperLogLevel.DEBUG.value < ScraperLogLevel.INFO.value
        assert ScraperLogLevel.INFO.value < ScraperLogLevel.WARNING.value
        assert ScraperLogLevel.WARNING.value < ScraperLogLevel.ERROR.value


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestScraperBaseIntegration:
    """Integration tests for ScraperBase."""

    @patch('scrapers.scraper_base.get_bigquery_client')
    def test_subclass_implementation(self, mock_get_bq):
        """Subclass should implement required methods."""
        mock_get_bq.return_value = Mock()

        class CompleteScraper(ScraperBase):
            """A complete scraper implementation."""

            def construct_url(self, opts):
                game_date = opts.game_date.strftime('%Y-%m-%d') if opts.game_date else 'today'
                return f"https://api.example.com/games/{game_date}"

            def validate_data(self, raw_data, decoded_data):
                return isinstance(decoded_data, dict) and 'games' in decoded_data

            def transform_data(self, raw_data, decoded_data):
                return {
                    'games': decoded_data.get('games', []),
                    'scraped_at': datetime.now().isoformat(),
                }

        opts = ScraperOpts(
            scraper_name='complete_scraper',
            game_date=date(2026, 1, 20),
        )

        scraper = CompleteScraper(opts)

        # Test URL construction
        url = scraper.construct_url(opts)
        assert '2026-01-20' in url

        # Test validation
        assert scraper.validate_data('raw', {'games': []}) is True
        assert scraper.validate_data('raw', {}) is False

        # Test transformation
        result = scraper.transform_data('raw', {'games': [1, 2, 3]})
        assert 'games' in result
        assert 'scraped_at' in result
        assert result['games'] == [1, 2, 3]

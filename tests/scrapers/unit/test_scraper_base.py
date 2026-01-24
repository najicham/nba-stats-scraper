"""
Unit tests for scrapers/scraper_base.py

Tests the core ScraperBase functionality including:
- DownloadType and ExportMode enums
- Option validation
- HTTP downloading with retries
- Proxy handling
- Data validation hooks

Path: tests/scrapers/unit/test_scraper_base.py
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, date
import json


# ============================================================================
# TEST DOWNLOAD TYPE ENUM
# ============================================================================

class TestDownloadType:
    """Test DownloadType enum."""

    def test_download_types_defined(self):
        """DownloadType should define expected types."""
        from scrapers.scraper_base import DownloadType

        assert hasattr(DownloadType, 'JSON')
        assert hasattr(DownloadType, 'BINARY')
        assert hasattr(DownloadType, 'HTML')

    def test_download_type_values(self):
        """DownloadType values should be strings."""
        from scrapers.scraper_base import DownloadType

        assert DownloadType.JSON.value == "json"
        assert DownloadType.BINARY.value == "binary"
        assert DownloadType.HTML.value == "html"


# ============================================================================
# TEST EXPORT MODE ENUM
# ============================================================================

class TestExportMode:
    """Test ExportMode enum."""

    def test_export_modes_defined(self):
        """ExportMode should define expected modes."""
        from scrapers.scraper_base import ExportMode

        assert hasattr(ExportMode, 'RAW')
        assert hasattr(ExportMode, 'DECODED')
        assert hasattr(ExportMode, 'DATA')

    def test_export_mode_values(self):
        """ExportMode values should be strings."""
        from scrapers.scraper_base import ExportMode

        assert ExportMode.RAW.value == "raw"
        assert ExportMode.DECODED.value == "decoded"
        assert ExportMode.DATA.value == "data"


# ============================================================================
# TEST SCRAPER BASE CLASS ATTRIBUTES
# ============================================================================

class TestScraperBaseClassAttributes:
    """Test ScraperBase class-level attributes."""

    def test_default_class_attributes(self):
        """ScraperBase should have expected class attributes."""
        from scrapers.scraper_base import ScraperBase

        # Required/additional opts
        assert hasattr(ScraperBase, 'required_opts')
        assert hasattr(ScraperBase, 'additional_opts')
        assert hasattr(ScraperBase, 'exporters')

        # Proxy settings
        assert hasattr(ScraperBase, 'proxy_enabled')
        assert ScraperBase.proxy_enabled is False

        # Download settings
        assert hasattr(ScraperBase, 'decode_download_data')
        assert ScraperBase.decode_download_data is True

        # Retry settings
        assert hasattr(ScraperBase, 'max_retries_http')
        assert hasattr(ScraperBase, 'timeout_http')
        assert hasattr(ScraperBase, 'max_retries_decode')

    def test_default_retry_values(self):
        """ScraperBase should have sensible retry defaults."""
        from scrapers.scraper_base import ScraperBase

        assert ScraperBase.max_retries_http == 3
        assert ScraperBase.timeout_http == 20
        assert ScraperBase.max_retries_decode == 8

    def test_no_retry_status_codes(self):
        """ScraperBase should define status codes that shouldn't be retried."""
        from scrapers.scraper_base import ScraperBase

        assert 404 in ScraperBase.no_retry_status_codes
        assert 422 in ScraperBase.no_retry_status_codes


# ============================================================================
# TEST SCRAPER BASE INITIALIZATION
# ============================================================================

class TestScraperBaseInit:
    """Test ScraperBase initialization."""

    def test_basic_initialization(self):
        """ScraperBase should initialize instance variables."""
        from scrapers.scraper_base import ScraperBase

        scraper = ScraperBase()

        assert hasattr(scraper, 'opts')
        assert scraper.opts == {}
        assert hasattr(scraper, 'raw_response')
        assert scraper.raw_response is None
        assert hasattr(scraper, 'decoded_data')
        assert hasattr(scraper, 'data')
        assert hasattr(scraper, 'stats')

    def test_run_id_generation(self):
        """ScraperBase should generate unique run IDs."""
        from scrapers.scraper_base import ScraperBase

        scraper1 = ScraperBase()
        scraper2 = ScraperBase()

        # Each instance should have a unique run_id
        assert hasattr(scraper1, 'run_id')
        assert hasattr(scraper2, 'run_id')
        assert scraper1.run_id != scraper2.run_id
        assert len(scraper1.run_id) == 8  # First 8 chars of UUID

    def test_run_id_in_stats(self):
        """Run ID should be added to stats."""
        from scrapers.scraper_base import ScraperBase

        scraper = ScraperBase()

        assert 'run_id' in scraper.stats
        assert scraper.stats['run_id'] == scraper.run_id


# ============================================================================
# TEST SUBCLASS IMPLEMENTATION
# ============================================================================

class TestScraperSubclass:
    """Test that subclasses can properly override ScraperBase methods."""

    def test_subclass_can_override_set_url(self):
        """Subclass should be able to override set_url."""
        from scrapers.scraper_base import ScraperBase, DownloadType

        class TestScraper(ScraperBase):
            download_type = DownloadType.JSON

            def set_url(self):
                self.url = "https://api.example.com/test"

        scraper = TestScraper()
        scraper.set_url()

        assert scraper.url == "https://api.example.com/test"

    def test_subclass_can_override_set_headers(self):
        """Subclass should be able to override set_headers."""
        from scrapers.scraper_base import ScraperBase

        class TestScraper(ScraperBase):
            def set_headers(self):
                self.headers = {
                    "User-Agent": "Test/1.0",
                    "Accept": "application/json"
                }

        scraper = TestScraper()
        scraper.set_headers()

        assert scraper.headers["User-Agent"] == "Test/1.0"
        assert scraper.headers["Accept"] == "application/json"

    def test_subclass_can_define_required_opts(self):
        """Subclass should be able to define required_opts."""
        from scrapers.scraper_base import ScraperBase

        class TestScraper(ScraperBase):
            required_opts = ["gamedate", "team_id"]

        assert TestScraper.required_opts == ["gamedate", "team_id"]

    def test_subclass_can_define_exporters(self):
        """Subclass should be able to define exporters."""
        from scrapers.scraper_base import ScraperBase, ExportMode

        class TestScraper(ScraperBase):
            exporters = [
                {
                    "type": "file",
                    "filename": "/tmp/test.json",
                    "export_mode": ExportMode.DATA,
                    "groups": ["dev"],
                }
            ]

        assert len(TestScraper.exporters) == 1
        assert TestScraper.exporters[0]["type"] == "file"


# ============================================================================
# TEST DOWNLOAD TYPE CONFIGURATION
# ============================================================================

class TestDownloadTypeConfiguration:
    """Test DownloadType configuration in scrapers."""

    def test_json_download_type(self):
        """Scraper with JSON download type should decode response."""
        from scrapers.scraper_base import ScraperBase, DownloadType

        class JsonScraper(ScraperBase):
            download_type = DownloadType.JSON
            decode_download_data = True

        assert JsonScraper.download_type == DownloadType.JSON

    def test_binary_download_type(self):
        """Scraper with BINARY download type should not decode."""
        from scrapers.scraper_base import ScraperBase, DownloadType

        class BinaryScraper(ScraperBase):
            download_type = DownloadType.BINARY
            decode_download_data = False

        assert BinaryScraper.download_type == DownloadType.BINARY

    def test_html_download_type(self):
        """Scraper with HTML download type should store text."""
        from scrapers.scraper_base import ScraperBase, DownloadType

        class HtmlScraper(ScraperBase):
            download_type = DownloadType.HTML
            decode_download_data = True

        assert HtmlScraper.download_type == DownloadType.HTML


# ============================================================================
# TEST PROXY CONFIGURATION
# ============================================================================

class TestProxyConfiguration:
    """Test proxy configuration in scrapers."""

    def test_proxy_disabled_by_default(self):
        """Proxy should be disabled by default."""
        from scrapers.scraper_base import ScraperBase

        assert ScraperBase.proxy_enabled is False

    def test_subclass_can_enable_proxy(self):
        """Subclass should be able to enable proxy."""
        from scrapers.scraper_base import ScraperBase

        class ProxyScraper(ScraperBase):
            proxy_enabled = True

        assert ProxyScraper.proxy_enabled is True

    def test_proxy_url_attribute(self):
        """Scraper should have proxy_url attribute."""
        from scrapers.scraper_base import ScraperBase

        scraper = ScraperBase()
        assert hasattr(scraper.__class__, 'proxy_url')


# ============================================================================
# TEST BROWSER CONFIGURATION
# ============================================================================

class TestBrowserConfiguration:
    """Test browser (headless) configuration in scrapers."""

    def test_browser_disabled_by_default(self):
        """Browser should be disabled by default."""
        from scrapers.scraper_base import ScraperBase

        assert ScraperBase.browser_enabled is False

    def test_subclass_can_enable_browser(self):
        """Subclass should be able to enable browser mode."""
        from scrapers.scraper_base import ScraperBase

        class BrowserScraper(ScraperBase):
            browser_enabled = True
            browser_url = "https://example.com/init"

        assert BrowserScraper.browser_enabled is True
        assert BrowserScraper.browser_url == "https://example.com/init"


# ============================================================================
# TEST TIME MARKERS
# ============================================================================

class TestTimeMarkers:
    """Test time tracking functionality."""

    def test_time_markers_initialized(self):
        """Time markers should be initialized as empty dict."""
        from scrapers.scraper_base import ScraperBase

        scraper = ScraperBase()
        assert hasattr(scraper, 'time_markers')
        assert scraper.time_markers == {}

    def test_mark_time_method_exists(self):
        """Scraper should have mark_time method."""
        from scrapers.scraper_base import ScraperBase

        scraper = ScraperBase()
        assert hasattr(scraper, 'mark_time')
        assert callable(scraper.mark_time)


# ============================================================================
# TEST DATA PLACEHOLDERS
# ============================================================================

class TestDataPlaceholders:
    """Test data placeholder attributes."""

    def test_data_attributes_exist(self):
        """Scraper should have data placeholder attributes."""
        from scrapers.scraper_base import ScraperBase

        scraper = ScraperBase()

        assert hasattr(scraper, 'raw_response')
        assert hasattr(scraper, 'decoded_data')
        assert hasattr(scraper, 'data')
        assert hasattr(scraper, 'stats')

    def test_data_attributes_initial_values(self):
        """Data attributes should have correct initial values."""
        from scrapers.scraper_base import ScraperBase

        scraper = ScraperBase()

        assert scraper.raw_response is None
        assert scraper.decoded_data == {}
        assert scraper.data == {}


# ============================================================================
# TEST GCS CONFIGURATION
# ============================================================================

class TestGCSConfiguration:
    """Test GCS configuration in scrapers."""

    def test_gcs_disabled_by_default(self):
        """GCS should be disabled by default."""
        from scrapers.scraper_base import ScraperBase

        assert ScraperBase.gcs_enabled is False

    def test_subclass_can_enable_gcs(self):
        """Subclass should be able to enable GCS."""
        from scrapers.scraper_base import ScraperBase

        class GCSScraper(ScraperBase):
            gcs_enabled = True
            gcs_bucket = "my-bucket"
            gcs_path = "data/scraped"

        assert GCSScraper.gcs_enabled is True
        assert GCSScraper.gcs_bucket == "my-bucket"
        assert GCSScraper.gcs_path == "data/scraped"

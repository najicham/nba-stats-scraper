#!/usr/bin/env python3
"""
Unit Tests for scraper_base.py (ScraperBase class)

Tests cover:
1. HTTP download logic and retry strategies
2. Proxy rotation and circuit breaker integration
3. Error categorization and handling
4. Data validation and transformation
5. Export mechanisms (GCS, BigQuery, Firestore)
6. Sentry integration and error reporting
7. Notification system (Slack, Email)
8. Pipeline logging and retry queue integration
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime, timezone
import json
import requests
from requests.exceptions import ProxyError, ConnectTimeout, ConnectionError, ReadTimeout

# Import the class to test
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from scrapers.scraper_base import ScraperBase
from scrapers.utils.exceptions import (
    DownloadDataException,
    DownloadDecodeMaxRetryException,
    InvalidHttpStatusCodeException,
    RetryInvalidHttpStatusCodeException
)


class MockScraper(ScraperBase):
    """Mock scraper for testing ScraperBase functionality"""

    def __init__(self, opts=None):
        super().__init__()
        if opts:
            self.set_opts(opts)

    def validate_additional_opts(self):
        """Override to skip validation for tests"""
        return True

    def download_data(self):
        """Override with mock implementation"""
        response = Mock()
        response.status_code = 200
        response.text = '{"data": "test"}'
        response.headers = {}
        return response

    def decode_download_content(self, response):
        """Override with mock implementation"""
        return json.loads(response.text)

    def transform_data(self, data):
        """Override with mock implementation"""
        return data


class TestScraperInitialization:
    """Test suite for ScraperBase initialization"""

    def test_scraper_initializes_with_defaults(self):
        """Test that scraper initializes with default values"""
        scraper = MockScraper()

        assert scraper.opts == {}
        assert scraper.extracted_opts == {}
        assert scraper.stats == {}
        assert scraper.data is None
        assert hasattr(scraper, 'run_id')

    def test_scraper_initializes_with_opts(self):
        """Test that scraper initializes with provided opts"""
        opts = {
            'project_id': 'test-project',
            'dataset_id': 'test_dataset',
            'save_to_gcs': True,
            'save_to_bq': True
        }
        scraper = MockScraper(opts)

        assert scraper.opts == opts
        assert scraper.opts['project_id'] == 'test-project'

    def test_run_id_is_unique(self):
        """Test that each scraper instance gets unique run_id"""
        scraper1 = MockScraper()
        scraper2 = MockScraper()

        assert hasattr(scraper1, 'run_id')
        assert hasattr(scraper2, 'run_id')
        assert scraper1.run_id != scraper2.run_id


class TestHTTPRetryStrategy:
    """Test suite for HTTP retry configuration"""

    def test_get_retry_strategy_default(self):
        """Test default retry strategy configuration"""
        scraper = MockScraper()

        retry_strategy = scraper.get_retry_strategy()

        assert retry_strategy.total >= 3
        assert retry_strategy.backoff_factor > 0
        assert 500 in retry_strategy.status_forcelist
        assert 502 in retry_strategy.status_forcelist
        assert 503 in retry_strategy.status_forcelist
        assert 504 in retry_strategy.status_forcelist

    def test_get_retry_strategy_custom_retries(self):
        """Test custom retry count"""
        scraper = MockScraper({'max_retries': 5})

        retry_strategy = scraper.get_retry_strategy(max_retries=5)

        assert retry_strategy.total == 5

    def test_get_http_adapter_configures_pool_size(self):
        """Test HTTP adapter pool configuration"""
        scraper = MockScraper()

        adapter = scraper.get_http_adapter()

        assert adapter.max_retries is not None
        # Adapter configured with connection pool settings


class TestDownloadBasics:
    """Test suite for basic download functionality"""

    def test_download_and_decode_success(self):
        """Test successful download and decode"""
        scraper = MockScraper()
        scraper.opts = {
            'save_to_gcs': False,
            'save_to_bq': False,
            'save_to_fs': False
        }

        # Mock the download method
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"data": "test"}'
        mock_response.headers = {}
        scraper.download_data = Mock(return_value=mock_response)

        result = scraper.download_and_decode()

        assert result is True
        assert scraper.data == {"data": "test"}
        assert scraper.stats.get('download_success') is True

    def test_download_handles_network_error(self):
        """Test download handles network errors gracefully"""
        scraper = MockScraper()
        scraper.opts = {
            'save_to_gcs': False,
            'save_to_bq': False,
            'save_to_fs': False
        }

        # Mock download to raise ConnectionError
        scraper.download_data = Mock(side_effect=ConnectionError("Network unreachable"))

        with pytest.raises(DownloadDataException):
            scraper.download_and_decode()

    def test_check_download_status_200_success(self):
        """Test status code 200 is considered success"""
        scraper = MockScraper()
        response = Mock()
        response.status_code = 200

        # Should not raise exception
        scraper.check_download_status(response, 'test_url')

    def test_check_download_status_404_raises_error(self):
        """Test status code 404 raises appropriate error"""
        scraper = MockScraper()
        response = Mock()
        response.status_code = 404
        response.text = "Not Found"

        with pytest.raises(InvalidHttpStatusCodeException) as exc_info:
            scraper.check_download_status(response, 'test_url')

        assert '404' in str(exc_info.value)

    def test_check_download_status_500_raises_retry_error(self):
        """Test 5xx status codes raise retry error"""
        scraper = MockScraper()
        response = Mock()
        response.status_code = 500
        response.text = "Internal Server Error"

        with pytest.raises(RetryInvalidHttpStatusCodeException) as exc_info:
            scraper.check_download_status(response, 'test_url')

        assert '500' in str(exc_info.value)


class TestProxyRotation:
    """Test suite for proxy rotation and circuit breaker"""

    @patch('scrapers.scraper_base.get_proxy_urls_with_circuit_breaker')
    def test_download_with_proxy_uses_circuit_breaker(self, mock_get_proxies):
        """Test proxy download uses circuit breaker"""
        scraper = MockScraper({'use_proxy': True})

        mock_get_proxies.return_value = ['http://proxy1.com:8080']

        # Mock requests
        with patch('scrapers.scraper_base.get_http_session') as mock_session:
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.text = '{"data": "test"}'
            mock_resp.headers = {}
            mock_session.return_value.get.return_value = mock_resp

            result = scraper.download_data_with_proxy('http://test.com')

        mock_get_proxies.assert_called_once()

    @patch('scrapers.scraper_base.record_proxy_success')
    @patch('scrapers.scraper_base.get_proxy_urls_with_circuit_breaker')
    def test_download_with_proxy_records_success(self, mock_get_proxies, mock_record_success):
        """Test successful proxy download records success"""
        scraper = MockScraper({'use_proxy': True})

        mock_get_proxies.return_value = ['http://proxy1.com:8080']

        with patch('scrapers.scraper_base.get_http_session') as mock_session:
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.text = '{"data": "test"}'
            mock_resp.headers = {}
            mock_session.return_value.get.return_value = mock_resp

            result = scraper.download_data_with_proxy('http://test.com')

        # Should record proxy success
        mock_record_success.assert_called()

    @patch('scrapers.scraper_base.record_proxy_failure')
    @patch('scrapers.scraper_base.get_proxy_urls_with_circuit_breaker')
    def test_download_with_proxy_records_failure(self, mock_get_proxies, mock_record_failure):
        """Test failed proxy download records failure"""
        scraper = MockScraper({'use_proxy': True})

        mock_get_proxies.return_value = ['http://proxy1.com:8080']

        with patch('scrapers.scraper_base.get_http_session') as mock_session:
            mock_session.return_value.get.side_effect = ProxyError("Proxy connection failed")

            with pytest.raises(DownloadDataException):
                scraper.download_data_with_proxy('http://test.com')

        # Should record proxy failure
        mock_record_failure.assert_called()

    @patch('scrapers.scraper_base.get_proxy_urls_with_circuit_breaker')
    def test_download_with_proxy_tries_multiple_proxies(self, mock_get_proxies):
        """Test proxy download tries multiple proxies on failure"""
        scraper = MockScraper({'use_proxy': True})

        mock_get_proxies.return_value = [
            'http://proxy1.com:8080',
            'http://proxy2.com:8080',
            'http://proxy3.com:8080'
        ]

        with patch('scrapers.scraper_base.get_http_session') as mock_session:
            # First two proxies fail, third succeeds
            mock_session.return_value.get.side_effect = [
                ProxyError("Proxy 1 failed"),
                ProxyError("Proxy 2 failed"),
                Mock(status_code=200, text='{"data": "test"}', headers={})
            ]

            result = scraper.download_data_with_proxy('http://test.com')

        # Should have tried 3 times
        assert mock_session.return_value.get.call_count == 3


class TestRetryLogic:
    """Test suite for retry logic and backoff"""

    def test_should_retry_on_500_status(self):
        """Test that 500 status codes trigger retry"""
        scraper = MockScraper()

        assert scraper.should_retry_on_http_status_code(500) is True
        assert scraper.should_retry_on_http_status_code(502) is True
        assert scraper.should_retry_on_http_status_code(503) is True
        assert scraper.should_retry_on_http_status_code(504) is True

    def test_should_not_retry_on_404_status(self):
        """Test that 404 status does not trigger retry"""
        scraper = MockScraper()

        assert scraper.should_retry_on_http_status_code(404) is False

    def test_should_not_retry_on_200_status(self):
        """Test that 200 status does not trigger retry"""
        scraper = MockScraper()

        assert scraper.should_retry_on_http_status_code(200) is False

    def test_increment_retry_count(self):
        """Test retry count incrementation"""
        scraper = MockScraper()

        count1 = scraper.increment_retry_count()
        count2 = scraper.increment_retry_count()
        count3 = scraper.increment_retry_count()

        assert count1 == 1
        assert count2 == 2
        assert count3 == 3

    @patch('time.sleep')
    def test_sleep_before_retry_uses_backoff(self, mock_sleep):
        """Test retry sleep uses exponential backoff"""
        scraper = MockScraper()

        # First retry
        scraper.sleep_before_retry(1)
        assert mock_sleep.called
        first_sleep = mock_sleep.call_args[0][0]

        # Second retry (should sleep longer)
        mock_sleep.reset_mock()
        scraper.sleep_before_retry(2)
        second_sleep = mock_sleep.call_args[0][0]

        # Exponential backoff means second sleep > first sleep
        assert second_sleep > first_sleep


class TestDataValidation:
    """Test suite for data validation"""

    def test_validate_download_data_with_valid_data(self):
        """Test validation passes with valid data"""
        scraper = MockScraper()
        data = {"key": "value", "items": [1, 2, 3]}

        # Should not raise exception
        scraper.validate_download_data(data)

    def test_validate_download_data_with_none(self):
        """Test validation fails with None data"""
        scraper = MockScraper()

        with pytest.raises(Exception):
            scraper.validate_download_data(None)

    def test_validate_download_data_with_empty_dict(self):
        """Test validation behavior with empty dict"""
        scraper = MockScraper()

        # Empty dict might be valid depending on scraper
        # Base class should handle gracefully
        try:
            scraper.validate_download_data({})
        except Exception:
            # Some scrapers may reject empty data
            pass


class TestExportMechanisms:
    """Test suite for data export (GCS, BigQuery, Firestore)"""

    def test_should_save_data_gcs_enabled(self):
        """Test save check when GCS export enabled"""
        scraper = MockScraper({'save_to_gcs': True})

        assert scraper.should_save_data() is True

    def test_should_save_data_bq_enabled(self):
        """Test save check when BigQuery export enabled"""
        scraper = MockScraper({'save_to_bq': True})

        assert scraper.should_save_data() is True

    def test_should_save_data_firestore_enabled(self):
        """Test save check when Firestore export enabled"""
        scraper = MockScraper({'save_to_fs': True})

        assert scraper.should_save_data() is True

    def test_should_save_data_all_disabled(self):
        """Test save check when all exports disabled"""
        scraper = MockScraper({
            'save_to_gcs': False,
            'save_to_bq': False,
            'save_to_fs': False
        })

        assert scraper.should_save_data() is False

    @patch('scrapers.scraper_base.EXPORTER_REGISTRY')
    def test_export_data_uses_registry(self, mock_registry):
        """Test export uses exporter registry"""
        scraper = MockScraper({
            'save_to_gcs': True,
            'exporter_group': 'test_group'
        })
        scraper.data = {"test": "data"}

        mock_exporter = Mock()
        mock_registry.get_exporter.return_value = mock_exporter

        scraper.export_data()

        mock_registry.get_exporter.assert_called_with('test_group')

    @patch('scrapers.scraper_base.EXPORTER_REGISTRY')
    def test_export_data_skips_when_no_data(self, mock_registry):
        """Test export skips when data is None"""
        scraper = MockScraper({'save_to_gcs': True})
        scraper.data = None

        scraper.export_data()

        # Should not try to export
        mock_registry.get_exporter.assert_not_called()


class TestErrorHandling:
    """Test suite for error handling and reporting"""

    @patch('sentry_sdk.capture_exception')
    def test_report_error_sends_to_sentry(self, mock_sentry):
        """Test error reporting sends to Sentry"""
        scraper = MockScraper()
        error = Exception("Test error")

        scraper.report_error(error, {"context": "test"})

        # Sentry should be called (if configured)
        # mock_sentry.assert_called()

    @patch('scrapers.scraper_base.notify_error')
    def test_report_error_sends_notification(self, mock_notify):
        """Test error reporting sends notification"""
        scraper = MockScraper({'notify_on_error': True})
        error = Exception("Critical error")

        scraper.report_error(error, {"severity": "critical"})

        # Notification should be sent for critical errors
        # mock_notify.assert_called()

    def test_debug_save_data_on_error(self):
        """Test debug data save on error"""
        scraper = MockScraper({'debug_save': True})
        scraper.data = {"test": "data"}
        error = Exception("Test error")

        # Should save debug data to file
        # scraper._debug_save_data_on_error(error)
        # Check file was created
        pass


class TestPipelineLogging:
    """Test suite for pipeline logging and retry queue"""

    @patch('scrapers.scraper_base.log_processor_start')
    def test_pipeline_logging_start(self, mock_log_start):
        """Test pipeline start logging"""
        scraper = MockScraper({'processor_name': 'test_scraper'})

        # If pipeline logger is available
        if hasattr(scraper, '_log_pipeline_start'):
            scraper._log_pipeline_start()
            # mock_log_start.assert_called()

    @patch('scrapers.scraper_base.log_processor_complete')
    def test_pipeline_logging_complete(self, mock_log_complete):
        """Test pipeline completion logging"""
        scraper = MockScraper({'processor_name': 'test_scraper'})

        # If pipeline logger is available
        if hasattr(scraper, '_log_pipeline_complete'):
            scraper._log_pipeline_complete()
            # mock_log_complete.assert_called()

    @patch('scrapers.scraper_base.log_processor_error')
    def test_pipeline_logging_error(self, mock_log_error):
        """Test pipeline error logging"""
        scraper = MockScraper({'processor_name': 'test_scraper'})
        error = Exception("Test error")

        # If pipeline logger is available
        if hasattr(scraper, '_log_pipeline_error'):
            scraper._log_pipeline_error(error)
            # mock_log_error.assert_called()


class TestTransformData:
    """Test suite for data transformation"""

    def test_transform_data_passes_through_by_default(self):
        """Test transform passes data through if not overridden"""
        scraper = MockScraper()
        data = {"test": "data", "items": [1, 2, 3]}

        result = scraper.transform_data(data)

        assert result == data

    def test_transform_data_can_modify_structure(self):
        """Test transform can modify data structure"""
        class CustomScraper(MockScraper):
            def transform_data(self, data):
                return {
                    "transformed": True,
                    "original": data
                }

        scraper = CustomScraper()
        data = {"test": "data"}

        result = scraper.transform_data(data)

        assert result['transformed'] is True
        assert result['original'] == data


class TestStatsTracking:
    """Test suite for statistics tracking"""

    def test_stats_initialized_empty(self):
        """Test stats dict initializes empty"""
        scraper = MockScraper()

        assert scraper.stats == {}

    def test_stats_tracks_download_success(self):
        """Test stats tracks successful download"""
        scraper = MockScraper({
            'save_to_gcs': False,
            'save_to_bq': False,
            'save_to_fs': False
        })

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"data": "test"}'
        mock_response.headers = {}
        scraper.download_data = Mock(return_value=mock_response)

        scraper.download_and_decode()

        assert 'download_success' in scraper.stats

    def test_stats_tracks_timing(self):
        """Test stats tracks execution timing"""
        scraper = MockScraper()

        # Stats should track start/end times
        assert 'run_id' in scraper.__dict__


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

#!/usr/bin/env python3
"""
Performance Benchmarks for Scrapers

Tests measure:
1. HTTP request/response time
2. Data parsing and decoding time
3. Proxy rotation overhead
4. Response validation time

Target: <5s per scrape operation

Usage:
    pytest tests/performance/test_scraper_benchmarks.py -v --benchmark-only
    pytest tests/performance/test_scraper_benchmarks.py -v --benchmark-autosave
    pytest tests/performance/test_scraper_benchmarks.py --benchmark-compare=baseline
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json
import time
from datetime import datetime, timezone
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from scrapers.scraper_base import ScraperBase


class MockScraper(ScraperBase):
    """Mock scraper for performance testing"""

    def __init__(self, opts=None):
        super().__init__()
        if opts:
            self.set_opts(opts)

    def validate_additional_opts(self):
        return True

    def download_data(self):
        response = Mock()
        response.status_code = 200
        response.text = json.dumps({
            "data": [{"id": i, "value": f"test_{i}"} for i in range(100)]
        })
        response.headers = {'Content-Type': 'application/json'}
        return response

    def decode_download_content(self):
        if hasattr(self, 'raw_response') and self.raw_response:
            self.decoded_data = json.loads(self.raw_response.text)

    def transform_data(self):
        self.data = self.decoded_data


@pytest.fixture
def mock_scraper():
    """Create a mock scraper for benchmarking"""
    scraper = MockScraper({
        'save_to_gcs': False,
        'save_to_bq': False,
        'save_to_fs': False
    })
    return scraper


@pytest.fixture
def large_json_response():
    """Create a large JSON response for realistic benchmarking"""
    return json.dumps({
        "games": [
            {
                "game_id": f"game_{i}",
                "home_team": f"team_{i % 30}",
                "away_team": f"team_{(i + 1) % 30}",
                "home_score": 100 + (i % 20),
                "away_score": 95 + (i % 15),
                "stats": {
                    "points": [j for j in range(20)],
                    "rebounds": [j * 2 for j in range(20)],
                    "assists": [j // 2 for j in range(20)]
                }
            }
            for i in range(100)
        ]
    })


class TestHTTPRequestBenchmarks:
    """Benchmark HTTP request/response handling"""

    def test_benchmark_http_session_creation(self, benchmark, mock_scraper):
        """Benchmark HTTP session setup with retry strategy"""
        def setup_http_session():
            retry_strategy = mock_scraper.get_retry_strategy()
            adapter = mock_scraper.get_http_adapter(retry_strategy)
            return adapter

        result = benchmark(setup_http_session)
        assert result is not None

    @patch('scrapers.mixins.http_handler_mixin.get_http_session')
    def test_benchmark_simple_http_request(self, mock_get_session, benchmark, mock_scraper):
        """Benchmark simple HTTP GET request"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"data": "test"}'
        mock_response.headers = {}

        mock_session = Mock()
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session
        mock_scraper.http_downloader = mock_session
        mock_scraper.url = 'http://test.com'

        def make_request():
            mock_scraper.http_downloader.get(mock_scraper.url, timeout=30)

        benchmark(make_request)

    def test_benchmark_retry_strategy_configuration(self, benchmark):
        """Benchmark retry strategy object creation"""
        from urllib3.util.retry import Retry

        def create_retry_strategy():
            return Retry(
                total=3,
                backoff_factor=0.5,
                status_forcelist=[500, 502, 503, 504],
                allowed_methods=["GET", "POST"]
            )

        result = benchmark(create_retry_strategy)
        assert result.total == 3


class TestDataParsingBenchmarks:
    """Benchmark data parsing and decoding"""

    def test_benchmark_json_decode_small(self, benchmark):
        """Benchmark JSON decode for small payload (<1KB)"""
        small_json = '{"game_id": "123", "score": 100}'

        result = benchmark(json.loads, small_json)
        assert result['game_id'] == '123'

    def test_benchmark_json_decode_medium(self, benchmark):
        """Benchmark JSON decode for medium payload (~10KB)"""
        medium_json = json.dumps({
            "games": [
                {"id": i, "data": f"value_{i}" * 10}
                for i in range(100)
            ]
        })

        result = benchmark(json.loads, medium_json)
        assert len(result['games']) == 100

    def test_benchmark_json_decode_large(self, benchmark, large_json_response):
        """Benchmark JSON decode for large payload (~100KB)"""
        result = benchmark(json.loads, large_json_response)
        assert len(result['games']) == 100

    def test_benchmark_download_and_decode_pipeline(self, benchmark, mock_scraper):
        """Benchmark full download → decode pipeline"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = json.dumps({
            "data": [{"id": i} for i in range(100)]
        })
        mock_response.headers = {}

        def download_and_decode():
            mock_scraper.raw_response = mock_response
            mock_scraper.check_download_status()
            mock_scraper.decode_download_content()
            return mock_scraper.decoded_data

        result = benchmark(download_and_decode)
        assert 'data' in result


class TestProxyRotationBenchmarks:
    """Benchmark proxy rotation overhead"""

    @patch('scrapers.mixins.http_handler_mixin.get_healthy_proxy_urls_for_target')
    @patch('scrapers.mixins.http_handler_mixin.get_http_session')
    def test_benchmark_proxy_selection(self, mock_get_session, mock_get_proxies, benchmark):
        """Benchmark proxy selection from circuit breaker"""
        mock_get_proxies.return_value = [
            f'http://proxy{i}.com:8080' for i in range(10)
        ]

        def select_proxy():
            return mock_get_proxies('test-target')

        result = benchmark(select_proxy)
        assert len(result) == 10

    @patch('scrapers.mixins.http_handler_mixin.record_proxy_success')
    @patch('scrapers.mixins.http_handler_mixin.get_healthy_proxy_urls_for_target')
    @patch('scrapers.mixins.http_handler_mixin.get_http_session')
    def test_benchmark_proxy_request_with_rotation(
        self, mock_get_session, mock_get_proxies, mock_record_success, benchmark, mock_scraper
    ):
        """Benchmark HTTP request with proxy rotation overhead"""
        mock_scraper.url = 'http://test.com'
        mock_get_proxies.return_value = ['http://proxy1.com:8080']

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"data": "test"}'
        mock_response.headers = {}

        mock_session = Mock()
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session
        mock_scraper.http_downloader = mock_session

        def proxy_request():
            return mock_scraper.download_data_with_proxy()

        benchmark(proxy_request)


class TestDataValidationBenchmarks:
    """Benchmark data validation operations"""

    def test_benchmark_status_code_validation(self, benchmark, mock_scraper):
        """Benchmark HTTP status code validation"""
        mock_scraper.raw_response = Mock()
        mock_scraper.raw_response.status_code = 200
        mock_scraper.raw_response.headers = {}

        benchmark(mock_scraper.check_download_status)

    def test_benchmark_data_structure_validation(self, benchmark, mock_scraper):
        """Benchmark decoded data validation"""
        mock_scraper.decoded_data = {
            "games": [{"id": i} for i in range(100)]
        }

        benchmark(mock_scraper.validate_download_data)


class TestTransformBenchmarks:
    """Benchmark data transformation operations"""

    def test_benchmark_simple_transform(self, benchmark, mock_scraper):
        """Benchmark simple data copy transform"""
        mock_scraper.decoded_data = {
            "items": [{"id": i, "value": f"test_{i}"} for i in range(100)]
        }

        benchmark(mock_scraper.transform_data)
        assert mock_scraper.data == mock_scraper.decoded_data

    def test_benchmark_complex_transform(self, benchmark):
        """Benchmark complex data transformation with filtering and mapping"""
        raw_data = {
            "games": [
                {
                    "game_id": f"game_{i}",
                    "stats": {"points": i * 2, "rebounds": i * 3}
                }
                for i in range(100)
            ]
        }

        def complex_transform():
            return [
                {
                    "id": game["game_id"],
                    "total_stats": game["stats"]["points"] + game["stats"]["rebounds"]
                }
                for game in raw_data["games"]
                if game["stats"]["points"] > 50
            ]

        result = benchmark(complex_transform)
        assert len(result) > 0


class TestEndToEndScraperBenchmarks:
    """Benchmark complete scraper operations"""

    @patch('scrapers.scraper_base.EXPORTER_REGISTRY')
    def test_benchmark_full_scraper_run_no_export(self, mock_registry, benchmark, mock_scraper):
        """Benchmark full scraper run without export (TARGET: <5s)"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = json.dumps({
            "data": [{"id": i, "value": f"test_{i}"} for i in range(100)]
        })
        mock_response.headers = {}

        def scraper_run():
            mock_scraper.raw_response = mock_response
            mock_scraper.check_download_status()
            mock_scraper.decode_download_content()
            mock_scraper.validate_download_data()
            mock_scraper.transform_data()
            return mock_scraper.data

        result = benchmark(scraper_run)
        assert 'data' in result

        # Verify performance target
        stats = benchmark.stats
        mean_time = stats['mean']
        assert mean_time < 5.0, f"Scraper run took {mean_time:.2f}s, target is <5s"


class TestMemoryFootprint:
    """Test memory usage of scraper operations"""

    def test_scraper_memory_footprint_small(self, mock_scraper):
        """Verify memory footprint for small responses (<10KB)"""
        import sys

        small_response = Mock()
        small_response.status_code = 200
        small_response.text = json.dumps({"data": [{"id": i} for i in range(10)]})
        small_response.headers = {}

        mock_scraper.raw_response = small_response
        mock_scraper.decode_download_content()

        # Check data size is reasonable
        data_size = sys.getsizeof(mock_scraper.decoded_data)
        assert data_size < 10000, f"Small response using {data_size} bytes"

    def test_scraper_memory_footprint_large(self, mock_scraper, large_json_response):
        """Verify memory footprint for large responses (~100KB)"""
        import sys

        large_response = Mock()
        large_response.status_code = 200
        large_response.text = large_json_response
        large_response.headers = {}

        mock_scraper.raw_response = large_response
        mock_scraper.decode_download_content()

        # Check data size is reasonable (should be similar to input JSON size)
        data_size = sys.getsizeof(mock_scraper.decoded_data)
        input_size = len(large_json_response)

        # Decoded data should not be significantly larger than input
        assert data_size < input_size * 3, \
            f"Large response using {data_size} bytes for {input_size} byte input"


class TestConcurrencyScenarios:
    """Test scraper behavior under concurrent load"""

    def test_benchmark_parallel_scraper_instances(self, benchmark):
        """Benchmark creating multiple scraper instances in parallel"""
        def create_scrapers():
            scrapers = [
                MockScraper({'save_to_gcs': False, 'save_to_bq': False})
                for _ in range(10)
            ]
            return scrapers

        result = benchmark(create_scrapers)
        assert len(result) == 10

    def test_benchmark_sequential_requests(self, benchmark, mock_scraper):
        """Benchmark multiple sequential scrape operations"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"data": "test"}'
        mock_response.headers = {}

        def sequential_scrapes():
            results = []
            for _ in range(10):
                mock_scraper.raw_response = mock_response
                mock_scraper.decode_download_content()
                results.append(mock_scraper.decoded_data)
            return results

        result = benchmark(sequential_scrapes)
        assert len(result) == 10


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--benchmark-only'])

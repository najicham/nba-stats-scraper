# tests/performance/test_scraper_throughput.py
"""
Performance Tests for Scraper Throughput

Tests the performance of critical scraper operations:
1. HTTP request/response handling
2. JSON decoding speed
3. Data transformation throughput
4. Option validation overhead
5. Header generation speed

Run with:
    pytest test_scraper_throughput.py -v --benchmark-only
    pytest test_scraper_throughput.py -v --benchmark-columns=min,max,mean,stddev

To save and compare benchmarks:
    pytest test_scraper_throughput.py --benchmark-save=baseline
    pytest test_scraper_throughput.py --benchmark-compare=baseline
"""

import pytest
import json
import time
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any, List

# Import scraper components
from scrapers.scraper_base import ScraperBase, DownloadType, ExportMode


def _get_stats(benchmark):
    """Safely get benchmark stats, returns None if not available."""
    try:
        if hasattr(benchmark, 'stats') and hasattr(benchmark.stats, 'mean'):
            return benchmark.stats
    except Exception:
        pass
    return None


# =============================================================================
# Mock Scraper for Testing
# =============================================================================

class MockScraper(ScraperBase):
    """Mock scraper implementation for benchmarking."""

    required_opts = ['gamedate']
    additional_opts = ['season']
    exporters = []
    decode_download_data = True
    download_type = DownloadType.JSON

    def __init__(self):
        super().__init__()
        self.url = 'https://example.com/api'
        self._mock_response_data = None

    def set_url(self):
        """Set the URL for the request."""
        self.url = f"https://example.com/api?date={self.opts.get('gamedate')}"

    def set_headers(self):
        """Set headers for the request."""
        self.headers = {
            'Accept': 'application/json',
            'User-Agent': 'NBA-Stats-Scraper/1.0'
        }

    def validate_download_data(self):
        """Validate downloaded data."""
        return True

    def transform_data(self):
        """Transform data for export."""
        if isinstance(self.decoded_data, dict):
            self.data = self.decoded_data
        else:
            self.data = {'raw': self.decoded_data}


# =============================================================================
# JSON Decoding Performance
# =============================================================================

class TestJSONDecodingPerformance:
    """Test JSON decoding performance for various payload sizes."""

    @pytest.fixture
    def small_json_payload(self):
        """Generate small JSON payload (~1KB)."""
        return json.dumps({
            'players': [
                {'id': i, 'name': f'Player {i}', 'points': 20 + i}
                for i in range(10)
            ]
        })

    @pytest.fixture
    def medium_json_payload(self):
        """Generate medium JSON payload (~100KB)."""
        return json.dumps({
            'players': [
                {
                    'id': i,
                    'name': f'Player {i}',
                    'stats': {
                        'points': 20 + (i % 20),
                        'assists': 5 + (i % 10),
                        'rebounds': 7 + (i % 12),
                        'steals': 1 + (i % 3),
                        'blocks': i % 2,
                        'minutes': 30 + (i % 15),
                        'fg_made': 8 + (i % 6),
                        'fg_attempted': 15 + (i % 8),
                        'three_made': 2 + (i % 4),
                        'three_attempted': 6 + (i % 5)
                    },
                    'team': {'id': i % 30, 'name': f'Team {i % 30}'},
                    'games': [
                        {'date': f'2025-01-{(j % 28) + 1:02d}', 'points': 15 + j}
                        for j in range(10)
                    ]
                }
                for i in range(500)
            ]
        })

    @pytest.fixture
    def large_json_payload(self):
        """Generate large JSON payload (~1MB)."""
        return json.dumps({
            'resultSets': [
                {
                    'name': f'ResultSet{k}',
                    'headers': ['col1', 'col2', 'col3', 'col4', 'col5'],
                    'rowSet': [
                        [i, f'value_{i}', i * 1.5, i % 100, f'text_{i}']
                        for i in range(5000)
                    ]
                }
                for k in range(10)
            ]
        })

    def test_benchmark_small_json_decode(self, benchmark, small_json_payload):
        """Benchmark decoding small JSON payload."""
        result = benchmark(json.loads, small_json_payload)

        assert 'players' in result
        assert len(result['players']) == 10

        stats = _get_stats(benchmark)
        if stats:
            print(f"\nSmall JSON ({len(small_json_payload)} bytes): "
                  f"{stats.mean * 1000:.3f}ms")

    def test_benchmark_medium_json_decode(self, benchmark, medium_json_payload):
        """Benchmark decoding medium JSON payload."""
        result = benchmark(json.loads, medium_json_payload)

        assert 'players' in result
        assert len(result['players']) == 500

        stats = _get_stats(benchmark)
        if stats:
            print(f"\nMedium JSON ({len(medium_json_payload)} bytes): "
                  f"{stats.mean * 1000:.3f}ms")

    def test_benchmark_large_json_decode(self, benchmark, large_json_payload):
        """Benchmark decoding large JSON payload."""
        result = benchmark(json.loads, large_json_payload)

        assert 'resultSets' in result
        assert len(result['resultSets']) == 10

        stats = _get_stats(benchmark)
        if stats:
            print(f"\nLarge JSON ({len(large_json_payload)} bytes): "
                  f"{stats.mean * 1000:.3f}ms")


# =============================================================================
# Scraper Option Validation Performance
# =============================================================================

class TestOptionValidationPerformance:
    """Test option parsing and validation performance."""

    def test_benchmark_option_parsing(self, benchmark, sample_scraper_opts):
        """Benchmark option parsing overhead."""
        scraper = MockScraper()

        def parse_opts():
            scraper.opts = {}
            scraper.set_opts(sample_scraper_opts)
            return scraper.opts

        result = benchmark(parse_opts)

        assert 'gamedate' in result
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nOption parsing: {stats.mean * 1000:.3f}ms")

    def test_benchmark_option_validation(self, benchmark, sample_scraper_opts):
        """Benchmark option validation overhead."""
        scraper = MockScraper()
        scraper.set_opts(sample_scraper_opts)

        result = benchmark(scraper.validate_opts)

        stats = _get_stats(benchmark)
        if stats:
            print(f"\nOption validation: {stats.mean * 1000:.3f}ms")

    def test_benchmark_url_generation(self, benchmark, sample_scraper_opts):
        """Benchmark URL generation."""
        scraper = MockScraper()
        scraper.set_opts(sample_scraper_opts)

        result = benchmark(scraper.set_url)

        assert 'date=' in scraper.url
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nURL generation: {stats.mean * 1000:.3f}ms")

    def test_benchmark_header_generation(self, benchmark, sample_scraper_opts):
        """Benchmark header generation."""
        scraper = MockScraper()
        scraper.set_opts(sample_scraper_opts)

        result = benchmark(scraper.set_headers)

        assert 'Accept' in scraper.headers
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nHeader generation: {stats.mean * 1000:.3f}ms")


# =============================================================================
# Data Transformation Performance
# =============================================================================

class TestDataTransformationPerformance:
    """Test data transformation throughput."""

    @pytest.fixture
    def boxscore_data(self):
        """Generate realistic boxscore data for transformation tests."""
        return {
            'resultSets': [
                {
                    'name': 'PlayerStats',
                    'headers': [
                        'GAME_ID', 'TEAM_ID', 'PLAYER_ID', 'PLAYER_NAME',
                        'TEAM_ABBREVIATION', 'START_POSITION', 'MIN', 'FGM',
                        'FGA', 'FG_PCT', 'FG3M', 'FG3A', 'FG3_PCT', 'FTM',
                        'FTA', 'FT_PCT', 'OREB', 'DREB', 'REB', 'AST',
                        'STL', 'BLK', 'TO', 'PF', 'PTS', 'PLUS_MINUS'
                    ],
                    'rowSet': [
                        [
                            f'00224005{i:02d}', 1610612739 + (i % 30),
                            203507 + i, f'Player {i}', 'LAL', 'G' if i % 5 == 0 else '',
                            f'{30 + (i % 15)}:00', 8 + (i % 6), 15 + (i % 8),
                            0.45 + (i % 20) * 0.01, 2 + (i % 4), 6 + (i % 5),
                            0.35, 4 + (i % 5), 5 + (i % 4), 0.80,
                            2 + (i % 3), 5 + (i % 7), 7 + (i % 10),
                            5 + (i % 8), 1 + (i % 2), i % 3, 2 + (i % 3),
                            3 + (i % 4), 20 + (i % 15), (i % 30) - 15
                        ]
                        for i in range(450)  # ~450 players per game day
                    ]
                }
            ]
        }

    def test_benchmark_boxscore_transformation(self, benchmark, boxscore_data):
        """Benchmark transforming boxscore data."""
        def transform_boxscore():
            result_set = boxscore_data['resultSets'][0]
            headers = result_set['headers']
            rows = result_set['rowSet']

            # Transform to list of dicts (common pattern)
            transformed = []
            for row in rows:
                record = dict(zip(headers, row))
                # Add computed fields
                record['fg_pct_decimal'] = record['FG_PCT']
                record['is_starter'] = record['START_POSITION'] != ''
                transformed.append(record)

            return transformed

        result = benchmark(transform_boxscore)

        assert len(result) == 450
        assert 'fg_pct_decimal' in result[0]
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nBoxscore transformation (450 players): {stats.mean * 1000:.2f}ms")

    def test_benchmark_bulk_record_creation(self, benchmark, sample_player_rows, benchmark_config):
        """Benchmark bulk record creation."""
        rows = sample_player_rows(benchmark_config['medium_batch'])

        def create_records():
            records = []
            for row in rows:
                record = {
                    'player_id': row['player_lookup'],
                    'game_date': str(row['game_date']),
                    'points': row['points'],
                    'assists': row['assists'],
                    'rebounds': row['rebounds'],
                    'computed_per': (row['points'] + row['assists'] + row['rebounds']) / 3,
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }
                records.append(record)
            return records

        result = benchmark(create_records)

        assert len(result) == benchmark_config['medium_batch']
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nBulk record creation ({benchmark_config['medium_batch']} records): "
                  f"{stats.mean * 1000:.2f}ms")


# =============================================================================
# Hash Computation Performance (for Idempotency)
# =============================================================================

class TestHashComputationPerformance:
    """Test hash computation for smart idempotency."""

    def test_benchmark_single_record_hash(self, benchmark):
        """Benchmark hashing a single record."""
        import hashlib

        record = {
            'game_id': '0022400561',
            'player_lookup': 'lebron-james',
            'points': 25,
            'assists': 8,
            'rebounds': 7,
            'minutes_played': 35.5
        }

        def compute_hash():
            hash_fields = ['game_id', 'player_lookup', 'points', 'assists', 'rebounds']
            hash_string = '|'.join(str(record.get(f, '')) for f in hash_fields)
            return hashlib.md5(hash_string.encode()).hexdigest()[:16]

        result = benchmark(compute_hash)

        assert len(result) == 16
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nSingle record hash: {stats.mean * 1000000:.2f}us")

    def test_benchmark_batch_hash_computation(self, benchmark, sample_player_rows, benchmark_config):
        """Benchmark hashing a batch of records."""
        import hashlib

        rows = sample_player_rows(benchmark_config['medium_batch'])

        def compute_batch_hashes():
            hash_fields = ['player_lookup', 'points', 'assists', 'rebounds']
            hashes = []
            for record in rows:
                hash_string = '|'.join(str(record.get(f, '')) for f in hash_fields)
                hashes.append(hashlib.md5(hash_string.encode()).hexdigest()[:16])
            return hashes

        result = benchmark(compute_batch_hashes)

        assert len(result) == benchmark_config['medium_batch']
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nBatch hash ({benchmark_config['medium_batch']} records): "
                  f"{stats.mean * 1000:.2f}ms")


# =============================================================================
# End-to-End Scraper Lifecycle Performance
# =============================================================================

class TestScraperLifecyclePerformance:
    """Test end-to-end scraper lifecycle performance."""

    def test_benchmark_scraper_initialization(self, benchmark):
        """Benchmark scraper initialization."""
        result = benchmark(MockScraper)

        assert result.run_id is not None
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nScraper initialization: {stats.mean * 1000:.3f}ms")

    def test_benchmark_scraper_setup_phase(self, benchmark, sample_scraper_opts):
        """Benchmark scraper setup phase (opts, url, headers)."""
        def setup_scraper():
            scraper = MockScraper()
            scraper.set_opts(sample_scraper_opts)
            scraper.validate_opts()
            scraper.set_url()
            scraper.set_headers()
            return scraper

        result = benchmark(setup_scraper)

        assert result.url is not None
        assert result.headers is not None
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nScraper setup phase: {stats.mean * 1000:.3f}ms")


# =============================================================================
# Summary Test
# =============================================================================

def test_print_scraper_throughput_summary():
    """Print scraper throughput test summary."""
    print("\n" + "=" * 70)
    print("SCRAPER THROUGHPUT TEST SUMMARY")
    print("=" * 70)
    print("\nAll scraper throughput benchmarks completed!")
    print("Review the timing information above for performance metrics.")
    print("\nKey Performance Indicators:")
    print("  - JSON decode: < 10ms for typical payloads")
    print("  - Option validation: < 1ms")
    print("  - Record transformation: < 50ms for 450 records")
    print("  - Hash computation: < 10ms for 200 records")
    print("=" * 70)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--benchmark-only'])

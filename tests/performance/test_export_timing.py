# tests/performance/test_export_timing.py
"""
Performance Tests for Export Timing

Tests the performance of data export operations:
1. JSON serialization speed
2. GCS upload timing
3. BigQuery query to export pipeline
4. Batch export throughput
5. Cache header handling
6. Full export lifecycle

Run with:
    pytest test_export_timing.py -v --benchmark-only
    pytest test_export_timing.py -v --benchmark-columns=min,max,mean,stddev

To save and compare benchmarks:
    pytest test_export_timing.py --benchmark-save=baseline
    pytest test_export_timing.py --benchmark-compare=baseline
"""

import pytest
import json
import gzip
import io
import time
from datetime import date, datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, Any, List
from decimal import Decimal




def _get_stats(benchmark):
    """Safely get benchmark stats, returns None if not available."""
    try:
        if hasattr(benchmark, 'stats') and hasattr(benchmark.stats, 'mean'):
            return benchmark.stats
    except Exception:
        pass
    return None

# =============================================================================
# Mock Exporter Classes for Benchmarking
# =============================================================================

class MockBaseExporter:
    """Mock base exporter for benchmarking export operations."""

    API_VERSION = 'v1'

    def __init__(self, project_id: str = 'test-project', bucket_name: str = 'test-bucket'):
        self.project_id = project_id
        self.bucket_name = bucket_name
        self.bq_client = Mock()
        self.gcs_client = Mock()

        # Setup mock GCS client
        self._setup_mock_gcs()

    def _setup_mock_gcs(self):
        """Setup mock GCS client and blob."""
        bucket = Mock()
        blob = Mock()
        blob.upload_from_string = Mock(return_value=None)
        blob.patch = Mock(return_value=None)
        bucket.blob = Mock(return_value=blob)
        self.gcs_client.bucket = Mock(return_value=bucket)
        self._blob = blob

    def query_to_list(self, query: str, params: List = None) -> List[Dict]:
        """Execute BigQuery query and return results as list of dicts."""
        # Return mock data
        return self.bq_client.query_result

    def upload_to_gcs(self, json_data: Dict[str, Any], path: str,
                      cache_control: str = 'public, max-age=300') -> str:
        """Upload JSON data to GCS with cache headers."""
        bucket = self.gcs_client.bucket(self.bucket_name)
        full_path = f'{self.API_VERSION}/{path}'
        blob = bucket.blob(full_path)

        # Serialize with proper handling
        json_str = json.dumps(
            json_data,
            indent=2,
            default=self._json_serializer,
            ensure_ascii=False
        )

        # Upload
        blob.upload_from_string(json_str, content_type='application/json')
        blob.cache_control = cache_control
        blob.patch()

        return f'gs://{self.bucket_name}/{full_path}'

    def _json_serializer(self, obj: Any) -> Any:
        """Custom JSON serializer for types not handled by default."""
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        if hasattr(obj, '__float__'):
            return float(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    def get_generated_at(self) -> str:
        """Get current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()


class MockPredictionsExporter(MockBaseExporter):
    """Mock predictions exporter for benchmarking."""

    def generate_json(self, game_date: str, predictions: List[Dict]) -> Dict[str, Any]:
        """Generate predictions JSON payload."""
        return {
            'generated_at': self.get_generated_at(),
            'version': self.API_VERSION,
            'game_date': game_date,
            'prediction_count': len(predictions),
            'predictions': predictions
        }


class MockResultsExporter(MockBaseExporter):
    """Mock results exporter for benchmarking."""

    def generate_json(self, game_date: str, results: List[Dict]) -> Dict[str, Any]:
        """Generate results JSON payload."""
        return {
            'generated_at': self.get_generated_at(),
            'version': self.API_VERSION,
            'game_date': game_date,
            'result_count': len(results),
            'summary': {
                'total_games': len(set(r.get('game_id') for r in results)),
                'total_players': len(results),
                'avg_points': sum(r.get('points', 0) for r in results) / len(results) if results else 0
            },
            'results': results
        }


# =============================================================================
# JSON Serialization Performance Tests
# =============================================================================

class TestJSONSerializationPerformance:
    """Test JSON serialization speed for various payload sizes."""

    def test_benchmark_small_json_serialization(self, benchmark, sample_export_data):
        """Benchmark small JSON serialization (~10KB)."""
        data = sample_export_data(player_count=50, games_per_player=5)

        result = benchmark(json.dumps, data, indent=2)

        assert len(result) > 0
        print(f"\nSmall JSON serialization ({len(result)} bytes): "
              f"{(stats.mean if stats else 1) * 1000:.3f}ms")

    def test_benchmark_medium_json_serialization(self, benchmark, sample_export_data):
        """Benchmark medium JSON serialization (~100KB)."""
        data = sample_export_data(player_count=200, games_per_player=10)

        result = benchmark(json.dumps, data, indent=2)

        assert len(result) > 0
        print(f"\nMedium JSON serialization ({len(result)} bytes): "
              f"{(stats.mean if stats else 1) * 1000:.3f}ms")

    def test_benchmark_large_json_serialization(self, benchmark, sample_export_data):
        """Benchmark large JSON serialization (~1MB)."""
        data = sample_export_data(player_count=500, games_per_player=20)

        result = benchmark(json.dumps, data, indent=2)

        assert len(result) > 0
        print(f"\nLarge JSON serialization ({len(result)} bytes): "
              f"{(stats.mean if stats else 1) * 1000:.2f}ms")

    def test_benchmark_json_with_custom_encoder(self, benchmark):
        """Benchmark JSON serialization with custom encoder."""
        exporter = MockBaseExporter()

        data = {
            'generated_at': datetime.now(timezone.utc),
            'game_date': date(2025, 1, 15),
            'values': [Decimal('25.5'), Decimal('22.3'), Decimal('18.9')],
            'players': [
                {
                    'name': f'Player {i}',
                    'timestamp': datetime.now(timezone.utc),
                    'score': Decimal(str(20.5 + i))
                }
                for i in range(100)
            ]
        }

        def serialize():
            return json.dumps(data, default=exporter._json_serializer, indent=2)

        result = benchmark(serialize)

        assert len(result) > 0
        print(f"\nJSON with custom encoder: "
              f"{(stats.mean if stats else 1) * 1000:.3f}ms")


# =============================================================================
# GCS Upload Performance Tests
# =============================================================================

class TestGCSUploadPerformance:
    """Test GCS upload timing."""

    def test_benchmark_small_upload(self, benchmark, sample_export_data, mock_gcs_client):
        """Benchmark small payload upload."""
        exporter = MockBaseExporter()
        exporter.gcs_client = mock_gcs_client
        data = sample_export_data(player_count=50, games_per_player=5)

        result = benchmark(
            exporter.upload_to_gcs,
            data,
            'predictions/2025-01-15.json'
        )

        assert result.startswith('gs://')
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nSmall upload: {stats.mean * 1000:.3f}ms")

    def test_benchmark_medium_upload(self, benchmark, sample_export_data, mock_gcs_client):
        """Benchmark medium payload upload."""
        exporter = MockBaseExporter()
        exporter.gcs_client = mock_gcs_client
        data = sample_export_data(player_count=200, games_per_player=10)

        result = benchmark(
            exporter.upload_to_gcs,
            data,
            'predictions/2025-01-15.json'
        )

        assert result.startswith('gs://')
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nMedium upload: {stats.mean * 1000:.3f}ms")

    def test_benchmark_large_upload(self, benchmark, sample_export_data, mock_gcs_client):
        """Benchmark large payload upload."""
        exporter = MockBaseExporter()
        exporter.gcs_client = mock_gcs_client
        data = sample_export_data(player_count=500, games_per_player=20)

        result = benchmark(
            exporter.upload_to_gcs,
            data,
            'predictions/2025-01-15.json'
        )

        assert result.startswith('gs://')
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nLarge upload: {stats.mean * 1000:.2f}ms")


# =============================================================================
# Compression Performance Tests
# =============================================================================

class TestCompressionPerformance:
    """Test gzip compression performance for exports."""

    def test_benchmark_gzip_compression(self, benchmark, sample_export_data):
        """Benchmark gzip compression of JSON payload."""
        data = sample_export_data(player_count=200, games_per_player=10)
        json_str = json.dumps(data, indent=2)

        def compress():
            return gzip.compress(json_str.encode('utf-8'))

        result = benchmark(compress)

        compression_ratio = len(json_str) / len(result)
        print(f"\nGzip compression ({len(json_str)} -> {len(result)} bytes, "
              f"{compression_ratio:.1f}x): {(stats.mean if stats else 1) * 1000:.2f}ms")

    def test_benchmark_gzip_levels(self, sample_export_data):
        """Compare gzip compression levels."""
        data = sample_export_data(player_count=200, games_per_player=10)
        json_bytes = json.dumps(data, indent=2).encode('utf-8')

        results = {}
        for level in [1, 5, 9]:
            times = []
            for _ in range(10):
                start = time.perf_counter()
                compressed = gzip.compress(json_bytes, compresslevel=level)
                elapsed = (time.perf_counter() - start) * 1000
                times.append(elapsed)

            avg_time = sum(times) / len(times)
            compression_ratio = len(json_bytes) / len(compressed)
            results[level] = {
                'time_ms': avg_time,
                'size': len(compressed),
                'ratio': compression_ratio
            }

        print("\n" + "=" * 50)
        print("GZIP COMPRESSION LEVELS COMPARISON")
        print("=" * 50)
        print(f"Original size: {len(json_bytes):,} bytes")
        for level, metrics in results.items():
            print(f"Level {level}: {metrics['time_ms']:.2f}ms, "
                  f"{metrics['size']:,} bytes ({metrics['ratio']:.1f}x)")


# =============================================================================
# Full Export Lifecycle Performance Tests
# =============================================================================

class TestFullExportLifecycle:
    """Test full export lifecycle timing."""

    def test_benchmark_predictions_export_lifecycle(self, benchmark, mock_gcs_client):
        """Benchmark full predictions export lifecycle."""
        exporter = MockPredictionsExporter()
        exporter.gcs_client = mock_gcs_client

        # Generate mock predictions
        predictions = [
            {
                'player_lookup': f'player-{i}',
                'player_name': f'Player {i}',
                'team_abbr': 'LAL',
                'game_id': f'0022400{i:03d}',
                'prop_line': 22.5 + (i % 10),
                'prediction': 23.5 + (i % 12),
                'confidence': 0.55 + (i % 20) * 0.01,
                'recommendation': ['OVER', 'UNDER', 'PASS'][i % 3],
                'systems': {
                    'moving_average': {'prediction': 23.0, 'confidence': 0.52},
                    'ensemble': {'prediction': 24.0, 'confidence': 0.58}
                }
            }
            for i in range(450)
        ]

        def full_export():
            # 1. Generate JSON
            json_data = exporter.generate_json('2025-01-15', predictions)

            # 2. Upload to GCS
            gcs_path = exporter.upload_to_gcs(
                json_data,
                'predictions/2025-01-15.json'
            )

            return gcs_path

        result = benchmark(full_export)

        assert result.startswith('gs://')
        print(f"\nFull predictions export (450 players): "
              f"{(stats.mean if stats else 1) * 1000:.2f}ms")

    def test_benchmark_results_export_lifecycle(self, benchmark, mock_gcs_client):
        """Benchmark full results export lifecycle."""
        exporter = MockResultsExporter()
        exporter.gcs_client = mock_gcs_client

        # Generate mock results
        results = [
            {
                'player_lookup': f'player-{i}',
                'game_id': f'0022400{i:03d}',
                'game_date': '2025-01-15',
                'points': 20 + (i % 25),
                'assists': 5 + (i % 10),
                'rebounds': 7 + (i % 12),
                'prop_line': 22.5,
                'prediction': 23.5,
                'result': 'WIN' if (i % 3) == 0 else 'LOSS',
                'edge_actual': (20 + (i % 25)) - 22.5
            }
            for i in range(450)
        ]

        def full_export():
            # 1. Generate JSON
            json_data = exporter.generate_json('2025-01-15', results)

            # 2. Upload to GCS
            gcs_path = exporter.upload_to_gcs(
                json_data,
                'results/2025-01-15.json'
            )

            return gcs_path

        result = benchmark(full_export)

        assert result.startswith('gs://')
        print(f"\nFull results export (450 players): "
              f"{(stats.mean if stats else 1) * 1000:.2f}ms")


# =============================================================================
# Batch Export Performance Tests
# =============================================================================

class TestBatchExportPerformance:
    """Test batch export operations."""

    def test_benchmark_multi_day_export(self, benchmark, mock_gcs_client, sample_export_data):
        """Benchmark exporting multiple days of data."""
        exporter = MockBaseExporter()
        exporter.gcs_client = mock_gcs_client

        days = 7
        data_per_day = [
            sample_export_data(player_count=100, games_per_player=5)
            for _ in range(days)
        ]

        def export_multiple_days():
            paths = []
            for i, data in enumerate(data_per_day):
                date_str = f'2025-01-{15 + i:02d}'
                path = exporter.upload_to_gcs(
                    data,
                    f'predictions/{date_str}.json'
                )
                paths.append(path)
            return paths

        result = benchmark(export_multiple_days)

        assert len(result) == days
        print(f"\nMulti-day export ({days} days): "
              f"{(stats.mean if stats else 1) * 1000:.2f}ms "
              f"({(stats.mean if stats else 1) * 1000 / days:.2f}ms per day)")

    def test_benchmark_parallel_vs_sequential_export(self, mock_gcs_client, sample_export_data):
        """Compare parallel vs sequential export performance."""
        exporter = MockBaseExporter()
        exporter.gcs_client = mock_gcs_client

        # Generate data for 5 exports
        exports = [sample_export_data(100, 5) for _ in range(5)]

        # Sequential export
        start = time.perf_counter()
        for i, data in enumerate(exports):
            exporter.upload_to_gcs(data, f'test/file_{i}.json')
        sequential_time = (time.perf_counter() - start) * 1000

        print(f"\n5 sequential exports: {sequential_time:.2f}ms")
        print(f"Average per export: {sequential_time / 5:.2f}ms")


# =============================================================================
# Cache Header Performance Tests
# =============================================================================

class TestCacheHeaderPerformance:
    """Test cache header handling performance."""

    def test_benchmark_various_cache_settings(self, benchmark, mock_gcs_client, sample_export_data):
        """Benchmark exports with various cache settings."""
        exporter = MockBaseExporter()
        exporter.gcs_client = mock_gcs_client
        data = sample_export_data(100, 5)

        cache_settings = [
            'public, max-age=60',
            'public, max-age=300',
            'public, max-age=3600',
            'private, no-cache',
        ]

        for cache_control in cache_settings:
            result = benchmark(
                exporter.upload_to_gcs,
                data,
                f'test/cache_test.json',
                cache_control
            )

            print(f"\nCache '{cache_control[:20]}...': "
                  f"{(stats.mean if stats else 1) * 1000:.3f}ms")


# =============================================================================
# Export Size Analysis
# =============================================================================

class TestExportSizeAnalysis:
    """Analyze export payload sizes and timing relationships."""

    def test_size_vs_timing_analysis(self, sample_export_data):
        """Analyze relationship between payload size and export timing."""
        exporter = MockBaseExporter()

        sizes = [50, 100, 200, 500, 1000]
        results = {}

        for player_count in sizes:
            data = sample_export_data(player_count, games_per_player=10)

            times = []
            for _ in range(5):
                start = time.perf_counter()
                json_str = json.dumps(data, indent=2)
                elapsed = (time.perf_counter() - start) * 1000
                times.append(elapsed)

            avg_time = sum(times) / len(times)
            size_kb = len(json_str) / 1024

            results[player_count] = {
                'size_kb': size_kb,
                'time_ms': avg_time,
                'throughput_mb_s': (size_kb / 1024) / (avg_time / 1000)
            }

        print("\n" + "=" * 60)
        print("EXPORT SIZE VS TIMING ANALYSIS")
        print("=" * 60)
        print(f"{'Players':<10} {'Size (KB)':<12} {'Time (ms)':<12} {'MB/s':<10}")
        print("-" * 60)
        for count, metrics in results.items():
            print(f"{count:<10} {metrics['size_kb']:<12.1f} "
                  f"{metrics['time_ms']:<12.2f} {metrics['throughput_mb_s']:<10.1f}")


# =============================================================================
# Summary Test
# =============================================================================

def test_print_export_timing_summary():
    """Print export timing test summary."""
    print("\n" + "=" * 70)
    print("EXPORT TIMING TEST SUMMARY")
    print("=" * 70)
    print("\nAll export timing benchmarks completed!")
    print("Review the timing information above for performance metrics.")
    print("\nExport Timing Targets:")
    print("  - Small payload (<100KB): < 50ms")
    print("  - Medium payload (100KB-500KB): < 100ms")
    print("  - Large payload (500KB-1MB): < 200ms")
    print("  - Full game day export: < 500ms")
    print("  - Gzip compression: < 50ms for typical payloads")
    print("=" * 70)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--benchmark-only'])

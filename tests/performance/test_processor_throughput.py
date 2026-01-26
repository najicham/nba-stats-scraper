#!/usr/bin/env python3
"""
Processor Throughput Benchmarks

Tests measure:
1. Records processed per second
2. BigQuery write performance
3. Memory usage during processing
4. Batch processing efficiency

Target: Process 100+ games in <10 minutes

Usage:
    pytest tests/performance/test_processor_throughput.py -v --benchmark-only
    pytest tests/performance/test_processor_throughput.py -v --benchmark-autosave
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json
import time
from datetime import datetime, timezone
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from data_processors.raw.processor_base import ProcessorBase


class MockProcessor(ProcessorBase):
    """Mock processor for performance testing"""

    OUTPUT_TABLE = 'test_output'
    OUTPUT_DATASET = 'test_dataset'

    def __init__(self):
        super().__init__()
        self.raw_data = None
        self.transformed_data = None

    def load_data(self):
        """Simulate loading data"""
        self.raw_data = {
            "games": [
                {
                    "game_id": f"game_{i}",
                    "stats": {"points": i * 2, "rebounds": i * 3}
                }
                for i in range(100)
            ]
        }

    def transform_data(self):
        """Simulate transforming data"""
        self.transformed_data = [
            {
                "game_id": game["game_id"],
                "points": game["stats"]["points"],
                "rebounds": game["stats"]["rebounds"]
            }
            for game in self.raw_data["games"]
        ]


@pytest.fixture
def mock_processor():
    """Create a mock processor for benchmarking"""
    return MockProcessor()


@pytest.fixture
def large_dataset():
    """Create a large dataset for realistic benchmarking"""
    return [
        {
            "game_id": f"game_{i}",
            "date": f"2024-01-{(i % 28) + 1:02d}",
            "home_team": f"team_{i % 30}",
            "away_team": f"team_{(i + 1) % 30}",
            "stats": {
                "home_score": 100 + (i % 20),
                "away_score": 95 + (i % 15),
                "home_fg_pct": 0.45 + (i % 10) / 100,
                "away_fg_pct": 0.43 + (i % 12) / 100,
            }
        }
        for i in range(1000)
    ]


class TestDataLoadingBenchmarks:
    """Benchmark data loading operations"""

    @patch('data_processors.raw.processor_base.storage.Client')
    def test_benchmark_gcs_json_load_small(self, mock_storage, benchmark, mock_processor):
        """Benchmark loading small JSON from GCS (<10KB)"""
        mock_processor.set_opts({'project_id': 'test-project'})
        mock_processor.gcs_client = Mock()

        small_data = json.dumps({"games": [{"id": i} for i in range(10)]})

        mock_blob = Mock()
        mock_blob.exists.return_value = True
        mock_blob.download_as_string.return_value = small_data.encode()
        mock_bucket = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_processor.gcs_client.bucket.return_value = mock_bucket

        def load_from_gcs():
            return mock_processor.load_json_from_gcs(
                bucket='test-bucket',
                file_path='small.json'
            )

        result = benchmark(load_from_gcs)
        assert len(result['games']) == 10

    @patch('data_processors.raw.processor_base.storage.Client')
    def test_benchmark_gcs_json_load_large(self, mock_storage, benchmark, mock_processor):
        """Benchmark loading large JSON from GCS (~100KB)"""
        mock_processor.set_opts({'project_id': 'test-project'})
        mock_processor.gcs_client = Mock()

        large_data = json.dumps({
            "games": [
                {
                    "id": i,
                    "data": {"stats": [j for j in range(20)]}
                }
                for i in range(100)
            ]
        })

        mock_blob = Mock()
        mock_blob.exists.return_value = True
        mock_blob.download_as_string.return_value = large_data.encode()
        mock_bucket = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_processor.gcs_client.bucket.return_value = mock_bucket

        def load_from_gcs():
            return mock_processor.load_json_from_gcs(
                bucket='test-bucket',
                file_path='large.json'
            )

        result = benchmark(load_from_gcs)
        assert len(result['games']) == 100

    def test_benchmark_data_loading_method(self, benchmark, mock_processor):
        """Benchmark processor load_data method"""
        benchmark(mock_processor.load_data)
        assert mock_processor.raw_data is not None
        assert len(mock_processor.raw_data['games']) == 100


class TestDataTransformationBenchmarks:
    """Benchmark data transformation throughput"""

    def test_benchmark_transform_small_dataset(self, benchmark):
        """Benchmark transformation of 10 records"""
        raw_data = [
            {"game_id": f"game_{i}", "score": i * 10}
            for i in range(10)
        ]

        def transform():
            return [
                {"id": game["game_id"], "points": game["score"]}
                for game in raw_data
            ]

        result = benchmark(transform)
        assert len(result) == 10

    def test_benchmark_transform_medium_dataset(self, benchmark):
        """Benchmark transformation of 100 records"""
        raw_data = [
            {"game_id": f"game_{i}", "score": i * 10, "stats": {"a": i, "b": i * 2}}
            for i in range(100)
        ]

        def transform():
            return [
                {
                    "id": game["game_id"],
                    "points": game["score"],
                    "total": game["stats"]["a"] + game["stats"]["b"]
                }
                for game in raw_data
            ]

        result = benchmark(transform)
        assert len(result) == 100

    def test_benchmark_transform_large_dataset(self, benchmark, large_dataset):
        """Benchmark transformation of 1000 records"""
        def transform():
            return [
                {
                    "game_id": game["game_id"],
                    "date": game["date"],
                    "home_team": game["home_team"],
                    "away_team": game["away_team"],
                    "point_differential": (
                        game["stats"]["home_score"] - game["stats"]["away_score"]
                    ),
                    "fg_differential": (
                        game["stats"]["home_fg_pct"] - game["stats"]["away_fg_pct"]
                    )
                }
                for game in large_dataset
            ]

        result = benchmark(transform)
        assert len(result) == 1000

    def test_benchmark_processor_transform_method(self, benchmark, mock_processor):
        """Benchmark processor transform_data method"""
        mock_processor.load_data()
        benchmark(mock_processor.transform_data)
        assert len(mock_processor.transformed_data) == 100


class TestBigQueryWriteBenchmarks:
    """Benchmark BigQuery write operations"""

    @patch('data_processors.raw.processor_base.get_bigquery_client')
    def test_benchmark_bq_write_small_batch(self, mock_get_bq, benchmark, mock_processor):
        """Benchmark writing 10 rows to BigQuery"""
        mock_processor.set_opts({'project_id': 'test-project'})
        mock_processor.dataset_id = 'test_dataset'
        mock_processor.table_name = 'test_table'
        mock_processor.transformed_data = [
            {"game_id": f"game_{i}", "score": i * 10}
            for i in range(10)
        ]

        mock_bq_client = Mock()
        mock_table = Mock()
        mock_table.schema = []
        mock_bq_client.get_table.return_value = mock_table

        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.errors = None
        mock_bq_client.load_table_from_file.return_value = mock_job
        mock_processor.bq_client = mock_bq_client

        benchmark(mock_processor.save_data)
        assert mock_bq_client.load_table_from_file.called

    @patch('data_processors.raw.processor_base.get_bigquery_client')
    def test_benchmark_bq_write_medium_batch(self, mock_get_bq, benchmark, mock_processor):
        """Benchmark writing 100 rows to BigQuery"""
        mock_processor.set_opts({'project_id': 'test-project'})
        mock_processor.dataset_id = 'test_dataset'
        mock_processor.table_name = 'test_table'
        mock_processor.transformed_data = [
            {"game_id": f"game_{i}", "score": i * 10}
            for i in range(100)
        ]

        mock_bq_client = Mock()
        mock_table = Mock()
        mock_table.schema = []
        mock_bq_client.get_table.return_value = mock_table

        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.errors = None
        mock_bq_client.load_table_from_file.return_value = mock_job
        mock_processor.bq_client = mock_bq_client

        benchmark(mock_processor.save_data)
        assert mock_bq_client.load_table_from_file.called

    @patch('data_processors.raw.processor_base.get_bigquery_client')
    def test_benchmark_bq_write_large_batch(self, mock_get_bq, benchmark, mock_processor):
        """Benchmark writing 1000 rows to BigQuery"""
        mock_processor.set_opts({'project_id': 'test-project'})
        mock_processor.dataset_id = 'test_dataset'
        mock_processor.table_name = 'test_table'
        mock_processor.transformed_data = [
            {
                "game_id": f"game_{i}",
                "score": i * 10,
                "date": f"2024-01-{(i % 28) + 1:02d}"
            }
            for i in range(1000)
        ]

        mock_bq_client = Mock()
        mock_table = Mock()
        mock_table.schema = []
        mock_bq_client.get_table.return_value = mock_table

        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.errors = None
        mock_bq_client.load_table_from_file.return_value = mock_job
        mock_processor.bq_client = mock_bq_client

        benchmark(mock_processor.save_data)
        assert mock_bq_client.load_table_from_file.called


class TestThroughputMetrics:
    """Calculate records processed per second"""

    def test_records_per_second_small_batch(self, mock_processor):
        """Calculate throughput for 10 records"""
        mock_processor.raw_data = {
            "games": [{"game_id": f"game_{i}"} for i in range(10)]
        }

        start_time = time.time()
        mock_processor.transform_data()
        elapsed = time.time() - start_time

        records_per_second = 10 / elapsed if elapsed > 0 else 0
        assert records_per_second > 100, \
            f"Throughput: {records_per_second:.0f} records/sec (expected >100)"

    def test_records_per_second_medium_batch(self, mock_processor):
        """Calculate throughput for 100 records"""
        mock_processor.raw_data = {
            "games": [
                {"game_id": f"game_{i}", "stats": {"points": i}}
                for i in range(100)
            ]
        }

        start_time = time.time()
        mock_processor.transform_data()
        elapsed = time.time() - start_time

        records_per_second = 100 / elapsed if elapsed > 0 else 0
        assert records_per_second > 500, \
            f"Throughput: {records_per_second:.0f} records/sec (expected >500)"

    def test_records_per_second_large_batch(self, large_dataset):
        """Calculate throughput for 1000 records (TARGET: >1000 records/sec)"""
        def transform_large():
            return [
                {
                    "game_id": game["game_id"],
                    "point_diff": (
                        game["stats"]["home_score"] - game["stats"]["away_score"]
                    )
                }
                for game in large_dataset
            ]

        start_time = time.time()
        result = transform_large()
        elapsed = time.time() - start_time

        records_per_second = 1000 / elapsed if elapsed > 0 else 0
        assert records_per_second > 1000, \
            f"Throughput: {records_per_second:.0f} records/sec (expected >1000)"


class TestMemoryUsageProfiling:
    """Profile memory usage during processing"""

    def test_memory_usage_small_dataset(self, mock_processor):
        """Verify memory usage for 10 records"""
        import sys

        mock_processor.raw_data = {
            "games": [{"game_id": f"game_{i}"} for i in range(10)]
        }
        mock_processor.transform_data()

        # Check memory footprint
        data_size = sys.getsizeof(mock_processor.transformed_data)
        assert data_size < 10000, f"Small dataset using {data_size} bytes"

    def test_memory_usage_medium_dataset(self, mock_processor):
        """Verify memory usage for 100 records"""
        import sys

        mock_processor.raw_data = {
            "games": [
                {
                    "game_id": f"game_{i}",
                    "stats": {"points": i * 2, "rebounds": i * 3}
                }
                for i in range(100)
            ]
        }
        mock_processor.transform_data()

        # Check memory footprint
        data_size = sys.getsizeof(mock_processor.transformed_data)
        assert data_size < 100000, f"Medium dataset using {data_size} bytes"

    def test_memory_usage_large_dataset(self, large_dataset):
        """Verify memory usage for 1000 records (check for leaks)"""
        import sys

        def transform_and_measure():
            transformed = [
                {
                    "game_id": game["game_id"],
                    "date": game["date"],
                    "point_diff": (
                        game["stats"]["home_score"] - game["stats"]["away_score"]
                    )
                }
                for game in large_dataset
            ]
            return sys.getsizeof(transformed)

        data_size = transform_and_measure()
        # Should not exceed reasonable bounds
        assert data_size < 1000000, f"Large dataset using {data_size} bytes"


class TestEndToEndProcessorBenchmarks:
    """Benchmark complete processor runs"""

    @patch('data_processors.raw.processor_base.get_bigquery_client')
    def test_benchmark_full_processor_run(self, mock_get_bq, benchmark, mock_processor):
        """Benchmark full processor run: load → transform → save"""
        mock_processor.set_opts({'project_id': 'test-project'})
        mock_processor.dataset_id = 'test_dataset'
        mock_processor.table_name = 'test_table'

        mock_bq_client = Mock()
        mock_table = Mock()
        mock_table.schema = []
        mock_bq_client.get_table.return_value = mock_table

        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.errors = None
        mock_bq_client.load_table_from_file.return_value = mock_job
        mock_processor.bq_client = mock_bq_client

        def full_run():
            mock_processor.load_data()
            mock_processor.transform_data()
            mock_processor.save_data()

        benchmark(full_run)
        assert mock_processor.transformed_data is not None

    def test_100_games_processing_time(self, mock_processor):
        """Verify 100 games can be processed quickly (TARGET: <10 minutes for 100 games)"""
        mock_processor.raw_data = {
            "games": [
                {
                    "game_id": f"game_{i}",
                    "stats": {
                        "points": [j for j in range(20)],
                        "rebounds": [j * 2 for j in range(20)]
                    }
                }
                for i in range(100)
            ]
        }

        start_time = time.time()
        mock_processor.transform_data()
        elapsed = time.time() - start_time

        # For 100 games in memory, should be very fast (<1s)
        # Real BigQuery write would be slower, but still <10min target
        assert elapsed < 1.0, f"100 games took {elapsed:.2f}s (expected <1s for in-memory)"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--benchmark-only'])

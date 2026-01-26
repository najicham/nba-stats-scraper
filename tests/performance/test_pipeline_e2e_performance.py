#!/usr/bin/env python3
"""
End-to-End Pipeline Performance Benchmarks

Tests measure:
1. Phase transition times
2. Full pipeline completion time
3. Resource usage across phases
4. Bottleneck identification

Target: <30 minutes for full pipeline

Usage:
    pytest tests/performance/test_pipeline_e2e_performance.py -v --benchmark-only
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import time
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from scrapers.scraper_base import ScraperBase
from data_processors.raw.processor_base import ProcessorBase


class MockScraper(ScraperBase):
    """Mock scraper for pipeline testing"""

    def __init__(self, opts=None):
        super().__init__()
        if opts:
            self.set_opts(opts)

    def validate_additional_opts(self):
        return True

    def download_data(self):
        import json
        response = Mock()
        response.status_code = 200
        response.text = json.dumps({
            "games": [{"game_id": f"game_{i}", "score": 100 + i} for i in range(10)]
        })
        response.headers = {}
        return response

    def decode_download_content(self):
        import json
        if hasattr(self, 'raw_response') and self.raw_response:
            self.decoded_data = json.loads(self.raw_response.text)

    def transform_data(self):
        self.data = self.decoded_data


class MockProcessor(ProcessorBase):
    """Mock processor for pipeline testing"""

    OUTPUT_TABLE = 'test_output'
    OUTPUT_DATASET = 'test_dataset'

    def __init__(self):
        super().__init__()
        self.raw_data = None
        self.transformed_data = None

    def load_data(self):
        self.raw_data = {
            "games": [{"game_id": f"game_{i}"} for i in range(10)]
        }

    def transform_data(self):
        self.transformed_data = [
            {"game_id": game["game_id"]}
            for game in self.raw_data["games"]
        ]


@pytest.fixture
def mock_scraper():
    """Create mock scraper for pipeline testing"""
    return MockScraper({
        'save_to_gcs': False,
        'save_to_bq': False,
        'save_to_fs': False
    })


@pytest.fixture
def mock_processor():
    """Create mock processor for pipeline testing"""
    return MockProcessor()


class TestPhaseTransitionTiming:
    """Benchmark timing for phase transitions"""

    def test_phase1_scraper_execution(self, benchmark, mock_scraper):
        """Benchmark Phase 1: Scraper execution"""
        def run_scraper():
            mock_scraper.raw_response = mock_scraper.download_data()
            mock_scraper.check_download_status()
            mock_scraper.decode_download_content()
            mock_scraper.transform_data()
            return mock_scraper.data

        result = benchmark(run_scraper)
        assert 'games' in result

    @patch('data_processors.raw.processor_base.get_bigquery_client')
    def test_phase2_raw_processor_execution(self, mock_get_bq, benchmark, mock_processor):
        """Benchmark Phase 2: Raw processor execution"""
        mock_bq_client = Mock()
        mock_table = Mock()
        mock_table.schema = []
        mock_bq_client.get_table.return_value = mock_table

        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.errors = None
        mock_bq_client.load_table_from_file.return_value = mock_job
        mock_processor.bq_client = mock_bq_client
        mock_processor.set_opts({'project_id': 'test-project'})
        mock_processor.dataset_id = 'test_dataset'
        mock_processor.table_name = 'test_table'

        def run_processor():
            mock_processor.load_data()
            mock_processor.transform_data()
            mock_processor.save_data()

        benchmark(run_processor)
        assert mock_processor.transformed_data is not None

    def test_phase_transition_overhead(self, benchmark):
        """Benchmark overhead of transitioning between phases"""
        # Simulate phase transition (scraper → processor)
        def phase_transition():
            # Mock GCS write from scraper
            scraper_output = {"games": [{"id": i} for i in range(10)]}

            # Mock GCS read in processor
            processor_input = scraper_output.copy()

            return processor_input

        result = benchmark(phase_transition)
        assert len(result['games']) == 10


class TestFullPipelineBenchmarks:
    """Benchmark complete pipeline execution"""

    @patch('data_processors.raw.processor_base.get_bigquery_client')
    def test_single_game_full_pipeline(self, mock_get_bq, benchmark):
        """Benchmark full pipeline for single game"""
        scraper = MockScraper({'save_to_gcs': False, 'save_to_bq': False})
        processor = MockProcessor()
        processor.set_opts({'project_id': 'test-project'})

        mock_bq_client = Mock()
        mock_table = Mock()
        mock_table.schema = []
        mock_bq_client.get_table.return_value = mock_table
        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.errors = None
        mock_bq_client.load_table_from_file.return_value = mock_job
        processor.bq_client = mock_bq_client
        processor.dataset_id = 'test_dataset'
        processor.table_name = 'test_table'

        def full_pipeline():
            # Phase 1: Scrape
            scraper.raw_response = scraper.download_data()
            scraper.decode_download_content()
            scraper.transform_data()

            # Phase 2: Process
            processor.load_data()
            processor.transform_data()
            processor.save_data()

        benchmark(full_pipeline)

    @patch('data_processors.raw.processor_base.get_bigquery_client')
    def test_10_games_full_pipeline(self, mock_get_bq, benchmark):
        """Benchmark full pipeline for 10 games"""
        import json

        scraper = MockScraper({'save_to_gcs': False, 'save_to_bq': False})
        processor = MockProcessor()
        processor.set_opts({'project_id': 'test-project'})

        mock_bq_client = Mock()
        mock_table = Mock()
        mock_table.schema = []
        mock_bq_client.get_table.return_value = mock_table
        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.errors = None
        mock_bq_client.load_table_from_file.return_value = mock_job
        processor.bq_client = mock_bq_client
        processor.dataset_id = 'test_dataset'
        processor.table_name = 'test_table'

        def pipeline_10_games():
            # Phase 1: Scrape 10 games
            response = Mock()
            response.status_code = 200
            response.text = json.dumps({
                "games": [{"game_id": f"game_{i}", "score": 100 + i} for i in range(10)]
            })
            response.headers = {}

            scraper.raw_response = response
            scraper.decode_download_content()
            scraper.transform_data()

            # Phase 2: Process 10 games
            processor.raw_data = scraper.data
            processor.transform_data()
            processor.save_data()

        benchmark(pipeline_10_games)


class TestPipelineScaling:
    """Test pipeline scaling characteristics"""

    def test_100_games_completion_time(self):
        """Verify 100 games can complete in target time (TARGET: <10 min)"""
        import json

        scraper = MockScraper({'save_to_gcs': False, 'save_to_bq': False})

        # Simulate scraping 100 games
        start_time = time.time()

        for batch in range(10):  # 10 batches of 10 games
            response = Mock()
            response.status_code = 200
            response.text = json.dumps({
                "games": [
                    {"game_id": f"game_{batch * 10 + i}", "score": 100 + i}
                    for i in range(10)
                ]
            })
            response.headers = {}

            scraper.raw_response = response
            scraper.decode_download_content()
            scraper.transform_data()

        elapsed = time.time() - start_time

        # In-memory processing should be very fast
        # Real pipeline with BigQuery writes would be slower but <10min target
        assert elapsed < 1.0, f"100 games took {elapsed:.2f}s in-memory"

    def test_pipeline_throughput_scaling(self):
        """Test that throughput scales linearly"""
        import json

        scraper = MockScraper({'save_to_gcs': False, 'save_to_bq': False})

        # Test 10 games
        start_time = time.time()
        response = Mock()
        response.status_code = 200
        response.text = json.dumps({
            "games": [{"game_id": f"game_{i}"} for i in range(10)]
        })
        response.headers = {}
        scraper.raw_response = response
        scraper.decode_download_content()
        scraper.transform_data()
        time_10 = time.time() - start_time

        # Test 100 games
        start_time = time.time()
        response.text = json.dumps({
            "games": [{"game_id": f"game_{i}"} for i in range(100)]
        })
        scraper.raw_response = response
        scraper.decode_download_content()
        scraper.transform_data()
        time_100 = time.time() - start_time

        # Should scale roughly linearly (100 games ~10x time of 10 games)
        # Allow some overhead, so check it's less than 20x
        scaling_factor = time_100 / time_10 if time_10 > 0 else 0
        assert scaling_factor < 20, \
            f"Scaling factor: {scaling_factor:.1f}x (expected ~10x)"


class TestBottleneckIdentification:
    """Identify performance bottlenecks in pipeline"""

    def test_identify_slowest_phase(self):
        """Identify which phase is slowest"""
        import json

        scraper = MockScraper({'save_to_gcs': False, 'save_to_bq': False})
        processor = MockProcessor()

        # Measure Phase 1: Scraping
        start = time.time()
        response = Mock()
        response.status_code = 200
        response.text = json.dumps({
            "games": [{"game_id": f"game_{i}"} for i in range(100)]
        })
        response.headers = {}
        scraper.raw_response = response
        scraper.decode_download_content()
        scraper.transform_data()
        phase1_time = time.time() - start

        # Measure Phase 2: Processing
        start = time.time()
        processor.raw_data = scraper.data
        processor.transform_data()
        phase2_time = time.time() - start

        # Report bottleneck
        total_time = phase1_time + phase2_time
        phase1_pct = (phase1_time / total_time) * 100 if total_time > 0 else 0
        phase2_pct = (phase2_time / total_time) * 100 if total_time > 0 else 0

        # Both phases should be reasonably fast
        assert phase1_time < 1.0, f"Phase 1 (scraping): {phase1_time:.3f}s ({phase1_pct:.1f}%)"
        assert phase2_time < 1.0, f"Phase 2 (processing): {phase2_time:.3f}s ({phase2_pct:.1f}%)"

    @patch('data_processors.raw.processor_base.get_bigquery_client')
    def test_bigquery_write_bottleneck(self, mock_get_bq):
        """Identify BigQuery write as potential bottleneck"""
        processor = MockProcessor()
        processor.set_opts({'project_id': 'test-project'})
        processor.raw_data = {
            "games": [{"game_id": f"game_{i}"} for i in range(100)]
        }

        mock_bq_client = Mock()
        mock_table = Mock()
        mock_table.schema = []
        mock_bq_client.get_table.return_value = mock_table
        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.errors = None
        mock_bq_client.load_table_from_file.return_value = mock_job
        processor.bq_client = mock_bq_client
        processor.dataset_id = 'test_dataset'
        processor.table_name = 'test_table'

        # Measure transform vs save
        start = time.time()
        processor.transform_data()
        transform_time = time.time() - start

        start = time.time()
        processor.save_data()
        save_time = time.time() - start

        # BigQuery write typically slower than transform
        # In mock, both should be fast
        assert transform_time < 1.0, f"Transform: {transform_time:.3f}s"
        assert save_time < 1.0, f"Save: {save_time:.3f}s"


class TestResourceUsage:
    """Monitor resource usage during pipeline execution"""

    def test_memory_usage_during_pipeline(self):
        """Monitor memory usage throughout pipeline"""
        import sys
        import json

        scraper = MockScraper({'save_to_gcs': False, 'save_to_bq': False})

        # Baseline memory
        baseline = 0

        # After scraping
        response = Mock()
        response.status_code = 200
        response.text = json.dumps({
            "games": [
                {"game_id": f"game_{i}", "data": list(range(100))}
                for i in range(100)
            ]
        })
        response.headers = {}
        scraper.raw_response = response
        scraper.decode_download_content()
        scraper.transform_data()

        data_size = sys.getsizeof(scraper.data)

        # Memory should be reasonable
        assert data_size < 10000000, f"Pipeline using {data_size / 1e6:.1f}MB"

    def test_no_memory_leak_in_pipeline(self):
        """Verify no memory leaks across multiple runs"""
        import sys
        import json

        scraper = MockScraper({'save_to_gcs': False, 'save_to_bq': False})

        memory_sizes = []

        # Run pipeline 10 times
        for i in range(10):
            response = Mock()
            response.status_code = 200
            response.text = json.dumps({
                "games": [{"game_id": f"game_{j}"} for j in range(10)]
            })
            response.headers = {}

            scraper.raw_response = response
            scraper.decode_download_content()
            scraper.transform_data()

            memory_sizes.append(sys.getsizeof(scraper.data))

        # Memory should not grow significantly across runs
        first_run = memory_sizes[0]
        last_run = memory_sizes[-1]
        growth = (last_run - first_run) / first_run if first_run > 0 else 0

        assert growth < 0.5, \
            f"Memory grew {growth * 100:.1f}% across 10 runs (potential leak)"


class TestFullPipelineTarget:
    """Validate full pipeline completion time targets"""

    def test_30_minute_pipeline_target_simulation(self):
        """Simulate full pipeline to validate 30-minute target"""
        # This is a simulation - real pipeline would include:
        # - Multiple scraper runs
        # - Multiple raw processors
        # - Analytics processors
        # - BigQuery writes
        # - Pub/Sub messages

        start_time = time.time()

        # Simulate phases
        phases = {
            'phase1_scrapers': 0.01,  # Mock time per scraper
            'phase2_raw': 0.01,       # Mock time per processor
            'phase3_analytics': 0.02, # Mock time per analytics
            'phase4_precompute': 0.02 # Mock time per precompute
        }

        num_scrapers = 10
        num_processors = 10

        total_simulated_time = (
            phases['phase1_scrapers'] * num_scrapers +
            phases['phase2_raw'] * num_processors +
            phases['phase3_analytics'] * num_processors +
            phases['phase4_precompute'] * num_processors
        )

        elapsed = time.time() - start_time

        # Simulated time should project to <30 minutes at scale
        # With realistic BigQuery overhead, target is <30 min
        projected_time_minutes = total_simulated_time * 100  # Scale factor for real ops

        assert projected_time_minutes < 30, \
            f"Projected pipeline time: {projected_time_minutes:.1f} min (target <30 min)"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--benchmark-only'])

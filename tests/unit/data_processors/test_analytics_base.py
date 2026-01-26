#!/usr/bin/env python3
"""
Unit Tests for data_processors/analytics/analytics_base.py

Tests cover:
1. Initialization
2. Option handling (set_opts, validate_opts)
3. Client initialization
4. Data extraction lifecycle
5. Stats tracking
6. Error handling
7. Run history tracking
8. Dependency checking
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from datetime import datetime, date
from google.cloud import bigquery
from google.api_core.exceptions import NotFound, BadRequest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from data_processors.analytics.analytics_base import AnalyticsProcessorBase


# ============================================================================
# Test Fixture - Concrete Implementation
# ============================================================================

class ConcreteAnalyticsProcessor(AnalyticsProcessorBase):
    """Concrete implementation for testing."""

    table_name = "test_analytics_table"
    required_opts = ['start_date', 'end_date']
    additional_opts = ['season']

    def extract_raw_data(self):
        """Override abstract method."""
        self.raw_data = {'test': 'data'}

    def calculate_analytics(self):
        """Override abstract method."""
        self.transformed_data = [{'metric': 'value'}]


# ============================================================================
# Test Initialization
# ============================================================================

class TestAnalyticsInitialization:
    """Test suite for analytics processor initialization"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_processor_initializes_with_defaults(self, mock_project, mock_dataset, mock_bq):
        """Test processor initializes with default values"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.project_id == 'test-project'
        assert processor.dataset_id == 'analytics_dataset'
        assert processor.run_id is not None
        assert processor.stats == {'run_id': processor.run_id}
        assert processor.raw_data is None  # ✅ Initialized as None
        assert processor.validated_data == {}
        assert processor.transformed_data == {}  # ✅ Dict, not list

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_run_id_is_unique(self, mock_project, mock_dataset, mock_bq):
        """Test each processor instance gets unique run_id"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor1 = ConcreteAnalyticsProcessor()
        processor2 = ConcreteAnalyticsProcessor()

        assert processor1.run_id != processor2.run_id

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_phase_and_step_prefix_set(self, mock_project, mock_dataset, mock_bq):
        """Test phase and step prefix are set correctly"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.PHASE == 'phase_3_analytics'
        assert processor.STEP_PREFIX == 'ANALYTICS_STEP'


# ============================================================================
# Test Option Handling
# ============================================================================

class TestOptionHandling:
    """Test suite for option setting and validation"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_set_opts_stores_options(self, mock_project, mock_dataset, mock_bq):
        """Test set_opts stores options correctly"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        opts = {
            'start_date': '2024-01-01',
            'end_date': '2024-01-31',
            'season': '2023-24'
        }

        processor.set_opts(opts)

        assert processor.opts == opts
        assert processor.opts['start_date'] == '2024-01-01'
        assert processor.opts['end_date'] == '2024-01-31'

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_validate_opts_requires_start_date(self, mock_project, mock_dataset, mock_bq):
        """Test validate_opts raises error when start_date missing"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.set_opts({'end_date': '2024-01-31'})

        with pytest.raises(ValueError, match="start_date"):
            processor.validate_opts()

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_validate_opts_requires_end_date(self, mock_project, mock_dataset, mock_bq):
        """Test validate_opts raises error when end_date missing"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.set_opts({'start_date': '2024-01-01'})

        with pytest.raises(ValueError, match="end_date"):
            processor.validate_opts()

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_validate_opts_passes_with_all_required(self, mock_project, mock_dataset, mock_bq):
        """Test validate_opts passes when all required opts present"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.set_opts({
            'start_date': '2024-01-01',
            'end_date': '2024-01-31'
        })

        # Should not raise
        processor.validate_opts()


# ============================================================================
# Test Client Initialization
# ============================================================================

class TestClientInitialization:
    """Test suite for BigQuery client initialization"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_init_clients_sets_up_bigquery_client(self, mock_project, mock_dataset, mock_bq):
        """Test init_clients sets up BigQuery client"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_client = Mock()
        mock_bq.return_value = mock_client

        processor = ConcreteAnalyticsProcessor()
        processor.init_clients()

        # Client should already be set in __init__
        assert processor.bq_client is not None

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    @patch.dict(os.environ, {'GCP_PROJECT_ID': 'test-project-123'})
    def test_project_id_set_from_environment(self, mock_project, mock_dataset, mock_bq):
        """Test project_id is set from environment or config"""
        mock_project.return_value = 'fallback-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        # Should use environment variable first
        assert processor.project_id == 'test-project-123'


# ============================================================================
# Test Data Extraction Lifecycle
# ============================================================================

class TestDataExtractionLifecycle:
    """Test suite for data extraction and processing"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_extract_raw_data_populates_raw_data(self, mock_project, mock_dataset, mock_bq):
        """Test extract_raw_data populates raw_data dict"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        # Verify initial state
        assert processor.raw_data is None  # ✅ Initialized as None

        # Extract data
        processor.extract_raw_data()

        # Verify data populated
        assert processor.raw_data == {'test': 'data'}

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_calculate_analytics_populates_transformed_data(self, mock_project, mock_dataset, mock_bq):
        """Test calculate_analytics populates transformed_data list"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        # Verify initial state
        assert processor.transformed_data == {}  # ✅ Initialized as Dict

        # Calculate analytics
        processor.calculate_analytics()

        # Verify data populated (test implementation sets list)
        assert len(processor.transformed_data) == 1
        assert processor.transformed_data[0] == {'metric': 'value'}


# ============================================================================
# Test Stats Tracking
# ============================================================================

class TestStatsTracking:
    """Test suite for statistics tracking"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_stats_initialized_with_run_id(self, mock_project, mock_dataset, mock_bq):
        """Test stats dict initialized with run_id"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert 'run_id' in processor.stats
        assert processor.stats['run_id'] == processor.run_id

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_get_analytics_stats_returns_dict(self, mock_project, mock_dataset, mock_bq):
        """Test get_analytics_stats returns stats dictionary"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        stats = processor.get_analytics_stats()

        # Base implementation returns empty dict (child classes override)
        assert isinstance(stats, dict)
        assert stats == {}


# ============================================================================
# Test Time Tracking
# ============================================================================

class TestTimeTracking:
    """Test suite for time marker tracking"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_mark_time_creates_marker(self, mock_project, mock_dataset, mock_bq):
        """Test mark_time creates time marker"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        result = processor.mark_time("extraction")

        # First call returns "0.0"
        assert result == "0.0"
        assert "extraction" in processor.time_markers
        # Marker is dict with 'start' and 'last' keys
        assert isinstance(processor.time_markers["extraction"], dict)
        assert "start" in processor.time_markers["extraction"]
        assert "last" in processor.time_markers["extraction"]

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_get_elapsed_seconds_calculates_duration(self, mock_project, mock_dataset, mock_bq):
        """Test get_elapsed_seconds calculates time difference"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        import time
        processor.mark_time("test")
        time.sleep(0.1)  # Sleep for 100ms
        elapsed = processor.get_elapsed_seconds("test")

        assert elapsed >= 0.1
        assert elapsed < 1.0  # Should be less than 1 second


# ============================================================================
# Test Dataset Configuration
# ============================================================================

class TestDatasetConfiguration:
    """Test suite for dataset configuration"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_dataset_id_set_from_sport_config(self, mock_project, mock_dataset, mock_bq):
        """Test dataset_id is set from sport config"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'nba_analytics'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.dataset_id == 'nba_analytics'

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_table_name_set_by_child_class(self, mock_project, mock_dataset, mock_bq):
        """Test table_name is set by child class"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.table_name == 'test_analytics_table'

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_processing_strategy_has_default(self, mock_project, mock_dataset, mock_bq):
        """Test processing_strategy has default value"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.processing_strategy == 'MERGE_UPDATE'


# ============================================================================
# Test Correlation Tracking
# ============================================================================

class TestCorrelationTracking:
    """Test suite for correlation ID tracking"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_correlation_id_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test correlation_id is initialized"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        # Should be initialized by TransformProcessorBase
        assert hasattr(processor, 'correlation_id')

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_parent_processor_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test parent_processor is initialized"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert hasattr(processor, 'parent_processor')


# ============================================================================
# Test Registry Failure Tracking
# ============================================================================

class TestRegistryFailureTracking:
    """Test suite for registry failure tracking"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_registry_failures_initialized_empty(self, mock_project, mock_dataset, mock_bq):
        """Test registry_failures list initialized empty"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.registry_failures == []
        assert isinstance(processor.registry_failures, list)


# ============================================================================
# Test Soft Dependencies
# ============================================================================

class TestSoftDependencies:
    """Test suite for soft dependency configuration"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_soft_dependencies_disabled_by_default(self, mock_project, mock_dataset, mock_bq):
        """Test use_soft_dependencies is False by default"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.use_soft_dependencies is False

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_soft_dependency_threshold_default(self, mock_project, mock_dataset, mock_bq):
        """Test soft_dependency_threshold has default value"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.soft_dependency_threshold == 0.80


# ============================================================================
# Test Additional Options
# ============================================================================

class TestAdditionalOptions:
    """Test suite for additional option handling"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_set_additional_opts_adds_timestamp(self, mock_project, mock_dataset, mock_bq):
        """Test set_additional_opts adds timestamp if not present"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.set_opts({'start_date': '2024-01-01', 'end_date': '2024-01-31'})

        processor.set_additional_opts()

        assert 'timestamp' in processor.opts
        # Should be in YYYYMMDD_HHMMSS format
        assert len(processor.opts['timestamp']) == 15

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_set_additional_opts_preserves_existing_timestamp(self, mock_project, mock_dataset, mock_bq):
        """Test set_additional_opts preserves existing timestamp"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        custom_timestamp = '20240101_120000'
        processor.set_opts({
            'start_date': '2024-01-01',
            'end_date': '2024-01-31',
            'timestamp': custom_timestamp
        })

        processor.set_additional_opts()

        assert processor.opts['timestamp'] == custom_timestamp

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_validate_additional_opts_passes_by_default(self, mock_project, mock_dataset, mock_bq):
        """Test validate_additional_opts passes (child override hook)"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.set_opts({'start_date': '2024-01-01', 'end_date': '2024-01-31'})

        # Should not raise
        processor.validate_additional_opts()


# ============================================================================
# Test Run ID Propagation
# ============================================================================

class TestRunIdPropagation:
    """Test suite for run_id propagation through options"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_set_opts_adds_run_id_to_opts(self, mock_project, mock_dataset, mock_bq):
        """Test set_opts adds run_id to options"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        original_run_id = processor.run_id

        processor.set_opts({'start_date': '2024-01-01', 'end_date': '2024-01-31'})

        assert processor.opts['run_id'] == original_run_id


# ============================================================================
# Test Post Processing
# ============================================================================

class TestPostProcessing:
    """Test suite for post-processing hooks"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_post_process_is_callable(self, mock_project, mock_dataset, mock_bq):
        """Test post_process method is callable (hook for child classes)"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        # Should not raise
        processor.post_process()


# ============================================================================
# Test Finalize
# ============================================================================

class TestFinalize:
    """Test suite for finalize method"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_finalize_is_callable(self, mock_project, mock_dataset, mock_bq):
        """Test finalize method is callable"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        # Should not raise
        processor.finalize()

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_finalize_saves_failures_when_present(self, mock_project, mock_dataset, mock_bq):
        """Test finalize saves failures to BigQuery when failed_entities present"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.failed_entities = [{'test': 'failure'}]

        with patch.object(processor, 'save_failures_to_bq') as mock_save:
            processor.finalize()

            # Verify save_failures_to_bq was called
            mock_save.assert_called_once()

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_finalize_handles_save_failure_gracefully(self, mock_project, mock_dataset, mock_bq):
        """Test finalize handles save_failures_to_bq error gracefully"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.failed_entities = [{'test': 'failure'}]

        with patch.object(processor, 'save_failures_to_bq',
                        side_effect=Exception("Save failed")):
            # Should not raise - error is caught and logged
            processor.finalize()


# ============================================================================
# Test Backfill Mode Detection
# ============================================================================

class TestBackfillMode:
    """Test suite for backfill mode detection"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_is_backfill_mode_false_by_default(self, mock_project, mock_dataset, mock_bq):
        """Test is_backfill_mode is False by default"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.set_opts({'start_date': '2024-01-01', 'end_date': '2024-01-31'})

        assert processor.is_backfill_mode is False

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_is_backfill_mode_true_when_backfill_opt_set(self, mock_project, mock_dataset, mock_bq):
        """Test is_backfill_mode is True when backfill option set"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.set_opts({
            'start_date': '2024-01-01',
            'end_date': '2024-01-31',
            'backfill_mode': True  # ✅ Correct option name
        })

        assert processor.is_backfill_mode is True


# ============================================================================
# Test Quality Issue Tracking
# ============================================================================

class TestQualityIssueTracking:
    """Test suite for quality issue tracking"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_quality_issues_initialized_empty(self, mock_project, mock_dataset, mock_bq):
        """Test quality_issues list initialized empty"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.quality_issues == []
        assert isinstance(processor.quality_issues, list)

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_failed_entities_initialized_empty(self, mock_project, mock_dataset, mock_bq):
        """Test failed_entities list initialized empty"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.failed_entities == []
        assert isinstance(processor.failed_entities, list)


# ============================================================================
# Test Error Handling - validate_opts
# ============================================================================

class TestValidateOptsErrorHandling:
    """Test suite for validate_opts error handling"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_validate_opts_handles_notification_failure(self, mock_project, mock_dataset, mock_bq):
        """Test validate_opts handles notification failure gracefully"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.set_opts({'end_date': '2024-01-31'})  # Missing start_date

        # Mock notification to raise exception
        with patch.object(processor, '_send_notification', side_effect=Exception("Notification failed")):
            with pytest.raises(ValueError, match="start_date"):
                processor.validate_opts()

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_validate_opts_sends_notification_on_missing_opt(self, mock_project, mock_dataset, mock_bq):
        """Test validate_opts sends notification on missing option"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.set_opts({'end_date': '2024-01-31'})

        with patch.object(processor, '_send_notification') as mock_notify:
            with pytest.raises(ValueError):
                processor.validate_opts()

            # Verify notification was called
            mock_notify.assert_called_once()
            call_args = mock_notify.call_args
            assert call_args[1]['title'].startswith('Analytics Processor Configuration Error')


# ============================================================================
# Test Error Handling - init_clients
# ============================================================================

class TestInitClientsErrorHandling:
    """Test suite for init_clients error handling"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_init_clients_handles_bigquery_error(self, mock_project, mock_dataset, mock_bq):
        """Test init_clients handles BigQuery API errors"""
        from google.api_core.exceptions import GoogleAPIError

        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.set_opts({'start_date': '2024-01-01', 'end_date': '2024-01-31'})

        # Mock get_bigquery_client to raise GoogleAPIError
        with patch('data_processors.analytics.analytics_base.get_bigquery_client',
                   side_effect=GoogleAPIError("API Error")):
            with pytest.raises(GoogleAPIError):
                processor.init_clients()

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_init_clients_sends_notification_on_error(self, mock_project, mock_dataset, mock_bq):
        """Test init_clients sends notification on BigQuery error"""
        from google.api_core.exceptions import GoogleAPIError

        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.set_opts({'start_date': '2024-01-01', 'end_date': '2024-01-31'})

        with patch('data_processors.analytics.analytics_base.get_bigquery_client',
                   side_effect=GoogleAPIError("API Error")):
            with patch.object(processor, '_send_notification') as mock_notify:
                with pytest.raises(GoogleAPIError):
                    processor.init_clients()

                # Verify notification was called
                mock_notify.assert_called_once()
                call_args = mock_notify.call_args
                assert 'Client Initialization Failed' in call_args[1]['title']

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_init_clients_handles_notification_failure(self, mock_project, mock_dataset, mock_bq):
        """Test init_clients handles notification failure gracefully"""
        from google.api_core.exceptions import GoogleAPIError

        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.set_opts({'start_date': '2024-01-01', 'end_date': '2024-01-31'})

        with patch('data_processors.analytics.analytics_base.get_bigquery_client',
                   side_effect=GoogleAPIError("API Error")):
            with patch.object(processor, '_send_notification',
                            side_effect=Exception("Notification failed")):
                with pytest.raises(GoogleAPIError):
                    processor.init_clients()


# ============================================================================
# Test Error Handling - validate_extracted_data
# ============================================================================

class TestValidateExtractedDataErrorHandling:
    """Test suite for validate_extracted_data error handling"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_validate_extracted_data_raises_on_none(self, mock_project, mock_dataset, mock_bq):
        """Test validate_extracted_data raises error when raw_data is None"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.set_opts({'start_date': '2024-01-01', 'end_date': '2024-01-31'})
        processor.raw_data = None

        with pytest.raises(ValueError, match="No data extracted"):
            processor.validate_extracted_data()

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_validate_extracted_data_sends_notification(self, mock_project, mock_dataset, mock_bq):
        """Test validate_extracted_data sends notification on no data"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.set_opts({'start_date': '2024-01-01', 'end_date': '2024-01-31'})
        processor.raw_data = None

        with patch.object(processor, '_send_notification') as mock_notify:
            with pytest.raises(ValueError):
                processor.validate_extracted_data()

            # Verify notification was called
            mock_notify.assert_called_once()
            call_args = mock_notify.call_args
            assert 'No Data Extracted' in call_args[1]['title']

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_validate_extracted_data_handles_notification_failure(self, mock_project, mock_dataset, mock_bq):
        """Test validate_extracted_data handles notification failure gracefully"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()
        processor.set_opts({'start_date': '2024-01-01', 'end_date': '2024-01-31'})
        processor.raw_data = None

        with patch.object(processor, '_send_notification',
                        side_effect=Exception("Notification failed")):
            with pytest.raises(ValueError, match="No data extracted"):
                processor.validate_extracted_data()


# ============================================================================
# Test Notification Wrapper
# ============================================================================

class TestNotificationWrapper:
    """Test suite for notification wrapper methods"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_send_notification_wrapper_exists(self, mock_project, mock_dataset, mock_bq):
        """Test _send_notification wrapper method exists"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert hasattr(processor, '_send_notification')
        assert callable(processor._send_notification)


# ============================================================================
# Test Processor Name Property
# ============================================================================

class TestProcessorName:
    """Test suite for processor_name property"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_processor_name_returns_class_name(self, mock_project, mock_dataset, mock_bq):
        """Test processor_name property returns class name"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.processor_name == 'ConcreteAnalyticsProcessor'


# ============================================================================
# Test Step Info Method
# ============================================================================

class TestStepInfo:
    """Test suite for step_info logging method"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_step_info_is_callable(self, mock_project, mock_dataset, mock_bq):
        """Test step_info method is callable"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        # Should not raise
        processor.step_info("test_step", "Test message")


# ============================================================================
# Test Report Error Method
# ============================================================================

class TestReportError:
    """Test suite for report_error method"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_report_error_is_callable(self, mock_project, mock_dataset, mock_bq):
        """Test report_error method is callable"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        # Should not raise (report_error takes only error parameter)
        processor.report_error(Exception("Test error"))


# ============================================================================
# Test Completeness Checker
# ============================================================================

class TestCompletenessChecker:
    """Test suite for completeness checker initialization"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_completeness_checker_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test completeness_checker is initialized to None"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.completeness_checker is None


# ============================================================================
# Test Change Detector
# ============================================================================

class TestChangeDetector:
    """Test suite for change detector initialization"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_change_detector_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test change_detector is initialized to None"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.change_detector is None


# ============================================================================
# Test Dataset Methods
# ============================================================================

class TestDatasetMethods:
    """Test suite for dataset helper methods"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_get_output_dataset_returns_dataset_id(self, mock_project, mock_dataset, mock_bq):
        """Test get_output_dataset returns dataset_id"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        # Method inherited from TransformProcessorBase
        output_dataset = processor.get_output_dataset()
        assert output_dataset == 'analytics_dataset'


# ============================================================================
# Test Processing Strategy
# ============================================================================

class TestProcessingStrategy:
    """Test suite for processing strategy configuration"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_save_on_error_enabled_by_default(self, mock_project, mock_dataset, mock_bq):
        """Test save_on_error is enabled by default"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.save_on_error is True

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_validate_on_extract_enabled_by_default(self, mock_project, mock_dataset, mock_bq):
        """Test validate_on_extract is enabled by default"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.validate_on_extract is True


# ============================================================================
# Test Output Configuration
# ============================================================================

class TestOutputConfiguration:
    """Test suite for output table/dataset configuration"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_output_dataset_set_from_sport_config(self, mock_project, mock_dataset, mock_bq):
        """Test OUTPUT_DATASET is set from sport config"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'nba_analytics'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert processor.OUTPUT_DATASET == 'nba_analytics'


# ============================================================================
# Test Trigger Fields
# ============================================================================

class TestTriggerFields:
    """Test suite for trigger/correlation tracking fields"""

    @patch('data_processors.analytics.analytics_base.get_bigquery_client')
    @patch('data_processors.analytics.analytics_base.get_analytics_dataset')
    @patch('data_processors.analytics.analytics_base.get_project_id')
    def test_trigger_message_id_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test trigger_message_id is initialized"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'analytics_dataset'
        mock_bq.return_value = Mock()

        processor = ConcreteAnalyticsProcessor()

        assert hasattr(processor, 'trigger_message_id')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

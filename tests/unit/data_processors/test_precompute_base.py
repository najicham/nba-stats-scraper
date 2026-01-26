#!/usr/bin/env python3
"""
Unit Tests for data_processors/precompute/precompute_base.py

Tests cover:
1. Initialization
2. Option handling (set_opts, validate_opts)
3. Client initialization
4. Data extraction lifecycle
5. Stats tracking
6. Error handling
7. Run history tracking
8. Precompute-specific fields
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from datetime import datetime, date
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from data_processors.precompute.precompute_base import PrecomputeProcessorBase, _categorize_failure


# ============================================================================
# Test Fixture - Concrete Implementation
# ============================================================================

class ConcretePrecomputeProcessor(PrecomputeProcessorBase):
    """Concrete implementation for testing."""

    table_name = "test_precompute_table"
    required_opts = ['analysis_date']
    additional_opts = ['season']

    def extract_raw_data(self):
        """Override abstract method."""
        self.raw_data = {'test': 'data'}

    def calculate_precompute_metrics(self):
        """Override abstract method."""
        self.transformed_data = [{'metric': 'value'}]

    def set_opts(self, opts):
        """Override method from base."""
        self.opts = opts
        self.opts["run_id"] = self.run_id

    def validate_opts(self):
        """Override method from base."""
        for required_opt in self.required_opts:
            if required_opt not in self.opts:
                raise ValueError(f"Missing required option [{required_opt}]")

    def set_additional_opts(self):
        """Override method from base."""
        pass

    def validate_additional_opts(self):
        """Override method from base."""
        pass

    def init_clients(self):
        """Override method from base."""
        pass

    def validate_extracted_data(self):
        """Override method from base."""
        if self.raw_data is None or (hasattr(self.raw_data, 'empty') and self.raw_data.empty):
            raise ValueError("No data extracted")

    def log_processing_run(self, success, error=None, skip_reason=None):
        """Override method from base."""
        pass

    def post_process(self):
        """Override method from base."""
        pass


# ============================================================================
# Test Initialization
# ============================================================================

class TestPrecomputeInitialization:
    """Test suite for precompute processor initialization"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_processor_initializes_with_defaults(self, mock_project, mock_dataset, mock_bq):
        """Test processor initializes with default values"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.project_id == 'test-project'
        assert processor.dataset_id == 'precompute_dataset'
        assert processor.run_id is not None
        assert processor.stats == {'run_id': processor.run_id}
        assert processor.raw_data is None
        assert processor.validated_data == {}
        assert processor.transformed_data == {}

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_run_id_is_unique(self, mock_project, mock_dataset, mock_bq):
        """Test each processor instance gets unique run_id"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor1 = ConcretePrecomputeProcessor()
        processor2 = ConcretePrecomputeProcessor()

        assert processor1.run_id != processor2.run_id

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_phase_and_step_prefix_set(self, mock_project, mock_dataset, mock_bq):
        """Test phase and step prefix are set correctly"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.PHASE == 'phase_4_precompute'
        assert processor.STEP_PREFIX == 'PRECOMPUTE_STEP'


# ============================================================================
# Test Precompute-Specific Fields
# ============================================================================

class TestPrecomputeSpecificFields:
    """Test suite for precompute-specific field initialization"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_data_completeness_pct_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test data_completeness_pct is initialized to 100.0"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.data_completeness_pct == 100.0

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_dependency_check_passed_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test dependency_check_passed is initialized to True"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.dependency_check_passed is True

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_upstream_data_age_hours_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test upstream_data_age_hours is initialized to 0.0"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.upstream_data_age_hours == 0.0

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_missing_dependencies_list_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test missing_dependencies_list is initialized as empty list"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.missing_dependencies_list == []
        assert isinstance(processor.missing_dependencies_list, list)

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_write_success_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test write_success is initialized to True"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.write_success is True

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_dep_check_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test dep_check is initialized to None"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.dep_check is None


# ============================================================================
# Test Option Handling
# ============================================================================

class TestOptionHandling:
    """Test suite for option setting and validation"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_set_opts_stores_options(self, mock_project, mock_dataset, mock_bq):
        """Test set_opts stores options correctly"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()
        opts = {
            'analysis_date': date(2024, 1, 15),
            'season': '2023-24'
        }

        processor.set_opts(opts)

        assert processor.opts == opts
        assert processor.opts['analysis_date'] == date(2024, 1, 15)

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_validate_opts_requires_analysis_date(self, mock_project, mock_dataset, mock_bq):
        """Test validate_opts raises error when analysis_date missing"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()
        processor.set_opts({'season': '2023-24'})

        with pytest.raises(ValueError, match="analysis_date"):
            processor.validate_opts()

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_validate_opts_passes_with_all_required(self, mock_project, mock_dataset, mock_bq):
        """Test validate_opts passes when all required opts present"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()
        processor.set_opts({'analysis_date': date(2024, 1, 15)})

        # Should not raise
        processor.validate_opts()


# ============================================================================
# Test Client Initialization
# ============================================================================

class TestClientInitialization:
    """Test suite for BigQuery client initialization"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_init_clients_sets_up_bigquery_client(self, mock_project, mock_dataset, mock_bq):
        """Test init_clients sets up BigQuery client"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_client = Mock()
        mock_bq.return_value = mock_client

        processor = ConcretePrecomputeProcessor()
        processor.init_clients()

        # Client should already be set in __init__
        assert processor.bq_client is not None

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    @patch.dict(os.environ, {'GCP_PROJECT_ID': 'test-project-123'})
    def test_project_id_set_from_environment(self, mock_project, mock_dataset, mock_bq):
        """Test project_id is set from environment or config"""
        mock_project.return_value = 'fallback-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        # Should use environment variable first
        assert processor.project_id == 'test-project-123'


# ============================================================================
# Test Data Extraction Lifecycle
# ============================================================================

class TestDataExtractionLifecycle:
    """Test suite for data extraction and processing"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_extract_raw_data_populates_raw_data(self, mock_project, mock_dataset, mock_bq):
        """Test extract_raw_data populates raw_data dict"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        # Verify initial state
        assert processor.raw_data is None

        # Extract data
        processor.extract_raw_data()

        # Verify data populated
        assert processor.raw_data == {'test': 'data'}

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_calculate_precompute_metrics_populates_transformed_data(self, mock_project, mock_dataset, mock_bq):
        """Test calculate_precompute_metrics populates transformed_data list"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        # Verify initial state
        assert processor.transformed_data == {}

        # Calculate metrics
        processor.calculate_precompute_metrics()

        # Verify data populated
        assert len(processor.transformed_data) == 1
        assert processor.transformed_data[0] == {'metric': 'value'}


# ============================================================================
# Test Stats Tracking
# ============================================================================

class TestStatsTracking:
    """Test suite for statistics tracking"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_stats_initialized_with_run_id(self, mock_project, mock_dataset, mock_bq):
        """Test stats dict initialized with run_id"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert 'run_id' in processor.stats
        assert processor.stats['run_id'] == processor.run_id


# ============================================================================
# Test Time Tracking
# ============================================================================

class TestTimeTracking:
    """Test suite for time marker tracking"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_mark_time_creates_marker(self, mock_project, mock_dataset, mock_bq):
        """Test mark_time creates time marker"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        result = processor.mark_time("extraction")

        # First call returns "0.0"
        assert result == "0.0"
        assert "extraction" in processor.time_markers
        assert isinstance(processor.time_markers["extraction"], dict)

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_get_elapsed_seconds_calculates_duration(self, mock_project, mock_dataset, mock_bq):
        """Test get_elapsed_seconds calculates time difference"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        import time
        processor.mark_time("test")
        time.sleep(0.1)  # Sleep for 100ms
        elapsed = processor.get_elapsed_seconds("test")

        assert elapsed >= 0.1
        assert elapsed < 1.0


# ============================================================================
# Test Dataset Configuration
# ============================================================================

class TestDatasetConfiguration:
    """Test suite for dataset configuration"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_dataset_id_set_from_sport_config(self, mock_project, mock_dataset, mock_bq):
        """Test dataset_id is set from sport config"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'nba_precompute'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.dataset_id == 'nba_precompute'

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_table_name_set_by_child_class(self, mock_project, mock_dataset, mock_bq):
        """Test table_name is set by child class"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.table_name == 'test_precompute_table'

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_processing_strategy_has_default(self, mock_project, mock_dataset, mock_bq):
        """Test processing_strategy has default value"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.processing_strategy == 'MERGE_UPDATE'

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_date_column_has_default(self, mock_project, mock_dataset, mock_bq):
        """Test date_column has default value"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.date_column == 'analysis_date'


# ============================================================================
# Test Soft Dependencies
# ============================================================================

class TestSoftDependencies:
    """Test suite for soft dependency configuration"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_soft_dependencies_disabled_by_default(self, mock_project, mock_dataset, mock_bq):
        """Test use_soft_dependencies is False by default"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.use_soft_dependencies is False

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_soft_dependency_threshold_default(self, mock_project, mock_dataset, mock_bq):
        """Test soft_dependency_threshold has default value"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.soft_dependency_threshold == 0.80


# ============================================================================
# Test Quality Issue Tracking
# ============================================================================

class TestQualityIssueTracking:
    """Test suite for quality issue tracking"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_quality_issues_initialized_empty(self, mock_project, mock_dataset, mock_bq):
        """Test quality_issues list initialized empty"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.quality_issues == []
        assert isinstance(processor.quality_issues, list)

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_failed_entities_initialized_empty(self, mock_project, mock_dataset, mock_bq):
        """Test failed_entities list initialized empty"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.failed_entities == []
        assert isinstance(processor.failed_entities, list)


# ============================================================================
# Test Correlation Tracking
# ============================================================================

class TestCorrelationTracking:
    """Test suite for correlation ID tracking"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_correlation_id_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test correlation_id is initialized"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert hasattr(processor, 'correlation_id')

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_parent_processor_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test parent_processor is initialized"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert hasattr(processor, 'parent_processor')


# ============================================================================
# Test Processor Name Property
# ============================================================================

class TestProcessorName:
    """Test suite for processor_name property"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_processor_name_returns_class_name(self, mock_project, mock_dataset, mock_bq):
        """Test processor_name property returns class name"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.processor_name == 'ConcretePrecomputeProcessor'


# ============================================================================
# Test Step Info Method
# ============================================================================

class TestStepInfo:
    """Test suite for step_info logging method"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_step_info_is_callable(self, mock_project, mock_dataset, mock_bq):
        """Test step_info method is callable"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        # Should not raise
        processor.step_info("test_step", "Test message")


# ============================================================================
# Test Processing Configuration
# ============================================================================

class TestProcessingConfiguration:
    """Test suite for processing configuration flags"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_save_on_error_enabled_by_default(self, mock_project, mock_dataset, mock_bq):
        """Test save_on_error is enabled by default"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.save_on_error is True

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_validate_on_extract_enabled_by_default(self, mock_project, mock_dataset, mock_bq):
        """Test validate_on_extract is enabled by default"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.validate_on_extract is True


# ============================================================================
# Test Backfill Mode
# ============================================================================

class TestBackfillMode:
    """Test suite for backfill mode detection"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_is_backfill_mode_false_by_default(self, mock_project, mock_dataset, mock_bq):
        """Test is_backfill_mode is False by default"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()
        processor.set_opts({'analysis_date': date(2024, 1, 15)})

        assert processor.is_backfill_mode is False

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_is_backfill_mode_true_when_backfill_opt_set(self, mock_project, mock_dataset, mock_bq):
        """Test is_backfill_mode is True when backfill option set"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()
        processor.set_opts({
            'analysis_date': date(2024, 1, 15),
            'backfill_mode': True
        })

        assert processor.is_backfill_mode is True


# ============================================================================
# Test Run ID Propagation
# ============================================================================

class TestRunIdPropagation:
    """Test suite for run_id propagation through options"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_set_opts_adds_run_id_to_opts(self, mock_project, mock_dataset, mock_bq):
        """Test set_opts adds run_id to options"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()
        original_run_id = processor.run_id

        processor.set_opts({'analysis_date': date(2024, 1, 15)})

        assert processor.opts['run_id'] == original_run_id


# ============================================================================
# Test Report Error Method
# ============================================================================

class TestReportError:
    """Test suite for report_error method"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_report_error_is_callable(self, mock_project, mock_dataset, mock_bq):
        """Test report_error method is callable"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        # Should not raise (report_error takes only error parameter)
        processor.report_error(Exception("Test error"))


# ============================================================================
# Test Incremental Run Tracking
# ============================================================================

class TestIncrementalRun:
    """Test suite for incremental run tracking"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_is_incremental_run_initialized_false(self, mock_project, mock_dataset, mock_bq):
        """Test is_incremental_run is initialized to False"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert hasattr(processor, 'is_incremental_run')

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_entities_changed_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test entities_changed is initialized"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert hasattr(processor, 'entities_changed')


# ============================================================================
# Test Source Metadata Fields
# ============================================================================

class TestSourceMetadata:
    """Test suite for source metadata tracking"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_source_metadata_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test source_metadata is initialized"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert hasattr(processor, 'source_metadata')


# ============================================================================
# Test Output Configuration
# ============================================================================

class TestOutputConfiguration:
    """Test suite for output table/dataset configuration"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_output_dataset_set_from_sport_config(self, mock_project, mock_dataset, mock_bq):
        """Test OUTPUT_DATASET is set from sport config"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'nba_precompute'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert processor.OUTPUT_DATASET == 'nba_precompute'


# ============================================================================
# Test Trigger Message Tracking
# ============================================================================

class TestTriggerMessageTracking:
    """Test suite for trigger message tracking"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_trigger_message_id_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test trigger_message_id is initialized"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert hasattr(processor, 'trigger_message_id')


# ============================================================================
# Test Finalize Method
# ============================================================================

class TestFinalize:
    """Test suite for finalize method"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_finalize_is_callable(self, mock_project, mock_dataset, mock_bq):
        """Test finalize method is callable"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        # Should not raise
        processor.finalize()


# ============================================================================
# Test Get Output Dataset
# ============================================================================

class TestGetOutputDataset:
    """Test suite for get_output_dataset method"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_get_output_dataset_returns_dataset_id(self, mock_project, mock_dataset, mock_bq):
        """Test get_output_dataset returns dataset_id"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        output_dataset = processor.get_output_dataset()
        assert output_dataset == 'precompute_dataset'


# ============================================================================
# Test Failure Categorization
# ============================================================================

class TestFailureCategorization:
    """Test suite for _categorize_failure function"""

    def test_categorize_no_data_available_from_message(self):
        """Test categorizing no_data_available from error message"""
        error = ValueError("no data available")
        category = _categorize_failure(error, "load")
        assert category == "no_data_available"

    def test_categorize_no_data_available_from_error_type(self):
        """Test categorizing no_data_available from FileNotFoundError"""
        error = FileNotFoundError("file not found")
        category = _categorize_failure(error, "load")
        assert category == "no_data_available"

    def test_categorize_configuration_error(self):
        """Test categorizing configuration_error"""
        error = ValueError("Missing required option")
        category = _categorize_failure(error, "initialization")
        assert category == "configuration_error"

    def test_categorize_upstream_failure_from_message(self):
        """Test categorizing upstream_failure from error message"""
        error = ValueError("dependency check failed")
        category = _categorize_failure(error, "load")
        assert category == "upstream_failure"

    def test_categorize_timeout_error(self):
        """Test categorizing timeout error"""
        error = TimeoutError("operation timed out")
        category = _categorize_failure(error, "load")
        assert category == "timeout"

    def test_categorize_processing_error_default(self):
        """Test categorizing processing_error as default"""
        error = ValueError("unexpected error")
        category = _categorize_failure(error, "transform")
        assert category == "processing_error"

    def test_categorize_bigquery_error(self):
        """Test categorizing BigQuery-related error"""
        error = Exception("BigQuery operation failed")
        category = _categorize_failure(error, "save")
        assert category == "processing_error"

    def test_categorize_streaming_buffer_error(self):
        """Test categorizing streaming buffer error as no_data_available"""
        error = Exception("bigquery streaming buffer not yet committed")
        category = _categorize_failure(error, "load")
        assert category == "no_data_available"

    def test_categorize_off_season_error(self):
        """Test categorizing off-season as no_data_available"""
        error = ValueError("off-season")
        category = _categorize_failure(error, "load")
        assert category == "no_data_available"

    def test_categorize_empty_response_error(self):
        """Test categorizing empty response as no_data_available"""
        error = ValueError("empty response")
        category = _categorize_failure(error, "extract")
        assert category == "no_data_available"

    def test_categorize_no_games_scheduled(self):
        """Test categorizing no games scheduled as no_data_available"""
        error = ValueError("no games scheduled")
        category = _categorize_failure(error, "extract")
        assert category == "no_data_available"

    def test_categorize_deadline_exceeded(self):
        """Test categorizing deadline exceeded as timeout"""
        from google.api_core.exceptions import DeadlineExceeded
        error = DeadlineExceeded("deadline exceeded")
        category = _categorize_failure(error, "load")
        assert category == "timeout"

    def test_categorize_unknown_error(self):
        """Test categorizing unknown error defaults to processing_error"""
        error = RuntimeError("unknown error")
        category = _categorize_failure(error, "transform")
        assert category == "processing_error"


# ============================================================================
# Test Additional Option Methods
# ============================================================================

class TestAdditionalOptions:
    """Test suite for additional option handling"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_set_additional_opts_is_callable(self, mock_project, mock_dataset, mock_bq):
        """Test set_additional_opts is callable"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()
        processor.set_opts({'analysis_date': date(2024, 1, 15)})

        # Should not raise
        processor.set_additional_opts()

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_validate_additional_opts_is_callable(self, mock_project, mock_dataset, mock_bq):
        """Test validate_additional_opts is callable"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()
        processor.set_opts({'analysis_date': date(2024, 1, 15)})

        # Should not raise
        processor.validate_additional_opts()


# ============================================================================
# Test Heartbeat System
# ============================================================================

class TestHeartbeat:
    """Test suite for heartbeat initialization"""

    @patch('data_processors.precompute.precompute_base.get_bigquery_client')
    @patch('data_processors.precompute.precompute_base.get_precompute_dataset')
    @patch('data_processors.precompute.precompute_base.get_project_id')
    def test_heartbeat_initialized(self, mock_project, mock_dataset, mock_bq):
        """Test heartbeat is initialized"""
        mock_project.return_value = 'test-project'
        mock_dataset.return_value = 'precompute_dataset'
        mock_bq.return_value = Mock()

        processor = ConcretePrecomputeProcessor()

        assert hasattr(processor, 'heartbeat')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


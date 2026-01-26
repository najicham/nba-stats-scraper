#!/usr/bin/env python3
"""
Unit tests for validation/base_validator.py

Tests cover:
- Initialization and configuration loading
- Helper methods (date handling, command generation)
- Report generation and summary building
- Query execution and caching
- Validation result creation

Target: 20-30% coverage with 25-30 tests
"""

import pytest
import yaml
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock, mock_open
from datetime import date, datetime, timedelta
from pathlib import Path

# Import the classes we're testing
from validation.base_validator import (
    BaseValidator,
    ValidationResult,
    ValidationReport,
    ValidationStatus,
    ValidationSeverity,
    ValidationError
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_config():
    """Valid configuration for testing"""
    return {
        'processor': {
            'name': 'test_processor',
            'description': 'Test processor for validation',
            'table': 'nba_raw.test_table',
            'type': 'raw',
            'layers': ['bigquery']
        },
        'bigquery_validations': {
            'enabled': True,
            'completeness': {
                'target_table': 'nba_raw.test_table',
                'reference_table': 'nba_raw.nbac_schedule',
                'match_field': 'game_date',
                'severity': 'error'
            }
        },
        'remediation': {
            'processor_backfill_template': 'gcloud run jobs execute test-processor --args="{start_date},{end_date}"',
            'scraper_backfill_template': 'python scripts/scrape.py --date {date}'
        }
    }


@pytest.fixture
def temp_config_file(valid_config):
    """Create a temporary config file"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(valid_config, f)
        temp_path = f.name

    yield temp_path

    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def mock_bq_client():
    """Mock BigQuery client"""
    return Mock()


@pytest.fixture
def mock_gcs_client():
    """Mock GCS client"""
    return Mock()


# ============================================================================
# Test ValidationResult Dataclass
# ============================================================================

class TestValidationResult:
    """Tests for ValidationResult dataclass"""

    def test_validation_result_creates_with_required_fields(self):
        """Test ValidationResult creation with required fields"""
        result = ValidationResult(
            check_name="test_check",
            check_type="completeness",
            layer="bigquery",
            passed=True,
            severity="info",
            message="Test passed"
        )

        assert result.check_name == "test_check"
        assert result.check_type == "completeness"
        assert result.layer == "bigquery"
        assert result.passed is True
        assert result.severity == "info"
        assert result.message == "Test passed"

    def test_validation_result_initializes_empty_lists(self):
        """Test that affected_items and remediation default to empty lists"""
        result = ValidationResult(
            check_name="test",
            check_type="test",
            layer="test",
            passed=False,
            severity="error",
            message="Test"
        )

        assert result.affected_items == []
        assert result.remediation == []

    def test_validation_result_accepts_optional_fields(self):
        """Test ValidationResult with all optional fields"""
        result = ValidationResult(
            check_name="test",
            check_type="test",
            layer="test",
            passed=False,
            severity="error",
            message="Test",
            affected_count=5,
            affected_items=["item1", "item2"],
            remediation=["fix command"],
            query_used="SELECT * FROM test",
            execution_duration=1.23
        )

        assert result.affected_count == 5
        assert result.affected_items == ["item1", "item2"]
        assert result.remediation == ["fix command"]
        assert result.query_used == "SELECT * FROM test"
        assert result.execution_duration == 1.23


# ============================================================================
# Test Configuration Loading
# ============================================================================

class TestConfigLoading:
    """Tests for configuration loading and validation"""

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_load_valid_config(self, mock_storage, mock_bq, temp_config_file):
        """Test loading a valid configuration file"""
        validator = BaseValidator(temp_config_file)

        assert validator.processor_name == 'test_processor'
        assert validator.processor_type == 'raw'
        assert validator.config['processor']['name'] == 'test_processor'

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_config_file_not_found_raises_error(self, mock_storage, mock_bq):
        """Test that missing config file raises ValidationError"""
        with pytest.raises(ValidationError, match="Config file not found"):
            BaseValidator('/nonexistent/config.yaml')

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_invalid_yaml_raises_error(self, mock_storage, mock_bq):
        """Test that invalid YAML raises ValidationError"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("invalid: yaml: content:\n  - bad indent")
            temp_path = f.name

        try:
            with pytest.raises(ValidationError, match="Invalid YAML"):
                BaseValidator(temp_path)
        finally:
            os.unlink(temp_path)

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_missing_processor_field_raises_error(self, mock_storage, mock_bq):
        """Test that config missing 'processor' field raises error"""
        config = {'invalid': 'config'}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config, f)
            temp_path = f.name

        try:
            with pytest.raises(ValidationError, match="missing required field: processor"):
                BaseValidator(temp_path)
        finally:
            os.unlink(temp_path)

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_missing_processor_name_raises_error(self, mock_storage, mock_bq):
        """Test that processor config missing 'name' raises error"""
        config = {
            'processor': {
                'description': 'Missing name',
                'table': 'test.table'
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config, f)
            temp_path = f.name

        try:
            with pytest.raises(ValidationError, match="missing required field: name"):
                BaseValidator(temp_path)
        finally:
            os.unlink(temp_path)


# ============================================================================
# Test Initialization
# ============================================================================

class TestInitialization:
    """Tests for BaseValidator initialization"""

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_init_creates_clients(self, mock_storage, mock_bq, temp_config_file):
        """Test that __init__ creates BigQuery and GCS clients"""
        validator = BaseValidator(temp_config_file)

        assert mock_bq.called
        assert mock_storage.called
        assert validator.bq_client is not None
        assert validator.gcs_client is not None

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_init_sets_project_id_from_env(self, mock_storage, mock_bq, temp_config_file):
        """Test that project_id is set from environment variable"""
        with patch.dict(os.environ, {'GCP_PROJECT_ID': 'test-project'}):
            validator = BaseValidator(temp_config_file)
            assert validator.project_id == 'test-project'

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_init_defaults_project_id(self, mock_storage, mock_bq, temp_config_file):
        """Test that project_id defaults to nba-props-platform"""
        with patch.dict(os.environ, {}, clear=True):
            validator = BaseValidator(temp_config_file)
            assert validator.project_id == 'nba-props-platform'

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_init_initializes_empty_results_list(self, mock_storage, mock_bq, temp_config_file):
        """Test that results list is initialized empty"""
        validator = BaseValidator(temp_config_file)
        assert validator.results == []

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_init_initializes_query_cache(self, mock_storage, mock_bq, temp_config_file):
        """Test that query cache is initialized empty"""
        validator = BaseValidator(temp_config_file)
        assert validator._query_cache == {}


# ============================================================================
# Test Helper Methods - Date Handling
# ============================================================================

class TestDateHandling:
    """Tests for date handling helper methods"""

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_auto_detect_date_range_with_season(self, mock_storage, mock_bq, temp_config_file):
        """Test auto-detecting date range for a season year"""
        validator = BaseValidator(temp_config_file)

        start_date, end_date = validator._auto_detect_date_range(season_year=2024)

        assert start_date == "2024-10-01"
        assert end_date == "2025-06-30"

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_auto_detect_date_range_without_season(self, mock_storage, mock_bq, temp_config_file):
        """Test auto-detecting date range without season (last 30 days)"""
        validator = BaseValidator(temp_config_file)

        start_date, end_date = validator._auto_detect_date_range(season_year=None)

        expected_end = date.today().isoformat()
        expected_start = (date.today() - timedelta(days=30)).isoformat()

        assert start_date == expected_start
        assert end_date == expected_end

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_group_consecutive_dates_single_date(self, mock_storage, mock_bq, temp_config_file):
        """Test grouping a single date"""
        validator = BaseValidator(temp_config_file)

        result = validator._group_consecutive_dates(['2024-01-15'])

        assert result == [('2024-01-15', '2024-01-15')]

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_group_consecutive_dates_consecutive(self, mock_storage, mock_bq, temp_config_file):
        """Test grouping consecutive dates into a range"""
        validator = BaseValidator(temp_config_file)

        dates = ['2024-01-15', '2024-01-16', '2024-01-17']
        result = validator._group_consecutive_dates(dates)

        assert result == [('2024-01-15', '2024-01-17')]

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_group_consecutive_dates_multiple_groups(self, mock_storage, mock_bq, temp_config_file):
        """Test grouping dates with gaps into multiple ranges"""
        validator = BaseValidator(temp_config_file)

        dates = ['2024-01-15', '2024-01-16', '2024-01-20', '2024-01-21', '2024-01-25']
        result = validator._group_consecutive_dates(dates)

        assert result == [
            ('2024-01-15', '2024-01-16'),
            ('2024-01-20', '2024-01-21'),
            ('2024-01-25', '2024-01-25')
        ]

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_group_consecutive_dates_empty_list(self, mock_storage, mock_bq, temp_config_file):
        """Test grouping empty date list"""
        validator = BaseValidator(temp_config_file)

        result = validator._group_consecutive_dates([])

        assert result == []

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_group_consecutive_dates_handles_invalid_format(self, mock_storage, mock_bq, temp_config_file):
        """Test that invalid date format is handled gracefully"""
        validator = BaseValidator(temp_config_file)

        dates = ['invalid-date', '2024-01-15']
        result = validator._group_consecutive_dates(dates)

        # Should return individual dates when parsing fails
        assert len(result) <= 10  # Max 10 individual dates


# ============================================================================
# Test Helper Methods - Command Generation
# ============================================================================

class TestCommandGeneration:
    """Tests for remediation command generation"""

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_generate_backfill_commands_empty_list(self, mock_storage, mock_bq, temp_config_file):
        """Test generating backfill commands with empty date list"""
        validator = BaseValidator(temp_config_file)

        result = validator._generate_backfill_commands([])

        assert result == []

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_generate_backfill_commands_single_date(self, mock_storage, mock_bq, temp_config_file):
        """Test generating backfill command for single date"""
        validator = BaseValidator(temp_config_file)

        result = validator._generate_backfill_commands(['2024-01-15'])

        assert len(result) == 1
        assert '2024-01-15' in result[0]
        assert 'gcloud run jobs execute' in result[0]

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_generate_backfill_commands_consecutive_dates(self, mock_storage, mock_bq, temp_config_file):
        """Test generating backfill commands groups consecutive dates"""
        validator = BaseValidator(temp_config_file)

        dates = ['2024-01-15', '2024-01-16', '2024-01-17']
        result = validator._generate_backfill_commands(dates)

        # Should create one command for the range
        assert len(result) == 1
        assert '2024-01-15' in result[0]
        assert '2024-01-17' in result[0]

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_generate_scraper_commands_limits_to_10(self, mock_storage, mock_bq, temp_config_file):
        """Test that scraper commands are limited to 10 plus a message"""
        validator = BaseValidator(temp_config_file)

        dates = [f'2024-01-{i:02d}' for i in range(1, 20)]  # 19 dates
        result = validator._generate_scraper_commands(dates)

        # Should have 10 commands + 1 "and X more" message
        assert len(result) == 11
        assert '... and 9 more dates' in result[-1]

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_generate_scraper_commands_no_template(self, mock_storage, mock_bq):
        """Test scraper command generation when no template in config"""
        config = {
            'processor': {
                'name': 'test',
                'description': 'test',
                'table': 'test.table'
            },
            'remediation': {}
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config, f)
            temp_path = f.name

        try:
            validator = BaseValidator(temp_path)
            result = validator._generate_scraper_commands(['2024-01-15'])
            assert result == []
        finally:
            os.unlink(temp_path)


# ============================================================================
# Test Report Building
# ============================================================================

class TestReportBuilding:
    """Tests for report generation and summary building"""

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_build_summary_empty_results(self, mock_storage, mock_bq, temp_config_file):
        """Test building summary with no results"""
        validator = BaseValidator(temp_config_file)
        validator.results = []

        summary = validator._build_summary()

        assert summary['by_layer'] == {}
        assert summary['by_severity'] == {}
        assert summary['by_type'] == {}
        assert summary['execution_times'] == {}

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_build_summary_with_passed_results(self, mock_storage, mock_bq, temp_config_file):
        """Test building summary with passed results"""
        validator = BaseValidator(temp_config_file)
        validator.results = [
            ValidationResult(
                check_name="test1",
                check_type="completeness",
                layer="bigquery",
                passed=True,
                severity="info",
                message="Passed",
                execution_duration=1.5
            )
        ]

        summary = validator._build_summary()

        assert summary['by_layer']['bigquery']['passed'] == 1
        assert summary['by_layer']['bigquery']['failed'] == 0
        assert summary['by_type']['completeness']['passed'] == 1
        assert summary['execution_times']['test1'] == 1.5

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_build_summary_with_failed_results(self, mock_storage, mock_bq, temp_config_file):
        """Test building summary with failed results"""
        validator = BaseValidator(temp_config_file)
        validator.results = [
            ValidationResult(
                check_name="test1",
                check_type="completeness",
                layer="bigquery",
                passed=False,
                severity="error",
                message="Failed"
            )
        ]

        summary = validator._build_summary()

        assert summary['by_layer']['bigquery']['failed'] == 1
        assert summary['by_severity']['error'] == 1
        assert summary['by_type']['completeness']['failed'] == 1

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_build_summary_multiple_layers(self, mock_storage, mock_bq, temp_config_file):
        """Test building summary with results from multiple layers"""
        validator = BaseValidator(temp_config_file)
        validator.results = [
            ValidationResult(
                check_name="bq_check",
                check_type="completeness",
                layer="bigquery",
                passed=True,
                severity="info",
                message="Pass"
            ),
            ValidationResult(
                check_name="gcs_check",
                check_type="file_presence",
                layer="gcs",
                passed=False,
                severity="error",
                message="Fail"
            )
        ]

        summary = validator._build_summary()

        assert summary['by_layer']['bigquery']['passed'] == 1
        assert summary['by_layer']['gcs']['failed'] == 1
        assert len(summary['by_layer']) == 2


# ============================================================================
# Test Query Execution
# ============================================================================

class TestQueryExecution:
    """Tests for query execution and caching"""

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_execute_query_caches_result(self, mock_storage, mock_bq, temp_config_file):
        """Test that query results are cached when cache_key provided"""
        mock_bq_instance = Mock()
        mock_bq.return_value = mock_bq_instance

        mock_result = [Mock(value=1), Mock(value=2)]
        mock_job = Mock()
        mock_job.result.return_value = iter(mock_result)
        mock_bq_instance.query.return_value = mock_job

        validator = BaseValidator(temp_config_file)

        # First call - should execute query
        result = validator._execute_query("SELECT 1", cache_key="test_key")

        assert validator._query_cache["test_key"] == mock_result
        assert mock_bq_instance.query.call_count == 1

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_execute_query_uses_cached_result(self, mock_storage, mock_bq, temp_config_file):
        """Test that cached results are returned on subsequent calls"""
        mock_bq_instance = Mock()
        mock_bq.return_value = mock_bq_instance

        validator = BaseValidator(temp_config_file)
        cached_data = [Mock(value=1)]
        validator._query_cache["test_key"] = cached_data

        # Second call - should use cache
        result = validator._execute_query("SELECT 1", cache_key="test_key")

        assert result == cached_data
        assert not mock_bq_instance.query.called

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_execute_query_without_cache_key(self, mock_storage, mock_bq, temp_config_file):
        """Test query execution without caching"""
        mock_bq_instance = Mock()
        mock_bq.return_value = mock_bq_instance

        mock_result = Mock()
        mock_job = Mock()
        mock_job.result.return_value = mock_result
        mock_bq_instance.query.return_value = mock_job

        validator = BaseValidator(temp_config_file)

        result = validator._execute_query("SELECT 1")

        assert result == mock_result
        assert len(validator._query_cache) == 0


# ============================================================================
# Test Layer Stats
# ============================================================================

class TestLayerStats:
    """Tests for layer statistics calculation"""

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_get_layer_stats_empty_report(self, mock_storage, mock_bq, temp_config_file):
        """Test layer stats with empty report"""
        validator = BaseValidator(temp_config_file)

        report = ValidationReport(
            processor_name="test",
            processor_type="raw",
            validation_timestamp="2024-01-01T00:00:00Z",
            validation_run_id="test_run",
            date_range_start="2024-01-01",
            date_range_end="2024-01-31",
            season_year=None,
            total_checks=0,
            passed_checks=0,
            failed_checks=0,
            overall_status="pass",
            results=[],
            remediation_commands=[],
            summary={},
            execution_duration=1.0
        )

        stats = validator._get_layer_stats(report)

        assert stats == {}

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_get_layer_stats_with_results(self, mock_storage, mock_bq, temp_config_file):
        """Test layer stats calculation with results"""
        validator = BaseValidator(temp_config_file)

        results = [
            ValidationResult(
                check_name="check1",
                check_type="completeness",
                layer="bigquery",
                passed=True,
                severity="info",
                message="Pass"
            ),
            ValidationResult(
                check_name="check2",
                check_type="file_presence",
                layer="gcs",
                passed=False,
                severity="error",
                message="Fail"
            )
        ]

        # Add status attribute for compatibility
        for r in results:
            r.status = "pass" if r.passed else "fail"

        report = ValidationReport(
            processor_name="test",
            processor_type="raw",
            validation_timestamp="2024-01-01T00:00:00Z",
            validation_run_id="test_run",
            date_range_start="2024-01-01",
            date_range_end="2024-01-31",
            season_year=None,
            total_checks=2,
            passed_checks=1,
            failed_checks=1,
            overall_status="fail",
            results=results,
            remediation_commands=[],
            summary={},
            execution_duration=1.0
        )

        stats = validator._get_layer_stats(report)

        assert stats['bigquery']['passed'] == 1
        assert stats['bigquery']['failed'] == 0
        assert stats['gcs']['passed'] == 0
        assert stats['gcs']['failed'] == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

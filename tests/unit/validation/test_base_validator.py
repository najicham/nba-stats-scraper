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


# ============================================================================
# Test Validation Check Methods
# ============================================================================

class TestCompletenessCheck:
    """Tests for _check_completeness method"""

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_completeness_all_dates_present(self, mock_storage, mock_bq, temp_config_file):
        """Test completeness check when all dates are present"""
        validator = BaseValidator(temp_config_file)

        # Mock query result - no missing dates
        mock_result = []
        validator._execute_query = Mock(return_value=mock_result)

        config = {
            'target_table': 'nba_raw.test_table',
            'reference_table': 'nba_raw.nbac_schedule',
            'match_field': 'game_date',
            'severity': 'error'
        }

        validator._check_completeness(config, '2024-01-01', '2024-01-31', None)

        assert len(validator.results) == 1
        result = validator.results[0]
        assert result.check_name == 'completeness_game_date'
        assert result.check_type == 'completeness'
        assert result.layer == 'bigquery'
        assert result.passed is True
        assert result.severity == 'error'
        assert result.message == 'All dates present'
        assert result.affected_count == 0

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_completeness_missing_dates(self, mock_storage, mock_bq, temp_config_file):
        """Test completeness check with missing dates"""
        validator = BaseValidator(temp_config_file)

        # Mock query result - 3 missing dates
        mock_row1 = Mock()
        mock_row1.missing_date = '2024-01-15'
        mock_row2 = Mock()
        mock_row2.missing_date = '2024-01-16'
        mock_row3 = Mock()
        mock_row3.missing_date = '2024-01-17'

        mock_result = [mock_row1, mock_row2, mock_row3]
        validator._execute_query = Mock(return_value=mock_result)
        validator._generate_backfill_commands = Mock(return_value=['backfill cmd1', 'backfill cmd2'])

        config = {
            'target_table': 'nba_raw.test_table',
            'reference_table': 'nba_raw.nbac_schedule',
            'match_field': 'game_date',
            'severity': 'error'
        }

        validator._check_completeness(config, '2024-01-01', '2024-01-31', None)

        assert len(validator.results) == 1
        result = validator.results[0]
        assert result.check_name == 'completeness_game_date'
        assert result.passed is False
        assert result.message == 'Found 3 missing game_dates'
        assert result.affected_count == 3
        assert result.affected_items == ['2024-01-15', '2024-01-16', '2024-01-17']
        assert result.remediation == ['backfill cmd1', 'backfill cmd2']

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_completeness_with_season_filter(self, mock_storage, mock_bq, temp_config_file):
        """Test completeness check with season year filter"""
        validator = BaseValidator(temp_config_file)

        mock_result = []
        validator._execute_query = Mock(return_value=mock_result)

        config = {
            'target_table': 'nba_raw.test_table',
            'reference_table': 'nba_raw.nbac_schedule',
            'match_field': 'game_date',
            'severity': 'warning'
        }

        validator._check_completeness(config, '2024-01-01', '2024-01-31', 2024)

        # Verify the query was called with correct parameters
        validator._execute_query.assert_called_once()
        query_arg = validator._execute_query.call_args[0][0]
        assert 'season_year = 2024' in query_arg

        result = validator.results[0]
        assert result.severity == 'warning'

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_completeness_with_reference_filter(self, mock_storage, mock_bq, temp_config_file):
        """Test completeness check with reference filter"""
        validator = BaseValidator(temp_config_file)

        mock_result = []
        validator._execute_query = Mock(return_value=mock_result)

        config = {
            'target_table': 'nba_raw.test_table',
            'reference_table': 'nba_raw.nbac_schedule',
            'match_field': 'game_date',
            'severity': 'error',
            'reference_filter': 'game_status = 3'
        }

        validator._check_completeness(config, '2024-01-01', '2024-01-31', None)

        # Verify the query includes the reference filter
        query_arg = validator._execute_query.call_args[0][0]
        assert 'game_status = 3' in query_arg

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_completeness_many_missing_dates(self, mock_storage, mock_bq, temp_config_file):
        """Test completeness check with many missing dates (tests truncation)"""
        validator = BaseValidator(temp_config_file)

        # Create 25 missing dates
        mock_result = []
        for i in range(25):
            mock_row = Mock()
            mock_row.missing_date = f'2024-01-{i+1:02d}'
            mock_result.append(mock_row)

        validator._execute_query = Mock(return_value=mock_result)
        validator._generate_backfill_commands = Mock(return_value=[])

        config = {
            'target_table': 'nba_raw.test_table',
            'reference_table': 'nba_raw.nbac_schedule',
            'match_field': 'game_date',
            'severity': 'error'
        }

        validator._check_completeness(config, '2024-01-01', '2024-01-31', None)

        result = validator.results[0]
        assert result.affected_count == 25
        # Should only store first 20 items
        assert len(result.affected_items) == 20


class TestTeamPresenceCheck:
    """Tests for _check_team_presence method"""

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_team_presence_all_teams_present(self, mock_storage, mock_bq, temp_config_file):
        """Test team presence check when all 30 teams are present"""
        validator = BaseValidator(temp_config_file)

        # Mock query result - 30 teams
        mock_result = []
        teams = ['ATL', 'BOS', 'BRK', 'CHO', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
                 'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
                 'OKC', 'ORL', 'PHI', 'PHO', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS']
        for team in teams:
            mock_row = Mock()
            mock_row.team = team
            mock_result.append(mock_row)

        validator._execute_query = Mock(return_value=mock_result)

        config = {
            'target_table': 'nba_raw.test_table',
            'expected_teams': 30,
            'severity': 'warning'
        }

        validator._check_team_presence(config, '2024-01-01', '2024-01-31', None)

        assert len(validator.results) == 1
        result = validator.results[0]
        assert result.check_name == 'team_presence'
        assert result.check_type == 'team_presence'
        assert result.layer == 'bigquery'
        assert result.passed is True
        assert result.severity == 'warning'
        assert result.message == 'Found 30/30 teams'
        assert result.affected_count == 0

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_team_presence_missing_teams(self, mock_storage, mock_bq, temp_config_file):
        """Test team presence check with missing teams"""
        validator = BaseValidator(temp_config_file)

        # Mock query result - only 25 teams
        mock_result = []
        teams = ['ATL', 'BOS', 'BRK', 'CHO', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
                 'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
                 'OKC', 'ORL', 'PHI', 'PHO', 'POR']
        for team in teams:
            mock_row = Mock()
            mock_row.team = team
            mock_result.append(mock_row)

        validator._execute_query = Mock(return_value=mock_result)

        config = {
            'target_table': 'nba_raw.test_table',
            'expected_teams': 30,
            'severity': 'warning'
        }

        validator._check_team_presence(config, '2024-01-01', '2024-01-31', None)

        result = validator.results[0]
        assert result.passed is False
        assert result.message == 'Found 25/30 teams'
        assert result.affected_count == 5
        assert len(result.affected_items) == 25

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_team_presence_with_season_filter(self, mock_storage, mock_bq, temp_config_file):
        """Test team presence check with season year filter"""
        validator = BaseValidator(temp_config_file)

        mock_result = []
        validator._execute_query = Mock(return_value=mock_result)

        config = {
            'target_table': 'nba_raw.test_table',
            'expected_teams': 30,
            'severity': 'warning'
        }

        validator._check_team_presence(config, '2024-01-01', '2024-01-31', 2024)

        # Verify the query includes season filter
        query_arg = validator._execute_query.call_args[0][0]
        assert 'season_year = 2024' in query_arg

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_team_presence_exactly_expected_teams(self, mock_storage, mock_bq, temp_config_file):
        """Test team presence check with exactly the expected number"""
        validator = BaseValidator(temp_config_file)

        # Mock query result - exactly 30 teams
        mock_result = []
        for i in range(30):
            mock_row = Mock()
            mock_row.team = f'TEAM{i}'
            mock_result.append(mock_row)

        validator._execute_query = Mock(return_value=mock_result)

        config = {
            'target_table': 'nba_raw.test_table',
            'expected_teams': 30,
            'severity': 'error'
        }

        validator._check_team_presence(config, '2024-01-01', '2024-01-31', None)

        result = validator.results[0]
        assert result.passed is True
        assert result.severity == 'error'


class TestFieldValidationCheck:
    """Tests for _check_field_validation method"""

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_field_validation_no_nulls(self, mock_storage, mock_bq, temp_config_file):
        """Test field validation when no NULL values found"""
        validator = BaseValidator(temp_config_file)

        # Mock query result - 0 null count
        # Need to return a fresh iterator each time the method is called
        def mock_execute_query(*args, **kwargs):
            mock_row = Mock()
            mock_row.null_count = 0
            return iter([mock_row])

        validator._execute_query = Mock(side_effect=mock_execute_query)

        config = {
            'target_table': 'nba_raw.test_table',
            'required_not_null': ['game_id', 'game_date']
        }

        validator._check_field_validation(config, '2024-01-01', '2024-01-31')

        # Should have 2 results (one for each field)
        assert len(validator.results) == 2

        result1 = validator.results[0]
        assert result1.check_name == 'field_not_null_game_id'
        assert result1.check_type == 'field_validation'
        assert result1.layer == 'bigquery'
        assert result1.passed is True
        assert result1.severity == 'error'
        assert result1.message == 'game_id has no NULLs'
        assert result1.affected_count == 0

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_field_validation_with_nulls(self, mock_storage, mock_bq, temp_config_file):
        """Test field validation with NULL values found"""
        validator = BaseValidator(temp_config_file)

        # Mock query result - 5 null values
        # Need to return a fresh iterator each time the method is called
        def mock_execute_query(*args, **kwargs):
            mock_row = Mock()
            mock_row.null_count = 5
            return iter([mock_row])

        validator._execute_query = Mock(side_effect=mock_execute_query)

        config = {
            'target_table': 'nba_raw.test_table',
            'required_not_null': ['game_id']
        }

        validator._check_field_validation(config, '2024-01-01', '2024-01-31')

        result = validator.results[0]
        assert result.passed is False
        assert result.message == 'Found 5 NULL game_id values'
        assert result.affected_count == 5

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_field_validation_multiple_fields(self, mock_storage, mock_bq, temp_config_file):
        """Test field validation with multiple fields"""
        validator = BaseValidator(temp_config_file)

        # Mock query results - different null counts for each field
        def mock_execute_query(query, start_date, end_date):
            if 'game_id' in query:
                mock_row = Mock()
                mock_row.null_count = 0
                return iter([mock_row])
            elif 'team_id' in query:
                mock_row = Mock()
                mock_row.null_count = 3
                return iter([mock_row])
            elif 'score' in query:
                mock_row = Mock()
                mock_row.null_count = 0
                return iter([mock_row])

        validator._execute_query = Mock(side_effect=mock_execute_query)

        config = {
            'target_table': 'nba_raw.test_table',
            'required_not_null': ['game_id', 'team_id', 'score']
        }

        validator._check_field_validation(config, '2024-01-01', '2024-01-31')

        # Should have 3 results
        assert len(validator.results) == 3

        # First field: game_id - passed
        assert validator.results[0].check_name == 'field_not_null_game_id'
        assert validator.results[0].passed is True

        # Second field: team_id - failed
        assert validator.results[1].check_name == 'field_not_null_team_id'
        assert validator.results[1].passed is False
        assert validator.results[1].affected_count == 3

        # Third field: score - passed
        assert validator.results[2].check_name == 'field_not_null_score'
        assert validator.results[2].passed is True

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_field_validation_empty_field_list(self, mock_storage, mock_bq, temp_config_file):
        """Test field validation with empty field list"""
        validator = BaseValidator(temp_config_file)

        config = {
            'target_table': 'nba_raw.test_table',
            'required_not_null': []
        }

        validator._check_field_validation(config, '2024-01-01', '2024-01-31')

        # Should have no results
        assert len(validator.results) == 0


class TestFilePresenceCheck:
    """Tests for _check_file_presence method"""

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_file_presence_all_files_present(self, mock_storage, mock_bq, temp_config_file):
        """Test file presence check when all files are present"""
        validator = BaseValidator(temp_config_file)

        # Mock expected dates
        validator._get_expected_dates = Mock(return_value=['2024-01-01', '2024-01-02', '2024-01-03'])

        # Mock GCS bucket - all files present
        mock_bucket = Mock()
        mock_blob = Mock()
        mock_bucket.list_blobs = Mock(return_value=[mock_blob])  # Returns a blob for each prefix
        validator.gcs_client.bucket = Mock(return_value=mock_bucket)

        config = {
            'bucket': 'test-bucket',
            'path_pattern': 'espn/scoreboard/{date}/*.json'
        }

        validator._check_file_presence(config, '2024-01-01', '2024-01-03', None)

        assert len(validator.results) == 1
        result = validator.results[0]
        assert result.check_name == 'gcs_file_presence'
        assert result.check_type == 'file_presence'
        assert result.layer == 'gcs'
        assert result.passed is True
        assert result.severity == 'error'
        assert result.message == 'All GCS files present'
        assert result.affected_count == 0

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_file_presence_missing_files(self, mock_storage, mock_bq, temp_config_file):
        """Test file presence check with missing files"""
        validator = BaseValidator(temp_config_file)

        # Mock expected dates
        validator._get_expected_dates = Mock(return_value=['2024-01-01', '2024-01-02', '2024-01-03'])

        # Mock GCS bucket - some files missing
        mock_bucket = Mock()
        def mock_list_blobs(prefix, max_results):
            # Return blobs for some dates, empty for others
            if '2024-01-02' in prefix:
                return []  # Missing
            else:
                mock_blob = Mock()
                return [mock_blob]

        mock_bucket.list_blobs = Mock(side_effect=mock_list_blobs)
        validator.gcs_client.bucket = Mock(return_value=mock_bucket)
        validator._generate_scraper_commands = Mock(return_value=['scrape cmd'])

        config = {
            'bucket': 'test-bucket',
            'path_pattern': 'espn/scoreboard/{date}/*.json'
        }

        validator._check_file_presence(config, '2024-01-01', '2024-01-03', None)

        result = validator.results[0]
        assert result.passed is False
        assert result.message == 'Found 1 dates with missing GCS files'
        assert result.affected_count == 1
        assert result.affected_items == ['2024-01-02']
        assert result.remediation == ['scrape cmd']

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_file_presence_with_wildcard_pattern(self, mock_storage, mock_bq, temp_config_file):
        """Test file presence check with wildcard pattern"""
        validator = BaseValidator(temp_config_file)

        validator._get_expected_dates = Mock(return_value=['2024-01-01'])

        mock_bucket = Mock()
        mock_blob = Mock()
        mock_bucket.list_blobs = Mock(return_value=[mock_blob])
        validator.gcs_client.bucket = Mock(return_value=mock_bucket)

        config = {
            'bucket': 'test-bucket',
            'path_pattern': 'nba-com/schedule/{date}/*.json'
        }

        validator._check_file_presence(config, '2024-01-01', '2024-01-01', None)

        # Verify that list_blobs was called with the correct prefix
        call_args = mock_bucket.list_blobs.call_args
        assert call_args[1]['prefix'] == 'nba-com/schedule/2024-01-01/'

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_file_presence_with_exact_path(self, mock_storage, mock_bq, temp_config_file):
        """Test file presence check with exact file path (no wildcard)"""
        validator = BaseValidator(temp_config_file)

        validator._get_expected_dates = Mock(return_value=['2024-01-01'])

        mock_bucket = Mock()
        mock_blob = Mock()
        mock_bucket.list_blobs = Mock(return_value=[mock_blob])
        validator.gcs_client.bucket = Mock(return_value=mock_bucket)

        config = {
            'bucket': 'test-bucket',
            'path_pattern': 'nba-com/schedule/{date}/data.json'
        }

        validator._check_file_presence(config, '2024-01-01', '2024-01-01', None)

        # Verify that list_blobs was called with the correct prefix
        call_args = mock_bucket.list_blobs.call_args
        assert call_args[1]['prefix'] == 'nba-com/schedule/2024-01-01/'

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_file_presence_gcs_error(self, mock_storage, mock_bq, temp_config_file):
        """Test file presence check with GCS error"""
        validator = BaseValidator(temp_config_file)

        validator._get_expected_dates = Mock(return_value=['2024-01-01'])

        # Mock GCS bucket to raise an exception
        validator.gcs_client.bucket = Mock(side_effect=Exception('GCS connection failed'))

        config = {
            'bucket': 'test-bucket',
            'path_pattern': 'espn/scoreboard/{date}/*.json'
        }

        validator._check_file_presence(config, '2024-01-01', '2024-01-01', None)

        result = validator.results[0]
        assert result.passed is False
        assert result.message == 'GCS check failed: GCS connection failed'
        assert result.severity == 'error'

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_check_file_presence_many_missing_dates(self, mock_storage, mock_bq, temp_config_file):
        """Test file presence check with many missing dates (tests truncation)"""
        validator = BaseValidator(temp_config_file)

        # Mock 25 expected dates
        expected_dates = [f'2024-01-{i+1:02d}' for i in range(25)]
        validator._get_expected_dates = Mock(return_value=expected_dates)

        # Mock GCS bucket - all files missing
        mock_bucket = Mock()
        mock_bucket.list_blobs = Mock(return_value=[])  # No blobs found
        validator.gcs_client.bucket = Mock(return_value=mock_bucket)
        validator._generate_scraper_commands = Mock(return_value=[])

        config = {
            'bucket': 'test-bucket',
            'path_pattern': 'espn/scoreboard/{date}/*.json'
        }

        validator._check_file_presence(config, '2024-01-01', '2024-01-25', None)

        result = validator.results[0]
        assert result.affected_count == 25
        # Should only store first 20 items
        assert len(result.affected_items) == 20


# ============================================================================
# Test Layer Validation Methods
# ============================================================================

class TestGcsLayerValidation:
    """Tests for _validate_gcs_layer method"""

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_validate_gcs_layer_with_file_presence_check(self, mock_storage, mock_bq, temp_config_file):
        """Test GCS layer validation with file_presence config"""
        validator = BaseValidator(temp_config_file)

        # Mock the _check_file_presence method
        validator._check_file_presence = Mock()

        # Update config to include GCS validations
        validator.config['gcs_validations'] = {
            'file_presence': {
                'bucket': 'test-bucket',
                'path_pattern': 'test/{date}/*.json'
            }
        }

        validator._validate_gcs_layer('2024-01-01', '2024-01-31', 2024)

        # Verify _check_file_presence was called with correct parameters
        validator._check_file_presence.assert_called_once_with(
            validator.config['gcs_validations']['file_presence'],
            '2024-01-01',
            '2024-01-31',
            2024
        )

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_validate_gcs_layer_without_file_presence_check(self, mock_storage, mock_bq, temp_config_file):
        """Test GCS layer validation without file_presence config"""
        validator = BaseValidator(temp_config_file)

        # Mock the _check_file_presence method
        validator._check_file_presence = Mock()

        # Update config with empty GCS validations
        validator.config['gcs_validations'] = {}

        validator._validate_gcs_layer('2024-01-01', '2024-01-31', None)

        # Verify _check_file_presence was NOT called
        validator._check_file_presence.assert_not_called()

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_validate_gcs_layer_with_no_gcs_config(self, mock_storage, mock_bq, temp_config_file):
        """Test GCS layer validation with no gcs_validations in config"""
        validator = BaseValidator(temp_config_file)

        # Mock the _check_file_presence method
        validator._check_file_presence = Mock()

        # Remove gcs_validations from config
        if 'gcs_validations' in validator.config:
            del validator.config['gcs_validations']

        validator._validate_gcs_layer('2024-01-01', '2024-01-31', None)

        # Verify _check_file_presence was NOT called
        validator._check_file_presence.assert_not_called()


class TestBigQueryLayerValidation:
    """Tests for _validate_bigquery_layer method"""

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_validate_bigquery_layer_with_completeness_check(self, mock_storage, mock_bq, temp_config_file):
        """Test BigQuery layer validation with completeness check"""
        validator = BaseValidator(temp_config_file)

        # Mock the check methods
        validator._check_completeness = Mock()
        validator._check_team_presence = Mock()
        validator._check_field_validation = Mock()

        # Update config to include only completeness
        validator.config['bigquery_validations'] = {
            'completeness': {
                'target_table': 'nba_raw.test_table',
                'reference_table': 'nba_raw.schedule'
            }
        }

        validator._validate_bigquery_layer('2024-01-01', '2024-01-31', 2024)

        # Verify only _check_completeness was called
        validator._check_completeness.assert_called_once_with(
            validator.config['bigquery_validations']['completeness'],
            '2024-01-01',
            '2024-01-31',
            2024
        )
        validator._check_team_presence.assert_not_called()
        validator._check_field_validation.assert_not_called()

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_validate_bigquery_layer_with_team_presence_check(self, mock_storage, mock_bq, temp_config_file):
        """Test BigQuery layer validation with team_presence check"""
        validator = BaseValidator(temp_config_file)

        # Mock the check methods
        validator._check_completeness = Mock()
        validator._check_team_presence = Mock()
        validator._check_field_validation = Mock()

        # Update config to include only team_presence
        validator.config['bigquery_validations'] = {
            'team_presence': {
                'target_table': 'nba_raw.test_table',
                'expected_teams': 30
            }
        }

        validator._validate_bigquery_layer('2024-01-01', '2024-01-31', 2024)

        # Verify only _check_team_presence was called
        validator._check_team_presence.assert_called_once_with(
            validator.config['bigquery_validations']['team_presence'],
            '2024-01-01',
            '2024-01-31',
            2024
        )
        validator._check_completeness.assert_not_called()
        validator._check_field_validation.assert_not_called()

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_validate_bigquery_layer_with_field_validation_check(self, mock_storage, mock_bq, temp_config_file):
        """Test BigQuery layer validation with field_validation check"""
        validator = BaseValidator(temp_config_file)

        # Mock the check methods
        validator._check_completeness = Mock()
        validator._check_team_presence = Mock()
        validator._check_field_validation = Mock()

        # Update config to include only field_validation
        validator.config['bigquery_validations'] = {
            'field_validation': {
                'target_table': 'nba_raw.test_table',
                'fields': ['player_id', 'team_id']
            }
        }

        validator._validate_bigquery_layer('2024-01-01', '2024-01-31', None)

        # Verify only _check_field_validation was called
        validator._check_field_validation.assert_called_once_with(
            validator.config['bigquery_validations']['field_validation'],
            '2024-01-01',
            '2024-01-31'
        )
        validator._check_completeness.assert_not_called()
        validator._check_team_presence.assert_not_called()

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_validate_bigquery_layer_with_all_checks(self, mock_storage, mock_bq, temp_config_file):
        """Test BigQuery layer validation with all three checks"""
        validator = BaseValidator(temp_config_file)

        # Mock the check methods
        validator._check_completeness = Mock()
        validator._check_team_presence = Mock()
        validator._check_field_validation = Mock()

        # Update config to include all checks
        validator.config['bigquery_validations'] = {
            'completeness': {
                'target_table': 'nba_raw.test_table',
                'reference_table': 'nba_raw.schedule'
            },
            'team_presence': {
                'target_table': 'nba_raw.test_table',
                'expected_teams': 30
            },
            'field_validation': {
                'target_table': 'nba_raw.test_table',
                'fields': ['player_id', 'team_id']
            }
        }

        validator._validate_bigquery_layer('2024-01-01', '2024-01-31', 2024)

        # Verify all three check methods were called
        validator._check_completeness.assert_called_once()
        validator._check_team_presence.assert_called_once()
        validator._check_field_validation.assert_called_once()

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_validate_bigquery_layer_with_no_checks(self, mock_storage, mock_bq, temp_config_file):
        """Test BigQuery layer validation with empty config"""
        validator = BaseValidator(temp_config_file)

        # Mock the check methods
        validator._check_completeness = Mock()
        validator._check_team_presence = Mock()
        validator._check_field_validation = Mock()

        # Update config with empty bigquery_validations
        validator.config['bigquery_validations'] = {}

        validator._validate_bigquery_layer('2024-01-01', '2024-01-31', None)

        # Verify no check methods were called
        validator._check_completeness.assert_not_called()
        validator._check_team_presence.assert_not_called()
        validator._check_field_validation.assert_not_called()


class TestScheduleLayerValidation:
    """Tests for _validate_schedule_layer method"""

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_validate_schedule_layer_with_data_freshness_enabled(self, mock_storage, mock_bq, temp_config_file):
        """Test schedule layer validation with data_freshness enabled"""
        validator = BaseValidator(temp_config_file)

        # Mock the check methods
        validator._check_data_freshness = Mock()
        validator._check_processing_schedule = Mock()

        # Update config with data_freshness enabled
        validator.config['schedule_checks'] = {
            'data_freshness': {
                'enabled': True,
                'target_table': 'nba_raw.test_table',
                'max_staleness_hours': 24
            }
        }

        validator._validate_schedule_layer('2024-01-01', '2024-01-31')

        # Verify _check_data_freshness was called
        validator._check_data_freshness.assert_called_once_with(
            validator.config['schedule_checks']['data_freshness'],
            '2024-01-01',
            '2024-01-31'
        )
        validator._check_processing_schedule.assert_not_called()

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_validate_schedule_layer_with_data_freshness_disabled(self, mock_storage, mock_bq, temp_config_file):
        """Test schedule layer validation with data_freshness disabled"""
        validator = BaseValidator(temp_config_file)

        # Mock the check methods
        validator._check_data_freshness = Mock()
        validator._check_processing_schedule = Mock()

        # Update config with data_freshness disabled
        validator.config['schedule_checks'] = {
            'data_freshness': {
                'enabled': False,
                'target_table': 'nba_raw.test_table'
            }
        }

        validator._validate_schedule_layer('2024-01-01', '2024-01-31')

        # Verify _check_data_freshness was NOT called
        validator._check_data_freshness.assert_not_called()
        validator._check_processing_schedule.assert_not_called()

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_validate_schedule_layer_with_processing_schedule_enabled(self, mock_storage, mock_bq, temp_config_file):
        """Test schedule layer validation with processing_schedule enabled"""
        validator = BaseValidator(temp_config_file)

        # Mock the check methods
        validator._check_data_freshness = Mock()
        validator._check_processing_schedule = Mock()

        # Update config with processing_schedule enabled
        validator.config['schedule_checks'] = {
            'processing_schedule': {
                'enabled': True,
                'target_table': 'nba_raw.test_table',
                'expected_processing_time': '02:00'
            }
        }

        validator._validate_schedule_layer('2024-01-01', '2024-01-31')

        # Verify _check_processing_schedule was called
        validator._check_processing_schedule.assert_called_once_with(
            validator.config['schedule_checks']['processing_schedule'],
            '2024-01-01',
            '2024-01-31'
        )
        validator._check_data_freshness.assert_not_called()

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_validate_schedule_layer_with_both_checks_enabled(self, mock_storage, mock_bq, temp_config_file):
        """Test schedule layer validation with both checks enabled"""
        validator = BaseValidator(temp_config_file)

        # Mock the check methods
        validator._check_data_freshness = Mock()
        validator._check_processing_schedule = Mock()

        # Update config with both checks enabled
        validator.config['schedule_checks'] = {
            'data_freshness': {
                'enabled': True,
                'target_table': 'nba_raw.test_table',
                'max_staleness_hours': 24
            },
            'processing_schedule': {
                'enabled': True,
                'target_table': 'nba_raw.test_table',
                'expected_processing_time': '02:00'
            }
        }

        validator._validate_schedule_layer('2024-01-01', '2024-01-31')

        # Verify both check methods were called
        validator._check_data_freshness.assert_called_once()
        validator._check_processing_schedule.assert_called_once()

    @patch('validation.base_validator.bigquery.Client')
    @patch('validation.base_validator.storage.Client')
    def test_validate_schedule_layer_with_no_schedule_checks(self, mock_storage, mock_bq, temp_config_file):
        """Test schedule layer validation with no schedule_checks config"""
        validator = BaseValidator(temp_config_file)

        # Mock the check methods
        validator._check_data_freshness = Mock()
        validator._check_processing_schedule = Mock()

        # Remove schedule_checks from config
        if 'schedule_checks' in validator.config:
            del validator.config['schedule_checks']

        validator._validate_schedule_layer('2024-01-01', '2024-01-31')

        # Verify no check methods were called
        validator._check_data_freshness.assert_not_called()
        validator._check_processing_schedule.assert_not_called()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

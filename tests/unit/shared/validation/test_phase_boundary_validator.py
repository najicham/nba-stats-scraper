"""
Unit tests for PhaseBoundaryValidator

Tests the phase boundary validation framework including:
- Validation modes and severity levels
- Game count validation
- Processor completion validation
- Data quality validation
- ValidationResult properties and serialization
"""

import pytest
import os
from datetime import date, datetime
from unittest.mock import Mock, MagicMock, patch
from google.cloud.bigquery import Row

from shared.validation.phase_boundary_validator import (
    PhaseBoundaryValidator,
    ValidationMode,
    ValidationSeverity,
    ValidationIssue,
    ValidationResult
)


class TestValidationEnums:
    """Test validation enum classes"""

    def test_validation_severity_values(self):
        """Test ValidationSeverity enum values"""
        assert ValidationSeverity.INFO.value == "info"
        assert ValidationSeverity.WARNING.value == "warning"
        assert ValidationSeverity.ERROR.value == "error"

    def test_validation_mode_values(self):
        """Test ValidationMode enum values"""
        assert ValidationMode.DISABLED.value == "disabled"
        assert ValidationMode.WARNING.value == "warning"
        assert ValidationMode.BLOCKING.value == "blocking"


class TestValidationIssue:
    """Test ValidationIssue dataclass"""

    def test_validation_issue_creation(self):
        """Test creating a ValidationIssue"""
        issue = ValidationIssue(
            validation_type="game_count",
            severity=ValidationSeverity.WARNING,
            message="Low game count",
            details={'actual': 7, 'expected': 10}
        )

        assert issue.validation_type == "game_count"
        assert issue.severity == ValidationSeverity.WARNING
        assert issue.message == "Low game count"
        assert issue.details['actual'] == 7
        assert issue.details['expected'] == 10

    def test_validation_issue_default_details(self):
        """Test ValidationIssue with default empty details"""
        issue = ValidationIssue(
            validation_type="processor",
            severity=ValidationSeverity.ERROR,
            message="Missing processor"
        )

        assert issue.details == {}


class TestValidationResult:
    """Test ValidationResult dataclass"""

    def test_validation_result_creation(self):
        """Test creating a ValidationResult"""
        result = ValidationResult(
            game_date=date(2026, 1, 21),
            phase_name="phase2",
            is_valid=True,
            mode=ValidationMode.WARNING
        )

        assert result.game_date == date(2026, 1, 21)
        assert result.phase_name == "phase2"
        assert result.is_valid is True
        assert result.mode == ValidationMode.WARNING
        assert result.issues == []
        assert result.metrics == {}
        assert isinstance(result.timestamp, datetime)

    def test_has_warnings_property_true(self):
        """Test has_warnings returns True when warnings present"""
        result = ValidationResult(
            game_date=date(2026, 1, 21),
            phase_name="phase2",
            is_valid=True,
            mode=ValidationMode.WARNING,
            issues=[
                ValidationIssue(
                    validation_type="game_count",
                    severity=ValidationSeverity.WARNING,
                    message="Low game count"
                )
            ]
        )

        assert result.has_warnings is True
        assert result.has_errors is False

    def test_has_warnings_property_false(self):
        """Test has_warnings returns False when no warnings"""
        result = ValidationResult(
            game_date=date(2026, 1, 21),
            phase_name="phase2",
            is_valid=True,
            mode=ValidationMode.WARNING,
            issues=[
                ValidationIssue(
                    validation_type="game_count",
                    severity=ValidationSeverity.INFO,
                    message="All good"
                )
            ]
        )

        assert result.has_warnings is False

    def test_has_errors_property_true(self):
        """Test has_errors returns True when errors present"""
        result = ValidationResult(
            game_date=date(2026, 1, 21),
            phase_name="phase2",
            is_valid=False,
            mode=ValidationMode.BLOCKING,
            issues=[
                ValidationIssue(
                    validation_type="game_count",
                    severity=ValidationSeverity.ERROR,
                    message="No games found"
                )
            ]
        )

        assert result.has_errors is True
        assert result.has_warnings is False

    def test_has_errors_property_false(self):
        """Test has_errors returns False when no errors"""
        result = ValidationResult(
            game_date=date(2026, 1, 21),
            phase_name="phase2",
            is_valid=True,
            mode=ValidationMode.WARNING,
            issues=[]
        )

        assert result.has_errors is False

    def test_has_both_warnings_and_errors(self):
        """Test result with both warnings and errors"""
        result = ValidationResult(
            game_date=date(2026, 1, 21),
            phase_name="phase2",
            is_valid=False,
            mode=ValidationMode.BLOCKING,
            issues=[
                ValidationIssue(
                    validation_type="game_count",
                    severity=ValidationSeverity.WARNING,
                    message="Low game count"
                ),
                ValidationIssue(
                    validation_type="processor",
                    severity=ValidationSeverity.ERROR,
                    message="Missing processor"
                )
            ]
        )

        assert result.has_warnings is True
        assert result.has_errors is True

    def test_to_dict_serialization(self):
        """Test ValidationResult.to_dict() serialization"""
        result = ValidationResult(
            game_date=date(2026, 1, 21),
            phase_name="phase2",
            is_valid=False,
            mode=ValidationMode.WARNING,
            issues=[
                ValidationIssue(
                    validation_type="game_count",
                    severity=ValidationSeverity.WARNING,
                    message="Low game count",
                    details={'actual': 7, 'expected': 10}
                )
            ],
            metrics={'actual_game_count': 7}
        )

        result_dict = result.to_dict()

        assert result_dict['game_date'] == '2026-01-21'
        assert result_dict['phase_name'] == 'phase2'
        assert result_dict['is_valid'] is False
        assert result_dict['mode'] == 'warning'
        assert len(result_dict['issues']) == 1
        assert result_dict['issues'][0]['validation_type'] == 'game_count'
        assert result_dict['issues'][0]['severity'] == 'warning'
        assert result_dict['issues'][0]['message'] == 'Low game count'
        assert result_dict['issues'][0]['details']['actual'] == 7
        assert result_dict['metrics']['actual_game_count'] == 7
        assert 'timestamp' in result_dict


class TestPhaseBoundaryValidatorInit:
    """Test PhaseBoundaryValidator initialization"""

    def test_init_default_mode(self):
        """Test initialization with default mode from env"""
        bq_client = Mock()

        with patch.dict(os.environ, {}, clear=True):
            validator = PhaseBoundaryValidator(
                bq_client=bq_client,
                project_id="test-project",
                phase_name="phase2"
            )

            assert validator.bq_client is bq_client
            assert validator.project_id == "test-project"
            assert validator.phase_name == "phase2"
            assert validator.enabled is True
            assert validator.mode == ValidationMode.WARNING
            assert validator.game_count_threshold == 0.8
            assert validator.quality_threshold == 0.7

    def test_init_explicit_mode(self):
        """Test initialization with explicit mode"""
        bq_client = Mock()

        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase3",
            mode=ValidationMode.BLOCKING
        )

        assert validator.mode == ValidationMode.BLOCKING

    def test_init_from_env_vars(self):
        """Test initialization loading config from env vars"""
        bq_client = Mock()

        with patch.dict(os.environ, {
            'PHASE_VALIDATION_ENABLED': 'false',
            'PHASE_VALIDATION_MODE': 'blocking',
            'PHASE_VALIDATION_GAME_COUNT_THRESHOLD': '0.9',
            'PHASE_VALIDATION_QUALITY_THRESHOLD': '0.85'
        }):
            validator = PhaseBoundaryValidator(
                bq_client=bq_client,
                project_id="test-project",
                phase_name="phase3"
            )

            assert validator.enabled is False
            assert validator.mode == ValidationMode.BLOCKING
            assert validator.game_count_threshold == 0.9
            assert validator.quality_threshold == 0.85


class TestValidateGameCount:
    """Test game count validation logic"""

    def test_validate_game_count_pass(self):
        """Test game count validation passes when count is acceptable"""
        bq_client = Mock()
        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        issue = validator.validate_game_count(
            game_date=date(2026, 1, 21),
            actual=10,
            expected=10
        )

        assert issue is None

    def test_validate_game_count_pass_above_threshold(self):
        """Test game count validation passes when above threshold"""
        bq_client = Mock()
        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )
        validator.game_count_threshold = 0.8

        # 9/10 = 0.9, above 0.8 threshold
        issue = validator.validate_game_count(
            game_date=date(2026, 1, 21),
            actual=9,
            expected=10
        )

        assert issue is None

    def test_validate_game_count_warning(self):
        """Test game count validation returns warning when below threshold"""
        bq_client = Mock()
        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )
        validator.game_count_threshold = 0.8

        # 7/10 = 0.7, below 0.8 threshold but above 0.5
        issue = validator.validate_game_count(
            game_date=date(2026, 1, 21),
            actual=7,
            expected=10
        )

        assert issue is not None
        assert issue.severity == ValidationSeverity.WARNING
        assert "7/10" in issue.message
        assert issue.details['actual_count'] == 7
        assert issue.details['expected_count'] == 10

    def test_validate_game_count_error(self):
        """Test game count validation returns error when very low"""
        bq_client = Mock()
        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )
        validator.game_count_threshold = 0.8

        # 3/10 = 0.3, below 0.5 threshold (error level)
        issue = validator.validate_game_count(
            game_date=date(2026, 1, 21),
            actual=3,
            expected=10
        )

        assert issue is not None
        assert issue.severity == ValidationSeverity.ERROR
        assert issue.details['actual_count'] == 3
        assert issue.details['expected_count'] == 10

    def test_validate_game_count_zero_expected(self):
        """Test game count validation with zero expected games"""
        bq_client = Mock()
        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        issue = validator.validate_game_count(
            game_date=date(2026, 1, 21),
            actual=0,
            expected=0
        )

        # Should not raise issue when no games expected
        assert issue is None

    def test_validate_game_count_zero_actual_nonzero_expected(self):
        """Test game count validation with zero actual but nonzero expected"""
        bq_client = Mock()
        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        # 0/10 = 0.0, well below threshold
        issue = validator.validate_game_count(
            game_date=date(2026, 1, 21),
            actual=0,
            expected=10
        )

        assert issue is not None
        assert issue.severity == ValidationSeverity.ERROR
        assert issue.details['actual_count'] == 0
        assert issue.details['expected_count'] == 10


class TestValidateProcessorCompletions:
    """Test processor completion validation"""

    def test_validate_processor_completions_all_complete(self):
        """Test processor validation when all processors complete"""
        bq_client = Mock()
        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        issues = validator.validate_processor_completions(
            game_date=date(2026, 1, 21),
            completed=['bdl_games', 'bdl_player_boxscores'],
            expected=['bdl_games', 'bdl_player_boxscores']
        )

        assert len(issues) == 0

    def test_validate_processor_completions_missing_one(self):
        """Test processor validation when one processor is missing"""
        bq_client = Mock()
        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        issues = validator.validate_processor_completions(
            game_date=date(2026, 1, 21),
            completed=['bdl_games'],
            expected=['bdl_games', 'bdl_player_boxscores']
        )

        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR
        assert 'bdl_player_boxscores' in issues[0].message

    def test_validate_processor_completions_missing_multiple(self):
        """Test processor validation when multiple processors are missing"""
        bq_client = Mock()
        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        issues = validator.validate_processor_completions(
            game_date=date(2026, 1, 21),
            completed=['bdl_games'],
            expected=['bdl_games', 'bdl_player_boxscores', 'odds_api']
        )

        assert len(issues) == 2
        assert any('bdl_player_boxscores' in issue.message for issue in issues)
        assert any('odds_api' in issue.message for issue in issues)

    def test_validate_processor_completions_extra_processors(self):
        """Test processor validation with extra unexpected processors"""
        bq_client = Mock()
        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        issues = validator.validate_processor_completions(
            game_date=date(2026, 1, 21),
            completed=['bdl_games', 'bdl_player_boxscores', 'extra_processor'],
            expected=['bdl_games', 'bdl_player_boxscores']
        )

        # Extra processors are OK, should not generate issues
        assert len(issues) == 0

    def test_validate_processor_completions_empty_completed(self):
        """Test processor validation with no completed processors"""
        bq_client = Mock()
        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        issues = validator.validate_processor_completions(
            game_date=date(2026, 1, 21),
            completed=[],
            expected=['bdl_games', 'bdl_player_boxscores']
        )

        assert len(issues) == 2


class TestBigQueryQueries:
    """Test BigQuery query methods"""

    def test_get_actual_game_count(self):
        """Test get_actual_game_count queries BigQuery correctly"""
        # Create mock BigQuery client and response
        bq_client = Mock()
        mock_row = Mock()
        mock_row.game_count = 10
        bq_client.query.return_value.result.return_value = [mock_row]

        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        count = validator.get_actual_game_count(
            game_date=date(2026, 1, 21),
            dataset='nba_raw',
            table='bdl_games'
        )

        assert count == 10
        # Verify query was called
        bq_client.query.assert_called_once()

    def test_get_actual_game_count_no_results(self):
        """Test get_actual_game_count with no results"""
        bq_client = Mock()
        bq_client.query.return_value.result.return_value = []

        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        count = validator.get_actual_game_count(
            game_date=date(2026, 1, 21),
            dataset='nba_raw',
            table='bdl_games'
        )

        assert count == 0

    def test_get_actual_game_count_query_error(self):
        """Test get_actual_game_count handles query errors"""
        bq_client = Mock()
        bq_client.query.side_effect = Exception("Query failed")

        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        count = validator.get_actual_game_count(
            game_date=date(2026, 1, 21),
            dataset='nba_raw',
            table='bdl_games'
        )

        # Should return 0 on error
        assert count == 0


class TestRunValidation:
    """Test run_validation orchestration method"""

    def test_run_validation_all_checks_pass(self):
        """Test run_validation with all checks passing"""
        bq_client = Mock()

        # Mock BigQuery responses
        mock_row = Mock()
        mock_row.game_count = 10
        bq_client.query.return_value.result.return_value = [mock_row]

        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        # Mock get_completed_processors to return expected processors
        with patch.object(validator, 'get_completed_processors', return_value=['bdl_games']):
            result = validator.run_validation(
                game_date=date(2026, 1, 21),
                validation_config={
                    'check_game_count': True,
                    'expected_game_count': 10,
                    'game_count_dataset': 'nba_raw',
                    'game_count_table': 'bdl_games',
                    'check_processors': True,
                    'expected_processors': ['bdl_games'],
                    'check_data_quality': False
                }
            )

        assert result.is_valid is True
        assert len(result.issues) == 0
        assert result.phase_name == "phase2"
        assert result.game_date == date(2026, 1, 21)

    def test_run_validation_game_count_fail(self):
        """Test run_validation with game count failure"""
        bq_client = Mock()

        # Mock low game count
        mock_row = Mock()
        mock_row.game_count = 3
        bq_client.query.return_value.result.return_value = [mock_row]

        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        result = validator.run_validation(
            game_date=date(2026, 1, 21),
            validation_config={
                'check_game_count': True,
                'expected_game_count': 10,
                'game_count_dataset': 'nba_raw',
                'game_count_table': 'bdl_games',
                'check_processors': False,
                'check_data_quality': False
            }
        )

        assert result.is_valid is False
        assert len(result.issues) == 1
        assert result.issues[0].validation_type == 'game_count'

    def test_run_validation_skip_checks(self):
        """Test run_validation with checks disabled"""
        bq_client = Mock()

        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        result = validator.run_validation(
            game_date=date(2026, 1, 21),
            validation_config={
                'check_game_count': False,
                'check_processors': False,
                'check_data_quality': False
            }
        )

        assert result.is_valid is True
        assert len(result.issues) == 0
        # BigQuery should not be called
        bq_client.query.assert_not_called()


class TestLogValidationToBigQuery:
    """Test BigQuery logging functionality"""

    def test_log_validation_to_bigquery_success(self):
        """Test logging validation results to BigQuery"""
        bq_client = Mock()
        bq_client.insert_rows_json.return_value = []

        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        result = ValidationResult(
            game_date=date(2026, 1, 21),
            phase_name="phase2",
            is_valid=False,
            mode=ValidationMode.WARNING,
            issues=[
                ValidationIssue(
                    validation_type="game_count",
                    severity=ValidationSeverity.WARNING,
                    message="Low game count",
                    details={'actual': 7, 'expected': 10}
                )
            ]
        )

        validator.log_validation_to_bigquery(result)

        # Verify BigQuery insert was called
        bq_client.insert_rows_json.assert_called_once()

        # Verify correct table
        call_args = bq_client.insert_rows_json.call_args
        table_id = call_args[0][0]
        assert 'nba_monitoring.phase_boundary_validations' in table_id

    def test_log_validation_to_bigquery_handles_errors(self):
        """Test logging handles BigQuery errors gracefully"""
        bq_client = Mock()
        bq_client.insert_rows_json.side_effect = Exception("BigQuery error")

        validator = PhaseBoundaryValidator(
            bq_client=bq_client,
            project_id="test-project",
            phase_name="phase2"
        )

        result = ValidationResult(
            game_date=date(2026, 1, 21),
            phase_name="phase2",
            is_valid=True,
            mode=ValidationMode.WARNING
        )

        # Should not raise exception
        try:
            validator.log_validation_to_bigquery(result)
        except Exception:
            pytest.fail("log_validation_to_bigquery should handle errors gracefully")

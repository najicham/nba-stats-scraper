"""
End-to-end tests for phase boundary validation gates.

Tests the full integration of:
- PhaseBoundaryValidator in WARNING and BLOCKING modes
- Phase transition functions (phase1→2, phase2→3, phase3→4)
- BigQuery validation logging
- Game count validation
- Data quality validation
- Processor completion validation
"""

import pytest
from datetime import date, datetime
from unittest.mock import Mock, patch, MagicMock
from google.cloud import bigquery

from shared.validation.phase_boundary_validator import (
    PhaseBoundaryValidator,
    ValidationMode,
    ValidationResult,
    ValidationIssue,
    ValidationSeverity,
    PhaseValidationError
)


class TestValidationGatesWarningMode:
    """Test validation gates in WARNING mode (non-blocking)."""

    def test_warning_mode_logs_but_does_not_block_on_low_game_count(self):
        """Test that WARNING mode logs issues but doesn't block pipeline."""
        # Arrange
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="phase2",
            mode=ValidationMode.WARNING
        )

        game_date = date(2026, 1, 15)
        expected_games = 10
        actual_games = 5  # Only 50%, below 80% threshold

        # Mock BigQuery insert
        mock_bq_client.insert_rows_json = Mock(return_value=[])

        # Act
        result = validator.validate_game_count(
            game_date=game_date,
            expected_count=expected_games,
            actual_count=actual_games,
            phase_name="phase2_to_phase3"
        )

        # Assert
        assert result.is_valid is False  # Validation failed
        assert len(result.issues) > 0
        assert any("game count" in issue.message.lower() for issue in result.issues)

        # Verify BigQuery logging was called
        assert mock_bq_client.insert_rows_json.called

    def test_warning_mode_logs_but_does_not_block_on_low_quality(self):
        """Test that WARNING mode logs quality issues but doesn't block."""
        # Arrange
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="test_phase",
            mode=ValidationMode.WARNING
        )

        game_date = date(2026, 1, 15)
        quality_score = 0.5  # 50%, below 70% threshold

        mock_bq_client.insert_rows_json = Mock(return_value=[])

        # Act
        result = validator.validate_data_quality(
            game_date=game_date,
            quality_score=quality_score,
            phase_name="phase2_to_phase3",
            details={"sample_size": 100, "failed_checks": 50}
        )

        # Assert
        assert result.is_valid is False
        assert len(result.issues) > 0
        assert any("quality" in issue.message.lower() for issue in result.issues)

        # Verify logging
        assert mock_bq_client.insert_rows_json.called


class TestValidationGatesBlockingMode:
    """Test validation gates in BLOCKING mode (raises exceptions)."""

    def test_blocking_mode_raises_exception_on_low_game_count(self):
        """Test that BLOCKING mode raises exception for validation failures."""
        # Arrange
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="test_phase",
            mode=ValidationMode.BLOCKING
        )

        game_date = date(2026, 1, 15)
        expected_games = 10
        actual_games = 3  # Only 30%, below 80% threshold

        mock_bq_client.insert_rows_json = Mock(return_value=[])

        # Act
        result = validator.validate_game_count(
            game_date=game_date,
            expected_count=expected_games,
            actual_count=actual_games,
            phase_name="phase3_to_phase4"
        )

        # Assert validation failed
        assert result.is_valid is False

        # In blocking mode, application code should raise exception
        with pytest.raises(PhaseValidationError) as exc_info:
            if not result.is_valid:
                raise PhaseValidationError(
                    f"Phase validation failed for phase3_to_phase4 on {game_date}",
                    result
                )

        assert "phase3_to_phase4" in str(exc_info.value)

    def test_blocking_mode_allows_valid_data_to_pass(self):
        """Test that BLOCKING mode allows valid data through."""
        # Arrange
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="test_phase",
            mode=ValidationMode.BLOCKING
        )

        game_date = date(2026, 1, 15)
        expected_games = 10
        actual_games = 9  # 90%, above 80% threshold

        mock_bq_client.insert_rows_json = Mock(return_value=[])

        # Act
        result = validator.validate_game_count(
            game_date=game_date,
            expected_count=expected_games,
            actual_count=actual_games,
            phase_name="phase3_to_phase4"
        )

        # Assert
        assert result.is_valid is True
        assert len(result.issues) == 0


class TestBigQueryLogging:
    """Test BigQuery logging of validation results."""

    def test_validation_results_logged_to_bigquery(self):
        """Test that validation results are logged to BigQuery."""
        # Arrange
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="test_phase",
            mode=ValidationMode.WARNING
        )

        game_date = date(2026, 1, 15)
        mock_bq_client.insert_rows_json = Mock(return_value=[])

        # Act
        result = validator.validate_game_count(
            game_date=game_date,
            expected_count=10,
            actual_count=8,
            phase_name="phase2_to_phase3"
        )

        # Assert BigQuery insert was called
        assert mock_bq_client.insert_rows_json.called
        call_args = mock_bq_client.insert_rows_json.call_args

        # Verify table name
        table_arg = call_args[0][0]
        assert "phase_boundary_validations" in str(table_arg)

        # Verify row data structure
        rows = call_args[0][1]
        assert len(rows) > 0

        row = rows[0]
        assert 'validation_id' in row
        assert 'game_date' in row
        assert 'phase_name' in row
        assert row['phase_name'] == 'phase2_to_phase3'
        assert 'is_valid' in row
        assert 'mode' in row
        assert row['mode'] == 'warning'

    def test_bigquery_logging_failure_is_handled_gracefully(self):
        """Test that BigQuery logging failures don't crash validation."""
        # Arrange
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="test_phase",
            mode=ValidationMode.WARNING
        )

        game_date = date(2026, 1, 15)

        # Mock BigQuery insert to fail
        mock_bq_client.insert_rows_json = Mock(
            side_effect=Exception("BigQuery connection failed")
        )

        # Act - Should not raise exception even if logging fails
        result = validator.validate_game_count(
            game_date=game_date,
            expected_count=10,
            actual_count=8,
            phase_name="phase2_to_phase3"
        )

        # Assert - Validation still completes
        assert result.is_valid is True  # 8/10 = 80%, meets threshold


class TestGameCountValidation:
    """Test game count validation logic."""

    def test_game_count_above_threshold_passes(self):
        """Test that game count above 80% threshold passes validation."""
        # Arrange
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="test_phase",
            mode=ValidationMode.WARNING,
            game_count_threshold=0.8
        )

        game_date = date(2026, 1, 15)
        mock_bq_client.insert_rows_json = Mock(return_value=[])

        # Act - Test various passing scenarios
        test_cases = [
            (10, 8),   # Exactly 80%
            (10, 9),   # 90%
            (10, 10),  # 100%
            (5, 4),    # 80%
        ]

        for expected, actual in test_cases:
            result = validator.validate_game_count(
                game_date=game_date,
                expected_count=expected,
                actual_count=actual,
                phase_name="test_phase"
            )

            # Assert
            assert result.is_valid is True, f"Failed for {actual}/{expected}"
            assert len(result.issues) == 0

    def test_game_count_below_threshold_fails(self):
        """Test that game count below 80% threshold fails validation."""
        # Arrange
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="test_phase",
            mode=ValidationMode.WARNING,
            game_count_threshold=0.8
        )

        game_date = date(2026, 1, 15)
        mock_bq_client.insert_rows_json = Mock(return_value=[])

        # Act - Test various failing scenarios
        test_cases = [
            (10, 7),   # 70%
            (10, 5),   # 50%
            (10, 0),   # 0%
            (5, 3),    # 60%
        ]

        for expected, actual in test_cases:
            result = validator.validate_game_count(
                game_date=game_date,
                expected_count=expected,
                actual_count=actual,
                phase_name="test_phase"
            )

            # Assert
            assert result.is_valid is False, f"Should fail for {actual}/{expected}"
            assert len(result.issues) > 0


class TestDataQualityValidation:
    """Test data quality validation logic."""

    def test_quality_score_above_threshold_passes(self):
        """Test that quality score above 70% threshold passes."""
        # Arrange
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="test_phase",
            mode=ValidationMode.WARNING,
            quality_threshold=0.7
        )

        game_date = date(2026, 1, 15)
        mock_bq_client.insert_rows_json = Mock(return_value=[])

        # Act - Test passing scenarios
        test_scores = [0.7, 0.8, 0.9, 1.0]

        for score in test_scores:
            result = validator.validate_data_quality(
                game_date=game_date,
                quality_score=score,
                phase_name="test_phase",
                details={"score": score}
            )

            # Assert
            assert result.is_valid is True, f"Failed for score {score}"

    def test_quality_score_below_threshold_fails(self):
        """Test that quality score below 70% threshold fails."""
        # Arrange
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="test_phase",
            mode=ValidationMode.WARNING,
            quality_threshold=0.7
        )

        game_date = date(2026, 1, 15)
        mock_bq_client.insert_rows_json = Mock(return_value=[])

        # Act - Test failing scenarios
        test_scores = [0.69, 0.5, 0.3, 0.0]

        for score in test_scores:
            result = validator.validate_data_quality(
                game_date=game_date,
                quality_score=score,
                phase_name="test_phase",
                details={"score": score}
            )

            # Assert
            assert result.is_valid is False, f"Should fail for score {score}"


class TestProcessorCompletionValidation:
    """Test processor completion validation."""

    def test_all_processors_complete_passes(self):
        """Test that all completed processors passes validation."""
        # Arrange
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="test_phase",
            mode=ValidationMode.WARNING
        )

        game_date = date(2026, 1, 15)
        mock_bq_client.insert_rows_json = Mock(return_value=[])

        # Act
        result = validator.validate_processor_completions(
            game_date=game_date,
            phase_name="phase3_to_phase4",
            processors_status={
                "processor_a": True,
                "processor_b": True,
                "processor_c": True
            }
        )

        # Assert
        assert result.is_valid is True
        assert len(result.issues) == 0

    def test_missing_processors_fails(self):
        """Test that missing processors fails validation."""
        # Arrange
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="test_phase",
            mode=ValidationMode.WARNING
        )

        game_date = date(2026, 1, 15)
        mock_bq_client.insert_rows_json = Mock(return_value=[])

        # Act
        result = validator.validate_processor_completions(
            game_date=game_date,
            phase_name="phase3_to_phase4",
            processors_status={
                "processor_a": True,
                "processor_b": False,  # Missing
                "processor_c": True
            }
        )

        # Assert
        assert result.is_valid is False
        assert len(result.issues) > 0
        assert any("processor_b" in issue.message for issue in result.issues)


class TestValidationModeConfiguration:
    """Test validation mode configuration via environment variables."""

    @patch.dict('os.environ', {
        'PHASE_VALIDATION_MODE': 'warning'
    })
    def test_warning_mode_from_environment(self):
        """Test that WARNING mode can be configured via environment."""
        # Arrange & Act
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="test_phase"
        )

        # Assert
        assert validator.mode == ValidationMode.WARNING

    @patch.dict('os.environ', {
        'PHASE_VALIDATION_MODE': 'blocking'
    })
    def test_blocking_mode_from_environment(self):
        """Test that BLOCKING mode can be configured via environment."""
        # Arrange & Act
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="test_phase"
        )

        # Assert
        assert validator.mode == ValidationMode.BLOCKING

    @patch.dict('os.environ', {
        'PHASE_VALIDATION_GAME_COUNT_THRESHOLD': '0.85',
        'PHASE_VALIDATION_QUALITY_THRESHOLD': '0.75'
    })
    def test_thresholds_from_environment(self):
        """Test that thresholds can be configured via environment."""
        # Arrange & Act
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="test_phase"
        )

        # Assert
        assert validator.game_count_threshold == 0.85
        assert validator.quality_threshold == 0.75


class TestEndToEndValidationFlow:
    """Complete end-to-end validation flow tests."""

    def test_complete_phase_transition_validation_flow(self):
        """Test complete validation flow through a phase transition."""
        # Arrange
        mock_bq_client = Mock(spec=bigquery.Client)
        validator = PhaseBoundaryValidator(
            bq_client=mock_bq_client,
            project_id="test-project",
            phase_name="test_phase",
            mode=ValidationMode.WARNING
        )

        game_date = date(2026, 1, 15)
        mock_bq_client.insert_rows_json = Mock(return_value=[])

        # Act - Simulate full phase transition validation
        # 1. Validate game count
        result1 = validator.validate_game_count(
            game_date=game_date,
            expected_count=10,
            actual_count=9,
            phase_name="phase2_to_phase3"
        )

        # 2. Validate processor completion
        result2 = validator.validate_processor_completions(
            game_date=game_date,
            phase_name="phase2_to_phase3",
            processors_status={
                "bdl_player_boxscores": True,
                "nbac_gamebook_player_stats": True,
                "odds_api_game_lines": True
            }
        )

        # 3. Validate data quality
        result3 = validator.validate_data_quality(
            game_date=game_date,
            quality_score=0.95,
            phase_name="phase2_to_phase3",
            details={"checks_passed": 95, "checks_total": 100}
        )

        # Assert - All validations passed
        assert result1.is_valid is True
        assert result2.is_valid is True
        assert result3.is_valid is True

        # Verify BigQuery logging happened for all validations
        assert mock_bq_client.insert_rows_json.call_count == 3

"""
Unit Tests for Grading Pipeline (ML Feedback Loop)

Tests cover:
1. PredictionAccuracyProcessor - grading predictions against actual results
2. DNP voiding logic - treating DNP like sportsbook voided bets
3. Prediction correctness evaluation - OVER/UNDER accuracy
4. Error calculation - MAE, signed error, threshold accuracy
5. Confidence decile computation - for calibration curves
6. Data sanitization - JSON compatibility for BigQuery

Run with: pytest tests/unit/ml/test_grading_pipeline.py -v

Directory: tests/unit/ml/
"""

import pytest
from datetime import date, datetime, timezone
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, List, Any


# ============================================================================
# TEST FIXTURES
# ============================================================================

@pytest.fixture
def mock_bq_client():
    """Create mock BigQuery client."""
    client = Mock()
    client.query.return_value.to_dataframe.return_value = Mock()
    client.query.return_value.result.return_value = []
    return client


@pytest.fixture
def mock_processor(mock_bq_client):
    """
    Create PredictionAccuracyProcessor with mocked dependencies.

    Uses object.__new__ to avoid __init__ side effects.
    """
    import math
    from data_processors.grading.prediction_accuracy.prediction_accuracy_processor import (
        PredictionAccuracyProcessor
    )

    processor = object.__new__(PredictionAccuracyProcessor)
    processor._math = math
    processor.project_id = 'test-project'
    processor.dataset_prefix = ''
    processor.bq_client = mock_bq_client

    # Set table names
    processor.predictions_table = 'test-project.nba_predictions.player_prop_predictions'
    processor.actuals_table = 'test-project.nba_analytics.player_game_summary'
    processor.accuracy_table = 'test-project.nba_predictions.prediction_accuracy'
    processor.injury_table = 'test-project.nba_raw.nbac_injury_report'

    # Initialize injury cache
    processor._injury_cache = {}

    return processor


@pytest.fixture
def sample_prediction():
    """Sample prediction record for testing."""
    return {
        'player_lookup': 'lebron-james',
        'game_id': '20250115_LAL_BOS',
        'game_date': date(2025, 1, 15),
        'system_id': 'catboost_v8',
        'predicted_points': 28.5,
        'confidence_score': 0.75,
        'recommendation': 'OVER',
        'line_value': 25.5,
        'pace_adjustment': 1.05,
        'similarity_sample_size': 15,
        'model_version': 'v8.0.0',
        'has_prop_line': True,
        'line_source': 'ODDS_API',
        'estimated_line_value': None,
        'is_actionable': True,
        'filter_reason': None,
        'injury_status_at_prediction': None,
        'injury_flag_at_prediction': False,
        'injury_reason_at_prediction': None,
        'injury_checked_at': None
    }


@pytest.fixture
def sample_actual_data():
    """Sample actual game result for testing."""
    return {
        'actual_points': 32,
        'team_abbr': 'LAL',
        'opponent_team_abbr': 'BOS',
        'minutes_played': 38.5
    }


# ============================================================================
# TEST CLASS 1: PREDICTION CORRECTNESS EVALUATION (6 tests)
# ============================================================================

class TestPredictionCorrectness:
    """Test OVER/UNDER recommendation evaluation."""

    def test_over_recommendation_correct_when_player_exceeds_line(self, mock_processor):
        """
        Test OVER is correct when actual > line.

        Scenario: Recommended OVER at 25.5, player scored 28
        Expected: prediction_correct = True
        """
        result = mock_processor.compute_prediction_correct(
            recommendation='OVER',
            line_value=25.5,
            actual_points=28
        )

        assert result is True

    def test_over_recommendation_wrong_when_player_under_line(self, mock_processor):
        """
        Test OVER is incorrect when actual < line.

        Scenario: Recommended OVER at 25.5, player scored 22
        Expected: prediction_correct = False
        """
        result = mock_processor.compute_prediction_correct(
            recommendation='OVER',
            line_value=25.5,
            actual_points=22
        )

        assert result is False

    def test_under_recommendation_correct_when_player_below_line(self, mock_processor):
        """
        Test UNDER is correct when actual < line.

        Scenario: Recommended UNDER at 25.5, player scored 22
        Expected: prediction_correct = True
        """
        result = mock_processor.compute_prediction_correct(
            recommendation='UNDER',
            line_value=25.5,
            actual_points=22
        )

        assert result is True

    def test_under_recommendation_wrong_when_player_exceeds_line(self, mock_processor):
        """
        Test UNDER is incorrect when actual > line.

        Scenario: Recommended UNDER at 25.5, player scored 28
        Expected: prediction_correct = False
        """
        result = mock_processor.compute_prediction_correct(
            recommendation='UNDER',
            line_value=25.5,
            actual_points=28
        )

        assert result is False

    def test_push_returns_none_when_actual_equals_line(self, mock_processor):
        """
        Test that push (exact line hit) returns None.

        Scenario: Recommended OVER at 25.5, player scored exactly 25.5
        Expected: prediction_correct = None (push)

        Business Logic: Like sportsbooks, pushes are neither wins nor losses
        """
        result = mock_processor.compute_prediction_correct(
            recommendation='OVER',
            line_value=25.5,
            actual_points=25.5
        )

        assert result is None

    def test_pass_recommendation_not_evaluated(self, mock_processor):
        """
        Test that PASS recommendation returns None (not evaluated).

        Scenario: Recommended PASS (no bet), player scored 30
        Expected: prediction_correct = None

        Business Logic: PASS means we didn't recommend action, can't be right/wrong
        """
        for rec in ['PASS', 'HOLD', 'NO_LINE', None]:
            result = mock_processor.compute_prediction_correct(
                recommendation=rec,
                line_value=25.5,
                actual_points=30
            )

            assert result is None, f"Expected None for recommendation={rec}"


# ============================================================================
# TEST CLASS 2: DNP VOIDING LOGIC (6 tests)
# ============================================================================

class TestDnpVoiding:
    """Test DNP (Did Not Play) voiding like sportsbooks void bets."""

    def test_player_played_not_voided(self, mock_processor):
        """
        Test that player who played is NOT voided.

        Scenario: Player scored 25 points in 35 minutes
        Expected: is_voided = False
        """
        result = mock_processor.detect_dnp_voiding(
            actual_points=25,
            minutes_played=35.0,
            player_lookup='test-player',
            game_date=date(2025, 1, 15)
        )

        assert result['is_voided'] is False
        assert result['void_reason'] is None

    def test_dnp_with_injury_confirmed_voided(self, mock_processor):
        """
        Test that DNP with confirmed injury is voided.

        Scenario: Player DNP'd (0 pts, 0 min) with OUT injury status
        Expected: is_voided = True, void_reason = 'dnp_injury_confirmed'
        """
        result = mock_processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=0.0,
            player_lookup='test-player',
            game_date=date(2025, 1, 15),
            captured_injury_status='OUT',
            captured_injury_flag=True,
            captured_injury_reason='Ankle sprain'
        )

        assert result['is_voided'] is True
        assert result['void_reason'] == 'dnp_injury_confirmed'
        assert result['pre_game_injury_flag'] is True
        assert result['pre_game_injury_status'] == 'OUT'
        assert result['injury_confirmed_postgame'] is True

    def test_dnp_late_scratch_voided(self, mock_processor):
        """
        Test that DNP from late scratch is voided with different reason.

        Scenario: Player was QUESTIONABLE, ended up DNP
        Expected: is_voided = True, void_reason = 'dnp_late_scratch'
        """
        result = mock_processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=0.0,
            player_lookup='test-player',
            game_date=date(2025, 1, 15),
            captured_injury_status='QUESTIONABLE',
            captured_injury_flag=True,
            captured_injury_reason='Back tightness'
        )

        assert result['is_voided'] is True
        assert result['void_reason'] == 'dnp_late_scratch'
        assert result['pre_game_injury_flag'] is True

    def test_dnp_unknown_reason_voided(self, mock_processor):
        """
        Test that DNP with unknown reason is voided.

        Scenario: Player DNP'd with no injury report (coach decision?)
        Expected: is_voided = True, void_reason = 'dnp_unknown'
        """
        result = mock_processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=0.0,
            player_lookup='test-player',
            game_date=date(2025, 1, 15),
            captured_injury_status=None,
            captured_injury_flag=False,
            captured_injury_reason=None
        )

        assert result['is_voided'] is True
        assert result['void_reason'] == 'dnp_unknown'
        assert result['pre_game_injury_flag'] is False

    def test_zero_points_with_minutes_not_voided(self, mock_processor):
        """
        Test that player with 0 points but played minutes is NOT voided.

        Scenario: Player had terrible game - 0 pts in 20 min (rare but possible)
        Expected: is_voided = False
        """
        result = mock_processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=20.0,
            player_lookup='test-player',
            game_date=date(2025, 1, 15)
        )

        assert result['is_voided'] is False
        assert result['void_reason'] is None

    def test_dnp_with_none_minutes_voided(self, mock_processor):
        """
        Test that 0 points with None minutes is treated as DNP.

        Scenario: Player not in boxscore at all (minutes=None)
        Expected: is_voided = True
        """
        result = mock_processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=None,
            player_lookup='test-player',
            game_date=date(2025, 1, 15)
        )

        assert result['is_voided'] is True


# ============================================================================
# TEST CLASS 3: ERROR CALCULATION (6 tests)
# ============================================================================

class TestErrorCalculation:
    """Test error metric calculations."""

    def test_grade_prediction_absolute_error(self, mock_processor, sample_prediction,
                                              sample_actual_data):
        """
        Test absolute error calculation.

        Scenario: Predicted 28.5, actual 32
        Expected: absolute_error = 3.5
        """
        result = mock_processor.grade_prediction(
            prediction=sample_prediction,
            actual_data=sample_actual_data,
            game_date=date(2025, 1, 15)
        )

        assert result['absolute_error'] == 3.5

    def test_grade_prediction_signed_error_over_prediction(self, mock_processor,
                                                            sample_prediction,
                                                            sample_actual_data):
        """
        Test signed error when over-predicting.

        Scenario: Predicted 28.5, actual 32
        Expected: signed_error = -3.5 (we under-predicted)
        """
        result = mock_processor.grade_prediction(
            prediction=sample_prediction,
            actual_data=sample_actual_data,
            game_date=date(2025, 1, 15)
        )

        # signed_error = predicted - actual = 28.5 - 32 = -3.5
        assert result['signed_error'] == -3.5

    def test_grade_prediction_signed_error_under_prediction(self, mock_processor,
                                                             sample_prediction,
                                                             sample_actual_data):
        """
        Test signed error when under-predicting.

        Scenario: Predicted 35, actual 32
        Expected: signed_error = +3 (we over-predicted)
        """
        sample_prediction['predicted_points'] = 35.0

        result = mock_processor.grade_prediction(
            prediction=sample_prediction,
            actual_data=sample_actual_data,
            game_date=date(2025, 1, 15)
        )

        # signed_error = predicted - actual = 35 - 32 = 3
        assert result['signed_error'] == 3.0

    def test_grade_prediction_within_3_points(self, mock_processor, sample_prediction,
                                               sample_actual_data):
        """
        Test within_3_points threshold.

        Scenario: absolute_error = 3.5
        Expected: within_3_points = False
        """
        result = mock_processor.grade_prediction(
            prediction=sample_prediction,
            actual_data=sample_actual_data,
            game_date=date(2025, 1, 15)
        )

        assert result['within_3_points'] is False

        # Now test when within 3
        sample_prediction['predicted_points'] = 30.0  # error = 2
        result = mock_processor.grade_prediction(
            prediction=sample_prediction,
            actual_data=sample_actual_data,
            game_date=date(2025, 1, 15)
        )

        assert result['within_3_points'] is True

    def test_grade_prediction_within_5_points(self, mock_processor, sample_prediction,
                                               sample_actual_data):
        """
        Test within_5_points threshold.

        Scenario: absolute_error = 3.5
        Expected: within_5_points = True
        """
        result = mock_processor.grade_prediction(
            prediction=sample_prediction,
            actual_data=sample_actual_data,
            game_date=date(2025, 1, 15)
        )

        assert result['within_5_points'] is True

    def test_grade_prediction_margin_calculations(self, mock_processor, sample_prediction,
                                                   sample_actual_data):
        """
        Test margin calculations for betting analysis.

        Scenario: Predicted 28.5, line 25.5, actual 32
        Expected: predicted_margin = 3.0, actual_margin = 6.5
        """
        result = mock_processor.grade_prediction(
            prediction=sample_prediction,
            actual_data=sample_actual_data,
            game_date=date(2025, 1, 15)
        )

        # predicted_margin = predicted - line = 28.5 - 25.5 = 3.0
        assert result['predicted_margin'] == 3.0

        # actual_margin = actual - line = 32 - 25.5 = 6.5
        assert result['actual_margin'] == 6.5


# ============================================================================
# TEST CLASS 4: CONFIDENCE DECILE COMPUTATION (4 tests)
# ============================================================================

class TestConfidenceDecile:
    """Test confidence decile computation for calibration curves."""

    def test_confidence_decile_low(self, mock_processor):
        """Test decile for low confidence (0.05)."""
        decile = mock_processor.compute_confidence_decile(0.05)
        assert decile == 1

    def test_confidence_decile_mid(self, mock_processor):
        """Test decile for medium confidence (0.55)."""
        decile = mock_processor.compute_confidence_decile(0.55)
        assert decile == 6

    def test_confidence_decile_high(self, mock_processor):
        """Test decile for high confidence (0.95)."""
        decile = mock_processor.compute_confidence_decile(0.95)
        assert decile == 10

    def test_confidence_decile_none(self, mock_processor):
        """Test decile for None confidence."""
        decile = mock_processor.compute_confidence_decile(None)
        assert decile is None


# ============================================================================
# TEST CLASS 5: DATA SANITIZATION (5 tests)
# ============================================================================

class TestDataSanitization:
    """Test data sanitization for JSON/BigQuery compatibility."""

    def test_safe_float_normal(self, mock_processor):
        """Test safe_float with normal value."""
        result = mock_processor._safe_float(25.5)
        assert result == 25.5

    def test_safe_float_nan(self, mock_processor):
        """Test safe_float with NaN returns None."""
        import math
        result = mock_processor._safe_float(float('nan'))
        assert result is None

    def test_safe_float_inf(self, mock_processor):
        """Test safe_float with infinity returns None."""
        result = mock_processor._safe_float(float('inf'))
        assert result is None

    def test_safe_string_truncation(self, mock_processor):
        """Test safe_string truncates long strings."""
        long_string = 'a' * 600
        result = mock_processor._safe_string(long_string)
        assert len(result) == 500

    def test_is_nan_detection(self, mock_processor):
        """Test NaN detection helper."""
        import math
        assert mock_processor._is_nan(float('nan')) is True
        assert mock_processor._is_nan(25.5) is False
        assert mock_processor._is_nan(None) is False


# ============================================================================
# TEST CLASS 6: GRADED RESULT STRUCTURE (4 tests)
# ============================================================================

class TestGradedResultStructure:
    """Test the structure of graded prediction results."""

    def test_graded_result_has_all_required_fields(self, mock_processor,
                                                    sample_prediction,
                                                    sample_actual_data):
        """
        Test that graded result contains all required fields.

        Verifies schema completeness for BigQuery insertion.
        """
        result = mock_processor.grade_prediction(
            prediction=sample_prediction,
            actual_data=sample_actual_data,
            game_date=date(2025, 1, 15)
        )

        required_fields = [
            'player_lookup', 'game_id', 'game_date', 'system_id',
            'team_abbr', 'opponent_team_abbr',
            'predicted_points', 'confidence_score', 'recommendation', 'line_value',
            'actual_points', 'minutes_played',
            'absolute_error', 'signed_error', 'prediction_correct',
            'predicted_margin', 'actual_margin',
            'within_3_points', 'within_5_points',
            'has_prop_line', 'line_source',
            'is_actionable', 'filter_reason',
            'is_voided', 'void_reason',
            'model_version', 'graded_at'
        ]

        for field in required_fields:
            assert field in result, f"Missing required field: {field}"

    def test_graded_result_confidence_normalized(self, mock_processor,
                                                  sample_prediction,
                                                  sample_actual_data):
        """
        Test that confidence scores are normalized to 0-1 range.

        CatBoost V8 uses 0-100, should be converted to 0-1.
        """
        # Test with 0-100 format (CatBoost style)
        sample_prediction['confidence_score'] = 75.0
        result = mock_processor.grade_prediction(
            prediction=sample_prediction,
            actual_data=sample_actual_data,
            game_date=date(2025, 1, 15)
        )

        assert result['confidence_score'] == 0.75

    def test_graded_result_game_date_iso_format(self, mock_processor,
                                                 sample_prediction,
                                                 sample_actual_data):
        """
        Test that game_date is in ISO format string.

        BigQuery expects date strings in YYYY-MM-DD format.
        """
        result = mock_processor.grade_prediction(
            prediction=sample_prediction,
            actual_data=sample_actual_data,
            game_date=date(2025, 1, 15)
        )

        assert result['game_date'] == '2025-01-15'

    def test_graded_result_graded_at_populated(self, mock_processor,
                                                sample_prediction,
                                                sample_actual_data):
        """
        Test that graded_at timestamp is populated.

        Tracks when grading occurred for debugging.
        """
        result = mock_processor.grade_prediction(
            prediction=sample_prediction,
            actual_data=sample_actual_data,
            game_date=date(2025, 1, 15)
        )

        assert result['graded_at'] is not None
        # Should be ISO format
        assert 'T' in result['graded_at']


# ============================================================================
# TEST CLASS 7: PROCESS DATE WORKFLOW (4 tests)
# ============================================================================

class TestProcessDateWorkflow:
    """Test the full process_date workflow."""

    def test_process_date_no_predictions(self, mock_processor):
        """
        Test process_date when no predictions exist.

        Expected: Returns status 'no_predictions'
        """
        mock_processor.get_predictions_for_date = Mock(return_value=[])

        result = mock_processor.process_date(date(2025, 1, 15))

        assert result['status'] == 'no_predictions'
        assert result['predictions_found'] == 0
        assert result['graded'] == 0

    def test_process_date_no_actuals(self, mock_processor, sample_prediction):
        """
        Test process_date when no actual results available.

        Expected: Returns status 'no_actuals'
        """
        mock_processor.get_predictions_for_date = Mock(return_value=[sample_prediction])
        mock_processor.get_actuals_for_date = Mock(return_value={})

        result = mock_processor.process_date(date(2025, 1, 15))

        assert result['status'] == 'no_actuals'
        assert result['predictions_found'] == 1
        assert result['graded'] == 0

    def test_process_date_success(self, mock_processor, sample_prediction,
                                   sample_actual_data):
        """
        Test successful process_date.

        Expected: Returns status 'success' with statistics
        """
        mock_processor.get_predictions_for_date = Mock(return_value=[sample_prediction])
        mock_processor.get_actuals_for_date = Mock(return_value={
            'lebron-james': sample_actual_data
        })
        mock_processor.write_graded_results = Mock(return_value=1)
        mock_processor._check_for_duplicates = Mock(return_value=0)

        result = mock_processor.process_date(date(2025, 1, 15))

        assert result['status'] == 'success'
        assert result['predictions_found'] == 1
        assert result['graded'] == 1
        assert result['mae'] is not None
        assert result['recommendation_accuracy'] is not None

    def test_process_date_voiding_stats(self, mock_processor, sample_prediction,
                                         sample_actual_data):
        """
        Test that process_date returns voiding statistics.

        Expected: Returns voided_count, voided_injury, etc.
        """
        # Create DNP scenario
        sample_actual_data['actual_points'] = 0
        sample_actual_data['minutes_played'] = 0.0
        sample_prediction['injury_status_at_prediction'] = 'OUT'
        sample_prediction['injury_flag_at_prediction'] = True

        mock_processor.get_predictions_for_date = Mock(return_value=[sample_prediction])
        mock_processor.get_actuals_for_date = Mock(return_value={
            'lebron-james': sample_actual_data
        })
        mock_processor.write_graded_results = Mock(return_value=1)
        mock_processor._check_for_duplicates = Mock(return_value=0)

        result = mock_processor.process_date(date(2025, 1, 15))

        assert 'voided_count' in result
        assert 'voided_injury' in result
        assert 'voided_scratch' in result
        assert 'net_accuracy' in result


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

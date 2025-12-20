"""
Unit Tests for Prediction Accuracy Processor

Tests individual methods and calculations in isolation.
Run with: pytest tests/processors/grading/prediction_accuracy/test_unit.py -v

Path: tests/processors/grading/prediction_accuracy/test_unit.py
"""

import pytest
import math
from datetime import date, datetime, timezone
from unittest.mock import Mock, MagicMock, patch

from data_processors.grading.prediction_accuracy.prediction_accuracy_processor import (
    PredictionAccuracyProcessor
)


class TestIsNan:
    """Test NaN detection helper."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery client."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery'):
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            return proc

    def test_detects_float_nan(self, processor):
        """Test detection of float('nan')."""
        assert processor._is_nan(float('nan')) is True

    def test_detects_math_nan(self, processor):
        """Test detection of math.nan."""
        assert processor._is_nan(math.nan) is True

    def test_none_is_not_nan(self, processor):
        """Test that None is not considered NaN."""
        assert processor._is_nan(None) is False

    def test_regular_float_is_not_nan(self, processor):
        """Test that regular floats are not NaN."""
        assert processor._is_nan(0.0) is False
        assert processor._is_nan(1.5) is False
        assert processor._is_nan(-100.0) is False

    def test_integer_is_not_nan(self, processor):
        """Test that integers are not NaN."""
        assert processor._is_nan(0) is False
        assert processor._is_nan(42) is False

    def test_string_nan_is_detected(self, processor):
        """Test that string 'nan' is detected as NaN (converts to float)."""
        # Python's float("nan") is NaN, so string "nan" is detected
        assert processor._is_nan("nan") is True

    def test_regular_string_is_not_nan(self, processor):
        """Test that regular strings are not NaN."""
        assert processor._is_nan("hello") is False

    def test_infinity_is_not_nan(self, processor):
        """Test that infinity is not NaN."""
        assert processor._is_nan(float('inf')) is False
        assert processor._is_nan(float('-inf')) is False


class TestSafeFloat:
    """Test safe float conversion helper."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery'):
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            return proc

    def test_converts_int_to_float(self, processor):
        """Test integer conversion."""
        assert processor._safe_float(42) == 42.0

    def test_returns_float_unchanged(self, processor):
        """Test float passthrough."""
        assert processor._safe_float(3.14) == 3.14

    def test_none_returns_none(self, processor):
        """Test None handling."""
        assert processor._safe_float(None) is None

    def test_nan_returns_none(self, processor):
        """Test NaN returns None."""
        assert processor._safe_float(float('nan')) is None
        assert processor._safe_float(math.nan) is None

    def test_infinity_returns_none(self, processor):
        """Test infinity returns None."""
        assert processor._safe_float(float('inf')) is None
        assert processor._safe_float(float('-inf')) is None

    def test_string_number_converts(self, processor):
        """Test numeric string conversion."""
        assert processor._safe_float("3.14") == 3.14
        assert processor._safe_float("42") == 42.0

    def test_invalid_string_returns_none(self, processor):
        """Test invalid string returns None."""
        assert processor._safe_float("hello") is None
        assert processor._safe_float("") is None


class TestComputePredictionCorrect:
    """Test OVER/UNDER recommendation correctness evaluation."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery'):
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            return proc

    def test_over_correct_when_actual_exceeds_line(self, processor):
        """Test OVER is correct when actual > line."""
        result = processor.compute_prediction_correct(
            recommendation='OVER',
            line_value=20.5,
            actual_points=25
        )
        assert result is True

    def test_over_incorrect_when_actual_below_line(self, processor):
        """Test OVER is incorrect when actual < line."""
        result = processor.compute_prediction_correct(
            recommendation='OVER',
            line_value=20.5,
            actual_points=18
        )
        assert result is False

    def test_under_correct_when_actual_below_line(self, processor):
        """Test UNDER is correct when actual < line."""
        result = processor.compute_prediction_correct(
            recommendation='UNDER',
            line_value=20.5,
            actual_points=18
        )
        assert result is True

    def test_under_incorrect_when_actual_exceeds_line(self, processor):
        """Test UNDER is incorrect when actual > line."""
        result = processor.compute_prediction_correct(
            recommendation='UNDER',
            line_value=20.5,
            actual_points=25
        )
        assert result is False

    def test_push_returns_none(self, processor):
        """Test that exactly hitting the line (push) returns None."""
        result = processor.compute_prediction_correct(
            recommendation='OVER',
            line_value=20.0,
            actual_points=20
        )
        assert result is None

    def test_pass_returns_none(self, processor):
        """Test PASS recommendation returns None."""
        result = processor.compute_prediction_correct(
            recommendation='PASS',
            line_value=20.5,
            actual_points=25
        )
        assert result is None

    def test_hold_returns_none(self, processor):
        """Test HOLD recommendation returns None."""
        result = processor.compute_prediction_correct(
            recommendation='HOLD',
            line_value=20.5,
            actual_points=25
        )
        assert result is None

    def test_none_recommendation_returns_none(self, processor):
        """Test None recommendation returns None."""
        result = processor.compute_prediction_correct(
            recommendation=None,
            line_value=20.5,
            actual_points=25
        )
        assert result is None

    def test_none_line_returns_none(self, processor):
        """Test missing line returns None."""
        result = processor.compute_prediction_correct(
            recommendation='OVER',
            line_value=None,
            actual_points=25
        )
        assert result is None

    def test_half_point_lines(self, processor):
        """Test with half-point lines (common in betting)."""
        # 21 > 20.5 → OVER correct
        assert processor.compute_prediction_correct('OVER', 20.5, 21) is True
        # 20 < 20.5 → UNDER correct
        assert processor.compute_prediction_correct('UNDER', 20.5, 20) is True


class TestComputeConfidenceDecile:
    """Test confidence decile bucketing."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery'):
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            return proc

    def test_zero_confidence_is_decile_1(self, processor):
        """Test 0.0 confidence → decile 1."""
        assert processor.compute_confidence_decile(0.0) == 1

    def test_low_confidence_decile(self, processor):
        """Test low confidence (0.05) → decile 1."""
        assert processor.compute_confidence_decile(0.05) == 1

    def test_mid_confidence_decile(self, processor):
        """Test mid confidence (0.55) → decile 6."""
        assert processor.compute_confidence_decile(0.55) == 6

    def test_high_confidence_decile(self, processor):
        """Test high confidence (0.85) → decile 9."""
        assert processor.compute_confidence_decile(0.85) == 9

    def test_max_confidence_capped_at_10(self, processor):
        """Test 1.0 confidence → decile 10 (capped)."""
        assert processor.compute_confidence_decile(1.0) == 10

    def test_over_1_capped_at_10(self, processor):
        """Test confidence > 1.0 is capped at decile 10."""
        assert processor.compute_confidence_decile(1.5) == 10

    def test_none_returns_none(self, processor):
        """Test None confidence returns None."""
        assert processor.compute_confidence_decile(None) is None

    def test_decile_boundaries(self, processor):
        """Test exact decile boundaries."""
        # 0.09 → 1, 0.10 → 2
        assert processor.compute_confidence_decile(0.09) == 1
        assert processor.compute_confidence_decile(0.10) == 2
        # 0.69 → 7, 0.70 → 8
        assert processor.compute_confidence_decile(0.69) == 7
        assert processor.compute_confidence_decile(0.70) == 8


class TestGradePrediction:
    """Test the main grade_prediction method."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery'):
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            return proc

    @pytest.fixture
    def sample_prediction(self):
        """Sample prediction record."""
        return {
            'player_lookup': 'lebron-james',
            'game_id': '20251215_LAL_BOS',
            'game_date': date(2025, 12, 15),
            'system_id': 'ensemble_v1',
            'predicted_points': 27.5,
            'confidence_score': 0.72,
            'recommendation': 'OVER',
            'line_value': 24.5,
            'pace_adjustment': 1.05,
            'similarity_sample_size': 15,
            'model_version': 'v1.0',
            # Line source tracking (for no-line player analysis)
            'has_prop_line': True,
            'line_source': 'ACTUAL_PROP',
            'estimated_line_value': None
        }

    @pytest.fixture
    def sample_actual(self):
        """Sample actual result."""
        return {
            'actual_points': 30,
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'BOS',
            'minutes_played': 36.5
        }

    def test_computes_absolute_error(self, processor, sample_prediction, sample_actual):
        """Test absolute error calculation."""
        result = processor.grade_prediction(sample_prediction, sample_actual)

        # |27.5 - 30| = 2.5
        assert result['absolute_error'] == 2.5

    def test_computes_signed_error(self, processor, sample_prediction, sample_actual):
        """Test signed error calculation (bias direction)."""
        result = processor.grade_prediction(sample_prediction, sample_actual)

        # 27.5 - 30 = -2.5 (under-predicted)
        assert result['signed_error'] == -2.5

    def test_within_3_points(self, processor, sample_prediction, sample_actual):
        """Test within_3_points flag."""
        result = processor.grade_prediction(sample_prediction, sample_actual)

        # Error of 2.5 is within 3
        assert result['within_3_points'] is True

    def test_within_5_points(self, processor, sample_prediction, sample_actual):
        """Test within_5_points flag."""
        result = processor.grade_prediction(sample_prediction, sample_actual)

        # Error of 2.5 is within 5
        assert result['within_5_points'] is True

    def test_not_within_3_points(self, processor, sample_prediction, sample_actual):
        """Test when error exceeds 3 points."""
        sample_actual['actual_points'] = 35  # 27.5 vs 35 = 7.5 error

        result = processor.grade_prediction(sample_prediction, sample_actual)

        assert result['within_3_points'] is False
        assert result['within_5_points'] is False

    def test_prediction_correct_for_over(self, processor, sample_prediction, sample_actual):
        """Test prediction_correct for correct OVER call."""
        # Predicted OVER 24.5, actual was 30 → correct
        result = processor.grade_prediction(sample_prediction, sample_actual)

        assert result['prediction_correct'] is True

    def test_prediction_incorrect_for_over(self, processor, sample_prediction, sample_actual):
        """Test prediction_correct for incorrect OVER call."""
        sample_actual['actual_points'] = 22  # Below 24.5 line

        result = processor.grade_prediction(sample_prediction, sample_actual)

        assert result['prediction_correct'] is False

    def test_computes_predicted_margin(self, processor, sample_prediction, sample_actual):
        """Test predicted margin calculation."""
        result = processor.grade_prediction(sample_prediction, sample_actual)

        # 27.5 - 24.5 = 3.0
        assert result['predicted_margin'] == 3.0

    def test_computes_actual_margin(self, processor, sample_prediction, sample_actual):
        """Test actual margin calculation."""
        result = processor.grade_prediction(sample_prediction, sample_actual)

        # 30 - 24.5 = 5.5
        assert result['actual_margin'] == 5.5

    def test_includes_confidence_decile(self, processor, sample_prediction, sample_actual):
        """Test confidence decile is computed."""
        result = processor.grade_prediction(sample_prediction, sample_actual)

        # 0.72 → decile 8
        assert result['confidence_decile'] == 8

    def test_includes_team_context(self, processor, sample_prediction, sample_actual):
        """Test team context is included."""
        result = processor.grade_prediction(sample_prediction, sample_actual)

        assert result['team_abbr'] == 'LAL'
        assert result['opponent_team_abbr'] == 'BOS'

    def test_includes_minutes_played(self, processor, sample_prediction, sample_actual):
        """Test minutes_played is included."""
        result = processor.grade_prediction(sample_prediction, sample_actual)

        assert result['minutes_played'] == 36.5

    def test_includes_graded_at_timestamp(self, processor, sample_prediction, sample_actual):
        """Test graded_at timestamp is included."""
        result = processor.grade_prediction(sample_prediction, sample_actual)

        assert 'graded_at' in result
        assert 'T' in result['graded_at']  # ISO format

    def test_handles_none_predicted_points(self, processor, sample_prediction, sample_actual):
        """Test handling when predicted_points is None."""
        sample_prediction['predicted_points'] = None

        result = processor.grade_prediction(sample_prediction, sample_actual)

        assert result['absolute_error'] is None
        assert result['signed_error'] is None
        assert result['within_3_points'] is None
        assert result['within_5_points'] is None

    def test_handles_none_line_value(self, processor, sample_prediction, sample_actual):
        """Test handling when line_value is None."""
        sample_prediction['line_value'] = None

        result = processor.grade_prediction(sample_prediction, sample_actual)

        assert result['predicted_margin'] is None
        assert result['actual_margin'] is None
        assert result['prediction_correct'] is None

    def test_handles_nan_pace_adjustment(self, processor, sample_prediction, sample_actual):
        """Test handling NaN pace_adjustment."""
        sample_prediction['pace_adjustment'] = float('nan')

        result = processor.grade_prediction(sample_prediction, sample_actual)

        assert result['pace_adjustment'] is None

    def test_handles_nan_similarity_sample_size(self, processor, sample_prediction, sample_actual):
        """Test handling NaN similarity_sample_size."""
        sample_prediction['similarity_sample_size'] = float('nan')

        result = processor.grade_prediction(sample_prediction, sample_actual)

        assert result['similarity_sample_size'] is None

    def test_game_date_formatted_as_string(self, processor, sample_prediction, sample_actual):
        """Test game_date is formatted as ISO string."""
        result = processor.grade_prediction(sample_prediction, sample_actual)

        assert result['game_date'] == '2025-12-15'

    def test_includes_has_prop_line(self, processor, sample_prediction, sample_actual):
        """Test has_prop_line is included for line source tracking."""
        result = processor.grade_prediction(sample_prediction, sample_actual)

        assert result['has_prop_line'] is True

    def test_includes_line_source(self, processor, sample_prediction, sample_actual):
        """Test line_source is included for line source tracking."""
        result = processor.grade_prediction(sample_prediction, sample_actual)

        assert result['line_source'] == 'ACTUAL_PROP'

    def test_includes_estimated_line_value_when_present(self, processor, sample_prediction, sample_actual):
        """Test estimated_line_value is included when present."""
        sample_prediction['has_prop_line'] = False
        sample_prediction['line_source'] = 'ESTIMATED_AVG'
        sample_prediction['estimated_line_value'] = 22.3

        result = processor.grade_prediction(sample_prediction, sample_actual)

        assert result['has_prop_line'] is False
        assert result['line_source'] == 'ESTIMATED_AVG'
        assert result['estimated_line_value'] == 22.3

    def test_no_line_player_still_computes_point_accuracy(self, processor, sample_prediction, sample_actual):
        """Test that no-line players still get point accuracy metrics."""
        # Simulate a no-line player (only has estimated line)
        sample_prediction['has_prop_line'] = False
        sample_prediction['line_source'] = 'ESTIMATED_AVG'
        sample_prediction['line_value'] = None  # No real betting line
        sample_prediction['estimated_line_value'] = 22.3

        result = processor.grade_prediction(sample_prediction, sample_actual)

        # Point accuracy should still be computed
        assert result['absolute_error'] == 2.5  # |27.5 - 30| = 2.5
        assert result['signed_error'] == -2.5
        assert result['within_3_points'] is True
        # But O/U correctness cannot be evaluated
        assert result['prediction_correct'] is None
        assert result['predicted_margin'] is None
        assert result['actual_margin'] is None

    def test_defaults_has_prop_line_to_true(self, processor, sample_prediction, sample_actual):
        """Test that missing has_prop_line defaults to True for backwards compatibility."""
        del sample_prediction['has_prop_line']
        del sample_prediction['line_source']
        del sample_prediction['estimated_line_value']

        result = processor.grade_prediction(sample_prediction, sample_actual)

        assert result['has_prop_line'] is True
        assert result['line_source'] == 'ACTUAL_PROP'

    def test_rounds_numeric_values(self, processor, sample_prediction, sample_actual):
        """Test that numeric values are rounded for BigQuery NUMERIC compatibility."""
        sample_prediction['predicted_points'] = 27.123456789
        sample_prediction['confidence_score'] = 0.7234567

        result = processor.grade_prediction(sample_prediction, sample_actual)

        # Check rounding
        assert result['predicted_points'] == 27.12
        assert result['confidence_score'] == 0.7235


class TestProcessDate:
    """Test the process_date method with mocked data."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked methods."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery'):
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            return proc

    def test_returns_no_predictions_status(self, processor):
        """Test status when no predictions found."""
        processor.get_predictions_for_date = Mock(return_value=[])

        result = processor.process_date(date(2025, 12, 15))

        assert result['status'] == 'no_predictions'
        assert result['predictions_found'] == 0

    def test_returns_no_actuals_status(self, processor):
        """Test status when no actuals found."""
        processor.get_predictions_for_date = Mock(return_value=[
            {'player_lookup': 'test-player', 'system_id': 'ensemble_v1'}
        ])
        processor.get_actuals_for_date = Mock(return_value={})

        result = processor.process_date(date(2025, 12, 15))

        assert result['status'] == 'no_actuals'
        assert result['predictions_found'] == 1
        assert result['graded'] == 0

    def test_computes_mae(self, processor):
        """Test MAE calculation in process_date."""
        processor.get_predictions_for_date = Mock(return_value=[
            {
                'player_lookup': 'player-a',
                'game_id': 'game1',
                'game_date': date(2025, 12, 15),
                'system_id': 'ensemble_v1',
                'predicted_points': 25.0,
                'confidence_score': 0.7,
                'recommendation': 'OVER',
                'line_value': 22.5,
                'pace_adjustment': None,
                'similarity_sample_size': None,
                'model_version': 'v1'
            },
            {
                'player_lookup': 'player-b',
                'game_id': 'game2',
                'game_date': date(2025, 12, 15),
                'system_id': 'ensemble_v1',
                'predicted_points': 20.0,
                'confidence_score': 0.6,
                'recommendation': 'UNDER',
                'line_value': 22.5,
                'pace_adjustment': None,
                'similarity_sample_size': None,
                'model_version': 'v1'
            }
        ])
        processor.get_actuals_for_date = Mock(return_value={
            'player-a': {'actual_points': 28, 'team_abbr': 'LAL', 'opponent_team_abbr': 'BOS', 'minutes_played': 35},
            'player-b': {'actual_points': 18, 'team_abbr': 'GSW', 'opponent_team_abbr': 'PHX', 'minutes_played': 32}
        })
        processor.write_graded_results = Mock(return_value=2)

        result = processor.process_date(date(2025, 12, 15))

        # MAE = (|25-28| + |20-18|) / 2 = (3 + 2) / 2 = 2.5
        assert result['mae'] == 2.5

    def test_computes_bias(self, processor):
        """Test bias calculation in process_date."""
        processor.get_predictions_for_date = Mock(return_value=[
            {
                'player_lookup': 'player-a',
                'game_id': 'game1',
                'game_date': date(2025, 12, 15),
                'system_id': 'ensemble_v1',
                'predicted_points': 25.0,
                'confidence_score': 0.7,
                'recommendation': 'OVER',
                'line_value': 22.5,
                'pace_adjustment': None,
                'similarity_sample_size': None,
                'model_version': 'v1'
            }
        ])
        processor.get_actuals_for_date = Mock(return_value={
            'player-a': {'actual_points': 28, 'team_abbr': 'LAL', 'opponent_team_abbr': 'BOS', 'minutes_played': 35}
        })
        processor.write_graded_results = Mock(return_value=1)

        result = processor.process_date(date(2025, 12, 15))

        # Bias = 25 - 28 = -3 (under-predicted)
        assert result['bias'] == -3.0

    def test_computes_recommendation_accuracy(self, processor):
        """Test recommendation accuracy calculation."""
        processor.get_predictions_for_date = Mock(return_value=[
            {
                'player_lookup': 'player-a',
                'game_id': 'game1',
                'game_date': date(2025, 12, 15),
                'system_id': 'ensemble_v1',
                'predicted_points': 25.0,
                'confidence_score': 0.7,
                'recommendation': 'OVER',
                'line_value': 22.5,
                'pace_adjustment': None,
                'similarity_sample_size': None,
                'model_version': 'v1'
            },
            {
                'player_lookup': 'player-b',
                'game_id': 'game2',
                'game_date': date(2025, 12, 15),
                'system_id': 'ensemble_v1',
                'predicted_points': 20.0,
                'confidence_score': 0.6,
                'recommendation': 'UNDER',
                'line_value': 22.5,
                'pace_adjustment': None,
                'similarity_sample_size': None,
                'model_version': 'v1'
            }
        ])
        processor.get_actuals_for_date = Mock(return_value={
            'player-a': {'actual_points': 28, 'team_abbr': 'LAL', 'opponent_team_abbr': 'BOS', 'minutes_played': 35},  # OVER correct (28 > 22.5)
            'player-b': {'actual_points': 25, 'team_abbr': 'GSW', 'opponent_team_abbr': 'PHX', 'minutes_played': 32}   # UNDER wrong (25 > 22.5)
        })
        processor.write_graded_results = Mock(return_value=2)

        result = processor.process_date(date(2025, 12, 15))

        # 1 correct, 1 wrong = 50%
        assert result['recommendation_accuracy'] == 50.0

    def test_tracks_missing_actuals(self, processor):
        """Test that missing actuals are tracked."""
        processor.get_predictions_for_date = Mock(return_value=[
            {
                'player_lookup': 'player-a',
                'game_id': 'game1',
                'game_date': date(2025, 12, 15),
                'system_id': 'ensemble_v1',
                'predicted_points': 25.0,
                'confidence_score': 0.7,
                'recommendation': 'OVER',
                'line_value': 22.5,
                'pace_adjustment': None,
                'similarity_sample_size': None,
                'model_version': 'v1'
            },
            {
                'player_lookup': 'player-missing',
                'game_id': 'game2',
                'game_date': date(2025, 12, 15),
                'system_id': 'ensemble_v1',
                'predicted_points': 20.0,
                'confidence_score': 0.6,
                'recommendation': 'UNDER',
                'line_value': 22.5,
                'pace_adjustment': None,
                'similarity_sample_size': None,
                'model_version': 'v1'
            }
        ])
        processor.get_actuals_for_date = Mock(return_value={
            'player-a': {'actual_points': 28, 'team_abbr': 'LAL', 'opponent_team_abbr': 'BOS', 'minutes_played': 35}
            # player-missing has no actuals
        })
        processor.write_graded_results = Mock(return_value=1)

        result = processor.process_date(date(2025, 12, 15))

        assert result['missing_actuals'] == 1
        assert result['graded'] == 1


class TestWriteGradedResults:
    """Test writing results to BigQuery."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery') as mock_bq:
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            # Mock table reference
            mock_table = Mock()
            mock_table.schema = []
            proc.bq_client.get_table.return_value = mock_table
            return proc

    def test_returns_zero_for_empty_list(self, processor):
        """Test that 0 is returned for empty results."""
        result = processor.write_graded_results([], date(2025, 12, 15))
        assert result == 0

    def test_deletes_existing_records_first(self, processor):
        """Test idempotency - deletes existing records before insert."""
        mock_load_job = Mock()
        mock_load_job.result.return_value = None
        mock_load_job.errors = None
        mock_load_job.output_rows = 5
        processor.bq_client.load_table_from_json.return_value = mock_load_job

        # Mock delete job
        mock_delete_job = Mock()
        mock_delete_job.result.return_value = None
        mock_delete_job.num_dml_affected_rows = 3
        processor.bq_client.query.return_value = mock_delete_job

        results = [{'player_lookup': 'test', 'game_date': '2025-12-15'}]
        processor.write_graded_results(results, date(2025, 12, 15))

        # Verify delete was called
        delete_call = processor.bq_client.query.call_args[0][0]
        assert "DELETE FROM" in delete_call
        assert "2025-12-15" in delete_call

    def test_returns_output_rows(self, processor):
        """Test that output_rows count is returned."""
        mock_load_job = Mock()
        mock_load_job.result.return_value = None
        mock_load_job.errors = None
        mock_load_job.output_rows = 42
        processor.bq_client.load_table_from_json.return_value = mock_load_job

        mock_delete_job = Mock()
        mock_delete_job.result.return_value = None
        mock_delete_job.num_dml_affected_rows = 0
        processor.bq_client.query.return_value = mock_delete_job

        results = [{'player_lookup': 'test'}]
        result = processor.write_graded_results(results, date(2025, 12, 15))

        assert result == 42

    def test_handles_exception(self, processor):
        """Test that exceptions return 0."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        results = [{'player_lookup': 'test'}]
        result = processor.write_graded_results(results, date(2025, 12, 15))

        assert result == 0


class TestCheckPredictionsExist:
    """Test prediction existence check."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery'):
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            return proc

    def test_returns_exists_true_when_data_found(self, processor):
        """Test exists=True when predictions found."""
        import pandas as pd
        mock_df = pd.DataFrame({'total': [150], 'players': [30], 'systems': [5]})
        processor.bq_client.query.return_value.to_dataframe.return_value = mock_df

        result = processor.check_predictions_exist(date(2025, 12, 15))

        assert result['exists'] is True
        assert result['total_predictions'] == 150
        assert result['unique_players'] == 30
        assert result['systems'] == 5

    def test_returns_exists_false_when_no_data(self, processor):
        """Test exists=False when no predictions."""
        import pandas as pd
        mock_df = pd.DataFrame({'total': [0], 'players': [0], 'systems': [0]})
        processor.bq_client.query.return_value.to_dataframe.return_value = mock_df

        result = processor.check_predictions_exist(date(2025, 12, 15))

        assert result['exists'] is False


class TestCheckActualsExist:
    """Test actuals existence check."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery'):
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            return proc

    def test_returns_exists_true_when_data_found(self, processor):
        """Test exists=True when actuals found."""
        import pandas as pd
        mock_df = pd.DataFrame({'players': [250]})
        processor.bq_client.query.return_value.to_dataframe.return_value = mock_df

        result = processor.check_actuals_exist(date(2025, 12, 15))

        assert result['exists'] is True
        assert result['players'] == 250

    def test_returns_exists_false_when_no_data(self, processor):
        """Test exists=False when no actuals."""
        import pandas as pd
        mock_df = pd.DataFrame({'players': [0]})
        processor.bq_client.query.return_value.to_dataframe.return_value = mock_df

        result = processor.check_actuals_exist(date(2025, 12, 15))

        assert result['exists'] is False


# ============================================================================
# Test Summary
# ============================================================================
# Total Tests: 65+ unit tests
# Coverage: Core processor methods for prediction grading
#
# Test Distribution:
# - _is_nan helper: 7 tests
# - _safe_float helper: 7 tests
# - compute_prediction_correct: 10 tests
# - compute_confidence_decile: 8 tests
# - grade_prediction: 18 tests
# - process_date: 5 tests
# - write_graded_results: 4 tests
# - check_predictions_exist: 2 tests
# - check_actuals_exist: 2 tests
#
# Run with:
#   pytest tests/processors/grading/prediction_accuracy/test_unit.py -v
#   pytest tests/processors/grading/prediction_accuracy/test_unit.py -k "prediction_correct" -v
# ============================================================================

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
        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        # |27.5 - 30| = 2.5
        assert result['absolute_error'] == 2.5

    def test_computes_signed_error(self, processor, sample_prediction, sample_actual):
        """Test signed error calculation (bias direction)."""
        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        # 27.5 - 30 = -2.5 (under-predicted)
        assert result['signed_error'] == -2.5

    def test_within_3_points(self, processor, sample_prediction, sample_actual):
        """Test within_3_points flag."""
        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        # Error of 2.5 is within 3
        assert result['within_3_points'] is True

    def test_within_5_points(self, processor, sample_prediction, sample_actual):
        """Test within_5_points flag."""
        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        # Error of 2.5 is within 5
        assert result['within_5_points'] is True

    def test_not_within_3_points(self, processor, sample_prediction, sample_actual):
        """Test when error exceeds 3 points."""
        sample_actual['actual_points'] = 35  # 27.5 vs 35 = 7.5 error

        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        assert result['within_3_points'] is False
        assert result['within_5_points'] is False

    def test_prediction_correct_for_over(self, processor, sample_prediction, sample_actual):
        """Test prediction_correct for correct OVER call."""
        # Predicted OVER 24.5, actual was 30 → correct
        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        assert result['prediction_correct'] is True

    def test_prediction_incorrect_for_over(self, processor, sample_prediction, sample_actual):
        """Test prediction_correct for incorrect OVER call."""
        sample_actual['actual_points'] = 22  # Below 24.5 line

        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        assert result['prediction_correct'] is False

    def test_computes_predicted_margin(self, processor, sample_prediction, sample_actual):
        """Test predicted margin calculation."""
        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        # 27.5 - 24.5 = 3.0
        assert result['predicted_margin'] == 3.0

    def test_computes_actual_margin(self, processor, sample_prediction, sample_actual):
        """Test actual margin calculation."""
        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        # 30 - 24.5 = 5.5
        assert result['actual_margin'] == 5.5

    def test_includes_confidence_decile(self, processor, sample_prediction, sample_actual):
        """Test confidence decile is computed."""
        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        # 0.72 → decile 8
        assert result['confidence_decile'] == 8

    def test_includes_team_context(self, processor, sample_prediction, sample_actual):
        """Test team context is included."""
        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        assert result['team_abbr'] == 'LAL'
        assert result['opponent_team_abbr'] == 'BOS'

    def test_includes_minutes_played(self, processor, sample_prediction, sample_actual):
        """Test minutes_played is included."""
        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        assert result['minutes_played'] == 36.5

    def test_includes_graded_at_timestamp(self, processor, sample_prediction, sample_actual):
        """Test graded_at timestamp is included."""
        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        assert 'graded_at' in result
        assert 'T' in result['graded_at']  # ISO format

    def test_handles_none_predicted_points(self, processor, sample_prediction, sample_actual):
        """Test handling when predicted_points is None."""
        sample_prediction['predicted_points'] = None

        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        assert result['absolute_error'] is None
        assert result['signed_error'] is None
        assert result['within_3_points'] is None
        assert result['within_5_points'] is None

    def test_handles_none_line_value(self, processor, sample_prediction, sample_actual):
        """Test handling when line_value is None."""
        sample_prediction['line_value'] = None

        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        assert result['predicted_margin'] is None
        assert result['actual_margin'] is None
        assert result['prediction_correct'] is None

    def test_handles_nan_pace_adjustment(self, processor, sample_prediction, sample_actual):
        """Test handling NaN pace_adjustment."""
        sample_prediction['pace_adjustment'] = float('nan')

        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        assert result['pace_adjustment'] is None

    def test_handles_nan_similarity_sample_size(self, processor, sample_prediction, sample_actual):
        """Test handling NaN similarity_sample_size."""
        sample_prediction['similarity_sample_size'] = float('nan')

        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        assert result['similarity_sample_size'] is None

    def test_game_date_formatted_as_string(self, processor, sample_prediction, sample_actual):
        """Test game_date is formatted as ISO string."""
        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        assert result['game_date'] == '2025-12-15'

    def test_includes_has_prop_line(self, processor, sample_prediction, sample_actual):
        """Test has_prop_line is included for line source tracking."""
        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        assert result['has_prop_line'] is True

    def test_includes_line_source(self, processor, sample_prediction, sample_actual):
        """Test line_source is included for line source tracking."""
        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        assert result['line_source'] == 'ACTUAL_PROP'

    def test_includes_estimated_line_value_when_present(self, processor, sample_prediction, sample_actual):
        """Test estimated_line_value is included when present."""
        sample_prediction['has_prop_line'] = False
        sample_prediction['line_source'] = 'ESTIMATED_AVG'
        sample_prediction['estimated_line_value'] = 22.3

        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

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

        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

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

        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

        assert result['has_prop_line'] is True
        assert result['line_source'] == 'ACTUAL_PROP'

    def test_rounds_numeric_values(self, processor, sample_prediction, sample_actual):
        """Test that numeric values are rounded for BigQuery NUMERIC compatibility."""
        sample_prediction['predicted_points'] = 27.123456789
        sample_prediction['confidence_score'] = 0.7234567

        result = processor.grade_prediction(sample_prediction, sample_actual, sample_prediction['game_date'])

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

            # Mock query results to return proper iterables
            mock_query_result = Mock()
            mock_query_result.result.return_value = iter([])  # Empty iterable
            proc.bq_client.query.return_value = mock_query_result

            # Mock _check_for_duplicates to avoid BQ calls
            proc._check_for_duplicates = Mock(return_value=0)

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


@pytest.mark.skip(reason="Requires Firestore distributed lock - integration test")
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


class TestDetectDnpVoiding:
    """Test DNP (Did Not Play) voiding detection."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery'):
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            # Mock injury cache to avoid BQ calls
            proc._injury_cache = {}
            return proc

    def test_not_voided_when_player_plays_normally(self, processor):
        """Test that normal playing time is not voided."""
        result = processor.detect_dnp_voiding(
            actual_points=25,
            minutes_played=32.5,
            player_lookup='lebron-james',
            game_date=date(2025, 12, 15)
        )

        assert result['is_voided'] is False
        assert result['void_reason'] is None

    def test_not_voided_when_zero_points_but_played(self, processor):
        """Test that scoring 0 points with minutes is NOT voided."""
        result = processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=15.0,
            player_lookup='bench-player',
            game_date=date(2025, 12, 15)
        )

        assert result['is_voided'] is False
        assert result['void_reason'] is None

    def test_voided_when_zero_points_zero_minutes(self, processor):
        """Test DNP detection with 0 points and 0 minutes."""
        # Pre-populate injury cache to avoid BQ lookup
        processor._injury_cache['2025-12-15'] = {}

        result = processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=0,
            player_lookup='injured-player',
            game_date=date(2025, 12, 15)
        )

        assert result['is_voided'] is True
        assert result['void_reason'] is not None  # Could be dnp_unknown

    def test_voided_when_zero_points_none_minutes(self, processor):
        """Test DNP detection with 0 points and None minutes."""
        # Pre-populate injury cache to avoid BQ lookup
        processor._injury_cache['2025-12-15'] = {}

        result = processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=None,
            player_lookup='injured-player',
            game_date=date(2025, 12, 15)
        )

        assert result['is_voided'] is True
        assert result['void_reason'] is not None

    def test_dnp_injury_confirmed_with_captured_out_status(self, processor):
        """Test DNP with captured OUT injury status."""
        result = processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=0,
            player_lookup='injured-player',
            game_date=date(2025, 12, 15),
            captured_injury_status='OUT',
            captured_injury_flag=True,
            captured_injury_reason='Knee injury'
        )

        assert result['is_voided'] is True
        assert result['void_reason'] == 'dnp_injury_confirmed'
        assert result['pre_game_injury_flag'] is True
        assert result['pre_game_injury_status'] == 'OUT'
        assert result['injury_confirmed_postgame'] is True

    def test_dnp_injury_confirmed_with_doubtful_status(self, processor):
        """Test DNP with captured DOUBTFUL injury status."""
        result = processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=0,
            player_lookup='injured-player',
            game_date=date(2025, 12, 15),
            captured_injury_status='DOUBTFUL',
            captured_injury_flag=True
        )

        assert result['is_voided'] is True
        assert result['void_reason'] == 'dnp_injury_confirmed'
        assert result['pre_game_injury_flag'] is True

    def test_dnp_late_scratch_with_questionable_status(self, processor):
        """Test DNP with QUESTIONABLE status (late scratch)."""
        result = processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=0,
            player_lookup='injured-player',
            game_date=date(2025, 12, 15),
            captured_injury_status='QUESTIONABLE',
            captured_injury_flag=True
        )

        assert result['is_voided'] is True
        assert result['void_reason'] == 'dnp_late_scratch'
        assert result['pre_game_injury_flag'] is True
        assert result['injury_confirmed_postgame'] is True

    def test_dnp_late_scratch_with_probable_status(self, processor):
        """Test DNP with PROBABLE status (unexpected late scratch)."""
        result = processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=0,
            player_lookup='injured-player',
            game_date=date(2025, 12, 15),
            captured_injury_status='PROBABLE',
            captured_injury_flag=True
        )

        assert result['is_voided'] is True
        assert result['void_reason'] == 'dnp_late_scratch'

    def test_dnp_unknown_with_no_injury_flag(self, processor):
        """Test DNP with no injury flag (surprise scratch)."""
        result = processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=0,
            player_lookup='healthy-player',
            game_date=date(2025, 12, 15),
            captured_injury_status=None,
            captured_injury_flag=False
        )

        assert result['is_voided'] is True
        assert result['void_reason'] == 'dnp_unknown'
        assert result['pre_game_injury_flag'] is False
        assert result['injury_confirmed_postgame'] is False

    def test_dnp_unknown_with_injury_flag_but_strange_status(self, processor):
        """Test DNP with injury flag but unusual status."""
        result = processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=0,
            player_lookup='player',
            game_date=date(2025, 12, 15),
            captured_injury_status='AVAILABLE',  # Unusual status
            captured_injury_flag=True
        )

        assert result['is_voided'] is True
        assert result['void_reason'] == 'dnp_unknown'

    def test_fallback_to_injury_lookup_when_no_captured_status(self, processor):
        """Test fallback to injury lookup when no captured status."""
        # Mock the injury cache with injury data
        processor._injury_cache['2025-12-15'] = {
            'injured-player': {
                'injury_status': 'OUT',
                'reason': 'Ankle sprain'
            }
        }

        result = processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=0,
            player_lookup='injured-player',
            game_date=date(2025, 12, 15)
            # No captured_injury_status provided
        )

        assert result['is_voided'] is True
        assert result['void_reason'] == 'dnp_injury_confirmed'
        assert result['pre_game_injury_flag'] is True
        assert result['pre_game_injury_status'] == 'OUT'

    def test_fallback_to_injury_lookup_questionable(self, processor):
        """Test fallback with QUESTIONABLE injury status."""
        processor._injury_cache['2025-12-15'] = {
            'game-time-decision': {
                'injury_status': 'QUESTIONABLE',
                'reason': 'Hamstring tightness'
            }
        }

        result = processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=0,
            player_lookup='game-time-decision',
            game_date=date(2025, 12, 15)
        )

        assert result['is_voided'] is True
        assert result['void_reason'] == 'dnp_late_scratch'

    def test_fallback_dnp_unknown_when_no_injury_report(self, processor):
        """Test fallback when no injury report exists."""
        processor._injury_cache['2025-12-15'] = {}  # No injury reports

        result = processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=0,
            player_lookup='healthy-scratch',
            game_date=date(2025, 12, 15)
        )

        assert result['is_voided'] is True
        assert result['void_reason'] == 'dnp_unknown'
        assert result['pre_game_injury_flag'] is False

    def test_case_insensitive_injury_status(self, processor):
        """Test that injury status comparison is case-insensitive."""
        result = processor.detect_dnp_voiding(
            actual_points=0,
            minutes_played=0,
            player_lookup='player',
            game_date=date(2025, 12, 15),
            captured_injury_status='out',  # lowercase
            captured_injury_flag=True
        )

        assert result['void_reason'] == 'dnp_injury_confirmed'


class TestSanitizeRecord:
    """Test _sanitize_record method for JSON compatibility."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery'):
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            return proc

    def test_passes_through_normal_values(self, processor):
        """Test that normal values pass through unchanged."""
        record = {
            'player_lookup': 'lebron-james',
            'predicted_points': 27.5,
            'actual_points': 30,
            'is_voided': False
        }

        result = processor._sanitize_record(record)

        assert result['player_lookup'] == 'lebron-james'
        assert result['predicted_points'] == 27.5
        assert result['actual_points'] == 30
        assert result['is_voided'] is False

    def test_converts_nan_to_none(self, processor):
        """Test that NaN values become None."""
        record = {
            'pace_adjustment': float('nan'),
            'confidence_score': math.nan
        }

        result = processor._sanitize_record(record)

        assert result['pace_adjustment'] is None
        assert result['confidence_score'] is None

    def test_converts_inf_to_none(self, processor):
        """Test that infinity values become None."""
        record = {
            'positive_inf': float('inf'),
            'negative_inf': float('-inf')
        }

        result = processor._sanitize_record(record)

        assert result['positive_inf'] is None
        assert result['negative_inf'] is None

    def test_preserves_none_values(self, processor):
        """Test that None values remain None."""
        record = {
            'line_value': None,
            'estimated_line_value': None
        }

        result = processor._sanitize_record(record)

        assert result['line_value'] is None
        assert result['estimated_line_value'] is None

    def test_preserves_boolean_values(self, processor):
        """Test that boolean values are preserved as booleans (not ints)."""
        record = {
            'is_voided': True,
            'prediction_correct': False,
            'within_3_points': True
        }

        result = processor._sanitize_record(record)

        assert result['is_voided'] is True
        assert isinstance(result['is_voided'], bool)
        assert result['prediction_correct'] is False
        assert isinstance(result['prediction_correct'], bool)

    def test_preserves_integer_values(self, processor):
        """Test that integer values are preserved."""
        record = {
            'actual_points': 25,
            'confidence_decile': 8
        }

        result = processor._sanitize_record(record)

        assert result['actual_points'] == 25
        assert result['confidence_decile'] == 8

    def test_preserves_string_values(self, processor):
        """Test that string values are preserved."""
        record = {
            'player_lookup': 'stephen-curry',
            'system_id': 'ensemble_v1'
        }

        result = processor._sanitize_record(record)

        assert result['player_lookup'] == 'stephen-curry'
        assert result['system_id'] == 'ensemble_v1'

    def test_converts_unsupported_types_to_string(self, processor):
        """Test that unsupported types are converted to strings."""
        record = {
            'game_date': date(2025, 12, 15)
        }

        result = processor._sanitize_record(record)

        assert result['game_date'] == '2025-12-15'
        assert isinstance(result['game_date'], str)

    def test_handles_mixed_record(self, processor):
        """Test sanitizing a record with mixed value types."""
        record = {
            'player_lookup': 'player-a',
            'predicted_points': 20.5,
            'actual_points': 22,
            'pace_adjustment': float('nan'),
            'is_voided': False,
            'void_reason': None,
            'confidence_score': 0.75
        }

        result = processor._sanitize_record(record)

        assert result['player_lookup'] == 'player-a'
        assert result['predicted_points'] == 20.5
        assert result['actual_points'] == 22
        assert result['pace_adjustment'] is None  # NaN converted
        assert result['is_voided'] is False
        assert result['void_reason'] is None
        assert result['confidence_score'] == 0.75


class TestGradePredictionDnpHandling:
    """Test grade_prediction method with DNP scenarios."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery'):
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            proc._injury_cache = {}
            return proc

    @pytest.fixture
    def sample_prediction(self):
        """Sample prediction for DNP player."""
        return {
            'player_lookup': 'injured-player',
            'game_id': '20251215_LAL_BOS',
            'game_date': date(2025, 12, 15),
            'system_id': 'ensemble_v1',
            'predicted_points': 20.5,
            'confidence_score': 0.65,
            'recommendation': 'OVER',
            'line_value': 18.5,
            'pace_adjustment': 1.02,
            'similarity_sample_size': 12,
            'model_version': 'v1.0',
            'has_prop_line': True,
            'line_source': 'ACTUAL_PROP',
            'estimated_line_value': None,
            'injury_status_at_prediction': 'QUESTIONABLE',
            'injury_flag_at_prediction': True,
            'injury_reason_at_prediction': 'Knee soreness'
        }

    def test_dnp_player_is_voided(self, processor, sample_prediction):
        """Test that DNP player prediction is marked as voided."""
        actual_data = {
            'actual_points': 0,
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'BOS',
            'minutes_played': 0  # DNP
        }

        result = processor.grade_prediction(
            sample_prediction, actual_data, sample_prediction['game_date']
        )

        assert result['is_voided'] is True
        assert result['void_reason'] is not None

    def test_dnp_player_prediction_correct_is_none(self, processor, sample_prediction):
        """Test that voided predictions have prediction_correct=None."""
        actual_data = {
            'actual_points': 0,
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'BOS',
            'minutes_played': 0
        }

        result = processor.grade_prediction(
            sample_prediction, actual_data, sample_prediction['game_date']
        )

        # Voided predictions should not have prediction_correct calculated
        assert result['prediction_correct'] is None

    def test_dnp_player_still_has_error_metrics(self, processor, sample_prediction):
        """Test that DNP players still have error metrics (for analysis)."""
        actual_data = {
            'actual_points': 0,
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'BOS',
            'minutes_played': 0
        }

        result = processor.grade_prediction(
            sample_prediction, actual_data, sample_prediction['game_date']
        )

        # Error metrics are still calculated (for ML analysis)
        # |20.5 - 0| = 20.5
        assert result['absolute_error'] == 20.5
        # 20.5 - 0 = 20.5 (over-predicted)
        assert result['signed_error'] == 20.5

    def test_dnp_player_injury_info_captured(self, processor, sample_prediction):
        """Test that DNP player injury info is captured in result."""
        actual_data = {
            'actual_points': 0,
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'BOS',
            'minutes_played': 0
        }

        result = processor.grade_prediction(
            sample_prediction, actual_data, sample_prediction['game_date']
        )

        assert result['pre_game_injury_flag'] is True
        assert result['pre_game_injury_status'] == 'QUESTIONABLE'

    def test_playing_player_not_voided(self, processor, sample_prediction):
        """Test that player who played is not voided."""
        actual_data = {
            'actual_points': 22,
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'BOS',
            'minutes_played': 28.5
        }

        result = processor.grade_prediction(
            sample_prediction, actual_data, sample_prediction['game_date']
        )

        assert result['is_voided'] is False
        assert result['void_reason'] is None
        # prediction_correct should be calculated
        # OVER 18.5, actual 22 > 18.5 -> correct
        assert result['prediction_correct'] is True

    def test_zero_points_with_minutes_not_voided(self, processor, sample_prediction):
        """Test that 0 points with minutes played is NOT voided."""
        sample_prediction['predicted_points'] = 8.0
        sample_prediction['line_value'] = 7.5
        actual_data = {
            'actual_points': 0,
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'BOS',
            'minutes_played': 12.0  # Played but scored 0
        }

        result = processor.grade_prediction(
            sample_prediction, actual_data, sample_prediction['game_date']
        )

        assert result['is_voided'] is False
        # OVER 7.5, actual 0 < 7.5 -> incorrect
        assert result['prediction_correct'] is False


class TestGradePredictionNullHandling:
    """Test grade_prediction with various null/None scenarios."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery'):
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            proc._injury_cache = {}
            return proc

    @pytest.fixture
    def base_prediction(self):
        """Base prediction for testing."""
        return {
            'player_lookup': 'test-player',
            'game_id': 'game1',
            'game_date': date(2025, 12, 15),
            'system_id': 'ensemble_v1',
            'predicted_points': 22.0,
            'confidence_score': 0.7,
            'recommendation': 'OVER',
            'line_value': 20.5,
            'pace_adjustment': 1.0,
            'similarity_sample_size': 10,
            'model_version': 'v1.0',
            'has_prop_line': True,
            'line_source': 'ACTUAL_PROP',
            'estimated_line_value': None
        }

    @pytest.fixture
    def base_actual(self):
        """Base actual data for testing."""
        return {
            'actual_points': 25,
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'BOS',
            'minutes_played': 32.0
        }

    def test_handles_none_actual_points_in_voiding_check(self, processor, base_prediction, base_actual):
        """Test that None actual_points is skipped in process_date (not grade_prediction)."""
        # Note: In process_date, None actual_points players are skipped
        # grade_prediction expects actual_points to be present
        base_actual['actual_points'] = None

        # This would normally be skipped in process_date
        # If called directly, prediction_correct should be None
        result = processor.grade_prediction(
            base_prediction, base_actual, base_prediction['game_date']
        )

        assert result['prediction_correct'] is None

    def test_handles_none_minutes_played(self, processor, base_prediction, base_actual):
        """Test handling when minutes_played is None."""
        base_actual['minutes_played'] = None

        result = processor.grade_prediction(
            base_prediction, base_actual, base_prediction['game_date']
        )

        assert result['minutes_played'] is None

    def test_handles_none_team_abbr(self, processor, base_prediction, base_actual):
        """Test handling when team_abbr is None."""
        base_actual['team_abbr'] = None
        base_actual['opponent_team_abbr'] = None

        result = processor.grade_prediction(
            base_prediction, base_actual, base_prediction['game_date']
        )

        assert result['team_abbr'] is None
        assert result['opponent_team_abbr'] is None


class TestGradePredictionZeroDivision:
    """Test grade_prediction with potential zero division scenarios."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery'):
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            proc._injury_cache = {}
            return proc

    def test_zero_line_value_margin_calculation(self, processor):
        """Test margin calculation with line_value=0."""
        prediction = {
            'player_lookup': 'player',
            'game_id': 'game1',
            'game_date': date(2025, 12, 15),
            'system_id': 'ensemble_v1',
            'predicted_points': 5.0,
            'confidence_score': 0.5,
            'recommendation': 'OVER',
            'line_value': 0.0,  # Zero line
            'pace_adjustment': None,
            'similarity_sample_size': None,
            'model_version': 'v1'
        }
        actual_data = {
            'actual_points': 3,
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'BOS',
            'minutes_played': 10.0
        }

        result = processor.grade_prediction(prediction, actual_data, prediction['game_date'])

        # predicted_margin = 5.0 - 0.0 = 5.0
        assert result['predicted_margin'] == 5.0
        # actual_margin = 3 - 0.0 = 3.0
        assert result['actual_margin'] == 3.0
        # OVER 0, actual 3 > 0 -> correct
        assert result['prediction_correct'] is True

    def test_zero_predicted_points(self, processor):
        """Test with predicted_points=0."""
        prediction = {
            'player_lookup': 'player',
            'game_id': 'game1',
            'game_date': date(2025, 12, 15),
            'system_id': 'ensemble_v1',
            'predicted_points': 0.0,
            'confidence_score': 0.3,
            'recommendation': 'UNDER',
            'line_value': 5.5,
            'pace_adjustment': None,
            'similarity_sample_size': None,
            'model_version': 'v1'
        }
        actual_data = {
            'actual_points': 2,
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'BOS',
            'minutes_played': 8.0
        }

        result = processor.grade_prediction(prediction, actual_data, prediction['game_date'])

        # |0 - 2| = 2
        assert result['absolute_error'] == 2.0
        # 0 - 2 = -2 (under-predicted)
        assert result['signed_error'] == -2.0
        # predicted_margin = 0 - 5.5 = -5.5
        assert result['predicted_margin'] == -5.5

    def test_zero_actual_and_predicted_points(self, processor):
        """Test with both actual and predicted = 0."""
        prediction = {
            'player_lookup': 'player',
            'game_id': 'game1',
            'game_date': date(2025, 12, 15),
            'system_id': 'ensemble_v1',
            'predicted_points': 0.0,
            'confidence_score': 0.2,
            'recommendation': 'UNDER',
            'line_value': 3.5,
            'pace_adjustment': None,
            'similarity_sample_size': None,
            'model_version': 'v1'
        }
        actual_data = {
            'actual_points': 0,
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'BOS',
            'minutes_played': 5.0  # Played but scored 0
        }

        result = processor.grade_prediction(prediction, actual_data, prediction['game_date'])

        # |0 - 0| = 0
        assert result['absolute_error'] == 0.0
        # 0 - 0 = 0
        assert result['signed_error'] == 0.0
        # within_3_points and within_5_points should be True (0 <= 3, 0 <= 5)
        assert result['within_3_points'] is True
        assert result['within_5_points'] is True


class TestConfidenceNormalization:
    """Test confidence score normalization (0-100 to 0-1)."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery'):
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            proc._injury_cache = {}
            return proc

    def test_normalizes_percentage_confidence(self, processor):
        """Test that confidence > 1 is normalized to 0-1 range."""
        prediction = {
            'player_lookup': 'player',
            'game_id': 'game1',
            'game_date': date(2025, 12, 15),
            'system_id': 'catboost_v8',
            'predicted_points': 25.0,
            'confidence_score': 75.0,  # 75% in 0-100 format
            'recommendation': 'OVER',
            'line_value': 22.5,
            'pace_adjustment': None,
            'similarity_sample_size': None,
            'model_version': 'v8'
        }
        actual_data = {
            'actual_points': 28,
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'BOS',
            'minutes_played': 35.0
        }

        result = processor.grade_prediction(prediction, actual_data, prediction['game_date'])

        # 75.0 / 100 = 0.75
        assert result['confidence_score'] == 0.75
        # Decile for 0.75 should be 8
        assert result['confidence_decile'] == 8

    def test_preserves_0_to_1_confidence(self, processor):
        """Test that confidence already in 0-1 range is preserved."""
        prediction = {
            'player_lookup': 'player',
            'game_id': 'game1',
            'game_date': date(2025, 12, 15),
            'system_id': 'ensemble_v1',
            'predicted_points': 25.0,
            'confidence_score': 0.72,  # Already 0-1 format
            'recommendation': 'OVER',
            'line_value': 22.5,
            'pace_adjustment': None,
            'similarity_sample_size': None,
            'model_version': 'v1'
        }
        actual_data = {
            'actual_points': 28,
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'BOS',
            'minutes_played': 35.0
        }

        result = processor.grade_prediction(prediction, actual_data, prediction['game_date'])

        assert result['confidence_score'] == 0.72


class TestSafeString:
    """Test _safe_string method for sanitization."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery'):
            proc = PredictionAccuracyProcessor(project_id='test-project')
            proc.bq_client = Mock()
            return proc

    def test_passes_through_normal_string(self, processor):
        """Test normal string passes through."""
        assert processor._safe_string('lebron-james') == 'lebron-james'

    def test_returns_none_for_none(self, processor):
        """Test None returns None."""
        assert processor._safe_string(None) is None

    def test_removes_control_characters(self, processor):
        """Test that control characters are removed."""
        # String with tab and newline
        result = processor._safe_string('hello\tworld\n')
        assert '\t' not in result
        assert '\n' not in result

    def test_truncates_long_strings(self, processor):
        """Test that strings > 500 chars are truncated."""
        long_string = 'a' * 600
        result = processor._safe_string(long_string)
        assert len(result) == 500

    def test_converts_non_string_to_string(self, processor):
        """Test that non-strings are converted."""
        assert processor._safe_string(123) == '123'
        assert processor._safe_string(45.67) == '45.67'


# ============================================================================
# Test Summary
# ============================================================================
# Total Tests: 100+ unit tests
# Coverage: Core processor methods for prediction grading
#
# Test Distribution:
# - _is_nan helper: 7 tests
# - _safe_float helper: 7 tests
# - _safe_string helper: 5 tests
# - compute_prediction_correct: 10 tests
# - compute_confidence_decile: 8 tests
# - grade_prediction: 22 tests
# - grade_prediction DNP handling: 6 tests
# - grade_prediction null handling: 3 tests
# - grade_prediction zero division: 3 tests
# - detect_dnp_voiding: 15 tests
# - _sanitize_record: 9 tests
# - confidence normalization: 2 tests
# - process_date: 5 tests
# - write_graded_results: 4 tests (skipped - requires Firestore)
# - check_predictions_exist: 2 tests
# - check_actuals_exist: 2 tests
#
# Run with:
#   pytest tests/processors/grading/prediction_accuracy/test_unit.py -v
#   pytest tests/processors/grading/prediction_accuracy/test_unit.py -k "dnp" -v
#   pytest tests/processors/grading/prediction_accuracy/test_unit.py -k "sanitize" -v
# ============================================================================

"""
Unit Tests for LiveGradingExporter

Tests cover:
1. Prediction grading against live scores
2. Status determination (correct/incorrect/pending/trending)
3. Summary statistics computation
4. Player lookup cache building
5. Live scores map building
6. Empty data handling
7. Mock API and BigQuery responses
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date
import requests

from data_processors.publishing.live_grading_exporter import LiveGradingExporter


class MockBigQueryClient:
    """Mock BigQuery client for testing"""

    def __init__(self):
        self.query_results = []
        self.query_calls = []

    def query(self, sql, job_config=None):
        """Mock query execution"""
        self.query_calls.append({'sql': sql, 'config': job_config})
        mock_result = Mock()
        mock_result.result.return_value = self.query_results
        return mock_result

    def set_results(self, results):
        """Set results to return from next query"""
        self.query_results = results


class TestLiveGradingExporterInit:
    """Test suite for initialization"""

    def test_initialization(self):
        """Test that exporter initializes correctly"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()
                assert exporter is not None
                assert exporter._player_lookup_cache == {}


class TestGenerateJson:
    """Test suite for generate_json method"""

    def test_generate_json_with_predictions(self):
        """Test JSON generation with predictions and live data"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                with patch.object(LiveGradingExporter, '_fetch_live_box_scores') as mock_fetch:
                    with patch.object(LiveGradingExporter, '_build_player_lookup_cache'):
                        mock_client = MockBigQueryClient()
                        mock_client.set_results([
                            {
                                'player_lookup': 'lebronjames',
                                'player_name': 'LeBron James',
                                'game_id': '12345',
                                'home_team': 'LAL',
                                'away_team': 'GSW',
                                'predicted_points': 27.5,
                                'confidence_score': 0.78,
                                'recommendation': 'OVER',
                                'line_value': 25.5,
                                'has_prop_line': True,
                                'line_source': 'draftkings'
                            }
                        ])
                        mock_bq.return_value = mock_client

                        mock_fetch.return_value = []  # No live games yet

                        exporter = LiveGradingExporter()
                        result = exporter.generate_json('2024-12-15')

                        assert result['game_date'] == '2024-12-15'
                        assert 'summary' in result
                        assert 'predictions' in result
                        assert len(result['predictions']) == 1

    def test_generate_json_no_predictions(self):
        """Test JSON generation when no predictions exist"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])
                mock_bq.return_value = mock_client

                exporter = LiveGradingExporter()
                result = exporter.generate_json('2024-12-15')

                assert result['game_date'] == '2024-12-15'
                assert result['summary']['total_predictions'] == 0
                assert result['predictions'] == []


class TestGradePredictions:
    """Test suite for _grade_predictions method"""

    def test_grade_correct_over(self):
        """Test grading correct OVER prediction for final game"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()

                predictions = [
                    {
                        'player_lookup': 'player1',
                        'player_name': 'Player One',
                        'predicted_points': 28.0,
                        'line_value': 25.5,
                        'recommendation': 'OVER',
                        'confidence_score': 0.75,
                        'has_prop_line': True,
                        'home_team': 'LAL',
                        'away_team': 'GSW'
                    }
                ]

                live_scores = {
                    'player1': {
                        'points': 30,  # Scored over 25.5
                        'minutes': '35:00',
                        'team': 'LAL',
                        'game_status': 'final'
                    }
                }

                result = exporter._grade_predictions(predictions, live_scores)

                assert len(result) == 1
                assert result[0]['status'] == 'correct'
                assert result[0]['actual'] == 30
                assert result[0]['margin_vs_line'] == 4.5

    def test_grade_incorrect_over(self):
        """Test grading incorrect OVER prediction for final game"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()

                predictions = [
                    {
                        'player_lookup': 'player1',
                        'player_name': 'Player One',
                        'predicted_points': 28.0,
                        'line_value': 25.5,
                        'recommendation': 'OVER',
                        'confidence_score': 0.75,
                        'has_prop_line': True,
                        'home_team': 'LAL',
                        'away_team': 'GSW'
                    }
                ]

                live_scores = {
                    'player1': {
                        'points': 20,  # Scored under 25.5
                        'minutes': '32:00',
                        'team': 'LAL',
                        'game_status': 'final'
                    }
                }

                result = exporter._grade_predictions(predictions, live_scores)

                assert result[0]['status'] == 'incorrect'

    def test_grade_correct_under(self):
        """Test grading correct UNDER prediction for final game"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()

                predictions = [
                    {
                        'player_lookup': 'player1',
                        'player_name': 'Player One',
                        'predicted_points': 22.0,
                        'line_value': 25.5,
                        'recommendation': 'UNDER',
                        'confidence_score': 0.70,
                        'has_prop_line': True,
                        'home_team': 'LAL',
                        'away_team': 'GSW'
                    }
                ]

                live_scores = {
                    'player1': {
                        'points': 18,  # Scored under 25.5
                        'minutes': '28:00',
                        'team': 'LAL',
                        'game_status': 'final'
                    }
                }

                result = exporter._grade_predictions(predictions, live_scores)

                assert result[0]['status'] == 'correct'

    def test_grade_pending_no_live_data(self):
        """Test grading when no live data available"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()

                predictions = [
                    {
                        'player_lookup': 'player1',
                        'player_name': 'Player One',
                        'predicted_points': 28.0,
                        'line_value': 25.5,
                        'recommendation': 'OVER',
                        'confidence_score': 0.75,
                        'has_prop_line': True,
                        'home_team': 'LAL',
                        'away_team': 'GSW'
                    }
                ]

                live_scores = {}  # No live data

                result = exporter._grade_predictions(predictions, live_scores)

                assert result[0]['status'] == 'pending'
                assert result[0]['actual'] is None

    def test_grade_trending_correct_in_progress(self):
        """Test trending_correct status for in-progress game"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()

                predictions = [
                    {
                        'player_lookup': 'player1',
                        'player_name': 'Player One',
                        'predicted_points': 28.0,
                        'line_value': 20.5,
                        'recommendation': 'OVER',
                        'confidence_score': 0.75,
                        'has_prop_line': True,
                        'home_team': 'LAL',
                        'away_team': 'GSW'
                    }
                ]

                live_scores = {
                    'player1': {
                        'points': 22,  # Already over 20.5 line
                        'minutes': '20:00',
                        'team': 'LAL',
                        'game_status': 'in_progress'
                    }
                }

                result = exporter._grade_predictions(predictions, live_scores)

                assert result[0]['status'] == 'trending_correct'

    def test_grade_trending_incorrect_in_progress(self):
        """Test trending_incorrect status for in-progress game"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()

                predictions = [
                    {
                        'player_lookup': 'player1',
                        'player_name': 'Player One',
                        'predicted_points': 28.0,
                        'line_value': 25.5,
                        'recommendation': 'OVER',
                        'confidence_score': 0.75,
                        'has_prop_line': True,
                        'home_team': 'LAL',
                        'away_team': 'GSW'
                    }
                ]

                live_scores = {
                    'player1': {
                        'points': 10,  # Significantly under (< line - 5)
                        'minutes': '25:00',
                        'team': 'LAL',
                        'game_status': 'in_progress'
                    }
                }

                result = exporter._grade_predictions(predictions, live_scores)

                assert result[0]['status'] == 'trending_incorrect'


class TestComputeSummary:
    """Test suite for _compute_summary method"""

    def test_compute_summary_basic(self):
        """Test basic summary computation"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()

                graded_predictions = [
                    {'status': 'correct', 'actual': 30, 'error': -2.0},
                    {'status': 'correct', 'actual': 25, 'error': 1.5},
                    {'status': 'incorrect', 'actual': 15, 'error': 10.0},
                    {'status': 'pending', 'actual': None, 'error': None}
                ]

                live_data = [
                    {'status': 'Final', 'period': 4},
                    {'status': 'in progress', 'period': 2}
                ]

                summary = exporter._compute_summary(graded_predictions, live_data)

                assert summary['total_predictions'] == 4
                assert summary['graded'] == 3
                assert summary['pending'] == 1
                assert summary['correct'] == 2
                assert summary['incorrect'] == 1
                assert summary['win_rate'] == 0.667  # 2/3

    def test_compute_summary_average_error(self):
        """Test average error calculation"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()

                graded_predictions = [
                    {'status': 'correct', 'actual': 30, 'error': -2.0},
                    {'status': 'incorrect', 'actual': 15, 'error': 6.0}
                ]

                live_data = [{'status': 'Final', 'period': 4}]

                summary = exporter._compute_summary(graded_predictions, live_data)

                # Average of abs(-2.0) and abs(6.0) = (2 + 6) / 2 = 4.0
                assert summary['avg_error'] == 4.0

    def test_compute_summary_trending_counts(self):
        """Test trending counts in summary"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()

                graded_predictions = [
                    {'status': 'trending_correct', 'actual': 20, 'error': -3.0},
                    {'status': 'trending_correct', 'actual': 22, 'error': -2.0},
                    {'status': 'trending_incorrect', 'actual': 10, 'error': 8.0}
                ]

                live_data = [{'status': 'in progress', 'period': 2}]

                summary = exporter._compute_summary(graded_predictions, live_data)

                assert summary['trending_correct'] == 2
                assert summary['trending_incorrect'] == 1


class TestBuildLiveScoresMap:
    """Test suite for _build_live_scores_map method"""

    def test_build_live_scores_map(self):
        """Test building live scores map from API data"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()
                exporter._player_lookup_cache = {123: 'lebronjames'}

                live_data = [
                    {
                        'date': '2024-12-15',
                        'status': 'in progress',
                        'period': 2,
                        'time': '3:45',
                        'home_team': {
                            'abbreviation': 'LAL',
                            'players': [
                                {
                                    'player': {'id': 123, 'first_name': 'LeBron', 'last_name': 'James'},
                                    'pts': 20,
                                    'min': '22:30'
                                }
                            ]
                        },
                        'visitor_team': {
                            'abbreviation': 'GSW',
                            'players': []
                        }
                    }
                ]

                result = exporter._build_live_scores_map(live_data, '2024-12-15')

                assert 'lebronjames' in result
                assert result['lebronjames']['points'] == 20
                assert result['lebronjames']['team'] == 'LAL'
                assert result['lebronjames']['game_status'] == 'in_progress'

    def test_build_live_scores_map_filters_dates(self):
        """Test that games from other dates are filtered"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()
                exporter._player_lookup_cache = {123: 'lebronjames'}

                live_data = [
                    {
                        'date': '2024-12-14',  # Different date
                        'status': 'Final',
                        'period': 4,
                        'home_team': {
                            'abbreviation': 'LAL',
                            'players': [
                                {
                                    'player': {'id': 123},
                                    'pts': 30,
                                    'min': '35:00'
                                }
                            ]
                        },
                        'visitor_team': {'abbreviation': 'GSW', 'players': []}
                    }
                ]

                result = exporter._build_live_scores_map(live_data, '2024-12-15')

                assert len(result) == 0


class TestAddPlayerToMap:
    """Test suite for _add_player_to_map method"""

    def test_add_player_with_cache(self):
        """Test adding player with cached lookup"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()
                exporter._player_lookup_cache = {456: 'stephencurry'}

                live_scores = {}
                player_stat = {
                    'player': {'id': 456, 'first_name': 'Stephen', 'last_name': 'Curry'},
                    'pts': 35,
                    'min': '38:00'
                }

                exporter._add_player_to_map(
                    live_scores, player_stat, 'GSW', 'in_progress', 3, '4:30'
                )

                assert 'stephencurry' in live_scores
                assert live_scores['stephencurry']['points'] == 35

    def test_add_player_fallback_lookup(self):
        """Test adding player with fallback lookup generation"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()
                exporter._player_lookup_cache = {}  # Empty cache

                live_scores = {}
                player_stat = {
                    'player': {'id': 789, 'first_name': 'New', 'last_name': 'Player'},
                    'pts': 15,
                    'min': '20:00'
                }

                exporter._add_player_to_map(
                    live_scores, player_stat, 'BOS', 'in_progress', 2, '5:00'
                )

                assert 'newplayer' in live_scores


class TestFetchLiveBoxScores:
    """Test suite for _fetch_live_box_scores method"""

    def test_fetch_success(self):
        """Test successful API fetch"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                with patch('data_processors.publishing.live_grading_exporter.requests.get') as mock_get:
                    mock_response = Mock()
                    mock_response.json.return_value = {
                        'data': [{'id': '123', 'status': 'in progress'}]
                    }
                    mock_response.raise_for_status = Mock()
                    mock_get.return_value = mock_response

                    exporter = LiveGradingExporter()
                    result = exporter._fetch_live_box_scores()

                    assert len(result) == 1

    def test_fetch_api_error(self):
        """Test API error handling"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                with patch('data_processors.publishing.live_grading_exporter.requests.get') as mock_get:
                    mock_get.side_effect = requests.RequestException("API Error")

                    exporter = LiveGradingExporter()
                    result = exporter._fetch_live_box_scores()

                    assert result == []


class TestEmptyResponse:
    """Test suite for empty response structure"""

    def test_empty_response_structure(self):
        """Test that empty response has correct structure"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()
                response = exporter._empty_response('2024-12-15')

                assert response['game_date'] == '2024-12-15'
                assert response['predictions'] == []
                assert 'summary' in response
                assert response['summary']['total_predictions'] == 0
                assert response['summary']['graded'] == 0
                assert response['summary']['pending'] == 0
                assert response['summary']['correct'] == 0
                assert response['summary']['incorrect'] == 0
                assert response['summary']['win_rate'] is None
                assert response['summary']['avg_error'] is None


class TestPredictionSorting:
    """Test suite for prediction sorting in output"""

    def test_predictions_sorted_by_status_and_confidence(self):
        """Test that predictions are sorted by status then confidence"""
        with patch('data_processors.publishing.live_grading_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveGradingExporter()

                predictions = [
                    {
                        'player_lookup': 'pending_player',
                        'player_name': 'Pending Player',
                        'predicted_points': 25.0,
                        'line_value': 24.5,
                        'recommendation': 'OVER',
                        'confidence_score': 0.90,  # High confidence but pending
                        'has_prop_line': True,
                        'home_team': 'LAL',
                        'away_team': 'GSW'
                    },
                    {
                        'player_lookup': 'correct_player',
                        'player_name': 'Correct Player',
                        'predicted_points': 28.0,
                        'line_value': 25.5,
                        'recommendation': 'OVER',
                        'confidence_score': 0.75,
                        'has_prop_line': True,
                        'home_team': 'LAL',
                        'away_team': 'GSW'
                    }
                ]

                live_scores = {
                    'correct_player': {
                        'points': 30,
                        'minutes': '35:00',
                        'team': 'LAL',
                        'game_status': 'final'
                    }
                }

                result = exporter._grade_predictions(predictions, live_scores)

                # Correct should come before pending
                assert result[0]['player_lookup'] == 'correct_player'
                assert result[1]['player_lookup'] == 'pending_player'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

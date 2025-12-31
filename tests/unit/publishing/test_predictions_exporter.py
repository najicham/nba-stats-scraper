"""
Unit Tests for PredictionsExporter

Tests cover:
1. Prediction query and formatting
2. Game grouping and sorting
3. Edge calculation
4. Empty data handling
5. Mock BigQuery responses
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date

from data_processors.publishing.predictions_exporter import PredictionsExporter


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


class TestPredictionsExporterInit:
    """Test suite for initialization"""

    def test_initialization(self):
        """Test that exporter initializes correctly"""
        with patch('data_processors.publishing.predictions_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PredictionsExporter()
                assert exporter is not None


class TestGenerateJson:
    """Test suite for generate_json method"""

    def test_generate_json_with_predictions(self):
        """Test JSON generation with valid predictions"""
        with patch('data_processors.publishing.predictions_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'lebronjames',
                        'game_id': '20241215_LAL_GSW',
                        'game_date': date(2024, 12, 15),
                        'predicted_points': 27.5,
                        'confidence_score': 0.78,
                        'recommendation': 'OVER',
                        'line_value': 25.5,
                        'pace_adjustment': 1.02,
                        'similar_games_count': 15,
                        'team_abbr': 'LAL',
                        'opponent_team_abbr': 'GSW'
                    },
                    {
                        'player_lookup': 'stephencurry',
                        'game_id': '20241215_LAL_GSW',
                        'game_date': date(2024, 12, 15),
                        'predicted_points': 29.0,
                        'confidence_score': 0.82,
                        'recommendation': 'OVER',
                        'line_value': 26.5,
                        'pace_adjustment': 0.98,
                        'similar_games_count': 20,
                        'team_abbr': 'GSW',
                        'opponent_team_abbr': 'LAL'
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = PredictionsExporter()

                result = exporter.generate_json('2024-12-15')

                assert result['game_date'] == '2024-12-15'
                assert result['total_games'] == 1
                assert result['total_predictions'] == 2
                assert len(result['games']) == 1
                assert 'generated_at' in result

    def test_generate_json_empty_predictions(self):
        """Test JSON generation with no predictions"""
        with patch('data_processors.publishing.predictions_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])
                mock_bq.return_value = mock_client
                exporter = PredictionsExporter()

                result = exporter.generate_json('2024-12-15')

                assert result['game_date'] == '2024-12-15'
                assert result['total_games'] == 0
                assert result['total_predictions'] == 0
                assert result['games'] == []


class TestGroupByGame:
    """Test suite for game grouping logic"""

    def test_group_by_game_single_game(self):
        """Test grouping predictions into a single game"""
        with patch('data_processors.publishing.predictions_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'game_id': '20241215_BOS_MIA',
                        'game_date': date(2024, 12, 15),
                        'predicted_points': 22.0,
                        'confidence_score': 0.65,
                        'recommendation': 'UNDER',
                        'line_value': 24.5,
                        'pace_adjustment': 1.0,
                        'similar_games_count': 10,
                        'team_abbr': 'BOS',
                        'opponent_team_abbr': 'MIA'
                    },
                    {
                        'player_lookup': 'player2',
                        'game_id': '20241215_BOS_MIA',
                        'game_date': date(2024, 12, 15),
                        'predicted_points': 18.5,
                        'confidence_score': 0.70,
                        'recommendation': 'OVER',
                        'line_value': 16.5,
                        'pace_adjustment': 1.05,
                        'similar_games_count': 12,
                        'team_abbr': 'MIA',
                        'opponent_team_abbr': 'BOS'
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = PredictionsExporter()

                result = exporter.generate_json('2024-12-15')

                assert len(result['games']) == 1
                game = result['games'][0]
                assert game['game_id'] == '20241215_BOS_MIA'
                assert game['home_team'] == 'MIA'
                assert game['away_team'] == 'BOS'
                assert game['prediction_count'] == 2

    def test_group_by_game_multiple_games(self):
        """Test grouping predictions into multiple games"""
        with patch('data_processors.publishing.predictions_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'game_id': '20241215_BOS_MIA',
                        'game_date': date(2024, 12, 15),
                        'predicted_points': 22.0,
                        'confidence_score': 0.65,
                        'recommendation': 'UNDER',
                        'line_value': 24.5,
                        'pace_adjustment': 1.0,
                        'similar_games_count': 10,
                        'team_abbr': 'BOS',
                        'opponent_team_abbr': 'MIA'
                    },
                    {
                        'player_lookup': 'player2',
                        'game_id': '20241215_LAL_GSW',
                        'game_date': date(2024, 12, 15),
                        'predicted_points': 28.0,
                        'confidence_score': 0.80,
                        'recommendation': 'OVER',
                        'line_value': 25.5,
                        'pace_adjustment': 1.02,
                        'similar_games_count': 18,
                        'team_abbr': 'LAL',
                        'opponent_team_abbr': 'GSW'
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = PredictionsExporter()

                result = exporter.generate_json('2024-12-15')

                assert len(result['games']) == 2
                assert result['total_predictions'] == 2


class TestRecommendationBreakdown:
    """Test suite for recommendation breakdown counting"""

    def test_recommendation_breakdown(self):
        """Test that recommendation counts are correct"""
        with patch('data_processors.publishing.predictions_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'game_id': '20241215_BOS_MIA',
                        'game_date': date(2024, 12, 15),
                        'predicted_points': 22.0,
                        'confidence_score': 0.65,
                        'recommendation': 'OVER',
                        'line_value': 20.5,
                        'pace_adjustment': 1.0,
                        'similar_games_count': 10,
                        'team_abbr': 'BOS',
                        'opponent_team_abbr': 'MIA'
                    },
                    {
                        'player_lookup': 'player2',
                        'game_id': '20241215_BOS_MIA',
                        'game_date': date(2024, 12, 15),
                        'predicted_points': 18.0,
                        'confidence_score': 0.60,
                        'recommendation': 'UNDER',
                        'line_value': 20.5,
                        'pace_adjustment': 1.0,
                        'similar_games_count': 10,
                        'team_abbr': 'MIA',
                        'opponent_team_abbr': 'BOS'
                    },
                    {
                        'player_lookup': 'player3',
                        'game_id': '20241215_BOS_MIA',
                        'game_date': date(2024, 12, 15),
                        'predicted_points': 15.0,
                        'confidence_score': 0.45,
                        'recommendation': 'PASS',
                        'line_value': 14.5,
                        'pace_adjustment': 1.0,
                        'similar_games_count': 5,
                        'team_abbr': 'BOS',
                        'opponent_team_abbr': 'MIA'
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = PredictionsExporter()

                result = exporter.generate_json('2024-12-15')

                game = result['games'][0]
                assert game['recommendation_breakdown']['over'] == 1
                assert game['recommendation_breakdown']['under'] == 1
                assert game['recommendation_breakdown']['pass'] == 1


class TestEdgeCalculation:
    """Test suite for edge calculation"""

    def test_calc_edge_positive(self):
        """Test positive edge calculation (predicted > line)"""
        with patch('data_processors.publishing.predictions_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PredictionsExporter()

                pred = {'predicted_points': 28.5, 'line_value': 25.5}
                edge = exporter._calc_edge(pred)

                assert edge == 3.0

    def test_calc_edge_negative(self):
        """Test negative edge calculation (predicted < line)"""
        with patch('data_processors.publishing.predictions_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PredictionsExporter()

                pred = {'predicted_points': 22.0, 'line_value': 25.5}
                edge = exporter._calc_edge(pred)

                assert edge == -3.5

    def test_calc_edge_none_values(self):
        """Test edge calculation with None values"""
        with patch('data_processors.publishing.predictions_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PredictionsExporter()

                assert exporter._calc_edge({'predicted_points': None, 'line_value': 25.5}) is None
                assert exporter._calc_edge({'predicted_points': 28.0, 'line_value': None}) is None
                assert exporter._calc_edge({'predicted_points': None, 'line_value': None}) is None


class TestSafeFloat:
    """Test suite for _safe_float utility method"""

    def test_safe_float_valid(self):
        """Test valid float conversion"""
        with patch('data_processors.publishing.predictions_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PredictionsExporter()

                assert exporter._safe_float(25.567) == 25.57
                assert exporter._safe_float(10) == 10.0
                assert exporter._safe_float(0.789) == 0.79

    def test_safe_float_none(self):
        """Test None handling"""
        with patch('data_processors.publishing.predictions_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PredictionsExporter()

                assert exporter._safe_float(None) is None

    def test_safe_float_nan(self):
        """Test NaN handling"""
        with patch('data_processors.publishing.predictions_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PredictionsExporter()

                assert exporter._safe_float(float('nan')) is None


class TestPredictionFormatting:
    """Test suite for prediction formatting in output"""

    def test_prediction_structure(self):
        """Test that predictions have correct structure"""
        with patch('data_processors.publishing.predictions_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'lebronjames',
                        'game_id': '20241215_LAL_GSW',
                        'game_date': date(2024, 12, 15),
                        'predicted_points': 27.5,
                        'confidence_score': 0.78,
                        'recommendation': 'OVER',
                        'line_value': 25.5,
                        'pace_adjustment': 1.02,
                        'similar_games_count': 15,
                        'team_abbr': 'LAL',
                        'opponent_team_abbr': 'GSW'
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = PredictionsExporter()

                result = exporter.generate_json('2024-12-15')

                prediction = result['games'][0]['predictions'][0]
                assert prediction['player_lookup'] == 'lebronjames'
                assert prediction['team'] == 'LAL'
                assert 'prediction' in prediction
                assert prediction['prediction']['points'] == 27.5
                assert prediction['prediction']['confidence'] == 0.78
                assert prediction['prediction']['recommendation'] == 'OVER'
                assert prediction['prediction']['line'] == 25.5
                assert prediction['prediction']['edge'] == 2.0
                assert 'context' in prediction
                assert prediction['context']['pace_adjustment'] == 1.02


class TestEmptyResponse:
    """Test suite for empty response structure"""

    def test_empty_response_structure(self):
        """Test that empty response has correct structure"""
        with patch('data_processors.publishing.predictions_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PredictionsExporter()
                response = exporter._empty_response('2024-12-15')

                assert response['game_date'] == '2024-12-15'
                assert response['total_games'] == 0
                assert response['total_predictions'] == 0
                assert response['games'] == []
                assert 'generated_at' in response


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

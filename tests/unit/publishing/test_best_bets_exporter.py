"""
Unit Tests for BestBetsExporter

Tests cover:
1. Composite score calculation and ranking
2. Pick formatting with rationale
3. Fatigue level classification
4. Result determination (WIN/LOSS/PENDING)
5. Empty data handling
6. Mock BigQuery responses
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date

from data_processors.publishing.best_bets_exporter import BestBetsExporter


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


class TestBestBetsExporterInit:
    """Test suite for initialization"""

    def test_initialization(self):
        """Test that exporter initializes correctly"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()
                assert exporter is not None
                assert exporter.DEFAULT_TOP_N == 15


class TestGenerateJson:
    """Test suite for generate_json method"""

    def test_generate_json_with_picks(self):
        """Test JSON generation with valid picks"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'lebronjames',
                        'player_full_name': 'LeBron James',
                        'game_id': '20241215_LAL_GSW',
                        'team_abbr': 'LAL',
                        'opponent_team_abbr': 'GSW',
                        'predicted_points': 28.5,
                        'actual_points': None,
                        'line_value': 25.5,
                        'recommendation': 'OVER',
                        'prediction_correct': None,
                        'confidence_score': 0.82,
                        'absolute_error': None,
                        'signed_error': None,
                        'edge': 3.0,
                        'player_historical_accuracy': 0.78,
                        'player_sample_size': 25,
                        'fatigue_score': 92,
                        'edge_factor': 1.3,
                        'hist_factor': 0.78,
                        'composite_score': 0.85
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')

                assert result['game_date'] == '2024-12-15'
                assert result['total_picks'] == 1
                assert 'methodology' in result
                assert len(result['picks']) == 1
                assert 'generated_at' in result

    def test_generate_json_empty_picks(self):
        """Test JSON generation with no picks"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')

                assert result['game_date'] == '2024-12-15'
                assert result['total_picks'] == 0
                assert result['picks'] == []

    def test_generate_json_custom_top_n(self):
        """Test JSON generation with custom top_n parameter"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                # Return more results than top_n
                mock_client.set_results([
                    {
                        'player_lookup': f'player{i}',
                        'player_full_name': f'Player {i}',
                        'game_id': '20241215_LAL_GSW',
                        'team_abbr': 'LAL',
                        'opponent_team_abbr': 'GSW',
                        'predicted_points': 25.0 + i,
                        'actual_points': None,
                        'line_value': 24.0,
                        'recommendation': 'OVER',
                        'prediction_correct': None,
                        'confidence_score': 0.7,
                        'absolute_error': None,
                        'signed_error': None,
                        'edge': 1.0 + i,
                        'player_historical_accuracy': 0.7,
                        'player_sample_size': 10,
                        'fatigue_score': 90,
                        'edge_factor': 1.1,
                        'hist_factor': 0.7,
                        'composite_score': 0.7 + (i * 0.01)
                    }
                    for i in range(5)
                ])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15', top_n=5)

                assert result['total_picks'] == 5


class TestPickFormatting:
    """Test suite for pick formatting"""

    def test_pick_structure(self):
        """Test that formatted picks have correct structure"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'stephencurry',
                        'player_full_name': 'Stephen Curry',
                        'game_id': '20241215_LAL_GSW',
                        'team_abbr': 'GSW',
                        'opponent_team_abbr': 'LAL',
                        'predicted_points': 29.0,
                        'actual_points': 32,
                        'line_value': 26.5,
                        'recommendation': 'OVER',
                        'prediction_correct': True,
                        'confidence_score': 0.85,
                        'absolute_error': 3.0,
                        'signed_error': -3.0,
                        'edge': 2.5,
                        'player_historical_accuracy': 0.82,
                        'player_sample_size': 30,
                        'fatigue_score': 95,
                        'edge_factor': 1.25,
                        'hist_factor': 0.82,
                        'composite_score': 0.91
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')
                pick = result['picks'][0]

                assert pick['rank'] == 1
                assert pick['player_lookup'] == 'stephencurry'
                assert pick['player_full_name'] == 'Stephen Curry'
                assert pick['game_id'] == '20241215_LAL_GSW'
                assert pick['team'] == 'GSW'
                assert pick['opponent'] == 'LAL'
                assert pick['recommendation'] == 'OVER'
                assert pick['line'] == 26.5
                assert pick['predicted'] == 29.0
                assert pick['edge'] == 2.5
                assert pick['confidence'] == 0.85
                assert pick['composite_score'] == 0.91
                assert pick['result'] == 'WIN'
                assert pick['actual'] == 32
                assert 'rationale' in pick


class TestResultDetermination:
    """Test suite for result determination logic"""

    def test_result_win(self):
        """Test WIN result when prediction is correct"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_full_name': 'Player One',
                        'game_id': '20241215_BOS_MIA',
                        'team_abbr': 'BOS',
                        'opponent_team_abbr': 'MIA',
                        'predicted_points': 25.0,
                        'actual_points': 28,
                        'line_value': 24.5,
                        'recommendation': 'OVER',
                        'prediction_correct': True,
                        'confidence_score': 0.7,
                        'absolute_error': 3.0,
                        'signed_error': -3.0,
                        'edge': 0.5,
                        'player_historical_accuracy': 0.7,
                        'player_sample_size': 15,
                        'fatigue_score': 85,
                        'edge_factor': 1.05,
                        'hist_factor': 0.7,
                        'composite_score': 0.75
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')
                assert result['picks'][0]['result'] == 'WIN'

    def test_result_loss(self):
        """Test LOSS result when prediction is incorrect"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_full_name': 'Player One',
                        'game_id': '20241215_BOS_MIA',
                        'team_abbr': 'BOS',
                        'opponent_team_abbr': 'MIA',
                        'predicted_points': 25.0,
                        'actual_points': 20,
                        'line_value': 24.5,
                        'recommendation': 'OVER',
                        'prediction_correct': False,
                        'confidence_score': 0.7,
                        'absolute_error': 5.0,
                        'signed_error': 5.0,
                        'edge': 0.5,
                        'player_historical_accuracy': 0.7,
                        'player_sample_size': 15,
                        'fatigue_score': 85,
                        'edge_factor': 1.05,
                        'hist_factor': 0.7,
                        'composite_score': 0.75
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')
                assert result['picks'][0]['result'] == 'LOSS'

    def test_result_pending(self):
        """Test PENDING result when game hasn't finished"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_full_name': 'Player One',
                        'game_id': '20241215_BOS_MIA',
                        'team_abbr': 'BOS',
                        'opponent_team_abbr': 'MIA',
                        'predicted_points': 25.0,
                        'actual_points': None,  # No actual yet
                        'line_value': 24.5,
                        'recommendation': 'OVER',
                        'prediction_correct': None,
                        'confidence_score': 0.7,
                        'absolute_error': None,
                        'signed_error': None,
                        'edge': 0.5,
                        'player_historical_accuracy': 0.7,
                        'player_sample_size': 15,
                        'fatigue_score': 85,
                        'edge_factor': 1.05,
                        'hist_factor': 0.7,
                        'composite_score': 0.75
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')
                assert result['picks'][0]['result'] == 'PENDING'


class TestFatigueLevel:
    """Test suite for fatigue level classification"""

    def test_fatigue_level_fresh(self):
        """Test fatigue_level = 'fresh' for score >= 95"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_full_name': 'Player One',
                        'game_id': '20241215_BOS_MIA',
                        'team_abbr': 'BOS',
                        'opponent_team_abbr': 'MIA',
                        'predicted_points': 25.0,
                        'actual_points': None,
                        'line_value': 24.5,
                        'recommendation': 'OVER',
                        'prediction_correct': None,
                        'confidence_score': 0.7,
                        'absolute_error': None,
                        'signed_error': None,
                        'edge': 0.5,
                        'player_historical_accuracy': 0.7,
                        'player_sample_size': 15,
                        'fatigue_score': 98,  # Fresh
                        'edge_factor': 1.05,
                        'hist_factor': 0.7,
                        'composite_score': 0.75
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')
                assert result['picks'][0]['fatigue_level'] == 'fresh'

    def test_fatigue_level_normal(self):
        """Test fatigue_level = 'normal' for score 75-94"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_full_name': 'Player One',
                        'game_id': '20241215_BOS_MIA',
                        'team_abbr': 'BOS',
                        'opponent_team_abbr': 'MIA',
                        'predicted_points': 25.0,
                        'actual_points': None,
                        'line_value': 24.5,
                        'recommendation': 'OVER',
                        'prediction_correct': None,
                        'confidence_score': 0.7,
                        'absolute_error': None,
                        'signed_error': None,
                        'edge': 0.5,
                        'player_historical_accuracy': 0.7,
                        'player_sample_size': 15,
                        'fatigue_score': 85,  # Normal
                        'edge_factor': 1.05,
                        'hist_factor': 0.7,
                        'composite_score': 0.75
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')
                assert result['picks'][0]['fatigue_level'] == 'normal'

    def test_fatigue_level_tired(self):
        """Test fatigue_level = 'tired' for score < 75"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_full_name': 'Player One',
                        'game_id': '20241215_BOS_MIA',
                        'team_abbr': 'BOS',
                        'opponent_team_abbr': 'MIA',
                        'predicted_points': 25.0,
                        'actual_points': None,
                        'line_value': 24.5,
                        'recommendation': 'OVER',
                        'prediction_correct': None,
                        'confidence_score': 0.7,
                        'absolute_error': None,
                        'signed_error': None,
                        'edge': 0.5,
                        'player_historical_accuracy': 0.7,
                        'player_sample_size': 15,
                        'fatigue_score': 65,  # Tired
                        'edge_factor': 1.05,
                        'hist_factor': 0.7,
                        'composite_score': 0.75
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')
                assert result['picks'][0]['fatigue_level'] == 'tired'


class TestBuildRationale:
    """Test suite for rationale building"""

    def test_rationale_high_confidence(self):
        """Test rationale includes high confidence message"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()

                pick = {
                    'confidence_score': 0.85,
                    'edge': 2.0,
                    'player_historical_accuracy': 0.65,
                    'player_sample_size': 10,
                    'fatigue_score': 85
                }
                rationale = exporter._build_rationale(pick)

                assert any('High confidence' in r for r in rationale)

    def test_rationale_strong_edge(self):
        """Test rationale includes strong edge message"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()

                pick = {
                    'confidence_score': 0.65,
                    'edge': 5.0,  # Strong edge
                    'player_historical_accuracy': 0.65,
                    'player_sample_size': 10,
                    'fatigue_score': 85
                }
                rationale = exporter._build_rationale(pick)

                assert any('Strong edge' in r for r in rationale)

    def test_rationale_strong_track_record(self):
        """Test rationale includes strong track record"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()

                pick = {
                    'confidence_score': 0.65,
                    'edge': 2.0,
                    'player_historical_accuracy': 0.85,  # Strong accuracy
                    'player_sample_size': 20,
                    'fatigue_score': 85
                }
                rationale = exporter._build_rationale(pick)

                assert any('Strong track record' in r for r in rationale)

    def test_rationale_well_rested(self):
        """Test rationale includes well-rested message"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()

                pick = {
                    'confidence_score': 0.65,
                    'edge': 2.0,
                    'player_historical_accuracy': 0.65,
                    'player_sample_size': 10,
                    'fatigue_score': 98  # Well-rested
                }
                rationale = exporter._build_rationale(pick)

                assert any('Well-rested' in r for r in rationale)

    def test_rationale_default(self):
        """Test default rationale when no criteria met"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()

                pick = {
                    'confidence_score': 0.55,  # Not high
                    'edge': 1.0,  # Not strong
                    'player_historical_accuracy': 0.55,  # Not strong
                    'player_sample_size': 3,  # Too few
                    'fatigue_score': 85  # Not well-rested
                }
                rationale = exporter._build_rationale(pick)

                assert 'Meets minimum criteria' in rationale


class TestSafeFloat:
    """Test suite for _safe_float utility method"""

    def test_safe_float_valid(self):
        """Test valid float conversion"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()

                assert exporter._safe_float(25.5678) == 25.568
                assert exporter._safe_float(10) == 10.0

    def test_safe_float_none(self):
        """Test None handling"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()

                assert exporter._safe_float(None) is None

    def test_safe_float_nan(self):
        """Test NaN handling"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()

                assert exporter._safe_float(float('nan')) is None


class TestEmptyResponse:
    """Test suite for empty response structure"""

    def test_empty_response_structure(self):
        """Test that empty response has correct structure"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()
                response = exporter._empty_response('2024-12-15')

                assert response['game_date'] == '2024-12-15'
                assert response['total_picks'] == 0
                assert response['picks'] == []
                assert 'methodology' in response
                assert 'generated_at' in response


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

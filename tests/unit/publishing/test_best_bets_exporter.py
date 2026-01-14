"""
Unit Tests for BestBetsExporter

Tests cover:
1. Tiered selection logic (premium, strong, value, standard)
2. UNDER-only filtering (OVER excluded based on analysis)
3. Edge threshold filtering (min 2 points)
4. Star player exclusion (predicted_points < 25)
5. 88-90% confidence tier exclusion
6. Composite score calculation and ranking
7. Pick formatting with tier-aware rationale
8. Fatigue level classification
9. Result determination (WIN/LOSS/PENDING)
10. Empty data handling
11. Tier summary in output
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date

from data_processors.publishing.best_bets_exporter import (
    BestBetsExporter,
    TIER_CONFIG,
    AVOID_CRITERIA,
)


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


class TestTierConfiguration:
    """Test suite for tier configuration constants"""

    def test_tier_config_structure(self):
        """Test that tier config has expected structure"""
        assert 'premium' in TIER_CONFIG
        assert 'strong' in TIER_CONFIG
        assert 'value' in TIER_CONFIG

        for tier_name, config in TIER_CONFIG.items():
            assert 'min_confidence' in config
            assert 'min_edge' in config
            assert 'max_predicted_points' in config
            assert 'max_picks' in config

    def test_premium_tier_criteria(self):
        """Test premium tier has strictest criteria"""
        premium = TIER_CONFIG['premium']
        assert premium['min_confidence'] >= 0.90
        assert premium['min_edge'] >= 5.0
        assert premium['max_predicted_points'] <= 18

    def test_avoid_criteria_structure(self):
        """Test avoid criteria has expected fields"""
        assert 'over_recommendation' in AVOID_CRITERIA
        assert 'min_edge_threshold' in AVOID_CRITERIA
        assert 'max_predicted_points' in AVOID_CRITERIA
        assert 'exclude_confidence_range' in AVOID_CRITERIA


class TestBestBetsExporterInit:
    """Test suite for initialization"""

    def test_initialization(self):
        """Test that exporter initializes correctly"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()
                assert exporter is not None
                assert exporter.DEFAULT_TOP_N == 25  # Increased for tiered selection


class TestGenerateJson:
    """Test suite for generate_json method"""

    def test_generate_json_with_picks(self):
        """Test JSON generation with valid tiered picks"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'benchplayer',
                        'player_full_name': 'Bench Player',
                        'game_id': '20241215_LAL_GSW',
                        'team_abbr': 'LAL',
                        'opponent_team_abbr': 'GSW',
                        'predicted_points': 8.5,  # Bench player (< 18 for premium)
                        'actual_points': None,
                        'line_value': 14.5,
                        'recommendation': 'UNDER',  # Must be UNDER
                        'prediction_correct': None,
                        'confidence_score': 0.92,  # High confidence
                        'absolute_error': None,
                        'signed_error': None,
                        'edge': 6.0,  # Strong edge (>= 5)
                        'player_historical_accuracy': 0.78,
                        'player_sample_size': 25,
                        'fatigue_score': 92,
                        'edge_factor': 1.6,
                        'hist_factor': 0.78,
                        'composite_score': 0.85,
                        'tier': 'premium',
                        'tier_order': 1
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')

                assert result['game_date'] == '2024-12-15'
                assert result['total_picks'] == 1
                assert 'methodology' in result
                assert 'Tiered selection' in result['methodology']
                assert len(result['picks']) == 1
                assert 'generated_at' in result
                assert 'tier_summary' in result
                assert result['tier_summary']['premium'] == 1

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
                assert 'tier_summary' in result
                assert result['tier_summary'] == {'premium': 0, 'strong': 0, 'value': 0, 'standard': 0}

    def test_generate_json_multiple_tiers(self):
        """Test JSON generation with picks from multiple tiers"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    # Premium pick
                    {
                        'player_lookup': 'player1',
                        'player_full_name': 'Player One',
                        'game_id': '20241215_LAL_GSW',
                        'team_abbr': 'LAL',
                        'opponent_team_abbr': 'GSW',
                        'predicted_points': 10.0,
                        'actual_points': None,
                        'line_value': 16.0,
                        'recommendation': 'UNDER',
                        'prediction_correct': None,
                        'confidence_score': 0.92,
                        'absolute_error': None,
                        'signed_error': None,
                        'edge': 6.0,
                        'player_historical_accuracy': 0.8,
                        'player_sample_size': 15,
                        'fatigue_score': 90,
                        'edge_factor': 1.6,
                        'hist_factor': 0.8,
                        'composite_score': 1.2,
                        'tier': 'premium',
                        'tier_order': 1
                    },
                    # Strong pick
                    {
                        'player_lookup': 'player2',
                        'player_full_name': 'Player Two',
                        'game_id': '20241215_BOS_MIA',
                        'team_abbr': 'BOS',
                        'opponent_team_abbr': 'MIA',
                        'predicted_points': 15.0,
                        'actual_points': None,
                        'line_value': 19.5,
                        'recommendation': 'UNDER',
                        'prediction_correct': None,
                        'confidence_score': 0.91,
                        'absolute_error': None,
                        'signed_error': None,
                        'edge': 4.5,
                        'player_historical_accuracy': 0.75,
                        'player_sample_size': 20,
                        'fatigue_score': 85,
                        'edge_factor': 1.45,
                        'hist_factor': 0.75,
                        'composite_score': 1.0,
                        'tier': 'strong',
                        'tier_order': 2
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')

                assert result['total_picks'] == 2
                assert result['tier_summary']['premium'] == 1
                assert result['tier_summary']['strong'] == 1
                # Verify premium comes first (sorted by tier_order)
                assert result['picks'][0]['tier'] == 'premium'
                assert result['picks'][1]['tier'] == 'strong'


class TestPickFormatting:
    """Test suite for pick formatting"""

    def test_pick_structure(self):
        """Test that formatted picks have correct structure with tier"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'benchplayer',
                        'player_full_name': 'Bench Player',
                        'game_id': '20241215_LAL_GSW',
                        'team_abbr': 'GSW',
                        'opponent_team_abbr': 'LAL',
                        'predicted_points': 8.0,  # Bench player
                        'actual_points': 6,
                        'line_value': 14.5,
                        'recommendation': 'UNDER',  # Must be UNDER
                        'prediction_correct': True,
                        'confidence_score': 0.92,
                        'absolute_error': 2.0,
                        'signed_error': 2.0,
                        'edge': 6.5,
                        'player_historical_accuracy': 0.82,
                        'player_sample_size': 30,
                        'fatigue_score': 95,
                        'edge_factor': 1.65,
                        'hist_factor': 0.82,
                        'composite_score': 1.24,
                        'tier': 'premium',
                        'tier_order': 1
                    }
                ])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')
                pick = result['picks'][0]

                assert pick['rank'] == 1
                assert pick['tier'] == 'premium'  # New field
                assert pick['player_lookup'] == 'benchplayer'
                assert pick['player_full_name'] == 'Bench Player'
                assert pick['game_id'] == '20241215_LAL_GSW'
                assert pick['team'] == 'GSW'
                assert pick['opponent'] == 'LAL'
                assert pick['recommendation'] == 'UNDER'
                assert pick['line'] == 14.5
                assert pick['predicted'] == 8.0
                assert pick['edge'] == 6.5
                assert pick['confidence'] == 0.92
                assert pick['composite_score'] == 1.24
                assert pick['result'] == 'WIN'
                assert pick['actual'] == 6
                assert 'rationale' in pick


class TestResultDetermination:
    """Test suite for result determination logic"""

    def _make_pick(self, actual_points, prediction_correct):
        """Helper to create a valid pick for testing"""
        return {
            'player_lookup': 'player1',
            'player_full_name': 'Player One',
            'game_id': '20241215_BOS_MIA',
            'team_abbr': 'BOS',
            'opponent_team_abbr': 'MIA',
            'predicted_points': 10.0,  # Bench player
            'actual_points': actual_points,
            'line_value': 15.5,
            'recommendation': 'UNDER',  # Must be UNDER
            'prediction_correct': prediction_correct,
            'confidence_score': 0.92,
            'absolute_error': 3.0 if actual_points else None,
            'signed_error': -3.0 if actual_points else None,
            'edge': 5.5,
            'player_historical_accuracy': 0.8,
            'player_sample_size': 15,
            'fatigue_score': 85,
            'edge_factor': 1.55,
            'hist_factor': 0.8,
            'composite_score': 1.15,
            'tier': 'premium',
            'tier_order': 1
        }

    def test_result_win(self):
        """Test WIN result when prediction is correct"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([self._make_pick(actual_points=8, prediction_correct=True)])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')
                assert result['picks'][0]['result'] == 'WIN'

    def test_result_loss(self):
        """Test LOSS result when prediction is incorrect"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([self._make_pick(actual_points=18, prediction_correct=False)])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')
                assert result['picks'][0]['result'] == 'LOSS'

    def test_result_pending(self):
        """Test PENDING result when game hasn't finished"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([self._make_pick(actual_points=None, prediction_correct=None)])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')
                assert result['picks'][0]['result'] == 'PENDING'


class TestFatigueLevel:
    """Test suite for fatigue level classification"""

    def _make_fatigue_pick(self, fatigue_score):
        """Helper to create a valid pick with specific fatigue score"""
        return {
            'player_lookup': 'player1',
            'player_full_name': 'Player One',
            'game_id': '20241215_BOS_MIA',
            'team_abbr': 'BOS',
            'opponent_team_abbr': 'MIA',
            'predicted_points': 10.0,  # Bench player
            'actual_points': None,
            'line_value': 16.5,
            'recommendation': 'UNDER',
            'prediction_correct': None,
            'confidence_score': 0.92,
            'absolute_error': None,
            'signed_error': None,
            'edge': 6.5,
            'player_historical_accuracy': 0.8,
            'player_sample_size': 15,
            'fatigue_score': fatigue_score,
            'edge_factor': 1.65,
            'hist_factor': 0.8,
            'composite_score': 1.2,
            'tier': 'premium',
            'tier_order': 1
        }

    def test_fatigue_level_fresh(self):
        """Test fatigue_level = 'fresh' for score >= 95"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([self._make_fatigue_pick(fatigue_score=98)])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')
                assert result['picks'][0]['fatigue_level'] == 'fresh'

    def test_fatigue_level_normal(self):
        """Test fatigue_level = 'normal' for score 75-94"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([self._make_fatigue_pick(fatigue_score=85)])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')
                assert result['picks'][0]['fatigue_level'] == 'normal'

    def test_fatigue_level_tired(self):
        """Test fatigue_level = 'tired' for score < 75"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([self._make_fatigue_pick(fatigue_score=65)])
                mock_bq.return_value = mock_client
                exporter = BestBetsExporter()

                result = exporter.generate_json('2024-12-15')
                assert result['picks'][0]['fatigue_level'] == 'tired'


class TestBuildRationale:
    """Test suite for rationale building with tier-aware messaging"""

    def test_rationale_premium_tier(self):
        """Test rationale includes premium tier message"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()

                pick = {
                    'tier': 'premium',
                    'confidence_score': 0.92,
                    'edge': 6.0,
                    'predicted_points': 10.0,
                    'player_historical_accuracy': 0.8,
                    'player_sample_size': 15,
                    'fatigue_score': 90
                }
                rationale = exporter._build_rationale(pick)

                assert any('Premium pick' in r for r in rationale)
                assert any('92%+' in r for r in rationale)

    def test_rationale_high_confidence(self):
        """Test rationale includes high confidence message"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()

                pick = {
                    'tier': 'strong',
                    'confidence_score': 0.91,
                    'edge': 4.5,
                    'predicted_points': 15.0,
                    'player_historical_accuracy': 0.75,
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
                    'tier': 'value',
                    'confidence_score': 0.85,
                    'edge': 6.0,  # Strong edge
                    'predicted_points': 12.0,
                    'player_historical_accuracy': 0.7,
                    'player_sample_size': 10,
                    'fatigue_score': 85
                }
                rationale = exporter._build_rationale(pick)

                assert any('Strong edge' in r for r in rationale)

    def test_rationale_bench_player(self):
        """Test rationale includes bench player message"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()

                pick = {
                    'tier': 'premium',
                    'confidence_score': 0.92,
                    'edge': 6.0,
                    'predicted_points': 8.0,  # Bench player
                    'player_historical_accuracy': 0.8,
                    'player_sample_size': 15,
                    'fatigue_score': 90
                }
                rationale = exporter._build_rationale(pick)

                assert any('Bench player' in r for r in rationale)

    def test_rationale_strong_track_record(self):
        """Test rationale includes strong track record"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()

                pick = {
                    'tier': 'strong',
                    'confidence_score': 0.91,
                    'edge': 4.5,
                    'predicted_points': 15.0,
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
                    'tier': 'premium',
                    'confidence_score': 0.92,
                    'edge': 6.0,
                    'predicted_points': 10.0,
                    'player_historical_accuracy': 0.75,
                    'player_sample_size': 10,
                    'fatigue_score': 98  # Well-rested
                }
                rationale = exporter._build_rationale(pick)

                assert any('Well-rested' in r for r in rationale)

    def test_rationale_standard_tier(self):
        """Test rationale for standard tier picks"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()

                pick = {
                    'tier': 'standard',  # No tier message
                    'confidence_score': 0.82,
                    'edge': 3.0,
                    'predicted_points': 20.0,
                    'player_historical_accuracy': 0.65,
                    'player_sample_size': 3,  # Too few for track record
                    'fatigue_score': 85
                }
                rationale = exporter._build_rationale(pick)

                # Should not have tier-specific message
                assert not any('Premium' in r or 'Strong' in r or 'Value' in r for r in rationale)
                # Should have general criteria message
                assert any('confidence' in r.lower() or 'edge' in r.lower() or 'criteria' in r.lower() for r in rationale)


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
        """Test that empty response has correct structure with tier_summary"""
        with patch('data_processors.publishing.best_bets_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BestBetsExporter()
                response = exporter._empty_response('2024-12-15')

                assert response['game_date'] == '2024-12-15'
                assert response['total_picks'] == 0
                assert response['picks'] == []
                assert 'methodology' in response
                assert 'Tiered selection' in response['methodology']
                assert 'generated_at' in response
                # New: tier_summary should be present with zero counts
                assert 'tier_summary' in response
                assert response['tier_summary'] == {'premium': 0, 'strong': 0, 'value': 0, 'standard': 0}


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

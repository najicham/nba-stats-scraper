"""
Unit Tests for ResultsExporter

Tests cover:
1. Tier classification functions (confidence_tier, player_tier)
2. Breakdown computation
3. Format results with new fields
4. Empty data handling
"""

import pytest
from unittest.mock import Mock, patch

from data_processors.publishing.results_exporter import (
    ResultsExporter,
    get_confidence_tier,
    get_player_tier,
    CONFIDENCE_THRESHOLDS,
    PLAYER_TIER_THRESHOLDS,
)


class TestConfidenceTier:
    """Test suite for confidence tier classification"""

    def test_high_confidence(self):
        """Test high confidence tier (>= 0.70)"""
        assert get_confidence_tier(0.70) == 'high'
        assert get_confidence_tier(0.85) == 'high'
        assert get_confidence_tier(1.0) == 'high'

    def test_medium_confidence(self):
        """Test medium confidence tier (0.55 - 0.69)"""
        assert get_confidence_tier(0.55) == 'medium'
        assert get_confidence_tier(0.65) == 'medium'
        assert get_confidence_tier(0.69) == 'medium'

    def test_low_confidence(self):
        """Test low confidence tier (< 0.55)"""
        assert get_confidence_tier(0.54) == 'low'
        assert get_confidence_tier(0.40) == 'low'
        assert get_confidence_tier(0.0) == 'low'

    def test_none_confidence(self):
        """Test None confidence defaults to low"""
        assert get_confidence_tier(None) == 'low'

    def test_boundary_values(self):
        """Test exact boundary values"""
        # High boundary
        assert get_confidence_tier(CONFIDENCE_THRESHOLDS['high']) == 'high'
        assert get_confidence_tier(CONFIDENCE_THRESHOLDS['high'] - 0.01) == 'medium'

        # Medium boundary
        assert get_confidence_tier(CONFIDENCE_THRESHOLDS['medium']) == 'medium'
        assert get_confidence_tier(CONFIDENCE_THRESHOLDS['medium'] - 0.01) == 'low'


class TestPlayerTier:
    """Test suite for player tier classification"""

    def test_elite_tier(self):
        """Test elite tier (>= 25 PPG)"""
        assert get_player_tier(25.0) == 'elite'
        assert get_player_tier(30.5) == 'elite'
        assert get_player_tier(35.0) == 'elite'

    def test_starter_tier(self):
        """Test starter tier (15 - 24.9 PPG)"""
        assert get_player_tier(15.0) == 'starter'
        assert get_player_tier(20.0) == 'starter'
        assert get_player_tier(24.9) == 'starter'

    def test_role_player_tier(self):
        """Test role player tier (< 15 PPG)"""
        assert get_player_tier(14.9) == 'role_player'
        assert get_player_tier(10.0) == 'role_player'
        assert get_player_tier(0.0) == 'role_player'

    def test_none_ppg(self):
        """Test None PPG defaults to role_player"""
        assert get_player_tier(None) == 'role_player'

    def test_boundary_values(self):
        """Test exact boundary values"""
        # Elite boundary
        assert get_player_tier(PLAYER_TIER_THRESHOLDS['elite']) == 'elite'
        assert get_player_tier(PLAYER_TIER_THRESHOLDS['elite'] - 0.1) == 'starter'

        # Starter boundary
        assert get_player_tier(PLAYER_TIER_THRESHOLDS['starter']) == 'starter'
        assert get_player_tier(PLAYER_TIER_THRESHOLDS['starter'] - 0.1) == 'role_player'


class TestBreakdownComputation:
    """Test suite for breakdown computation"""

    @pytest.fixture
    def sample_formatted_results(self):
        """Sample formatted results for breakdown testing"""
        return [
            # Elite, High confidence, OVER, Home, WIN
            {
                'player_lookup': 'curry',
                'recommendation': 'OVER',
                'result': 'WIN',
                'error': 3.5,
                'player_tier': 'elite',
                'confidence_tier': 'high',
                'is_home': True,
                'is_back_to_back': False,
                'days_rest': 3,
            },
            # Starter, High confidence, UNDER, Away, WIN
            {
                'player_lookup': 'tatum',
                'recommendation': 'UNDER',
                'result': 'WIN',
                'error': 2.0,
                'player_tier': 'starter',
                'confidence_tier': 'high',
                'is_home': False,
                'is_back_to_back': False,
                'days_rest': 2,
            },
            # Role player, Medium confidence, UNDER, Away, LOSS
            {
                'player_lookup': 'bench_player',
                'recommendation': 'UNDER',
                'result': 'LOSS',
                'error': 8.0,
                'player_tier': 'role_player',
                'confidence_tier': 'medium',
                'is_home': False,
                'is_back_to_back': True,
                'days_rest': 0,
            },
            # Role player, Low confidence, PASS (should be excluded from breakdowns)
            {
                'player_lookup': 'another_player',
                'recommendation': 'PASS',
                'result': 'PASS',
                'error': None,
                'player_tier': 'role_player',
                'confidence_tier': 'low',
                'is_home': True,
                'is_back_to_back': False,
                'days_rest': 1,
            },
        ]

    def test_breakdown_by_player_tier(self, sample_formatted_results):
        """Test breakdown by player tier"""
        with patch('data_processors.publishing.results_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = ResultsExporter()
                breakdowns = exporter._compute_breakdowns(sample_formatted_results)

                # Elite: 1 win, 0 losses
                assert breakdowns['by_player_tier']['elite']['total'] == 1
                assert breakdowns['by_player_tier']['elite']['wins'] == 1
                assert breakdowns['by_player_tier']['elite']['win_rate'] == 1.0

                # Starter: 1 win, 0 losses
                assert breakdowns['by_player_tier']['starter']['total'] == 1
                assert breakdowns['by_player_tier']['starter']['wins'] == 1

                # Role player: 0 wins, 1 loss (PASS excluded)
                assert breakdowns['by_player_tier']['role_player']['total'] == 1
                assert breakdowns['by_player_tier']['role_player']['losses'] == 1

    def test_breakdown_by_confidence(self, sample_formatted_results):
        """Test breakdown by confidence tier"""
        with patch('data_processors.publishing.results_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = ResultsExporter()
                breakdowns = exporter._compute_breakdowns(sample_formatted_results)

                # High: 2 wins
                assert breakdowns['by_confidence']['high']['total'] == 2
                assert breakdowns['by_confidence']['high']['wins'] == 2
                assert breakdowns['by_confidence']['high']['win_rate'] == 1.0

                # Medium: 1 loss
                assert breakdowns['by_confidence']['medium']['total'] == 1
                assert breakdowns['by_confidence']['medium']['losses'] == 1

                # Low: 0 (PASS excluded)
                assert breakdowns['by_confidence']['low']['total'] == 0

    def test_breakdown_by_recommendation(self, sample_formatted_results):
        """Test breakdown by recommendation"""
        with patch('data_processors.publishing.results_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = ResultsExporter()
                breakdowns = exporter._compute_breakdowns(sample_formatted_results)

                # OVER: 1 win
                assert breakdowns['by_recommendation']['over']['total'] == 1
                assert breakdowns['by_recommendation']['over']['wins'] == 1

                # UNDER: 1 win, 1 loss
                assert breakdowns['by_recommendation']['under']['total'] == 2
                assert breakdowns['by_recommendation']['under']['wins'] == 1
                assert breakdowns['by_recommendation']['under']['losses'] == 1

    def test_breakdown_by_context(self, sample_formatted_results):
        """Test breakdown by context"""
        with patch('data_processors.publishing.results_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = ResultsExporter()
                breakdowns = exporter._compute_breakdowns(sample_formatted_results)

                # Home: 1 (curry is home, PASS excluded)
                assert breakdowns['by_context']['home']['total'] == 1
                assert breakdowns['by_context']['home']['wins'] == 1

                # Away: 2
                assert breakdowns['by_context']['away']['total'] == 2

                # Back-to-back: 1
                assert breakdowns['by_context']['back_to_back']['total'] == 1
                assert breakdowns['by_context']['back_to_back']['losses'] == 1

                # Rested (days_rest >= 2): 2 (curry + tatum)
                assert breakdowns['by_context']['rested']['total'] == 2
                assert breakdowns['by_context']['rested']['wins'] == 2

    def test_empty_results_breakdown(self):
        """Test breakdown with empty results"""
        with patch('data_processors.publishing.results_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = ResultsExporter()
                breakdowns = exporter._compute_breakdowns([])

                # All categories should have zero totals
                assert breakdowns['by_player_tier']['elite']['total'] == 0
                assert breakdowns['by_confidence']['high']['total'] == 0
                assert breakdowns['by_recommendation']['over']['total'] == 0
                assert breakdowns['by_context']['home']['total'] == 0


class TestFormatResults:
    """Test suite for format results with new fields"""

    def test_format_includes_new_fields(self):
        """Test that formatted results include tier and context fields"""
        with patch('data_processors.publishing.results_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = ResultsExporter()

                raw_results = [{
                    'player_lookup': 'curry',
                    'game_id': '20240410_GSW_PHX',
                    'team_abbr': 'GSW',
                    'opponent_team_abbr': 'PHX',
                    'predicted_points': 28.5,
                    'actual_points': 31,
                    'line_value': 27.5,
                    'recommendation': 'OVER',
                    'prediction_correct': True,
                    'absolute_error': 2.5,
                    'signed_error': -2.5,
                    'confidence_score': 0.75,
                    'within_3_points': True,
                    'within_5_points': True,
                    'minutes_played': 36,
                    'is_home': True,
                    'days_rest': 3,
                    'is_back_to_back': False,
                    'points_avg_season': 28.0,
                }]

                formatted = exporter._format_results(raw_results)

                assert len(formatted) == 1
                result = formatted[0]

                # Check new tier fields
                assert result['confidence_tier'] == 'high'  # 0.75 >= 0.70
                assert result['player_tier'] == 'elite'  # 28.0 >= 25.0

                # Check context fields
                assert result['is_home'] is True
                assert result['is_back_to_back'] is False
                assert result['days_rest'] == 3


class TestEmptyResponse:
    """Test suite for empty response structure"""

    def test_empty_response_has_breakdowns(self):
        """Test that empty response includes breakdowns structure"""
        with patch('data_processors.publishing.results_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = ResultsExporter()
                response = exporter._empty_response('2024-12-15')

                assert 'breakdowns' in response
                assert 'by_player_tier' in response['breakdowns']
                assert 'by_confidence' in response['breakdowns']
                assert 'by_recommendation' in response['breakdowns']
                assert 'by_context' in response['breakdowns']

                # Check structure
                assert response['breakdowns']['by_player_tier']['elite']['total'] == 0
                assert response['breakdowns']['by_confidence']['high']['total'] == 0

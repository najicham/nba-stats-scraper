# tests/mlb/test_base_predictor.py
"""
Unit tests for BaseMLBPredictor

Tests shared logic for all prediction systems:
- Confidence calculation
- Red flag checking
- Recommendation generation
"""

import pytest
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from predictions.mlb.base_predictor import BaseMLBPredictor, RedFlagResult
from predictions.mlb.config import get_config, reset_config


class ConcretePredictor(BaseMLBPredictor):
    """Concrete implementation for testing abstract base class"""

    def predict(self, pitcher_lookup, features, strikeouts_line=None):
        return {
            'pitcher_lookup': pitcher_lookup,
            'predicted_strikeouts': 6.5,
            'confidence': 75.0,
            'recommendation': 'OVER',
            'system_id': self.system_id
        }


class TestBaseMLBPredictor:
    """Tests for BaseMLBPredictor abstract class"""

    def setup_method(self):
        """Setup for each test"""
        reset_config()
        self.predictor = ConcretePredictor(system_id='test_system')

    def teardown_method(self):
        """Cleanup after each test"""
        reset_config()

    # ========================================================================
    # Confidence Calculation Tests
    # ========================================================================

    def test_calculate_confidence_high_quality_data(self):
        """Test confidence with high quality data"""
        features = {
            'data_completeness_score': 95,
            'rolling_stats_games': 12,
            'k_std_last_10': 1.5
        }

        confidence = self.predictor._calculate_confidence(features)

        # Base (70) + completeness (15) + rolling_games (10) + consistency (5) = 100
        assert confidence == 100

    def test_calculate_confidence_medium_quality_data(self):
        """Test confidence with medium quality data"""
        features = {
            'data_completeness_score': 75,
            'rolling_stats_games': 5,
            'k_std_last_10': 2.5
        }

        confidence = self.predictor._calculate_confidence(features)

        # Base (70) + completeness (5) + rolling_games (5) + consistency (2) = 82
        assert confidence == 82

    def test_calculate_confidence_low_quality_data(self):
        """Test confidence with low quality data"""
        features = {
            'data_completeness_score': 45,
            'rolling_stats_games': 2,
            'k_std_last_10': 5.0
        }

        confidence = self.predictor._calculate_confidence(features)

        # Base (70) + completeness (-10) + rolling_games (-10) + consistency (-5) = 45
        assert confidence == 45

    def test_calculate_confidence_clamped_to_100(self):
        """Test confidence is clamped to max 100"""
        features = {
            'data_completeness_score': 100,
            'rolling_stats_games': 20,
            'k_std_last_10': 0.5
        }

        confidence = self.predictor._calculate_confidence(features)
        assert confidence == 100  # Should be clamped

    def test_calculate_confidence_clamped_to_0(self):
        """Test confidence is clamped to min 0"""
        features = {
            'data_completeness_score': 20,
            'rolling_stats_games': 0,
            'k_std_last_10': 10.0
        }

        confidence = self.predictor._calculate_confidence(features)
        assert confidence >= 0  # Should be clamped

    # ========================================================================
    # Recommendation Generation Tests
    # ========================================================================

    def test_generate_recommendation_over(self):
        """Test OVER recommendation when edge >= threshold"""
        config = get_config()

        recommendation = self.predictor._generate_recommendation(
            predicted_strikeouts=7.0,
            strikeouts_line=6.5,
            confidence=70.0
        )

        assert recommendation == 'OVER'

    def test_generate_recommendation_under(self):
        """Test UNDER recommendation when edge <= -threshold"""
        recommendation = self.predictor._generate_recommendation(
            predicted_strikeouts=6.0,
            strikeouts_line=6.5,
            confidence=70.0
        )

        assert recommendation == 'UNDER'

    def test_generate_recommendation_pass_low_confidence(self):
        """Test PASS when confidence below threshold"""
        recommendation = self.predictor._generate_recommendation(
            predicted_strikeouts=7.0,
            strikeouts_line=6.5,
            confidence=50.0  # Below min_confidence (60)
        )

        assert recommendation == 'PASS'

    def test_generate_recommendation_pass_small_edge(self):
        """Test PASS when edge too small"""
        recommendation = self.predictor._generate_recommendation(
            predicted_strikeouts=6.6,
            strikeouts_line=6.5,
            confidence=70.0  # Edge = 0.1, below min_edge (0.5)
        )

        assert recommendation == 'PASS'

    def test_generate_recommendation_no_line(self):
        """Test NO_LINE when line not provided"""
        recommendation = self.predictor._generate_recommendation(
            predicted_strikeouts=7.0,
            strikeouts_line=None,
            confidence=70.0
        )

        assert recommendation == 'NO_LINE'

    # ========================================================================
    # Red Flag Tests
    # ========================================================================

    @patch.object(BaseMLBPredictor, '_get_current_il_pitchers')
    def test_red_flag_pitcher_on_il(self, mock_il_pitchers):
        """Test hard skip for pitcher on IL"""
        mock_il_pitchers.return_value = {'gerrittcole'}

        features = {
            'player_lookup': 'gerrit_cole',
            'season_games_started': 5,
            'ip_avg_last_5': 6.0,
            'rolling_stats_games': 10
        }

        result = self.predictor._check_red_flags(features)

        assert result.skip_bet is True
        assert 'IL' in result.skip_reason
        assert len(result.flags) > 0

    def test_red_flag_first_start(self):
        """Test hard skip for first start of season"""
        features = {
            'player_lookup': 'gerrit-cole',
            'is_first_start': True,
            'season_games_started': 0,
            'ip_avg_last_5': 6.0,
            'rolling_stats_games': 10
        }

        result = self.predictor._check_red_flags(features)

        assert result.skip_bet is True
        assert 'first start' in result.skip_reason.lower()

    def test_red_flag_low_ip_avg(self):
        """Test hard skip for low IP average (bullpen/opener)"""
        features = {
            'player_lookup': 'gerrit-cole',
            'season_games_started': 5,
            'ip_avg_last_5': 3.5,  # Below min_ip_avg (4.0)
            'rolling_stats_games': 10
        }

        result = self.predictor._check_red_flags(features)

        assert result.skip_bet is True
        assert 'IP' in result.skip_reason or 'bullpen' in result.skip_reason.lower()

    def test_red_flag_mlb_debut(self):
        """Test hard skip for MLB debut (very few career starts)"""
        features = {
            'player_lookup': 'gerrit-cole',
            'season_games_started': 5,
            'ip_avg_last_5': 6.0,
            'rolling_stats_games': 1  # Below min_career_starts (2)
        }

        result = self.predictor._check_red_flags(features)

        assert result.skip_bet is True
        assert 'career starts' in result.skip_reason.lower()

    def test_red_flag_high_variance_over(self):
        """Test confidence reduction for high variance on OVER bet"""
        features = {
            'player_lookup': 'gerrit-cole',
            'season_games_started': 10,
            'ip_avg_last_5': 6.0,
            'rolling_stats_games': 10,
            'k_std_last_10': 4.5  # High variance
        }

        result = self.predictor._check_red_flags(features, recommendation='OVER')

        assert result.skip_bet is False
        assert result.confidence_multiplier < 1.0
        assert any('variance' in flag.lower() for flag in result.flags)

    def test_red_flag_high_variance_under(self):
        """Test confidence boost for high variance on UNDER bet"""
        features = {
            'player_lookup': 'gerrit-cole',
            'season_games_started': 10,
            'ip_avg_last_5': 6.0,
            'rolling_stats_games': 10,
            'k_std_last_10': 4.5  # High variance
        }

        result = self.predictor._check_red_flags(features, recommendation='UNDER')

        assert result.skip_bet is False
        assert result.confidence_multiplier > 1.0  # Boost for UNDER
        assert any('variance' in flag.lower() for flag in result.flags)

    def test_red_flag_short_rest_over(self):
        """Test confidence reduction for short rest on OVER bet"""
        features = {
            'player_lookup': 'gerrit-cole',
            'season_games_started': 10,
            'ip_avg_last_5': 6.0,
            'rolling_stats_games': 10,
            'days_rest': 3  # Short rest
        }

        result = self.predictor._check_red_flags(features, recommendation='OVER')

        assert result.skip_bet is False
        assert result.confidence_multiplier < 1.0
        assert any('rest' in flag.lower() for flag in result.flags)

    def test_red_flag_elite_swstr_over(self):
        """Test confidence boost for elite SwStr% on OVER bet"""
        features = {
            'player_lookup': 'gerrit-cole',
            'season_games_started': 10,
            'ip_avg_last_5': 6.0,
            'rolling_stats_games': 10,
            'season_swstr_pct': 0.13  # Elite
        }

        result = self.predictor._check_red_flags(features, recommendation='OVER')

        assert result.skip_bet is False
        assert result.confidence_multiplier > 1.0
        assert any('SwStr%' in flag for flag in result.flags)

    def test_red_flag_no_flags(self):
        """Test no red flags for normal pitcher"""
        features = {
            'player_lookup': 'gerrit-cole',
            'season_games_started': 10,
            'ip_avg_last_5': 6.0,
            'rolling_stats_games': 10,
            'k_std_last_10': 2.5,
            'days_rest': 5,
            'games_last_30_days': 5,
            'season_swstr_pct': 0.10
        }

        result = self.predictor._check_red_flags(features, recommendation='OVER')

        assert result.skip_bet is False
        assert result.confidence_multiplier == 1.0
        assert len(result.flags) == 0

    # ========================================================================
    # IL Cache Tests
    # ========================================================================

    @patch.object(BaseMLBPredictor, '_get_bq_client')
    def test_il_cache_hit(self, mock_bq_client):
        """Test IL cache returns cached data within TTL"""
        # Set up cache
        BaseMLBPredictor._il_cache = {'test-pitcher'}
        BaseMLBPredictor._il_cache_timestamp = datetime.now()

        # Call should use cache, not query BQ
        result = self.predictor._get_current_il_pitchers()

        assert result == {'test-pitcher'}
        mock_bq_client.assert_not_called()

    @patch.object(BaseMLBPredictor, '_get_bq_client')
    def test_il_cache_expired(self, mock_bq_client):
        """Test IL cache refreshes after TTL expires"""
        # Set up expired cache
        BaseMLBPredictor._il_cache = {'old-pitcher'}
        BaseMLBPredictor._il_cache_timestamp = datetime.now() - timedelta(hours=7)  # Expired (TTL=6h)

        # Mock BigQuery result
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = Mock(return_value=iter([
            MagicMock(player_lookup='new-pitcher')
        ]))
        mock_client.query.return_value.result.return_value = mock_result
        mock_bq_client.return_value = mock_client

        # Call should refresh cache
        result = self.predictor._get_current_il_pitchers()

        assert result == {'new-pitcher'}
        mock_bq_client.assert_called_once()

    # ========================================================================
    # Abstract Method Test
    # ========================================================================

    def test_predict_is_abstract(self):
        """Test that predict() must be implemented by subclasses"""
        with pytest.raises(TypeError):
            # Should not be able to instantiate BaseMLBPredictor directly
            BaseMLBPredictor(system_id='test')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

# tests/mlb/prediction_systems/test_ensemble_v1.py
"""
Unit tests for MLBEnsembleV1

Tests ensemble prediction logic:
- Weighted averaging (V1 30% + V1.6 50%)
- Agreement bonus/penalty
- Fallback when one system fails
- Skip handling
"""

import pytest
from unittest.mock import Mock, MagicMock

from predictions.mlb.prediction_systems.ensemble_v1 import MLBEnsembleV1
from predictions.mlb.base_predictor import BaseMLBPredictor


class TestMLBEnsembleV1:
    """Tests for MLBEnsembleV1 predictor"""

    def setup_method(self):
        """Setup for each test"""
        # Create mock predictors
        self.mock_v1 = Mock(spec=BaseMLBPredictor)
        self.mock_v1.system_id = 'v1_baseline'

        self.mock_v1_6 = Mock(spec=BaseMLBPredictor)
        self.mock_v1_6.system_id = 'v1_6_rolling'

        self.ensemble = MLBEnsembleV1(
            v1_predictor=self.mock_v1,
            v1_6_predictor=self.mock_v1_6,
            v1_weight=0.3,
            v1_6_weight=0.5
        )

    # ========================================================================
    # Weighted Averaging Tests
    # ========================================================================

    def test_weighted_average_basic(self):
        """Test basic weighted averaging of predictions"""
        # V1 predicts 6.0, V1.6 predicts 7.0
        # Weighted: (6.0 * 0.3) + (7.0 * 0.5) = 1.8 + 3.5 = 5.3
        self.mock_v1.predict.return_value = {
            'predicted_strikeouts': 6.0,
            'confidence': 70,
            'recommendation': 'OVER'
        }
        self.mock_v1_6.predict.return_value = {
            'predicted_strikeouts': 7.0,
            'confidence': 80,
            'recommendation': 'OVER'
        }

        result = self.ensemble.predict(
            pitcher_lookup='gerrit-cole',
            features={'season_games_started': 10, 'ip_avg_last_5': 6.0, 'rolling_stats_games': 10},
            strikeouts_line=6.5
        )

        assert result['predicted_strikeouts'] == 5.3
        assert result['system_id'] == 'ensemble_v1'
        assert 'component_predictions' in result
        assert result['component_predictions']['v1_baseline'] == 6.0
        assert result['component_predictions']['v1_6_rolling'] == 7.0

    def test_confidence_average(self):
        """Test ensemble averages component confidences"""
        self.mock_v1.predict.return_value = {
            'predicted_strikeouts': 6.0,
            'confidence': 70,
            'recommendation': 'OVER'
        }
        self.mock_v1_6.predict.return_value = {
            'predicted_strikeouts': 6.5,
            'confidence': 80,
            'recommendation': 'OVER'
        }

        result = self.ensemble.predict(
            pitcher_lookup='gerrit-cole',
            features={'season_games_started': 10, 'ip_avg_last_5': 6.0, 'rolling_stats_games': 10},
            strikeouts_line=6.0
        )

        # Base confidence = (70 + 80) / 2 = 75
        # With strong agreement (diff < 1.0), boost by 1.1
        expected_base_confidence = 75
        assert result['base_confidence'] == expected_base_confidence * 1.1

    # ========================================================================
    # Agreement Bonus/Penalty Tests
    # ========================================================================

    def test_strong_agreement_bonus(self):
        """Test confidence boost when systems strongly agree (< 1.0 K diff)"""
        self.mock_v1.predict.return_value = {
            'predicted_strikeouts': 6.0,
            'confidence': 70,
            'recommendation': 'OVER'
        }
        self.mock_v1_6.predict.return_value = {
            'predicted_strikeouts': 6.5,  # Diff = 0.5 < 1.0
            'confidence': 80,
            'recommendation': 'OVER'
        }

        result = self.ensemble.predict(
            pitcher_lookup='gerrit-cole',
            features={'season_games_started': 10, 'ip_avg_last_5': 6.0, 'rolling_stats_games': 10},
            strikeouts_line=6.0
        )

        assert 'Strong agreement' in result['agreement_note']
        # Confidence should be boosted
        assert result['base_confidence'] > 75  # (70+80)/2 = 75, boosted by 1.1 = 82.5

    def test_moderate_agreement_neutral(self):
        """Test no adjustment for moderate agreement (1.0-2.0 K diff)"""
        self.mock_v1.predict.return_value = {
            'predicted_strikeouts': 5.0,
            'confidence': 70,
            'recommendation': 'UNDER'
        }
        self.mock_v1_6.predict.return_value = {
            'predicted_strikeouts': 6.5,  # Diff = 1.5
            'confidence': 80,
            'recommendation': 'OVER'
        }

        result = self.ensemble.predict(
            pitcher_lookup='gerrit-cole',
            features={'season_games_started': 10, 'ip_avg_last_5': 6.0, 'rolling_stats_games': 10},
            strikeouts_line=6.0
        )

        assert 'Moderate agreement' in result['agreement_note']
        # Confidence should not be adjusted
        assert result['base_confidence'] == 75  # (70+80)/2, no multiplier

    def test_disagreement_penalty(self):
        """Test confidence penalty when systems disagree (> 2.0 K diff)"""
        self.mock_v1.predict.return_value = {
            'predicted_strikeouts': 4.0,
            'confidence': 70,
            'recommendation': 'UNDER'
        }
        self.mock_v1_6.predict.return_value = {
            'predicted_strikeouts': 7.0,  # Diff = 3.0 > 2.0
            'confidence': 80,
            'recommendation': 'OVER'
        }

        result = self.ensemble.predict(
            pitcher_lookup='gerrit-cole',
            features={'season_games_started': 10, 'ip_avg_last_5': 6.0, 'rolling_stats_games': 10},
            strikeouts_line=6.0
        )

        assert 'disagree' in result['agreement_note'].lower()
        # Confidence should be penalized
        assert result['base_confidence'] < 75  # (70+80)/2 = 75, penalized by 0.85 = 63.75

    # ========================================================================
    # Fallback Tests (One System Fails)
    # ========================================================================

    def test_v1_skips_uses_v1_6(self):
        """Test fallback to V1.6 when V1 skips"""
        self.mock_v1.predict.return_value = {
            'recommendation': 'SKIP',
            'skip_reason': 'First start of season',
            'red_flags': ['SKIP: First start']
        }
        self.mock_v1_6.predict.return_value = {
            'predicted_strikeouts': 7.0,
            'confidence': 80,
            'recommendation': 'OVER'
        }

        result = self.ensemble.predict(
            pitcher_lookup='gerrit-cole',
            features={},
            strikeouts_line=6.5
        )

        assert result['system_id'] == 'ensemble_v1'
        assert 'V1 skipped' in result['ensemble_note']
        # Should use V1.6 prediction with reduced confidence
        assert result['confidence'] == 80 * 0.8  # Reduced to 64

    def test_v1_6_skips_uses_v1(self):
        """Test fallback to V1 when V1.6 skips"""
        self.mock_v1.predict.return_value = {
            'predicted_strikeouts': 6.0,
            'confidence': 70,
            'recommendation': 'OVER'
        }
        self.mock_v1_6.predict.return_value = {
            'recommendation': 'SKIP',
            'skip_reason': 'Low IP average',
            'red_flags': ['SKIP: Low IP']
        }

        result = self.ensemble.predict(
            pitcher_lookup='gerrit-cole',
            features={},
            strikeouts_line=6.5
        )

        assert result['system_id'] == 'ensemble_v1'
        assert 'V1.6 skipped' in result['ensemble_note']
        # Should use V1 prediction with reduced confidence
        assert result['confidence'] == 70 * 0.8  # Reduced to 56

    def test_both_skip(self):
        """Test skip when both systems skip"""
        self.mock_v1.predict.return_value = {
            'recommendation': 'SKIP',
            'skip_reason': 'First start',
            'red_flags': ['SKIP: First start']
        }
        self.mock_v1_6.predict.return_value = {
            'recommendation': 'SKIP',
            'skip_reason': 'First start',
            'red_flags': ['SKIP: First start']
        }

        result = self.ensemble.predict(
            pitcher_lookup='gerrit-cole',
            features={},
            strikeouts_line=6.5
        )

        assert result['recommendation'] == 'SKIP'
        assert result['skip_reason'] == 'Both systems skipped'
        assert result['system_id'] == 'ensemble_v1'

    def test_both_error(self):
        """Test error when both systems fail"""
        self.mock_v1.predict.return_value = {
            'recommendation': 'ERROR',
            'error': 'Model failed to load'
        }
        self.mock_v1_6.predict.return_value = {
            'recommendation': 'ERROR',
            'error': 'Model failed to load'
        }

        result = self.ensemble.predict(
            pitcher_lookup='gerrit-cole',
            features={},
            strikeouts_line=6.5
        )

        assert result['recommendation'] == 'ERROR'
        assert 'Both systems failed' in result['error']

    def test_v1_error_uses_v1_6(self):
        """Test fallback to V1.6 when V1 errors"""
        self.mock_v1.predict.return_value = {
            'recommendation': 'ERROR',
            'error': 'Model failed'
        }
        self.mock_v1_6.predict.return_value = {
            'predicted_strikeouts': 7.0,
            'confidence': 80,
            'recommendation': 'OVER'
        }

        result = self.ensemble.predict(
            pitcher_lookup='gerrit-cole',
            features={'season_games_started': 10, 'ip_avg_last_5': 6.0, 'rolling_stats_games': 10},
            strikeouts_line=6.5
        )

        # Should still use V1.6 (skip ERROR like SKIP)
        assert result['system_id'] == 'ensemble_v1'

    # ========================================================================
    # Weight Normalization Tests
    # ========================================================================

    def test_weight_normalization(self):
        """Test weights are normalized if sum > 1.0"""
        ensemble = MLBEnsembleV1(
            v1_predictor=self.mock_v1,
            v1_6_predictor=self.mock_v1_6,
            v1_weight=0.6,
            v1_6_weight=0.8  # Total = 1.4 > 1.0
        )

        # Weights should be normalized
        assert ensemble.v1_weight == pytest.approx(0.6 / 1.4, rel=1e-2)
        assert ensemble.v1_6_weight == pytest.approx(0.8 / 1.4, rel=1e-2)
        assert ensemble.v1_weight + ensemble.v1_6_weight == pytest.approx(1.0, rel=1e-2)

    # ========================================================================
    # Component Prediction Metadata Tests
    # ========================================================================

    def test_includes_component_predictions(self):
        """Test ensemble result includes component predictions"""
        self.mock_v1.predict.return_value = {
            'predicted_strikeouts': 6.0,
            'confidence': 70,
            'recommendation': 'OVER'
        }
        self.mock_v1_6.predict.return_value = {
            'predicted_strikeouts': 7.0,
            'confidence': 80,
            'recommendation': 'OVER'
        }

        result = self.ensemble.predict(
            pitcher_lookup='gerrit-cole',
            features={'season_games_started': 10, 'ip_avg_last_5': 6.0, 'rolling_stats_games': 10},
            strikeouts_line=6.5
        )

        assert 'component_predictions' in result
        assert result['component_predictions'] == {
            'v1_baseline': 6.0,
            'v1_6_rolling': 7.0
        }

    def test_includes_component_confidences(self):
        """Test ensemble result includes component confidences"""
        self.mock_v1.predict.return_value = {
            'predicted_strikeouts': 6.0,
            'confidence': 70,
            'recommendation': 'OVER'
        }
        self.mock_v1_6.predict.return_value = {
            'predicted_strikeouts': 7.0,
            'confidence': 80,
            'recommendation': 'OVER'
        }

        result = self.ensemble.predict(
            pitcher_lookup='gerrit-cole',
            features={'season_games_started': 10, 'ip_avg_last_5': 6.0, 'rolling_stats_games': 10},
            strikeouts_line=6.5
        )

        assert 'component_confidences' in result
        assert result['component_confidences'] == {
            'v1_baseline': 70,
            'v1_6_rolling': 80
        }

    def test_includes_agreement_note(self):
        """Test ensemble result includes agreement note"""
        self.mock_v1.predict.return_value = {
            'predicted_strikeouts': 6.0,
            'confidence': 70,
            'recommendation': 'OVER'
        }
        self.mock_v1_6.predict.return_value = {
            'predicted_strikeouts': 6.5,
            'confidence': 80,
            'recommendation': 'OVER'
        }

        result = self.ensemble.predict(
            pitcher_lookup='gerrit-cole',
            features={'season_games_started': 10, 'ip_avg_last_5': 6.0, 'rolling_stats_games': 10},
            strikeouts_line=6.5
        )

        assert 'agreement_note' in result
        assert 'diff=' in result['agreement_note']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

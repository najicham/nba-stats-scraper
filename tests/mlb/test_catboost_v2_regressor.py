# tests/mlb/test_catboost_v2_regressor.py
"""
Unit tests for CatBoost V2 Regressor Predictor

Tests the regressor prediction flow: model.predict() -> predicted_K -> edge.
Uses mocked CatBoost model to avoid GCS/model dependencies.
"""

import math
import pytest
import numpy as np
from unittest.mock import Mock, MagicMock, patch

from predictions.mlb.prediction_systems.catboost_v2_regressor_predictor import (
    CatBoostV2RegressorPredictor,
    SIGMOID_SCALE,
)


def _make_features(**overrides):
    """Build a minimal valid feature dict (36 active features + legacy extras)."""
    base = {
        'k_avg_last_3': 6.0,
        'k_avg_last_5': 5.8,
        'k_avg_last_10': 5.5,
        'k_std_last_10': 2.0,
        'ip_avg_last_5': 6.0,
        'season_k_per_9': 9.5,
        'season_era': 3.50,
        'season_whip': 1.10,
        'season_games_started': 15,
        'season_strikeouts': 100,
        'is_home': True,
        'opponent_team_k_rate': 0.23,
        'ballpark_k_factor': 1.02,
        'month_of_season': 6,
        'days_into_season': 75,
        'season_swstr_pct': 0.11,
        'season_csw_pct': 0.30,
        'days_rest': 5,
        'games_last_30_days': 5,
        'pitch_count_avg_last_5': 92.0,
        'season_innings': 95.0,
        'is_postseason': False,
        'k_avg_vs_line': 0.3,
        'strikeouts_line': 5.5,
        'bp_projection': 6.0,
        'projection_diff': 0.5,
        'over_implied_prob': 0.52,
        'swstr_pct_last_3': 0.12,
        'fb_velocity_last_3': 95.0,
        'swstr_trend': 0.01,
        'velocity_change': -0.2,
        'vs_opp_k_per_9': 8.5,
        'vs_opp_games': 3,
        'season_starts': 15,
        'k_per_pitch': 0.065,
        'recent_workload_ratio': 1.0,
        'o_swing_pct': 0.32,
        'z_contact_pct': 0.85,
        'fip': 3.40,
        'gb_pct': 0.42,
        # Red flag avoidance
        'player_lookup': 'test-pitcher',
        'rolling_stats_games': 10,
    }
    base.update(overrides)
    return base


def _make_predictor_with_mock_model(model_return_value):
    """Create a CatBoostV2RegressorPredictor with a mocked model.

    Bypasses load_model() and GCS — injects mock model directly.
    """
    predictor = CatBoostV2RegressorPredictor.__new__(CatBoostV2RegressorPredictor)
    predictor.system_id = 'catboost_v2_regressor'
    predictor.project_id = 'test-project'
    predictor.model_path = 'gs://test-bucket/test-model.cbm'
    predictor.model_metadata = {}
    predictor._bq_client = None

    mock_model = MagicMock()
    mock_model.predict.return_value = np.array([model_return_value])
    predictor.model = mock_model

    return predictor


class TestCatBoostV2Regressor:
    """Tests for CatBoostV2RegressorPredictor."""

    # ========================================================================
    # Test 1: predict returns real edge (OVER direction)
    # ========================================================================
    def test_predict_returns_real_edge(self):
        """Mock model returns predicted_K=6.5 with line=5.5 -> edge=1.0, OVER."""
        predictor = _make_predictor_with_mock_model(model_return_value=6.5)
        features = _make_features()

        result = predictor.predict(
            pitcher_lookup='gerrit_cole',
            features=features,
            strikeouts_line=5.5,
        )

        assert result['recommendation'] == 'OVER'
        assert result['edge'] == 1.0
        assert result['predicted_strikeouts'] == 6.5
        assert result['strikeouts_line'] == 5.5
        assert result['system_id'] == 'catboost_v2_regressor'

    # ========================================================================
    # Test 2: predict under direction
    # ========================================================================
    def test_predict_under_direction(self):
        """Mock model returns predicted_K=4.5 with line=5.5 -> edge=-1.0, UNDER."""
        predictor = _make_predictor_with_mock_model(model_return_value=4.5)
        features = _make_features()

        result = predictor.predict(
            pitcher_lookup='gerrit_cole',
            features=features,
            strikeouts_line=5.5,
        )

        assert result['recommendation'] == 'UNDER'
        assert result['edge'] == -1.0
        assert result['predicted_strikeouts'] == 4.5

    # ========================================================================
    # Test 3: p_over sigmoid
    # ========================================================================
    def test_p_over_sigmoid(self):
        """Verify p_over is between 0 and 1, >0.5 for OVER, <0.5 for UNDER."""
        # OVER case: predicted_K=6.5, line=5.5, edge=+1.0
        predictor_over = _make_predictor_with_mock_model(model_return_value=6.5)
        result_over = predictor_over.predict(
            pitcher_lookup='gerrit_cole',
            features=_make_features(),
            strikeouts_line=5.5,
        )
        assert 0.0 < result_over['p_over'] < 1.0
        assert result_over['p_over'] > 0.5

        # Verify sigmoid math: p_over = 1 / (1 + exp(-edge * SIGMOID_SCALE))
        expected = 1.0 / (1.0 + math.exp(-1.0 * SIGMOID_SCALE))
        assert abs(result_over['p_over'] - round(expected, 4)) < 0.001

        # UNDER case: predicted_K=4.5, line=5.5, edge=-1.0
        predictor_under = _make_predictor_with_mock_model(model_return_value=4.5)
        result_under = predictor_under.predict(
            pitcher_lookup='gerrit_cole',
            features=_make_features(),
            strikeouts_line=5.5,
        )
        assert 0.0 < result_under['p_over'] < 1.0
        assert result_under['p_over'] < 0.5

    # ========================================================================
    # Test 4: predicted_K clamped
    # ========================================================================
    def test_predicted_k_clamped(self):
        """Model returns 25.0 -> clamped to 20.0."""
        predictor = _make_predictor_with_mock_model(model_return_value=25.0)
        features = _make_features()

        result = predictor.predict(
            pitcher_lookup='gerrit_cole',
            features=features,
            strikeouts_line=5.5,
        )

        assert result['predicted_strikeouts'] == 20.0
        # Edge should be 20.0 - 5.5 = 14.5
        assert result['edge'] == 14.5
        assert result['recommendation'] == 'OVER'

    # ========================================================================
    # Test 5: missing line
    # ========================================================================
    def test_missing_line(self):
        """strikeouts_line is None -> edge is None, recommendation is NO_LINE."""
        predictor = _make_predictor_with_mock_model(model_return_value=6.5)
        features = _make_features()

        result = predictor.predict(
            pitcher_lookup='gerrit_cole',
            features=features,
            strikeouts_line=None,
        )

        assert result['edge'] is None
        assert result['recommendation'] == 'NO_LINE'
        assert result['predicted_strikeouts'] == 6.5
        # p_over defaults to 0.5 when no line
        assert result['p_over'] == 0.5

    # ========================================================================
    # Test 6: system_id
    # ========================================================================
    def test_system_id(self):
        """Verify system_id is 'catboost_v2_regressor'."""
        predictor = _make_predictor_with_mock_model(model_return_value=6.0)
        features = _make_features()

        result = predictor.predict(
            pitcher_lookup='gerrit_cole',
            features=features,
            strikeouts_line=5.5,
        )

        assert result['system_id'] == 'catboost_v2_regressor'

    # ========================================================================
    # Test 7: negative predicted_K clamped to 0
    # ========================================================================
    def test_negative_predicted_k_clamped(self):
        """Model returns -2.0 -> clamped to 0.0."""
        predictor = _make_predictor_with_mock_model(model_return_value=-2.0)
        features = _make_features()

        result = predictor.predict(
            pitcher_lookup='test-pitcher',
            features=features,
            strikeouts_line=5.5,
        )

        assert result['predicted_strikeouts'] == 0.0
        assert result['edge'] == -5.5
        assert result['recommendation'] == 'UNDER'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

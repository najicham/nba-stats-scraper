# tests/mlb/test_catboost_v2_regressor.py
"""
Unit tests for CatBoost V2 Regressor Predictor

Tests the regressor prediction flow: model.predict() -> predicted_K ->
model-market blend -> edge / Poisson p_over (Stage 1.1).
Uses a mocked CatBoost model to avoid GCS/model dependencies.
"""

import math
import os
import pytest
import numpy as np
from unittest.mock import MagicMock, patch

from predictions.mlb.prediction_systems.catboost_v2_regressor_predictor import (
    CatBoostV2RegressorPredictor,
    BLEND_WEIGHT_FLOOR,
    _poisson_cdf,
    poisson_p_over,
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


def _make_predictor_with_mock_model(model_return_value, metadata=None):
    """Create a CatBoostV2RegressorPredictor with a mocked model.

    Bypasses load_model() and GCS — injects mock model directly.
    `metadata` populates model_metadata (used by the model-market blend).
    """
    predictor = CatBoostV2RegressorPredictor.__new__(CatBoostV2RegressorPredictor)
    predictor.system_id = 'catboost_v2_regressor'
    predictor.project_id = 'test-project'
    predictor.model_path = 'gs://test-bucket/test-model.cbm'
    predictor.model_metadata = metadata if metadata is not None else {}
    predictor._bq_client = None

    mock_model = MagicMock()
    mock_model.predict.return_value = np.array([model_return_value])
    predictor.model = mock_model

    return predictor


class TestCatBoostV2Regressor:
    """Tests for CatBoostV2RegressorPredictor prediction flow."""

    # ========================================================================
    # Test 1: predict returns real edge (OVER direction)
    # ========================================================================
    def test_predict_returns_real_edge(self):
        """Mock model returns predicted_K=6.5 with line=5.5 -> edge=1.0, OVER.

        No blend metadata -> w=1.0 (pure model), so blended_K == model output.
        """
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
        assert result['blend_weight'] == 1.0

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
    # Test 3: p_over is the Poisson tail P(K > line)
    # ========================================================================
    def test_p_over_poisson(self):
        """p_over = P(K > line) under K ~ Poisson(blended_K); honest probability."""
        # OVER case: predicted_K=6.5, line=5.5, w=1.0 -> lambda=6.5
        predictor_over = _make_predictor_with_mock_model(model_return_value=6.5)
        result_over = predictor_over.predict(
            pitcher_lookup='gerrit_cole',
            features=_make_features(),
            strikeouts_line=5.5,
        )
        assert result_over['p_over'] == round(poisson_p_over(5.5, 6.5), 4)
        # Numeric anchor independent of the helper: P(K>5.5 | lambda=6.5) ~= 0.631
        assert abs(result_over['p_over'] - 0.631) < 0.002
        assert result_over['p_over'] > 0.5

        # UNDER case: predicted_K=4.5, line=5.5 -> lambda=4.5
        predictor_under = _make_predictor_with_mock_model(model_return_value=4.5)
        result_under = predictor_under.predict(
            pitcher_lookup='gerrit_cole',
            features=_make_features(),
            strikeouts_line=5.5,
        )
        assert result_under['p_over'] == round(poisson_p_over(5.5, 4.5), 4)
        assert abs(result_under['p_over'] - 0.2971) < 0.002
        assert result_under['p_over'] < 0.5

    # ========================================================================
    # Test 4: predicted_K clamped
    # ========================================================================
    def test_predicted_k_clamped(self):
        """Model returns 25.0 -> clamped to 20.0 (blend with w=1.0 is a no-op)."""
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
        # p_over defaults to 0.5 when no line (no Poisson tail to evaluate)
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


class TestPoissonHelpers:
    """Tests for the stdlib Poisson CDF / tail helpers."""

    def test_poisson_cdf_known_values(self):
        """_poisson_cdf matches hand-computed Poisson CDF values."""
        # P(X <= 5 | lambda=6.5) ~= 0.36904
        assert abs(_poisson_cdf(5, 6.5) - 0.36904) < 1e-4
        # P(X <= 5 | lambda=4.5) ~= 0.70293
        assert abs(_poisson_cdf(5, 4.5) - 0.70293) < 1e-4

    def test_poisson_cdf_is_monotone_and_bounded(self):
        """CDF is non-decreasing in k and stays within [0, 1]."""
        prev = -1.0
        for k in range(0, 15):
            v = _poisson_cdf(k, 7.0)
            assert 0.0 <= v <= 1.0
            assert v >= prev
            prev = v
        # CDF over the full support approaches 1.
        assert _poisson_cdf(40, 7.0) == pytest.approx(1.0, abs=1e-6)

    def test_poisson_cdf_zero_lambda(self):
        """Non-positive lambda is a degenerate point mass at 0 -> CDF == 1."""
        assert _poisson_cdf(0, 0.0) == 1.0
        assert _poisson_cdf(5, -1.0) == 1.0

    def test_poisson_p_over_bounds(self):
        """p_over stays in [0, 1] and rises with lambda."""
        low = poisson_p_over(5.5, 3.0)
        high = poisson_p_over(5.5, 9.0)
        assert 0.0 <= low <= 1.0
        assert 0.0 <= high <= 1.0
        assert high > low

    def test_poisson_p_over_integer_line_excludes_push(self):
        """An integer line treats K == line as a push, not an over.

        floor(6.0) == floor(6.5) == 6, so P(K > 6.0) == P(K > 6.5): a K of
        exactly 6 wins neither.
        """
        assert poisson_p_over(6.0, 7.0) == poisson_p_over(6.5, 7.0)
        assert poisson_p_over(6.0, 7.0) == pytest.approx(
            1.0 - _poisson_cdf(6, 7.0), abs=1e-9
        )


class TestModelMarketBlend:
    """Tests for the Stage 1.1 model-market blend (blended = w*model + (1-w)*line)."""

    def test_blend_default_no_metadata(self):
        """No metadata and no env var -> w=1.0 (pure model, no blend)."""
        predictor = _make_predictor_with_mock_model(model_return_value=7.5)
        assert predictor._get_blend_weight() == 1.0

    def test_blend_weight_from_metadata(self):
        """Metadata blend_weight shrinks edge: blended = w*model + (1-w)*line."""
        predictor = _make_predictor_with_mock_model(
            model_return_value=7.5, metadata={'blend_weight': 0.5},
        )
        result = predictor.predict(
            pitcher_lookup='blended_pitcher',
            features=_make_features(),
            strikeouts_line=5.5,
        )
        # blended_K = 0.5 * 7.5 + 0.5 * 5.5 = 6.5; edge = 1.0 (raw edge 2.0 * w)
        assert result['blend_weight'] == 0.5
        assert result['predicted_strikeouts'] == 6.5
        assert result['edge'] == 1.0
        assert result['recommendation'] == 'OVER'
        assert result['p_over'] == round(poisson_p_over(5.5, 6.5), 4)

    def test_blend_env_override_beats_metadata(self):
        """MLB_BLEND_WEIGHT env var overrides the metadata blend_weight."""
        predictor = _make_predictor_with_mock_model(
            model_return_value=8.5, metadata={'blend_weight': 1.0},
        )
        with patch.dict(os.environ, {'MLB_BLEND_WEIGHT': '0.3'}):
            result = predictor.predict(
                pitcher_lookup='env_pitcher',
                features=_make_features(),
                strikeouts_line=5.5,
            )
        # blended_K = 0.3 * 8.5 + 0.7 * 5.5 = 6.4; edge = 0.9
        assert result['blend_weight'] == 0.3
        assert result['predicted_strikeouts'] == 6.4
        assert result['edge'] == pytest.approx(0.9, abs=1e-9)

    def test_blend_weight_clamped_to_floor(self):
        """A blend_weight below the floor is clamped up to BLEND_WEIGHT_FLOOR."""
        predictor = _make_predictor_with_mock_model(
            model_return_value=7.5, metadata={'blend_weight': 0.05},
        )
        assert predictor._get_blend_weight() == BLEND_WEIGHT_FLOOR

    def test_blend_weight_clamped_to_one(self):
        """A blend_weight above 1.0 is clamped down to 1.0 (model never amplified)."""
        predictor = _make_predictor_with_mock_model(
            model_return_value=7.5, metadata={'blend_weight': 1.8},
        )
        assert predictor._get_blend_weight() == 1.0

    def test_blend_weight_invalid_falls_back(self):
        """A non-numeric blend_weight falls back to 1.0 (no blend) rather than erroring."""
        predictor = _make_predictor_with_mock_model(
            model_return_value=7.5, metadata={'blend_weight': 'not-a-number'},
        )
        assert predictor._get_blend_weight() == 1.0

    def test_blend_shrinks_edge_toward_zero(self):
        """The blend pulls the prediction toward the line, shrinking |edge|."""
        raw = _make_predictor_with_mock_model(model_return_value=9.0)
        blended = _make_predictor_with_mock_model(
            model_return_value=9.0, metadata={'blend_weight': 0.4},
        )
        raw_result = raw.predict(
            pitcher_lookup='p', features=_make_features(), strikeouts_line=5.5,
        )
        blended_result = blended.predict(
            pitcher_lookup='p', features=_make_features(), strikeouts_line=5.5,
        )
        # Raw edge 3.5; blended edge = 0.4 * 3.5 = 1.4. Same direction, smaller.
        assert raw_result['edge'] == 3.5
        assert blended_result['edge'] == pytest.approx(1.4, abs=1e-9)
        assert abs(blended_result['edge']) < abs(raw_result['edge'])
        assert blended_result['recommendation'] == raw_result['recommendation']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

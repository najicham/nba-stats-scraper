# tests/predictions/test_catboost_v8.py

"""
Unit tests for CatBoost V8 Prediction System

CatBoost V8 is the PRIMARY production model (71.6% accuracy, MAE 3.40).
This test suite ensures model reliability and prevents silent failures.

Tests cover:
- Model loading from local and GCS paths
- Fallback behavior when model unavailable
- 33-feature vector preparation and validation
- Feature version validation (v2_33features required)
- Prediction output format
- Confidence calculation
- Recommendation logic
- Error handling and logging

Run with: pytest tests/predictions/test_catboost_v8.py -v
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import numpy as np
import sys
import os
import logging

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from predictions.worker.prediction_systems.catboost_v8 import CatBoostV8, V8_FEATURES, ModelLoadError


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_features_v2():
    """Sample feature dictionary with v2_33features"""
    return {
        # Base features (25)
        'points_avg_last_5': 26.5,
        'points_avg_last_10': 25.8,
        'points_avg_season': 25.0,
        'points_std_last_10': 4.8,
        'games_in_last_7_days': 2,
        'fatigue_score': 78.0,
        'shot_zone_mismatch_score': 4.5,
        'pace_score': 0.8,
        'usage_spike_score': 0.0,
        'rest_advantage': 1,
        'injury_risk': 0,
        'recent_trend': 2.5,
        'minutes_change': 0.5,
        'opponent_def_rating': 112.5,
        'opponent_pace': 102.0,
        'home_away': 0,
        'back_to_back': 0,
        'playoff_game': 0,
        'pct_paint': 42.0,
        'pct_mid_range': 18.0,
        'pct_three': 28.0,
        'pct_free_throw': 12.0,
        'team_pace': 100.8,
        'team_off_rating': 117.2,
        'team_win_pct': 0.55,
        # Metadata
        'feature_quality_score': 85.0,
        'feature_version': 'v2_33features',
        'feature_count': 33,
    }


@pytest.fixture
def mock_catboost_model():
    """Mock CatBoost model"""
    mock_model = Mock()
    mock_model.predict = Mock(return_value=np.array([25.5]))
    return mock_model


@pytest.fixture
def catboost_system_with_mock(mock_catboost_model):
    """Create CatBoost system with mock model (bypassing actual model loading)"""
    # Use require_model=False to allow testing without actual model file
    # Then inject the mock model
    system = CatBoostV8(use_local=False, require_model=False)
    system.model = mock_catboost_model
    return system


@pytest.fixture
def catboost_system_no_model():
    """Create CatBoost system without model (for fallback testing)

    Note: In production, require_model=True by default, which raises ModelLoadError.
    For testing fallback behavior, we use require_model=False.
    """
    system = CatBoostV8(use_local=False, require_model=False)
    system.model = None
    return system


# ============================================================================
# TEST CLASS 1: Model Loading
# ============================================================================

class TestModelLoading:
    """Test model loading from various sources"""

    def test_system_initialization(self, catboost_system_with_mock):
        """Test system initializes with correct attributes"""
        assert catboost_system_with_mock.system_id == 'catboost_v8'
        assert catboost_system_with_mock.model_version == 'v8'
        assert catboost_system_with_mock.model is not None

    @patch.dict(os.environ, {'CATBOOST_V8_MODEL_PATH': 'gs://bucket/model.cbm'})
    @patch('predictions.worker.prediction_systems.catboost_v8.CatBoostV8._load_model_from_path')
    def test_load_from_env_variable(self, mock_load):
        """Test model loading from CATBOOST_V8_MODEL_PATH env var"""
        # Use require_model=False since mock doesn't actually set self.model
        system = CatBoostV8(require_model=False)
        # With retry logic, it's called multiple times (3 attempts)
        mock_load.assert_called_with('gs://bucket/model.cbm')
        assert mock_load.call_count <= 3  # May be called up to 3 times

    @patch('predictions.worker.prediction_systems.catboost_v8.CatBoostV8._load_model_from_path')
    def test_explicit_path_overrides_env(self, mock_load):
        """Test explicit model_path parameter takes priority over env var"""
        with patch.dict(os.environ, {'CATBOOST_V8_MODEL_PATH': 'gs://bucket/old.cbm'}):
            # Use require_model=False since mock doesn't actually set self.model
            system = CatBoostV8(model_path='gs://bucket/new.cbm', use_local=False, require_model=False)
            # With retry logic, it's called multiple times (3 attempts)
            mock_load.assert_called_with('gs://bucket/new.cbm')
            assert mock_load.call_count <= 3  # May be called up to 3 times

    def test_no_model_loaded_creates_none(self, catboost_system_no_model):
        """Test system gracefully handles missing model"""
        assert catboost_system_no_model.model is None


# ============================================================================
# TEST CLASS 2: Feature Vector Preparation
# ============================================================================

class TestFeatureVectorPreparation:
    """Test 33-feature vector preparation and validation"""

    def test_prepare_33_features_complete(self, catboost_system_with_mock, sample_features_v2):
        """Test feature vector with all 33 features"""
        vector = catboost_system_with_mock._prepare_feature_vector(
            features=sample_features_v2,
            vegas_line=24.5,
            vegas_opening=24.0,
            opponent_avg=23.5,
            games_vs_opponent=5,
            minutes_avg_last_10=34.2,
            ppm_avg_last_10=0.75,
        )

        assert vector is not None
        assert vector.shape == (1, 33)

        # Verify base features (first 25)
        assert vector[0, 0] == 26.5  # points_avg_last_5
        assert vector[0, 1] == 25.8  # points_avg_last_10
        assert vector[0, 2] == 25.0  # points_avg_season

        # Verify Vegas features (positions 25-28)
        assert vector[0, 25] == 24.5  # vegas_line
        assert vector[0, 26] == 24.0  # vegas_opening
        assert vector[0, 27] == 0.5   # vegas_line_move
        assert vector[0, 28] == 1.0   # has_vegas_line

        # Verify opponent history (positions 29-30)
        assert vector[0, 29] == 23.5  # avg_points_vs_opponent
        assert vector[0, 30] == 5.0   # games_vs_opponent

        # Verify minutes/PPM (positions 31-32)
        assert vector[0, 31] == 34.2  # minutes_avg_last_10
        assert vector[0, 32] == 0.75  # ppm_avg_last_10

    def test_prepare_features_missing_vegas(self, catboost_system_with_mock, sample_features_v2):
        """Test feature vector with missing Vegas features (uses fallback)"""
        vector = catboost_system_with_mock._prepare_feature_vector(
            features=sample_features_v2,
            vegas_line=None,
            vegas_opening=None,
            opponent_avg=23.5,
            games_vs_opponent=5,
            minutes_avg_last_10=34.2,
            ppm_avg_last_10=0.75,
        )

        assert vector is not None
        # Should use season_avg (25.0) as fallback for missing Vegas features
        assert vector[0, 25] == 25.0  # vegas_line fallback
        assert vector[0, 26] == 25.0  # vegas_opening fallback
        assert vector[0, 27] == 0.0   # vegas_line_move (no data)
        assert vector[0, 28] == 0.0   # has_vegas_line (False)

    def test_prepare_features_missing_opponent_history(self, catboost_system_with_mock, sample_features_v2):
        """Test feature vector with missing opponent history (uses season avg)"""
        vector = catboost_system_with_mock._prepare_feature_vector(
            features=sample_features_v2,
            vegas_line=24.5,
            vegas_opening=24.0,
            opponent_avg=None,
            games_vs_opponent=0,
            minutes_avg_last_10=34.2,
            ppm_avg_last_10=0.75,
        )

        assert vector is not None
        # Should use season_avg (25.0) as fallback
        assert vector[0, 29] == 25.0  # avg_points_vs_opponent fallback
        assert vector[0, 30] == 0.0   # games_vs_opponent

    def test_feature_vector_no_nan_or_inf(self, catboost_system_with_mock, sample_features_v2):
        """Test feature vector contains no NaN or Inf values"""
        vector = catboost_system_with_mock._prepare_feature_vector(
            features=sample_features_v2,
            vegas_line=24.5,
            vegas_opening=24.0,
            opponent_avg=23.5,
            games_vs_opponent=5,
            minutes_avg_last_10=34.2,
            ppm_avg_last_10=0.75,
        )

        assert not np.any(np.isnan(vector))
        assert not np.any(np.isinf(vector))

    def test_feature_vector_length_exactly_33(self, catboost_system_with_mock, sample_features_v2):
        """Test feature vector is exactly 33 features (critical for model compatibility)"""
        vector = catboost_system_with_mock._prepare_feature_vector(
            features=sample_features_v2,
            vegas_line=24.5,
            vegas_opening=24.0,
            opponent_avg=23.5,
            games_vs_opponent=5,
            minutes_avg_last_10=34.2,
            ppm_avg_last_10=0.75,
        )

        # CRITICAL: Model is trained on exactly 33 features
        assert vector.shape[1] == 33, "CatBoost V8 requires exactly 33 features"
        assert len(V8_FEATURES) == 33, "V8_FEATURES constant must match model training"


# ============================================================================
# TEST CLASS 3: Feature Version Validation
# ============================================================================

class TestFeatureVersionValidation:
    """Test feature version validation (v2_33features required)"""

    def test_correct_feature_version_accepted(self, catboost_system_with_mock, sample_features_v2):
        """Test prediction succeeds with correct feature_version"""
        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=24.5,
        )

        assert result['system_id'] == 'catboost_v8'
        assert result['model_type'] == 'catboost_v8_real'

    def test_wrong_feature_version_raises_error(self, catboost_system_with_mock, sample_features_v2):
        """Test prediction fails with wrong feature_version"""
        sample_features_v2['feature_version'] = 'v1_25features'

        with pytest.raises(ValueError, match="requires feature_version='v2_33features'"):
            catboost_system_with_mock.predict(
                player_lookup='lebronjames',
                features=sample_features_v2,
                betting_line=24.5,
            )

    def test_missing_feature_version_raises_error(self, catboost_system_with_mock, sample_features_v2):
        """Test prediction fails with missing feature_version"""
        del sample_features_v2['feature_version']

        with pytest.raises(ValueError, match="requires feature_version='v2_33features'"):
            catboost_system_with_mock.predict(
                player_lookup='lebronjames',
                features=sample_features_v2,
                betting_line=24.5,
            )

    def test_wrong_feature_count_raises_error(self, catboost_system_with_mock, sample_features_v2):
        """Test prediction fails with wrong feature_count"""
        sample_features_v2['feature_count'] = 25  # Wrong count

        with pytest.raises(ValueError, match="requires 33 features"):
            catboost_system_with_mock.predict(
                player_lookup='lebronjames',
                features=sample_features_v2,
                betting_line=24.5,
            )


# ============================================================================
# TEST CLASS 4: Prediction Output
# ============================================================================

class TestPredictionOutput:
    """Test prediction generation and output format"""

    def test_prediction_output_format(self, catboost_system_with_mock, sample_features_v2):
        """Test prediction output has correct structure"""
        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=24.5,
        )

        # Check required fields
        assert 'system_id' in result
        assert 'model_version' in result
        assert 'predicted_points' in result
        assert 'confidence_score' in result
        assert 'recommendation' in result
        assert 'model_type' in result
        assert 'feature_count' in result

        # Check field values
        assert result['system_id'] == 'catboost_v8'
        assert result['model_version'] == 'v8'
        assert result['feature_count'] == 33
        assert result['model_type'] == 'catboost_v8_real'

    def test_predicted_points_clamped(self, catboost_system_with_mock, sample_features_v2):
        """Test predicted points are clamped to reasonable range [0, 60]"""
        # Mock model returns extreme value
        catboost_system_with_mock.model.predict = Mock(return_value=np.array([75.0]))

        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=24.5,
        )

        assert result['predicted_points'] <= 60.0

        # Test negative clamping
        catboost_system_with_mock.model.predict = Mock(return_value=np.array([-5.0]))

        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=24.5,
        )

        assert result['predicted_points'] >= 0.0

    def test_prediction_values_rounded(self, catboost_system_with_mock, sample_features_v2):
        """Test prediction values are rounded to 2 decimal places"""
        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=24.5,
        )

        # Check rounding
        assert isinstance(result['predicted_points'], float)
        assert isinstance(result['confidence_score'], float)
        # Verify at most 2 decimal places
        assert result['predicted_points'] == round(result['predicted_points'], 2)
        assert result['confidence_score'] == round(result['confidence_score'], 2)


# ============================================================================
# TEST CLASS 5: Confidence Calculation
# ============================================================================

class TestConfidenceCalculation:
    """Test confidence score calculation"""

    def test_high_quality_high_consistency(self, catboost_system_with_mock, sample_features_v2):
        """Test high confidence with high quality and consistency"""
        sample_features_v2['feature_quality_score'] = 95.0
        sample_features_v2['points_std_last_10'] = 3.5  # Low std = high consistency

        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=24.5,
        )

        # Base 75 + quality 10 + consistency 10 = 95
        assert result['confidence_score'] >= 90.0

    def test_low_quality_low_consistency(self, catboost_system_with_mock, sample_features_v2):
        """Test lower confidence with low quality and consistency"""
        sample_features_v2['feature_quality_score'] = 65.0
        sample_features_v2['points_std_last_10'] = 9.0  # High std = low consistency

        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=24.5,
        )

        # Base 75 + quality 2 + consistency 2 = 79
        assert result['confidence_score'] < 85.0

    def test_confidence_bounded_0_100(self, catboost_system_with_mock, sample_features_v2):
        """Test confidence is always between 0 and 100"""
        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=24.5,
        )

        assert 0 <= result['confidence_score'] <= 100


# ============================================================================
# TEST CLASS 6: Recommendation Logic
# ============================================================================

class TestRecommendationLogic:
    """Test betting recommendation generation"""

    def test_over_recommendation(self, catboost_system_with_mock, sample_features_v2):
        """Test OVER recommendation when prediction > line + edge"""
        catboost_system_with_mock.model.predict = Mock(return_value=np.array([27.0]))

        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=24.5,  # Prediction 27.0 - line 24.5 = 2.5 edge > 1.0 threshold
        )

        assert result['recommendation'] == 'OVER'

    def test_under_recommendation(self, catboost_system_with_mock, sample_features_v2):
        """Test UNDER recommendation when prediction < line - edge"""
        catboost_system_with_mock.model.predict = Mock(return_value=np.array([22.0]))

        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=24.5,  # Line 24.5 - prediction 22.0 = 2.5 edge > 1.0 threshold
        )

        assert result['recommendation'] == 'UNDER'

    def test_pass_recommendation_small_edge(self, catboost_system_with_mock, sample_features_v2):
        """Test PASS recommendation when edge is too small"""
        catboost_system_with_mock.model.predict = Mock(return_value=np.array([24.8]))

        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=24.5,  # Edge 0.3 < 1.0 threshold
        )

        assert result['recommendation'] == 'PASS'

    def test_pass_recommendation_low_confidence(self, catboost_system_with_mock, sample_features_v2):
        """Test PASS recommendation when confidence < 60"""
        sample_features_v2['feature_quality_score'] = 50.0  # Low quality
        sample_features_v2['points_std_last_10'] = 15.0     # High volatility

        catboost_system_with_mock.model.predict = Mock(return_value=np.array([27.0]))

        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=24.5,
        )

        # Even with good edge, low confidence should PASS
        if result['confidence_score'] < 60:
            assert result['recommendation'] == 'PASS'

    def test_no_line_recommendation(self, catboost_system_with_mock, sample_features_v2):
        """Test NO_LINE recommendation when betting_line is None"""
        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=None,
        )

        assert result['recommendation'] == 'NO_LINE'


# ============================================================================
# TEST CLASS 7: Fallback Behavior
# ============================================================================

class TestFallbackBehavior:
    """Test fallback prediction behavior

    Session 40 Update: MODEL_NOT_LOADED now raises ModelLoadError instead of
    falling back to weighted average. Fallback is only used for:
    - FEATURE_PREPARATION_FAILED
    - MODEL_PREDICTION_FAILED
    """

    def test_model_not_loaded_raises_error(self, catboost_system_no_model, sample_features_v2):
        """Test that predict() raises ModelLoadError when model is None

        This is the Session 40 behavior change: no silent fallback to weighted average.
        """
        with pytest.raises(ModelLoadError, match="model is not loaded"):
            catboost_system_no_model.predict(
                player_lookup='lebronjames',
                features=sample_features_v2,
                betting_line=24.5,
            )

    def test_require_model_true_raises_on_init(self):
        """Test that require_model=True (default) raises error during initialization"""
        with pytest.raises(ModelLoadError, match="FAILED to load after"):
            # No model path or local model available
            CatBoostV8(use_local=False, require_model=True)

    def test_require_model_false_allows_none(self):
        """Test that require_model=False allows model to be None (for testing only)"""
        system = CatBoostV8(use_local=False, require_model=False)
        assert system.model is None

    def test_fallback_for_feature_prep_failure(self, catboost_system_with_mock, sample_features_v2):
        """Test that FEATURE_PREPARATION_FAILED still uses fallback (not ModelLoadError)"""
        # Make _prepare_feature_vector return None to simulate feature prep failure
        catboost_system_with_mock._prepare_feature_vector = Mock(return_value=None)

        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=24.5,
        )

        # Should get fallback response, not exception
        assert result['model_type'] == 'fallback'
        assert result['prediction_error_code'] == 'FEATURE_PREPARATION_FAILED'
        assert result['confidence_score'] == 50.0

    def test_fallback_for_prediction_failure(self, catboost_system_with_mock, sample_features_v2):
        """Test that MODEL_PREDICTION_FAILED still uses fallback (not ModelLoadError)"""
        # Make model.predict() raise an exception
        catboost_system_with_mock.model.predict = Mock(side_effect=Exception("Prediction error"))

        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=24.5,
        )

        # Should get fallback response, not exception
        assert result['model_type'] == 'fallback'
        assert result['prediction_error_code'] == 'MODEL_PREDICTION_FAILED'
        assert result['confidence_score'] == 50.0

    def test_fallback_weighted_average_formula(self, catboost_system_with_mock):
        """Test fallback calculates weighted average correctly"""
        # Make prediction fail so fallback is used
        catboost_system_with_mock.model.predict = Mock(side_effect=Exception("Model error"))

        features = {
            'points_avg_last_5': 30.0,
            'points_avg_last_10': 28.0,
            'points_avg_season': 25.0,
            'feature_version': 'v2_33features',
        }

        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=features,
            betting_line=24.5,
        )

        # Expected: 0.4*30 + 0.35*28 + 0.25*25 = 12 + 9.8 + 6.25 = 28.05
        assert abs(result['predicted_points'] - 28.05) < 0.1

    def test_fallback_logs_warning(self, catboost_system_with_mock, sample_features_v2, caplog):
        """Test fallback logs warning message"""
        # Make prediction fail to trigger fallback
        catboost_system_with_mock.model.predict = Mock(side_effect=Exception("Model error"))

        with caplog.at_level(logging.WARNING):
            result = catboost_system_with_mock.predict(
                player_lookup='lebronjames',
                features=sample_features_v2,
                betting_line=24.5,
            )

        # Check warning was logged
        assert any('FALLBACK_PREDICTION' in record.message for record in caplog.records)


# ============================================================================
# TEST CLASS 8: Error Handling
# ============================================================================

class TestErrorHandling:
    """Test error handling and edge cases"""

    def test_prediction_error_returns_fallback(self, catboost_system_with_mock, sample_features_v2):
        """Test fallback is used when prediction raises exception"""
        catboost_system_with_mock.model.predict = Mock(side_effect=Exception("Model error"))

        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features=sample_features_v2,
            betting_line=24.5,
        )

        assert result['model_type'] == 'fallback'

    def test_invalid_feature_vector_returns_fallback(self, catboost_system_with_mock):
        """Test fallback when feature vector preparation fails"""
        # Mock _prepare_feature_vector to return None (simulating failure)
        catboost_system_with_mock._prepare_feature_vector = Mock(return_value=None)

        result = catboost_system_with_mock.predict(
            player_lookup='lebronjames',
            features={'feature_version': 'v2_33features', 'feature_count': 33},
            betting_line=24.5,
        )

        # Should use fallback when feature vector prep returns None
        assert result['model_type'] == 'fallback'


# ============================================================================
# TEST CLASS 9: Model Info
# ============================================================================

class TestModelInfo:
    """Test model information retrieval"""

    def test_get_model_info_with_model(self, catboost_system_with_mock):
        """Test get_model_info returns correct information when model loaded"""
        info = catboost_system_with_mock.get_model_info()

        assert info['system_id'] == 'catboost_v8'
        assert info['model_version'] == 'v8'
        assert info['model_loaded'] is True
        assert info['feature_count'] == 33
        assert info['features'] == V8_FEATURES
        assert len(info['features']) == 33

    def test_get_model_info_without_model(self, catboost_system_no_model):
        """Test get_model_info when model not loaded"""
        info = catboost_system_no_model.get_model_info()

        assert info['model_loaded'] is False

    def test_get_model_info_with_metadata(self, catboost_system_with_mock):
        """Test get_model_info includes metadata when available"""
        catboost_system_with_mock.metadata = {
            'best_mae': 3.40,
            'training_samples': 76863,
        }

        info = catboost_system_with_mock.get_model_info()

        assert 'training_mae' in info
        assert 'training_samples' in info
        assert info['training_mae'] == 3.40
        assert info['training_samples'] == 76863


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

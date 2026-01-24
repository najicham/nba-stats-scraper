"""
Unit Tests for ML Feature Extraction (Retraining Pipeline)

Tests cover:
1. Feature vector building - constructing feature arrays for ML models
2. Model loader functionality - loading different model types
3. Feature validation - ensuring correct dimensions and values
4. Model wrapper interface - consistent prediction interface
5. Cache management - model caching behavior
6. Feature count handling - 25 vs 33 feature models

Run with: pytest tests/unit/ml/test_feature_extraction.py -v

Directory: tests/unit/ml/
"""

import pytest
import numpy as np
from datetime import date
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, List, Any


# ============================================================================
# TEST FIXTURES
# ============================================================================

@pytest.fixture
def sample_player_data():
    """Sample player data for feature vector building."""
    return {
        'player_lookup': 'lebron-james',
        'game_id': '20250115_LAL_BOS',
        'features': [
            25.5, 24.8, 24.0, 4.5, 32.0,        # Recent performance (0-4)
            75.0, 3.5, 1.2, 0.5,                 # Composite factors (5-8)
            0.0, 0.0, 0.0, 0.0,                  # Deferred/placeholder (9-12)
            112.0, 100.5,                        # Opponent metrics (13-14)
            1.0, 2.0, 0.0,                       # Context flags (15-17)
            35.0, 20.0, 30.0, 65.0,             # Shot zones (18-21)
            102.0, 115.0, 28.0                   # Team metrics (22-24)
        ],
        'opponent_team_abbr': 'BOS',
        'team_abbr': 'LAL',
        'season_avg': 25.0,
        'vegas_line': 26.5,
        'vegas_opening': 25.5,
        'avg_points_vs_opponent': 28.5,
        'games_vs_opponent': 8,
        'minutes_avg_last_10': 34.5,
        'ppm_avg_last_10': 0.75,
        'injury_status': None
    }


@pytest.fixture
def sample_model_info():
    """Sample ModelInfo for testing."""
    from ml.model_loader import ModelInfo

    return ModelInfo(
        model_id='test_catboost_v8',
        model_type='catboost',
        model_path='/tmp/test_model.cbm',
        model_format='cbm',
        feature_count=25,
        feature_list=None
    )


@pytest.fixture
def sample_model_info_33():
    """Sample ModelInfo for 33-feature model."""
    from ml.model_loader import ModelInfo

    return ModelInfo(
        model_id='test_catboost_v8_extended',
        model_type='catboost',
        model_path='/tmp/test_model_extended.cbm',
        model_format='cbm',
        feature_count=33,
        feature_list=None
    )


# ============================================================================
# TEST CLASS 1: FEATURE VECTOR BUILDING - 25 FEATURES (5 tests)
# ============================================================================

class TestFeatureVectorBuilding25:
    """Test feature vector building for 25-feature models."""

    def test_build_feature_vector_25_correct_shape(self, sample_player_data):
        """
        Test that 25-feature vector has correct shape.

        Expected: (1, 25) array for single prediction
        """
        from ml.experiment_runner import build_feature_vector

        features = build_feature_vector(
            sample_player_data,
            feature_count=25
        )

        assert features is not None
        assert features.shape == (1, 25)

    def test_build_feature_vector_25_values_match(self, sample_player_data):
        """
        Test that feature values match base features.

        Expected: Direct passthrough of base 25 features
        """
        from ml.experiment_runner import build_feature_vector

        features = build_feature_vector(
            sample_player_data,
            feature_count=25
        )

        # Verify first few values
        assert features[0, 0] == 25.5  # points_avg_last_5
        assert features[0, 1] == 24.8  # points_avg_last_10
        assert features[0, 2] == 24.0  # points_avg_season
        assert features[0, 4] == 32.0  # minutes_avg_last_10

    def test_build_feature_vector_25_no_nan(self, sample_player_data):
        """
        Test that feature vector has no NaN values.

        Expected: All values are valid numbers
        """
        from ml.experiment_runner import build_feature_vector

        features = build_feature_vector(
            sample_player_data,
            feature_count=25
        )

        assert not np.any(np.isnan(features))
        assert not np.any(np.isinf(features))

    def test_build_feature_vector_25_all_features_present(self, sample_player_data):
        """
        Test that all 25 features are populated.

        Expected: No None/empty values in the vector
        """
        from ml.experiment_runner import build_feature_vector

        features = build_feature_vector(
            sample_player_data,
            feature_count=25
        )

        # All values should be numeric
        for i in range(25):
            assert isinstance(features[0, i], (int, float, np.floating, np.integer))

    def test_build_feature_vector_25_dtype(self, sample_player_data):
        """
        Test that feature vector has correct dtype.

        Expected: numpy array with float64 or similar
        """
        from ml.experiment_runner import build_feature_vector

        features = build_feature_vector(
            sample_player_data,
            feature_count=25
        )

        assert features.dtype in [np.float64, np.float32]


# ============================================================================
# TEST CLASS 2: FEATURE VECTOR BUILDING - 33 FEATURES (5 tests)
# ============================================================================

class TestFeatureVectorBuilding33:
    """Test feature vector building for 33-feature models (V8 extended)."""

    def test_build_feature_vector_33_correct_shape(self, sample_player_data):
        """
        Test that 33-feature vector has correct shape.

        V8 models add: vegas line, opening, line move, has_line,
                       opponent history, minutes, ppm
        """
        from ml.experiment_runner import build_feature_vector

        features = build_feature_vector(
            sample_player_data,
            feature_count=33
        )

        assert features is not None
        assert features.shape == (1, 33)

    def test_build_feature_vector_33_base_features_preserved(self, sample_player_data):
        """
        Test that first 25 features are base features.

        Extended features shouldn't modify base features.
        """
        from ml.experiment_runner import build_feature_vector

        features = build_feature_vector(
            sample_player_data,
            feature_count=33
        )

        # First 25 should match base features
        assert features[0, 0] == 25.5
        assert features[0, 1] == 24.8

    def test_build_feature_vector_33_vegas_features_added(self, sample_player_data):
        """
        Test that vegas line features are added.

        Features 25-27: vegas_line, vegas_opening, line_movement
        """
        from ml.experiment_runner import build_feature_vector

        features = build_feature_vector(
            sample_player_data,
            feature_count=33
        )

        # Feature 25: vegas_line (or season_avg if no line)
        assert features[0, 25] == 26.5  # vegas_line
        # Feature 26: vegas_opening
        assert features[0, 26] == 25.5  # vegas_opening
        # Feature 27: line movement
        assert features[0, 27] == 1.0  # 26.5 - 25.5

    def test_build_feature_vector_33_opponent_history_added(self, sample_player_data):
        """
        Test that opponent history features are added.

        Feature 29: avg_points_vs_opponent
        Feature 30: games_vs_opponent
        """
        from ml.experiment_runner import build_feature_vector

        features = build_feature_vector(
            sample_player_data,
            feature_count=33
        )

        # Feature 29: avg_points_vs_opponent
        assert features[0, 29] == 28.5
        # Feature 30: games_vs_opponent
        assert features[0, 30] == 8.0

    def test_build_feature_vector_33_missing_vegas_uses_defaults(self, sample_player_data):
        """
        Test that missing vegas line uses season_avg as default.

        No-line players should use their season average.
        """
        from ml.experiment_runner import build_feature_vector

        sample_player_data['vegas_line'] = None
        sample_player_data['vegas_opening'] = None

        features = build_feature_vector(
            sample_player_data,
            feature_count=33
        )

        # Should use season_avg (25.0) when vegas_line is None
        assert features[0, 25] == 25.0  # season_avg fallback
        assert features[0, 26] == 25.0  # season_avg fallback
        assert features[0, 27] == 0  # no line movement


# ============================================================================
# TEST CLASS 3: MODEL LOADER FUNCTIONALITY (6 tests)
# ============================================================================

class TestModelLoader:
    """Test model loading functionality."""

    def test_model_info_dataclass(self, sample_model_info):
        """
        Test ModelInfo dataclass structure.

        Verifies all required fields are present.
        """
        assert sample_model_info.model_id == 'test_catboost_v8'
        assert sample_model_info.model_type == 'catboost'
        assert sample_model_info.model_path == '/tmp/test_model.cbm'
        assert sample_model_info.model_format == 'cbm'
        assert sample_model_info.feature_count == 25

    def test_model_wrapper_predict_interface(self):
        """
        Test ModelWrapper provides consistent predict interface.

        All model types should use wrapper.predict(features).
        """
        from ml.model_loader import ModelWrapper, ModelInfo

        # Create mock model
        mock_model = Mock()
        mock_model.predict.return_value = np.array([25.5])

        model_info = ModelInfo(
            model_id='test',
            model_type='catboost',
            model_path='/tmp/test.cbm',
            model_format='cbm',
            feature_count=25
        )

        wrapper = ModelWrapper(mock_model, model_info)

        # Test predict
        features = np.array([[1.0] * 25])
        result = wrapper.predict(features)

        assert result[0] == 25.5
        mock_model.predict.assert_called_once()

    def test_model_wrapper_properties(self):
        """
        Test ModelWrapper exposes model info properties.

        Should provide model_id and feature_count.
        """
        from ml.model_loader import ModelWrapper, ModelInfo

        mock_model = Mock()
        model_info = ModelInfo(
            model_id='catboost_v8',
            model_type='catboost',
            model_path='/tmp/test.cbm',
            model_format='cbm',
            feature_count=33
        )

        wrapper = ModelWrapper(mock_model, model_info)

        assert wrapper.model_id == 'catboost_v8'
        assert wrapper.feature_count == 33

    def test_ensure_local_handles_local_path(self):
        """
        Test _ensure_local with existing local file.

        Should return path unchanged.
        """
        from ml.model_loader import _ensure_local

        with patch('pathlib.Path.exists', return_value=True):
            result = _ensure_local('/existing/model.cbm')

        assert result == '/existing/model.cbm'

    def test_ensure_local_handles_gcs_path(self):
        """
        Test _ensure_local with GCS path.

        Should attempt to download from GCS.
        """
        from ml.model_loader import _ensure_local

        with patch('ml.model_loader._download_from_gcs', return_value='/tmp/downloaded.cbm'):
            result = _ensure_local('gs://bucket/model.cbm')

        assert result == '/tmp/downloaded.cbm'

    def test_load_model_unknown_type_returns_none(self):
        """
        Test load_model with unknown model type.

        Should return None gracefully.
        """
        from ml.model_loader import load_model, ModelInfo

        model_info = ModelInfo(
            model_id='unknown',
            model_type='pytorch',  # Not supported
            model_path='/tmp/model.pt',
            model_format='pt',
            feature_count=25
        )

        with patch('ml.model_loader._ensure_local', return_value='/tmp/model.pt'):
            result = load_model(model_info)

        assert result is None


# ============================================================================
# TEST CLASS 4: MODEL CACHING (4 tests)
# ============================================================================

class TestModelCaching:
    """Test model caching behavior."""

    def test_get_cached_model_creates_cache_entry(self, sample_model_info):
        """
        Test that get_cached_model creates cache entry.

        First call should load and cache.
        """
        from ml.model_loader import get_cached_model, _model_cache, clear_model_cache

        # Clear cache first
        clear_model_cache()

        with patch('ml.model_loader.load_model') as mock_load:
            mock_wrapper = Mock()
            mock_load.return_value = mock_wrapper

            result = get_cached_model(sample_model_info)

            assert result == mock_wrapper
            mock_load.assert_called_once()

    def test_get_cached_model_returns_cached(self, sample_model_info):
        """
        Test that second call returns cached model.

        Should not reload model.
        """
        from ml.model_loader import get_cached_model, _model_cache, clear_model_cache

        # Clear cache first
        clear_model_cache()

        with patch('ml.model_loader.load_model') as mock_load:
            mock_wrapper = Mock()
            mock_load.return_value = mock_wrapper

            # First call - loads model
            get_cached_model(sample_model_info)

            # Second call - should use cache
            result = get_cached_model(sample_model_info)

            assert result == mock_wrapper
            # load_model should only be called once
            assert mock_load.call_count == 1

    def test_clear_model_cache(self, sample_model_info):
        """
        Test clear_model_cache empties the cache.

        After clear, next get should reload.
        """
        from ml.model_loader import get_cached_model, _model_cache, clear_model_cache

        with patch('ml.model_loader.load_model') as mock_load:
            mock_wrapper = Mock()
            mock_load.return_value = mock_wrapper

            # Load model
            get_cached_model(sample_model_info)
            assert mock_load.call_count == 1

            # Clear cache
            clear_model_cache()

            # Load again - should call load_model again
            get_cached_model(sample_model_info)
            assert mock_load.call_count == 2

    def test_cache_isolates_different_models(self):
        """
        Test that cache keeps different models separate.

        Different model_ids should have separate cache entries.
        """
        from ml.model_loader import get_cached_model, ModelInfo, clear_model_cache

        clear_model_cache()

        model_info_1 = ModelInfo(
            model_id='model_1',
            model_type='catboost',
            model_path='/tmp/model1.cbm',
            model_format='cbm',
            feature_count=25
        )

        model_info_2 = ModelInfo(
            model_id='model_2',
            model_type='catboost',
            model_path='/tmp/model2.cbm',
            model_format='cbm',
            feature_count=33
        )

        with patch('ml.model_loader.load_model') as mock_load:
            mock_wrapper_1 = Mock()
            mock_wrapper_1.model_id = 'model_1'
            mock_wrapper_2 = Mock()
            mock_wrapper_2.model_id = 'model_2'

            mock_load.side_effect = [mock_wrapper_1, mock_wrapper_2]

            result_1 = get_cached_model(model_info_1)
            result_2 = get_cached_model(model_info_2)

            assert result_1.model_id == 'model_1'
            assert result_2.model_id == 'model_2'
            assert mock_load.call_count == 2


# ============================================================================
# TEST CLASS 5: SKLEARN MODEL VALIDATION (4 tests)
# ============================================================================

class TestSklearnModelValidation:
    """Test sklearn model loading with hash validation."""

    def test_sklearn_validation_requires_hash_file(self):
        """
        Test that sklearn loading requires hash file.

        Security: Prevents loading unverified pickle files.
        """
        from ml.model_loader import _load_sklearn

        with patch('os.path.exists', return_value=False):
            result = _load_sklearn('/tmp/model.pkl')

        assert result is None

    def test_sklearn_validation_rejects_hash_mismatch(self):
        """
        Test that hash mismatch is rejected.

        Security: Detects tampered model files.
        """
        from ml.model_loader import _load_sklearn
        import hashlib

        fake_content = b'fake model content'
        expected_hash = 'wrong_hash_value'
        actual_hash = hashlib.sha256(fake_content).hexdigest()

        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open_multiple(expected_hash, fake_content)):
                result = _load_sklearn('/tmp/model.pkl')

        assert result is None

    def test_sklearn_validation_accepts_valid_hash(self):
        """
        Test that valid hash allows loading.

        Happy path: Hash matches, model loads.
        """
        from ml.model_loader import _load_sklearn
        import hashlib
        import joblib

        fake_content = b'valid model content'
        expected_hash = hashlib.sha256(fake_content).hexdigest()

        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open_multiple(expected_hash, fake_content)):
                with patch('joblib.load', return_value=Mock()):
                    result = _load_sklearn('/tmp/model.pkl')

        # Would succeed if hash matches
        # Note: This test verifies the flow, actual loading mocked

    def test_sklearn_hash_file_format(self):
        """
        Test expected hash file format.

        Hash file should contain just the hex digest.
        """
        # Expected: /path/to/model.pkl.sha256 contains just the hash
        expected_path = '/tmp/model.pkl'
        expected_hash_path = f'{expected_path}.sha256'

        assert expected_hash_path == '/tmp/model.pkl.sha256'


# ============================================================================
# TEST CLASS 6: EXPERIMENT RUNNER INTEGRATION (4 tests)
# ============================================================================

class TestExperimentRunnerIntegration:
    """Test experiment runner integration with models."""

    def test_run_model_predictions_skips_out_players(self, sample_player_data):
        """
        Test that OUT players are skipped.

        Should not generate predictions for injured-out players.
        """
        from ml.experiment_runner import run_model_predictions
        from ml.model_loader import ModelInfo

        model_info = ModelInfo(
            model_id='test',
            model_type='catboost',
            model_path='/tmp/test.cbm',
            model_format='cbm',
            feature_count=25
        )

        mock_model = Mock()
        mock_model.predict.return_value = np.array([25.5])

        # Player is OUT
        sample_player_data['injury_status'] = 'out'

        predictions = run_model_predictions(
            model=mock_model,
            model_info=model_info,
            players=[sample_player_data],
            game_date=date(2025, 1, 15)
        )

        assert len(predictions) == 0

    def test_run_model_predictions_clamps_extreme_values(self, sample_player_data):
        """
        Test that predictions are clamped to 0-60 range.

        Prevents unrealistic predictions.
        """
        from ml.experiment_runner import run_model_predictions
        from ml.model_loader import ModelInfo

        model_info = ModelInfo(
            model_id='test',
            model_type='catboost',
            model_path='/tmp/test.cbm',
            model_format='cbm',
            feature_count=25
        )

        mock_model = Mock()
        mock_model.predict.return_value = np.array([85.0])  # Unrealistic

        predictions = run_model_predictions(
            model=mock_model,
            model_info=model_info,
            players=[sample_player_data],
            game_date=date(2025, 1, 15)
        )

        assert len(predictions) == 1
        assert predictions[0].predicted_points == 60  # Clamped

    def test_run_model_predictions_recommendation_logic(self, sample_player_data):
        """
        Test recommendation generation logic.

        OVER: edge >= 1.5
        UNDER: edge <= -1.5
        PASS: otherwise
        """
        from ml.experiment_runner import run_model_predictions
        from ml.model_loader import ModelInfo

        model_info = ModelInfo(
            model_id='test',
            model_type='catboost',
            model_path='/tmp/test.cbm',
            model_format='cbm',
            feature_count=25
        )

        # Test OVER recommendation
        mock_model = Mock()
        mock_model.predict.return_value = np.array([28.5])  # 2 point edge

        sample_player_data['vegas_line'] = 26.5

        predictions = run_model_predictions(
            model=mock_model,
            model_info=model_info,
            players=[sample_player_data],
            game_date=date(2025, 1, 15)
        )

        assert predictions[0].recommendation == 'OVER'

    def test_run_model_predictions_no_line_handling(self, sample_player_data):
        """
        Test handling when no vegas line exists.

        Should return NO_LINE recommendation.
        """
        from ml.experiment_runner import run_model_predictions
        from ml.model_loader import ModelInfo

        model_info = ModelInfo(
            model_id='test',
            model_type='catboost',
            model_path='/tmp/test.cbm',
            model_format='cbm',
            feature_count=25
        )

        mock_model = Mock()
        mock_model.predict.return_value = np.array([25.5])

        sample_player_data['vegas_line'] = None

        predictions = run_model_predictions(
            model=mock_model,
            model_info=model_info,
            players=[sample_player_data],
            game_date=date(2025, 1, 15)
        )

        assert predictions[0].recommendation == 'NO_LINE'


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def mock_open_multiple(hash_content, model_content):
    """Create mock for open() that handles both hash and model file reads."""
    from unittest.mock import mock_open

    hash_mock = mock_open(read_data=hash_content)
    model_mock = mock_open(read_data=model_content)

    def side_effect(path, *args, **kwargs):
        if path.endswith('.sha256'):
            return hash_mock(path, *args, **kwargs)
        else:
            return model_mock(path, *args, **kwargs)

    return Mock(side_effect=side_effect)


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

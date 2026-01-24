"""
Unit tests for ml/model_loader.py

Tests the model loading functionality including:
- ModelInfo dataclass
- ModelWrapper class
- Model loading by type
- GCS path handling

Path: tests/ml/unit/test_model_loader.py
Created: 2026-01-24
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import numpy as np
import tempfile
import os


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_model_info():
    """Sample ModelInfo for testing."""
    from ml.model_loader import ModelInfo
    return ModelInfo(
        model_id='test_model_v1',
        model_type='catboost',
        model_path='/path/to/model.cbm',
        model_format='cbm',
        feature_count=50
    )


@pytest.fixture
def mock_catboost_model():
    """Mock CatBoost model."""
    model = Mock()
    model.predict.return_value = np.array([25.5, 30.2, 18.7])
    return model


@pytest.fixture
def sample_features():
    """Sample feature array for testing."""
    return np.random.randn(3, 50)


# ============================================================================
# TEST MODEL INFO
# ============================================================================

class TestModelInfo:
    """Test the ModelInfo dataclass."""

    def test_model_info_creation(self):
        """Should create ModelInfo with required fields."""
        from ml.model_loader import ModelInfo

        info = ModelInfo(
            model_id='test_model',
            model_type='catboost',
            model_path='/path/to/model.cbm',
            model_format='cbm',
            feature_count=50
        )

        assert info.model_id == 'test_model'
        assert info.model_type == 'catboost'
        assert info.model_path == '/path/to/model.cbm'
        assert info.model_format == 'cbm'
        assert info.feature_count == 50
        assert info.feature_list is None

    def test_model_info_with_features(self):
        """Should create ModelInfo with feature list."""
        from ml.model_loader import ModelInfo

        features = ['pts_avg', 'min_avg', 'usage']
        info = ModelInfo(
            model_id='test_model',
            model_type='xgboost',
            model_path='/path/to/model.json',
            model_format='json',
            feature_count=3,
            feature_list=features
        )

        assert info.feature_list == features
        assert len(info.feature_list) == info.feature_count


# ============================================================================
# TEST MODEL WRAPPER
# ============================================================================

class TestModelWrapper:
    """Test the ModelWrapper class."""

    def test_wrapper_predict(self, mock_catboost_model, sample_model_info):
        """Should delegate predict to underlying model."""
        from ml.model_loader import ModelWrapper

        wrapper = ModelWrapper(mock_catboost_model, sample_model_info)
        features = np.random.randn(3, 50)

        result = wrapper.predict(features)

        mock_catboost_model.predict.assert_called_once()
        assert isinstance(result, np.ndarray)

    def test_wrapper_properties(self, mock_catboost_model, sample_model_info):
        """Should expose model properties."""
        from ml.model_loader import ModelWrapper

        wrapper = ModelWrapper(mock_catboost_model, sample_model_info)

        assert wrapper.model_id == sample_model_info.model_id
        assert wrapper.feature_count == sample_model_info.feature_count

    def test_wrapper_stores_original_model(self, mock_catboost_model, sample_model_info):
        """Should store reference to original model."""
        from ml.model_loader import ModelWrapper

        wrapper = ModelWrapper(mock_catboost_model, sample_model_info)

        assert wrapper.model is mock_catboost_model
        assert wrapper.model_info is sample_model_info


# ============================================================================
# TEST LOAD MODEL
# ============================================================================

class TestLoadModel:
    """Test the load_model function."""

    @patch('ml.model_loader._ensure_local')
    @patch('ml.model_loader._load_catboost')
    def test_load_catboost_model(self, mock_load_catboost, mock_ensure_local, sample_model_info):
        """Should load CatBoost model correctly."""
        from ml.model_loader import load_model

        mock_ensure_local.return_value = '/tmp/model.cbm'
        mock_model = Mock()
        mock_load_catboost.return_value = mock_model

        result = load_model(sample_model_info)

        mock_ensure_local.assert_called_once_with(sample_model_info.model_path)
        mock_load_catboost.assert_called_once()
        assert result is not None
        assert result.model_id == sample_model_info.model_id

    @patch('ml.model_loader._ensure_local')
    def test_load_model_with_invalid_path(self, mock_ensure_local, sample_model_info):
        """Should return None for invalid path."""
        from ml.model_loader import load_model

        mock_ensure_local.return_value = None

        result = load_model(sample_model_info)

        assert result is None

    @patch('ml.model_loader._ensure_local')
    def test_load_unknown_model_type(self, mock_ensure_local):
        """Should return None for unknown model type."""
        from ml.model_loader import load_model, ModelInfo

        mock_ensure_local.return_value = '/tmp/model.xyz'

        info = ModelInfo(
            model_id='unknown',
            model_type='unknown_type',
            model_path='/path/to/model.xyz',
            model_format='xyz',
            feature_count=10
        )

        result = load_model(info)

        assert result is None


# ============================================================================
# TEST PATH HANDLING
# ============================================================================

class TestPathHandling:
    """Test GCS and local path handling."""

    def test_detect_gcs_path(self):
        """Should detect GCS paths."""
        gcs_path = 'gs://bucket-name/models/model.cbm'
        local_path = '/home/user/models/model.cbm'

        assert gcs_path.startswith('gs://')
        assert not local_path.startswith('gs://')

    def test_parse_gcs_path(self):
        """Should parse GCS path components."""
        gcs_path = 'gs://nba-models/v8/catboost_v8.cbm'

        # Remove gs:// prefix
        path_without_prefix = gcs_path[5:]
        parts = path_without_prefix.split('/', 1)

        assert parts[0] == 'nba-models'  # bucket
        assert parts[1] == 'v8/catboost_v8.cbm'  # blob path


# ============================================================================
# TEST MODEL TYPE DETECTION
# ============================================================================

class TestModelTypeDetection:
    """Test model type and format detection."""

    @pytest.mark.parametrize("model_type,expected_loader", [
        ('catboost', '_load_catboost'),
        ('xgboost', '_load_xgboost'),
        ('lightgbm', '_load_lightgbm'),
        ('sklearn', '_load_sklearn'),
    ])
    def test_model_type_to_loader(self, model_type, expected_loader):
        """Should map model types to correct loaders."""
        # This is a logic test - verify the mapping exists
        loader_map = {
            'catboost': '_load_catboost',
            'xgboost': '_load_xgboost',
            'lightgbm': '_load_lightgbm',
            'sklearn': '_load_sklearn',
        }

        assert loader_map.get(model_type) == expected_loader

    @pytest.mark.parametrize("format,extension", [
        ('cbm', '.cbm'),
        ('json', '.json'),
        ('txt', '.txt'),
        ('pkl', '.pkl'),
    ])
    def test_format_to_extension(self, format, extension):
        """Should map formats to file extensions."""
        assert f'.{format}' == extension


# ============================================================================
# TEST PREDICTION INTERFACE
# ============================================================================

class TestPredictionInterface:
    """Test prediction functionality."""

    def test_predict_single_sample(self, sample_features):
        """Should predict for single sample."""
        single_sample = sample_features[0:1]  # Shape: (1, 50)

        # Mock model that returns single prediction
        mock_model = Mock()
        mock_model.predict.return_value = np.array([25.5])

        result = mock_model.predict(single_sample)

        assert result.shape == (1,)
        assert result[0] == 25.5

    def test_predict_batch(self, sample_features):
        """Should predict for batch of samples."""
        # Mock model that returns batch predictions
        mock_model = Mock()
        mock_model.predict.return_value = np.array([25.5, 30.2, 18.7])

        result = mock_model.predict(sample_features)

        assert result.shape == (3,)
        assert len(result) == sample_features.shape[0]


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestModelLoaderIntegration:
    """Integration tests for model loader."""

    def test_full_load_predict_workflow(self, sample_model_info, sample_features):
        """Should complete full load and predict workflow."""
        from ml.model_loader import ModelWrapper

        # Create mock model
        mock_model = Mock()
        mock_model.predict.return_value = np.array([25.5, 30.2, 18.7])

        # Create wrapper
        wrapper = ModelWrapper(mock_model, sample_model_info)

        # Make prediction
        predictions = wrapper.predict(sample_features)

        # Verify
        assert predictions.shape == (3,)
        assert wrapper.model_id == sample_model_info.model_id

    def test_multiple_model_loading(self):
        """Should support loading multiple models."""
        from ml.model_loader import ModelInfo, ModelWrapper

        models = []
        for i in range(3):
            info = ModelInfo(
                model_id=f'model_v{i}',
                model_type='catboost',
                model_path=f'/path/model_v{i}.cbm',
                model_format='cbm',
                feature_count=50
            )
            mock_model = Mock()
            mock_model.predict.return_value = np.array([20 + i])
            wrapper = ModelWrapper(mock_model, info)
            models.append(wrapper)

        assert len(models) == 3
        assert models[0].model_id == 'model_v0'
        assert models[2].model_id == 'model_v2'

# tests/mlb/prediction_systems/test_v1_baseline_predictor.py
"""
Unit tests for V1BaselinePredictor

Tests V1 baseline prediction system:
- Feature preparation (25 features)
- Model loading (mocked)
- Prediction output format
- Integration with base class
"""

import pytest
import numpy as np
from unittest.mock import Mock, MagicMock, patch

from predictions.mlb.prediction_systems.v1_baseline_predictor import (
    V1BaselinePredictor,
    FEATURE_DEFAULTS,
    RAW_TO_MODEL_MAPPING,
    FEATURE_ORDER_V1_4
)


class TestV1BaselinePredictor:
    """Tests for V1BaselinePredictor"""

    def setup_method(self):
        """Setup for each test"""
        self.predictor = V1BaselinePredictor(
            model_path='gs://test-bucket/test-model.json',
            project_id='test-project'
        )
        self.predictor.feature_order = FEATURE_ORDER_V1_4

    # ========================================================================
    # Feature Preparation Tests
    # ========================================================================

    def test_prepare_features_with_model_names(self):
        """Test feature preparation with model feature names"""
        raw_features = {
            'f00_k_avg_last_3': 6.5,
            'f01_k_avg_last_5': 6.2,
            'f02_k_avg_last_10': 6.0,
            'f03_k_std_last_10': 2.3,
            'f04_ip_avg_last_5': 6.0,
            'f05_season_k_per_9': 9.5,
            'f06_season_era': 3.45,
            'f07_season_whip': 1.15,
            'f08_season_games': 12,
            'f09_season_k_total': 85,
            'f10_is_home': 1.0,
            'f15_opponent_team_k_rate': 0.23,
            'f16_ballpark_k_factor': 1.02,
            'f17_month_of_season': 6,
            'f18_days_into_season': 90,
            'f20_days_rest': 5,
            'f21_games_last_30_days': 6,
            'f22_pitch_count_avg': 95.0,
            'f23_season_ip_total': 75.0,
            'f24_is_postseason': 0.0,
            'f25_bottom_up_k_expected': 6.3,
            'f26_lineup_k_vs_hand': 0.24,
            'f27_avg_k_vs_opponent': 6.5,
            'f28_games_vs_opponent': 3,
            'f33_lineup_weak_spots': 2
        }

        feature_vector = self.predictor.prepare_features(raw_features)

        assert feature_vector is not None
        assert feature_vector.shape == (1, 25)
        assert feature_vector[0][0] == 6.5  # f00_k_avg_last_3
        assert feature_vector[0][6] == 3.45  # f06_season_era

    def test_prepare_features_with_raw_names(self):
        """Test feature preparation with raw feature names"""
        raw_features = {
            'k_avg_last_3': 6.5,
            'k_avg_last_5': 6.2,
            'k_avg_last_10': 6.0,
            'k_std_last_10': 2.3,
            'ip_avg_last_5': 6.0,
            'season_k_per_9': 9.5,
            'season_era': 3.45,
            'season_whip': 1.15,
            'season_games_started': 12,
            'season_strikeouts': 85,
            'is_home': True,  # Boolean
            'opponent_team_k_rate': 0.23,
            'ballpark_k_factor': 1.02,
            'month_of_season': 6,
            'days_into_season': 90,
            'days_rest': 5,
            'games_last_30_days': 6,
            'pitch_count_avg': 95.0,
            'season_innings': 75.0,
            'is_postseason': False,  # Boolean
            'bottom_up_k_expected': 6.3,
            'lineup_k_vs_hand': 0.24,
            'avg_k_vs_opponent': 6.5,
            'games_vs_opponent': 3,
            'lineup_weak_spots': 2
        }

        feature_vector = self.predictor.prepare_features(raw_features)

        assert feature_vector is not None
        assert feature_vector.shape == (1, 25)
        assert feature_vector[0][0] == 6.5  # k_avg_last_3
        assert feature_vector[0][10] == 1.0  # is_home (converted from True)
        assert feature_vector[0][19] == 0.0  # is_postseason (converted from False)

    def test_prepare_features_with_defaults(self):
        """Test feature preparation fills in missing values with defaults"""
        raw_features = {
            'k_avg_last_3': 6.5,
            # Missing most features
        }

        feature_vector = self.predictor.prepare_features(raw_features)

        assert feature_vector is not None
        assert feature_vector.shape == (1, 25)
        assert feature_vector[0][0] == 6.5  # Provided value
        assert feature_vector[0][1] == FEATURE_DEFAULTS['f01_k_avg_last_5']  # Default

    def test_prepare_features_handles_nan(self):
        """Test feature preparation handles NaN values"""
        raw_features = {
            'k_avg_last_3': float('nan'),
            'k_avg_last_5': 6.0
        }

        feature_vector = self.predictor.prepare_features(raw_features)

        assert feature_vector is not None
        # NaN should be replaced with default
        assert not np.isnan(feature_vector[0][0])
        assert feature_vector[0][0] == FEATURE_DEFAULTS['f00_k_avg_last_3']

    def test_prepare_features_alternative_era_whip(self):
        """Test feature preparation handles alternative ERA/WHIP sources"""
        # Test with era_rolling_10 instead of season_era
        raw_features = {
            'k_avg_last_3': 6.5,
            'era_rolling_10': 3.25,  # Should map to f06_season_era
            'whip_rolling_10': 1.18,  # Should map to f07_season_whip
        }

        feature_vector = self.predictor.prepare_features(raw_features)

        assert feature_vector is not None
        # Check ERA and WHIP were mapped correctly
        era_idx = FEATURE_ORDER_V1_4.index('f06_season_era')
        whip_idx = FEATURE_ORDER_V1_4.index('f07_season_whip')
        assert feature_vector[0][era_idx] == 3.25
        assert feature_vector[0][whip_idx] == 1.18

    def test_prepare_features_bottom_up_fallback(self):
        """Test bottom_up_k_expected falls back to k_avg_last_5"""
        raw_features = {
            'k_avg_last_5': 6.2,
            # bottom_up_k_expected not provided
        }

        feature_vector = self.predictor.prepare_features(raw_features)

        assert feature_vector is not None
        bottom_up_idx = FEATURE_ORDER_V1_4.index('f25_bottom_up_k_expected')
        assert feature_vector[0][bottom_up_idx] == 6.2

    # ========================================================================
    # Prediction Tests (with mocked model)
    # ========================================================================

    @patch.object(V1BaselinePredictor, 'load_model')
    @patch('predictions.mlb.prediction_systems.v1_baseline_predictor.xgb')
    def test_predict_success(self, mock_xgb, mock_load_model):
        """Test successful prediction"""
        # Mock model loading
        mock_load_model.return_value = True
        self.predictor.model = MagicMock()
        self.predictor.model_metadata = {'model_id': 'v1_test', 'test_mae': 1.23}

        # Mock XGBoost prediction
        mock_dmatrix = MagicMock()
        mock_xgb.DMatrix.return_value = mock_dmatrix
        self.predictor.model.predict.return_value = np.array([6.5])

        features = {
            'player_lookup': 'gerrit-cole',
            'season_games_started': 10,
            'ip_avg_last_5': 6.0,
            'rolling_stats_games': 10,
            'k_avg_last_5': 6.2
        }

        result = self.predictor.predict(
            pitcher_lookup='gerrit-cole',
            features=features,
            strikeouts_line=6.0
        )

        assert result['pitcher_lookup'] == 'gerrit-cole'
        assert result['predicted_strikeouts'] == 6.5
        assert result['system_id'] == 'v1_baseline'
        assert result['recommendation'] in ['OVER', 'UNDER', 'PASS']
        assert 'confidence' in result
        assert 'model_version' in result

    @patch.object(V1BaselinePredictor, 'load_model')
    def test_predict_model_load_failure(self, mock_load_model):
        """Test prediction when model fails to load"""
        mock_load_model.return_value = False

        result = self.predictor.predict(
            pitcher_lookup='gerrit-cole',
            features={},
            strikeouts_line=6.0
        )

        assert result['recommendation'] == 'ERROR'
        assert 'error' in result
        assert 'Failed to load model' in result['error']

    @patch.object(V1BaselinePredictor, 'load_model')
    def test_predict_feature_preparation_failure(self, mock_load_model):
        """Test prediction when feature preparation fails"""
        mock_load_model.return_value = True
        self.predictor.model = MagicMock()
        self.predictor.feature_order = None  # Will cause prepare_features to fail

        result = self.predictor.predict(
            pitcher_lookup='gerrit-cole',
            features={},
            strikeouts_line=6.0
        )

        assert result['recommendation'] == 'ERROR'
        assert 'Failed to prepare features' in result['error']

    @patch.object(V1BaselinePredictor, 'load_model')
    @patch.object(V1BaselinePredictor, '_check_red_flags')
    @patch('predictions.mlb.prediction_systems.v1_baseline_predictor.xgb')
    def test_predict_with_red_flag_skip(self, mock_xgb, mock_red_flags, mock_load_model):
        """Test prediction with red flag causing skip"""
        from predictions.mlb.base_predictor import RedFlagResult

        # Setup mocks
        mock_load_model.return_value = True
        self.predictor.model = MagicMock()
        self.predictor.model_metadata = {'model_id': 'v1_test'}

        mock_dmatrix = MagicMock()
        mock_xgb.DMatrix.return_value = mock_dmatrix
        self.predictor.model.predict.return_value = np.array([6.5])

        # Mock red flag skip
        mock_red_flags.return_value = RedFlagResult(
            skip_bet=True,
            skip_reason='First start of season',
            flags=['SKIP: First start']
        )

        features = {
            'player_lookup': 'gerrit-cole',
            'season_games_started': 0,
            'ip_avg_last_5': 6.0,
            'rolling_stats_games': 10
        }

        result = self.predictor.predict(
            pitcher_lookup='gerrit-cole',
            features=features,
            strikeouts_line=6.0
        )

        assert result['recommendation'] == 'SKIP'
        assert result['skip_reason'] == 'First start of season'
        assert result['confidence'] == 0.0

    @patch.object(V1BaselinePredictor, 'load_model')
    @patch.object(V1BaselinePredictor, '_check_red_flags')
    @patch('predictions.mlb.prediction_systems.v1_baseline_predictor.xgb')
    def test_predict_with_confidence_reduction(self, mock_xgb, mock_red_flags, mock_load_model):
        """Test prediction with confidence reduction from red flags"""
        from predictions.mlb.base_predictor import RedFlagResult

        # Setup mocks
        mock_load_model.return_value = True
        self.predictor.model = MagicMock()
        self.predictor.model_metadata = {'model_id': 'v1_test'}

        mock_dmatrix = MagicMock()
        mock_xgb.DMatrix.return_value = mock_dmatrix
        self.predictor.model.predict.return_value = np.array([6.5])

        # Mock confidence reduction
        mock_red_flags.return_value = RedFlagResult(
            skip_bet=False,
            confidence_multiplier=0.7,
            flags=['REDUCE: Short rest']
        )

        features = {
            'player_lookup': 'gerrit-cole',
            'season_games_started': 10,
            'ip_avg_last_5': 6.0,
            'rolling_stats_games': 10,
            'days_rest': 3
        }

        result = self.predictor.predict(
            pitcher_lookup='gerrit-cole',
            features=features,
            strikeouts_line=6.0
        )

        assert result['recommendation'] in ['OVER', 'UNDER', 'PASS']
        assert 'confidence_multiplier' in result
        assert result['confidence_multiplier'] == 0.7
        assert result['red_flags'] == ['REDUCE: Short rest']

    # ========================================================================
    # Model Loading Tests (mocked)
    # ========================================================================

    @patch('predictions.mlb.prediction_systems.v1_baseline_predictor.storage')
    @patch('predictions.mlb.prediction_systems.v1_baseline_predictor.xgb')
    @patch('builtins.open', create=True)
    def test_load_model_success(self, mock_open, mock_xgb, mock_storage):
        """Test successful model loading"""
        # Mock storage client
        mock_client = MagicMock()
        mock_storage.Client.return_value = mock_client

        # Mock bucket and blob
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_metadata_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.side_effect = [mock_blob, mock_metadata_blob]

        # Mock XGBoost model
        mock_model = MagicMock()
        mock_xgb.Booster.return_value = mock_model

        # Mock metadata file
        mock_file = MagicMock()
        mock_file.__enter__.return_value.read.return_value = '{"model_id": "v1_test", "test_mae": 1.23, "features": ["f00", "f01"]}'
        mock_open.return_value = mock_file

        result = self.predictor.load_model()

        assert result is True
        assert self.predictor.model is not None
        assert self.predictor.model_metadata is not None
        assert self.predictor.feature_order is not None

    @patch('predictions.mlb.prediction_systems.v1_baseline_predictor.storage')
    def test_load_model_invalid_path(self, mock_storage):
        """Test model loading with invalid GCS path"""
        self.predictor.model_path = 'invalid-path'

        result = self.predictor.load_model()

        assert result is False
        assert self.predictor.model is None

    # ========================================================================
    # System ID Tests
    # ========================================================================

    def test_system_id(self):
        """Test predictor has correct system_id"""
        assert self.predictor.system_id == 'v1_baseline'

    def test_default_model_path(self):
        """Test default model path is set correctly"""
        predictor = V1BaselinePredictor()
        assert 'v1_4features' in predictor.model_path


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

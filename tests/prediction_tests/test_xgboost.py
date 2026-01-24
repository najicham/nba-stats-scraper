# tests/predictions/test_xgboost.py

"""
Unit tests for XGBoost V1 Prediction System

Tests cover:
- Feature vector preparation
- Model prediction with mock model
- Confidence calculation
- Recommendation logic
- Error handling
- Integration with mock data generator

Run with: pytest tests/predictions/test_xgboost.py -v
"""

import pytest
from datetime import date
import numpy as np
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from predictions.worker.prediction_systems.xgboost_v1 import XGBoostV1
from predictions.shared.mock_xgboost_model import MockXGBoostModel, create_feature_vector
from predictions.shared.mock_data_generator import MockDataGenerator


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def xgboost_system():
    """Create XGBoost system with mock model"""
    mock_model = MockXGBoostModel(seed=42)
    return XGBoostV1(model=mock_model)


@pytest.fixture
def mock_generator():
    """Create mock data generator"""
    return MockDataGenerator(seed=42)


@pytest.fixture
def sample_features():
    """Sample feature dictionary"""
    return {
        'points_avg_last_5': 26.5,
        'points_avg_last_10': 25.8,
        'points_avg_season': 25.0,
        'points_std_last_10': 4.8,
        'minutes_avg_last_10': 35.2,
        'fatigue_score': 78.0,
        'shot_zone_mismatch_score': 4.5,
        'pace_score': 0.8,
        'usage_spike_score': 0.0,
        'referee_favorability_score': 0.0,
        'look_ahead_pressure_score': 0.0,
        'matchup_history_score': 0.0,
        'momentum_score': 0.0,
        'opponent_def_rating_last_15': 112.5,
        'opponent_pace_last_15': 102.0,
        'is_home': 0.0,
        'days_rest': 1.0,
        'back_to_back': 0.0,
        'paint_rate_last_10': 42.0,
        'mid_range_rate_last_10': 18.0,
        'three_pt_rate_last_10': 28.0,
        'assisted_rate_last_10': 68.0,
        'team_pace_last_10': 100.8,
        'team_off_rating_last_10': 117.2,
        'usage_rate_last_10': 27.5,
        'feature_quality_score': 85.0
    }


# ============================================================================
# TEST CLASS 1: Feature Vector Preparation
# ============================================================================

class TestFeatureVectorPreparation:
    """Test feature vector creation and validation"""
    
    def test_prepare_feature_vector_complete(self, xgboost_system, sample_features):
        """Test feature vector with all features present"""
        vector = xgboost_system._prepare_feature_vector(sample_features)
        
        assert vector is not None
        assert vector.shape == (1, 25)
        
        # Check first few values
        assert vector[0, 0] == 26.5  # points_last_5
        assert vector[0, 1] == 25.8  # points_last_10
        assert vector[0, 2] == 25.0  # points_season
    
    def test_prepare_feature_vector_missing_features(self, xgboost_system):
        """Test with missing features (should use defaults)"""
        minimal_features = {
            'points_avg_last_5': 25.0,
            'points_avg_last_10': 24.0
        }
        
        vector = xgboost_system._prepare_feature_vector(minimal_features)
        
        assert vector is not None
        assert vector.shape == (1, 25)
        
        # Missing features should have defaults
        assert vector[0, 5] == 70.0  # Default fatigue_score
        assert vector[0, 13] == 112.0  # Default opponent_def_rating
    
    def test_prepare_feature_vector_order(self, xgboost_system):
        """Test that features are in correct order"""
        features = {
            'points_avg_last_5': 1.0,
            'points_avg_last_10': 2.0,
            'points_avg_season': 3.0,
            'points_std_last_10': 4.0,
            'minutes_avg_last_10': 5.0
        }
        
        vector = xgboost_system._prepare_feature_vector(features)
        
        # Verify order
        assert vector[0, 0] == 1.0
        assert vector[0, 1] == 2.0
        assert vector[0, 2] == 3.0
        assert vector[0, 3] == 4.0
        assert vector[0, 4] == 5.0
    
    def test_feature_vector_no_nan(self, xgboost_system, sample_features):
        """Test that feature vector has no NaN values"""
        vector = xgboost_system._prepare_feature_vector(sample_features)
        
        assert not np.any(np.isnan(vector))
        assert not np.any(np.isinf(vector))
    
    def test_create_feature_vector_helper(self, sample_features):
        """Test helper function for creating feature vectors"""
        vector = create_feature_vector(sample_features)
        
        assert vector.shape == (25,)
        assert vector[0] == 26.5
        assert vector[1] == 25.8


# ============================================================================
# TEST CLASS 2: Mock Model Behavior
# ============================================================================

class TestMockModel:
    """Test mock XGBoost model"""
    
    def test_mock_model_predict_single(self):
        """Test prediction on single sample"""
        model = MockXGBoostModel(seed=42)
        
        features = np.array([
            26.5, 25.8, 25.0, 4.8, 35.2,  # Recent performance
            78.0, 4.5, 0.8, 0.0,           # Composite factors
            0.0, 0.0, 0.0, 0.0,            # Deferred factors
            112.5, 102.0,                   # Opponent
            0.0, 1.0, 0.0,                  # Context
            42.0, 18.0, 28.0, 68.0,        # Shot zones
            100.8, 117.2, 27.5              # Team
        ])
        
        prediction = model.predict(features)
        
        assert isinstance(prediction, np.ndarray)
        assert prediction.shape == (1,)
        assert 0 < prediction[0] < 60
    
    def test_mock_model_predict_batch(self):
        """Test prediction on multiple samples"""
        model = MockXGBoostModel(seed=42)
        
        # Create 3 samples
        features = np.array([
            [25.0] * 25,
            [20.0] * 25,
            [30.0] * 25
        ])
        
        predictions = model.predict(features)
        
        assert predictions.shape == (3,)
        assert all(0 < p < 60 for p in predictions)
    
    def test_mock_model_feature_importance(self):
        """Test feature importance retrieval"""
        model = MockXGBoostModel(seed=42)
        
        importance = model.get_feature_importance()
        
        assert isinstance(importance, dict)
        assert len(importance) == 25
        
        # Check high importance features
        assert importance[0] > 0.10  # points_last_5
        assert importance[6] > 0.10  # zone_mismatch
    
    def test_mock_model_metadata(self):
        """Test model metadata"""
        model = MockXGBoostModel(seed=42)
        
        metadata = model.get_model_metadata()
        
        assert metadata['model_type'] == 'mock_xgboost'
        assert metadata['n_features'] == 25
        assert metadata['is_mock'] is True
    
    def test_mock_model_consistency(self):
        """Test that same inputs give consistent outputs"""
        model1 = MockXGBoostModel(seed=42)
        model2 = MockXGBoostModel(seed=42)
        
        features = np.array([25.0] * 25)
        
        pred1 = model1.predict(features)
        pred2 = model2.predict(features)
        
        # Should be close (small variance is okay)
        assert abs(pred1[0] - pred2[0]) < 1.0


# ============================================================================
# TEST CLASS 3: Full Prediction
# ============================================================================

class TestFullPrediction:
    """Test complete prediction workflow"""
    
    def test_predict_success(self, xgboost_system, sample_features):
        """Test successful prediction"""
        result = xgboost_system.predict(
            player_lookup='lebron-james',
            features=sample_features,
            betting_line=25.5
        )
        
        assert result['system_id'] == 'xgboost_v1'
        assert result['predicted_points'] is not None
        assert 0 < result['predicted_points'] < 60
        assert 0 <= result['confidence_score'] <= 100
        assert result['recommendation'] in ['OVER', 'UNDER', 'PASS']
        assert result['model_type'] == 'mock'
    
    def test_predict_over_recommendation(self, xgboost_system):
        """Test OVER recommendation"""
        # Features that should predict high
        features = {
            'points_avg_last_5': 32.0,  # Hot
            'points_avg_last_10': 30.0,
            'points_avg_season': 28.0,
            'points_std_last_10': 3.5,  # Consistent
            'fatigue_score': 90.0,  # Well-rested
            'shot_zone_mismatch_score': 6.0,  # Favorable
            'is_home': 1.0,  # Home
            'back_to_back': 0.0,
            'opponent_def_rating_last_15': 120.0,  # Weak defense
            'feature_quality_score': 90.0
        }
        
        result = xgboost_system.predict(
            player_lookup='star-player',
            features=features,
            betting_line=25.5
        )
        
        # Should predict OVER
        assert result['predicted_points'] > 28.0
        assert result['confidence_score'] > 70.0
    
    def test_predict_under_recommendation(self, xgboost_system):
        """Test UNDER recommendation"""
        # Features that should predict low
        features = {
            'points_avg_last_5': 18.0,  # Cold
            'points_avg_last_10': 20.0,
            'points_avg_season': 22.0,
            'points_std_last_10': 6.5,  # Inconsistent
            'fatigue_score': 40.0,  # Fatigued
            'shot_zone_mismatch_score': -5.0,  # Unfavorable
            'is_home': 0.0,  # Away
            'back_to_back': 1.0,  # B2B
            'opponent_def_rating_last_15': 106.0,  # Elite defense
            'feature_quality_score': 75.0
        }
        
        result = xgboost_system.predict(
            player_lookup='struggling-player',
            features=features,
            betting_line=25.5
        )
        
        # Should predict low
        assert result['predicted_points'] < 23.0
    
    def test_predict_pass_no_line(self, xgboost_system, sample_features):
        """Test PASS when no betting line"""
        result = xgboost_system.predict(
            player_lookup='test-player',
            features=sample_features,
            betting_line=None
        )
        
        assert result['recommendation'] == 'PASS'
    
    def test_predict_pass_low_confidence(self, xgboost_system):
        """Test PASS with low confidence"""
        features = {
            'points_avg_last_5': 25.0,
            'points_std_last_10': 12.0,  # Very inconsistent
            'feature_quality_score': 50.0  # Low quality
        }
        
        result = xgboost_system.predict(
            player_lookup='inconsistent-player',
            features=features,
            betting_line=25.5
        )
        
        # Low confidence should PASS
        if result['confidence_score'] < 60:
            assert result['recommendation'] == 'PASS'


# ============================================================================
# TEST CLASS 4: Confidence Calculation
# ============================================================================

class TestConfidenceCalculation:
    """Test confidence score calculation"""
    
    def test_confidence_high_quality(self, xgboost_system):
        """Test high confidence with good data quality"""
        features = {
            'feature_quality_score': 95.0,  # Excellent
            'points_std_last_10': 3.5  # Very consistent
        }
        
        vector = np.array([25.0] * 25).reshape(1, -1)
        confidence = xgboost_system._calculate_confidence(features, vector)
        
        assert confidence > 85.0
    
    def test_confidence_low_quality(self, xgboost_system):
        """Test lower confidence with poor data quality"""
        features = {
            'feature_quality_score': 55.0,  # Poor
            'points_std_last_10': 10.0  # Very inconsistent
        }
        
        vector = np.array([25.0] * 25).reshape(1, -1)
        confidence = xgboost_system._calculate_confidence(features, vector)
        
        assert confidence < 80.0
    
    def test_confidence_clamped(self, xgboost_system):
        """Test that confidence is clamped to 0-100"""
        features = {
            'feature_quality_score': 100.0,
            'points_std_last_10': 1.0
        }
        
        vector = np.array([25.0] * 25).reshape(1, -1)
        confidence = xgboost_system._calculate_confidence(features, vector)
        
        assert 0 <= confidence <= 100


# ============================================================================
# TEST CLASS 5: Recommendation Logic
# ============================================================================

class TestRecommendationLogic:
    """Test recommendation generation"""
    
    def test_recommendation_strong_over(self, xgboost_system):
        """Test OVER with strong edge"""
        rec = xgboost_system._generate_recommendation(
            predicted_points=28.0,
            betting_line=24.5,  # +3.5 edge
            confidence=75.0
        )
        
        assert rec == 'OVER'
    
    def test_recommendation_strong_under(self, xgboost_system):
        """Test UNDER with strong edge"""
        rec = xgboost_system._generate_recommendation(
            predicted_points=22.0,
            betting_line=25.5,  # -3.5 edge
            confidence=75.0
        )
        
        assert rec == 'UNDER'
    
    def test_recommendation_small_edge(self, xgboost_system):
        """Test PASS with small edge"""
        rec = xgboost_system._generate_recommendation(
            predicted_points=26.0,
            betting_line=25.5,  # +0.5 edge (too small)
            confidence=75.0
        )
        
        assert rec == 'PASS'
    
    def test_recommendation_low_confidence(self, xgboost_system):
        """Test PASS with low confidence"""
        rec = xgboost_system._generate_recommendation(
            predicted_points=30.0,
            betting_line=24.5,  # Large edge
            confidence=50.0  # But low confidence
        )
        
        assert rec == 'PASS'
    
    def test_recommendation_ml_threshold(self, xgboost_system):
        """Test that ML uses 1.5 threshold (not 2.0)"""
        # Edge of 1.6 should recommend (1.5 threshold)
        rec = xgboost_system._generate_recommendation(
            predicted_points=27.1,
            betting_line=25.5,  # +1.6 edge
            confidence=75.0
        )
        
        assert rec == 'OVER'


# ============================================================================
# TEST CLASS 6: Integration with Mock Data
# ============================================================================

class TestMockDataIntegration:
    """Test integration with mock data generator"""
    
    def test_predict_with_generated_features(self, xgboost_system, mock_generator):
        """Test prediction with generated features"""
        features = mock_generator.generate_all_features(
            'test-player',
            date(2025, 1, 15),
            tier='star',
            position='SF'
        )
        
        result = xgboost_system.predict(
            player_lookup='test-player',
            features=features,
            betting_line=25.5
        )
        
        assert result['predicted_points'] is not None
        assert result['confidence_score'] > 0
    
    def test_multiple_players(self, xgboost_system, mock_generator):
        """Test predictions for multiple players"""
        players = [
            ('player-1', 'superstar', 'PG'),
            ('player-2', 'star', 'SF'),
            ('player-3', 'starter', 'C'),
            ('player-4', 'rotation', 'SG')
        ]
        
        for player_lookup, tier, position in players:
            features = mock_generator.generate_all_features(
                player_lookup,
                date(2025, 1, 15),
                tier=tier,
                position=position
            )
            
            result = xgboost_system.predict(
                player_lookup=player_lookup,
                features=features,
                betting_line=20.5
            )
            
            assert result['predicted_points'] is not None


# ============================================================================
# TEST CLASS 7: Error Handling
# ============================================================================

class TestErrorHandling:
    """Test error handling and edge cases"""
    
    def test_invalid_feature_vector(self, xgboost_system):
        """Test handling of invalid feature vector"""
        # This should trigger error in preparation
        features = {}  # Empty
        
        result = xgboost_system.predict(
            player_lookup='test-player',
            features=features,
            betting_line=25.5
        )
        
        # Should handle gracefully but won't have prediction
        assert result['system_id'] == 'xgboost_v1'
    
    def test_extreme_predictions_clamped(self, xgboost_system):
        """Test that extreme predictions are clamped"""
        features = {
            'points_avg_last_5': 50.0,
            'points_avg_last_10': 48.0,
            'points_avg_season': 45.0,
            'fatigue_score': 100.0,
            'shot_zone_mismatch_score': 10.0
        }
        
        result = xgboost_system.predict(
            player_lookup='superhuman-player',
            features=features,
            betting_line=25.5
        )
        
        # Should clamp to 0-60 range
        assert 0 <= result['predicted_points'] <= 60


# ============================================================================
# TEST CLASS 8: Model Information
# ============================================================================

class TestModelInformation:
    """Test model info retrieval"""
    
    def test_get_feature_importance(self, xgboost_system):
        """Test feature importance retrieval"""
        importance = xgboost_system.get_feature_importance()
        
        assert isinstance(importance, dict)
        assert len(importance) > 0
    
    def test_get_model_info(self, xgboost_system):
        """Test model info retrieval"""
        info = xgboost_system.get_model_info()
        
        assert info['system_id'] == 'xgboost_v1'
        assert info['model_type'] == 'mock'
        assert 'model_version' in info


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

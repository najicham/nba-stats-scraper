# tests/predictions/test_ensemble_updated.py

"""
Updated unit tests for Ensemble V1 with 4 systems

Tests cover:
- Integration with all 4 base systems
- 4-way agreement calculation
- Weighted averaging with 4 systems
- Confidence calculation
- Recommendation logic
- Error handling when systems fail

Run with: pytest tests/predictions/test_ensemble_updated.py -v
"""

import pytest
from datetime import date
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from predictions.worker.prediction_systems.ensemble_v1 import EnsembleV1
from predictions.worker.prediction_systems.moving_average_baseline import MovingAverageBaseline
from predictions.worker.prediction_systems.zone_matchup_v1 import ZoneMatchupV1
from predictions.worker.prediction_systems.similarity_balanced_v1 import SimilarityBalancedV1
from predictions.worker.prediction_systems.xgboost_v1 import XGBoostV1
from predictions.shared.mock_xgboost_model import MockXGBoostModel
from predictions.shared.mock_data_generator import MockDataGenerator


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_generator():
    """Mock data generator with fixed seed"""
    return MockDataGenerator(seed=42)


@pytest.fixture
def base_systems():
    """Create all 4 base systems"""
    moving_avg = MovingAverageBaseline()
    zone_matchup = ZoneMatchupV1()
    similarity = SimilarityBalancedV1()
    xgboost = XGBoostV1(model=MockXGBoostModel(seed=42))
    
    return moving_avg, zone_matchup, similarity, xgboost


@pytest.fixture
def ensemble_system(base_systems):
    """Create ensemble with all 4 base systems"""
    ma, zm, sim, xgb = base_systems
    return EnsembleV1(ma, zm, sim, xgb)


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


@pytest.fixture
def sample_historical_games():
    """Sample historical games for similarity system"""
    games = []
    for i in range(20):
        game = {
            'player_lookup': 'test-player',
            'game_date': date(2024, 12, 15),
            'opponent_tier': 'tier_2_average',
            'days_rest': 1,
            'is_home': False,
            'recent_form': 'normal',
            'points': 26.0 + (i % 5),
            'minutes_played': 35.0
        }
        games.append(game)
    return games


# ============================================================================
# TEST CLASS 1: Basic Ensemble Functionality
# ============================================================================

class TestBasicEnsemble:
    """Test basic ensemble operations with 4 systems"""
    
    def test_ensemble_initialization(self, ensemble_system):
        """Test ensemble initializes correctly"""
        assert ensemble_system.system_id == 'ensemble_v1'
        assert ensemble_system.version == '2.0'
        assert ensemble_system.moving_average is not None
        assert ensemble_system.zone_matchup is not None
        assert ensemble_system.similarity is not None
        assert ensemble_system.xgboost is not None
    
    def test_ensemble_predict_all_systems(
        self,
        ensemble_system,
        sample_features,
        sample_historical_games
    ):
        """Test prediction using all 4 systems"""
        pred, conf, rec, metadata = ensemble_system.predict(
            features=sample_features,
            player_lookup='test-player',
            game_date=date(2025, 1, 15),
            prop_line=25.5,
            historical_games=sample_historical_games
        )
        
        # Should return valid prediction
        assert pred is not None
        assert 0 < pred < 60
        assert 0 <= conf <= 1.0
        assert rec in ['OVER', 'UNDER', 'PASS']
        
        # Metadata should show 4 systems used (or 3 if similarity fails)
        assert metadata['systems_used'] >= 3
        assert 'agreement' in metadata
        assert 'predictions' in metadata
    
    def test_ensemble_without_historical_games(
        self,
        ensemble_system,
        sample_features
    ):
        """Test that ensemble works even without historical games (3 systems)"""
        pred, conf, rec, metadata = ensemble_system.predict(
            features=sample_features,
            player_lookup='test-player',
            game_date=date(2025, 1, 15),
            prop_line=25.5,
            historical_games=None  # No historical games
        )
        
        # Should still work with 3 systems
        assert pred is not None
        assert metadata['systems_used'] == 3  # MA, ZM, XGB (no similarity)


# ============================================================================
# TEST CLASS 2: Agreement Calculation
# ============================================================================

class TestAgreementCalculation:
    """Test 4-way agreement metrics"""
    
    def test_high_agreement(self, ensemble_system):
        """Test high agreement detection (variance < 2.0)"""
        predictions = [
            {'system': 'ma', 'prediction': 26.0, 'confidence': 80.0, 'recommendation': 'OVER'},
            {'system': 'zm', 'prediction': 26.5, 'confidence': 82.0, 'recommendation': 'OVER'},
            {'system': 'sim', 'prediction': 25.8, 'confidence': 85.0, 'recommendation': 'OVER'},
            {'system': 'xgb', 'prediction': 26.2, 'confidence': 84.0, 'recommendation': 'OVER'}
        ]
        
        agreement = ensemble_system._calculate_agreement_metrics(predictions)
        
        assert agreement['type'] == 'high'
        assert agreement['variance'] < 2.0
        assert agreement['agreement_percentage'] >= 90
    
    def test_good_agreement(self, ensemble_system):
        """Test good agreement (variance < 4.0)"""
        predictions = [
            {'system': 'ma', 'prediction': 25.0, 'confidence': 80.0, 'recommendation': 'OVER'},
            {'system': 'zm', 'prediction': 27.0, 'confidence': 82.0, 'recommendation': 'OVER'},
            {'system': 'sim', 'prediction': 26.0, 'confidence': 85.0, 'recommendation': 'OVER'},
            {'system': 'xgb', 'prediction': 28.0, 'confidence': 84.0, 'recommendation': 'OVER'}
        ]
        
        agreement = ensemble_system._calculate_agreement_metrics(predictions)
        
        assert agreement['type'] == 'good'
        assert 2.0 <= agreement['variance'] < 4.0
        assert agreement['agreement_percentage'] >= 80
    
    def test_low_agreement(self, ensemble_system):
        """Test low agreement detection"""
        predictions = [
            {'system': 'ma', 'prediction': 20.0, 'confidence': 75.0, 'recommendation': 'UNDER'},
            {'system': 'zm', 'prediction': 28.0, 'confidence': 85.0, 'recommendation': 'OVER'},
            {'system': 'sim', 'prediction': 24.0, 'confidence': 70.0, 'recommendation': 'PASS'},
            {'system': 'xgb', 'prediction': 32.0, 'confidence': 80.0, 'recommendation': 'OVER'}
        ]
        
        agreement = ensemble_system._calculate_agreement_metrics(predictions)
        
        assert agreement['type'] in ['moderate', 'low']
        assert agreement['variance'] >= 4.0


# ============================================================================
# TEST CLASS 3: Weighted Prediction
# ============================================================================

class TestWeightedPrediction:
    """Test confidence-weighted averaging with 4 systems"""
    
    def test_weighted_average_equal_confidence(self, ensemble_system):
        """Test weighted average with equal confidences"""
        predictions = [
            {'system': 'ma', 'prediction': 24.0, 'confidence': 80.0},
            {'system': 'zm', 'prediction': 26.0, 'confidence': 80.0},
            {'system': 'sim', 'prediction': 25.0, 'confidence': 80.0},
            {'system': 'xgb', 'prediction': 27.0, 'confidence': 80.0}
        ]
        
        weighted = ensemble_system._calculate_weighted_prediction(predictions)
        
        # With equal weights, should be simple average
        expected = (24.0 + 26.0 + 25.0 + 27.0) / 4
        assert abs(weighted - expected) < 0.1
    
    def test_weighted_average_different_confidence(self, ensemble_system):
        """Test weighted average with different confidences"""
        predictions = [
            {'system': 'ma', 'prediction': 24.0, 'confidence': 70.0},
            {'system': 'zm', 'prediction': 26.0, 'confidence': 90.0},  # Highest conf
            {'system': 'sim', 'prediction': 25.0, 'confidence': 75.0},
            {'system': 'xgb', 'prediction': 27.0, 'confidence': 85.0}
        ]
        
        weighted = ensemble_system._calculate_weighted_prediction(predictions)
        
        # Should be closer to high-confidence predictions (zm=26, xgb=27)
        assert 25.5 < weighted < 27.0
    
    def test_weighted_with_three_systems(self, ensemble_system):
        """Test that ensemble works with only 3 systems"""
        predictions = [
            {'system': 'ma', 'prediction': 25.0, 'confidence': 80.0},
            {'system': 'zm', 'prediction': 26.0, 'confidence': 85.0},
            {'system': 'xgb', 'prediction': 25.5, 'confidence': 82.0}
        ]
        
        weighted = ensemble_system._calculate_weighted_prediction(predictions)
        
        assert 25.0 <= weighted <= 26.0


# ============================================================================
# TEST CLASS 4: Confidence Calculation
# ============================================================================

class TestEnsembleConfidence:
    """Test ensemble confidence calculation"""
    
    def test_confidence_with_high_agreement(self, ensemble_system):
        """Test confidence boost with high agreement"""
        predictions = [
            {'system': 'ma', 'prediction': 26.0, 'confidence': 80.0, 'recommendation': 'OVER'},
            {'system': 'zm', 'prediction': 26.2, 'confidence': 82.0, 'recommendation': 'OVER'},
            {'system': 'sim', 'prediction': 25.9, 'confidence': 85.0, 'recommendation': 'OVER'},
            {'system': 'xgb', 'prediction': 26.1, 'confidence': 84.0, 'recommendation': 'OVER'}
        ]
        
        confidence = ensemble_system._calculate_ensemble_confidence(predictions)
        
        # Should have high confidence due to agreement + all 4 systems
        assert confidence > 85.0
    
    def test_confidence_with_low_agreement(self, ensemble_system):
        """Test lower confidence with disagreement"""
        predictions = [
            {'system': 'ma', 'prediction': 22.0, 'confidence': 75.0, 'recommendation': 'UNDER'},
            {'system': 'zm', 'prediction': 28.0, 'confidence': 85.0, 'recommendation': 'OVER'},
            {'system': 'sim', 'prediction': 24.0, 'confidence': 70.0, 'recommendation': 'PASS'},
            {'system': 'xgb', 'prediction': 30.0, 'confidence': 80.0, 'recommendation': 'OVER'}
        ]
        
        confidence = ensemble_system._calculate_ensemble_confidence(predictions)
        
        # Should have lower confidence due to disagreement
        assert confidence < 85.0
    
    def test_confidence_with_three_systems(self, ensemble_system):
        """Test confidence penalty when only 3 systems"""
        predictions = [
            {'system': 'ma', 'prediction': 26.0, 'confidence': 80.0, 'recommendation': 'OVER'},
            {'system': 'zm', 'prediction': 26.2, 'confidence': 82.0, 'recommendation': 'OVER'},
            {'system': 'xgb', 'prediction': 26.1, 'confidence': 84.0, 'recommendation': 'OVER'}
        ]
        
        confidence = ensemble_system._calculate_ensemble_confidence(predictions)
        
        # Should be lower than with 4 systems (no all-systems bonus)
        assert confidence < 95.0


# ============================================================================
# TEST CLASS 5: Recommendation Logic
# ============================================================================

class TestRecommendationLogic:
    """Test ensemble recommendation generation"""
    
    def test_strong_over_recommendation(self, ensemble_system):
        """Test OVER when all systems agree"""
        predictions = [
            {'system': 'ma', 'prediction': 28.0, 'confidence': 85.0, 'recommendation': 'OVER'},
            {'system': 'zm', 'prediction': 28.5, 'confidence': 88.0, 'recommendation': 'OVER'},
            {'system': 'sim', 'prediction': 27.8, 'confidence': 85.0, 'recommendation': 'OVER'},
            {'system': 'xgb', 'prediction': 28.2, 'confidence': 86.0, 'recommendation': 'OVER'}
        ]
        
        rec = ensemble_system._determine_ensemble_recommendation(
            ensemble_pred=28.1,
            prop_line=25.5,
            ensemble_conf=90.0,
            predictions=predictions
        )
        
        assert rec == 'OVER'
    
    def test_pass_on_low_confidence(self, ensemble_system):
        """Test PASS when confidence too low"""
        predictions = [
            {'system': 'ma', 'prediction': 28.0, 'confidence': 60.0, 'recommendation': 'OVER'},
            {'system': 'zm', 'prediction': 22.0, 'confidence': 55.0, 'recommendation': 'UNDER'}
        ]
        
        rec = ensemble_system._determine_ensemble_recommendation(
            ensemble_pred=25.0,
            prop_line=24.5,
            ensemble_conf=50.0,  # Too low
            predictions=predictions
        )
        
        assert rec == 'PASS'
    
    def test_pass_on_small_edge(self, ensemble_system):
        """Test PASS when edge too small"""
        predictions = [
            {'system': 'ma', 'prediction': 26.0, 'confidence': 85.0, 'recommendation': 'OVER'}
        ]
        
        rec = ensemble_system._determine_ensemble_recommendation(
            ensemble_pred=26.0,
            prop_line=25.5,  # Only 0.5 edge (< 1.5 threshold)
            ensemble_conf=85.0,
            predictions=predictions
        )
        
        assert rec == 'PASS'


# ============================================================================
# TEST CLASS 6: Integration Tests
# ============================================================================

class TestIntegration:
    """Test complete workflow with generated data"""
    
    def test_full_prediction_with_mock_data(
        self,
        ensemble_system,
        mock_generator
    ):
        """Test end-to-end prediction with generated features"""
        # Generate features
        features = mock_generator.generate_all_features(
            'lebron-james',
            date(2025, 1, 15),
            tier='star',
            position='SF'
        )
        
        # Generate historical games
        historical_games = mock_generator.generate_historical_games(
            'lebron-james',
            date(2025, 1, 15),
            num_games=30,
            tier='star'
        )
        
        # Make prediction
        pred, conf, rec, metadata = ensemble_system.predict(
            features=features,
            player_lookup='lebron-james',
            game_date=date(2025, 1, 15),
            prop_line=25.5,
            historical_games=historical_games
        )
        
        # Verify results
        assert pred is not None
        assert 0 < pred < 60
        assert 0 <= conf <= 1.0
        assert rec in ['OVER', 'UNDER', 'PASS']
        assert metadata['systems_used'] >= 3
    
    def test_multiple_players(
        self,
        ensemble_system,
        mock_generator
    ):
        """Test predictions for players of different tiers"""
        tiers = ['superstar', 'star', 'starter', 'rotation']
        
        for tier in tiers:
            features = mock_generator.generate_all_features(
                f'player-{tier}',
                date(2025, 1, 15),
                tier=tier,
                position='SF'
            )
            
            historical_games = mock_generator.generate_historical_games(
                f'player-{tier}',
                date(2025, 1, 15),
                num_games=20,
                tier=tier
            )
            
            pred, conf, rec, metadata = ensemble_system.predict(
                features=features,
                player_lookup=f'player-{tier}',
                game_date=date(2025, 1, 15),
                prop_line=20.5,
                historical_games=historical_games
            )
            
            # All should work
            assert pred is not None
            assert metadata['systems_used'] >= 2


# ============================================================================
# TEST CLASS 7: Error Handling
# ============================================================================

class TestErrorHandling:
    """Test error handling when systems fail"""
    
    def test_insufficient_systems(
        self,
        ensemble_system,
        sample_features
    ):
        """Test handling when too few systems produce predictions"""
        # With no historical games and if other systems fail,
        # ensemble should handle gracefully
        pred, conf, rec, metadata = ensemble_system.predict(
            features={},  # Empty features might cause failures
            player_lookup='test-player',
            game_date=date(2025, 1, 15),
            prop_line=25.5,
            historical_games=None
        )
        
        # Should handle gracefully (might PASS or have low confidence)
        assert rec in ['OVER', 'UNDER', 'PASS']


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

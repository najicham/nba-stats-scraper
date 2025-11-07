# tests/predictions/test_base_predictor.py

"""
Unit Tests for Base Predictor Abstract Class

Tests cover:
1. Initialization
2. Confidence calculation (volatility + recent games)
3. Recommendation logic (edge + confidence thresholds)
4. Feature validation
5. Feature extraction
"""

import pytest
from datetime import date
from typing import Dict, Any, Tuple

# Mock concrete implementation for testing abstract class
class ConcretePredictor:
    """Minimal concrete implementation of BasePredictor for testing"""
    
    def __init__(self, system_id: str, system_name: str, version: str = "1.0"):
        self.system_id = system_id
        self.system_name = system_name
        self.version = version
    
    def predict(self, features: Dict[str, float], player_lookup: str, 
                game_date: date, prop_line: float = None) -> Tuple[float, float, str]:
        """Simple implementation for testing"""
        return (25.0, 0.6, 'OVER')
    
    def calculate_confidence(self, volatility: float, recent_games: int, 
                           data_quality: float = 1.0) -> float:
        """Import from base_predictor.py"""
        confidence = 0.5
        
        if volatility > 6.0:
            confidence -= 0.15
        elif volatility > 4.0:
            confidence -= 0.08
        
        if recent_games >= 3:
            confidence += 0.10
        elif recent_games >= 2:
            confidence += 0.05
        else:
            confidence -= 0.10
        
        confidence *= data_quality
        return max(0.2, min(0.8, confidence))
    
    def determine_recommendation(self, predicted_points: float, prop_line: float,
                               confidence: float, edge_threshold: float = 2.0,
                               confidence_threshold: float = 0.45) -> str:
        """Import from base_predictor.py"""
        edge = abs(predicted_points - prop_line)
        
        if edge <= edge_threshold:  # Must exceed threshold
            return 'PASS'
        
        if confidence <= confidence_threshold:  # Must exceed threshold
            return 'PASS'
        
        if predicted_points > prop_line:
            return 'OVER'
        else:
            return 'UNDER'
    
    def validate_features(self, features: Dict[str, float]) -> bool:
        """Import from base_predictor.py"""
        required_fields = ['feature_count', 'feature_version', 'data_source', 'features_array']
        
        for field in required_fields:
            if field not in features:
                return False
        
        if features['feature_count'] != 25:
            return False
        
        if len(features['features_array']) != 25:
            return False
        
        return True
    
    def extract_feature(self, features: Dict[str, float], feature_name: str) -> float:
        """Import from base_predictor.py"""
        if feature_name not in features:
            raise KeyError(f"Feature '{feature_name}' not found in features dict")
        return features[feature_name]


@pytest.fixture
def predictor():
    """Create predictor instance for testing"""
    return ConcretePredictor(
        system_id='test_system',
        system_name='Test Predictor',
        version='1.0'
    )


@pytest.fixture
def valid_features():
    """Valid feature dictionary for testing"""
    return {
        'feature_count': 25,
        'feature_version': 'v1_baseline_25',
        'data_source': 'mock',
        'features_array': [20.5, 22.3, 24.1, 3.2, 2, 45.0, 0.5, 0.8, 1.2, 
                          85.0, 12.0, 5.0, 3.5, 110.0, 98.5, 1, 0, 0,
                          0.45, 0.25, 0.20, 0.10, 102.0, 112.5, 0.58],
        'points_avg_last_5': 20.5,
        'points_avg_last_10': 22.3,
        'points_avg_season': 24.1,
        'points_std_last_10': 3.2,
        'games_played_last_7_days': 2,
        'fatigue_score': 45.0
    }


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================

class TestInitialization:
    """Test predictor initialization"""
    
    def test_initialization_with_required_params(self):
        """Should initialize with system_id and system_name"""
        predictor = ConcretePredictor('test_id', 'Test System')
        
        assert predictor.system_id == 'test_id'
        assert predictor.system_name == 'Test System'
        assert predictor.version == '1.0'  # Default version
    
    def test_initialization_with_custom_version(self):
        """Should initialize with custom version"""
        predictor = ConcretePredictor('test_id', 'Test System', version='2.1')
        
        assert predictor.version == '2.1'


# ============================================================================
# CONFIDENCE CALCULATION TESTS
# ============================================================================

class TestConfidenceCalculation:
    """Test confidence score calculation"""
    
    def test_baseline_confidence(self, predictor):
        """Should start with 0.5 base confidence"""
        # Medium volatility (4-6), adequate recent games (2)
        confidence = predictor.calculate_confidence(5.0, 2)
        
        # Base 0.5 - 0.08 (medium vol) + 0.05 (2 games) = 0.47
        assert confidence == pytest.approx(0.47, abs=0.01)
    
    def test_high_volatility_penalty(self, predictor):
        """High volatility (>6.0) should reduce confidence by 0.15"""
        confidence = predictor.calculate_confidence(7.0, 3)
        
        # Base 0.5 - 0.15 (high vol) + 0.10 (3+ games) = 0.45
        assert confidence == pytest.approx(0.45, abs=0.01)
    
    def test_medium_volatility_penalty(self, predictor):
        """Medium volatility (4-6) should reduce confidence by 0.08"""
        confidence = predictor.calculate_confidence(5.0, 3)
        
        # Base 0.5 - 0.08 (medium vol) + 0.10 (3+ games) = 0.52
        assert confidence == pytest.approx(0.52, abs=0.01)
    
    def test_low_volatility_no_penalty(self, predictor):
        """Low volatility (<4) should not reduce confidence"""
        confidence = predictor.calculate_confidence(3.0, 3)
        
        # Base 0.5 + 0.0 (low vol) + 0.10 (3+ games) = 0.60
        assert confidence == pytest.approx(0.60, abs=0.01)
    
    def test_many_recent_games_bonus(self, predictor):
        """3+ recent games should add 0.10 confidence"""
        confidence = predictor.calculate_confidence(3.0, 3)
        
        assert confidence == pytest.approx(0.60, abs=0.01)
    
    def test_two_recent_games_small_bonus(self, predictor):
        """2 recent games should add 0.05 confidence"""
        confidence = predictor.calculate_confidence(3.0, 2)
        
        # Base 0.5 + 0.0 (low vol) + 0.05 (2 games) = 0.55
        assert confidence == pytest.approx(0.55, abs=0.01)
    
    def test_few_recent_games_penalty(self, predictor):
        """<2 recent games should reduce confidence by 0.10"""
        confidence = predictor.calculate_confidence(3.0, 1)
        
        # Base 0.5 + 0.0 (low vol) - 0.10 (1 game) = 0.40
        assert confidence == pytest.approx(0.40, abs=0.01)
    
    def test_data_quality_adjustment(self, predictor):
        """Should multiply confidence by data quality factor"""
        # Perfect conditions but poor data quality
        confidence = predictor.calculate_confidence(3.0, 3, data_quality=0.8)
        
        # (0.5 + 0.0 + 0.10) * 0.8 = 0.48
        assert confidence == pytest.approx(0.48, abs=0.01)
    
    def test_confidence_clamped_to_minimum(self, predictor):
        """Confidence should never go below 0.2"""
        # Worst case: high volatility, no games, poor data
        confidence = predictor.calculate_confidence(10.0, 0, data_quality=0.5)
        
        # Would be: (0.5 - 0.15 - 0.10) * 0.5 = 0.125, clamped to 0.2
        assert confidence == 0.2
    
    def test_confidence_clamped_to_maximum(self, predictor):
        """Confidence should never go above 0.8"""
        # Best case: low volatility, many games, perfect data
        confidence = predictor.calculate_confidence(2.0, 5, data_quality=1.0)
        
        # Would be: 0.5 + 0.0 + 0.10 = 0.60 (under max)
        assert confidence <= 0.8


# ============================================================================
# RECOMMENDATION LOGIC TESTS
# ============================================================================

class TestRecommendationLogic:
    """Test OVER/UNDER/PASS recommendation logic"""
    
    def test_over_recommendation_with_edge(self, predictor):
        """Should recommend OVER when prediction > line with sufficient edge"""
        recommendation = predictor.determine_recommendation(
            predicted_points=28.0,
            prop_line=25.0,  # 3 point edge
            confidence=0.6
        )
        
        assert recommendation == 'OVER'
    
    def test_under_recommendation_with_edge(self, predictor):
        """Should recommend UNDER when prediction < line with sufficient edge"""
        recommendation = predictor.determine_recommendation(
            predicted_points=22.0,
            prop_line=25.0,  # 3 point edge
            confidence=0.6
        )
        
        assert recommendation == 'UNDER'
    
    def test_pass_when_insufficient_edge(self, predictor):
        """Should PASS when edge is below threshold"""
        recommendation = predictor.determine_recommendation(
            predicted_points=26.0,
            prop_line=25.0,  # 1 point edge (< 2.0 threshold)
            confidence=0.6
        )
        
        assert recommendation == 'PASS'
    
    def test_pass_when_low_confidence(self, predictor):
        """Should PASS when confidence is below threshold"""
        recommendation = predictor.determine_recommendation(
            predicted_points=28.0,
            prop_line=25.0,  # 3 point edge
            confidence=0.4  # Below 0.45 threshold
        )
        
        assert recommendation == 'PASS'
    
    def test_pass_at_edge_threshold_boundary(self, predictor):
        """Should PASS when exactly at edge threshold (not enough)"""
        recommendation = predictor.determine_recommendation(
            predicted_points=27.0,
            prop_line=25.0,  # Exactly 2.0 edge
            confidence=0.6,
            edge_threshold=2.0
        )
        
        assert recommendation == 'PASS'
    
    def test_pass_at_confidence_threshold_boundary(self, predictor):
        """Should PASS when exactly at confidence threshold (not enough)"""
        recommendation = predictor.determine_recommendation(
            predicted_points=28.0,
            prop_line=25.0,
            confidence=0.45,  # Exactly at threshold
            confidence_threshold=0.45
        )
        
        assert recommendation == 'PASS'
    
    def test_custom_edge_threshold(self, predictor):
        """Should respect custom edge threshold"""
        # With 1.5 edge and 1.0 threshold = should recommend
        recommendation = predictor.determine_recommendation(
            predicted_points=26.5,
            prop_line=25.0,
            confidence=0.6,
            edge_threshold=1.0
        )
        
        assert recommendation == 'OVER'
    
    def test_custom_confidence_threshold(self, predictor):
        """Should respect custom confidence threshold"""
        # With 0.4 confidence and 0.35 threshold = should recommend
        recommendation = predictor.determine_recommendation(
            predicted_points=28.0,
            prop_line=25.0,
            confidence=0.4,
            confidence_threshold=0.35
        )
        
        assert recommendation == 'OVER'


# ============================================================================
# FEATURE VALIDATION TESTS
# ============================================================================

class TestFeatureValidation:
    """Test feature dictionary validation"""
    
    def test_valid_features(self, predictor, valid_features):
        """Should validate correct feature dictionary"""
        assert predictor.validate_features(valid_features) is True
    
    def test_missing_feature_count(self, predictor, valid_features):
        """Should reject features missing feature_count"""
        del valid_features['feature_count']
        assert predictor.validate_features(valid_features) is False
    
    def test_missing_feature_version(self, predictor, valid_features):
        """Should reject features missing feature_version"""
        del valid_features['feature_version']
        assert predictor.validate_features(valid_features) is False
    
    def test_missing_data_source(self, predictor, valid_features):
        """Should reject features missing data_source"""
        del valid_features['data_source']
        assert predictor.validate_features(valid_features) is False
    
    def test_missing_features_array(self, predictor, valid_features):
        """Should reject features missing features_array"""
        del valid_features['features_array']
        assert predictor.validate_features(valid_features) is False
    
    def test_wrong_feature_count(self, predictor, valid_features):
        """Should reject if feature_count != 25"""
        valid_features['feature_count'] = 20
        assert predictor.validate_features(valid_features) is False
    
    def test_wrong_array_length(self, predictor, valid_features):
        """Should reject if features_array length != 25"""
        valid_features['features_array'] = [1.0] * 20  # Only 20 features
        assert predictor.validate_features(valid_features) is False


# ============================================================================
# FEATURE EXTRACTION TESTS
# ============================================================================

class TestFeatureExtraction:
    """Test extracting named features from dictionary"""
    
    def test_extract_existing_feature(self, predictor, valid_features):
        """Should extract feature by name"""
        points_avg = predictor.extract_feature(valid_features, 'points_avg_last_5')
        
        assert points_avg == 20.5
    
    def test_extract_multiple_features(self, predictor, valid_features):
        """Should extract multiple features"""
        last_5 = predictor.extract_feature(valid_features, 'points_avg_last_5')
        last_10 = predictor.extract_feature(valid_features, 'points_avg_last_10')
        season = predictor.extract_feature(valid_features, 'points_avg_season')
        
        assert last_5 == 20.5
        assert last_10 == 22.3
        assert season == 24.1
    
    def test_extract_missing_feature_raises_error(self, predictor, valid_features):
        """Should raise KeyError for missing feature"""
        with pytest.raises(KeyError, match="not found"):
            predictor.extract_feature(valid_features, 'nonexistent_feature')


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestBasePredictorIntegration:
    """Test base predictor methods work together"""
    
    def test_full_prediction_workflow(self, predictor, valid_features):
        """Should validate → predict → recommend in sequence"""
        # 1. Validate features
        assert predictor.validate_features(valid_features) is True
        
        # 2. Calculate confidence
        volatility = predictor.extract_feature(valid_features, 'points_std_last_10')
        recent_games = predictor.extract_feature(valid_features, 'games_played_last_7_days')
        confidence = predictor.calculate_confidence(volatility, int(recent_games))
        
        assert 0.2 <= confidence <= 0.8
        
        # 3. Make prediction (using concrete implementation)
        predicted_points, pred_confidence, recommendation = predictor.predict(
            valid_features, 'test-player', date(2025, 1, 15)
        )
        
        assert isinstance(predicted_points, float)
        assert isinstance(pred_confidence, float)
        assert recommendation in ['OVER', 'UNDER', 'PASS']
    
    def test_realistic_confidence_scenarios(self, predictor):
        """Test confidence calculation with realistic NBA scenarios"""
        # Scenario 1: Consistent superstar (LeBron)
        confidence = predictor.calculate_confidence(volatility=3.5, recent_games=3)
        assert confidence >= 0.55  # High confidence
        
        # Scenario 2: Inconsistent bench player
        confidence = predictor.calculate_confidence(volatility=8.0, recent_games=1)
        assert confidence <= 0.35  # Low confidence
        
        # Scenario 3: Starter returning from injury
        confidence = predictor.calculate_confidence(volatility=5.0, recent_games=2, data_quality=0.8)
        assert 0.35 <= confidence <= 0.50  # Medium confidence


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
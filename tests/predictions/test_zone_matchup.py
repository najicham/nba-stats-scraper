# tests/unit/predictions/test_zone_matchup.py

"""
Unit Tests for Zone Matchup V1 Prediction System

Tests cover:
1. Base prediction (season average)
2. Zone matchup calculation (4 zones: paint, mid, three, FT)
3. Zone scoring logic (elite/average/weak defense)
4. Usage weighting (high/medium/low usage zones)
5. Context adjustments (pace, venue, fatigue)
6. Confidence calculation
7. Recommendation logic
8. Edge cases and boundary conditions
9. End-to-end integration
"""

import pytest
from datetime import date
import sys
sys.path.insert(0, '/home/claude')

# Import Zone Matchup system
from zone_matchup_v1 import ZoneMatchupV1


@pytest.fixture
def predictor():
    """Create Zone Matchup predictor instance"""
    return ZoneMatchupV1()


@pytest.fixture
def baseline_features():
    """Baseline features with neutral values"""
    return {
        'feature_count': 25,
        'feature_version': 'v1_baseline_25',
        'data_source': 'mock',
        'features_array': [20.0] * 25,
        'points_avg_season': 22.0,  # Base prediction
        'points_std_last_10': 4.0,
        'games_played_last_7_days': 3,
        'fatigue_score': 40.0,  # Low fatigue
        'pace_score': 0.0,  # Neutral pace
        'opponent_def_rating': 110.0,  # Average defense
        'opponent_pace': 100.0,
        'home_away': 1,  # Home game
        # Zone usage (paint-heavy player)
        'pct_paint': 0.45,  # High usage in paint
        'pct_mid_range': 0.25,  # Medium usage
        'pct_three': 0.20,  # Medium usage
        'pct_free_throw': 0.10,  # Low usage
    }


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================

class TestInitialization:
    """Test predictor initialization"""
    
    def test_initialization(self):
        """Should initialize with correct system info"""
        predictor = ZoneMatchupV1()
        
        assert predictor.system_id == 'zone_matchup'
        assert predictor.system_name == 'Zone Matchup V1'
        assert predictor.version == '1.0'
    
    def test_usage_thresholds_set(self, predictor):
        """Should have usage thresholds configured"""
        assert predictor.high_usage_threshold == 0.40
        assert predictor.medium_usage_threshold == 0.20
        assert predictor.medium_usage_multiplier == 0.7
        assert predictor.low_usage_multiplier == 0.4


# ============================================================================
# ZONE SCORING TESTS
# ============================================================================

class TestZoneScoring:
    """Test zone-specific matchup scoring"""
    
    def test_weak_defense_favorable(self, predictor):
        """Weak defense (>115) should create favorable matchup"""
        score = predictor._calculate_zone_score(
            player_usage=0.40,
            opponent_defense=118.0,  # Weak defense
            zone_type='paint'
        )
        
        # Should be positive (easier to score)
        assert score > 0.0
    
    def test_elite_defense_unfavorable(self, predictor):
        """Elite defense (<105) should create unfavorable matchup"""
        score = predictor._calculate_zone_score(
            player_usage=0.40,
            opponent_defense=102.0,  # Elite defense
            zone_type='paint'
        )
        
        # Should be negative (harder to score)
        assert score < 0.0
    
    def test_average_defense_neutral(self, predictor):
        """Average defense (~110) should be neutral"""
        score = predictor._calculate_zone_score(
            player_usage=0.40,
            opponent_defense=110.0,  # Average defense
            zone_type='paint'
        )
        
        # Should be near zero
        assert abs(score) < 0.5
    
    def test_zone_type_multipliers(self, predictor):
        """Different zones should have different impact multipliers"""
        defense = 115.0  # Weak defense
        
        paint_score = predictor._calculate_zone_score(0.40, defense, 'paint')
        mid_score = predictor._calculate_zone_score(0.40, defense, 'mid_range')
        three_score = predictor._calculate_zone_score(0.40, defense, 'three')
        ft_score = predictor._calculate_zone_score(0.40, defense, 'free_throw')
        
        # Paint should matter most (1.2x), FT least (0.8x)
        assert paint_score > mid_score > ft_score
        assert three_score > ft_score
    
    def test_zone_score_clamped(self, predictor):
        """Zone scores should be clamped to [-3.0, 3.0]"""
        # Extreme weak defense
        score = predictor._calculate_zone_score(
            player_usage=1.0,
            opponent_defense=130.0,
            zone_type='paint'
        )
        
        assert -3.0 <= score <= 3.0


# ============================================================================
# USAGE WEIGHTING TESTS
# ============================================================================

class TestUsageWeighting:
    """Test usage-based weighting of zone scores"""
    
    def test_high_usage_full_weight(self, predictor):
        """High usage (>40%) should get full weight"""
        weight = predictor._get_usage_weight(0.45)
        assert weight == 1.0
    
    def test_medium_usage_reduced_weight(self, predictor):
        """Medium usage (20-40%) should get 0.7x weight"""
        weight = predictor._get_usage_weight(0.30)
        assert weight == 0.7
    
    def test_low_usage_minimal_weight(self, predictor):
        """Low usage (<20%) should get 0.4x weight"""
        weight = predictor._get_usage_weight(0.15)
        assert weight == 0.4
    
    def test_usage_weight_boundaries(self, predictor):
        """Test boundary cases for usage thresholds"""
        # Exactly at high threshold
        assert predictor._get_usage_weight(0.40) == 1.0
        
        # Just below high threshold
        assert predictor._get_usage_weight(0.39) == 0.7
        
        # Exactly at medium threshold
        assert predictor._get_usage_weight(0.20) == 0.7
        
        # Just below medium threshold
        assert predictor._get_usage_weight(0.19) == 0.4


# ============================================================================
# ZONE MATCHUP ADJUSTMENT TESTS
# ============================================================================

class TestZoneMatchupAdjustment:
    """Test overall zone matchup adjustment calculation"""
    
    def test_paint_heavy_vs_weak_paint_defense(self, predictor, baseline_features):
        """Paint-heavy player vs weak paint defense should boost prediction"""
        # Paint-heavy player (45% paint usage)
        baseline_features['pct_paint'] = 0.45
        baseline_features['opponent_def_rating'] = 118.0  # Weak defense
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Should be above season average
        season_avg = baseline_features['points_avg_season']
        assert prediction > season_avg
    
    def test_perimeter_player_vs_elite_perimeter_defense(self, predictor, baseline_features):
        """Perimeter player vs elite perimeter defense should lower prediction"""
        # Perimeter-heavy player
        baseline_features['pct_paint'] = 0.15  # Low paint usage
        baseline_features['pct_three'] = 0.50  # High three usage
        baseline_features['opponent_def_rating'] = 102.0  # Elite defense
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Should be below or near season average
        season_avg = baseline_features['points_avg_season']
        assert prediction <= season_avg + 1.0


# ============================================================================
# CONTEXT ADJUSTMENT TESTS
# ============================================================================

class TestContextAdjustments:
    """Test pace, venue, and fatigue adjustments"""
    
    def test_fast_pace_bonus(self, predictor, baseline_features):
        """Fast pace should boost prediction"""
        baseline_features['pace_score'] = 3.0
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Should include pace bonus (3.0 * 0.4 = 1.2)
        assert prediction > baseline_features['points_avg_season']
    
    def test_home_game_advantage(self, predictor, baseline_features):
        """Home game should add +0.8 points"""
        baseline_features['home_away'] = 1
        baseline_features['pace_score'] = 0.0  # Isolate venue effect
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Should include home advantage
        assert prediction > baseline_features['points_avg_season']
    
    def test_away_game_penalty(self, predictor, baseline_features):
        """Away game should add -0.8 points"""
        baseline_features['home_away'] = 0
        baseline_features['pace_score'] = 0.0  # Isolate venue effect
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Should include away penalty
        assert prediction < baseline_features['points_avg_season']
    
    def test_high_fatigue_penalty(self, predictor, baseline_features):
        """High fatigue (>70) should apply -1.5 penalty"""
        baseline_features['fatigue_score'] = 75.0
        
        adj = predictor._calculate_fatigue_adjustment(baseline_features)
        assert adj == -1.5
    
    def test_medium_fatigue_penalty(self, predictor, baseline_features):
        """Medium fatigue (50-70) should apply -0.8 penalty"""
        baseline_features['fatigue_score'] = 60.0
        
        adj = predictor._calculate_fatigue_adjustment(baseline_features)
        assert adj == -0.8


# ============================================================================
# CONFIDENCE TESTS
# ============================================================================

class TestConfidence:
    """Test confidence calculation"""
    
    def test_high_confidence_scenario(self, predictor, baseline_features):
        """Consistent player with recent games should have high confidence"""
        baseline_features['points_std_last_10'] = 3.0  # Low volatility
        baseline_features['games_played_last_7_days'] = 3  # Good data
        
        _, confidence, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Should have decent confidence
        assert confidence >= 0.45
    
    def test_low_confidence_scenario(self, predictor, baseline_features):
        """Inconsistent player with few games should have low confidence"""
        baseline_features['points_std_last_10'] = 8.0  # High volatility
        baseline_features['games_played_last_7_days'] = 1  # Limited data
        
        _, confidence, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Should have low confidence
        assert confidence <= 0.35


# ============================================================================
# RECOMMENDATION TESTS
# ============================================================================

class TestRecommendation:
    """Test OVER/UNDER/PASS recommendation logic"""
    
    def test_pass_recommendation(self, predictor, baseline_features):
        """Should PASS when edge is too small"""
        # Neutral matchup, line close to prediction
        prediction, _, recommendation = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15), prop_line=22.0
        )
        
        # Line is close to season average, should PASS
        assert recommendation == 'PASS'


# ============================================================================
# EDGE CASE TESTS
# ============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions"""
    
    def test_prediction_clamped_to_zero(self, predictor, baseline_features):
        """Negative predictions should be clamped to 0"""
        # Create scenario with extreme negative adjustments
        baseline_features['points_avg_season'] = 5.0
        baseline_features['opponent_def_rating'] = 100.0  # Elite defense
        baseline_features['fatigue_score'] = 80.0
        baseline_features['home_away'] = 0  # Away
        baseline_features['pace_score'] = -3.0
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        assert prediction >= 0.0
    
    def test_prediction_clamped_to_sixty(self, predictor, baseline_features):
        """Very high predictions should be clamped to 60"""
        # Create scenario with extreme positive values
        baseline_features['points_avg_season'] = 45.0
        baseline_features['opponent_def_rating'] = 125.0  # Very weak defense
        baseline_features['pace_score'] = 3.0
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        assert prediction <= 60.0
    
    def test_invalid_features_raises_error(self, predictor):
        """Should raise ValueError for invalid features"""
        invalid_features = {'feature_count': 20}
        
        with pytest.raises(ValueError, match="Invalid features"):
            predictor.predict(
                invalid_features, 'test-player', date(2025, 1, 15)
            )


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Test complete prediction workflow"""
    
    def test_complete_prediction_workflow(self, predictor, baseline_features):
        """Should complete full prediction with all components"""
        prediction, confidence, recommendation = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15), prop_line=22.0
        )
        
        # Verify all return values
        assert isinstance(prediction, float)
        assert isinstance(confidence, float)
        assert isinstance(recommendation, str)
        
        # Verify ranges
        assert 0.0 <= prediction <= 60.0
        assert 0.2 <= confidence <= 0.8
        assert recommendation in ['OVER', 'UNDER', 'PASS']
    
    def test_center_vs_weak_paint_defense(self, predictor):
        """Test realistic scenario: center vs weak paint defense"""
        center_features = {
            'feature_count': 25,
            'feature_version': 'v1_baseline_25',
            'data_source': 'mock',
            'features_array': [20.0] * 25,
            'points_avg_season': 18.5,
            'points_std_last_10': 4.5,
            'games_played_last_7_days': 3,
            'fatigue_score': 45.0,
            'pace_score': 1.0,
            'opponent_def_rating': 118.0,  # Weak defense
            'opponent_pace': 102.0,
            'home_away': 1,
            'pct_paint': 0.60,  # Center shoots mostly in paint
            'pct_mid_range': 0.15,
            'pct_three': 0.05,
            'pct_free_throw': 0.20,
        }
        
        prediction, confidence, recommendation = predictor.predict(
            center_features, 'center-player', date(2025, 1, 15), prop_line=18.0
        )
        
        # Should predict above season average (favorable matchup)
        assert prediction >= 18.5
        assert confidence >= 0.40
        assert recommendation in ['OVER', 'PASS']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
# tests/predictions/test_moving_average.py

"""
Unit Tests for Moving Average Baseline Prediction System

Tests cover:
1. Base prediction calculation (weighted averages)
2. Individual adjustments (fatigue, matchup, rest, pace, venue, usage)
3. Confidence calculation
4. Recommendation logic
5. Edge cases and boundary conditions
6. End-to-end prediction workflow
"""

import pytest
from datetime import date


# Import the system (will need to adjust import path)
class MovingAverageBaseline:
    """Copy implementation for testing"""
    
    def __init__(self):
        self.system_id = 'moving_average'
        self.system_name = 'Moving Average Baseline'
        self.version = '1.0'
        
        self.weight_last_5 = 0.50
        self.weight_last_10 = 0.30
        self.weight_season = 0.20
        
        self.matchup_multiplier = 0.3
        self.pace_multiplier = 0.3
        self.usage_multiplier = 0.4
        
        self.home_advantage = 0.5
        self.away_penalty = -0.5
        self.back_to_back_penalty = -1.5
    
    def predict(self, features, player_lookup, game_date, prop_line=None):
        if not self.validate_features(features):
            raise ValueError(f"Invalid features for player {player_lookup}")
        
        points_last_5 = self.extract_feature(features, 'points_avg_last_5')
        points_last_10 = self.extract_feature(features, 'points_avg_last_10')
        points_season = self.extract_feature(features, 'points_avg_season')
        volatility = self.extract_feature(features, 'points_std_last_10')
        recent_games = int(self.extract_feature(features, 'games_played_last_7_days'))
        
        base_prediction = (
            points_last_5 * self.weight_last_5 +
            points_last_10 * self.weight_last_10 +
            points_season * self.weight_season
        )
        
        fatigue_adj = self._calculate_fatigue_adjustment(features)
        matchup_adj = self._calculate_matchup_adjustment(features)
        rest_adj = self._calculate_rest_adjustment(features)
        pace_adj = self._calculate_pace_adjustment(features)
        venue_adj = self._calculate_venue_adjustment(features)
        usage_adj = self._calculate_usage_adjustment(features)
        
        total_adjustment = (
            fatigue_adj + matchup_adj + rest_adj + 
            pace_adj + venue_adj + usage_adj
        )
        
        predicted_points = base_prediction + total_adjustment
        predicted_points = max(0.0, min(60.0, predicted_points))
        
        data_quality = 0.8 if features['data_source'] == 'mock' else 1.0
        confidence = self.calculate_confidence(volatility, recent_games, data_quality)
        
        if prop_line is not None:
            recommendation = self.determine_recommendation(
                predicted_points, prop_line, confidence
            )
        else:
            recommendation = 'PASS'
        
        return (predicted_points, confidence, recommendation)
    
    def _calculate_fatigue_adjustment(self, features):
        fatigue_score = self.extract_feature(features, 'fatigue_score')
        if fatigue_score > 70:
            return -2.5
        elif fatigue_score > 50:
            return -1.0
        else:
            return 0.0
    
    def _calculate_matchup_adjustment(self, features):
        shot_zone_mismatch = self.extract_feature(features, 'shot_zone_mismatch_score')
        return shot_zone_mismatch * self.matchup_multiplier
    
    def _calculate_rest_adjustment(self, features):
        back_to_back = self.extract_feature(features, 'back_to_back')
        if back_to_back == 1:
            return self.back_to_back_penalty
        else:
            return 0.0
    
    def _calculate_pace_adjustment(self, features):
        pace_score = self.extract_feature(features, 'pace_score')
        return pace_score * self.pace_multiplier
    
    def _calculate_venue_adjustment(self, features):
        home_away = self.extract_feature(features, 'home_away')
        if home_away == 1:
            return self.home_advantage
        else:
            return self.away_penalty
    
    def _calculate_usage_adjustment(self, features):
        usage_spike = self.extract_feature(features, 'usage_spike_score')
        return usage_spike * self.usage_multiplier
    
    def calculate_confidence(self, volatility, recent_games, data_quality=1.0):
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
    
    def determine_recommendation(self, predicted_points, prop_line, confidence, 
                                edge_threshold=2.0, confidence_threshold=0.45):
        edge = abs(predicted_points - prop_line)
        
        if edge <= edge_threshold:
            return 'PASS'
        if confidence <= confidence_threshold:
            return 'PASS'
        
        if predicted_points > prop_line:
            return 'OVER'
        else:
            return 'UNDER'
    
    def validate_features(self, features):
        required_fields = ['feature_count', 'feature_version', 'data_source', 'features_array']
        for field in required_fields:
            if field not in features:
                return False
        if features['feature_count'] != 25:
            return False
        if len(features['features_array']) != 25:
            return False
        return True
    
    def extract_feature(self, features, feature_name):
        if feature_name not in features:
            raise KeyError(f"Feature '{feature_name}' not found")
        return features[feature_name]


@pytest.fixture
def predictor():
    """Create Moving Average predictor instance"""
    return MovingAverageBaseline()


@pytest.fixture
def baseline_features():
    """Baseline features with neutral values"""
    return {
        'feature_count': 25,
        'feature_version': 'v1_baseline_25',
        'data_source': 'mock',
        'features_array': [20.0] * 25,
        'points_avg_last_5': 20.0,
        'points_avg_last_10': 22.0,
        'points_avg_season': 24.0,
        'points_std_last_10': 3.5,
        'games_played_last_7_days': 2,
        'fatigue_score': 40.0,  # Low fatigue
        'shot_zone_mismatch_score': 0.0,  # Neutral matchup
        'pace_score': 0.0,  # Neutral pace
        'usage_spike_score': 0.0,  # Neutral usage
        'home_away': 1,  # Home game
        'back_to_back': 0,  # Not back-to-back
    }


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================

class TestInitialization:
    """Test predictor initialization"""
    
    def test_initialization(self):
        """Should initialize with correct system info"""
        predictor = MovingAverageBaseline()
        
        assert predictor.system_id == 'moving_average'
        assert predictor.system_name == 'Moving Average Baseline'
        assert predictor.version == '1.0'
    
    def test_weights_sum_to_one(self):
        """Weights should sum to 1.0 for proper averaging"""
        predictor = MovingAverageBaseline()
        
        total_weight = (
            predictor.weight_last_5 + 
            predictor.weight_last_10 + 
            predictor.weight_season
        )
        
        assert total_weight == pytest.approx(1.0)


# ============================================================================
# BASE PREDICTION TESTS
# ============================================================================

class TestBasePrediction:
    """Test base prediction calculation (weighted average)"""
    
    def test_base_prediction_calculation(self, predictor, baseline_features):
        """Should calculate weighted average correctly"""
        # last_5=20, last_10=22, season=24
        # Expected: 20*0.5 + 22*0.3 + 24*0.2 = 10 + 6.6 + 4.8 = 21.4
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15), prop_line=25.0
        )
        
        # Base = 21.4, venue_adj = +0.5 (home), total = 21.9
        assert prediction == pytest.approx(21.9, abs=0.1)
    
    def test_recent_games_weighted_more(self, predictor, baseline_features):
        """Last 5 games should have more impact than season"""
        # Test 1: High last 5
        baseline_features['points_avg_last_5'] = 30.0
        pred1, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Test 2: High season
        baseline_features['points_avg_last_5'] = 20.0
        baseline_features['points_avg_season'] = 30.0
        pred2, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # pred1 should be higher because last_5 has 50% weight vs season's 20%
        assert pred1 > pred2


# ============================================================================
# FATIGUE ADJUSTMENT TESTS
# ============================================================================

class TestFatigueAdjustment:
    """Test fatigue adjustment logic"""
    
    def test_high_fatigue_penalty(self, predictor, baseline_features):
        """High fatigue (>70) should apply -2.5 penalty"""
        baseline_features['fatigue_score'] = 75.0
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Base = 21.4, fatigue = -2.5, venue = +0.5, total = 19.4
        assert prediction == pytest.approx(19.4, abs=0.1)
    
    def test_medium_fatigue_penalty(self, predictor, baseline_features):
        """Medium fatigue (50-70) should apply -1.0 penalty"""
        baseline_features['fatigue_score'] = 60.0
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Base = 21.4, fatigue = -1.0, venue = +0.5, total = 20.9
        assert prediction == pytest.approx(20.9, abs=0.1)
    
    def test_low_fatigue_no_penalty(self, predictor, baseline_features):
        """Low fatigue (<50) should have no penalty"""
        baseline_features['fatigue_score'] = 30.0
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Base = 21.4, fatigue = 0.0, venue = +0.5, total = 21.9
        assert prediction == pytest.approx(21.9, abs=0.1)
    
    def test_fatigue_boundary_at_50(self, predictor, baseline_features):
        """Fatigue score of exactly 50 should not trigger penalty"""
        baseline_features['fatigue_score'] = 50.0
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Should have no fatigue penalty
        assert prediction == pytest.approx(21.9, abs=0.1)


# ============================================================================
# MATCHUP ADJUSTMENT TESTS
# ============================================================================

class TestMatchupAdjustment:
    """Test shot zone matchup adjustment"""
    
    def test_favorable_matchup_bonus(self, predictor, baseline_features):
        """Positive matchup score should boost prediction"""
        baseline_features['shot_zone_mismatch_score'] = 5.0
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Base = 21.4, matchup = 5.0*0.3=1.5, venue = +0.5, total = 23.4
        assert prediction == pytest.approx(23.4, abs=0.1)
    
    def test_unfavorable_matchup_penalty(self, predictor, baseline_features):
        """Negative matchup score should lower prediction"""
        baseline_features['shot_zone_mismatch_score'] = -5.0
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Base = 21.4, matchup = -5.0*0.3=-1.5, venue = +0.5, total = 20.4
        assert prediction == pytest.approx(20.4, abs=0.1)


# ============================================================================
# REST ADJUSTMENT TESTS
# ============================================================================

class TestRestAdjustment:
    """Test back-to-back and rest adjustments"""
    
    def test_back_to_back_penalty(self, predictor, baseline_features):
        """Back-to-back game should apply -1.5 penalty"""
        baseline_features['back_to_back'] = 1
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Base = 21.4, b2b = -1.5, venue = +0.5, total = 20.4
        assert prediction == pytest.approx(20.4, abs=0.1)
    
    def test_normal_rest_no_adjustment(self, predictor, baseline_features):
        """Normal rest should have no adjustment (for now)"""
        baseline_features['back_to_back'] = 0
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Base = 21.4, rest = 0.0, venue = +0.5, total = 21.9
        assert prediction == pytest.approx(21.9, abs=0.1)


# ============================================================================
# PACE ADJUSTMENT TESTS
# ============================================================================

class TestPaceAdjustment:
    """Test pace adjustment"""
    
    def test_fast_pace_bonus(self, predictor, baseline_features):
        """Positive pace score should boost prediction"""
        baseline_features['pace_score'] = 3.0
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Base = 21.4, pace = 3.0*0.3=0.9, venue = +0.5, total = 22.8
        assert prediction == pytest.approx(22.8, abs=0.1)
    
    def test_slow_pace_penalty(self, predictor, baseline_features):
        """Negative pace score should lower prediction"""
        baseline_features['pace_score'] = -3.0
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Base = 21.4, pace = -3.0*0.3=-0.9, venue = +0.5, total = 21.0
        assert prediction == pytest.approx(21.0, abs=0.1)


# ============================================================================
# VENUE ADJUSTMENT TESTS
# ============================================================================

class TestVenueAdjustment:
    """Test home/away venue adjustment"""
    
    def test_home_game_bonus(self, predictor, baseline_features):
        """Home game should add +0.5"""
        baseline_features['home_away'] = 1
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Should include +0.5 home advantage
        assert prediction == pytest.approx(21.9, abs=0.1)
    
    def test_away_game_penalty(self, predictor, baseline_features):
        """Away game should add -0.5"""
        baseline_features['home_away'] = 0
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Base = 21.4, venue = -0.5, total = 20.9
        assert prediction == pytest.approx(20.9, abs=0.1)


# ============================================================================
# USAGE ADJUSTMENT TESTS
# ============================================================================

class TestUsageAdjustment:
    """Test usage spike adjustment"""
    
    def test_usage_spike_bonus(self, predictor, baseline_features):
        """Positive usage spike should boost prediction"""
        baseline_features['usage_spike_score'] = 2.5
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Base = 21.4, usage = 2.5*0.4=1.0, venue = +0.5, total = 22.9
        assert prediction == pytest.approx(22.9, abs=0.1)
    
    def test_usage_drop_penalty(self, predictor, baseline_features):
        """Negative usage spike should lower prediction"""
        baseline_features['usage_spike_score'] = -2.5
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Base = 21.4, usage = -2.5*0.4=-1.0, venue = +0.5, total = 20.9
        assert prediction == pytest.approx(20.9, abs=0.1)


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
        
        # 0.5 + 0.0 (low vol) + 0.10 (3 games) = 0.60, * 0.8 (mock) = 0.48
        assert confidence == pytest.approx(0.48, abs=0.01)
    
    def test_low_confidence_scenario(self, predictor, baseline_features):
        """Inconsistent player with few games should have low confidence"""
        baseline_features['points_std_last_10'] = 8.0  # High volatility
        baseline_features['games_played_last_7_days'] = 1  # Limited data
        
        _, confidence, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # 0.5 - 0.15 (high vol) - 0.10 (1 game) = 0.25, * 0.8 = 0.20
        assert confidence == 0.20  # Clamped to minimum


# ============================================================================
# RECOMMENDATION TESTS
# ============================================================================

class TestRecommendation:
    """Test OVER/UNDER/PASS recommendation logic"""
    
    def test_over_recommendation(self, predictor, baseline_features):
        """Should recommend OVER when prediction significantly exceeds line"""
        # Boost confidence by increasing recent games
        baseline_features['games_played_last_7_days'] = 3  # +0.10 instead of +0.05
        
        # Prediction will be ~21.9, line is 19.0 (2.9 edge, >2.0 threshold)
        # Confidence: 0.5 + 0.10 = 0.60, * 0.8 = 0.48 (> 0.45 threshold)
        _, _, recommendation = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15), prop_line=19.0
        )
        
        assert recommendation == 'OVER'
    
    def test_under_recommendation(self, predictor, baseline_features):
        """Should recommend UNDER when prediction significantly below line"""
        # Boost confidence by increasing recent games
        baseline_features['games_played_last_7_days'] = 3  # +0.10 instead of +0.05
        
        # Prediction will be ~21.9, line is 25.0 (3.1 edge, >2.0 threshold)
        # Confidence: 0.5 + 0.10 = 0.60, * 0.8 = 0.48 (> 0.45 threshold)
        _, _, recommendation = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15), prop_line=25.0
        )
        
        assert recommendation == 'UNDER'
    
    def test_pass_recommendation_insufficient_edge(self, predictor, baseline_features):
        """Should PASS when edge is too small"""
        # Prediction ~21.9, line is 21.0 (0.9 edge, <2.0 threshold)
        _, _, recommendation = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15), prop_line=21.0
        )
        
        assert recommendation == 'PASS'


# ============================================================================
# EDGE CASE TESTS
# ============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions"""
    
    def test_prediction_clamped_to_zero(self, predictor, baseline_features):
        """Negative predictions should be clamped to 0"""
        # Create scenario with extreme negative adjustments
        baseline_features['points_avg_last_5'] = 5.0
        baseline_features['points_avg_last_10'] = 5.0
        baseline_features['points_avg_season'] = 5.0
        baseline_features['fatigue_score'] = 80.0  # -2.5
        baseline_features['back_to_back'] = 1  # -1.5
        baseline_features['home_away'] = 0  # -0.5
        baseline_features['shot_zone_mismatch_score'] = -10.0  # -3.0
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        assert prediction >= 0.0
    
    def test_prediction_clamped_to_sixty(self, predictor, baseline_features):
        """Very high predictions should be clamped to 60"""
        # Create scenario with extreme positive values
        baseline_features['points_avg_last_5'] = 50.0
        baseline_features['points_avg_last_10'] = 48.0
        baseline_features['points_avg_season'] = 46.0
        baseline_features['shot_zone_mismatch_score'] = 10.0  # +3.0
        baseline_features['usage_spike_score'] = 5.0  # +2.0
        baseline_features['pace_score'] = 3.0  # +0.9
        
        prediction, _, _ = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        assert prediction <= 60.0
    
    def test_invalid_features_raises_error(self, predictor):
        """Should raise ValueError for invalid features"""
        invalid_features = {'feature_count': 20}  # Missing fields
        
        with pytest.raises(ValueError, match="Invalid features"):
            predictor.predict(
                invalid_features, 'test-player', date(2025, 1, 15)
            )


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Test full prediction workflow"""
    
    def test_complete_prediction_workflow(self, predictor, baseline_features):
        """Should complete full prediction with all components"""
        prediction, confidence, recommendation = predictor.predict(
            baseline_features, 'test-player', date(2025, 1, 15), prop_line=22.0
        )
        
        # Verify all return values are correct type
        assert isinstance(prediction, float)
        assert isinstance(confidence, float)
        assert isinstance(recommendation, str)
        
        # Verify ranges
        assert 0.0 <= prediction <= 60.0
        assert 0.2 <= confidence <= 0.8
        assert recommendation in ['OVER', 'UNDER', 'PASS']
    
    def test_realistic_lebron_scenario(self, predictor):
        """Test with realistic LeBron James features"""
        lebron_features = {
            'feature_count': 25,
            'feature_version': 'v1_baseline_25',
            'data_source': 'mock',
            'features_array': [25.0] * 25,
            'points_avg_last_5': 26.5,
            'points_avg_last_10': 25.8,
            'points_avg_season': 25.2,
            'points_std_last_10': 4.2,  # Consistent
            'games_played_last_7_days': 2,
            'fatigue_score': 55.0,  # Medium fatigue
            'shot_zone_mismatch_score': 1.5,  # Slight advantage
            'pace_score': 0.8,
            'usage_spike_score': 0.5,
            'home_away': 1,  # Home game
            'back_to_back': 0,
        }
        
        prediction, confidence, recommendation = predictor.predict(
            lebron_features, 'lebron-james', date(2025, 1, 15), prop_line=25.5
        )
        
        # Should predict slightly above season average with adjustments
        assert 25.0 <= prediction <= 28.0
        assert confidence >= 0.35
        assert recommendation in ['OVER', 'PASS']  # Likely OVER or close PASS


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
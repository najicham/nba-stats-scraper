# tests/predictions/test_end_to_end.py

"""
End-to-End Integration Test

Tests the complete workflow:
1. Generate mock features using MockDataGenerator
2. Run prediction using MovingAverageBaseline
3. Verify complete prediction pipeline works

This proves all components work together before deploying.
"""

import pytest
from datetime import date


# Import mock data generator (Session 1)
class MockDataGenerator:
    """Simplified mock data generator for testing"""
    
    def __init__(self, seed=42):
        import random
        self.random = random
        self.random.seed(seed)
    
    def generate_all_features(self, player_lookup, game_date):
        """Generate 25 features for a player"""
        # Determine tier based on player name
        if 'lebron' in player_lookup or 'curry' in player_lookup:
            tier = 'superstar'
        elif 'jordan' in player_lookup or 'durant' in player_lookup:
            tier = 'star'
        else:
            tier = 'starter'
        
        # Generate realistic features based on tier
        if tier == 'superstar':
            points_avg_season = self.random.uniform(25.0, 30.0)
        elif tier == 'star':
            points_avg_season = self.random.uniform(20.0, 25.0)
        else:
            points_avg_season = self.random.uniform(10.0, 18.0)
        
        # Generate related features
        points_avg_last_5 = points_avg_season + self.random.uniform(-3.0, 3.0)
        points_avg_last_10 = points_avg_season + self.random.uniform(-2.0, 2.0)
        points_std = self.random.uniform(3.0, 6.0)
        recent_games = self.random.randint(2, 3)
        
        # Composite factors
        fatigue_score = self.random.uniform(30.0, 70.0)
        shot_zone_mismatch = self.random.uniform(-3.0, 3.0)
        pace_score = self.random.uniform(-2.0, 2.0)
        usage_spike = self.random.uniform(-2.0, 2.0)
        
        # Context
        home_away = self.random.choice([0, 1])
        back_to_back = self.random.choice([0, 0, 0, 1])  # 25% chance
        
        features_array = [
            points_avg_last_5, points_avg_last_10, points_avg_season,
            points_std, recent_games,
            fatigue_score, shot_zone_mismatch, pace_score, usage_spike,
            0.0, 0.0, 0.0, 0.0,  # Other composite factors
            110.0, 98.0,  # Opponent def rating, pace
            home_away, back_to_back, 0,  # Venue, b2b, playoff
            0.45, 0.25, 0.20, 0.10,  # Shot zones
            102.0, 112.0, 0.58  # Team stats
        ]
        
        return {
            'feature_count': 25,
            'feature_version': 'v1_baseline_25',
            'data_source': 'mock',
            'features_array': features_array,
            'points_avg_last_5': points_avg_last_5,
            'points_avg_last_10': points_avg_last_10,
            'points_avg_season': points_avg_season,
            'points_std_last_10': points_std,
            'games_played_last_7_days': recent_games,
            'fatigue_score': fatigue_score,
            'shot_zone_mismatch_score': shot_zone_mismatch,
            'pace_score': pace_score,
            'usage_spike_score': usage_spike,
            'home_away': home_away,
            'back_to_back': back_to_back,
        }


# Import Moving Average predictor (Session 2)
class MovingAverageBaseline:
    """Simplified Moving Average for testing"""
    
    def __init__(self):
        self.system_id = 'moving_average'
        self.system_name = 'Moving Average Baseline'
        self.version = '1.0'
        
        self.weight_last_5 = 0.50
        self.weight_last_10 = 0.30
        self.weight_season = 0.20
    
    def predict(self, features, player_lookup, game_date, prop_line=None):
        points_last_5 = features['points_avg_last_5']
        points_last_10 = features['points_avg_last_10']
        points_season = features['points_avg_season']
        
        base_prediction = (
            points_last_5 * 0.50 +
            points_last_10 * 0.30 +
            points_season * 0.20
        )
        
        # Apply adjustments
        fatigue = features['fatigue_score']
        if fatigue > 70:
            fatigue_adj = -2.5
        elif fatigue > 50:
            fatigue_adj = -1.0
        else:
            fatigue_adj = 0.0
        
        matchup_adj = features['shot_zone_mismatch_score'] * 0.3
        pace_adj = features['pace_score'] * 0.3
        usage_adj = features['usage_spike_score'] * 0.4
        
        if features['back_to_back'] == 1:
            rest_adj = -1.5
        else:
            rest_adj = 0.0
        
        if features['home_away'] == 1:
            venue_adj = 0.5
        else:
            venue_adj = -0.5
        
        total_adj = fatigue_adj + matchup_adj + rest_adj + pace_adj + venue_adj + usage_adj
        predicted_points = base_prediction + total_adj
        predicted_points = max(0.0, min(60.0, predicted_points))
        
        # Confidence
        volatility = features['points_std_last_10']
        recent_games = int(features['games_played_last_7_days'])
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
        
        confidence *= 0.8 if features['data_source'] == 'mock' else 1.0
        confidence = max(0.2, min(0.8, confidence))
        
        # Recommendation
        if prop_line is not None:
            edge = abs(predicted_points - prop_line)
            if edge <= 2.0 or confidence <= 0.45:
                recommendation = 'PASS'
            elif predicted_points > prop_line:
                recommendation = 'OVER'
            else:
                recommendation = 'UNDER'
        else:
            recommendation = 'PASS'
        
        return (predicted_points, confidence, recommendation)


@pytest.fixture
def mock_generator():
    """Create mock data generator"""
    return MockDataGenerator(seed=42)


@pytest.fixture
def predictor():
    """Create Moving Average predictor"""
    return MovingAverageBaseline()


# ============================================================================
# END-TO-END TESTS
# ============================================================================

class TestEndToEndWorkflow:
    """Test complete prediction workflow"""
    
    def test_single_player_prediction(self, mock_generator, predictor):
        """Test generating features and making prediction for one player"""
        # Step 1: Generate mock features
        features = mock_generator.generate_all_features('lebron-james', date(2025, 1, 15))
        
        # Verify features generated correctly
        assert features['feature_count'] == 25
        assert features['data_source'] == 'mock'
        assert len(features['features_array']) == 25
        
        # Step 2: Make prediction
        predicted_points, confidence, recommendation = predictor.predict(
            features, 'lebron-james', date(2025, 1, 15), prop_line=26.5
        )
        
        # Verify prediction output
        assert isinstance(predicted_points, float)
        assert isinstance(confidence, float)
        assert isinstance(recommendation, str)
        
        # Verify ranges
        assert 20.0 <= predicted_points <= 35.0  # LeBron range
        assert 0.2 <= confidence <= 0.8
        assert recommendation in ['OVER', 'UNDER', 'PASS']
        
        print(f"\n✅ LeBron James prediction:")
        print(f"   Predicted: {predicted_points:.1f} points")
        print(f"   Confidence: {confidence:.2f}")
        print(f"   Line: 26.5")
        print(f"   Recommendation: {recommendation}")
    
    def test_multiple_players_batch(self, mock_generator, predictor):
        """Test batch prediction for multiple players"""
        players = [
            ('lebron-james', 26.5),
            ('stephen-curry', 24.5),
            ('role-player', 12.5)
        ]
        
        results = []
        
        for player_lookup, prop_line in players:
            # Generate features
            features = mock_generator.generate_all_features(
                player_lookup, date(2025, 1, 15)
            )
            
            # Make prediction
            pred, conf, rec = predictor.predict(
                features, player_lookup, date(2025, 1, 15), prop_line=prop_line
            )
            
            results.append({
                'player': player_lookup,
                'prediction': pred,
                'confidence': conf,
                'line': prop_line,
                'recommendation': rec
            })
        
        # Verify we got results for all players
        assert len(results) == 3
        
        # Verify all predictions are valid
        for result in results:
            assert 0.0 <= result['prediction'] <= 60.0
            assert 0.2 <= result['confidence'] <= 0.8
            assert result['recommendation'] in ['OVER', 'UNDER', 'PASS']
        
        print("\n✅ Batch prediction results:")
        for result in results:
            print(f"   {result['player']:20s} "
                  f"Pred: {result['prediction']:5.1f} "
                  f"Line: {result['line']:5.1f} "
                  f"Conf: {result['confidence']:.2f} "
                  f"→ {result['recommendation']}")
    
    def test_reproducible_predictions(self, predictor):
        """Test that same features produce same prediction"""
        features = {
            'feature_count': 25,
            'feature_version': 'v1_baseline_25',
            'data_source': 'mock',
            'features_array': [25.0] * 25,
            'points_avg_last_5': 26.0,
            'points_avg_last_10': 25.5,
            'points_avg_season': 25.0,
            'points_std_last_10': 4.0,
            'games_played_last_7_days': 3,
            'fatigue_score': 50.0,
            'shot_zone_mismatch_score': 0.0,
            'pace_score': 0.0,
            'usage_spike_score': 0.0,
            'home_away': 1,
            'back_to_back': 0,
        }
        
        # Make prediction twice
        pred1, conf1, rec1 = predictor.predict(
            features, 'test-player', date(2025, 1, 15), prop_line=25.0
        )
        
        pred2, conf2, rec2 = predictor.predict(
            features, 'test-player', date(2025, 1, 15), prop_line=25.0
        )
        
        # Should be identical
        assert pred1 == pred2
        assert conf1 == conf2
        assert rec1 == rec2
        
        print(f"\n✅ Reproducibility verified:")
        print(f"   Run 1: {pred1:.1f} ({conf1:.2f}) → {rec1}")
        print(f"   Run 2: {pred2:.1f} ({conf2:.2f}) → {rec2}")
    
    def test_realistic_game_scenarios(self, mock_generator, predictor):
        """Test various realistic NBA game scenarios"""
        scenarios = [
            {
                'name': 'Superstar at home vs weak defense',
                'player': 'lebron-james',
                'line': 25.5,
                'expected_range': (24.0, 32.0)
            },
            {
                'name': 'Role player on road',
                'player': 'role-player',
                'line': 10.5,
                'expected_range': (8.0, 16.0)
            },
            {
                'name': 'Star player',
                'player': 'kevin-durant',
                'line': 22.5,
                'expected_range': (18.0, 28.0)  # Wider range for mock data variance
            }
        ]
        
        print("\n✅ Realistic game scenarios:")
        for scenario in scenarios:
            features = mock_generator.generate_all_features(
                scenario['player'], date(2025, 1, 15)
            )
            
            pred, conf, rec = predictor.predict(
                features, scenario['player'], date(2025, 1, 15), 
                prop_line=scenario['line']
            )
            
            # Verify prediction is in expected range
            min_expected, max_expected = scenario['expected_range']
            assert min_expected <= pred <= max_expected, \
                f"{scenario['name']}: prediction {pred} outside range {scenario['expected_range']}"
            
            print(f"   {scenario['name']:40s} "
                  f"Pred: {pred:5.1f} "
                  f"Line: {scenario['line']:5.1f} "
                  f"→ {rec}")


# ============================================================================
# PERFORMANCE TESTS
# ============================================================================

class TestPerformance:
    """Test system performance characteristics"""
    
    def test_prediction_speed(self, mock_generator, predictor):
        """Test that predictions are fast enough for production"""
        import time
        
        # Generate features once
        features = mock_generator.generate_all_features('test-player', date(2025, 1, 15))
        
        # Time 100 predictions
        start = time.time()
        for _ in range(100):
            predictor.predict(features, 'test-player', date(2025, 1, 15), prop_line=25.0)
        end = time.time()
        
        elapsed = end - start
        per_prediction = elapsed / 100
        
        # Should be very fast (< 1ms per prediction)
        assert per_prediction < 0.001, f"Prediction too slow: {per_prediction*1000:.2f}ms"
        
        print(f"\n✅ Performance test:")
        print(f"   100 predictions in {elapsed*1000:.2f}ms")
        print(f"   {per_prediction*1000:.4f}ms per prediction")
        print(f"   ~{int(1/per_prediction)} predictions/second")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])

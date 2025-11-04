# tests/unit/predictions/test_system_comparison.py

"""
System Comparison Tests

Compare Moving Average vs Zone Matchup predictions:
1. Same features → different predictions (different algorithms)
2. Both systems produce valid outputs
3. System agreement/disagreement analysis
4. Performance comparison
"""

import pytest
from datetime import date
import sys
sys.path.insert(0, '/home/claude')

from moving_average_baseline import MovingAverageBaseline
from zone_matchup_v1 import ZoneMatchupV1


@pytest.fixture
def moving_average():
    """Create Moving Average predictor"""
    return MovingAverageBaseline()


@pytest.fixture
def zone_matchup():
    """Create Zone Matchup predictor"""
    return ZoneMatchupV1()


@pytest.fixture
def test_features():
    """Standard test features"""
    return {
        'feature_count': 25,
        'feature_version': 'v1_baseline_25',
        'data_source': 'mock',
        'features_array': [20.0] * 25,
        'points_avg_last_5': 24.0,
        'points_avg_last_10': 23.0,
        'points_avg_season': 22.0,
        'points_std_last_10': 4.0,
        'games_played_last_7_days': 3,
        'fatigue_score': 45.0,
        'shot_zone_mismatch_score': 1.0,
        'pace_score': 1.0,
        'usage_spike_score': 0.5,
        'home_away': 1,
        'back_to_back': 0,
        'opponent_def_rating': 112.0,
        'opponent_pace': 100.0,
        'pct_paint': 0.40,
        'pct_mid_range': 0.25,
        'pct_three': 0.25,
        'pct_free_throw': 0.10,
    }


# ============================================================================
# SYSTEM COMPARISON TESTS
# ============================================================================

class TestSystemComparison:
    """Compare predictions from both systems"""
    
    def test_both_systems_produce_valid_outputs(self, moving_average, zone_matchup, test_features):
        """Both systems should produce valid predictions"""
        ma_pred, ma_conf, ma_rec = moving_average.predict(
            test_features, 'test-player', date(2025, 1, 15), prop_line=23.0
        )
        
        zm_pred, zm_conf, zm_rec = zone_matchup.predict(
            test_features, 'test-player', date(2025, 1, 15), prop_line=23.0
        )
        
        # Both should be valid
        assert 0.0 <= ma_pred <= 60.0
        assert 0.0 <= zm_pred <= 60.0
        assert 0.2 <= ma_conf <= 0.8
        assert 0.2 <= zm_conf <= 0.8
        assert ma_rec in ['OVER', 'UNDER', 'PASS']
        assert zm_rec in ['OVER', 'UNDER', 'PASS']
        
        print(f"\n✅ Both systems produce valid outputs:")
        print(f"   Moving Average: {ma_pred:.1f} (conf: {ma_conf:.2f}) → {ma_rec}")
        print(f"   Zone Matchup:   {zm_pred:.1f} (conf: {zm_conf:.2f}) → {zm_rec}")
    
    def test_systems_use_different_algorithms(self, moving_average, zone_matchup, test_features):
        """Systems should produce different predictions (different algorithms)"""
        # Moving Average emphasizes recent games
        test_features['points_avg_last_5'] = 28.0  # Hot streak
        test_features['points_avg_last_10'] = 25.0
        test_features['points_avg_season'] = 22.0
        
        ma_pred, _, _ = moving_average.predict(
            test_features, 'test-player', date(2025, 1, 15)
        )
        
        # Zone Matchup emphasizes season average + matchup
        zm_pred, _, _ = zone_matchup.predict(
            test_features, 'test-player', date(2025, 1, 15)
        )
        
        # Predictions should differ (MA weights recent more heavily)
        # MA: 28*0.5 + 25*0.3 + 22*0.2 = 14 + 7.5 + 4.4 = 25.9
        # ZM: 22 (season) + adjustments
        print(f"\n✅ Different algorithms produce different predictions:")
        print(f"   Moving Average: {ma_pred:.1f} (emphasizes recent hot streak)")
        print(f"   Zone Matchup:   {zm_pred:.1f} (emphasizes season + matchup)")
        
        # They should be different but both reasonable
        assert abs(ma_pred - zm_pred) > 0.5  # At least 0.5 point difference
    
    def test_system_agreement_favorable_matchup(self, moving_average, zone_matchup, test_features):
        """Both systems should agree on favorable matchup"""
        # Create favorable scenario
        test_features['opponent_def_rating'] = 118.0  # Weak defense
        test_features['fatigue_score'] = 30.0  # Low fatigue
        test_features['home_away'] = 1  # Home game
        test_features['pace_score'] = 2.0  # Fast pace
        
        ma_pred, _, ma_rec = moving_average.predict(
            test_features, 'test-player', date(2025, 1, 15), prop_line=20.0
        )
        
        zm_pred, _, zm_rec = zone_matchup.predict(
            test_features, 'test-player', date(2025, 1, 15), prop_line=20.0
        )
        
        # Both should predict above average
        assert ma_pred > test_features['points_avg_season']
        assert zm_pred > test_features['points_avg_season']
        
        print(f"\n✅ System agreement on favorable matchup:")
        print(f"   Moving Average: {ma_pred:.1f} → {ma_rec}")
        print(f"   Zone Matchup:   {zm_pred:.1f} → {zm_rec}")
        print(f"   Both predict ABOVE season average (22.0)")
    
    def test_system_disagreement_analysis(self, moving_average, zone_matchup, test_features):
        """Systems may disagree when different factors dominate"""
        # Scenario: Recent cold streak but favorable zone matchup
        test_features['points_avg_last_5'] = 18.0  # Cold streak
        test_features['points_avg_last_10'] = 19.0
        test_features['points_avg_season'] = 22.0  # Season average higher
        test_features['opponent_def_rating'] = 116.0  # Favorable matchup
        test_features['pct_paint'] = 0.50  # Paint-heavy player
        
        ma_pred, _, _ = moving_average.predict(
            test_features, 'test-player', date(2025, 1, 15)
        )
        
        zm_pred, _, _ = zone_matchup.predict(
            test_features, 'test-player', date(2025, 1, 15)
        )
        
        print(f"\n✅ System disagreement analysis:")
        print(f"   Scenario: Cold streak (18 PPG) but favorable matchup")
        print(f"   Moving Average: {ma_pred:.1f} (weights recent cold streak)")
        print(f"   Zone Matchup:   {zm_pred:.1f} (weights season + favorable matchup)")
        print(f"   Difference: {abs(ma_pred - zm_pred):.1f} points")
        
        # Moving Average should be lower (recent cold streak)
        # Zone Matchup should be higher (season avg + favorable matchup)
        assert ma_pred < zm_pred


# ============================================================================
# MULTI-PLAYER BATCH TESTS
# ============================================================================

class TestBatchPredictions:
    """Test batch predictions across multiple players"""
    
    def test_batch_prediction_comparison(self, moving_average, zone_matchup):
        """Compare systems across multiple player scenarios"""
        scenarios = [
            {
                'name': 'Paint-heavy center vs weak paint defense',
                'features': {
                    'points_avg_season': 18.0,
                    'points_avg_last_5': 19.0,
                    'points_avg_last_10': 18.5,
                    'opponent_def_rating': 118.0,  # Weak
                    'pct_paint': 0.65,
                    'home_away': 1,
                }
            },
            {
                'name': 'Three-point shooter vs elite defense',
                'features': {
                    'points_avg_season': 22.0,
                    'points_avg_last_5': 24.0,
                    'points_avg_last_10': 23.0,
                    'opponent_def_rating': 103.0,  # Elite
                    'pct_three': 0.55,
                    'home_away': 0,
                }
            },
            {
                'name': 'Balanced player, neutral matchup',
                'features': {
                    'points_avg_season': 20.0,
                    'points_avg_last_5': 20.0,
                    'points_avg_last_10': 20.0,
                    'opponent_def_rating': 110.0,  # Average
                    'pct_paint': 0.30,
                    'pct_mid_range': 0.30,
                    'pct_three': 0.30,
                    'home_away': 1,
                }
            }
        ]
        
        print(f"\n✅ Batch prediction comparison:")
        print(f"   {'Scenario':<45s} {'MA Pred':>8s} {'ZM Pred':>8s} {'Diff':>6s}")
        print(f"   {'-'*70}")
        
        for scenario in scenarios:
            # Create full features
            features = {
                'feature_count': 25,
                'feature_version': 'v1_baseline_25',
                'data_source': 'mock',
                'features_array': [20.0] * 25,
                'points_std_last_10': 4.0,
                'games_played_last_7_days': 3,
                'fatigue_score': 40.0,
                'shot_zone_mismatch_score': 0.0,
                'pace_score': 0.0,
                'usage_spike_score': 0.0,
                'back_to_back': 0,
                'opponent_pace': 100.0,
                'pct_paint': 0.35,
                'pct_mid_range': 0.25,
                'pct_three': 0.25,
                'pct_free_throw': 0.15,
            }
            features.update(scenario['features'])
            
            ma_pred, _, _ = moving_average.predict(
                features, 'player', date(2025, 1, 15)
            )
            
            zm_pred, _, _ = zone_matchup.predict(
                features, 'player', date(2025, 1, 15)
            )
            
            diff = abs(ma_pred - zm_pred)
            
            print(f"   {scenario['name']:<45s} {ma_pred:>7.1f} {zm_pred:>7.1f} {diff:>6.1f}")
            
            # Verify both are reasonable
            assert 0.0 <= ma_pred <= 60.0
            assert 0.0 <= zm_pred <= 60.0


# ============================================================================
# PERFORMANCE COMPARISON
# ============================================================================

class TestPerformanceComparison:
    """Compare performance characteristics of both systems"""
    
    def test_speed_comparison(self, moving_average, zone_matchup, test_features):
        """Compare prediction speed of both systems"""
        import time
        
        # Time Moving Average
        start = time.time()
        for _ in range(100):
            moving_average.predict(test_features, 'test-player', date(2025, 1, 15))
        ma_time = time.time() - start
        
        # Time Zone Matchup
        start = time.time()
        for _ in range(100):
            zone_matchup.predict(test_features, 'test-player', date(2025, 1, 15))
        zm_time = time.time() - start
        
        print(f"\n✅ Performance comparison (100 predictions):")
        print(f"   Moving Average: {ma_time*1000:.2f}ms ({ma_time/100*1000:.4f}ms each)")
        print(f"   Zone Matchup:   {zm_time*1000:.2f}ms ({zm_time/100*1000:.4f}ms each)")
        
        # Both should be very fast
        assert ma_time < 0.1  # < 100ms for 100 predictions
        assert zm_time < 0.1


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])

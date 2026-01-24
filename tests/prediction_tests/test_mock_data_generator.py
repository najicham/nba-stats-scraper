# tests/predictions/test_mock_data_generator.py
"""
Unit Tests for Mock Data Generator

Tests verify:
    - Correct feature count (25 features)
    - Value ranges for all features
    - Tier-based distributions (superstars score more)
    - Position-based shot distributions (centers shoot in paint)
    - Feature array consistency
    - Reproducibility with seeds
    - Batch generation
"""

import sys
import os
# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import pytest
from datetime import date
from predictions.shared.mock_data_generator import MockDataGenerator, get_mock_features


class TestMockDataGenerator:
    """Test suite for MockDataGenerator class"""
    
    @pytest.fixture
    def generator(self):
        """Create generator with fixed seed for reproducibility"""
        return MockDataGenerator(seed=42)
    
    @pytest.fixture
    def sample_features(self, generator):
        """Generate sample features for testing"""
        return generator.generate_all_features('lebron-james', date(2025, 1, 15))
    
    # ========================================================================
    # Feature Structure Tests
    # ========================================================================
    
    def test_feature_count(self, sample_features):
        """Test that exactly 25 features are generated"""
        assert sample_features['feature_count'] == 25
        assert len(sample_features['features']) == 25
        assert len(sample_features['feature_names']) == 25
    
    def test_feature_version(self, sample_features):
        """Test correct feature version is set"""
        assert sample_features['feature_version'] == 'v1_baseline_25'
    
    def test_data_source_marked_as_mock(self, sample_features):
        """Test that data source is marked as 'mock'"""
        assert sample_features['data_source'] == 'mock'
    
    def test_required_metadata_present(self, sample_features):
        """Test that all required metadata fields are present"""
        required_fields = [
            'player_lookup',
            'game_date',
            'data_source',
            'feature_quality_score',
            'player_tier',
            'player_position'
        ]
        
        for field in required_fields:
            assert field in sample_features, f"Missing required field: {field}"
    
    def test_feature_array_matches_individual_features(self, sample_features):
        """Test that feature array values match individual feature values"""
        feature_names = sample_features['feature_names']
        feature_array = sample_features['features']
        
        for i, name in enumerate(feature_names):
            assert sample_features[name] == feature_array[i], \
                f"Mismatch for {name}: {sample_features[name]} != {feature_array[i]}"
    
    # ========================================================================
    # Feature Range Tests (Indices 0-4: Recent Performance)
    # ========================================================================
    
    def test_points_avg_last_5_range(self, sample_features):
        """Test points_avg_last_5 is in valid range"""
        value = sample_features['points_avg_last_5']
        assert 0 <= value <= 50, f"points_avg_last_5 out of range: {value}"
    
    def test_points_avg_last_10_range(self, sample_features):
        """Test points_avg_last_10 is in valid range"""
        value = sample_features['points_avg_last_10']
        assert 0 <= value <= 50, f"points_avg_last_10 out of range: {value}"
    
    def test_points_avg_season_range(self, sample_features):
        """Test points_avg_season is in valid range"""
        value = sample_features['points_avg_season']
        assert 0 <= value <= 50, f"points_avg_season out of range: {value}"
    
    def test_points_std_last_10_range(self, sample_features):
        """Test points_std_last_10 is in valid range"""
        value = sample_features['points_std_last_10']
        assert 0 <= value <= 15, f"points_std_last_10 out of range: {value}"
    
    def test_minutes_avg_last_10_range(self, sample_features):
        """Test minutes_avg_last_10 is in valid range"""
        value = sample_features['minutes_avg_last_10']
        assert 0 <= value <= 48, f"minutes_avg_last_10 out of range: {value}"
    
    # ========================================================================
    # Feature Range Tests (Indices 5-12: Composite Factors)
    # ========================================================================
    
    def test_fatigue_score_range(self, sample_features):
        """Test fatigue_score is in valid range (0-100)"""
        value = sample_features['fatigue_score']
        assert 0 <= value <= 100, f"fatigue_score out of range: {value}"
    
    def test_shot_zone_mismatch_range(self, sample_features):
        """Test shot_zone_mismatch_score is in valid range (-10 to +10)"""
        value = sample_features['shot_zone_mismatch_score']
        assert -10 <= value <= 10, f"shot_zone_mismatch_score out of range: {value}"
    
    def test_pace_score_range(self, sample_features):
        """Test pace_score is in valid range (-3 to +3)"""
        value = sample_features['pace_score']
        assert -3 <= value <= 3, f"pace_score out of range: {value}"
    
    def test_usage_spike_score_range(self, sample_features):
        """Test usage_spike_score is in valid range (-3 to +3)"""
        value = sample_features['usage_spike_score']
        assert -3 <= value <= 3, f"usage_spike_score out of range: {value}"
    
    def test_deferred_factors_are_zero(self, sample_features):
        """Test that all deferred factors are set to 0"""
        deferred_factors = [
            'referee_favorability_score',
            'look_ahead_pressure_score',
            'matchup_history_score',
            'momentum_score'
        ]
        
        for factor in deferred_factors:
            assert sample_features[factor] == 0.0, \
                f"Deferred factor {factor} should be 0, got {sample_features[factor]}"
    
    # ========================================================================
    # Feature Range Tests (Indices 13-17: Matchup Context)
    # ========================================================================
    
    def test_opponent_def_rating_range(self, sample_features):
        """Test opponent_def_rating_last_15 is in valid range"""
        value = sample_features['opponent_def_rating_last_15']
        assert 100 <= value <= 125, f"opponent_def_rating_last_15 out of range: {value}"
    
    def test_opponent_pace_range(self, sample_features):
        """Test opponent_pace_last_15 is in valid range"""
        value = sample_features['opponent_pace_last_15']
        assert 90 <= value <= 110, f"opponent_pace_last_15 out of range: {value}"
    
    def test_is_home_binary(self, sample_features):
        """Test is_home is binary (0.0 or 1.0)"""
        value = sample_features['is_home']
        assert value in [0.0, 1.0], f"is_home should be 0 or 1, got {value}"
    
    def test_days_rest_range(self, sample_features):
        """Test days_rest is in valid range"""
        value = sample_features['days_rest']
        assert 0 <= value <= 14, f"days_rest out of range: {value}"
    
    def test_back_to_back_binary(self, sample_features):
        """Test back_to_back is binary (0.0 or 1.0)"""
        value = sample_features['back_to_back']
        assert value in [0.0, 1.0], f"back_to_back should be 0 or 1, got {value}"
    
    # ========================================================================
    # Feature Range Tests (Indices 18-21: Shot Zones)
    # ========================================================================
    
    def test_paint_rate_range(self, sample_features):
        """Test paint_rate_last_10 is percentage (0-100)"""
        value = sample_features['paint_rate_last_10']
        assert 0 <= value <= 100, f"paint_rate_last_10 out of range: {value}"
    
    def test_mid_range_rate_range(self, sample_features):
        """Test mid_range_rate_last_10 is percentage (0-100)"""
        value = sample_features['mid_range_rate_last_10']
        assert 0 <= value <= 100, f"mid_range_rate_last_10 out of range: {value}"
    
    def test_three_pt_rate_range(self, sample_features):
        """Test three_pt_rate_last_10 is percentage (0-100)"""
        value = sample_features['three_pt_rate_last_10']
        assert 0 <= value <= 100, f"three_pt_rate_last_10 out of range: {value}"
    
    def test_shot_zones_sum_to_100_percent(self, sample_features):
        """Test that paint + mid + three rates sum to ~100%"""
        total = (sample_features['paint_rate_last_10'] +
                sample_features['mid_range_rate_last_10'] +
                sample_features['three_pt_rate_last_10'])
        
        # Allow 1% tolerance for rounding
        assert 99 <= total <= 101, \
            f"Shot zone rates should sum to 100%, got {total}%"
    
    def test_assisted_rate_range(self, sample_features):
        """Test assisted_rate_last_10 is percentage (0-100)"""
        value = sample_features['assisted_rate_last_10']
        assert 0 <= value <= 100, f"assisted_rate_last_10 out of range: {value}"
    
    # ========================================================================
    # Feature Range Tests (Indices 22-24: Team Context)
    # ========================================================================
    
    def test_team_pace_range(self, sample_features):
        """Test team_pace_last_10 is in valid range"""
        value = sample_features['team_pace_last_10']
        assert 90 <= value <= 110, f"team_pace_last_10 out of range: {value}"
    
    def test_team_off_rating_range(self, sample_features):
        """Test team_off_rating_last_10 is in valid range"""
        value = sample_features['team_off_rating_last_10']
        assert 100 <= value <= 125, f"team_off_rating_last_10 out of range: {value}"
    
    def test_usage_rate_range(self, sample_features):
        """Test usage_rate_last_10 is in valid range"""
        value = sample_features['usage_rate_last_10']
        assert 5 <= value <= 45, f"usage_rate_last_10 out of range: {value}"
    
    # ========================================================================
    # Tier-Based Distribution Tests
    # ========================================================================
    
    def test_superstar_scores_more_than_bench(self, generator):
        """Test that superstars have higher scoring than bench players"""
        lebron = generator.generate_all_features('lebron-james', date(2025, 1, 15))
        
        # Generate features for a bench player (unknown name defaults to bench sometimes)
        bench = generator.generate_all_features('unknown-player-xyz', date(2025, 1, 15))
        
        # LeBron is always superstar (hardcoded), so this should be reliable
        if lebron['player_tier'] == 'superstar' and bench['player_tier'] == 'bench':
            assert lebron['points_avg_season'] > bench['points_avg_season'], \
                "Superstar should score more than bench player"
    
    def test_superstar_plays_more_minutes(self, generator):
        """Test that superstars play more minutes"""
        lebron = generator.generate_all_features('lebron-james', date(2025, 1, 15))
        
        assert lebron['player_tier'] == 'superstar'
        assert lebron['minutes_avg_last_10'] >= 30, \
            f"Superstar should play 30+ minutes, got {lebron['minutes_avg_last_10']}"
    
    def test_superstar_has_higher_usage(self, generator):
        """Test that superstars have higher usage rate"""
        lebron = generator.generate_all_features('lebron-james', date(2025, 1, 15))
        
        assert lebron['player_tier'] == 'superstar'
        assert lebron['usage_rate_last_10'] >= 25, \
            f"Superstar should have usage >= 25%, got {lebron['usage_rate_last_10']}"
    
    # ========================================================================
    # Position-Based Distribution Tests
    # ========================================================================
    
    def test_center_shoots_more_in_paint(self, generator):
        """Test that centers have higher paint rate"""
        embiid = generator.generate_all_features('joel-embiid', date(2025, 1, 15))
        
        assert embiid['player_position'] == 'C'
        assert embiid['paint_rate_last_10'] >= 50, \
            f"Center should shoot 50%+ in paint, got {embiid['paint_rate_last_10']}"
    
    def test_point_guard_shoots_more_threes(self, generator):
        """Test that point guards have higher three-point rate"""
        curry = generator.generate_all_features('stephen-curry', date(2025, 1, 15))
        
        assert curry['player_position'] == 'PG'
        assert curry['three_pt_rate_last_10'] >= 30, \
            f"Point guard should shoot 30%+ threes, got {curry['three_pt_rate_last_10']}"
    
    def test_center_has_high_assisted_rate(self, generator):
        """Test that centers have high assisted rate (catch and finish)"""
        embiid = generator.generate_all_features('joel-embiid', date(2025, 1, 15))
        
        assert embiid['player_position'] == 'C'
        assert embiid['assisted_rate_last_10'] >= 60, \
            f"Center should have assisted rate >= 60%, got {embiid['assisted_rate_last_10']}"
    
    # ========================================================================
    # Reproducibility Tests
    # ========================================================================
    
    def test_seed_produces_reproducible_results(self):
        """Test that same seed produces same results"""
        gen1 = MockDataGenerator(seed=12345)
        gen2 = MockDataGenerator(seed=12345)
        
        features1 = gen1.generate_all_features('test-player', date(2025, 1, 15))
        features2 = gen2.generate_all_features('test-player', date(2025, 1, 15))
        
        # Should be identical
        assert features1['points_avg_last_5'] == features2['points_avg_last_5']
        assert features1['fatigue_score'] == features2['fatigue_score']
        assert features1['paint_rate_last_10'] == features2['paint_rate_last_10']
    
    def test_different_seeds_produce_different_results(self):
        """Test that different seeds produce different results"""
        gen1 = MockDataGenerator(seed=111)
        gen2 = MockDataGenerator(seed=222)
        
        features1 = gen1.generate_all_features('test-player', date(2025, 1, 15))
        features2 = gen2.generate_all_features('test-player', date(2025, 1, 15))
        
        # Should be different (at least some features)
        differences = sum([
            features1['points_avg_last_5'] != features2['points_avg_last_5'],
            features1['fatigue_score'] != features2['fatigue_score'],
            features1['paint_rate_last_10'] != features2['paint_rate_last_10']
        ])
        
        assert differences >= 2, "Different seeds should produce different results"
    
    # ========================================================================
    # Batch Generation Tests
    # ========================================================================
    
    def test_batch_generation(self, generator):
        """Test generating features for multiple players"""
        players = ['lebron-james', 'stephen-curry', 'joel-embiid']
        game_date = date(2025, 1, 15)
        
        batch = generator.generate_batch(players, game_date)
        
        assert len(batch) == 3
        for player in players:
            assert player in batch
            assert batch[player]['feature_count'] == 25
            assert batch[player]['data_source'] == 'mock'
    
    def test_batch_different_players_different_features(self, generator):
        """Test that different players get different feature values"""
        players = ['lebron-james', 'stephen-curry']
        batch = generator.generate_batch(players, date(2025, 1, 15))
        
        lebron = batch['lebron-james']
        curry = batch['stephen-curry']
        
        # LeBron and Curry should have different positions
        assert lebron['player_position'] != curry['player_position']
        
        # Should have different shot distributions
        assert lebron['paint_rate_last_10'] != curry['paint_rate_last_10']
    
    # ========================================================================
    # Convenience Function Test
    # ========================================================================
    
    def test_convenience_function(self):
        """Test the convenience function works correctly"""
        features = get_mock_features('lebron-james', date(2025, 1, 15))
        
        assert features['feature_count'] == 25
        assert features['data_source'] == 'mock'
        assert features['player_lookup'] == 'lebron-james'
    
    # ========================================================================
    # Edge Cases
    # ========================================================================
    
    def test_unknown_player_gets_valid_features(self, generator):
        """Test that unknown players still get valid features"""
        features = generator.generate_all_features('totally-unknown-player-xyz', date(2025, 1, 15))
        
        assert features['feature_count'] == 25
        assert features['data_source'] == 'mock'
        assert features['points_avg_season'] >= 0
        assert features['minutes_avg_last_10'] >= 0
    
    def test_feature_quality_score_is_reasonable(self, sample_features):
        """Test that feature quality score is reasonable for mock data"""
        quality = sample_features['feature_quality_score']
        assert 80 <= quality <= 90, \
            f"Mock data quality should be 80-90, got {quality}"
    
    # ========================================================================
    # Data Type Tests
    # ========================================================================
    
    def test_feature_array_contains_floats(self, sample_features):
        """Test that feature array contains only floats"""
        for i, value in enumerate(sample_features['features']):
            assert isinstance(value, (float, int)), \
                f"Feature {i} ({sample_features['feature_names'][i]}) is not numeric: {type(value)}"
    
    def test_feature_names_are_strings(self, sample_features):
        """Test that feature names are strings"""
        for name in sample_features['feature_names']:
            assert isinstance(name, str), f"Feature name is not string: {type(name)}"
    
    def test_no_null_values_in_features(self, sample_features):
        """Test that no feature values are None/null"""
        for i, value in enumerate(sample_features['features']):
            assert value is not None, \
                f"Feature {i} ({sample_features['feature_names'][i]}) is None"


# ============================================================================
# Integration-Style Tests (Multiple Generations)
# ============================================================================

class TestMockDataGeneratorIntegration:
    """Integration-style tests for mock data generator"""
    
    def test_generate_features_for_50_players(self):
        """Test generating features for many players (stress test)"""
        generator = MockDataGenerator(seed=42)
        
        # Generate for 50 players
        players = [f'player-{i}' for i in range(50)]
        batch = generator.generate_batch(players, date(2025, 1, 15))
        
        assert len(batch) == 50
        
        # All should have valid features
        for player, features in batch.items():
            assert features['feature_count'] == 25
            assert 0 <= features['points_avg_season'] <= 50
            assert 0 <= features['fatigue_score'] <= 100
    
    def test_consistent_tier_inference(self):
        """Test that tier inference is consistent for same player"""
        generator = MockDataGenerator(seed=42)
        
        # Generate multiple times for same player
        results = [
            generator.generate_all_features('lebron-james', date(2025, 1, 15))
            for _ in range(5)
        ]
        
        # Tier should be consistent
        tiers = [r['player_tier'] for r in results]
        assert all(tier == 'superstar' for tier in tiers), \
            "LeBron should always be superstar"
    
    def test_realistic_feature_correlations(self):
        """Test that features have realistic correlations"""
        generator = MockDataGenerator(seed=42)
        
        # Generate for many players to check correlations
        batch = generator.generate_batch(
            ['lebron-james', 'stephen-curry', 'joel-embiid', 'unknown-bench-player'],
            date(2025, 1, 15)
        )
        
        # Higher usage should correlate with higher points
        for player, features in batch.items():
            if features['usage_rate_last_10'] > 30:
                assert features['points_avg_season'] > 20, \
                    f"{player}: High usage should mean high scoring"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

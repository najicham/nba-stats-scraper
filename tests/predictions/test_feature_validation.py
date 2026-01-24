# tests/predictions/test_feature_validation.py

"""
Test suite for feature validation in Phase 5 predictions

Tests the validate_features() function that ensures feature quality
before running prediction systems.
"""

import pytest
import sys
import os
from datetime import date

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from predictions.worker.data_loaders import validate_features
from predictions.shared.mock_data_generator import MockDataGenerator


@pytest.fixture
def mock_generator():
    """Mock data generator with fixed seed"""
    return MockDataGenerator(seed=42)


@pytest.fixture
def complete_features(mock_generator):
    """Generate complete, valid feature set"""
    return mock_generator.generate_all_features(
        player_lookup='test-player',
        game_date=date(2025, 11, 8)
    )


class TestFeatureValidation:
    """Test suite for validate_features function"""
    
    def test_validate_features_all_present(self, complete_features):
        """Test validation passes with complete features"""
        is_valid, errors = validate_features(complete_features)
        
        assert is_valid, f"Validation failed: {errors}"
        assert len(errors) == 0
        assert complete_features['feature_quality_score'] >= 70.0
    
    def test_validate_features_missing_field(self, complete_features):
        """Test validation fails with missing required field"""
        # Remove a critical field
        features = complete_features.copy()
        del features['points_avg_season']
        
        is_valid, errors = validate_features(features)
        
        assert not is_valid, "Should fail with missing field"
        assert len(errors) > 0
        assert 'points_avg_season' in errors[0]
        assert 'Missing fields' in errors[0]
    
    def test_validate_features_multiple_missing_fields(self, complete_features):
        """Test validation reports all missing fields"""
        features = complete_features.copy()
        del features['points_avg_season']
        del features['fatigue_score']
        del features['is_home']
        
        is_valid, errors = validate_features(features)
        
        assert not is_valid
        assert len(errors) > 0
        # Check that all missing fields are reported
        error_msg = errors[0]
        assert 'points_avg_season' in error_msg
        assert 'fatigue_score' in error_msg
        assert 'is_home' in error_msg
    
    def test_validate_features_low_quality_score(self, complete_features):
        """Test validation fails with low quality score"""
        features = complete_features.copy()
        features['feature_quality_score'] = 50.0
        
        is_valid, errors = validate_features(features, min_quality_score=70.0)
        
        assert not is_valid, "Should fail with low quality score"
        assert len(errors) > 0
        assert 'Quality score' in errors[0]
        assert '50.0' in errors[0]
        assert '70.0' in errors[0]
    
    def test_validate_features_custom_quality_threshold(self, complete_features):
        """Test validation with custom quality threshold"""
        features = complete_features.copy()
        features['feature_quality_score'] = 60.0
        
        # Should fail with threshold 70
        is_valid, errors = validate_features(features, min_quality_score=70.0)
        assert not is_valid
        
        # Should pass with threshold 50
        is_valid, errors = validate_features(features, min_quality_score=50.0)
        assert is_valid
        assert len(errors) == 0
    
    def test_validate_features_null_value(self, complete_features):
        """Test validation fails with null value"""
        features = complete_features.copy()
        features['fatigue_score'] = None
        
        is_valid, errors = validate_features(features)
        
        assert not is_valid, "Should fail with null value"
        assert len(errors) > 0
        assert 'fatigue_score is None' in errors
    
    def test_validate_features_multiple_null_values(self, complete_features):
        """Test validation reports all null values"""
        features = complete_features.copy()
        features['fatigue_score'] = None
        features['pace_score'] = None
        features['usage_spike_score'] = None
        
        is_valid, errors = validate_features(features)
        
        assert not is_valid
        assert len(errors) >= 3
        assert 'fatigue_score is None' in errors
        assert 'pace_score is None' in errors
        assert 'usage_spike_score is None' in errors
    
    def test_validate_features_nan_value(self, complete_features):
        """Test validation fails with NaN value"""
        features = complete_features.copy()
        features['points_avg_last_10'] = float('nan')
        
        is_valid, errors = validate_features(features)
        
        assert not is_valid, "Should fail with NaN value"
        assert len(errors) > 0
        assert 'points_avg_last_10 is NaN' in errors
    
    def test_validate_features_out_of_range_points_avg(self, complete_features):
        """Test validation fails with impossible points average"""
        features = complete_features.copy()
        features['points_avg_season'] = 150.0  # Impossible PPG
        
        is_valid, errors = validate_features(features)
        
        assert not is_valid, "Should fail with out-of-range value"
        assert len(errors) > 0
        assert 'points_avg_season' in errors[0]
        assert 'outside range' in errors[0]
    
    def test_validate_features_negative_points_avg(self, complete_features):
        """Test validation fails with negative points average"""
        features = complete_features.copy()
        features['points_avg_last_5'] = -5.0  # Negative PPG
        
        is_valid, errors = validate_features(features)
        
        assert not is_valid
        assert len(errors) > 0
        assert 'points_avg_last_5' in errors[0]
        assert 'outside range' in errors[0]
    
    def test_validate_features_out_of_range_fatigue(self, complete_features):
        """Test validation fails with invalid fatigue score"""
        features = complete_features.copy()
        features['fatigue_score'] = 150.0  # Max should be 100
        
        is_valid, errors = validate_features(features)
        
        assert not is_valid
        assert len(errors) > 0
        assert 'fatigue_score' in errors[0]
    
    def test_validate_features_invalid_is_home(self, complete_features):
        """Test validation fails with invalid boolean flag"""
        features = complete_features.copy()
        features['is_home'] = 2.0  # Should be 0 or 1
        
        is_valid, errors = validate_features(features)
        
        assert not is_valid
        assert len(errors) > 0
        assert 'is_home' in errors[0]
    
    def test_validate_features_invalid_back_to_back(self, complete_features):
        """Test validation fails with invalid back-to-back flag"""
        features = complete_features.copy()
        features['back_to_back'] = -1.0  # Should be 0 or 1
        
        is_valid, errors = validate_features(features)
        
        assert not is_valid
        assert len(errors) > 0
        assert 'back_to_back' in errors[0]
    
    def test_validate_features_extreme_usage_rate(self, complete_features):
        """Test validation fails with unrealistic usage rate"""
        features = complete_features.copy()
        features['usage_rate_last_10'] = 60.0  # Extremely high
        
        is_valid, errors = validate_features(features)
        
        assert not is_valid
        assert len(errors) > 0
        assert 'usage_rate_last_10' in errors[0]
    
    def test_validate_features_boundary_values(self, complete_features):
        """Test validation with boundary values (should pass)"""
        features = complete_features.copy()
        
        # Set to boundary values (should all pass)
        features['points_avg_season'] = 0.0  # Min
        features['points_avg_last_5'] = 80.0  # Max
        features['fatigue_score'] = 100.0  # Max
        features['usage_rate_last_10'] = 5.0  # Min
        features['is_home'] = 1.0
        features['days_rest'] = 10.0
        features['back_to_back'] = 0.0
        
        is_valid, errors = validate_features(features)
        
        assert is_valid, f"Boundary values should be valid: {errors}"
        assert len(errors) == 0


class TestFeatureValidationEdgeCases:
    """Test edge cases and error combinations"""
    
    def test_validate_features_empty_dict(self):
        """Test validation fails gracefully with empty dict"""
        features = {}
        
        is_valid, errors = validate_features(features)
        
        assert not is_valid
        assert len(errors) > 0
        assert 'Missing fields' in errors[0]
    
    def test_validate_features_multiple_error_types(self, complete_features):
        """Test validation reports multiple error types"""
        features = complete_features.copy()
        
        # Create multiple errors
        features['feature_quality_score'] = 50.0  # Low quality
        features['fatigue_score'] = None  # Null value
        features['points_avg_season'] = 150.0  # Out of range
        
        is_valid, errors = validate_features(features)
        
        assert not is_valid
        # Should report quality score first, then return
        assert 'Quality score' in errors[0]
    
    def test_validate_features_quality_score_zero(self, complete_features):
        """Test validation with zero quality score"""
        features = complete_features.copy()
        features['feature_quality_score'] = 0.0
        
        is_valid, errors = validate_features(features, min_quality_score=70.0)
        
        assert not is_valid
        assert 'Quality score' in errors[0]
    
    def test_validate_features_quality_score_exactly_threshold(self, complete_features):
        """Test validation with quality score exactly at threshold"""
        features = complete_features.copy()
        features['feature_quality_score'] = 70.0
        
        is_valid, errors = validate_features(features, min_quality_score=70.0)
        
        assert is_valid, "Should pass when exactly at threshold"
        assert len(errors) == 0
    
    def test_validate_features_all_required_fields_present(self, complete_features):
        """Test that all 25 required fields are checked"""
        required_fields = [
            'points_avg_last_5', 'points_avg_last_10', 'points_avg_season',
            'points_std_last_10', 'games_played_last_7_days',
            'fatigue_score', 'shot_zone_mismatch_score', 'pace_score',
            'usage_spike_score', 'referee_favorability_score',
            'look_ahead_pressure_score', 'matchup_history_score', 'momentum_score',
            'opponent_def_rating_last_15', 'opponent_pace_last_15',
            'is_home', 'days_rest', 'back_to_back',
            'paint_rate_last_10', 'mid_range_rate_last_10',
            'three_pt_rate_last_10', 'assisted_rate_last_10',
            'team_pace_last_10', 'team_off_rating_last_10', 'usage_rate_last_10',
            'feature_quality_score'
        ]
        
        # Verify all required fields are in complete_features
        for field in required_fields:
            assert field in complete_features, f"Mock data missing required field: {field}"
        
        # Validation should pass
        is_valid, errors = validate_features(complete_features)
        assert is_valid


class TestFeatureValidationIntegration:
    """Integration tests with mock data generator"""
    
    def test_validate_mock_generated_features_superstar(self):
        """Test validation with mock superstar features"""
        generator = MockDataGenerator(seed=42)
        features = generator.generate_all_features(
            player_lookup='lebron-james',
            game_date=date(2025, 11, 8),
            tier='superstar'
        )
        
        is_valid, errors = validate_features(features)
        
        assert is_valid, f"Superstar features should be valid: {errors}"
        assert features['points_avg_season'] >= 28  # Superstar range
    
    def test_validate_mock_generated_features_bench(self):
        """Test validation with mock bench player features"""
        generator = MockDataGenerator(seed=42)
        features = generator.generate_all_features(
            player_lookup='bench-player',
            game_date=date(2025, 11, 8),
            tier='bench'
        )
        
        is_valid, errors = validate_features(features)
        
        assert is_valid, f"Bench features should be valid: {errors}"
        assert features['points_avg_season'] <= 10  # Bench range
    
    def test_validate_batch_features(self):
        """Test validation with multiple players"""
        generator = MockDataGenerator(seed=42)
        game_date = date(2025, 11, 8)
        
        players = ['player-1', 'player-2', 'player-3', 'player-4', 'player-5']
        
        for player in players:
            features = generator.generate_all_features(player, game_date)
            is_valid, errors = validate_features(features)
            assert is_valid, f"Player {player} features should be valid: {errors}"
    
    def test_validate_features_different_positions(self):
        """Test validation with different position types"""
        generator = MockDataGenerator(seed=42)
        game_date = date(2025, 11, 8)
        
        positions = ['PG', 'SG', 'SF', 'PF', 'C']
        
        for position in positions:
            features = generator.generate_all_features(
                player_lookup=f'player-{position}',
                game_date=game_date,
                position=position
            )
            is_valid, errors = validate_features(features)
            assert is_valid, f"Position {position} features should be valid: {errors}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
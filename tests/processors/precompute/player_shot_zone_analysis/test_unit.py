"""
Unit Tests for Player Shot Zone Analysis Processor

Tests individual methods and calculations in isolation.
Run with: pytest tests/processors/precompute/test_player_shot_unit.py -v

Test Coverage:
- Zone metrics calculation (shot distribution, efficiency, volume)
- Primary scoring zone identification
- Data quality tier assignment
- Sample quality assessment
- v4.0 source tracking fields
- Dependency configuration

Based on: Team Defense Zone Analysis test patterns
Created: October 30, 2025
"""

import pytest
import pandas as pd
from datetime import date, datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
from decimal import Decimal

from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import (
    PlayerShotZoneAnalysisProcessor
)


class TestZoneMetricsCalculation:
    """Test _calculate_zone_metrics method - core calculation logic."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        proc = PlayerShotZoneAnalysisProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        return proc
    
    @pytest.fixture
    def sample_player_games(self):
        """
        Create sample player game data (10 games).
        
        LeBron-like stats: Paint-dominant player (45% paint, 20% mid, 35% three)
        """
        return pd.DataFrame([
            {
                'player_lookup': 'lebronjames',
                'game_date': date(2025, 1, i),
                'paint_attempts': 8,
                'paint_makes': 5,
                'mid_range_attempts': 4,
                'mid_range_makes': 2,
                'three_pt_attempts': 6,
                'three_pt_makes': 2,
                'fg_makes': 9,
                'assisted_fg_makes': 6,
                'unassisted_fg_makes': 3,
                'minutes_played': 35
            }
            for i in range(1, 11)  # 10 games
        ])
    
    def test_calculate_zone_metrics_basic(self, processor, sample_player_games):
        """Test basic zone metrics calculation with normal inputs."""
        result = processor._calculate_zone_metrics(sample_player_games)
        
        # Calculate expected values explicitly
        total_paint = 8 * 10  # 80 attempts
        total_mid = 4 * 10    # 40 attempts
        total_three = 6 * 10  # 60 attempts
        total_shots = 18 * 10  # 180 attempts
        
        # Shot distribution (rates)
        expected_paint_rate = (total_paint / total_shots) * 100  # 44.44%
        expected_mid_rate = (total_mid / total_shots) * 100      # 22.22%
        expected_three_rate = (total_three / total_shots) * 100  # 33.33%
        
        assert result['paint_rate'] == pytest.approx(expected_paint_rate, abs=0.01)
        assert result['mid_range_rate'] == pytest.approx(expected_mid_rate, abs=0.01)
        assert result['three_pt_rate'] == pytest.approx(expected_three_rate, abs=0.01)
        
        # Shooting efficiency (FG%)
        expected_paint_pct = (5 * 10) / total_paint  # 50/80 = 0.625
        expected_mid_pct = (2 * 10) / total_mid      # 20/40 = 0.500
        expected_three_pct = (2 * 10) / total_three  # 20/60 = 0.333
        
        assert result['paint_pct'] == pytest.approx(expected_paint_pct, abs=0.001)
        assert result['mid_range_pct'] == pytest.approx(expected_mid_pct, abs=0.001)
        assert result['three_pt_pct'] == pytest.approx(expected_three_pct, abs=0.001)
        
        # Volume per game
        assert result['paint_attempts_pg'] == pytest.approx(8.0, abs=0.1)
        assert result['mid_range_attempts_pg'] == pytest.approx(4.0, abs=0.1)
        assert result['three_pt_attempts_pg'] == pytest.approx(6.0, abs=0.1)
        
        # Shot creation
        expected_assisted = (6 * 10) / (9 * 10) * 100  # 60/90 = 66.67%
        expected_unassisted = (3 * 10) / (9 * 10) * 100  # 30/90 = 33.33%
        
        assert result['assisted_rate'] == pytest.approx(expected_assisted, abs=0.01)
        assert result['unassisted_rate'] == pytest.approx(expected_unassisted, abs=0.01)
        
        # Total shots
        assert result['total_shots'] == 180
    
    def test_calculate_zone_metrics_no_mid_range(self, processor, sample_player_games):
        """Test handling when player takes no mid-range shots."""
        # Modern 3-and-D player: no mid-range attempts
        sample_player_games['mid_range_attempts'] = 0
        sample_player_games['mid_range_makes'] = 0
        
        result = processor._calculate_zone_metrics(sample_player_games)
        
        # Mid-range should be None (can't calculate percentage with 0 attempts)
        assert result['mid_range_pct'] is None
        assert result['mid_range_attempts_pg'] == 0.0
        
        # Distribution should still add up (paint + three = 100%)
        total_rate = result['paint_rate'] + result['three_pt_rate']
        assert total_rate == pytest.approx(100.0, abs=0.1)
        
        # Other zones should still work
        assert result['paint_pct'] is not None
        assert result['three_pt_pct'] is not None
    
    def test_calculate_zone_metrics_perfect_shooting(self, processor, sample_player_games):
        """Test when player makes all shots (100% FG%)."""
        # Set makes equal to attempts
        sample_player_games['paint_makes'] = sample_player_games['paint_attempts']
        sample_player_games['mid_range_makes'] = sample_player_games['mid_range_attempts']
        sample_player_games['three_pt_makes'] = sample_player_games['three_pt_attempts']
        sample_player_games['fg_makes'] = 18  # 8 + 4 + 6
        
        result = processor._calculate_zone_metrics(sample_player_games)
        
        # All percentages should be 1.0 (100%)
        assert result['paint_pct'] == pytest.approx(1.0, abs=0.001)
        assert result['mid_range_pct'] == pytest.approx(1.0, abs=0.001)
        assert result['three_pt_pct'] == pytest.approx(1.0, abs=0.001)
    
    def test_calculate_zone_metrics_zero_shooting(self, processor, sample_player_games):
        """Test when player misses all shots (0% FG%)."""
        sample_player_games['paint_makes'] = 0
        sample_player_games['mid_range_makes'] = 0
        sample_player_games['three_pt_makes'] = 0
        sample_player_games['fg_makes'] = 0
        
        result = processor._calculate_zone_metrics(sample_player_games)
        
        # All percentages should be 0.0
        assert result['paint_pct'] == 0.0
        assert result['mid_range_pct'] == 0.0
        assert result['three_pt_pct'] == 0.0
        
        # Assisted rates should be None (0 makes)
        assert result['assisted_rate'] is None
        assert result['unassisted_rate'] is None
    
    def test_calculate_zone_metrics_single_game(self, processor):
        """Test calculation with just 1 game."""
        single_game = pd.DataFrame([{
            'player_lookup': 'rookieplayer',
            'game_date': date(2025, 1, 1),
            'paint_attempts': 10,
            'paint_makes': 6,
            'mid_range_attempts': 5,
            'mid_range_makes': 2,
            'three_pt_attempts': 8,
            'three_pt_makes': 3,
            'fg_makes': 11,
            'assisted_fg_makes': 8,
            'unassisted_fg_makes': 3,
            'minutes_played': 28
        }])
        
        result = processor._calculate_zone_metrics(single_game)
        
        # Per game stats should equal game totals
        assert result['paint_attempts_pg'] == 10.0
        assert result['mid_range_attempts_pg'] == 5.0
        assert result['three_pt_attempts_pg'] == 8.0
        
        # Percentages should work normally
        assert result['paint_pct'] == pytest.approx(0.6, abs=0.001)
    
    def test_calculate_zone_metrics_varied_volume(self, processor):
        """Test with games having different shot volumes."""
        varied_games = pd.DataFrame([
            {
                'player_lookup': 'benchplayer',
                'game_date': date(2025, 1, i),
                'paint_attempts': 2 if i % 2 == 0 else 10,  # Alternating volume
                'paint_makes': 1 if i % 2 == 0 else 6,
                'mid_range_attempts': 1,
                'mid_range_makes': 0,
                'three_pt_attempts': 3,
                'three_pt_makes': 1,
                'fg_makes': 2 if i % 2 == 0 else 8,
                'assisted_fg_makes': 2 if i % 2 == 0 else 6,
                'unassisted_fg_makes': 0 if i % 2 == 0 else 2,
                'minutes_played': 15 if i % 2 == 0 else 35
            }
            for i in range(1, 11)
        ])
        
        result = processor._calculate_zone_metrics(varied_games)
        
        # Averages should handle varying volume
        total_paint = (2 * 5) + (10 * 5)  # 60 attempts
        assert result['paint_attempts_pg'] == pytest.approx(6.0, abs=0.1)
        
        # Percentages should aggregate correctly
        total_paint_makes = (1 * 5) + (6 * 5)  # 35 makes
        expected_pct = 35 / 60
        assert result['paint_pct'] == pytest.approx(expected_pct, abs=0.001)


class TestPrimaryZoneIdentification:
    """Test _determine_primary_zone method - identifies player's preferred zone."""
    
    @pytest.fixture
    def processor(self):
        return PlayerShotZoneAnalysisProcessor()
    
    def test_paint_dominant_player(self, processor):
        """Test paint-dominant player (≥40% paint rate)."""
        metrics = {
            'paint_rate': 45.0,
            'mid_range_rate': 20.0,
            'three_pt_rate': 35.0
        }
        
        result = processor._determine_primary_zone(metrics)
        assert result == 'paint'
    
    def test_paint_exactly_40_percent(self, processor):
        """Test boundary: exactly 40% paint rate."""
        metrics = {
            'paint_rate': 40.0,
            'mid_range_rate': 25.0,
            'three_pt_rate': 35.0
        }
        
        result = processor._determine_primary_zone(metrics)
        assert result == 'paint'
    
    def test_perimeter_dominant_player(self, processor):
        """Test perimeter-dominant player (≥40% three-point rate)."""
        metrics = {
            'paint_rate': 25.0,
            'mid_range_rate': 15.0,
            'three_pt_rate': 60.0
        }
        
        result = processor._determine_primary_zone(metrics)
        assert result == 'perimeter'
    
    def test_perimeter_exactly_40_percent(self, processor):
        """Test boundary: exactly 40% three-point rate."""
        metrics = {
            'paint_rate': 35.0,
            'mid_range_rate': 25.0,
            'three_pt_rate': 40.0
        }
        
        result = processor._determine_primary_zone(metrics)
        assert result == 'perimeter'
    
    def test_mid_range_dominant_player(self, processor):
        """Test mid-range specialist (≥30% mid-range rate)."""
        metrics = {
            'paint_rate': 30.0,
            'mid_range_rate': 40.0,
            'three_pt_rate': 30.0
        }
        
        result = processor._determine_primary_zone(metrics)
        assert result == 'mid_range'
    
    def test_mid_range_exactly_30_percent(self, processor):
        """Test boundary: exactly 30% mid-range rate now returns 'balanced'."""
        metrics = {
            'paint_rate': 35.0,
            'mid_range_rate': 30.0,
            'three_pt_rate': 35.0
        }
        
        # With new 35% threshold, 30% mid-range returns 'balanced'
        result = processor._determine_primary_zone(metrics)
        assert result == 'balanced'

    def test_mid_range_exactly_35_percent(self, processor):
        """Test boundary: exactly 35% mid-range rate returns 'mid_range'."""
        metrics = {
            'paint_rate': 30.0,
            'mid_range_rate': 35.0,
            'three_pt_rate': 35.0
        }
        
        result = processor._determine_primary_zone(metrics)
        assert result == 'mid_range'
    
    def test_balanced_player(self, processor):
        """Test balanced player (no zone dominates)."""
        metrics = {
            'paint_rate': 35.0,
            'mid_range_rate': 25.0,
            'three_pt_rate': 38.0  # Just under 40%
        }
        
        result = processor._determine_primary_zone(metrics)
        assert result == 'balanced'
    
    def test_perfectly_balanced_player(self, processor):
        """Test perfectly balanced distribution."""
        metrics = {
            'paint_rate': 33.3,
            'mid_range_rate': 33.3,
            'three_pt_rate': 33.4
        }
        
        result = processor._determine_primary_zone(metrics)
        assert result == 'balanced'
    
    def test_paint_over_perimeter_priority(self, processor):
        """Test that paint takes priority over perimeter when both ≥40%."""
        # Edge case: shouldn't happen in real data, but test priority
        metrics = {
            'paint_rate': 45.0,
            'mid_range_rate': 10.0,
            'three_pt_rate': 45.0
        }
        
        result = processor._determine_primary_zone(metrics)
        assert result == 'paint'  # Paint is checked first
    
    def test_missing_data_returns_none(self, processor):
        """Test handling when all rates are None or 0."""
        metrics = {
            'paint_rate': None,
            'mid_range_rate': None,
            'three_pt_rate': None
        }
        
        result = processor._determine_primary_zone(metrics)
        assert result is None
    
    def test_zero_rates_returns_none(self, processor):
        """Test handling when all rates are 0."""
        metrics = {
            'paint_rate': 0,
            'mid_range_rate': 0,
            'three_pt_rate': 0
        }
        
        result = processor._determine_primary_zone(metrics)
        assert result is None


class TestDataQualityTier:
    """Test _determine_quality_tier method - assigns quality based on sample size."""
    
    @pytest.fixture
    def processor(self):
        return PlayerShotZoneAnalysisProcessor()
    
    def test_high_quality_exactly_10_games(self, processor):
        """Test high quality with exactly 10 games (minimum required)."""
        assert processor._determine_quality_tier(10) == 'high'
    
    def test_high_quality_more_games(self, processor):
        """Test high quality with more than 10 games."""
        assert processor._determine_quality_tier(15) == 'high'
        assert processor._determine_quality_tier(20) == 'high'
        assert processor._determine_quality_tier(82) == 'high'  # Full season
    
    def test_medium_quality_7_games(self, processor):
        """Test medium quality with exactly 7 games."""
        assert processor._determine_quality_tier(7) == 'medium'
    
    def test_medium_quality_8_to_9_games(self, processor):
        """Test medium quality with 8-9 games."""
        assert processor._determine_quality_tier(8) == 'medium'
        assert processor._determine_quality_tier(9) == 'medium'
    
    def test_low_quality_below_7_games(self, processor):
        """Test low quality with <7 games."""
        assert processor._determine_quality_tier(6) == 'low'
        assert processor._determine_quality_tier(5) == 'low'
        assert processor._determine_quality_tier(1) == 'low'
    
    def test_low_quality_zero_games(self, processor):
        """Test low quality with 0 games."""
        assert processor._determine_quality_tier(0) == 'low'


class TestSampleQualityAssessment:
    """Test _determine_sample_quality method - assesses quality relative to target."""
    
    @pytest.fixture
    def processor(self):
        return PlayerShotZoneAnalysisProcessor()
    
    def test_excellent_quality_10_game_target(self, processor):
        """Test excellent quality when meeting 10-game target."""
        assert processor._determine_sample_quality(10, 10) == 'excellent'
        assert processor._determine_sample_quality(12, 10) == 'excellent'
    
    def test_excellent_quality_20_game_target(self, processor):
        """Test excellent quality when meeting 20-game target."""
        assert processor._determine_sample_quality(20, 20) == 'excellent'
        assert processor._determine_sample_quality(25, 20) == 'excellent'
    
    def test_good_quality_10_game_target(self, processor):
        """Test good quality with 70-99% of 10-game target."""
        # 70% of 10 = 7 games
        assert processor._determine_sample_quality(7, 10) == 'good'
        assert processor._determine_sample_quality(8, 10) == 'good'
        assert processor._determine_sample_quality(9, 10) == 'good'
    
    def test_good_quality_20_game_target(self, processor):
        """Test good quality with 70-99% of 20-game target."""
        # 70% of 20 = 14 games
        assert processor._determine_sample_quality(14, 20) == 'good'
        assert processor._determine_sample_quality(15, 20) == 'good'
        assert processor._determine_sample_quality(19, 20) == 'good'
    
    def test_limited_quality_10_game_target(self, processor):
        """Test limited quality with 50-69% of 10-game target."""
        # 50% of 10 = 5 games
        assert processor._determine_sample_quality(5, 10) == 'limited'
        assert processor._determine_sample_quality(6, 10) == 'limited'
    
    def test_limited_quality_20_game_target(self, processor):
        """Test limited quality with 50-69% of 20-game target."""
        # 50% of 20 = 10 games
        assert processor._determine_sample_quality(10, 20) == 'limited'
        assert processor._determine_sample_quality(13, 20) == 'limited'
    
    def test_insufficient_quality_below_50_percent(self, processor):
        """Test insufficient quality with <50% of target."""
        assert processor._determine_sample_quality(4, 10) == 'insufficient'
        assert processor._determine_sample_quality(9, 20) == 'insufficient'
        assert processor._determine_sample_quality(1, 10) == 'insufficient'
    
    def test_insufficient_quality_zero_games(self, processor):
        """Test insufficient quality with 0 games."""
        assert processor._determine_sample_quality(0, 10) == 'insufficient'
        assert processor._determine_sample_quality(0, 20) == 'insufficient'
    
    def test_boundary_exactly_70_percent(self, processor):
        """Test boundary: exactly 70% should be 'good'."""
        # 70% of 10 = 7
        assert processor._determine_sample_quality(7, 10) == 'good'
        # 70% of 20 = 14
        assert processor._determine_sample_quality(14, 20) == 'good'
    
    def test_boundary_exactly_50_percent(self, processor):
        """Test boundary: exactly 50% should be 'limited'."""
        # 50% of 10 = 5
        assert processor._determine_sample_quality(5, 10) == 'limited'
        # 50% of 20 = 10
        assert processor._determine_sample_quality(10, 20) == 'limited'


class TestSourceTrackingFields:
    """Test build_source_tracking_fields method (v4.0 dependency tracking)."""
    
    @pytest.fixture
    def processor(self):
        """Create processor with mocked source metadata."""
        proc = PlayerShotZoneAnalysisProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        
        # Mock source metadata (populated by track_source_usage)
        # Use the FULL TABLE NAME as the key
        proc.source_metadata = {
            'nba_analytics.player_game_summary': {
                'last_updated': '2025-01-27T23:05:00Z',
                'rows_found': 10,
                'completeness_pct': 100.0
            }
        }
        return proc
    
    def test_build_source_tracking_normal_season(self, processor):
        """Test source tracking fields for normal season (not early season)."""
        fields = processor.build_source_tracking_fields()
        
        # Check v4.0 fields (3 per source) - use get() for safety
        assert fields.get('source_player_game_last_updated') == '2025-01-27T23:05:00Z'
        assert fields.get('source_player_game_rows_found') == 10
        assert fields.get('source_player_game_completeness_pct') == 100.0
    
    def test_build_source_tracking_early_season(self, processor):
        """Test source tracking fields when early season flags are set."""
        # Set early season attributes
        processor.early_season_flag = True
        processor.insufficient_data_reason = "Only 5 games available, need 10"
        
        fields = processor.build_source_tracking_fields()
        
        # Source tracking still populated
        assert fields['source_player_game_last_updated'] == '2025-01-27T23:05:00Z'
        assert fields['source_player_game_rows_found'] == 10
        assert fields['source_player_game_completeness_pct'] == 100.0
        
        # Early season flags set
        assert fields['early_season_flag'] is True
        assert fields['insufficient_data_reason'] == "Only 5 games available, need 10"
    
    def test_build_source_tracking_incomplete_data(self, processor):
        """Test source tracking with incomplete data (<100% completeness)."""
        # Update the source_metadata to show incomplete data
        processor.source_metadata['nba_analytics.player_game_summary']['completeness_pct'] = 70.0
        processor.source_metadata['nba_analytics.player_game_summary']['rows_found'] = 7
        
        fields = processor.build_source_tracking_fields()
        
        # Should reflect incomplete data
        assert fields['source_player_game_completeness_pct'] == 70.0
        assert fields['source_player_game_rows_found'] == 7
    
    def test_build_source_tracking_missing_source(self, processor):
        """Test source tracking when source data is missing."""
        # Set source_metadata to empty dict (source not found)
        processor.source_metadata = {}
        
        fields = processor.build_source_tracking_fields()
        
        # All fields should be None
        assert fields['source_player_game_last_updated'] is None
        assert fields['source_player_game_rows_found'] is None
        assert fields['source_player_game_completeness_pct'] is None
    
    def test_build_source_tracking_field_names(self, processor):
        """Test that all expected field names are present."""
        fields = processor.build_source_tracking_fields()
        
        # Required v4.0 fields
        expected_fields = [
            'source_player_game_last_updated',
            'source_player_game_rows_found',
            'source_player_game_completeness_pct'
        ]
        
        for field in expected_fields:
            assert field in fields, f"Missing required field: {field}"


class TestDependencyConfiguration:
    """Test get_dependencies method - processor dependency configuration."""
    
    @pytest.fixture
    def processor(self):
        return PlayerShotZoneAnalysisProcessor()
    
    def test_get_dependencies_returns_dict(self, processor):
        """Test that get_dependencies returns a dictionary."""
        deps = processor.get_dependencies()
        assert isinstance(deps, dict)
    
    def test_dependency_on_player_game_summary(self, processor):
        """Test dependency on nba_analytics.player_game_summary."""
        deps = processor.get_dependencies()
        
        assert 'nba_analytics.player_game_summary' in deps
    
    def test_dependency_configuration_structure(self, processor):
        """Test structure of dependency configuration."""
        deps = processor.get_dependencies()
        config = deps['nba_analytics.player_game_summary']
        
        # Check required fields
        assert 'field_prefix' in config
        assert 'description' in config
        assert 'check_type' in config
        assert 'min_games_required' in config
        assert 'min_players_with_data' in config
        assert 'entity_field' in config
        assert 'max_age_hours_warn' in config
        assert 'max_age_hours_fail' in config
        assert 'critical' in config
    
    def test_dependency_field_prefix(self, processor):
        """Test field_prefix matches source tracking fields."""
        deps = processor.get_dependencies()
        config = deps['nba_analytics.player_game_summary']
        
        assert config['field_prefix'] == 'source_player_game'
    
    def test_dependency_check_type(self, processor):
        """Test check_type is set correctly."""
        deps = processor.get_dependencies()
        config = deps['nba_analytics.player_game_summary']
        
        # Should be per-player game count check
        assert config['check_type'] == 'per_player_game_count'
    
    def test_dependency_min_games_matches_processor(self, processor):
        """Test min_games_required matches processor's min_games_required."""
        deps = processor.get_dependencies()
        config = deps['nba_analytics.player_game_summary']
        
        assert config['min_games_required'] == processor.min_games_required
        assert config['min_games_required'] == 10
    
    def test_dependency_entity_field(self, processor):
        """Test entity_field is set correctly."""
        deps = processor.get_dependencies()
        config = deps['nba_analytics.player_game_summary']
        
        assert config['entity_field'] == 'player_lookup'
    
    def test_dependency_freshness_thresholds(self, processor):
        """Test freshness threshold values."""
        deps = processor.get_dependencies()
        config = deps['nba_analytics.player_game_summary']
        
        # Warning at 24 hours, fail at 72 hours
        assert config['max_age_hours_warn'] == 24
        assert config['max_age_hours_fail'] == 72
    
    def test_dependency_early_season_config(self, processor):
        """Test early season configuration."""
        deps = processor.get_dependencies()
        config = deps['nba_analytics.player_game_summary']
        
        # First 2 weeks of season
        assert config['early_season_days'] == 14
        assert config['early_season_behavior'] == 'WRITE_PLACEHOLDER'
    
    def test_dependency_is_critical(self, processor):
        """Test dependency is marked as critical."""
        deps = processor.get_dependencies()
        config = deps['nba_analytics.player_game_summary']
        
        assert config['critical'] is True
    
    def test_dependency_min_players_threshold(self, processor):
        """Test minimum players threshold."""
        deps = processor.get_dependencies()
        config = deps['nba_analytics.player_game_summary']
        
        # Should expect at least 400 active players
        assert config['min_players_with_data'] >= 400


# Test runner
if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

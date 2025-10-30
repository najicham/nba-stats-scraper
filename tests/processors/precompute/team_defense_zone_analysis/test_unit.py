"""
Path: tests/processors/precompute/team_defense_zone_analysis/test_unit.py

Unit Tests for Team Defense Zone Analysis Processor

Tests individual methods and calculations in isolation.
Run with: pytest tests/precompute/test_team_defense_unit.py -v
"""

import pytest
import pandas as pd
from datetime import date, datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
from decimal import Decimal

# Import processor
from data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor import (
    TeamDefenseZoneAnalysisProcessor
)


class TestZoneDefenseCalculations:
    """Test _calculate_zone_defense method."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        proc = TeamDefenseZoneAnalysisProcessor()
        proc.league_averages = {
            'paint_pct': 0.580,
            'mid_range_pct': 0.410,
            'three_pt_pct': 0.355
        }
        return proc
    
    @pytest.fixture
    def sample_team_data(self):
        """Create sample team defensive data (15 games)."""
        return pd.DataFrame([
            {
                'defending_team_abbr': 'LAL',
                'game_date': date(2025, 1, 15),
                'opp_paint_makes': 20,
                'opp_paint_attempts': 35,
                'opp_mid_range_makes': 8,
                'opp_mid_range_attempts': 20,
                'opp_three_pt_makes': 12,
                'opp_three_pt_attempts': 35,
                'points_in_paint_allowed': 42,
                'mid_range_points_allowed': 16,
                'three_pt_points_allowed': 36,
                'blocks_paint': 2,
                'blocks_mid_range': 1,
                'blocks_three_pt': 0,
                'points_allowed': 110,
                'defensive_rating': 112.5,
                'opponent_pace': 99.2
            }
            for i in range(15)  # 15 identical games for simplicity
        ])
    
    def test_calculate_zone_defense_basic(self, processor, sample_team_data):
        """Test basic zone defense calculation."""
        result = processor._calculate_zone_defense(sample_team_data, games_count=15)
        
        # Check paint defense
        expected_paint_pct = 20 * 15 / (35 * 15)  # 300/525 = 0.571
        assert result['paint_pct'] == pytest.approx(0.571, abs=0.001)
        assert result['paint_attempts_pg'] == pytest.approx(35.0, abs=0.1)
        assert result['paint_points_pg'] == pytest.approx(42.0, abs=0.1)
        assert result['paint_blocks_pg'] == pytest.approx(2.0, abs=0.1)
        
        # Check mid-range defense
        expected_mid_pct = 8 * 15 / (20 * 15)  # 120/300 = 0.400
        assert result['mid_range_pct'] == pytest.approx(0.400, abs=0.001)
        assert result['mid_range_attempts_pg'] == pytest.approx(20.0, abs=0.1)
        
        # Check three-point defense
        expected_three_pct = 12 * 15 / (35 * 15)  # 180/525 = 0.343
        assert result['three_pt_pct'] == pytest.approx(0.343, abs=0.001)
        assert result['three_pt_attempts_pg'] == pytest.approx(35.0, abs=0.1)
        
        # Check overall metrics
        assert result['defensive_rating'] == pytest.approx(112.5, abs=0.1)
        assert result['opp_points_pg'] == pytest.approx(110.0, abs=0.1)
        assert result['opponent_pace'] == pytest.approx(99.2, abs=0.1)
    
    def test_vs_league_average_calculations(self, processor, sample_team_data):
        """Test vs league average percentage point calculations."""
        result = processor._calculate_zone_defense(sample_team_data, games_count=15)
        
        # Paint: 0.571 vs 0.580 league = -0.9 pp (better defense)
        assert result['paint_vs_league'] == pytest.approx(-0.9, abs=0.1)
        
        # Mid-range: 0.400 vs 0.410 league = -1.0 pp (better defense)
        assert result['mid_range_vs_league'] == pytest.approx(-1.0, abs=0.1)
        
        # Three-point: 0.343 vs 0.355 league = -1.2 pp (better defense)
        assert result['three_pt_vs_league'] == pytest.approx(-1.2, abs=0.1)
    
    def test_no_mid_range_attempts(self, processor, sample_team_data):
        """Test handling when team allows no mid-range attempts."""
        # Set mid-range attempts to 0
        sample_team_data['opp_mid_range_attempts'] = 0
        sample_team_data['opp_mid_range_makes'] = 0
        
        result = processor._calculate_zone_defense(sample_team_data, games_count=15)
        
        # Mid-range should be None
        assert result['mid_range_pct'] is None
        assert result['mid_range_vs_league'] is None
        
        # Others should still work
        assert result['paint_pct'] is not None
        assert result['three_pt_pct'] is not None
        
        # Should have note
        assert result['notes'] == "No mid-range attempts"
    
    def test_zero_attempts_all_zones(self, processor):
        """Test handling when team allows no attempts in any zone."""
        # Create data with zero attempts
        zero_data = pd.DataFrame([
            {
                'defending_team_abbr': 'LAL',
                'game_date': date(2025, 1, 15),
                'opp_paint_makes': 0,
                'opp_paint_attempts': 0,
                'opp_mid_range_makes': 0,
                'opp_mid_range_attempts': 0,
                'opp_three_pt_makes': 0,
                'opp_three_pt_attempts': 0,
                'points_in_paint_allowed': 0,
                'mid_range_points_allowed': 0,
                'three_pt_points_allowed': 0,
                'blocks_paint': 0,
                'blocks_mid_range': 0,
                'blocks_three_pt': 0,
                'points_allowed': 0,
                'defensive_rating': 100.0,
                'opponent_pace': 95.0
            }
            for i in range(15)
        ])
        
        result = processor._calculate_zone_defense(zero_data, games_count=15)
        
        # All percentages should be None
        assert result['paint_pct'] is None
        assert result['mid_range_pct'] is None
        assert result['three_pt_pct'] is None
        
        # Volume metrics should be 0
        assert result['paint_attempts_pg'] == 0.0
        assert result['mid_range_attempts_pg'] == 0.0
        assert result['three_pt_attempts_pg'] == 0.0
        
        # Should have notes for all zones
        assert "No paint attempts" in result['notes']
        assert "No mid-range attempts" in result['notes']
        assert "No three-point attempts" in result['notes']


class TestStrengthsWeaknessesIdentification:
    """Test _identify_strengths_weaknesses method."""
    
    @pytest.fixture
    def processor(self):
        return TeamDefenseZoneAnalysisProcessor()
    
    def test_identify_clear_strength_weakness(self, processor):
        """Test identification when one zone is clearly best/worst."""
        zone_metrics = {
            'paint_vs_league': 3.0,      # Worst (allowing 3pp more)
            'mid_range_vs_league': -2.5,  # Best (allowing 2.5pp less)
            'three_pt_vs_league': 0.5     # Average
        }
        
        result = processor._identify_strengths_weaknesses(zone_metrics)
        
        assert result['strongest'] == 'mid_range'
        assert result['weakest'] == 'paint'
    
    def test_identify_perimeter_strength(self, processor):
        """Test identification of perimeter strength."""
        zone_metrics = {
            'paint_vs_league': 1.0,
            'mid_range_vs_league': 0.5,
            'three_pt_vs_league': -4.0  # Elite perimeter defense
        }
        
        result = processor._identify_strengths_weaknesses(zone_metrics)
        
        assert result['strongest'] == 'perimeter'
        assert result['weakest'] == 'paint'
    
    def test_identify_with_missing_zone(self, processor):
        """Test identification when one zone has no data."""
        zone_metrics = {
            'paint_vs_league': 2.0,
            'mid_range_vs_league': None,  # No mid-range data
            'three_pt_vs_league': -1.0
        }
        
        result = processor._identify_strengths_weaknesses(zone_metrics)
        
        # Should only compare available zones
        assert result['strongest'] == 'perimeter'
        assert result['weakest'] == 'paint'
    
    def test_identify_all_zones_missing(self, processor):
        """Test identification when all zones have no data."""
        zone_metrics = {
            'paint_vs_league': None,
            'mid_range_vs_league': None,
            'three_pt_vs_league': None
        }
        
        result = processor._identify_strengths_weaknesses(zone_metrics)
        
        assert result['strongest'] is None
        assert result['weakest'] is None
    
    def test_identify_balanced_defense(self, processor):
        """Test identification when all zones are similar."""
        zone_metrics = {
            'paint_vs_league': 0.1,
            'mid_range_vs_league': 0.2,
            'three_pt_vs_league': -0.1
        }
        
        result = processor._identify_strengths_weaknesses(zone_metrics)
        
        # Should still identify strongest/weakest even if close
        assert result['strongest'] == 'perimeter'  # -0.1
        assert result['weakest'] == 'mid_range'    # +0.2


class TestDataQualityTier:
    """Test _determine_quality_tier method."""
    
    @pytest.fixture
    def processor(self):
        return TeamDefenseZoneAnalysisProcessor()
    
    def test_high_quality_15_games(self, processor):
        """Test high quality with exactly 15 games."""
        assert processor._determine_quality_tier(15) == 'high'
    
    def test_high_quality_more_games(self, processor):
        """Test high quality with more than 15 games."""
        assert processor._determine_quality_tier(20) == 'high'
    
    def test_medium_quality(self, processor):
        """Test medium quality with 10-14 games."""
        assert processor._determine_quality_tier(10) == 'medium'
        assert processor._determine_quality_tier(12) == 'medium'
        assert processor._determine_quality_tier(14) == 'medium'
    
    def test_low_quality(self, processor):
        """Test low quality with <10 games."""
        assert processor._determine_quality_tier(9) == 'low'
        assert processor._determine_quality_tier(5) == 'low'
        assert processor._determine_quality_tier(1) == 'low'


class TestSourceTrackingFields:
    """Test build_source_tracking_fields method (v4.0)."""
    
    @pytest.fixture
    def processor(self):
        proc = TeamDefenseZoneAnalysisProcessor()
        # Mock source metadata populated by track_source_usage
        proc.source_metadata = {
            'nba_analytics.team_defense_game_summary': {
                'last_updated': '2025-01-27T23:05:00Z',
                'rows_found': 450,
                'completeness_pct': 100.00
            }
        }
        return proc
    
    def test_build_source_tracking_normal(self, processor):
        """Test source tracking fields for normal season."""
        fields = processor.build_source_tracking_fields()
        
        # Check v4.0 fields (3 per source)
        assert fields['source_team_defense_last_updated'] == '2025-01-27T23:05:00Z'
        assert fields['source_team_defense_rows_found'] == 450
        assert fields['source_team_defense_completeness_pct'] == 100.00
        
        # Early season should be None
        assert fields['early_season_flag'] is None
        assert fields['insufficient_data_reason'] is None
    
    def test_build_source_tracking_early_season(self, processor):
        """Test source tracking fields for early season."""
        processor.early_season_flag = True
        processor.insufficient_data_reason = "Only 3 games available, need 15"
        
        fields = processor.build_source_tracking_fields()
        
        # Source tracking still populated
        assert fields['source_team_defense_last_updated'] == '2025-01-27T23:05:00Z'
        assert fields['source_team_defense_rows_found'] == 450
        
        # Early season flags set
        assert fields['early_season_flag'] is True
        assert fields['insufficient_data_reason'] == "Only 3 games available, need 15"
    
    def test_build_source_tracking_missing_source(self, processor):
        """Test source tracking when source has no data."""
        processor.source_metadata = {}
        
        fields = processor.build_source_tracking_fields()
        
        # All fields should be None
        assert fields['source_team_defense_last_updated'] is None
        assert fields['source_team_defense_rows_found'] is None
        assert fields['source_team_defense_completeness_pct'] is None


class TestLeagueAverageCalculation:
    """Test league average calculation logic."""
    
    @pytest.fixture
    def processor(self):
        proc = TeamDefenseZoneAnalysisProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.opts = {'analysis_date': date(2025, 1, 27)}
        return proc
    
    def test_league_averages_sufficient_teams(self, processor):
        """Test league average calculation with sufficient teams."""
        # Mock BigQuery response with 25 teams
        mock_df = pd.DataFrame([{
            'league_avg_paint_pct': 0.585,
            'league_avg_mid_range_pct': 0.415,
            'league_avg_three_pt_pct': 0.358,
            'teams_in_sample': 25
        }])
        
        processor.bq_client.query.return_value.to_dataframe.return_value = mock_df
        
        processor._calculate_league_averages()
        
        # Check calculated averages
        assert processor.league_averages['paint_pct'] == 0.585
        assert processor.league_averages['mid_range_pct'] == 0.415
        assert processor.league_averages['three_pt_pct'] == 0.358
        assert processor.league_averages['teams_in_sample'] == 25
    
    def test_league_averages_insufficient_teams(self, processor):
        """Test league average fallback with <10 teams."""
        # Mock BigQuery response with only 8 teams
        mock_df = pd.DataFrame([{
            'league_avg_paint_pct': 0.600,
            'league_avg_mid_range_pct': 0.420,
            'league_avg_three_pt_pct': 0.365,
            'teams_in_sample': 8
        }])
        
        processor.bq_client.query.return_value.to_dataframe.return_value = mock_df
        
        processor._calculate_league_averages()
        
        # Should use defaults
        assert processor.league_averages['paint_pct'] == 0.580
        assert processor.league_averages['mid_range_pct'] == 0.410
        assert processor.league_averages['three_pt_pct'] == 0.355
        assert processor.league_averages['teams_in_sample'] == 0
    
    def test_league_averages_empty_result(self, processor):
        """Test league average fallback with no results."""
        # Mock empty BigQuery response
        mock_df = pd.DataFrame()
        
        processor.bq_client.query.return_value.to_dataframe.return_value = mock_df
        
        processor._calculate_league_averages()
        
        # Should use defaults
        assert processor.league_averages['paint_pct'] == 0.580
        assert processor.league_averages['mid_range_pct'] == 0.410
        assert processor.league_averages['three_pt_pct'] == 0.355
        assert processor.league_averages['teams_in_sample'] == 0


class TestDependencyConfiguration:
    """Test dependency configuration."""
    
    @pytest.fixture
    def processor(self):
        return TeamDefenseZoneAnalysisProcessor()
    
    def test_get_dependencies_structure(self, processor):
        """Test dependency configuration structure."""
        deps = processor.get_dependencies()
        
        # Should have team_defense_game_summary
        assert 'nba_analytics.team_defense_game_summary' in deps
        
        dep_config = deps['nba_analytics.team_defense_game_summary']
        
        # Check required fields
        assert dep_config['field_prefix'] == 'source_team_defense'
        assert dep_config['check_type'] == 'per_team_game_count'
        assert dep_config['min_games_required'] == 15
        assert dep_config['min_teams_with_data'] == 25
        assert dep_config['critical'] is True
    
    def test_get_dependencies_configurable_params(self, processor):
        """Test that dependency uses processor's configurable parameters."""
        # Change processor config
        processor.min_games_required = 20
        processor.early_season_threshold_days = 21
        
        deps = processor.get_dependencies()
        dep_config = deps['nba_analytics.team_defense_game_summary']
        
        # Should reflect processor config
        assert dep_config['min_games_required'] == 20
        assert dep_config['early_season_days'] == 21


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

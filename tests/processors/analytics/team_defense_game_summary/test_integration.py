# Path: tests/processors/analytics/team_defense_game_summary/test_integration.py

"""
Integration tests for team_defense_game_summary processor.
Tests complete pipeline with mocked BigQuery.

Run with: pytest test_integration.py -v
"""

import pytest
import pandas as pd
from datetime import datetime, date, timezone
from unittest.mock import Mock, patch, MagicMock
from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import (
    TeamDefenseGameSummaryProcessor
)


def test_full_pipeline_success(
    mock_processor,
    sample_raw_extracted_data
):
    """Test complete pipeline from extraction to save."""
    
    # Mock extract_raw_data to set raw_data
    def mock_extract():
        mock_processor.raw_data = sample_raw_extracted_data
    
    with patch.object(mock_processor, 'extract_raw_data', side_effect=mock_extract):
        # Mock build_source_tracking_fields
        mock_processor.build_source_tracking_fields = Mock(return_value={
            'source_team_boxscore_last_updated': datetime(2024, 10, 21, 23, 0, 0),
            'source_team_boxscore_rows_found': 2,
            'source_team_boxscore_completeness_pct': 100.0
        })
        
        result = mock_processor.run({
            'start_date': '2024-10-21',
            'end_date': '2024-10-21'
        })
        
        assert result is True
        assert mock_processor.save_analytics.called
        assert len(mock_processor.transformed_data) > 0


def test_pipeline_fails_on_missing_dependency(mock_processor):
    """Test pipeline fails gracefully when dependency missing."""
    
    # Create dependency check failure result (dict with 'details' key)
    dependency_check_failure = {
        'all_critical_present': False,
        'missing': ['nba_raw.nbac_team_boxscore'],
        'stale_fail': [],
        'details': {  # Changed from 'dependency_details' to 'details'
            'nba_raw.nbac_team_boxscore': {
                'exists': False,
                'row_count': 0,
                'age_hours': None,
                'last_updated': None,
                'error': 'Table not found'
            }
        }
    }
    
    # Mock dependency check to fail
    mock_processor.check_dependencies = Mock(return_value=dependency_check_failure)
    
    result = mock_processor.run({
        'start_date': '2024-10-21',
        'end_date': '2024-10-21'
    })
    
    assert result is False


def test_pipeline_processes_multiple_games(mock_processor):
    """Test pipeline processes multiple games correctly."""
    
    # Create multiple games
    multi_game_data = pd.DataFrame([
        {
            'game_id': f'2024102{i}LAL_GSW',
            'game_date': date(2024, 10, 21+i),
            'season_year': 2024,
            'nba_game_id': f'002240012{i}',
            'defending_team_abbr': 'LAL',
            'opponent_team_abbr': 'GSW',
            'home_game': True,
            'points_allowed': 100 + i,
            'opp_fg_makes': 45,
            'opp_fg_attempts': 92,
            'opp_three_pt_makes': 15,
            'opp_three_pt_attempts': 40,
            'opp_ft_makes': 3,
            'opp_ft_attempts': 5,
            'opp_rebounds': 48,
            'opp_assists': 28,
            'turnovers_forced': 12,
            'fouls_committed': 20,
            'steals': 8,
            'blocks_total': 5,
            'defensive_rebounds': 38,
            'blocks_paint': 0,
            'blocks_mid_range': 0,
            'blocks_three_pt': 0,
            'defensive_rating': 100.0 + i,
            'opponent_pace': 100.0,
            'opponent_ts_pct': 0.56,
            'possessions': 100,
            'win_flag': True,
            'margin_of_victory': 4,
            'overtime_periods': 0,
            'opp_paint_attempts': None,
            'opp_paint_makes': None,
            'opp_mid_range_attempts': None,
            'opp_mid_range_makes': None,
            'points_in_paint_allowed': None,
            'second_chance_points_allowed': None,
            'players_inactive': 0,
            'starters_inactive': 0,
            'referee_crew_id': None,
            'data_quality_tier': 'high',
            'primary_source_used': 'nba_api',
            'defensive_actions_source': 'nbac_gamebook'
        }
        for i in range(5)
    ])
    
    # Mock extract_raw_data to set raw_data
    def mock_extract():
        mock_processor.raw_data = multi_game_data
    
    with patch.object(mock_processor, 'extract_raw_data', side_effect=mock_extract):
        # Mock build_source_tracking_fields
        mock_processor.build_source_tracking_fields = Mock(return_value={})
        
        result = mock_processor.run({
            'start_date': '2024-10-21',
            'end_date': '2024-10-25'
        })
        
        assert result is True
        assert len(mock_processor.transformed_data) == 5


def test_pipeline_tracks_processing_time(
    mock_processor,
    sample_raw_extracted_data
):
    """Test pipeline tracks processing time correctly."""
    
    # Mock extract_raw_data to set raw_data
    def mock_extract():
        mock_processor.raw_data = sample_raw_extracted_data
    
    with patch.object(mock_processor, 'extract_raw_data', side_effect=mock_extract):
        # Mock build_source_tracking_fields
        mock_processor.build_source_tracking_fields = Mock(return_value={})
        
        result = mock_processor.run({
            'start_date': '2024-10-21',
            'end_date': '2024-10-21'
        })
        
        assert result is True
        assert 'extract_time' in mock_processor.stats
        assert 'transform_time' in mock_processor.stats
        assert 'total_runtime' in mock_processor.stats


def test_pipeline_logs_processing_run(
    mock_processor,
    sample_raw_extracted_data
):
    """Test pipeline logs processing run to monitoring table."""
    
    # Mock extract_raw_data to set raw_data
    def mock_extract():
        mock_processor.raw_data = sample_raw_extracted_data
    
    with patch.object(mock_processor, 'extract_raw_data', side_effect=mock_extract):
        # Mock build_source_tracking_fields
        mock_processor.build_source_tracking_fields = Mock(return_value={})
        
        result = mock_processor.run({
            'start_date': '2024-10-21',
            'end_date': '2024-10-21'
        })
        
        assert result is True
        # Should log success
        mock_processor.log_processing_run.assert_called_with(success=True)
"""
Path: tests/processors/analytics/team_offense_game_summary/test_integration.py

Integration Tests for Team Offense Game Summary Processor

Tests full processor flow with mocked BigQuery.
Run with: pytest test_integration.py -v

FIXES APPLIED:
1. Mock BigQuery client at analytics_base level to prevent real BQ calls
2. Mock notifications at analytics_base level where they're actually called
3. Set source tracking attributes manually since check_dependencies is mocked
4. Use MagicMock for all BigQuery operations
"""

import pytest
import pandas as pd
from datetime import date, datetime, timezone
from unittest.mock import Mock, MagicMock, patch, call
from io import BytesIO

# Import processor
from data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor import (
    TeamOffenseGameSummaryProcessor
)


class TestFullProcessorFlow:
    """Test complete processor flow from extraction to save."""
    
    @pytest.fixture
    def sample_team_boxscore_data(self):
        """Create sample team boxscore data."""
        return pd.DataFrame([
            {
                'game_id': '20250115_LAL_BOS',
                'nba_game_id': '0022400123',
                'game_date': date(2025, 1, 15),
                'season_year': 2024,
                'team_abbr': 'LAL',
                'team_name': 'Los Angeles Lakers',
                'is_home': False,
                'opponent_team_abbr': 'BOS',
                'opponent_points': 105,
                'points': 110,
                'fg_made': 40,
                'fg_attempted': 85,
                'fg_percentage': 0.471,
                'three_pt_made': 12,
                'three_pt_attempted': 30,
                'three_pt_percentage': 0.400,
                'ft_made': 18,
                'ft_attempted': 22,
                'ft_percentage': 0.818,
                'offensive_rebounds': 8,
                'defensive_rebounds': 32,
                'total_rebounds': 40,
                'assists': 25,
                'steals': 7,
                'blocks': 5,
                'turnovers': 12,
                'personal_fouls': 18,
                'plus_minus': 5,
                'minutes': '240:00',
                'source_last_updated': datetime(2025, 1, 15, 10, 0, 0),
                'processed_at': datetime(2025, 1, 15, 10, 0, 0)
            },
            {
                'game_id': '20250115_LAL_BOS',
                'nba_game_id': '0022400123',
                'game_date': date(2025, 1, 15),
                'season_year': 2024,
                'team_abbr': 'BOS',
                'team_name': 'Boston Celtics',
                'is_home': True,
                'opponent_team_abbr': 'LAL',
                'opponent_points': 110,
                'points': 105,
                'fg_made': 38,
                'fg_attempted': 82,
                'fg_percentage': 0.463,
                'three_pt_made': 15,
                'three_pt_attempted': 35,
                'three_pt_percentage': 0.429,
                'ft_made': 14,
                'ft_attempted': 18,
                'ft_percentage': 0.778,
                'offensive_rebounds': 6,
                'defensive_rebounds': 35,
                'total_rebounds': 41,
                'assists': 22,
                'steals': 8,
                'blocks': 4,
                'turnovers': 15,
                'personal_fouls': 20,
                'plus_minus': -5,
                'minutes': '240:00',
                'source_last_updated': datetime(2025, 1, 15, 10, 0, 0),
                'processed_at': datetime(2025, 1, 15, 10, 0, 0)
            }
        ])
    
    @pytest.fixture
    def shot_zone_data(self):
        """Create sample shot zone data."""
        return pd.DataFrame([
            {
                'game_id': '20250115_LAL_BOS',
                'team_abbr': 'LAL',
                'paint_attempts': 35,
                'paint_makes': 20,
                'points_in_paint': 40,
                'mid_range_attempts': 20,
                'mid_range_makes': 8,
                'three_attempts_pbp': 30,
                'three_makes_pbp': 12
            },
            {
                'game_id': '20250115_LAL_BOS',
                'team_abbr': 'BOS',
                'paint_attempts': 30,
                'paint_makes': 18,
                'points_in_paint': 36,
                'mid_range_attempts': 17,
                'mid_range_makes': 5,
                'three_attempts_pbp': 35,
                'three_makes_pbp': 15
            }
        ])
    
    @patch('data_processors.analytics.analytics_base.bigquery.Client')
    def test_successful_processing_with_shot_zones(
        self, 
        mock_bq_client_class,
        sample_team_boxscore_data,
        shot_zone_data
    ):
        """Test successful processing with shot zones available."""
        # Create mock BigQuery client
        mock_bq_client = MagicMock()
        mock_bq_client_class.return_value = mock_bq_client
        
        # Setup query responses
        mock_queries = [
            sample_team_boxscore_data,  # Team boxscore query
            shot_zone_data              # Shot zone query
        ]
        
        def query_side_effect(query_str):
            mock_job = MagicMock()
            mock_job.to_dataframe.return_value = mock_queries.pop(0) if mock_queries else pd.DataFrame()
            return mock_job
        
        mock_bq_client.query.side_effect = query_side_effect
        
        # Mock get_table for save
        mock_table = MagicMock()
        mock_table.schema = []
        mock_bq_client.get_table.return_value = mock_table
        
        # Mock load_table_from_file for save
        mock_load_job = MagicMock()
        mock_load_job.result.return_value = None
        mock_bq_client.load_table_from_file.return_value = mock_load_job
        
        # Create processor
        processor = TeamOffenseGameSummaryProcessor()
        
        # Mock dependency check result
        mock_dep_check = {
            'all_critical_present': True,
            'all_fresh': True,
            'has_stale_fail': False,
            'has_stale_warn': False,
            'missing': [],
            'stale_fail': [],
            'stale_warn': [],
            'details': {
                'nba_raw.nbac_team_boxscore': {
                    'exists': True,
                    'row_count': 2,
                    'expected_count_min': 20,
                    'age_hours': 1.0,
                    'last_updated': '2025-01-15T10:00:00Z'
                },
                'nba_raw.nbac_play_by_play': {
                    'exists': True,
                    'row_count': 500,
                    'expected_count_min': 1000,
                    'age_hours': 2.0,
                    'last_updated': '2025-01-15T11:00:00Z'
                }
            }
        }
        
        # Create a side effect function that sets source tracking attributes
        def mock_track_source_usage(*args, **kwargs):
            processor.source_nbac_boxscore_last_updated = '2025-01-15T10:00:00Z'
            processor.source_nbac_boxscore_rows_found = 2
            processor.source_nbac_boxscore_completeness_pct = 100.0
            processor.source_play_by_play_last_updated = '2025-01-15T11:00:00Z'
            processor.source_play_by_play_rows_found = 500
            processor.source_play_by_play_completeness_pct = 50.0
        
        # Mock check_dependencies and track_source_usage with side effect
        with patch.object(processor, 'check_dependencies', return_value=mock_dep_check), \
             patch.object(processor, 'track_source_usage', side_effect=mock_track_source_usage):
            
            # Run processor (track_source_usage will set attributes via side effect)
            success = processor.run({
                'start_date': '2025-01-15',
                'end_date': '2025-01-15'
            })
        
        # Verify success
        assert success is True, f"Processor run failed. Transformed data count: {len(processor.transformed_data)}"
        
        # Verify data was extracted
        assert len(processor.raw_data) == 2, f"Expected 2 raw data rows, got {len(processor.raw_data)}"
        
        # Verify shot zones were extracted
        assert processor.shot_zones_available is True, "Shot zones should be available"
        assert processor.shot_zones_source == 'nbac_pbp', f"Shot zones source should be 'nbac_pbp', got {processor.shot_zones_source}"
        assert len(processor.shot_zone_data) == 2, f"Expected 2 shot zone records, got {len(processor.shot_zone_data)}"
        
        # Verify analytics were calculated
        assert len(processor.transformed_data) == 2, f"Expected 2 transformed records, got {len(processor.transformed_data)}"
        
        # Verify source tracking was populated
        lal_record = [r for r in processor.transformed_data if r['team_abbr'] == 'LAL'][0]
        assert 'source_nbac_boxscore_last_updated' in lal_record, "Missing source tracking field"
        assert 'source_play_by_play_last_updated' in lal_record, "Missing play-by-play source tracking"
        
        # Verify calculations
        assert lal_record['points_scored'] == 110, f"Expected points_scored=110, got {lal_record['points_scored']}"
        assert lal_record['win_flag'] is True, "LAL should have won (110-105)"
        assert lal_record['home_game'] is False, "LAL should be away"
        assert lal_record['overtime_periods'] == 0, "Should be regulation game"
        assert lal_record['data_quality_tier'] == 'high', f"Expected 'high' quality tier, got {lal_record['data_quality_tier']}"
        
        # Verify shot zones in record
        assert lal_record['team_paint_attempts'] == 35, f"Expected 35 paint attempts, got {lal_record['team_paint_attempts']}"
        assert lal_record['team_paint_makes'] == 20, f"Expected 20 paint makes, got {lal_record['team_paint_makes']}"
        
        # Verify advanced metrics calculated
        assert lal_record['possessions'] is not None, "Possessions should be calculated"
        assert lal_record['offensive_rating'] is not None, "Offensive rating should be calculated"
        assert lal_record['pace'] is not None, "Pace should be calculated"
        assert lal_record['ts_pct'] is not None, "True shooting % should be calculated"
        
        # Verify save was called
        assert mock_bq_client.load_table_from_file.called, "Should save data to BigQuery"
    
    @patch('data_processors.analytics.analytics_base.bigquery.Client')
    def test_processing_without_shot_zones(
        self, 
        mock_bq_client_class,
        sample_team_boxscore_data
    ):
        """Test processing when shot zones unavailable."""
        # Create mock BigQuery client
        mock_bq_client = MagicMock()
        mock_bq_client_class.return_value = mock_bq_client
        
        # Setup query response (only boxscore, no shot zones query)
        mock_job = MagicMock()
        mock_job.to_dataframe.return_value = sample_team_boxscore_data
        mock_bq_client.query.return_value = mock_job
        
        # Mock get_table for save
        mock_table = MagicMock()
        mock_table.schema = []
        mock_bq_client.get_table.return_value = mock_table
        
        # Mock load_table_from_file
        mock_load_job = MagicMock()
        mock_load_job.result.return_value = None
        mock_bq_client.load_table_from_file.return_value = mock_load_job
        
        # Create processor
        processor = TeamOffenseGameSummaryProcessor()
        
        # Mock dependency check - play-by-play missing
        mock_dep_check = {
            'all_critical_present': True,
            'all_fresh': True,
            'has_stale_fail': False,
            'has_stale_warn': False,
            'missing': [],
            'stale_fail': [],
            'stale_warn': [],
            'details': {
                'nba_raw.nbac_team_boxscore': {
                    'exists': True,
                    'row_count': 2,
                    'age_hours': 1.0,
                    'last_updated': '2025-01-15T10:00:00Z'
                },
                'nba_raw.nbac_play_by_play': {
                    'exists': False,
                    'row_count': 0,
                    'age_hours': None,
                    'last_updated': None
                }
            }
        }
        
        # Create a side effect that sets attributes with play-by-play missing
        def mock_track_source_usage(*args, **kwargs):
            processor.source_nbac_boxscore_last_updated = '2025-01-15T10:00:00Z'
            processor.source_nbac_boxscore_rows_found = 2
            processor.source_nbac_boxscore_completeness_pct = 100.0
            processor.source_play_by_play_last_updated = None
            processor.source_play_by_play_rows_found = 0  # No play-by-play data
            processor.source_play_by_play_completeness_pct = None
        
        with patch.object(processor, 'check_dependencies', return_value=mock_dep_check), \
             patch.object(processor, 'track_source_usage', side_effect=mock_track_source_usage):
            success = processor.run({
                'start_date': '2025-01-15',
                'end_date': '2025-01-15'
            })
        
        assert success is True
        
        # Verify shot zones NOT available
        assert processor.shot_zones_available is False, "Shot zones should not be available"
        assert processor.shot_zones_source is None, "Shot zones source should be None"
        assert len(processor.shot_zone_data) == 0, f"Shot zone data should be empty, got {len(processor.shot_zone_data)}"
        
        # Verify records created
        assert len(processor.transformed_data) == 2
        
        # Verify shot zone fields are NULL
        lal_record = [r for r in processor.transformed_data if r['team_abbr'] == 'LAL'][0]
        assert lal_record['team_paint_attempts'] is None, "Paint attempts should be None without shot zones"
        assert lal_record['team_paint_makes'] is None, "Paint makes should be None without shot zones"
        assert lal_record['data_quality_tier'] == 'medium', f"Expected 'medium' quality tier, got {lal_record['data_quality_tier']}"
    
    @patch('data_processors.analytics.analytics_base.notify_error')
    @patch('data_processors.analytics.analytics_base.bigquery.Client')
    def test_missing_critical_dependency_fails(
        self,
        mock_bq_client_class,
        mock_notify_error
    ):
        """Test that missing critical dependency causes failure."""
        # Create mock BigQuery client
        mock_bq_client = MagicMock()
        mock_bq_client_class.return_value = mock_bq_client
        
        # Create processor
        processor = TeamOffenseGameSummaryProcessor()
        
        # Mock dependency check - team boxscore missing (CRITICAL)
        mock_dep_check = {
            'all_critical_present': False,  # ❌ Critical dependency missing
            'all_fresh': True,
            'has_stale_fail': False,
            'has_stale_warn': False,
            'missing': ['nba_raw.nbac_team_boxscore'],
            'stale_fail': [],
            'stale_warn': [],
            'details': {
                'nba_raw.nbac_team_boxscore': {
                    'exists': False,
                    'row_count': 0
                },
                'nba_raw.nbac_play_by_play': {
                    'exists': True,
                    'row_count': 500
                }
            }
        }
        
        with patch.object(processor, 'check_dependencies', return_value=mock_dep_check):
            success = processor.run({
                'start_date': '2025-01-15',
                'end_date': '2025-01-15'
            })
        
        # Should fail
        assert success is False, "Processor should fail when critical dependency is missing"
        
        # Should send error notification (called from analytics_base.py)
        assert mock_notify_error.called, "Should call notify_error when critical dependency missing"


class TestOvertimeGamesProcessing:
    """Test processing games with overtime periods."""
    
    @pytest.fixture
    def overtime_game_data(self):
        """Create sample overtime game data."""
        return pd.DataFrame([
            {
                'game_id': '20250120_GSW_PHX',
                'nba_game_id': '0022400456',
                'game_date': date(2025, 1, 20),
                'season_year': 2024,
                'team_abbr': 'GSW',
                'team_name': 'Golden State Warriors',
                'is_home': False,
                'opponent_team_abbr': 'PHX',
                'opponent_points': 125,
                'points': 128,
                'fg_made': 45,
                'fg_attempted': 92,
                'three_pt_made': 18,
                'three_pt_attempted': 40,
                'ft_made': 20,
                'ft_attempted': 24,
                'offensive_rebounds': 10,
                'defensive_rebounds': 35,
                'total_rebounds': 45,
                'assists': 28,
                'turnovers': 14,
                'personal_fouls': 22,
                'minutes': '265:00',  # 1 OT
                'processed_at': datetime(2025, 1, 20, 12, 0, 0)
            },
            {
                'game_id': '20250120_GSW_PHX',
                'nba_game_id': '0022400456',
                'game_date': date(2025, 1, 20),
                'season_year': 2024,
                'team_abbr': 'PHX',
                'team_name': 'Phoenix Suns',
                'is_home': True,
                'opponent_team_abbr': 'GSW',
                'opponent_points': 128,
                'points': 125,
                'fg_made': 43,
                'fg_attempted': 88,
                'three_pt_made': 16,
                'three_pt_attempted': 38,
                'ft_made': 23,
                'ft_attempted': 28,
                'offensive_rebounds': 8,
                'defensive_rebounds': 38,
                'total_rebounds': 46,
                'assists': 25,
                'turnovers': 16,
                'personal_fouls': 24,
                'minutes': '265:00',  # 1 OT
                'processed_at': datetime(2025, 1, 20, 12, 0, 0)
            }
        ])
    
    def test_overtime_period_detection(self, overtime_game_data):
        """Test that overtime periods are detected correctly."""
        processor = TeamOffenseGameSummaryProcessor()
        processor.raw_data = overtime_game_data
        
        # Set source tracking attributes
        processor.source_nbac_boxscore_last_updated = '2025-01-20T12:00:00Z'
        processor.source_nbac_boxscore_rows_found = 2
        processor.source_nbac_boxscore_completeness_pct = 100.0
        processor.source_play_by_play_last_updated = None
        processor.source_play_by_play_rows_found = 0
        processor.source_play_by_play_completeness_pct = None
        processor.shot_zones_available = False
        
        # Calculate analytics
        processor.calculate_analytics()
        
        # Verify OT periods detected
        gsw_record = [r for r in processor.transformed_data if r['team_abbr'] == 'GSW'][0]
        assert gsw_record['overtime_periods'] == 1, f"Expected 1 OT period, got {gsw_record['overtime_periods']}"
        
        phx_record = [r for r in processor.transformed_data if r['team_abbr'] == 'PHX'][0]
        assert phx_record['overtime_periods'] == 1, f"Expected 1 OT period, got {phx_record['overtime_periods']}"
    
    def test_pace_calculation_adjusted_for_ot(self, overtime_game_data):
        """Test that pace calculation uses actual minutes (265 for OT)."""
        processor = TeamOffenseGameSummaryProcessor()
        processor.raw_data = overtime_game_data
        
        # Set source tracking
        processor.source_nbac_boxscore_last_updated = '2025-01-20T12:00:00Z'
        processor.source_nbac_boxscore_rows_found = 2
        processor.source_nbac_boxscore_completeness_pct = 100.0
        processor.source_play_by_play_last_updated = None
        processor.source_play_by_play_rows_found = 0
        processor.source_play_by_play_completeness_pct = None
        processor.shot_zones_available = False
        
        processor.calculate_analytics()
        
        # Pace should be normalized to 48 minutes
        # Possessions × (48 / actual_game_minutes)
        gsw_record = [r for r in processor.transformed_data if r['team_abbr'] == 'GSW'][0]
        
        # Verify pace is calculated (should be lower than regulation pace for OT games)
        assert gsw_record['pace'] is not None, "Pace should be calculated"
        assert gsw_record['pace'] > 80, f"Pace seems too low: {gsw_record['pace']}"
        assert gsw_record['pace'] < 120, f"Pace seems too high: {gsw_record['pace']}"


class TestMultipleGamesProcessing:
    """Test processing multiple games in one run."""
    
    @pytest.fixture
    def multiple_games_data(self):
        """Create data for multiple games."""
        games = []
        
        # Game 1: LAL vs BOS
        games.extend([
            {'game_id': '20250115_LAL_BOS', 'team_abbr': 'LAL', 'opponent_team_abbr': 'BOS',
             'points': 110, 'opponent_points': 105, 'is_home': False},
            {'game_id': '20250115_LAL_BOS', 'team_abbr': 'BOS', 'opponent_team_abbr': 'LAL',
             'points': 105, 'opponent_points': 110, 'is_home': True}
        ])
        
        # Game 2: GSW vs PHX
        games.extend([
            {'game_id': '20250115_GSW_PHX', 'team_abbr': 'GSW', 'opponent_team_abbr': 'PHX',
             'points': 120, 'opponent_points': 115, 'is_home': True},
            {'game_id': '20250115_GSW_PHX', 'team_abbr': 'PHX', 'opponent_team_abbr': 'GSW',
             'points': 115, 'opponent_points': 120, 'is_home': False}
        ])
        
        # Game 3: MIA vs CHI
        games.extend([
            {'game_id': '20250115_MIA_CHI', 'team_abbr': 'MIA', 'opponent_team_abbr': 'CHI',
             'points': 98, 'opponent_points': 102, 'is_home': False},
            {'game_id': '20250115_MIA_CHI', 'team_abbr': 'CHI', 'opponent_team_abbr': 'MIA',
             'points': 102, 'opponent_points': 98, 'is_home': True}
        ])
        
        # Add required fields to all games
        for i, game in enumerate(games):
            game.update({
                'game_date': date(2025, 1, 15),
                'season_year': 2024,
                'nba_game_id': f'002240{i:04d}',
                'team_name': f'{game["team_abbr"]} Team',
                'fg_made': 40,
                'fg_attempted': 85,
                'three_pt_made': 12,
                'three_pt_attempted': 30,
                'ft_made': 18,
                'ft_attempted': 22,
                'offensive_rebounds': 8,
                'defensive_rebounds': 32,
                'total_rebounds': 40,
                'assists': 25,
                'turnovers': 12,
                'personal_fouls': 18,
                'minutes': '240:00',
                'processed_at': datetime(2025, 1, 15, 10, 0, 0)
            })
        
        return pd.DataFrame(games)
    
    def test_processes_all_games(self, multiple_games_data):
        """Test that all games are processed correctly."""
        processor = TeamOffenseGameSummaryProcessor()
        processor.raw_data = multiple_games_data
        
        # Set source tracking
        processor.source_nbac_boxscore_last_updated = '2025-01-15T10:00:00Z'
        processor.source_nbac_boxscore_rows_found = 6
        processor.source_nbac_boxscore_completeness_pct = 100.0
        processor.source_play_by_play_last_updated = None
        processor.source_play_by_play_rows_found = 0
        processor.source_play_by_play_completeness_pct = None
        processor.shot_zones_available = False
        
        processor.calculate_analytics()
        
        # Should have 6 team-game records (3 games × 2 teams)
        assert len(processor.transformed_data) == 6, f"Expected 6 records, got {len(processor.transformed_data)}"
        
        # Verify unique game_ids
        game_ids = {r['game_id'] for r in processor.transformed_data}
        assert len(game_ids) == 3, f"Expected 3 unique games, got {len(game_ids)}"
        
        # Verify unique teams
        teams = {r['team_abbr'] for r in processor.transformed_data}
        assert len(teams) == 6, f"Expected 6 unique teams, got {len(teams)}"
    
    def test_win_loss_consistency_across_games(self, multiple_games_data):
        """Test that win/loss flags are consistent for each game."""
        processor = TeamOffenseGameSummaryProcessor()
        processor.raw_data = multiple_games_data
        
        # Set source tracking
        processor.source_nbac_boxscore_last_updated = '2025-01-15T10:00:00Z'
        processor.source_nbac_boxscore_rows_found = 6
        processor.source_nbac_boxscore_completeness_pct = 100.0
        processor.source_play_by_play_last_updated = None
        processor.source_play_by_play_rows_found = 0
        processor.source_play_by_play_completeness_pct = None
        processor.shot_zones_available = False
        
        processor.calculate_analytics()
        
        # For each game, one team should win, one should lose
        for game_id in ['20250115_LAL_BOS', '20250115_GSW_PHX', '20250115_MIA_CHI']:
            game_records = [r for r in processor.transformed_data if r['game_id'] == game_id]
            assert len(game_records) == 2, f"Expected 2 records for {game_id}, got {len(game_records)}"
            
            # One winner, one loser
            win_flags = [r['win_flag'] for r in game_records]
            assert True in win_flags, f"No winner in game {game_id}"
            assert False in win_flags, f"No loser in game {game_id}"
            assert len([w for w in win_flags if w]) == 1, f"Should have exactly 1 winner in {game_id}"


class TestErrorHandling:
    """Test error handling and edge cases."""
    
    def test_empty_dataset_handling(self):
        """Test handling of empty dataset."""
        processor = TeamOffenseGameSummaryProcessor()
        processor.raw_data = pd.DataFrame()  # Empty
        
        # Set source tracking
        processor.source_nbac_boxscore_last_updated = '2025-01-15T10:00:00Z'
        processor.source_nbac_boxscore_rows_found = 0
        processor.source_nbac_boxscore_completeness_pct = 0.0
        processor.source_play_by_play_last_updated = None
        processor.source_play_by_play_rows_found = 0
        processor.source_play_by_play_completeness_pct = None
        processor.shot_zones_available = False
        
        # Should not crash
        processor.calculate_analytics()
        
        # Should have empty transformed data
        assert len(processor.transformed_data) == 0
    
    @patch('data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor.notify_warning')
    def test_high_processing_error_rate_notification(self, mock_notify_warning):
        """Test notification when processing error rate is high."""
        processor = TeamOffenseGameSummaryProcessor()
        
        # Create data that will cause errors (missing required fields)
        processor.raw_data = pd.DataFrame([
            {'game_id': f'game_{i}', 'team_abbr': f'TEAM{i}'}
            for i in range(20)
        ])
        
        # Set source tracking
        processor.source_nbac_boxscore_last_updated = '2025-01-15T10:00:00Z'
        processor.source_nbac_boxscore_rows_found = 20
        processor.source_nbac_boxscore_completeness_pct = 100.0
        processor.source_play_by_play_last_updated = None
        processor.source_play_by_play_rows_found = 0
        processor.source_play_by_play_completeness_pct = None
        processor.shot_zones_available = False
        
        # Process (will have errors due to missing fields)
        processor.calculate_analytics()
        
        # Should send warning notification about high error rate
        assert mock_notify_warning.called, "Should send warning notification for high error rate"


# ============================================================================
# Test Summary
# ============================================================================
# Total Tests: 9 integration tests
# Coverage: Full end-to-end flows with proper mocking
# Runtime: ~2-5 seconds
#
# FIXES APPLIED:
# 1. Mock BigQuery client at module import level (analytics_base.bigquery.Client)
# 2. Mock notifications at base class level (analytics_base.notify_error)
# 3. Set source tracking attributes manually in each test
# 4. Use MagicMock for all BigQuery operations
#
# Test Distribution:
# - Full processor flow: 3 tests
# - Overtime games: 2 tests
# - Multiple games: 2 tests
# - Error handling: 2 tests
#
# Run with:
#   pytest test_integration.py -v
#   pytest test_integration.py::TestFullProcessorFlow -v
#   python run_tests.py integration --verbose
# ============================================================================
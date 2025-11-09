# predictions/coordinator/tests/test_player_loader.py

"""
Test suite for PlayerLoader class

Tests BigQuery queries, request creation, betting line logic,
and validation utilities in the coordinator's player loader.
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from coordinator.player_loader import (
    PlayerLoader,
    validate_game_date,
    get_nba_season,
    create_manual_prediction_request
)
from .conftest import create_mock_bigquery_row


class TestPlayerLoader:
    """Test suite for PlayerLoader class"""
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_init(self, mock_client_class):
        """Test PlayerLoader initialization"""
        mock_client = Mock()
        mock_client.project = 'test-project'
        mock_client_class.return_value = mock_client
        
        loader = PlayerLoader('test-project')
        
        assert loader.project_id == 'test-project'
        assert loader.client is not None
        mock_client_class.assert_called_once_with(project='test-project')
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_get_summary_stats(self, mock_client_class, sample_game_date, sample_summary_stats):
        """Test get_summary_stats returns expected structure"""
        # Setup mock
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        mock_result = create_mock_bigquery_row(
            total_games=15,
            total_players=450,
            teams_playing=30,
            avg_projected_minutes=28.5,
            min_projected_minutes=10.0,
            max_projected_minutes=38.0,
            pg_count=90,
            sg_count=90,
            sf_count=90,
            pf_count=90,
            c_count=90
        )
        
        mock_query_job = Mock()
        mock_query_job.result.return_value = iter([mock_result])
        mock_client.query.return_value = mock_query_job
        
        # Test
        loader = PlayerLoader('test-project')
        stats = loader.get_summary_stats(sample_game_date)
        
        # Assertions
        assert stats['total_games'] == 15
        assert stats['total_players'] == 450
        assert stats['teams_playing'] == 30
        assert stats['avg_projected_minutes'] == 28.5
        assert stats['players_by_position']['PG'] == 90
        assert stats['players_by_position']['C'] == 90
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_get_summary_stats_no_data(self, mock_client_class, sample_game_date):
        """Test get_summary_stats handles no data gracefully"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        mock_query_job = Mock()
        mock_query_job.result.return_value = iter([])  # No results
        mock_client.query.return_value = mock_query_job
        
        loader = PlayerLoader('test-project')
        stats = loader.get_summary_stats(sample_game_date)
        
        assert stats['total_games'] == 0
        assert stats['total_players'] == 0
        assert 'game_date' in stats
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_create_prediction_requests(self, mock_client_class, sample_game_date, sample_players):
        """Test create_prediction_requests returns correct structure"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        # Mock query results
        mock_rows = [create_mock_bigquery_row(**player) for player in sample_players]
        mock_query_job = Mock()
        mock_query_job.result.return_value = iter(mock_rows)
        mock_client.query.return_value = mock_query_job
        
        # Test
        loader = PlayerLoader('test-project')
        requests = loader.create_prediction_requests(
            game_date=sample_game_date,
            min_minutes=15,
            use_multiple_lines=False
        )
        
        # Assertions
        assert len(requests) == 3
        assert requests[0]['player_lookup'] == 'lebron-james'
        assert requests[0]['game_id'] == '20251108_LAL_GSW'
        assert 'line_values' in requests[0]
        assert isinstance(requests[0]['line_values'], list)
        assert len(requests[0]['line_values']) >= 1
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_create_prediction_requests_multiple_lines(self, mock_client_class, sample_game_date, sample_players):
        """Test create_prediction_requests with multiple lines enabled"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        mock_rows = [create_mock_bigquery_row(**sample_players[0])]
        mock_query_job = Mock()
        mock_query_job.result.return_value = iter(mock_rows)
        mock_client.query.return_value = mock_query_job
        
        loader = PlayerLoader('test-project')
        requests = loader.create_prediction_requests(
            game_date=sample_game_date,
            min_minutes=15,
            use_multiple_lines=True
        )
        
        # Should have 5 lines per player (base ± 2)
        assert len(requests[0]['line_values']) == 5
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_create_prediction_requests_invalid_date(self, mock_client_class):
        """Test create_prediction_requests rejects invalid dates"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        loader = PlayerLoader('test-project')
        
        # Past date (invalid)
        past_date = date.today() - timedelta(days=5)
        requests = loader.create_prediction_requests(past_date)
        
        assert len(requests) == 0
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_validate_player_exists_true(self, mock_client_class, sample_game_date):
        """Test validate_player_exists returns True when player exists"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        mock_result = create_mock_bigquery_row(count=1)
        mock_query_job = Mock()
        mock_query_job.result.return_value = iter([mock_result])
        mock_client.query.return_value = mock_query_job
        
        loader = PlayerLoader('test-project')
        exists = loader.validate_player_exists('lebron-james', sample_game_date)
        
        assert exists is True
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_validate_player_exists_false(self, mock_client_class, sample_game_date):
        """Test validate_player_exists returns False when player doesn't exist"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        mock_result = create_mock_bigquery_row(count=0)
        mock_query_job = Mock()
        mock_query_job.result.return_value = iter([mock_result])
        mock_client.query.return_value = mock_query_job
        
        loader = PlayerLoader('test-project')
        exists = loader.validate_player_exists('fake-player', sample_game_date)
        
        assert exists is False
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_get_players_for_game(self, mock_client_class):
        """Test get_players_for_game returns players for specific game"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        mock_rows = [
            create_mock_bigquery_row(
                player_lookup='lebron-james',
                team_abbr='LAL',
                opponent_team_abbr='GSW',
                projected_minutes=35.0,
                position='SF',
                injury_status=None
            ),
            create_mock_bigquery_row(
                player_lookup='anthony-davis',
                team_abbr='LAL',
                opponent_team_abbr='GSW',
                projected_minutes=34.0,
                position='PF',
                injury_status=None
            )
        ]
        
        mock_query_job = Mock()
        mock_query_job.result.return_value = iter(mock_rows)
        mock_client.query.return_value = mock_query_job
        
        loader = PlayerLoader('test-project')
        players = loader.get_players_for_game('20251108_LAL_GSW')
        
        assert len(players) == 2
        assert players[0]['player_lookup'] == 'lebron-james'
        assert players[0]['team_abbr'] == 'LAL'
        assert players[1]['player_lookup'] == 'anthony-davis'
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_query_actual_betting_line_found(self, mock_client_class, sample_game_date):
        """Test _query_actual_betting_line finds line from odds data"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        mock_result = create_mock_bigquery_row(line_value=25.5)
        mock_query_job = Mock()
        mock_query_job.result.return_value = iter([mock_result])
        mock_client.query.return_value = mock_query_job
        
        loader = PlayerLoader('test-project')
        line = loader._query_actual_betting_line('lebron-james', sample_game_date)
        
        assert line == 25.5
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_query_actual_betting_line_not_found(self, mock_client_class, sample_game_date):
        """Test _query_actual_betting_line returns None when no line"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        mock_query_job = Mock()
        mock_query_job.result.return_value = iter([])  # No results
        mock_client.query.return_value = mock_query_job
        
        loader = PlayerLoader('test-project')
        line = loader._query_actual_betting_line('unknown-player', sample_game_date)
        
        assert line is None
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_estimate_betting_line_from_season_avg(self, mock_client_class):
        """Test _estimate_betting_line uses season average"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        mock_result = create_mock_bigquery_row(points_avg_season=27.3)
        mock_query_job = Mock()
        mock_query_job.result.return_value = iter([mock_result])
        mock_client.query.return_value = mock_query_job
        
        loader = PlayerLoader('test-project')
        line = loader._estimate_betting_line('lebron-james')
        
        # Should round to nearest 0.5
        assert line == 27.5
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_estimate_betting_line_default(self, mock_client_class):
        """Test _estimate_betting_line returns default when no data"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        mock_query_job = Mock()
        mock_query_job.result.return_value = iter([])  # No results
        mock_client.query.return_value = mock_query_job
        
        loader = PlayerLoader('test-project')
        line = loader._estimate_betting_line('unknown-player')
        
        assert line == 15.5  # Default fallback


class TestUtilityFunctions:
    """Test utility functions in player_loader"""
    
    def test_validate_game_date_today(self):
        """Test validate_game_date accepts today"""
        today = date.today()
        assert validate_game_date(today) is True
    
    def test_validate_game_date_tomorrow(self):
        """Test validate_game_date accepts tomorrow"""
        tomorrow = date.today() + timedelta(days=1)
        assert validate_game_date(tomorrow) is True
    
    def test_validate_game_date_future(self):
        """Test validate_game_date accepts near future"""
        future = date.today() + timedelta(days=7)
        assert validate_game_date(future) is True
    
    def test_validate_game_date_too_far_future(self):
        """Test validate_game_date rejects far future"""
        far_future = date.today() + timedelta(days=30)
        assert validate_game_date(far_future) is False
    
    def test_validate_game_date_past(self):
        """Test validate_game_date rejects past dates"""
        past = date.today() - timedelta(days=2)
        assert validate_game_date(past) is False
    
    def test_get_nba_season_regular(self):
        """Test get_nba_season returns correct format"""
        test_date = date(2024, 11, 15)  # November (regular season)
        season = get_nba_season(test_date)
        assert season == '2024-25'
    
    def test_get_nba_season_playoffs(self):
        """Test get_nba_season during playoffs"""
        test_date = date(2025, 5, 15)  # May (playoffs)
        season = get_nba_season(test_date)
        assert season == '2024-25'
    
    def test_get_nba_season_summer(self):
        """Test get_nba_season in offseason"""
        test_date = date(2024, 8, 15)  # August (offseason)
        season = get_nba_season(test_date)
        assert season == '2024-25'  # Next season starting in October
    
    def test_create_manual_prediction_request(self):
        """Test create_manual_prediction_request creates valid request"""
        request = create_manual_prediction_request(
            player_lookup='lebron-james',
            game_date=date(2025, 11, 8),
            game_id='20251108_LAL_GSW',
            line_values=[25.5, 26.5]
        )
        
        assert request['player_lookup'] == 'lebron-james'
        assert request['game_date'] == '2025-11-08'
        assert request['game_id'] == '20251108_LAL_GSW'
        assert request['line_values'] == [25.5, 26.5]
    
    def test_create_manual_prediction_request_string_date(self):
        """Test create_manual_prediction_request handles string dates"""
        request = create_manual_prediction_request(
            player_lookup='lebron-james',
            game_date='2025-11-08',
            game_id='20251108_LAL_GSW',
            line_values=[25.5]
        )
        
        assert request['game_date'] == '2025-11-08'


class TestBettingLineGeneration:
    """Test betting line generation logic"""
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_get_betting_lines_single(self, mock_client_class, sample_game_date):
        """Test _get_betting_lines returns single line"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        # Mock no actual line found, will use estimate
        mock_query_job = Mock()
        mock_query_job.result.return_value = iter([])
        mock_client.query.return_value = mock_query_job
        
        loader = PlayerLoader('test-project')
        lines = loader._get_betting_lines('test-player', sample_game_date, use_multiple_lines=False)
        
        assert len(lines) == 1
        assert isinstance(lines[0], float)
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_get_betting_lines_multiple(self, mock_client_class, sample_game_date):
        """Test _get_betting_lines returns 5 lines when enabled"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        # Need to mock TWO queries:
        # 1. _query_actual_betting_line (returns empty - no odds)
        # 2. _estimate_betting_line (returns 25.0)
        
        mock_empty_result = Mock()
        mock_empty_result.result.return_value = iter([])  # No actual line
        
        mock_season_avg = create_mock_bigquery_row(points_avg_season=25.0)
        mock_avg_result = Mock()
        mock_avg_result.result.return_value = iter([mock_season_avg])
        
        # First call returns empty, second returns season avg
        mock_client.query.side_effect = [mock_empty_result, mock_avg_result]
        
        loader = PlayerLoader('test-project')
        lines = loader._get_betting_lines('test-player', sample_game_date, use_multiple_lines=True)
        
        assert len(lines) == 5
        # Should be 23.0, 24.0, 25.0, 26.0, 27.0
        assert lines[0] == 23.0
        assert lines[2] == 25.0
        assert lines[4] == 27.0
    
    @patch('coordinator.player_loader.bigquery.Client')
    def test_get_betting_lines_uses_actual_over_estimate(self, mock_client_class, sample_game_date):
        """Test _get_betting_lines prefers actual line over estimate"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        # First call: query_actual_betting_line (returns 28.5)
        # Second call: estimate_betting_line (should not be called)
        mock_actual_result = create_mock_bigquery_row(line_value=28.5)
        
        def side_effect(*args, **kwargs):
            # First query returns actual line
            mock_job = Mock()
            mock_job.result.return_value = iter([mock_actual_result])
            return mock_job
        
        mock_client.query.side_effect = side_effect
        
        loader = PlayerLoader('test-project')
        lines = loader._get_betting_lines('test-player', sample_game_date, use_multiple_lines=False)
        
        assert len(lines) == 1
        assert lines[0] == 28.5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

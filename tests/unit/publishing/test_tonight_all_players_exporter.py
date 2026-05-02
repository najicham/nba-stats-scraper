"""
Unit Tests for TonightAllPlayersExporter

Tests cover:
1. Games query and formatting
2. Player data aggregation
3. Last 10 results calculation
4. Fatigue level classification
5. Player sorting logic
6. Props array structure
7. Empty data handling
8. Mock BigQuery responses
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date

from data_processors.publishing.tonight_all_players_exporter import TonightAllPlayersExporter


class MockBigQueryClient:
    """Mock BigQuery client for testing"""

    def __init__(self):
        self.query_results = []
        self.query_calls = []
        self._results_queue = []

    def query(self, sql, job_config=None):
        """Mock query execution"""
        self.query_calls.append({'sql': sql, 'config': job_config})
        mock_result = Mock()
        if self._results_queue:
            mock_result.result.return_value = self._results_queue.pop(0)
        else:
            mock_result.result.return_value = self.query_results
        return mock_result

    def set_results(self, results):
        """Set results to return from next query"""
        self.query_results = results

    def queue_results(self, *results_list):
        """Queue multiple results for sequential queries"""
        self._results_queue = list(results_list)


class TestTonightAllPlayersExporterInit:
    """Test suite for initialization"""

    def test_initialization(self):
        """Test that exporter initializes correctly"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightAllPlayersExporter()
                assert exporter is not None


class TestGenerateJson:
    """Test suite for generate_json method"""

    def test_generate_json_with_games(self):
        """Test JSON generation with games and players"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                # Queue results for: games, players, last_10
                mock_client.queue_results(
                    # Games query result
                    [
                        {
                            'game_id': '0022500123',
                            'home_team_abbr': 'LAL',
                            'away_team_abbr': 'GSW',
                            'game_status': 1,
                            'game_time': ' 7:30 PM ET',
                            'game_date_est': '2024-12-15T19:30:00'
                        }
                    ],
                    # Players query result
                    [
                        {
                            'player_lookup': 'lebronjames',
                            'player_full_name': 'LeBron James',
                            'game_id': '0022500123',
                            'team_abbr': 'LAL',
                            'opponent_team_abbr': 'GSW',
                            'home_game': True,
                            'predicted_points': 27.5,
                            'confidence_score': 0.78,
                            'recommendation': 'OVER',
                            'current_points_line': 25.5,
                            'has_line': True,
                            'fatigue_score': 90,
                            'fatigue_level': 'normal',
                            'days_rest': 2,
                            'injury_status': 'available',
                            'injury_reason': None,
                            'season_ppg': 25.8,
                            'season_mpg': 35.2,
                            'last_5_ppg': 28.0,
                            'games_played': 25,
                            'over_odds': -110,
                            'under_odds': -110
                        }
                    ],
                    # Last 10 query result
                    [
                        {
                            'player_lookup': 'lebronjames',
                            'last_10': [
                                {'over_under_result': 'OVER', 'points': 28},
                                {'over_under_result': 'UNDER', 'points': 22},
                                {'over_under_result': 'OVER', 'points': 30}
                            ]
                        }
                    ]
                )
                mock_bq.return_value = mock_client

                exporter = TonightAllPlayersExporter()
                result = exporter.generate_json('2024-12-15')

                assert result['game_date'] == '2024-12-15'
                assert result['total_players'] == 1
                assert result['total_with_lines'] == 1
                assert len(result['games']) == 1

    def test_generate_json_no_games(self):
        """Test JSON generation when no games exist"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])
                mock_bq.return_value = mock_client

                exporter = TonightAllPlayersExporter()
                result = exporter.generate_json('2024-12-15')

                assert result['game_date'] == '2024-12-15'
                assert result['total_players'] == 0
                assert result['games'] == []


class TestQueryGames:
    """Test suite for _query_games method"""

    def test_query_games(self):
        """Test games query"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'game_id': '0022500123',
                        'home_team_abbr': 'LAL',
                        'away_team_abbr': 'GSW',
                        'game_status': 1,
                        'game_time': ' 7:30 PM ET',
                        'game_date_est': '2024-12-15T19:30:00'
                    },
                    {
                        'game_id': '0022500124',
                        'home_team_abbr': 'BOS',
                        'away_team_abbr': 'MIA',
                        'game_status': 1,
                        'game_time': ' 8:00 PM ET',
                        'game_date_est': '2024-12-15T20:00:00'
                    }
                ])
                mock_bq.return_value = mock_client

                exporter = TonightAllPlayersExporter()
                result = exporter._query_games('2024-12-15')

                assert len(result) == 2
                assert result[0]['game_id'] == '0022500123'
                assert result[1]['game_id'] == '0022500124'


class TestQueryLast10Results:
    """Test suite for _query_last_10_results method"""

    def test_query_last_10_over_under(self):
        """Test last 10 O/U results calculation"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'last_10': [
                            {'over_under_result': 'OVER', 'points': 28},
                            {'over_under_result': 'OVER', 'points': 30},
                            {'over_under_result': 'UNDER', 'points': 20},
                            {'over_under_result': 'OVER', 'points': 25},
                            {'over_under_result': 'UNDER', 'points': 18}
                        ]
                    }
                ])
                mock_bq.return_value = mock_client

                exporter = TonightAllPlayersExporter()
                result = exporter._query_last_10_results(['player1'], '2024-12-15')

                assert 'player1' in result
                assert result['player1']['results'] == ['O', 'O', 'U', 'O', 'U']
                assert result['player1']['record'] == '3-2'
                assert result['player1']['points'] == [28, 30, 20, 25, 18]

    def test_query_last_10_empty_players(self):
        """Test last 10 with empty player list"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightAllPlayersExporter()
                result = exporter._query_last_10_results([], '2024-12-15')

                assert result == {}


class TestBuildGamesData:
    """Test suite for _build_games_data method"""

    def test_build_games_data(self):
        """Test building games data with players"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightAllPlayersExporter()

                games = [
                    {
                        'game_id': '0022500123',
                        'home_team_abbr': 'LAL',
                        'away_team_abbr': 'GSW',
                        'game_status': 1,
                        'game_time': ' 7:30 PM ET'
                    }
                ]

                players = [
                    {
                        'player_lookup': 'lebronjames',
                        'player_full_name': 'LeBron James',
                        'game_id': '0022500123',
                        'team_abbr': 'LAL',
                        'opponent_team_abbr': 'GSW',
                        'home_game': True,
                        'predicted_points': 27.5,
                        'confidence_score': 0.78,
                        'recommendation': 'OVER',
                        'current_points_line': 25.5,
                        'has_line': True,
                        'fatigue_score': 90,
                        'fatigue_level': 'normal',
                        'days_rest': 2,
                        'injury_status': 'available',
                        'injury_reason': None,
                        'season_ppg': 25.8,
                        'season_mpg': 35.2,
                        'last_5_ppg': 28.0,
                        'games_played': 25,
                        'over_odds': -110,
                        'under_odds': -110
                    }
                ]

                last_10_map = {
                    'lebronjames': {
                        'results': ['O', 'U', 'O', 'O', 'U'],
                        'points': [28, 22, 30, 27, 20],
                        'record': '3-2'
                    }
                }

                result = exporter._build_games_data(games, players, last_10_map)

                assert len(result) == 1
                game = result[0]
                assert game['game_id'] == '0022500123'
                assert game['home_team'] == 'LAL'
                assert game['away_team'] == 'GSW'
                assert game['player_count'] == 1
                assert len(game['players']) == 1

    def test_player_data_structure(self):
        """Test player data has correct structure"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightAllPlayersExporter()

                games = [{'game_id': '123', 'home_team_abbr': 'LAL', 'away_team_abbr': 'GSW', 'game_status': 1, 'game_time': '7:30 PM'}]
                players = [
                    {
                        'player_lookup': 'player1',
                        'player_full_name': 'Player One',
                        'game_id': '123',
                        'team_abbr': 'LAL',
                        'opponent_team_abbr': 'GSW',
                        'home_game': True,
                        'predicted_points': 25.0,
                        'confidence_score': 0.75,
                        'recommendation': 'OVER',
                        'current_points_line': 23.5,
                        'has_line': True,
                        'fatigue_score': 85,
                        'fatigue_level': 'normal',
                        'days_rest': 1,
                        'injury_status': 'available',
                        'injury_reason': None,
                        'season_ppg': 22.5,
                        'season_mpg': 32.0,
                        'last_5_ppg': 24.0,
                        'games_played': 20,
                        'over_odds': -115,
                        'under_odds': -105
                    }
                ]
                last_10_map = {'player1': {'results': ['O', 'O'], 'points': [25, 28], 'record': '2-0'}}

                result = exporter._build_games_data(games, players, last_10_map)

                player = result[0]['players'][0]
                assert player['player_lookup'] == 'player1'
                assert player['name'] == 'Player One'
                assert player['team'] == 'LAL'
                assert player['is_home'] is True
                assert player['has_line'] is True
                assert player['fatigue_level'] == 'normal'
                assert player['injury_status'] == 'available'
                assert player['season_ppg'] == 22.5
                assert 'prediction' in player
                assert 'props' in player


class TestPlayerSorting:
    """Test suite for player sorting logic"""

    def test_players_with_lines_first(self):
        """Test that players with lines come before those without"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightAllPlayersExporter()

                games = [{'game_id': '123', 'home_team_abbr': 'LAL', 'away_team_abbr': 'GSW', 'game_status': 1, 'game_time': '7:30'}]
                players = [
                    {
                        'player_lookup': 'no_line_player',
                        'player_full_name': 'No Line Player',
                        'game_id': '123',
                        'team_abbr': 'LAL',
                        'opponent_team_abbr': 'GSW',
                        'home_game': True,
                        'has_line': False,
                        'predicted_points': None,
                        'confidence_score': None,
                        'recommendation': None,
                        'current_points_line': None,
                        'fatigue_score': 85,
                        'fatigue_level': 'normal',
                        'days_rest': 1,
                        'injury_status': 'available',
                        'injury_reason': None,
                        'season_ppg': 30.0,  # High PPG but no line
                        'season_mpg': 35.0,
                        'last_5_ppg': 32.0,
                        'games_played': 20,
                        'over_odds': None,
                        'under_odds': None
                    },
                    {
                        'player_lookup': 'has_line_player',
                        'player_full_name': 'Has Line Player',
                        'game_id': '123',
                        'team_abbr': 'GSW',
                        'opponent_team_abbr': 'LAL',
                        'home_game': False,
                        'has_line': True,
                        'predicted_points': 20.0,
                        'confidence_score': 0.70,
                        'recommendation': 'OVER',
                        'current_points_line': 18.5,
                        'fatigue_score': 85,
                        'fatigue_level': 'normal',
                        'days_rest': 1,
                        'injury_status': 'available',
                        'injury_reason': None,
                        'season_ppg': 15.0,  # Lower PPG but has line
                        'season_mpg': 28.0,
                        'last_5_ppg': 16.0,
                        'games_played': 20,
                        'over_odds': -110,
                        'under_odds': -110
                    }
                ]
                last_10_map = {}

                result = exporter._build_games_data(games, players, last_10_map)

                # Player with line should come first
                assert result[0]['players'][0]['player_lookup'] == 'has_line_player'
                assert result[0]['players'][1]['player_lookup'] == 'no_line_player'

    def test_out_players_last(self):
        """Test that OUT players are sorted last"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightAllPlayersExporter()

                games = [{'game_id': '123', 'home_team_abbr': 'LAL', 'away_team_abbr': 'GSW', 'game_status': 1, 'game_time': '7:30'}]
                players = [
                    {
                        'player_lookup': 'out_player',
                        'player_full_name': 'Out Player',
                        'game_id': '123',
                        'team_abbr': 'LAL',
                        'opponent_team_abbr': 'GSW',
                        'home_game': True,
                        'has_line': True,
                        'predicted_points': 25.0,
                        'confidence_score': 0.90,  # High confidence but OUT
                        'recommendation': 'OVER',
                        'current_points_line': 23.5,
                        'fatigue_score': 85,
                        'fatigue_level': 'normal',
                        'days_rest': 1,
                        'injury_status': 'out',  # OUT
                        'injury_reason': 'Knee',
                        'season_ppg': 25.0,
                        'season_mpg': 32.0,
                        'last_5_ppg': 26.0,
                        'games_played': 20,
                        'over_odds': -110,
                        'under_odds': -110
                    },
                    {
                        'player_lookup': 'available_player',
                        'player_full_name': 'Available Player',
                        'game_id': '123',
                        'team_abbr': 'GSW',
                        'opponent_team_abbr': 'LAL',
                        'home_game': False,
                        'has_line': True,
                        'predicted_points': 20.0,
                        'confidence_score': 0.70,  # Lower confidence but available
                        'recommendation': 'OVER',
                        'current_points_line': 18.5,
                        'fatigue_score': 85,
                        'fatigue_level': 'normal',
                        'days_rest': 1,
                        'injury_status': 'available',
                        'injury_reason': None,
                        'season_ppg': 15.0,
                        'season_mpg': 28.0,
                        'last_5_ppg': 16.0,
                        'games_played': 20,
                        'over_odds': -110,
                        'under_odds': -110
                    }
                ]
                last_10_map = {}

                result = exporter._build_games_data(games, players, last_10_map)

                # Available player should come first (OUT is last)
                assert result[0]['players'][0]['player_lookup'] == 'available_player'
                assert result[0]['players'][1]['player_lookup'] == 'out_player'


class TestPropsArray:
    """Test suite for props array structure"""

    def test_props_array_for_player_with_line(self):
        """Test props array is created for player with line"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightAllPlayersExporter()

                games = [{'game_id': '123', 'home_team_abbr': 'LAL', 'away_team_abbr': 'GSW', 'game_status': 1, 'game_time': '7:30'}]
                players = [
                    {
                        'player_lookup': 'player1',
                        'player_full_name': 'Player One',
                        'game_id': '123',
                        'team_abbr': 'LAL',
                        'opponent_team_abbr': 'GSW',
                        'home_game': True,
                        'has_line': True,
                        'predicted_points': 25.0,
                        'confidence_score': 0.75,
                        'recommendation': 'OVER',
                        'current_points_line': 23.5,
                        'fatigue_score': 85,
                        'fatigue_level': 'normal',
                        'days_rest': 1,
                        'injury_status': 'available',
                        'injury_reason': None,
                        'season_ppg': 22.5,
                        'season_mpg': 32.0,
                        'last_5_ppg': 24.0,
                        'games_played': 20,
                        'over_odds': -115,
                        'under_odds': -105
                    }
                ]
                last_10_map = {}

                result = exporter._build_games_data(games, players, last_10_map)

                player = result[0]['players'][0]
                assert 'props' in player
                assert len(player['props']) == 1
                prop = player['props'][0]
                assert prop['stat_type'] == 'points'
                assert prop['line'] == 23.5
                assert prop['over_odds'] == -115
                assert prop['under_odds'] == -105


class TestFatigueLevel:
    """Test suite for fatigue level in output"""

    def test_fatigue_levels(self):
        """Test fatigue level classification"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightAllPlayersExporter()

                games = [{'game_id': '123', 'home_team_abbr': 'LAL', 'away_team_abbr': 'GSW', 'game_status': 1, 'game_time': '7:30'}]

                # Test fresh fatigue level
                players = [
                    {
                        'player_lookup': 'fresh_player',
                        'player_full_name': 'Fresh Player',
                        'game_id': '123',
                        'team_abbr': 'LAL',
                        'opponent_team_abbr': 'GSW',
                        'home_game': True,
                        'has_line': False,
                        'predicted_points': None,
                        'confidence_score': None,
                        'recommendation': None,
                        'current_points_line': None,
                        'fatigue_score': 98,
                        'fatigue_level': 'fresh',
                        'days_rest': 3,
                        'injury_status': 'available',
                        'injury_reason': None,
                        'season_ppg': 20.0,
                        'season_mpg': 30.0,
                        'last_5_ppg': 22.0,
                        'games_played': 15,
                        'over_odds': None,
                        'under_odds': None
                    }
                ]
                last_10_map = {}

                result = exporter._build_games_data(games, players, last_10_map)

                assert result[0]['players'][0]['fatigue_level'] == 'fresh'


class TestSafeFloat:
    """Test suite for _safe_float utility method"""

    def test_safe_float_valid(self):
        """Test valid float conversion"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightAllPlayersExporter()

                assert exporter._safe_float(25.567) == 25.57
                assert exporter._safe_float(10) == 10.0

    def test_safe_float_none(self):
        """Test None handling"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightAllPlayersExporter()

                assert exporter._safe_float(None) is None

    def test_safe_float_nan(self):
        """Test NaN handling"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightAllPlayersExporter()

                assert exporter._safe_float(float('nan')) is None


class TestEmptyResponse:
    """Test suite for empty response structure"""

    def test_empty_response_structure(self):
        """Test that empty response has correct structure"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightAllPlayersExporter()
                response = exporter._empty_response('2024-12-15')

                assert response['game_date'] == '2024-12-15'
                assert response['total_players'] == 0
                assert response['total_with_lines'] == 0
                assert response['games'] == []
                assert 'generated_at' in response


class TestLimitedDataFlag:
    """Test suite for limited_data flag"""

    def test_limited_data_true(self):
        """Test limited_data is True when games_played < 10"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightAllPlayersExporter()

                games = [{'game_id': '123', 'home_team_abbr': 'LAL', 'away_team_abbr': 'GSW', 'game_status': 1, 'game_time': '7:30'}]
                players = [
                    {
                        'player_lookup': 'rookie',
                        'player_full_name': 'Rookie Player',
                        'game_id': '123',
                        'team_abbr': 'LAL',
                        'opponent_team_abbr': 'GSW',
                        'home_game': True,
                        'has_line': False,
                        'predicted_points': None,
                        'confidence_score': None,
                        'recommendation': None,
                        'current_points_line': None,
                        'fatigue_score': 90,
                        'fatigue_level': 'normal',
                        'days_rest': 2,
                        'injury_status': 'available',
                        'injury_reason': None,
                        'season_ppg': 8.0,
                        'season_mpg': 15.0,
                        'last_5_ppg': 10.0,
                        'games_played': 5,  # Less than 10
                        'over_odds': None,
                        'under_odds': None
                    }
                ]
                last_10_map = {}

                result = exporter._build_games_data(games, players, last_10_map)

                assert result[0]['players'][0]['limited_data'] is True

    def test_limited_data_false(self):
        """Test limited_data is False when games_played >= 10"""
        with patch('data_processors.publishing.tonight_all_players_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightAllPlayersExporter()

                games = [{'game_id': '123', 'home_team_abbr': 'LAL', 'away_team_abbr': 'GSW', 'game_status': 1, 'game_time': '7:30'}]
                players = [
                    {
                        'player_lookup': 'veteran',
                        'player_full_name': 'Veteran Player',
                        'game_id': '123',
                        'team_abbr': 'LAL',
                        'opponent_team_abbr': 'GSW',
                        'home_game': True,
                        'has_line': False,
                        'predicted_points': None,
                        'confidence_score': None,
                        'recommendation': None,
                        'current_points_line': None,
                        'fatigue_score': 90,
                        'fatigue_level': 'normal',
                        'days_rest': 2,
                        'injury_status': 'available',
                        'injury_reason': None,
                        'season_ppg': 20.0,
                        'season_mpg': 32.0,
                        'last_5_ppg': 22.0,
                        'games_played': 25,  # More than 10
                        'over_odds': None,
                        'under_odds': None
                    }
                ]
                last_10_map = {}

                result = exporter._build_games_data(games, players, last_10_map)

                assert result[0]['players'][0]['limited_data'] is False


class TestContentGuard:
    """validate_content() + safe_export() guard rails (Apr 28-May 1 incident).

    See data_processors/publishing/base_exporter.py:safe_export and
    docs/09-handoff/2026-05-02-tonight-content-guard.md for context.
    """

    def _make(self):
        return TonightAllPlayersExporter.__new__(TonightAllPlayersExporter)

    def test_validate_passes_on_off_day(self):
        e = self._make()
        assert e.validate_content({'games': [], 'total_players': 0}) is None

    def test_validate_passes_on_full_rosters(self):
        e = self._make()
        # 1 game, 16 players (8/side floor)
        assert e.validate_content({'games': [{'game_id': 'X'}], 'total_players': 16}) is None

    def test_validate_fires_on_games_zero_players(self):
        # The actual bug: 4 games, 0 players (Apr 28-May 1)
        e = self._make()
        reason = e.validate_content({
            'games': [{'game_id': str(i)} for i in range(4)],
            'total_players': 0,
        })
        assert reason and 'players_below_floor' in reason

    def test_validate_fires_on_partial_rosters(self):
        # 3 games, 12 players = 4/game (under 8/game floor)
        e = self._make()
        reason = e.validate_content({
            'games': [{'g': i} for i in range(3)],
            'total_players': 12,
        })
        assert reason and 'players_below_floor' in reason

    def test_safe_export_writes_degraded_sentinel(self):
        e = self._make()
        captured = []
        e.upload_to_gcs = lambda data, path, cc: (captured.append({'data': dict(data), 'path': path}), f'gs://x/{path}')[1]
        bad = {'game_date': '2026-05-01', 'games': [{'g': 1}, {'g': 2}], 'total_players': 0}
        gcs_path, reason = e.safe_export(bad, 'tonight/2026-05-01.json', 'public, max-age=300')
        assert reason and 'players_below_floor' in reason
        assert captured[-1]['data']['status'] == 'degraded'
        assert captured[-1]['data']['degraded_reason'] == reason

    def test_safe_export_passes_through_healthy(self):
        e = self._make()
        captured = []
        e.upload_to_gcs = lambda data, path, cc: (captured.append({'data': dict(data)}), f'gs://x/{path}')[1]
        good = {'game_date': '2026-02-01', 'games': [{'g': 1}], 'total_players': 16}
        _, reason = e.safe_export(good, 'tonight/2026-02-01.json', 'public, max-age=86400')
        assert reason is None
        assert 'status' not in captured[-1]['data']

    def test_safe_export_kill_switch(self, monkeypatch):
        """TONIGHT_GUARD_ENABLED=false bypasses guard without redeploy."""
        e = self._make()
        captured = []
        e.upload_to_gcs = lambda data, path, cc: (captured.append({'data': dict(data)}), f'gs://x/{path}')[1]
        monkeypatch.setenv('TONIGHT_GUARD_ENABLED', 'false')
        bad = {'game_date': '2026-05-01', 'games': [{'g': 1}, {'g': 2}], 'total_players': 0}
        _, reason = e.safe_export(
            bad, 'tonight/2026-05-01.json', 'public, max-age=300',
            guard_env_var='TONIGHT_GUARD_ENABLED',
        )
        assert reason is None
        assert 'status' not in captured[-1]['data']

    def test_safe_export_does_not_mutate_caller_dict(self):
        """Two safe_export() calls in export() share the same json_data; the
        first call's mutation must not contaminate the second."""
        e = self._make()
        e.upload_to_gcs = lambda data, path, cc: f'gs://x/{path}'
        bad = {'game_date': '2026-05-01', 'games': [{'g': 1}, {'g': 2}], 'total_players': 0}
        original_keys = set(bad.keys())
        e.safe_export(bad, 'tonight/all-players.json', 'public, max-age=300')
        e.safe_export(bad, 'tonight/2026-05-01.json', 'public, max-age=300')
        assert set(bad.keys()) == original_keys, 'caller dict must not be mutated'

    def test_all_games_final_helper(self):
        e = self._make()
        assert e._all_games_final({'games': [{'game_status': 'final'}, {'game_status': 'final'}]}) is True
        assert e._all_games_final({'games': [{'game_status': 'final'}, {'game_status': 'in_progress'}]}) is False
        assert e._all_games_final({'games': []}) is False  # off-day → 5min cache


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

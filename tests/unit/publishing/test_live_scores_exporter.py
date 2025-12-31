"""
Unit Tests for LiveScoresExporter

Tests cover:
1. Live data fetching and transformation
2. Player lookup cache building
3. Game status determination
4. Player stat transformation
5. Date filtering for live games
6. Empty data handling
7. Mock API and BigQuery responses
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date, datetime, timezone
import requests

from data_processors.publishing.live_scores_exporter import LiveScoresExporter


class MockBigQueryClient:
    """Mock BigQuery client for testing"""

    def __init__(self):
        self.query_results = []
        self.query_calls = []

    def query(self, sql, job_config=None):
        """Mock query execution"""
        self.query_calls.append({'sql': sql, 'config': job_config})
        mock_result = Mock()
        mock_result.result.return_value = self.query_results
        return mock_result

    def set_results(self, results):
        """Set results to return from next query"""
        self.query_results = results


class TestLiveScoresExporterInit:
    """Test suite for initialization"""

    def test_initialization(self):
        """Test that exporter initializes correctly"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveScoresExporter()
                assert exporter is not None
                assert exporter._player_lookup_cache == {}
                assert exporter._player_name_cache == {}


class TestGenerateJson:
    """Test suite for generate_json method"""

    def test_generate_json_with_live_games(self):
        """Test JSON generation with live games"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                with patch.object(LiveScoresExporter, '_fetch_live_box_scores') as mock_fetch:
                    with patch.object(LiveScoresExporter, '_build_player_lookup_cache'):
                        mock_client = MockBigQueryClient()
                        mock_bq.return_value = mock_client

                        # Mock live API response
                        mock_fetch.return_value = [
                            {
                                'id': '12345',
                                'date': '2024-12-15',
                                'status': 'in progress',
                                'period': 3,
                                'time': '5:42',
                                'home_team': {'abbreviation': 'LAL', 'players': []},
                                'visitor_team': {'abbreviation': 'GSW', 'players': []},
                                'home_team_score': 78,
                                'visitor_team_score': 82
                            }
                        ]

                        exporter = LiveScoresExporter()
                        result = exporter.generate_json('2024-12-15')

                        assert result['game_date'] == '2024-12-15'
                        assert result['total_games'] == 1
                        assert result['games_in_progress'] == 1
                        assert 'updated_at' in result
                        assert 'poll_id' in result

    def test_generate_json_no_live_games(self):
        """Test JSON generation when no games are live"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                with patch.object(LiveScoresExporter, '_fetch_live_box_scores') as mock_fetch:
                    mock_client = MockBigQueryClient()
                    mock_bq.return_value = mock_client

                    mock_fetch.return_value = []

                    exporter = LiveScoresExporter()
                    result = exporter.generate_json('2024-12-15')

                    assert result['game_date'] == '2024-12-15'
                    assert result['total_games'] == 0
                    assert result['games'] == []


class TestFetchLiveBoxScores:
    """Test suite for _fetch_live_box_scores method"""

    def test_fetch_live_box_scores_success(self):
        """Test successful API fetch"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                with patch('data_processors.publishing.live_scores_exporter.requests.get') as mock_get:
                    mock_response = Mock()
                    mock_response.json.return_value = {
                        'data': [
                            {'id': '123', 'status': 'in progress'}
                        ],
                        'meta': {}
                    }
                    mock_response.raise_for_status = Mock()
                    mock_get.return_value = mock_response

                    exporter = LiveScoresExporter()
                    result = exporter._fetch_live_box_scores()

                    assert len(result) == 1
                    assert result[0]['id'] == '123'

    def test_fetch_live_box_scores_api_error(self):
        """Test API error handling"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                with patch('data_processors.publishing.live_scores_exporter.requests.get') as mock_get:
                    mock_get.side_effect = requests.RequestException("API Error")

                    exporter = LiveScoresExporter()
                    result = exporter._fetch_live_box_scores()

                    assert result == []


class TestBuildPlayerLookupCache:
    """Test suite for _build_player_lookup_cache method"""

    def test_build_cache_success(self):
        """Test successful cache building"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {'bdl_player_id': 123, 'player_lookup': 'lebronjames', 'player_full_name': 'LeBron James'},
                    {'bdl_player_id': 456, 'player_lookup': 'stephencurry', 'player_full_name': 'Stephen Curry'}
                ])
                mock_bq.return_value = mock_client

                exporter = LiveScoresExporter()
                exporter._build_player_lookup_cache()

                assert exporter._player_lookup_cache[123] == 'lebronjames'
                assert exporter._player_lookup_cache[456] == 'stephencurry'
                assert exporter._player_name_cache[123] == 'LeBron James'

    def test_cache_not_rebuilt_if_exists(self):
        """Test that cache is not rebuilt if already populated"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_bq.return_value = mock_client

                exporter = LiveScoresExporter()
                # Pre-populate cache
                exporter._player_lookup_cache = {123: 'existing'}

                exporter._build_player_lookup_cache()

                # Query should not have been called
                assert len(mock_client.query_calls) == 0


class TestTransformGames:
    """Test suite for _transform_games method"""

    def test_transform_games_in_progress(self):
        """Test transformation of in-progress game"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveScoresExporter()

                live_data = [
                    {
                        'id': '12345',
                        'date': '2024-12-15',
                        'status': 'in progress',
                        'period': 2,
                        'time': '3:45',
                        'home_team': {'abbreviation': 'LAL', 'players': []},
                        'visitor_team': {'abbreviation': 'GSW', 'players': []},
                        'home_team_score': 52,
                        'visitor_team_score': 48
                    }
                ]

                result = exporter._transform_games(live_data, '2024-12-15')

                assert len(result) == 1
                game = result[0]
                assert game['game_id'] == '12345'
                assert game['status'] == 'in_progress'
                assert game['home_team'] == 'LAL'
                assert game['away_team'] == 'GSW'
                assert game['home_score'] == 52
                assert game['away_score'] == 48
                assert game['period'] == 2

    def test_transform_games_final(self):
        """Test transformation of final game"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveScoresExporter()

                live_data = [
                    {
                        'id': '12345',
                        'date': '2024-12-15',
                        'status': 'Final',
                        'period': 4,
                        'time': '',
                        'home_team': {'abbreviation': 'LAL', 'players': []},
                        'visitor_team': {'abbreviation': 'GSW', 'players': []},
                        'home_team_score': 110,
                        'visitor_team_score': 105
                    }
                ]

                result = exporter._transform_games(live_data, '2024-12-15')

                assert result[0]['status'] == 'final'

    def test_transform_games_filters_other_dates(self):
        """Test that games from other dates are filtered out"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveScoresExporter()

                live_data = [
                    {
                        'id': '12345',
                        'date': '2024-12-14',  # Different date
                        'status': 'in progress',
                        'period': 2,
                        'time': '3:45',
                        'home_team': {'abbreviation': 'LAL', 'players': []},
                        'visitor_team': {'abbreviation': 'GSW', 'players': []},
                        'home_team_score': 52,
                        'visitor_team_score': 48
                    }
                ]

                result = exporter._transform_games(live_data, '2024-12-15')

                assert len(result) == 0


class TestTransformPlayer:
    """Test suite for _transform_player method"""

    def test_transform_player_with_cache(self):
        """Test player transformation with cached lookup"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveScoresExporter()
                exporter._player_lookup_cache = {123: 'lebronjames'}
                exporter._player_name_cache = {123: 'LeBron James'}

                player_stat = {
                    'player': {'id': 123, 'first_name': 'LeBron', 'last_name': 'James'},
                    'pts': 28,
                    'reb': 8,
                    'ast': 7,
                    'stl': 2,
                    'blk': 1,
                    'turnover': 3,
                    'min': '32:15',
                    'fgm': 10,
                    'fga': 18,
                    'fg3m': 2,
                    'fg3a': 5,
                    'ftm': 6,
                    'fta': 8
                }

                result = exporter._transform_player(player_stat, 'LAL')

                assert result['player_lookup'] == 'lebronjames'
                assert result['name'] == 'LeBron James'
                assert result['team'] == 'LAL'
                assert result['points'] == 28
                assert result['rebounds'] == 8
                assert result['assists'] == 7
                assert result['minutes'] == '32:15'

    def test_transform_player_fallback(self):
        """Test player transformation with fallback lookup generation"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveScoresExporter()
                exporter._player_lookup_cache = {}  # Empty cache

                player_stat = {
                    'player': {'id': 999, 'first_name': 'New', 'last_name': 'Player'},
                    'pts': 10,
                    'reb': 5,
                    'ast': 3,
                    'stl': 1,
                    'blk': 0,
                    'turnover': 2,
                    'min': '20:00'
                }

                result = exporter._transform_player(player_stat, 'BOS')

                assert result['player_lookup'] == 'newplayer'
                assert result['name'] == 'New Player'

    def test_transform_player_no_id(self):
        """Test player transformation with missing player ID"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveScoresExporter()

                player_stat = {
                    'player': {},  # No ID
                    'pts': 10
                }

                result = exporter._transform_player(player_stat, 'BOS')

                assert result is None


class TestGameStatusDetermination:
    """Test suite for game status logic"""

    def test_status_final(self):
        """Test final status detection"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveScoresExporter()

                live_data = [
                    {
                        'id': '123',
                        'date': '2024-12-15',
                        'status': 'Final',
                        'period': 4,
                        'home_team': {'abbreviation': 'LAL', 'players': []},
                        'visitor_team': {'abbreviation': 'GSW', 'players': []},
                        'home_team_score': 100,
                        'visitor_team_score': 95
                    }
                ]

                result = exporter._transform_games(live_data, '2024-12-15')
                assert result[0]['status'] == 'final'

    def test_status_in_progress(self):
        """Test in_progress status detection"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveScoresExporter()

                live_data = [
                    {
                        'id': '123',
                        'date': '2024-12-15',
                        'status': '',
                        'period': 2,  # Has period > 0
                        'home_team': {'abbreviation': 'LAL', 'players': []},
                        'visitor_team': {'abbreviation': 'GSW', 'players': []},
                        'home_team_score': 50,
                        'visitor_team_score': 45
                    }
                ]

                result = exporter._transform_games(live_data, '2024-12-15')
                assert result[0]['status'] == 'in_progress'

    def test_status_scheduled(self):
        """Test scheduled status detection"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveScoresExporter()

                live_data = [
                    {
                        'id': '123',
                        'date': '2024-12-15',
                        'status': '',
                        'period': 0,  # No period started
                        'home_team': {'abbreviation': 'LAL', 'players': []},
                        'visitor_team': {'abbreviation': 'GSW', 'players': []},
                        'home_team_score': 0,
                        'visitor_team_score': 0
                    }
                ]

                result = exporter._transform_games(live_data, '2024-12-15')
                assert result[0]['status'] == 'scheduled'


class TestEmptyResponse:
    """Test suite for empty response structure"""

    def test_empty_response_structure(self):
        """Test that empty response has correct structure"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveScoresExporter()
                response = exporter._empty_response('2024-12-15', 'poll123')

                assert response['game_date'] == '2024-12-15'
                assert response['poll_id'] == 'poll123'
                assert response['games_in_progress'] == 0
                assert response['games_final'] == 0
                assert response['total_games'] == 0
                assert response['games'] == []
                assert 'updated_at' in response


class TestGameSorting:
    """Test suite for game sorting by status"""

    def test_games_sorted_by_status(self):
        """Test that games are sorted: in_progress first, then final, then scheduled"""
        with patch('data_processors.publishing.live_scores_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = LiveScoresExporter()

                live_data = [
                    {
                        'id': '1',
                        'date': '2024-12-15',
                        'status': 'Final',
                        'period': 4,
                        'home_team': {'abbreviation': 'A', 'players': []},
                        'visitor_team': {'abbreviation': 'B', 'players': []},
                        'home_team_score': 100,
                        'visitor_team_score': 95
                    },
                    {
                        'id': '2',
                        'date': '2024-12-15',
                        'status': '',
                        'period': 2,  # In progress
                        'home_team': {'abbreviation': 'C', 'players': []},
                        'visitor_team': {'abbreviation': 'D', 'players': []},
                        'home_team_score': 50,
                        'visitor_team_score': 45
                    },
                    {
                        'id': '3',
                        'date': '2024-12-15',
                        'status': '',
                        'period': 0,  # Scheduled
                        'home_team': {'abbreviation': 'E', 'players': []},
                        'visitor_team': {'abbreviation': 'F', 'players': []},
                        'home_team_score': 0,
                        'visitor_team_score': 0
                    }
                ]

                result = exporter._transform_games(live_data, '2024-12-15')

                assert result[0]['status'] == 'in_progress'
                assert result[1]['status'] == 'final'
                assert result[2]['status'] == 'scheduled'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

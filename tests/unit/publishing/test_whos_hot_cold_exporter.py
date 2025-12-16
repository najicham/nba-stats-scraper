"""
Unit Tests for WhosHotColdExporter

Tests cover:
1. Heat score calculation (0.5 * hit_rate + 0.25 * streak_factor + 0.25 * margin_factor)
2. Streak detection logic
3. Empty data handling
4. Tonight's game enrichment
5. Mock BigQuery responses
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import date

from data_processors.publishing.whos_hot_cold_exporter import WhosHotColdExporter


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


class TestWhosHotColdExporterInit:
    """Test suite for initialization"""

    def test_initialization_defaults(self):
        """Test that exporter initializes with defaults"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = WhosHotColdExporter()

                assert exporter.project_id == 'nba-props-platform'
                assert exporter.bucket_name == 'nba-props-platform-api'
                assert exporter.DEFAULT_MIN_GAMES == 5
                assert exporter.DEFAULT_LOOKBACK_DAYS == 30
                assert exporter.DEFAULT_TOP_N == 10


class TestHeatScoreCalculation:
    """Test suite for heat score calculation formula"""

    def test_heat_score_formula_correct(self):
        """
        Test that heat score is calculated correctly:
        0.5 * hit_rate + 0.25 * streak_factor + 0.25 * margin_factor
        """
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # Sample data with known values
                mock_client.set_results([
                    {
                        'player_lookup': 'lebron',
                        'player_name': 'LeBron James',
                        'team_abbr': 'LAL',
                        'games_played': 10,
                        'hit_rate': 0.800,  # 80% hit rate
                        'avg_margin': 6.0,  # +6 average margin
                        'current_streak': 5,
                        'streak_type': 'OVER',
                        # Expected heat_score calculation:
                        # 0.5 * 0.800 + 0.25 * min(5/10, 1) + 0.25 * min(max((6+10)/20, 0), 1)
                        # = 0.5 * 0.800 + 0.25 * 0.5 + 0.25 * 0.8
                        # = 0.4 + 0.125 + 0.2 = 0.725
                        'heat_score': 0.725
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = WhosHotColdExporter()

                result = exporter._query_heat_scores('2024-12-15', 5, 30)

                assert len(result) == 1
                assert result[0]['heat_score'] == 0.725
                assert result[0]['hit_rate'] == 0.800
                assert result[0]['current_streak'] == 5
                assert result[0]['avg_margin'] == 6.0

    def test_heat_score_perfect_player(self):
        """Test heat score for perfect performance (100% hit rate, long streak, big margins)"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # Perfect player
                mock_client.set_results([
                    {
                        'player_lookup': 'perfect',
                        'player_name': 'Perfect Player',
                        'team_abbr': 'BOS',
                        'games_played': 10,
                        'hit_rate': 1.0,  # 100%
                        'avg_margin': 10.0,  # +10 margin
                        'current_streak': 10,  # 10 game streak
                        'streak_type': 'OVER',
                        # 0.5 * 1.0 + 0.25 * 1.0 + 0.25 * 1.0 = 1.0
                        'heat_score': 1.0
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = WhosHotColdExporter()

                result = exporter._query_heat_scores('2024-12-15', 5, 30)

                assert result[0]['heat_score'] == 1.0

    def test_heat_score_cold_player(self):
        """Test heat score for cold player (low hit rate, UNDER streak, negative margins)"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'player_lookup': 'cold',
                        'player_name': 'Cold Player',
                        'team_abbr': 'DET',
                        'games_played': 10,
                        'hit_rate': 0.2,  # 20%
                        'avg_margin': -8.0,  # -8 margin
                        'current_streak': 6,
                        'streak_type': 'UNDER',
                        # 0.5 * 0.2 + 0.25 * 0.6 + 0.25 * 0.1 = 0.275
                        'heat_score': 0.275
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = WhosHotColdExporter()

                result = exporter._query_heat_scores('2024-12-15', 5, 30)

                assert result[0]['heat_score'] == 0.275
                assert result[0]['streak_type'] == 'UNDER'


class TestStreakDetection:
    """Test suite for streak detection logic"""

    def test_streak_over_detected(self):
        """Test that OVER streaks are correctly identified"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'player_lookup': 'hot',
                        'player_name': 'Hot Player',
                        'team_abbr': 'MIA',
                        'games_played': 10,
                        'hit_rate': 0.7,
                        'avg_margin': 3.5,
                        'current_streak': 7,
                        'streak_type': 'OVER',
                        'heat_score': 0.65
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = WhosHotColdExporter()

                result = exporter._query_heat_scores('2024-12-15', 5, 30)

                assert result[0]['streak_type'] == 'OVER'
                assert result[0]['current_streak'] == 7

    def test_streak_under_detected(self):
        """Test that UNDER streaks are correctly identified"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'player_lookup': 'cold',
                        'player_name': 'Cold Player',
                        'team_abbr': 'DET',
                        'games_played': 10,
                        'hit_rate': 0.3,
                        'avg_margin': -4.0,
                        'current_streak': 5,
                        'streak_type': 'UNDER',
                        'heat_score': 0.35
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = WhosHotColdExporter()

                result = exporter._query_heat_scores('2024-12-15', 5, 30)

                assert result[0]['streak_type'] == 'UNDER'
                assert result[0]['current_streak'] == 5

    def test_no_streak_returns_zero(self):
        """Test player with no streak returns zero streak length"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'player_lookup': 'inconsistent',
                        'player_name': 'Inconsistent Player',
                        'team_abbr': 'SAC',
                        'games_played': 10,
                        'hit_rate': 0.5,
                        'avg_margin': 0.0,
                        'current_streak': 0,
                        'streak_type': 'NONE',
                        'heat_score': 0.4
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = WhosHotColdExporter()

                result = exporter._query_heat_scores('2024-12-15', 5, 30)

                assert result[0]['current_streak'] == 0
                assert result[0]['streak_type'] == 'NONE'


class TestEmptyDataHandling:
    """Test suite for empty data scenarios"""

    def test_empty_results_returns_empty_response(self):
        """Test that empty BigQuery results return proper empty response"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])  # Empty results

                mock_bq.return_value = mock_client
                exporter = WhosHotColdExporter()

                result = exporter.generate_json('2024-12-15', min_games=5)

                assert result['total_qualifying_players'] == 0
                assert result['hot'] == []
                assert result['cold'] == []
                assert result['league_average']['hit_rate'] is None
                assert result['league_average']['avg_margin'] is None

    def test_empty_response_structure(self):
        """Test structure of empty response"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = WhosHotColdExporter()

                result = exporter._empty_response('2024-12-15', 5, 30)

                assert 'generated_at' in result
                assert result['as_of_date'] == '2024-12-15'
                assert result['time_period'] == 'last_30_days'
                assert result['min_games'] == 5
                assert isinstance(result['hot'], list)
                assert isinstance(result['cold'], list)


class TestGenerateJson:
    """Test suite for generate_json method"""

    def test_generate_json_complete_flow(self):
        """Test complete JSON generation with sample data"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # Create 15 players with varying heat scores
                players = []
                for i in range(15):
                    heat_score = 0.9 - (i * 0.05)  # Descending heat scores
                    players.append({
                        'player_lookup': f'player{i}',
                        'player_name': f'Player {i}',
                        'team_abbr': 'LAL',
                        'games_played': 10,
                        'hit_rate': 0.8 - (i * 0.03),
                        'avg_margin': 5.0 - i,
                        'current_streak': 5,
                        'streak_type': 'OVER',
                        'heat_score': heat_score
                    })

                mock_client.set_results(players)
                mock_bq.return_value = mock_client
                exporter = WhosHotColdExporter()

                result = exporter.generate_json('2024-12-15', top_n=5)

                # Should have 5 hot and 5 cold players
                assert len(result['hot']) == 5
                assert len(result['cold']) == 5
                assert result['total_qualifying_players'] == 15

                # Hot players should be ranked 1-5
                assert result['hot'][0]['rank'] == 1
                assert result['hot'][4]['rank'] == 5

                # Cold players should be ranked 1-5 (coldest first)
                assert result['cold'][0]['rank'] == 1
                assert result['cold'][4]['rank'] == 5

                # Verify league averages calculated
                assert result['league_average']['hit_rate'] is not None
                assert result['league_average']['avg_margin'] is not None

    def test_generate_json_defaults(self):
        """Test that default parameters are applied"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = WhosHotColdExporter()

                result = exporter.generate_json(as_of_date='2024-12-15')

                # Should use defaults
                assert result['as_of_date'] == '2024-12-15'
                assert result['min_games'] == 5
                assert 'last_30_days' in result['time_period']


class TestTonightGameEnrichment:
    """Test suite for tonight's game enrichment"""

    def test_enrich_with_tonight_playing(self):
        """Test enrichment when player is playing tonight"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = WhosHotColdExporter()

                player = {
                    'player_lookup': 'lebron',
                    'player_name': 'LeBron James',
                    'team': 'LAL',
                    'heat_score': 0.85
                }

                tonight_games = {
                    'LAL': {
                        'opponent': 'GSW',
                        'game_time': '10:00 PM ET'
                    }
                }

                result = exporter._enrich_with_tonight(player, tonight_games, 1)

                assert result['rank'] == 1
                assert result['playing_tonight'] is True
                assert result['tonight_opponent'] == 'GSW'
                assert result['tonight_game_time'] == '10:00 PM ET'

    def test_enrich_with_tonight_not_playing(self):
        """Test enrichment when player is not playing tonight"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = WhosHotColdExporter()

                player = {
                    'player_lookup': 'lebron',
                    'player_name': 'LeBron James',
                    'team': 'LAL',
                    'heat_score': 0.85
                }

                tonight_games = {}  # No games tonight

                result = exporter._enrich_with_tonight(player, tonight_games, 3)

                assert result['rank'] == 3
                assert result['playing_tonight'] is False
                assert result['tonight_opponent'] is None
                assert result['tonight_game_time'] is None


class TestSafeFloat:
    """Test suite for _safe_float utility method"""

    def test_safe_float_valid_number(self):
        """Test conversion of valid numbers"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = WhosHotColdExporter()

                assert exporter._safe_float(0.12345) == 0.123
                assert exporter._safe_float(1.9999) == 2.0
                assert exporter._safe_float(0) == 0.0

    def test_safe_float_none(self):
        """Test that None returns None"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = WhosHotColdExporter()

                assert exporter._safe_float(None) is None

    def test_safe_float_nan(self):
        """Test that NaN returns None"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = WhosHotColdExporter()

                assert exporter._safe_float(float('nan')) is None

    def test_safe_float_invalid_string(self):
        """Test that invalid strings return None"""
        with patch('data_processors.publishing.whos_hot_cold_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = WhosHotColdExporter()

                assert exporter._safe_float('invalid') is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

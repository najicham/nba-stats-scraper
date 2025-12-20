"""
Unit Tests for PlayerSeasonExporter

Tests cover:
1. Season averages calculation
2. Current form and heat score calculation
3. Key patterns detection (rest_sensitive, home_performer, b2b_performer, road_warrior)
4. Splits calculation (home/away, rested/B2B)
5. Player tier classification
6. Empty data handling
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date

from data_processors.publishing.player_season_exporter import (
    PlayerSeasonExporter,
    get_player_tier,
    PLAYER_TIER_THRESHOLDS
)


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


class TestPlayerTierClassification:
    """Test suite for player tier classification"""

    def test_elite_tier(self):
        """Test player with 25+ PPG is elite"""
        assert get_player_tier(30.5) == 'elite'
        assert get_player_tier(25.0) == 'elite'

    def test_starter_tier(self):
        """Test player with 15-25 PPG is starter"""
        assert get_player_tier(24.9) == 'starter'
        assert get_player_tier(15.0) == 'starter'
        assert get_player_tier(20.0) == 'starter'

    def test_role_player_tier(self):
        """Test player with <15 PPG is role_player"""
        assert get_player_tier(14.9) == 'role_player'
        assert get_player_tier(8.0) == 'role_player'

    def test_none_ppg(self):
        """Test None PPG defaults to role_player"""
        assert get_player_tier(None) == 'role_player'


class TestPlayerSeasonExporterInit:
    """Test suite for initialization"""

    def test_initialization_defaults(self):
        """Test that exporter initializes with defaults"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerSeasonExporter()

                assert exporter.project_id == 'nba-props-platform'
                assert exporter.bucket_name == 'nba-props-platform-api'


class TestSeasonAverages:
    """Test suite for season averages calculation"""

    def test_season_averages(self):
        """Test season averages are correctly calculated"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'games': 45,
                        'ppg': 26.5,
                        'rpg': 6.2,
                        'apg': 5.1,
                        'spg': 1.2,
                        'bpg': 0.4,
                        'topg': 3.1,
                        'fg_pct': 0.485,
                        'three_pct': 0.412,
                        'ft_pct': 0.915,
                        'minutes': 34.5
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerSeasonExporter()

                result = exporter._query_season_averages('stephencurry', 2024)

                assert result['games'] == 45
                assert result['ppg'] == 26.5
                assert result['rpg'] == 6.2
                assert result['apg'] == 5.1
                assert result['fg_pct'] == 0.48  # Rounded
                assert result['minutes'] == 34.5

    def test_empty_season_averages(self):
        """Test handling when no games found"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([{'games': 0}])

                mock_bq.return_value = mock_client
                exporter = PlayerSeasonExporter()

                result = exporter._query_season_averages('newplayer', 2024)

                assert result == {}


class TestCurrentForm:
    """Test suite for current form calculation"""

    def test_hot_form(self):
        """Test player with hot form (high hit rate, streak)"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'l5_avg': 30.0,
                        'l10_avg': 28.5,
                        'season_avg': 26.0,
                        'overs_l10': 8,
                        'games_l10': 10,
                        'first_result': 'OVER',
                        'streak_length': 5
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerSeasonExporter()

                result = exporter._query_current_form('player', 2024)

                assert result['streak_direction'] == 'over'
                assert result['current_streak'] == 5
                assert result['hit_rate_l10'] == 0.8
                assert result['heat_score'] >= 6.5  # Should be warm or hot

    def test_cold_form(self):
        """Test player with cold form"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'l5_avg': 18.0,
                        'l10_avg': 20.0,
                        'season_avg': 25.0,
                        'overs_l10': 2,
                        'games_l10': 10,
                        'first_result': 'UNDER',
                        'streak_length': 4
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerSeasonExporter()

                result = exporter._query_current_form('player', 2024)

                assert result['streak_direction'] == 'under'
                assert result['heat_score'] < 5.0  # Should be cold or cool


class TestKeyPatterns:
    """Test suite for key patterns detection"""

    def test_rest_sensitive_pattern(self):
        """Test detection of rest-sensitive player (2.5+ PPG diff)"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'overall_avg': 25.0,
                        'home_avg': 25.5,
                        'away_avg': 24.5,
                        'rested_avg': 28.0,  # +3 on rest
                        'b2b_avg': 22.0,     # -3 on B2B = 6 PPG diff
                        'home_games': 30,
                        'away_games': 30,
                        'rested_games': 40,
                        'b2b_games': 10
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerSeasonExporter()

                result = exporter._query_key_patterns('player', 2024)

                patterns = [p['pattern'] for p in result]
                assert 'rest_sensitive' in patterns

                rest_pattern = next(p for p in result if p['pattern'] == 'rest_sensitive')
                assert 'strength' in rest_pattern
                assert rest_pattern['strength'] == 'strong'  # 6 PPG diff >= 4

    def test_b2b_performer_pattern(self):
        """Test detection of B2B performer (better on B2B)"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'overall_avg': 25.0,
                        'home_avg': 25.0,
                        'away_avg': 25.0,
                        'rested_avg': 23.0,  # Lower on rest
                        'b2b_avg': 27.0,     # Higher on B2B = -4 diff
                        'home_games': 30,
                        'away_games': 30,
                        'rested_games': 40,
                        'b2b_games': 10
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerSeasonExporter()

                result = exporter._query_key_patterns('player', 2024)

                patterns = [p['pattern'] for p in result]
                assert 'b2b_performer' in patterns

    def test_home_performer_pattern(self):
        """Test detection of home performer (2.5+ PPG diff at home)"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'overall_avg': 25.0,
                        'home_avg': 28.0,   # +3 at home
                        'away_avg': 22.0,   # -3 on road = 6 PPG diff
                        'rested_avg': 25.0,
                        'b2b_avg': 25.0,
                        'home_games': 30,
                        'away_games': 30,
                        'rested_games': 40,
                        'b2b_games': 10
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerSeasonExporter()

                result = exporter._query_key_patterns('player', 2024)

                patterns = [p['pattern'] for p in result]
                assert 'home_performer' in patterns

    def test_road_warrior_pattern(self):
        """Test detection of road warrior (2.5+ PPG diff on road)"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'overall_avg': 25.0,
                        'home_avg': 22.0,   # Lower at home
                        'away_avg': 28.0,   # Higher on road = -6 diff
                        'rested_avg': 25.0,
                        'b2b_avg': 25.0,
                        'home_games': 30,
                        'away_games': 30,
                        'rested_games': 40,
                        'b2b_games': 10
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerSeasonExporter()

                result = exporter._query_key_patterns('player', 2024)

                patterns = [p['pattern'] for p in result]
                assert 'road_warrior' in patterns

    def test_no_patterns(self):
        """Test player with no significant patterns"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'overall_avg': 25.0,
                        'home_avg': 25.5,  # Only 1 PPG diff
                        'away_avg': 24.5,
                        'rested_avg': 25.5,
                        'b2b_avg': 24.5,   # Only 1 PPG diff
                        'home_games': 30,
                        'away_games': 30,
                        'rested_games': 40,
                        'b2b_games': 10
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerSeasonExporter()

                result = exporter._query_key_patterns('player', 2024)

                assert result == []

    def test_max_four_patterns(self):
        """Test that max 4 patterns are returned"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # Setup data that would generate many patterns
                mock_client.set_results([
                    {
                        'overall_avg': 25.0,
                        'home_avg': 30.0,  # home performer
                        'away_avg': 20.0,
                        'rested_avg': 30.0,  # rest sensitive
                        'b2b_avg': 20.0,
                        'home_games': 30,
                        'away_games': 30,
                        'rested_games': 40,
                        'b2b_games': 10
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerSeasonExporter()

                result = exporter._query_key_patterns('player', 2024)

                assert len(result) <= 4


class TestSplits:
    """Test suite for performance splits"""

    def test_splits_calculation(self):
        """Test splits are correctly calculated"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {'split_type': 'home', 'games': 30, 'ppg': 28.5, 'over_rate': 0.65},
                    {'split_type': 'away', 'games': 30, 'ppg': 24.5, 'over_rate': 0.45},
                    {'split_type': 'rested', 'games': 45, 'ppg': 27.0, 'over_rate': 0.58},
                    {'split_type': 'back_to_back', 'games': 15, 'ppg': 23.5, 'over_rate': 0.40},
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerSeasonExporter()

                result = exporter._query_splits('player', 2024)

                assert 'home' in result
                assert result['home']['games'] == 30
                assert result['home']['ppg'] == 28.5
                assert result['home']['over_rate'] == 0.65

                assert 'away' in result
                assert 'back_to_back' in result


class TestEmptyResponse:
    """Test suite for empty response handling"""

    def test_empty_response_player_not_found(self):
        """Test empty response when player not found"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerSeasonExporter()

                result = exporter._empty_response('notaplayer', '2024-25', 'Player not found')

                assert result['player_lookup'] == 'notaplayer'
                assert result['season'] == '2024-25'
                assert result['error'] == 'Player not found'
                assert result['player_profile'] is None
                assert result['averages'] == {}
                assert result['key_patterns'] == []
                assert result['game_log'] == []


class TestSafeFloat:
    """Test suite for safe float conversion"""

    def test_safe_float_normal(self):
        """Test normal float conversion"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerSeasonExporter()

                assert exporter._safe_float(26.5) == 26.5
                assert exporter._safe_float('26.5') == 26.5

    def test_safe_float_none(self):
        """Test None handling"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerSeasonExporter()

                assert exporter._safe_float(None) is None

    def test_safe_float_rounding(self):
        """Test proper rounding behavior"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerSeasonExporter()

                # Small values rounded to 2 decimals
                assert exporter._safe_float(0.4567) == 0.46

                # Large values rounded to 1 decimal
                assert exporter._safe_float(26.567) == 26.6


class TestMonthly:
    """Test suite for monthly breakdown"""

    def test_monthly_breakdown(self):
        """Test monthly stats are correctly returned"""
        with patch('data_processors.publishing.player_season_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {'month': 'Oct', 'month_num': 10, 'games': 8, 'ppg': 24.5, 'over_rate': 0.50},
                    {'month': 'Nov', 'month_num': 11, 'games': 15, 'ppg': 26.8, 'over_rate': 0.60},
                    {'month': 'Dec', 'month_num': 12, 'games': 12, 'ppg': 28.2, 'over_rate': 0.67},
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerSeasonExporter()

                result = exporter._query_monthly('player', 2024)

                assert len(result) == 3
                assert result[0]['month'] == 'Oct'
                assert result[1]['ppg'] == 26.8
                assert result[2]['over_rate'] == 0.67

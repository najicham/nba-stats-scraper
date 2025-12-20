"""
Unit Tests for TonightTrendPlaysExporter

Tests cover:
1. Streak plays detection (3+ game streaks)
2. Momentum plays detection (15%+ L5 vs L15 change)
3. Rest plays detection (B2B tired, 3+ days fresh)
4. Tonight's games integration
5. Confidence classification
6. Empty data handling
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date

from data_processors.publishing.tonight_trend_plays_exporter import TonightTrendPlaysExporter


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


class MockScheduleService:
    """Mock NBAScheduleService for testing"""

    def __init__(self, games=None):
        self.games = games or []

    def get_games_for_date(self, date_str):
        return self.games


class MockGame:
    """Mock game object"""
    def __init__(self, home_team, away_team, commence_time='2024-12-15T19:30:00-05:00'):
        self.home_team = home_team
        self.away_team = away_team
        self.commence_time = commence_time


class TestTonightTrendPlaysExporterInit:
    """Test suite for initialization"""

    def test_initialization_defaults(self):
        """Test that exporter initializes with defaults"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightTrendPlaysExporter()

                assert exporter.MIN_STREAK_LENGTH == 3
                assert exporter.MIN_MOMENTUM_CHANGE_PCT == 0.15
                assert exporter.REST_THRESHOLD_FRESH == 3
                assert exporter.REST_THRESHOLD_TIRED == 1
                assert exporter.MAX_DAYS_REST == 7


class TestStreakPlays:
    """Test suite for streak plays detection"""

    def test_over_streak_high_confidence(self):
        """Test 5+ game OVER streak is high confidence"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_name': 'Player One',
                        'team_abbr': 'LAL',
                        'position': 'PG',
                        'streak_direction': 'OVER',
                        'streak_length': 6,
                        'avg_margin': 4.5,
                        'hit_rate_l10': 0.80
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = TonightTrendPlaysExporter()

                result = exporter._query_streak_plays('2024-12-15', {'LAL', 'GSW'})

                assert len(result) == 1
                assert result[0]['trend_type'] == 'streak'
                assert result[0]['trend_direction'] == 'over'
                assert result[0]['confidence'] == 'high'  # 6 >= 5
                assert result[0]['trend_details']['streak_length'] == 6

    def test_under_streak_medium_confidence(self):
        """Test 3-4 game UNDER streak is medium confidence"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_name': 'Player One',
                        'team_abbr': 'BOS',
                        'position': 'SF',
                        'streak_direction': 'UNDER',
                        'streak_length': 4,
                        'avg_margin': -2.5,
                        'hit_rate_l10': 0.30
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = TonightTrendPlaysExporter()

                result = exporter._query_streak_plays('2024-12-15', {'BOS'})

                assert len(result) == 1
                assert result[0]['trend_direction'] == 'under'
                assert result[0]['confidence'] == 'medium'  # 4 < 5


class TestMomentumPlays:
    """Test suite for momentum plays detection"""

    def test_surging_player_high_confidence(self):
        """Test player surging 25%+ is high confidence"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_name': 'Player One',
                        'team_abbr': 'MIA',
                        'position': 'SG',
                        'momentum_type': 'surging',
                        'l5_avg': 30.0,
                        'l15_avg': 22.0,
                        'pct_change': 36.4,  # (30-22)/22 * 100
                        'ppg_change': 8.0
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = TonightTrendPlaysExporter()

                result = exporter._query_momentum_plays('2024-12-15', {'MIA'})

                assert len(result) == 1
                assert result[0]['trend_type'] == 'momentum'
                assert result[0]['trend_direction'] == 'over'  # surging = over
                assert result[0]['confidence'] == 'high'  # 36.4% >= 25%
                assert result[0]['trend_details']['momentum_type'] == 'surging'

    def test_slumping_player_medium_confidence(self):
        """Test player slumping 15-25% is medium confidence"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_name': 'Player One',
                        'team_abbr': 'CHI',
                        'position': 'C',
                        'momentum_type': 'slumping',
                        'l5_avg': 18.0,
                        'l15_avg': 22.0,
                        'pct_change': -18.2,
                        'ppg_change': -4.0
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = TonightTrendPlaysExporter()

                result = exporter._query_momentum_plays('2024-12-15', {'CHI'})

                assert len(result) == 1
                assert result[0]['trend_direction'] == 'under'  # slumping = under
                assert result[0]['confidence'] == 'medium'  # 18.2% < 25%


class TestRestPlays:
    """Test suite for rest plays detection"""

    def test_fresh_player_with_significant_impact(self):
        """Test fresh player (3+ days rest) with significant historical impact"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_name': 'Player One',
                        'team_abbr': 'PHI',
                        'position': 'PF',
                        'days_rest': 4,
                        'rest_status': 'fresh',
                        'rested_avg': 28.0,
                        'b2b_avg': 22.0,
                        'overall_avg': 25.0,
                        'rested_games': 15,
                        'b2b_games': 8,
                        'rest_impact': 6.0  # rested_avg - b2b_avg
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = TonightTrendPlaysExporter()

                result = exporter._query_rest_plays('2024-12-15', {'PHI'})

                assert len(result) == 1
                assert result[0]['trend_type'] == 'rest'
                assert result[0]['trend_details']['rest_status'] == 'fresh'
                assert result[0]['trend_details']['days_rest'] == 4

    def test_tired_player_b2b(self):
        """Test tired player (B2B) detection"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_name': 'Player One',
                        'team_abbr': 'DEN',
                        'position': 'C',
                        'days_rest': 1,
                        'rest_status': 'tired',
                        'rested_avg': 30.0,
                        'b2b_avg': 24.0,
                        'overall_avg': 28.0,
                        'rested_games': 20,
                        'b2b_games': 10,
                        'rest_impact': 6.0
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = TonightTrendPlaysExporter()

                result = exporter._query_rest_plays('2024-12-15', {'DEN'})

                assert len(result) == 1
                assert result[0]['trend_details']['rest_status'] == 'tired'
                assert result[0]['trend_details']['days_rest'] == 1

    def test_rest_play_high_confidence(self):
        """Test rest play with high confidence (10+ games, 3+ PPG impact)"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_name': 'Player One',
                        'team_abbr': 'NYK',
                        'position': 'PG',
                        'days_rest': 5,
                        'rest_status': 'fresh',
                        'rested_avg': 30.0,
                        'b2b_avg': 24.0,
                        'overall_avg': 27.0,
                        'rested_games': 15,  # 10+ games
                        'b2b_games': 8,
                        'rest_impact': 6.0   # 3+ PPG impact
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = TonightTrendPlaysExporter()

                result = exporter._query_rest_plays('2024-12-15', {'NYK'})

                assert len(result) == 1
                # Fresh player with positive rest_impact should lean over
                assert result[0]['confidence'] == 'high'


class TestTonightGames:
    """Test suite for tonight's games integration"""

    def test_tonight_games_enrichment(self):
        """Test that plays are enriched with tonight's game info"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightTrendPlaysExporter()

                play = {
                    'player_lookup': 'player1',
                    'team_abbr': 'LAL'
                }

                tonight_games = {
                    'LAL': {'opponent': 'GSW', 'game_time': '7:30 PM ET', 'home': True},
                    'GSW': {'opponent': 'LAL', 'game_time': '7:30 PM ET', 'home': False}
                }

                exporter._enrich_with_tonight(play, tonight_games)

                assert play['tonight'] is not None
                assert play['tonight']['opponent'] == 'GSW'
                assert play['tonight']['home'] == True

    def test_player_not_playing_tonight(self):
        """Test player whose team is not playing tonight"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightTrendPlaysExporter()

                play = {
                    'player_lookup': 'player1',
                    'team_abbr': 'BOS'  # Not in tonight's games
                }

                tonight_games = {
                    'LAL': {'opponent': 'GSW', 'game_time': '7:30 PM ET', 'home': True},
                    'GSW': {'opponent': 'LAL', 'game_time': '7:30 PM ET', 'home': False}
                }

                exporter._enrich_with_tonight(play, tonight_games)

                assert play['tonight'] is None


class TestGenerateJson:
    """Test suite for full JSON generation"""

    def test_no_games_tonight(self):
        """Test response when no games tonight"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                with patch('data_processors.publishing.tonight_trend_plays_exporter.NBAScheduleService') as mock_sched:
                    mock_sched.return_value.get_games_for_date.return_value = []

                    exporter = TonightTrendPlaysExporter()
                    result = exporter.generate_json('2024-12-15')

                    assert result['games_tonight'] == 0
                    assert result['total_trend_plays'] == 0
                    assert result['trend_plays'] == []
                    assert result['by_trend_type'] == {'streak': 0, 'momentum': 0, 'rest': 0}


class TestEmptyResponse:
    """Test suite for empty response handling"""

    def test_empty_response(self):
        """Test empty response structure"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightTrendPlaysExporter()

                result = exporter._empty_response('2024-12-15', 0)

                assert result['game_date'] == '2024-12-15'
                assert result['games_tonight'] == 0
                assert result['total_trend_plays'] == 0
                assert result['trend_plays'] == []
                assert result['by_trend_type'] == {'streak': 0, 'momentum': 0, 'rest': 0}


class TestSafeFloat:
    """Test suite for safe float conversion"""

    def test_safe_float_normal(self):
        """Test normal float conversion"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightTrendPlaysExporter()

                assert exporter._safe_float(26.5) == 26.5
                assert exporter._safe_float('26.5') == 26.5

    def test_safe_float_none(self):
        """Test None handling"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightTrendPlaysExporter()

                assert exporter._safe_float(None) is None

    def test_safe_float_nan(self):
        """Test NaN handling"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightTrendPlaysExporter()

                assert exporter._safe_float(float('nan')) is None


class TestFormatGameTime:
    """Test suite for game time formatting"""

    def test_format_game_time_valid(self):
        """Test valid ISO time formatting"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightTrendPlaysExporter()

                result = exporter._format_game_time('2024-12-15T19:30:00-05:00')

                assert result is not None
                assert 'PM' in result or 'AM' in result

    def test_format_game_time_none(self):
        """Test None input handling"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightTrendPlaysExporter()

                assert exporter._format_game_time(None) is None

    def test_format_game_time_invalid(self):
        """Test invalid time string handling"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TonightTrendPlaysExporter()

                assert exporter._format_game_time('invalid') is None


class TestConfidenceClassification:
    """Test suite for confidence level classification"""

    def test_streak_confidence_thresholds(self):
        """Test streak confidence: 5+ = high, 3-4 = medium"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # Test with streak of exactly 5 (high)
                mock_client.set_results([
                    {
                        'player_lookup': 'p1',
                        'player_name': 'Player',
                        'team_abbr': 'LAL',
                        'position': 'PG',
                        'streak_direction': 'OVER',
                        'streak_length': 5,
                        'avg_margin': 3.0,
                        'hit_rate_l10': 0.70
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = TonightTrendPlaysExporter()

                result = exporter._query_streak_plays('2024-12-15', {'LAL'})
                assert result[0]['confidence'] == 'high'

    def test_momentum_confidence_thresholds(self):
        """Test momentum confidence: 25%+ = high, 15-25% = medium"""
        with patch('data_processors.publishing.tonight_trend_plays_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # Test with exactly 25% change (high)
                mock_client.set_results([
                    {
                        'player_lookup': 'p1',
                        'player_name': 'Player',
                        'team_abbr': 'BOS',
                        'position': 'SG',
                        'momentum_type': 'surging',
                        'l5_avg': 25.0,
                        'l15_avg': 20.0,
                        'pct_change': 25.0,  # Exactly 25%
                        'ppg_change': 5.0
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = TonightTrendPlaysExporter()

                result = exporter._query_momentum_plays('2024-12-15', {'BOS'})
                assert result[0]['confidence'] == 'high'

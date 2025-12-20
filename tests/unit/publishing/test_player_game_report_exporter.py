"""
Unit Tests for PlayerGameReportExporter

Tests cover:
1. Player profile with shot profile classification
2. Opponent context and defense tier classification
3. Moving averages calculation
4. Prediction angles building logic
5. Head-to-head history
6. Empty data handling
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date

from data_processors.publishing.player_game_report_exporter import (
    PlayerGameReportExporter,
    classify_shot_profile,
    SHOT_PROFILE_THRESHOLDS
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


class TestShotProfileClassification:
    """Test suite for shot profile classification"""

    def test_interior_player(self):
        """Test player with 50%+ paint shots"""
        result = classify_shot_profile(0.55, 0.20, 0.15)
        assert result == 'interior'

    def test_perimeter_player(self):
        """Test player with 50%+ three-point shots"""
        result = classify_shot_profile(0.20, 0.55, 0.15)
        assert result == 'perimeter'

    def test_mid_range_player(self):
        """Test player with 30%+ mid-range shots"""
        result = classify_shot_profile(0.30, 0.30, 0.35)
        assert result == 'mid_range'

    def test_balanced_player(self):
        """Test player with balanced shot distribution"""
        result = classify_shot_profile(0.35, 0.35, 0.25)
        assert result == 'balanced'

    def test_none_values(self):
        """Test handling of None values"""
        result = classify_shot_profile(None, None, None)
        assert result == 'balanced'

    def test_interior_priority(self):
        """Test that interior takes priority when multiple thresholds met"""
        # Interior should be checked first
        result = classify_shot_profile(0.55, 0.55, 0.35)
        assert result == 'interior'


class TestPlayerGameReportExporterInit:
    """Test suite for initialization"""

    def test_initialization(self):
        """Test that exporter initializes correctly"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerGameReportExporter()

                assert exporter.project_id == 'nba-props-platform'
                assert exporter.bucket_name == 'nba-props-platform-api'


class TestPlayerProfile:
    """Test suite for player profile queries"""

    def test_player_profile_with_shot_zones(self):
        """Test player profile returns correct shot profile"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # Perimeter shooter profile
                mock_client.set_results([
                    {
                        'player_lookup': 'stephencurry',
                        'player_name': 'Stephen Curry',
                        'position': 'PG',
                        'team_abbr': 'GSW',
                        'season_ppg': 26.5,
                        'pct_paint': 0.25,
                        'pct_mid_range': 0.15,
                        'pct_three': 0.55
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerGameReportExporter()

                result = exporter._query_player_profile('stephencurry', '2024-12-15')

                assert result is not None
                assert result['player_name'] == 'Stephen Curry'
                assert result['position'] == 'PG'
                assert result['shot_profile'] == 'perimeter'
                assert result['season_ppg'] == 26.5

    def test_player_not_found(self):
        """Test handling when player doesn't exist"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = PlayerGameReportExporter()

                result = exporter._query_player_profile('notaplayer', '2024-12-15')

                assert result is None


class TestOpponentContext:
    """Test suite for opponent context queries"""

    def test_weak_defense(self):
        """Test opponent with weak defense classification"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'team_abbr': 'WAS',
                        'paint_pct_allowed': 0.56,  # > 0.52 = weak
                        'three_pt_pct_allowed': 0.54,  # > 0.52 = weak
                        'overall_defense_rating': 118.5,
                        'opp_pace': 101.2,
                        'def_rank': 28
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerGameReportExporter()

                result = exporter._query_opponent_context('WAS', '2024-12-15')

                assert result['opponent'] == 'WAS'
                assert result['opp_paint_defense'] == 'weak'
                assert result['opp_perimeter_defense'] == 'weak'
                assert result['opp_def_rank'] == 28

    def test_strong_defense(self):
        """Test opponent with strong defense classification"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'team_abbr': 'BOS',
                        'paint_pct_allowed': 0.42,  # <= 0.45 = strong
                        'three_pt_pct_allowed': 0.44,  # <= 0.45 = strong
                        'overall_defense_rating': 105.2,
                        'opp_pace': 98.5,
                        'def_rank': 2
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerGameReportExporter()

                result = exporter._query_opponent_context('BOS', '2024-12-15')

                assert result['opp_paint_defense'] == 'strong'
                assert result['opp_perimeter_defense'] == 'strong'

    def test_no_opponent(self):
        """Test handling of no opponent provided"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerGameReportExporter()

                result = exporter._query_opponent_context(None, '2024-12-15')

                assert result == {}


class TestMovingAverages:
    """Test suite for moving averages calculation"""

    def test_moving_averages(self):
        """Test moving averages are correctly returned"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'l5': 28.2,
                        'l10': 26.8,
                        'l20': 26.1,
                        'season': 25.5
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerGameReportExporter()

                result = exporter._query_moving_averages('stephencurry', '2024-12-15')

                assert result['l5'] == 28.2
                assert result['l10'] == 26.8
                assert result['l20'] == 26.1
                assert result['season'] == 25.5

    def test_empty_moving_averages(self):
        """Test handling when no games found"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = PlayerGameReportExporter()

                result = exporter._query_moving_averages('newplayer', '2024-12-15')

                assert result == {}


class TestPredictionAngles:
    """Test suite for prediction angles building"""

    def test_hot_streak_angle(self):
        """Test hot streak detection"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerGameReportExporter()

                recent_games = [
                    {'result': 'OVER'},
                    {'result': 'OVER'},
                    {'result': 'OVER'},
                    {'result': 'OVER'},
                    {'result': 'UNDER'},
                ]

                result = exporter._build_prediction_angles(
                    {'shot_profile': 'balanced'},
                    {'l5': 26.0, 'season': 25.0},
                    {'opp_pace': 100},
                    {},
                    recent_games
                )

                assert 'Hot streak (4G OVER)' in result['supporting']

    def test_cold_streak_angle(self):
        """Test cold streak detection"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerGameReportExporter()

                recent_games = [
                    {'result': 'UNDER'},
                    {'result': 'UNDER'},
                    {'result': 'UNDER'},
                    {'result': 'OVER'},
                    {'result': 'OVER'},
                ]

                result = exporter._build_prediction_angles(
                    {'shot_profile': 'balanced'},
                    {'l5': 22.0, 'season': 25.0},
                    {'opp_pace': 100},
                    {},
                    recent_games
                )

                assert 'Cold streak (3G UNDER)' in result['against']

    def test_defense_matchup_supporting(self):
        """Test weak defense matchup angle"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerGameReportExporter()

                result = exporter._build_prediction_angles(
                    {'shot_profile': 'perimeter'},
                    {'l5': 25.0, 'season': 25.0},
                    {'opp_perimeter_defense': 'weak', 'opp_pace': 100},
                    {},
                    []
                )

                assert 'Weak perimeter defense' in result['supporting']

    def test_defense_matchup_against(self):
        """Test strong defense matchup angle"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerGameReportExporter()

                result = exporter._build_prediction_angles(
                    {'shot_profile': 'interior'},
                    {'l5': 25.0, 'season': 25.0},
                    {'opp_paint_defense': 'strong', 'opp_pace': 100},
                    {},
                    []
                )

                assert 'Strong paint defense' in result['against']

    def test_trending_up(self):
        """Test trending up angle (15%+ L5 vs season)"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerGameReportExporter()

                result = exporter._build_prediction_angles(
                    {'shot_profile': 'balanced'},
                    {'l5': 30.0, 'season': 25.0},  # 20% increase
                    {'opp_pace': 100},
                    {},
                    []
                )

                # Check for trending up message
                trending = [a for a in result['supporting'] if 'Trending up' in a]
                assert len(trending) == 1

    def test_fast_pace_angle(self):
        """Test fast-paced opponent angle"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerGameReportExporter()

                result = exporter._build_prediction_angles(
                    {'shot_profile': 'balanced'},
                    {'l5': 25.0, 'season': 25.0},
                    {'opp_pace': 105},
                    {},
                    []
                )

                assert 'Fast-paced opponent' in result['supporting']

    def test_slow_pace_angle(self):
        """Test slow-paced opponent angle"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerGameReportExporter()

                result = exporter._build_prediction_angles(
                    {'shot_profile': 'balanced'},
                    {'l5': 25.0, 'season': 25.0},
                    {'opp_pace': 94},
                    {},
                    []
                )

                assert 'Slow-paced opponent' in result['against']

    def test_max_three_angles(self):
        """Test that max 3 angles returned per side"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerGameReportExporter()

                result = exporter._build_prediction_angles(
                    {'shot_profile': 'balanced'},
                    {'l5': 25.0, 'season': 25.0},
                    {'opp_pace': 100},
                    {},
                    []
                )

                assert len(result['supporting']) <= 3
                assert len(result['against']) <= 3


class TestHeadToHead:
    """Test suite for head-to-head history"""

    def test_h2h_with_history(self):
        """Test head-to-head with games played"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'games': 8,
                        'avg_points': 28.5,
                        'avg_line': 26.0,
                        'overs': 6,
                        'unders': 2
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerGameReportExporter()

                result = exporter._query_head_to_head('stephencurry', 'LAL', '2024-12-15')

                assert result['games'] == 8
                assert result['avg_points'] == 28.5
                assert result['over_rate'] == 0.75

    def test_h2h_no_history(self):
        """Test head-to-head with no previous games"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {'games': 0, 'avg_points': None, 'avg_line': None, 'overs': 0, 'unders': 0}
                ])

                mock_bq.return_value = mock_client
                exporter = PlayerGameReportExporter()

                result = exporter._query_head_to_head('stephencurry', 'NEW', '2024-12-15')

                assert result == {'games': 0}


class TestEmptyResponse:
    """Test suite for empty response handling"""

    def test_empty_response_player_not_found(self):
        """Test empty response when player not found"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerGameReportExporter()

                result = exporter._empty_response('notaplayer', '2024-12-15', 'Player not found')

                assert result['player_lookup'] == 'notaplayer'
                assert result['error'] == 'Player not found'
                assert result['player_profile'] is None
                assert result['recent_games'] == []
                assert result['prediction_angles'] == {'supporting': [], 'against': []}


class TestSafeFloat:
    """Test suite for safe float conversion"""

    def test_safe_float_normal(self):
        """Test normal float conversion"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerGameReportExporter()

                assert exporter._safe_float(26.5) == 26.5
                assert exporter._safe_float('26.5') == 26.5

    def test_safe_float_none(self):
        """Test None handling"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerGameReportExporter()

                assert exporter._safe_float(None) is None

    def test_safe_float_nan(self):
        """Test NaN handling"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerGameReportExporter()

                assert exporter._safe_float(float('nan')) is None

    def test_safe_float_invalid(self):
        """Test invalid value handling"""
        with patch('data_processors.publishing.player_game_report_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = PlayerGameReportExporter()

                assert exporter._safe_float('not a number') is None

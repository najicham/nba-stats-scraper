"""
Unit Tests for TonightPlayerExporter

Tests cover:
1. Initialization
2. JSON generation for a player on a date
3. Fatigue scoring and levels
4. Streak computation
5. Tonight's factors building
6. Empty response handling
7. Safe float conversion
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


class TestTonightPlayerExporterInit:
    """Test suite for TonightPlayerExporter initialization"""

    def test_initialization_with_defaults(self):
        """Test that exporter initializes with default project and bucket"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                assert exporter.project_id is not None
                assert exporter.bucket_name is not None


class TestJsonGeneration:
    """Test suite for JSON generation"""

    def test_json_has_required_fields(self):
        """Test that generated JSON has required fields"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                # Mock all query methods
                exporter._query_game_context = Mock(return_value={
                    'player_lookup': 'lebronjames',
                    'player_full_name': 'LeBron James',
                    'game_id': '20250115_LAL_GSW',
                    'team_abbr': 'LAL',
                    'opponent_team_abbr': 'GSW',
                    'home_game': False,
                    'days_rest': 2,
                    'back_to_back': False,
                    'opening_points_line': None,
                    'current_points_line': None,
                    'line_movement': None
                })
                exporter._query_prediction = Mock(return_value=None)
                exporter._query_fatigue = Mock(return_value={'score': 85, 'level': 'normal', 'context': None})
                exporter._query_recent_form = Mock(return_value=[])
                exporter._query_quick_numbers = Mock(return_value={'games_played': 30})
                exporter._query_relevant_splits = Mock(return_value={})
                exporter._query_defense_tier = Mock(return_value=None)

                result = exporter.generate_json('lebronjames', '2025-01-15')

                assert 'player_lookup' in result
                assert 'player_full_name' in result
                assert 'game_date' in result
                assert 'generated_at' in result
                assert 'game_context' in result
                assert 'quick_numbers' in result
                assert 'fatigue' in result
                assert 'current_streak' in result
                assert 'tonights_factors' in result
                assert 'recent_form' in result
                assert 'prediction' in result
                assert 'opponent_defense' in result
                assert 'line_movement' in result

    def test_json_has_opponent_defense_from_tier(self):
        """Test that opponent_defense is populated from defense tier data"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                exporter._query_game_context = Mock(return_value={
                    'player_lookup': 'lebronjames',
                    'player_full_name': 'LeBron James',
                    'game_id': '20250115_LAL_GSW',
                    'team_abbr': 'LAL',
                    'opponent_team_abbr': 'GSW',
                    'home_game': False,
                    'days_rest': 2,
                    'back_to_back': False,
                    'opening_points_line': None,
                    'current_points_line': None,
                    'line_movement': None
                })
                exporter._query_prediction = Mock(return_value=None)
                exporter._query_fatigue = Mock(return_value={'score': 85, 'level': 'normal', 'context': None})
                exporter._query_recent_form = Mock(return_value=[])
                exporter._query_quick_numbers = Mock(return_value={'games_played': 30})
                exporter._query_relevant_splits = Mock(return_value={})
                exporter._query_defense_tier = Mock(return_value={
                    'rank': 5,
                    'tier_label': 'elite',
                    'ppg_allowed': 106.2,
                    'def_rating': 108.5
                })

                result = exporter.generate_json('lebronjames', '2025-01-15')

                assert result['opponent_defense'] is not None
                assert result['opponent_defense']['rating'] == 106.2
                assert result['opponent_defense']['rank'] == 5

    def test_days_rest_fallback_from_recent_form(self):
        """Test days_rest computed from recent_form when UPCG has null"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                exporter._query_game_context = Mock(return_value={
                    'player_lookup': 'bobbyportis',
                    'player_full_name': 'Bobby Portis',
                    'game_id': '20250115_MIL_CHI',
                    'team_abbr': 'MIL',
                    'opponent_team_abbr': 'CHI',
                    'home_game': False,
                    'days_rest': None,  # null from UPCG
                    'back_to_back': False,
                    'opening_points_line': None,
                    'current_points_line': None,
                    'line_movement': None
                })
                exporter._query_prediction = Mock(return_value=None)
                exporter._query_fatigue = Mock(return_value={'score': 85, 'level': 'normal', 'context': None})
                exporter._query_recent_form = Mock(return_value=[
                    {'game_date': '2025-01-13', 'opponent': 'BOS', 'points': 18, 'is_dnp': False,
                     'over_under': 'OVER', 'line': 15.5, 'margin': 3}
                ])
                exporter._query_quick_numbers = Mock(return_value={'games_played': 30})
                exporter._query_relevant_splits = Mock(return_value={})
                exporter._query_defense_tier = Mock(return_value=None)

                result = exporter.generate_json('bobbyportis', '2025-01-15')

                assert result['game_context']['days_rest'] == 2  # Jan 15 - Jan 13

    def test_empty_response_when_no_game(self):
        """Test empty response when player has no game"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                exporter._query_game_context = Mock(return_value=None)

                result = exporter.generate_json('unknownplayer', '2025-01-15')

                assert result['player_lookup'] == 'unknownplayer'
                assert result['game_context'] is None
                assert result['prediction'] is None


class TestFatigueScoring:
    """Test suite for fatigue scoring and levels"""

    def test_fatigue_level_fresh(self):
        """Test that high fatigue score maps to 'fresh' level"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                # Mock query to return high score
                mock_result = [{'fatigue_score': 98, 'fatigue_context_json': None}]
                exporter.query_to_list = Mock(return_value=mock_result)

                result = exporter._query_fatigue('player1', '2025-01-15')

                assert result['level'] == 'fresh'
                assert result['score'] == 98.0

    def test_fatigue_level_normal(self):
        """Test that medium fatigue score maps to 'normal' level"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                mock_result = [{'fatigue_score': 80, 'fatigue_context_json': None}]
                exporter.query_to_list = Mock(return_value=mock_result)

                result = exporter._query_fatigue('player1', '2025-01-15')

                assert result['level'] == 'normal'

    def test_fatigue_level_tired(self):
        """Test that low fatigue score maps to 'tired' level"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                mock_result = [{'fatigue_score': 60, 'fatigue_context_json': None}]
                exporter.query_to_list = Mock(return_value=mock_result)

                result = exporter._query_fatigue('player1', '2025-01-15')

                assert result['level'] == 'tired'

    def test_fatigue_context_json_string_parsed(self):
        """Test that fatigue_context_json string is parsed to dict"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                mock_result = [{'fatigue_score': 80, 'fatigue_context_json': '{"days_rest": 0, "back_to_back": false}'}]
                exporter.query_to_list = Mock(return_value=mock_result)

                result = exporter._query_fatigue('player1', '2025-01-15')

                assert isinstance(result['context'], dict)
                assert result['context']['days_rest'] == 0
                assert result['context']['back_to_back'] is False

    def test_fatigue_context_already_dict(self):
        """Test that fatigue_context_json dict is passed through"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                ctx = {"days_rest": 2, "back_to_back": False}
                mock_result = [{'fatigue_score': 90, 'fatigue_context_json': ctx}]
                exporter.query_to_list = Mock(return_value=mock_result)

                result = exporter._query_fatigue('player1', '2025-01-15')

                assert isinstance(result['context'], dict)
                assert result['context']['days_rest'] == 2


class TestStreakComputation:
    """Test suite for streak computation"""

    def test_over_streak(self):
        """Test computing an OVER streak"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                recent_form = [
                    {'over_under': 'OVER'},
                    {'over_under': 'OVER'},
                    {'over_under': 'OVER'},
                    {'over_under': 'UNDER'}
                ]

                streak = exporter._compute_streak(recent_form)

                assert streak['type'] == 'over'
                assert streak['length'] == 3

    def test_under_streak(self):
        """Test computing an UNDER streak"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                recent_form = [
                    {'over_under': 'UNDER'},
                    {'over_under': 'UNDER'},
                    {'over_under': 'OVER'}
                ]

                streak = exporter._compute_streak(recent_form)

                assert streak['type'] == 'under'
                assert streak['length'] == 2

    def test_no_streak(self):
        """Test no streak when empty form"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                streak = exporter._compute_streak([])

                assert streak['type'] is None
                assert streak['length'] == 0


class TestCandidateAngles:
    """Test suite for candidate angles building"""

    # Shared defaults for new params that most old tests don't care about
    _defaults = dict(
        recent_form=[], quick_numbers={'season_ppg': 24.0, 'season_mpg': 34.0},
        prediction=None, streak={'type': None, 'length': 0}
    )

    def test_back_to_back_angle(self):
        """Test that B2B angle is produced with correct direction"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                context = {
                    'back_to_back': True,
                    'home_game': True,
                    'opponent_team_abbr': 'GSW',
                    'days_rest': 1
                }
                splits = {
                    'b2b_ppg': 22.5,
                    'non_b2b_ppg': 25.0,
                    'b2b_games': 5,
                    'home_ppg': 25.0,
                    'away_ppg': 23.0,
                    'home_games': 10,
                }

                angles = exporter._build_candidate_angles(
                    context, {'level': 'normal'}, splits, None, **self._defaults
                )

                b2b = next((a for a in angles if a['id'] == 'b2b'), None)
                assert b2b is not None
                assert b2b['direction'] == 'negative'
                assert 0 < b2b['magnitude'] <= 1.0
                assert 'id' in b2b and 'factor' in b2b and 'description' in b2b

    def test_fatigue_angle_when_tired(self):
        """Test that fatigue angle is produced when tired"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                context = {
                    'back_to_back': False,
                    'home_game': None,
                    'opponent_team_abbr': 'GSW',
                    'days_rest': 2
                }

                angles = exporter._build_candidate_angles(
                    context, {'level': 'tired', 'score': 60}, {}, None, **self._defaults
                )

                fat = next((a for a in angles if a['id'] == 'fatigue'), None)
                assert fat is not None
                assert fat['direction'] == 'negative'
                assert fat['magnitude'] > 0
                assert 'score' not in fat['description'].lower()  # No raw fatigue score shown

    def test_fresh_fatigue_deduped_when_rest_present(self):
        """Test that fresh fatigue angle is dropped when rest angle exists"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                context = {
                    'back_to_back': False,
                    'home_game': None,
                    'opponent_team_abbr': 'GSW',
                    'days_rest': 4  # triggers rest angle
                }
                splits = {'rested_ppg': 26.0}

                angles = exporter._build_candidate_angles(
                    context, {'level': 'fresh', 'score': 100}, splits, None, **self._defaults
                )

                rest = next((a for a in angles if a['id'] == 'rest'), None)
                fatigue = next((a for a in angles if a['id'] == 'fatigue'), None)
                assert rest is not None
                assert fatigue is None  # deduped

    def test_opponent_defense_angle(self):
        """Test opponent defense angle for elite defense"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                context = {
                    'back_to_back': False,
                    'home_game': None,
                    'opponent_team_abbr': 'BOS',
                    'days_rest': 2
                }
                defense_tier = {
                    'rank': 3,
                    'tier_label': 'elite',
                    'ppg_allowed': 105.5
                }

                angles = exporter._build_candidate_angles(
                    context, {'level': 'normal'}, {}, defense_tier, **self._defaults
                )

                d = next((a for a in angles if a['id'] == 'opponent_defense'), None)
                assert d is not None
                assert d['direction'] == 'negative'

    def test_returns_max_4_angles(self):
        """Test that at most 4 angles are returned even with many candidates"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                context = {
                    'back_to_back': True,
                    'home_game': True,
                    'opponent_team_abbr': 'BOS',
                    'days_rest': 1
                }
                splits = {
                    'b2b_ppg': 20.0, 'non_b2b_ppg': 26.0, 'b2b_games': 5,
                    'home_ppg': 27.0, 'away_ppg': 21.0, 'home_games': 15,
                    'vs_opponent_ppg': 30.0, 'vs_opponent_games': 3,
                }
                defense_tier = {'rank': 2, 'tier_label': 'elite', 'ppg_allowed': 104.0}
                qn = {'season_ppg': 24.0, 'season_mpg': 34.0, 'last_5_ppg': 30.0, 'last_10_ppg': 25.0, 'last_5_mpg': 38.0}

                angles = exporter._build_candidate_angles(
                    context, {'level': 'tired', 'score': 55}, splits, defense_tier,
                    recent_form=[], quick_numbers=qn, prediction={'current_points_line': 20.0},
                    streak={'type': None, 'length': 0}
                )

                assert len(angles) <= 4

    def test_angles_sorted_by_magnitude(self):
        """Test that returned angles are sorted by magnitude descending"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                context = {
                    'back_to_back': True,
                    'home_game': True,
                    'opponent_team_abbr': 'BOS',
                    'days_rest': 1
                }
                splits = {
                    'b2b_ppg': 20.0, 'non_b2b_ppg': 26.0, 'b2b_games': 5,
                    'home_ppg': 27.0, 'away_ppg': 21.0, 'home_games': 15,
                }
                qn = {'season_ppg': 24.0, 'season_mpg': 34.0, 'last_5_ppg': 30.0}

                angles = exporter._build_candidate_angles(
                    context, {'level': 'tired', 'score': 55}, splits, None,
                    recent_form=[], quick_numbers=qn, prediction=None,
                    streak={'type': None, 'length': 0}
                )

                magnitudes = [a['magnitude'] for a in angles]
                assert magnitudes == sorted(magnitudes, reverse=True)

    def test_scoring_trend_angle(self):
        """Test scoring trend angle when last 5 diverges from season"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                context = {'back_to_back': False, 'home_game': None, 'opponent_team_abbr': 'MIA', 'days_rest': 2}
                qn = {'season_ppg': 22.0, 'season_mpg': 32.0, 'last_5_ppg': 28.0}

                angles = exporter._build_candidate_angles(
                    context, {'level': 'normal'}, {}, None,
                    recent_form=[], quick_numbers=qn, prediction=None,
                    streak={'type': None, 'length': 0}
                )

                trend = next((a for a in angles if a['id'] == 'scoring_trend'), None)
                assert trend is not None
                assert trend['direction'] == 'positive'
                assert 'Surge' in trend['factor']
                assert '28.0' in trend['description']

    def test_streak_angle(self):
        """Test streak angle when player has 4+ straight OVERs"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                context = {'back_to_back': False, 'home_game': None, 'opponent_team_abbr': 'CHI', 'days_rest': 2}
                recent = [
                    {'over_under': 'OVER', 'is_dnp': False},
                    {'over_under': 'OVER', 'is_dnp': False},
                    {'over_under': 'OVER', 'is_dnp': False},
                    {'over_under': 'OVER', 'is_dnp': False},
                    {'over_under': 'UNDER', 'is_dnp': False},
                ]

                angles = exporter._build_candidate_angles(
                    context, {'level': 'normal'}, {}, None,
                    recent_form=recent, quick_numbers={'season_ppg': 20.0, 'season_mpg': 30.0},
                    prediction=None, streak={'type': 'over', 'length': 4}
                )

                s = next((a for a in angles if a['id'] == 'streak'), None)
                assert s is not None
                assert s['direction'] == 'positive'
                assert '4 straight OVERs' in s['description']

    def test_fg_efficiency_angle(self):
        """Test FG efficiency angle from recent_form fg strings"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                context = {'back_to_back': False, 'home_game': None, 'opponent_team_abbr': 'DEN', 'days_rest': 2}
                # Last 5: 10/18 each = 55.6%, All 10: first 5 at 10/18, last 5 at 5/18 = 41.7% overall
                recent = []
                for _ in range(5):
                    recent.append({'fg': '10/18', 'is_dnp': False, 'over_under': 'OVER'})
                for _ in range(5):
                    recent.append({'fg': '5/18', 'is_dnp': False, 'over_under': 'UNDER'})

                angles = exporter._build_candidate_angles(
                    context, {'level': 'normal'}, {}, None,
                    recent_form=recent, quick_numbers={'season_ppg': 20.0, 'season_mpg': 30.0},
                    prediction=None, streak={'type': None, 'length': 0}
                )

                fg = next((a for a in angles if a['id'] == 'fg_efficiency'), None)
                assert fg is not None
                assert fg['direction'] == 'positive'
                assert 'Shooting Hot' in fg['factor']

    def test_parse_fg_helper(self):
        """Test FG string parsing"""
        from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
        assert TonightPlayerExporter._parse_fg('10/18') == (10, 18)
        assert TonightPlayerExporter._parse_fg('0/5') == (0, 5)
        assert TonightPlayerExporter._parse_fg(None) is None
        assert TonightPlayerExporter._parse_fg('') is None
        assert TonightPlayerExporter._parse_fg('bad') is None


class TestLineMovementFormatting:
    """Test suite for line movement formatting"""

    def test_line_movement_with_data(self):
        """Test line movement when opening and current lines exist"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                context = {'opening_points_line': 26.5, 'current_points_line': 25.5, 'line_movement': -1.0}
                prediction = {'recommendation': 'OVER'}

                result = exporter._format_line_movement(context, prediction)

                assert result is not None
                assert result['opened'] == 26.5
                assert result['current'] == 25.5
                assert result['movement'] == -1.0
                assert result['favorable'] is True  # Line dropped, we say OVER

    def test_line_movement_unfavorable(self):
        """Test line movement marked unfavorable when moving against recommendation"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                context = {'opening_points_line': 20.5, 'current_points_line': 23.5, 'line_movement': 3.0}
                prediction = {'recommendation': 'OVER'}

                result = exporter._format_line_movement(context, prediction)

                assert result['favorable'] is False  # Line rose, we say OVER = harder

    def test_line_movement_null_when_no_opening(self):
        """Test line movement returns null when opening line missing"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                context = {'opening_points_line': None, 'current_points_line': 25.5, 'line_movement': None}

                result = exporter._format_line_movement(context, None)

                assert result is None

    def test_line_movement_no_movement(self):
        """Test line movement when line hasn't moved"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                context = {'opening_points_line': 25.5, 'current_points_line': 25.5, 'line_movement': 0.0}
                prediction = {'recommendation': 'OVER'}

                result = exporter._format_line_movement(context, prediction)

                assert result['movement'] == 0.0
                assert result['favorable'] is None  # No movement = no direction


class TestPredictionFormatting:
    """Test suite for prediction formatting"""

    def test_format_prediction(self):
        """Test prediction data formatting with display confidence"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                prediction = {
                    'predicted_points': 25.5,
                    'confidence_score': 90.0,
                    'recommendation': 'OVER',
                    'current_points_line': 23.5,
                    'line_margin': 2.0,
                    'pace_adjustment': 0.5,
                    'similar_games_count': 15
                }

                result = exporter._format_prediction(prediction)

                assert result['predicted_points'] == 25.5
                # Display confidence: edge=2.0 → 14 + quality=(90-75)*1.5=22.5 + base=15 = 52
                assert result['confidence_score'] == 52
                assert result['recommendation'] == 'OVER'
                assert result['line'] == 23.5
                assert result['edge'] == 2.0


class TestSafeFloat:
    """Test suite for safe float conversion (module-level utility)"""

    def test_safe_float_with_valid_number(self):
        """Test safe float with valid number"""
        from data_processors.publishing.exporter_utils import safe_float

        assert safe_float(5.555) == 5.55  # Python banker's rounding
        assert safe_float(10) == 10.0

    def test_safe_float_with_none(self):
        """Test safe float with None"""
        from data_processors.publishing.exporter_utils import safe_float

        assert safe_float(None) is None

    def test_safe_float_with_nan(self):
        """Test safe float with NaN"""
        from data_processors.publishing.exporter_utils import safe_float

        assert safe_float(float('nan')) is None

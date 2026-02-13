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


class TestTonightsFactors:
    """Test suite for tonight's factors building"""

    def test_back_to_back_factor(self):
        """Test that B2B factor is added"""
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
                fatigue = {'level': 'normal'}
                splits = {
                    'b2b_ppg': 22.5,
                    'non_b2b_ppg': 25.0,
                    'b2b_vs_line_pct': 0.45
                }

                factors = exporter._build_tonights_factors(context, fatigue, splits)

                b2b_factor = next((f for f in factors if f['factor'] == 'back_to_back'), None)
                assert b2b_factor is not None
                assert b2b_factor['direction'] == 'negative'

    def test_fatigue_factor_when_tired(self):
        """Test that fatigue factor is added when tired"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                context = {
                    'back_to_back': False,
                    'home_game': True,
                    'opponent_team_abbr': 'GSW',
                    'days_rest': 2
                }
                fatigue = {'level': 'tired', 'score': 60}
                splits = {}

                factors = exporter._build_tonights_factors(context, fatigue, splits)

                fatigue_factor = next((f for f in factors if f['factor'] == 'fatigue'), None)
                assert fatigue_factor is not None
                assert fatigue_factor['direction'] == 'negative'

    def test_opponent_defense_factor(self):
        """Test opponent defense factor"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
                exporter = TonightPlayerExporter()

                context = {
                    'back_to_back': False,
                    'home_game': True,
                    'opponent_team_abbr': 'BOS',
                    'days_rest': 2
                }
                fatigue = {'level': 'normal'}
                splits = {}
                defense_tier = {
                    'rank': 3,
                    'tier_label': 'elite',
                    'ppg_allowed': 105.5
                }

                factors = exporter._build_tonights_factors(context, fatigue, splits, defense_tier)

                def_factor = next((f for f in factors if f['factor'] == 'opponent_defense'), None)
                assert def_factor is not None
                assert def_factor['direction'] == 'negative'
                assert def_factor['defense_tier'] == 'elite'


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

"""
Unit Tests for PlayerProfileExporter

Tests cover:
1. Initialization
2. Index JSON generation
3. Player detail JSON generation
4. Interpretation building
5. Empty player response
6. Safe float conversion
7. Recent predictions formatting
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


class TestPlayerProfileExporterInit:
    """Test suite for PlayerProfileExporter initialization"""

    def test_initialization_with_defaults(self):
        """Test that exporter initializes with default project and bucket"""
        with patch('data_processors.publishing.player_profile_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.player_profile_exporter import PlayerProfileExporter
                exporter = PlayerProfileExporter()

                assert exporter.project_id is not None
                assert exporter.bucket_name is not None


class TestIndexJsonGeneration:
    """Test suite for index JSON generation"""

    def test_index_json_structure(self):
        """Test that index JSON has required structure"""
        with patch('data_processors.publishing.player_profile_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.player_profile_exporter import PlayerProfileExporter
                exporter = PlayerProfileExporter()

                # Mock player summaries query
                exporter._query_player_summaries = Mock(return_value=[
                    {
                        'player_lookup': 'lebronjames',
                        'player_full_name': 'LeBron James',
                        'team_abbr': 'LAL',
                        'games_predicted': 50,
                        'recommendations': 45,
                        'mae': 4.5,
                        'win_rate': 0.72,
                        'bias': -1.2,
                        'within_5_pct': 0.65
                    }
                ])

                result = exporter.generate_index_json()

                assert 'generated_at' in result
                assert 'total_players' in result
                assert 'players' in result
                assert result['total_players'] == 1

    def test_index_json_empty_players(self):
        """Test index JSON with no players"""
        with patch('data_processors.publishing.player_profile_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.player_profile_exporter import PlayerProfileExporter
                exporter = PlayerProfileExporter()

                exporter._query_player_summaries = Mock(return_value=[])

                result = exporter.generate_index_json()

                assert result['total_players'] == 0
                assert result['players'] == []

    def test_players_sorted_by_games_predicted(self):
        """Test that players are sorted by games predicted descending"""
        with patch('data_processors.publishing.player_profile_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.player_profile_exporter import PlayerProfileExporter
                exporter = PlayerProfileExporter()

                exporter._query_player_summaries = Mock(return_value=[
                    {'player_lookup': 'player1', 'games_predicted': 10, 'recommendations': 8, 'mae': 5, 'win_rate': 0.6, 'bias': 0, 'within_5_pct': 0.5},
                    {'player_lookup': 'player2', 'games_predicted': 50, 'recommendations': 40, 'mae': 4, 'win_rate': 0.7, 'bias': 0, 'within_5_pct': 0.6},
                    {'player_lookup': 'player3', 'games_predicted': 25, 'recommendations': 20, 'mae': 4.5, 'win_rate': 0.65, 'bias': 0, 'within_5_pct': 0.55}
                ])

                result = exporter.generate_index_json()

                assert result['players'][0]['player_lookup'] == 'player2'
                assert result['players'][1]['player_lookup'] == 'player3'
                assert result['players'][2]['player_lookup'] == 'player1'


class TestPlayerDetailJsonGeneration:
    """Test suite for player detail JSON generation"""

    def test_player_json_structure(self):
        """Test that player detail JSON has required structure"""
        with patch('data_processors.publishing.player_profile_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.player_profile_exporter import PlayerProfileExporter
                exporter = PlayerProfileExporter()

                # Mock all query methods
                exporter._query_player_summary = Mock(return_value={
                    'player_lookup': 'lebronjames',
                    'player_full_name': 'LeBron James',
                    'team_abbr': 'LAL',
                    'games_predicted': 50,
                    'recommendations': 45,
                    'correct': 32,
                    'mae': 4.5,
                    'win_rate': 0.71,
                    'bias': -1.2,
                    'avg_confidence': 0.65,
                    'within_3_pct': 0.45,
                    'within_5_pct': 0.65,
                    'first_date': '2024-10-22',
                    'last_date': '2025-01-15'
                })
                exporter._query_game_log = Mock(return_value=[])
                exporter._query_splits = Mock(return_value={})
                exporter._query_track_record = Mock(return_value={})
                exporter._query_next_game = Mock(return_value=None)
                exporter._query_recent_news = Mock(return_value=[])

                result = exporter.generate_player_json('lebronjames')

                assert 'player_lookup' in result
                assert 'player_full_name' in result
                assert 'generated_at' in result
                assert 'summary' in result
                assert 'interpretation' in result
                assert 'game_log' in result
                assert 'splits' in result
                assert 'our_track_record' in result
                assert 'next_game' in result

    def test_empty_player_response(self):
        """Test response for player with no data"""
        with patch('data_processors.publishing.player_profile_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.player_profile_exporter import PlayerProfileExporter
                exporter = PlayerProfileExporter()

                exporter._query_player_summary = Mock(return_value=None)

                result = exporter.generate_player_json('unknownplayer')

                assert result['player_lookup'] == 'unknownplayer'
                assert result['summary'] is None
                assert 'error' in result['interpretation']


class TestInterpretationBuilding:
    """Test suite for interpretation building"""

    def test_bias_interpretation_under_predict(self):
        """Test bias interpretation for under-prediction"""
        with patch('data_processors.publishing.player_profile_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.player_profile_exporter import PlayerProfileExporter
                exporter = PlayerProfileExporter()

                summary = {'bias': -4, 'win_rate': 0.6, 'games_predicted': 20, 'recommendations': 15}
                interp = exporter._build_interpretation(summary)

                assert 'under-predict' in interp.get('bias', '').lower()

    def test_bias_interpretation_over_predict(self):
        """Test bias interpretation for over-prediction"""
        with patch('data_processors.publishing.player_profile_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.player_profile_exporter import PlayerProfileExporter
                exporter = PlayerProfileExporter()

                summary = {'bias': 4, 'win_rate': 0.6, 'games_predicted': 20, 'recommendations': 15}
                interp = exporter._build_interpretation(summary)

                assert 'over-predict' in interp.get('bias', '').lower()

    def test_bias_interpretation_well_calibrated(self):
        """Test bias interpretation for well-calibrated predictions"""
        with patch('data_processors.publishing.player_profile_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.player_profile_exporter import PlayerProfileExporter
                exporter = PlayerProfileExporter()

                summary = {'bias': 0.5, 'win_rate': 0.6, 'games_predicted': 20, 'recommendations': 15}
                interp = exporter._build_interpretation(summary)

                assert 'calibrated' in interp.get('bias', '').lower()

    def test_accuracy_interpretation_excellent(self):
        """Test accuracy interpretation for excellent win rate"""
        with patch('data_processors.publishing.player_profile_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.player_profile_exporter import PlayerProfileExporter
                exporter = PlayerProfileExporter()

                summary = {'bias': 0, 'win_rate': 0.90, 'games_predicted': 20, 'recommendations': 15}
                interp = exporter._build_interpretation(summary)

                assert 'excellent' in interp.get('accuracy', '').lower()

    def test_sample_size_interpretation_limited(self):
        """Test sample size interpretation for few games"""
        with patch('data_processors.publishing.player_profile_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.player_profile_exporter import PlayerProfileExporter
                exporter = PlayerProfileExporter()

                summary = {'bias': 0, 'win_rate': 0.6, 'games_predicted': 3, 'recommendations': 2}
                interp = exporter._build_interpretation(summary)

                assert 'limited' in interp.get('sample_size', '').lower()


class TestSafeFloat:
    """Test suite for safe float conversion"""

    def test_safe_float_with_valid_number(self):
        """Test safe float with valid number"""
        with patch('data_processors.publishing.player_profile_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.player_profile_exporter import PlayerProfileExporter
                exporter = PlayerProfileExporter()

                assert exporter._safe_float(5.123456) == 0.123
                assert exporter._safe_float(10.0) == 10.0

    def test_safe_float_with_none(self):
        """Test safe float with None"""
        with patch('data_processors.publishing.player_profile_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.player_profile_exporter import PlayerProfileExporter
                exporter = PlayerProfileExporter()

                assert exporter._safe_float(None) is None

    def test_safe_float_with_nan(self):
        """Test safe float with NaN"""
        with patch('data_processors.publishing.player_profile_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.player_profile_exporter import PlayerProfileExporter
                exporter = PlayerProfileExporter()

                assert exporter._safe_float(float('nan')) is None

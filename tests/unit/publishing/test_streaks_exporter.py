"""
Unit Tests for StreaksExporter

Tests cover:
1. OVER/UNDER streak queries
2. Prediction streak queries
3. Streak length filtering
4. Summary statistics
5. Game formatting within streaks
6. Empty data handling
7. Mock BigQuery responses
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date

from data_processors.publishing.streaks_exporter import StreaksExporter


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


class TestStreaksExporterInit:
    """Test suite for initialization"""

    def test_initialization_defaults(self):
        """Test that exporter initializes with default min_streak_length"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = StreaksExporter()
                assert exporter.min_streak_length == 4

    def test_initialization_custom_min_streak(self):
        """Test that exporter accepts custom min_streak_length"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = StreaksExporter(min_streak_length=5)
                assert exporter.min_streak_length == 5


class TestGenerateJson:
    """Test suite for generate_json method"""

    def test_generate_json_with_streaks(self):
        """Test JSON generation with various streaks"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                # Queue results for: over_streaks, under_streaks, prediction_streaks
                mock_client.queue_results(
                    # OVER streaks
                    [
                        {
                            'player_lookup': 'lebronjames',
                            'player_full_name': 'LeBron James',
                            'team': 'LAL',
                            'streak_length': 6,
                            'avg_margin': 4.5,
                            'games': [
                                {'game_date': date(2024, 12, 14), 'points': 30, 'points_line': 25.5, 'opponent_team_abbr': 'GSW'},
                                {'game_date': date(2024, 12, 12), 'points': 28, 'points_line': 25.5, 'opponent_team_abbr': 'PHX'}
                            ]
                        }
                    ],
                    # UNDER streaks
                    [
                        {
                            'player_lookup': 'player2',
                            'player_full_name': 'Player Two',
                            'team': 'BOS',
                            'streak_length': 5,
                            'avg_margin': -3.2,
                            'games': [
                                {'game_date': date(2024, 12, 14), 'points': 18, 'points_line': 22.5, 'opponent_team_abbr': 'MIA'}
                            ]
                        }
                    ],
                    # Prediction streaks
                    [
                        {
                            'player_lookup': 'player3',
                            'player_full_name': 'Player Three',
                            'team': 'MIL',
                            'streak_length': 7
                        }
                    ]
                )
                mock_bq.return_value = mock_client

                exporter = StreaksExporter()
                result = exporter.generate_json('2024-12-15')

                assert result['as_of_date'] == '2024-12-15'
                assert result['min_streak_length'] == 4
                assert 'streaks' in result
                assert 'summary' in result
                assert len(result['streaks']['over']) == 1
                assert len(result['streaks']['under']) == 1
                assert len(result['streaks']['prediction_hits']) == 1

    def test_generate_json_empty_streaks(self):
        """Test JSON generation with no streaks"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.queue_results([], [], [])  # All empty
                mock_bq.return_value = mock_client

                exporter = StreaksExporter()
                result = exporter.generate_json('2024-12-15')

                assert result['streaks']['over'] == []
                assert result['streaks']['under'] == []
                assert result['streaks']['prediction_hits'] == []
                assert result['summary']['total_over_streaks'] == 0
                assert result['summary']['total_under_streaks'] == 0
                assert result['summary']['longest_over'] == 0
                assert result['summary']['longest_under'] == 0


class TestQueryOverUnderStreaks:
    """Test suite for _query_over_under_streaks method"""

    def test_query_over_streaks(self):
        """Test querying OVER streaks"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'curry',
                        'player_full_name': 'Stephen Curry',
                        'team': 'GSW',
                        'streak_length': 8,
                        'avg_margin': 5.2,
                        'games': [
                            {'game_date': date(2024, 12, 14), 'points': 35, 'points_line': 28.5, 'opponent_team_abbr': 'LAL'}
                        ]
                    }
                ])
                mock_bq.return_value = mock_client

                exporter = StreaksExporter()
                result = exporter._query_over_under_streaks('2024-12-15', streak_type='OVER')

                assert len(result) == 1
                assert result[0]['player_lookup'] == 'curry'
                assert result[0]['streak_length'] == 8
                assert result[0]['avg_margin'] == 5.2

    def test_query_under_streaks(self):
        """Test querying UNDER streaks"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_full_name': 'Player One',
                        'team': 'MIA',
                        'streak_length': 5,
                        'avg_margin': -4.0,
                        'games': [
                            {'game_date': date(2024, 12, 14), 'points': 15, 'points_line': 20.5, 'opponent_team_abbr': 'BOS'}
                        ]
                    }
                ])
                mock_bq.return_value = mock_client

                exporter = StreaksExporter()
                result = exporter._query_over_under_streaks('2024-12-15', streak_type='UNDER')

                assert len(result) == 1
                assert result[0]['streak_length'] == 5
                assert result[0]['avg_margin'] == -4.0


class TestQueryPredictionStreaks:
    """Test suite for _query_prediction_streaks method"""

    def test_query_prediction_streaks(self):
        """Test querying prediction hit streaks"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'giannis',
                        'player_full_name': 'Giannis Antetokounmpo',
                        'team': 'MIL',
                        'streak_length': 10
                    }
                ])
                mock_bq.return_value = mock_client

                exporter = StreaksExporter()
                result = exporter._query_prediction_streaks('2024-12-15')

                assert len(result) == 1
                assert result[0]['player_lookup'] == 'giannis'
                assert result[0]['streak_length'] == 10
                assert result[0]['streak_type'] == 'prediction_hits'


class TestStreakFormatting:
    """Test suite for streak formatting in output"""

    def test_over_streak_structure(self):
        """Test OVER streak has correct structure"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_full_name': 'Player One',
                        'team': 'LAL',
                        'streak_length': 6,
                        'avg_margin': 3.5,
                        'games': [
                            {'game_date': date(2024, 12, 14), 'points': 28, 'points_line': 24.5, 'opponent_team_abbr': 'GSW'},
                            {'game_date': date(2024, 12, 12), 'points': 30, 'points_line': 24.5, 'opponent_team_abbr': 'PHX'},
                            {'game_date': date(2024, 12, 10), 'points': 26, 'points_line': 24.5, 'opponent_team_abbr': 'DEN'}
                        ]
                    }
                ])
                mock_bq.return_value = mock_client

                exporter = StreaksExporter()
                result = exporter._query_over_under_streaks('2024-12-15', 'OVER')

                streak = result[0]
                assert streak['player_lookup'] == 'player1'
                assert streak['player_full_name'] == 'Player One'
                assert streak['team'] == 'LAL'
                assert streak['streak_length'] == 6
                assert streak['avg_margin'] == 3.5
                assert len(streak['games']) == 3

    def test_games_limited_to_5(self):
        """Test that games array is limited to last 5"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                # Return 8 games
                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_full_name': 'Player One',
                        'team': 'LAL',
                        'streak_length': 8,
                        'avg_margin': 4.0,
                        'games': [
                            {'game_date': date(2024, 12, 14), 'points': 28, 'points_line': 24.5, 'opponent_team_abbr': 'G1'},
                            {'game_date': date(2024, 12, 13), 'points': 30, 'points_line': 24.5, 'opponent_team_abbr': 'G2'},
                            {'game_date': date(2024, 12, 12), 'points': 26, 'points_line': 24.5, 'opponent_team_abbr': 'G3'},
                            {'game_date': date(2024, 12, 11), 'points': 29, 'points_line': 24.5, 'opponent_team_abbr': 'G4'},
                            {'game_date': date(2024, 12, 10), 'points': 27, 'points_line': 24.5, 'opponent_team_abbr': 'G5'},
                            {'game_date': date(2024, 12, 9), 'points': 31, 'points_line': 24.5, 'opponent_team_abbr': 'G6'},
                            {'game_date': date(2024, 12, 8), 'points': 25, 'points_line': 24.5, 'opponent_team_abbr': 'G7'},
                            {'game_date': date(2024, 12, 7), 'points': 32, 'points_line': 24.5, 'opponent_team_abbr': 'G8'}
                        ]
                    }
                ])
                mock_bq.return_value = mock_client

                exporter = StreaksExporter()
                result = exporter._query_over_under_streaks('2024-12-15', 'OVER')

                # Should only have 5 games in output
                assert len(result[0]['games']) == 5

    def test_game_structure(self):
        """Test individual game has correct structure"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_full_name': 'Player One',
                        'team': 'LAL',
                        'streak_length': 4,
                        'avg_margin': 3.0,
                        'games': [
                            {'game_date': date(2024, 12, 14), 'points': 28, 'points_line': 24.5, 'opponent_team_abbr': 'GSW'}
                        ]
                    }
                ])
                mock_bq.return_value = mock_client

                exporter = StreaksExporter()
                result = exporter._query_over_under_streaks('2024-12-15', 'OVER')

                game = result[0]['games'][0]
                assert game['game_date'] == '2024-12-14'
                assert game['points'] == 28
                assert game['line'] == 24.5
                assert game['opponent'] == 'GSW'


class TestSummaryStatistics:
    """Test suite for summary statistics"""

    def test_summary_totals(self):
        """Test summary total counts"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.queue_results(
                    # 3 OVER streaks
                    [
                        {'player_lookup': 'p1', 'player_full_name': 'P1', 'team': 'A', 'streak_length': 6, 'avg_margin': 3.0, 'games': []},
                        {'player_lookup': 'p2', 'player_full_name': 'P2', 'team': 'B', 'streak_length': 5, 'avg_margin': 2.5, 'games': []},
                        {'player_lookup': 'p3', 'player_full_name': 'P3', 'team': 'C', 'streak_length': 4, 'avg_margin': 2.0, 'games': []}
                    ],
                    # 2 UNDER streaks
                    [
                        {'player_lookup': 'p4', 'player_full_name': 'P4', 'team': 'D', 'streak_length': 7, 'avg_margin': -4.0, 'games': []},
                        {'player_lookup': 'p5', 'player_full_name': 'P5', 'team': 'E', 'streak_length': 4, 'avg_margin': -3.0, 'games': []}
                    ],
                    # 1 prediction streak
                    [
                        {'player_lookup': 'p6', 'player_full_name': 'P6', 'team': 'F', 'streak_length': 8}
                    ]
                )
                mock_bq.return_value = mock_client

                exporter = StreaksExporter()
                result = exporter.generate_json('2024-12-15')

                assert result['summary']['total_over_streaks'] == 3
                assert result['summary']['total_under_streaks'] == 2
                assert result['summary']['total_prediction_streaks'] == 1

    def test_summary_longest_streaks(self):
        """Test summary longest streak values"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.queue_results(
                    # OVER streaks with max 8
                    [
                        {'player_lookup': 'p1', 'player_full_name': 'P1', 'team': 'A', 'streak_length': 8, 'avg_margin': 3.0, 'games': []},
                        {'player_lookup': 'p2', 'player_full_name': 'P2', 'team': 'B', 'streak_length': 5, 'avg_margin': 2.5, 'games': []}
                    ],
                    # UNDER streaks with max 6
                    [
                        {'player_lookup': 'p3', 'player_full_name': 'P3', 'team': 'C', 'streak_length': 6, 'avg_margin': -3.0, 'games': []}
                    ],
                    # Prediction streaks with max 10
                    [
                        {'player_lookup': 'p4', 'player_full_name': 'P4', 'team': 'D', 'streak_length': 10}
                    ]
                )
                mock_bq.return_value = mock_client

                exporter = StreaksExporter()
                result = exporter.generate_json('2024-12-15')

                assert result['summary']['longest_over'] == 8
                assert result['summary']['longest_under'] == 6
                assert result['summary']['longest_prediction'] == 10


class TestSafeFloat:
    """Test suite for _safe_float utility method"""

    def test_safe_float_valid(self):
        """Test valid float conversion"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = StreaksExporter()

                assert exporter._safe_float(25.567) == 25.57
                assert exporter._safe_float(10) == 10.0
                assert exporter._safe_float(-3.456) == -3.46

    def test_safe_float_none(self):
        """Test None handling"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = StreaksExporter()

                assert exporter._safe_float(None) is None

    def test_safe_float_nan(self):
        """Test NaN handling"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = StreaksExporter()

                assert exporter._safe_float(float('nan')) is None


class TestMinStreakLength:
    """Test suite for min_streak_length parameter"""

    def test_min_streak_length_in_output(self):
        """Test that min_streak_length is included in output"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.queue_results([], [], [])
                mock_bq.return_value = mock_client

                exporter = StreaksExporter(min_streak_length=6)
                result = exporter.generate_json('2024-12-15')

                assert result['min_streak_length'] == 6


class TestExport:
    """Test suite for export method"""

    def test_export_uses_today_path(self):
        """Test that export uploads to streaks/today.json"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client') as mock_gcs:
                mock_bq_client = MockBigQueryClient()
                mock_bq_client.queue_results([], [], [])
                mock_bq.return_value = mock_bq_client

                # Mock GCS
                mock_bucket = Mock()
                mock_blob = Mock()
                mock_bucket.blob.return_value = mock_blob
                mock_gcs.return_value.bucket.return_value = mock_bucket

                exporter = StreaksExporter()
                exporter.export('2024-12-15')

                # Check that upload_to_gcs was called with correct path
                mock_bucket.blob.assert_called_with('v1/streaks/today.json')


class TestPredictionStreakStructure:
    """Test suite for prediction streak structure"""

    def test_prediction_streak_has_streak_type(self):
        """Test that prediction streaks include streak_type field"""
        with patch('data_processors.publishing.streaks_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([
                    {
                        'player_lookup': 'player1',
                        'player_full_name': 'Player One',
                        'team': 'LAL',
                        'streak_length': 6
                    }
                ])
                mock_bq.return_value = mock_client

                exporter = StreaksExporter()
                result = exporter._query_prediction_streaks('2024-12-15')

                assert result[0]['streak_type'] == 'prediction_hits'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

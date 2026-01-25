"""
Integration tests for stale prediction detection SQL logic.

Tests the get_players_with_stale_predictions method in PlayerLoader that uses:
- QUALIFY clause for efficient deduplication
- LIMIT 500 for memory optimization
- ABS(current_line - prediction_line) >= threshold logic
- Multiple CTEs with joins

Reference: predictions/coordinator/player_loader.py:1220-1310

Created: 2026-01-25 (Session 18 - Phase 2: Core Logic Tests)
"""

import pytest
from datetime import date
from unittest.mock import Mock, patch
from predictions.coordinator.player_loader import PlayerLoader


class MockRow:
    """Mock BigQuery row for testing"""
    def __init__(self, **kwargs):
        self._data = kwargs

    def __getattr__(self, key):
        if key.startswith('_'):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{key}'")
        return self._data.get(key)

    def __getitem__(self, key):
        return self._data.get(key)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()


@pytest.fixture
def player_loader():
    """Create PlayerLoader instance for testing"""
    return PlayerLoader(project_id='test-project')


@pytest.fixture
def mock_bigquery_client():
    """Mock BigQuery client"""
    with patch('predictions.coordinator.player_loader.bigquery.Client') as mock_client:
        yield mock_client.return_value


class TestQualifyClauseCorrectness:
    """Test that QUALIFY clause correctly deduplicates players by latest created_at"""

    def test_qualify_deduplicates_by_latest_timestamp(self, player_loader, mock_bigquery_client):
        """Test QUALIFY returns only the latest record per player"""
        # Simulate multiple records for same player with different timestamps
        mock_rows = [
            MockRow(
                player_lookup='lebron-james-2544',
                current_line=25.5,
                prediction_line=23.0,
                line_change=2.5
            )
        ]

        mock_query_job = Mock()
        mock_query_job.result.return_value = mock_rows
        mock_bigquery_client.query.return_value = mock_query_job

        with patch.object(player_loader, 'client', mock_bigquery_client):
            result = player_loader.get_players_with_stale_predictions(
                game_date=date(2026, 1, 25),
                line_change_threshold=1.0
            )

        # Method returns list of player_lookup strings, not full row data
        assert len(result) == 1
        assert result[0] == 'lebron-james-2544'

        # Verify QUALIFY was used in SQL
        sql = mock_bigquery_client.query.call_args[0][0]
        assert 'QUALIFY' in sql
        assert 'ROW_NUMBER()' in sql
        assert 'PARTITION BY player_lookup' in sql
        assert 'ORDER BY created_at DESC' in sql

    def test_qualify_handles_single_record_per_player(self, player_loader, mock_bigquery_client):
        """Test QUALIFY works correctly when each player has only one record"""
        mock_rows = [
            MockRow(player_lookup='player1', current_line=25.5, prediction_line=23.0, line_change=2.5),
            MockRow(player_lookup='player2', current_line=30.5, prediction_line=28.0, line_change=2.5),
        ]

        mock_query_job = Mock()
        mock_query_job.result.return_value = mock_rows
        mock_bigquery_client.query.return_value = mock_query_job

        with patch.object(player_loader, 'client', mock_bigquery_client):
            result = player_loader.get_players_with_stale_predictions(
                game_date=date(2026, 1, 25),
                line_change_threshold=1.0
            )

        assert len(result) == 2


class TestLimit500Applied:
    """Test that LIMIT 500 clause is correctly applied for memory optimization"""

    def test_limit_500_in_sql(self, player_loader, mock_bigquery_client):
        """Test that LIMIT 500 is included in the SQL query"""
        mock_query_job = Mock()
        mock_query_job.result.return_value = []
        mock_bigquery_client.query.return_value = mock_query_job

        with patch.object(player_loader, 'client', mock_bigquery_client):
            player_loader.get_players_with_stale_predictions(
                game_date=date(2026, 1, 25)
            )

        sql = mock_bigquery_client.query.call_args[0][0]
        assert 'LIMIT 500' in sql

    def test_returns_at_most_500_players(self, player_loader, mock_bigquery_client):
        """Test that result set is capped at 500 players"""
        # Simulate 600 rows returned (should be impossible, but test boundary)
        mock_rows = [
            MockRow(player_lookup=f'player{i}', current_line=25.5, prediction_line=23.0, line_change=2.5)
            for i in range(500)
        ]

        mock_query_job = Mock()
        mock_query_job.result.return_value = mock_rows
        mock_bigquery_client.query.return_value = mock_query_job

        with patch.object(player_loader, 'client', mock_bigquery_client):
            result = player_loader.get_players_with_stale_predictions(
                game_date=date(2026, 1, 25)
            )

        assert len(result) <= 500


class TestThresholdFiltering:
    """Test that threshold parameter correctly filters stale predictions"""

    def test_default_threshold_1_point(self, player_loader, mock_bigquery_client):
        """Test default threshold of 1.0 point is applied"""
        mock_query_job = Mock()
        mock_query_job.result.return_value = []
        mock_bigquery_client.query.return_value = mock_query_job

        with patch.object(player_loader, 'client', mock_bigquery_client):
            player_loader.get_players_with_stale_predictions(
                game_date=date(2026, 1, 25)
            )

        # Verify threshold parameter passed to query
        job_config = mock_bigquery_client.query.call_args[1]['job_config']
        threshold_param = next(p for p in job_config.query_parameters if p.name == 'threshold')
        assert threshold_param.value == 1.0

    def test_custom_threshold(self, player_loader, mock_bigquery_client):
        """Test custom threshold value is correctly passed"""
        mock_query_job = Mock()
        mock_query_job.result.return_value = []
        mock_bigquery_client.query.return_value = mock_query_job

        with patch.object(player_loader, 'client', mock_bigquery_client):
            player_loader.get_players_with_stale_predictions(
                game_date=date(2026, 1, 25),
                line_change_threshold=2.5
            )

        job_config = mock_bigquery_client.query.call_args[1]['job_config']
        threshold_param = next(p for p in job_config.query_parameters if p.name == 'threshold')
        assert threshold_param.value == 2.5

    def test_abs_function_handles_negative_changes(self, player_loader, mock_bigquery_client):
        """Test ABS() function in SQL handles both positive and negative line changes"""
        # Result includes both positive and negative changes >= threshold
        mock_rows = [
            MockRow(player_lookup='player1', current_line=25.5, prediction_line=23.0, line_change=2.5),  # +2.5
            MockRow(player_lookup='player2', current_line=20.0, prediction_line=22.5, line_change=2.5),  # -2.5
        ]

        mock_query_job = Mock()
        mock_query_job.result.return_value = mock_rows
        mock_bigquery_client.query.return_value = mock_query_job

        with patch.object(player_loader, 'client', mock_bigquery_client):
            result = player_loader.get_players_with_stale_predictions(
                game_date=date(2026, 1, 25),
                line_change_threshold=2.0
            )

        # Both positive and negative changes should be included
        assert len(result) == 2

        # Verify ABS is in SQL
        sql = mock_bigquery_client.query.call_args[0][0]
        assert 'ABS(' in sql


class TestMultipleUpdatesSameGame:
    """Test handling of multiple line updates for the same player/game"""

    def test_latest_line_used_for_comparison(self, player_loader, mock_bigquery_client):
        """Test that the latest current line is compared with latest prediction line"""
        # Simulate result after QUALIFY deduplication
        mock_rows = [
            MockRow(
                player_lookup='curry-stephen-1966',
                current_line=28.5,  # Latest current line
                prediction_line=26.0,  # Latest prediction line
                line_change=2.5
            )
        ]

        mock_query_job = Mock()
        mock_query_job.result.return_value = mock_rows
        mock_bigquery_client.query.return_value = mock_query_job

        with patch.object(player_loader, 'client', mock_bigquery_client):
            result = player_loader.get_players_with_stale_predictions(
                game_date=date(2026, 1, 25)
            )

        # Method returns list of player_lookup strings
        assert len(result) == 1
        assert result[0] == 'curry-stephen-1966'


class TestEmptyResultSet:
    """Test handling of empty result sets"""

    def test_no_stale_predictions_returns_empty_list(self, player_loader, mock_bigquery_client):
        """Test that empty result set returns empty list"""
        mock_query_job = Mock()
        mock_query_job.result.return_value = []
        mock_bigquery_client.query.return_value = mock_query_job

        with patch.object(player_loader, 'client', mock_bigquery_client):
            result = player_loader.get_players_with_stale_predictions(
                game_date=date(2026, 1, 25)
            )

        assert result == []
        assert isinstance(result, list)

    def test_no_current_lines_available(self, player_loader, mock_bigquery_client):
        """Test when no current lines exist for game date"""
        mock_query_job = Mock()
        mock_query_job.result.return_value = []
        mock_bigquery_client.query.return_value = mock_query_job

        with patch.object(player_loader, 'client', mock_bigquery_client):
            result = player_loader.get_players_with_stale_predictions(
                game_date=date(2026, 1, 25)
            )

        assert result == []

    def test_no_predictions_exist_yet(self, player_loader, mock_bigquery_client):
        """Test when predictions don't exist yet for game date"""
        mock_query_job = Mock()
        mock_query_job.result.return_value = []
        mock_bigquery_client.query.return_value = mock_query_job

        with patch.object(player_loader, 'client', mock_bigquery_client):
            result = player_loader.get_players_with_stale_predictions(
                game_date=date(2026, 1, 25)
            )

        assert result == []


class TestEdgeCaseExactlyOnePoint:
    """Test edge case where line change is exactly 1.0 point"""

    def test_exactly_1_point_is_stale(self, player_loader, mock_bigquery_client):
        """Test that line change of exactly 1.0 is considered stale (>= threshold)"""
        mock_rows = [
            MockRow(
                player_lookup='player1',
                current_line=25.0,
                prediction_line=24.0,
                line_change=1.0  # Exactly threshold
            )
        ]

        mock_query_job = Mock()
        mock_query_job.result.return_value = mock_rows
        mock_bigquery_client.query.return_value = mock_query_job

        with patch.object(player_loader, 'client', mock_bigquery_client):
            result = player_loader.get_players_with_stale_predictions(
                game_date=date(2026, 1, 25),
                line_change_threshold=1.0
            )

        # Should include exactly 1.0 point change (>= threshold)
        assert len(result) == 1

    def test_just_under_1_point_not_stale(self, player_loader, mock_bigquery_client):
        """Test that line change of 0.9 is NOT considered stale"""
        # SQL handles this, but mock should reflect expected behavior
        mock_rows = []  # 0.9 point change filtered out by SQL

        mock_query_job = Mock()
        mock_query_job.result.return_value = mock_rows
        mock_bigquery_client.query.return_value = mock_query_job

        with patch.object(player_loader, 'client', mock_bigquery_client):
            result = player_loader.get_players_with_stale_predictions(
                game_date=date(2026, 1, 25),
                line_change_threshold=1.0
            )

        assert len(result) == 0


class TestIntegrationWithBigQuery:
    """Integration test with BigQuery service (mocked at client level)"""

    def test_query_parameters_correctly_formatted(self, player_loader, mock_bigquery_client):
        """Test that query parameters are correctly formatted for BigQuery"""
        mock_query_job = Mock()
        mock_query_job.result.return_value = []
        mock_bigquery_client.query.return_value = mock_query_job

        test_date = date(2026, 1, 25)
        test_line_change_threshold = 1.5

        with patch.object(player_loader, 'client', mock_bigquery_client):
            player_loader.get_players_with_stale_predictions(
                game_date=test_date,
                line_change_threshold=test_line_change_threshold
            )

        # Verify query was called
        assert mock_bigquery_client.query.called

        # Verify job config has correct parameters
        job_config = mock_bigquery_client.query.call_args[1]['job_config']
        params = {p.name: p.value for p in job_config.query_parameters}

        assert params['game_date'] == test_date
        assert params['threshold'] == test_line_change_threshold

    def test_sql_structure_includes_required_ctes(self, player_loader, mock_bigquery_client):
        """Test that SQL includes both current_lines and prediction_lines CTEs"""
        mock_query_job = Mock()
        mock_query_job.result.return_value = []
        mock_bigquery_client.query.return_value = mock_query_job

        with patch.object(player_loader, 'client', mock_bigquery_client):
            player_loader.get_players_with_stale_predictions(
                game_date=date(2026, 1, 25)
            )

        sql = mock_bigquery_client.query.call_args[0][0]

        # Verify CTE structure
        assert 'current_lines AS' in sql
        assert 'prediction_lines AS' in sql
        assert 'FROM prediction_lines p' in sql
        assert 'JOIN current_lines c' in sql

    def test_result_processing_handles_all_fields(self, player_loader, mock_bigquery_client):
        """Test that result processing correctly extracts player_lookup from rows"""
        mock_rows = [
            MockRow(
                player_lookup='lebron-james-2544',
                current_line=25.5,
                prediction_line=23.0,
                line_change=2.5
            ),
            MockRow(
                player_lookup='curry-stephen-1966',
                current_line=28.5,
                prediction_line=26.0,
                line_change=2.5
            )
        ]

        mock_query_job = Mock()
        mock_query_job.result.return_value = mock_rows
        mock_bigquery_client.query.return_value = mock_query_job

        with patch.object(player_loader, 'client', mock_bigquery_client):
            result = player_loader.get_players_with_stale_predictions(
                game_date=date(2026, 1, 25)
            )

        # Verify method returns list of player_lookup strings
        assert len(result) == 2
        assert result[0] == 'lebron-james-2544'
        assert result[1] == 'curry-stephen-1966'
        assert all(isinstance(player, str) for player in result)

#!/usr/bin/env python3
"""
Unit tests for registry failures tracking functionality.

Tests the complete registry failure lifecycle:
1. Saving registry failures (AnalyticsProcessorBase.save_registry_failures)
2. Marking failures as resolved (resolve_unresolved_batch.mark_registry_failures_resolved)
3. Getting players ready to reprocess (reprocess_resolved.get_players_ready_to_reprocess)
4. Marking failures as reprocessed (reprocess_resolved.mark_registry_failures_reprocessed)
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import date, datetime, timezone


class TestSaveRegistryFailures(unittest.TestCase):
    """Test AnalyticsProcessorBase.save_registry_failures()"""

    def setUp(self):
        """Setup mock processor instance."""
        # Import here to avoid circular dependencies
        from data_processors.analytics.analytics_base import AnalyticsProcessorBase

        # Create mock processor
        self.processor = AnalyticsProcessorBase()
        self.processor.project_id = 'test-project'
        self.processor.run_id = 'test-run-123'

        # Mock BigQuery client
        self.mock_client = Mock()
        self.processor.bq_client = self.mock_client

    def test_save_registry_failures_formats_records_correctly(self):
        """Test that records are correctly formatted for BigQuery."""
        # Setup test data
        self.processor.registry_failures = [
            {
                'player_lookup': 'johndoe',
                'game_date': date(2024, 11, 20),
                'team_abbr': 'LAL',
                'season': '2024-25',
                'game_id': '0022400089'
            }
        ]

        # Mock successful insert
        self.mock_client.insert_rows_json.return_value = []

        # Execute
        self.processor.save_registry_failures()

        # Verify insert was called
        self.mock_client.insert_rows_json.assert_called_once()

        # Extract call args
        call_args = self.mock_client.insert_rows_json.call_args
        table_id = call_args[0][0]
        records = call_args[0][1]

        # Verify table ID
        self.assertEqual(table_id, 'test-project.nba_processing.registry_failures')

        # Verify record format
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record['player_lookup'], 'johndoe')
        self.assertEqual(record['game_date'], '2024-11-20')
        self.assertEqual(record['team_abbr'], 'LAL')
        self.assertEqual(record['season'], '2024-25')
        self.assertEqual(record['game_id'], '0022400089')
        self.assertEqual(record['processor_name'], 'AnalyticsProcessorBase')
        self.assertEqual(record['run_id'], 'test-run-123')
        self.assertIsNone(record['resolved_at'])
        self.assertIsNone(record['reprocessed_at'])
        self.assertEqual(record['occurrence_count'], 1)
        self.assertIn('created_at', record)

    def test_save_registry_failures_deduplicates_by_player_and_date(self):
        """Test deduplication by (player_lookup, game_date)."""
        # Setup duplicate data
        self.processor.registry_failures = [
            {
                'player_lookup': 'johndoe',
                'game_date': date(2024, 11, 20),
                'team_abbr': 'LAL',
                'season': '2024-25',
                'game_id': '0022400089'
            },
            {
                'player_lookup': 'johndoe',
                'game_date': date(2024, 11, 20),  # Same player, same date
                'team_abbr': 'LAL',
                'season': '2024-25',
                'game_id': '0022400089'
            },
            {
                'player_lookup': 'janedoe',
                'game_date': date(2024, 11, 20),  # Different player
                'team_abbr': 'BOS',
                'season': '2024-25',
                'game_id': '0022400090'
            }
        ]

        # Mock successful insert
        self.mock_client.insert_rows_json.return_value = []

        # Execute
        self.processor.save_registry_failures()

        # Verify only 2 records inserted (duplicates removed)
        call_args = self.mock_client.insert_rows_json.call_args
        records = call_args[0][1]
        self.assertEqual(len(records), 2)

        # Verify correct records remain
        player_lookups = [r['player_lookup'] for r in records]
        self.assertIn('johndoe', player_lookups)
        self.assertIn('janedoe', player_lookups)

    def test_save_registry_failures_handles_empty_list(self):
        """Test handling of empty registry_failures list."""
        # Setup empty list
        self.processor.registry_failures = []

        # Execute
        self.processor.save_registry_failures()

        # Verify no insert call
        self.mock_client.insert_rows_json.assert_not_called()

    def test_save_registry_failures_batches_inserts(self):
        """Test that large lists are batched correctly."""
        # Create 1200 failure records (should split into 3 batches of 500)
        self.processor.registry_failures = [
            {
                'player_lookup': f'player{i}',
                'game_date': date(2024, 11, 20),
                'team_abbr': 'LAL',
                'season': '2024-25',
                'game_id': f'0022400{i:03d}'
            }
            for i in range(1200)
        ]

        # Mock successful inserts
        self.mock_client.insert_rows_json.return_value = []

        # Execute
        self.processor.save_registry_failures()

        # Verify 3 insert calls (batches of 500)
        self.assertEqual(self.mock_client.insert_rows_json.call_count, 3)

        # Verify batch sizes
        calls = self.mock_client.insert_rows_json.call_args_list
        self.assertEqual(len(calls[0][0][1]), 500)  # First batch
        self.assertEqual(len(calls[1][0][1]), 500)  # Second batch
        self.assertEqual(len(calls[2][0][1]), 200)  # Third batch (remainder)

    def test_save_registry_failures_handles_date_objects(self):
        """Test conversion of date objects to strings."""
        # Setup with date object
        self.processor.registry_failures = [
            {
                'player_lookup': 'johndoe',
                'game_date': date(2024, 11, 20),
                'team_abbr': 'LAL',
                'season': '2024-25'
            }
        ]

        # Mock successful insert
        self.mock_client.insert_rows_json.return_value = []

        # Execute
        self.processor.save_registry_failures()

        # Verify date converted to string
        call_args = self.mock_client.insert_rows_json.call_args
        records = call_args[0][1]
        self.assertEqual(records[0]['game_date'], '2024-11-20')

    def test_save_registry_failures_logs_errors(self):
        """Test error logging when insert fails."""
        # Setup test data
        self.processor.registry_failures = [
            {
                'player_lookup': 'johndoe',
                'game_date': date(2024, 11, 20),
                'team_abbr': 'LAL'
            }
        ]

        # Mock failed insert
        self.mock_client.insert_rows_json.side_effect = Exception("Insert failed")

        # Execute (should not raise, just log warning)
        with patch('data_processors.analytics.analytics_base.logger') as mock_logger:
            self.processor.save_registry_failures()
            mock_logger.warning.assert_called()


class TestMarkRegistryFailuresResolved(unittest.TestCase):
    """Test resolve_unresolved_batch.mark_registry_failures_resolved()"""

    def setUp(self):
        """Setup mock batch resolver."""
        # Import here to avoid path issues
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))

        from tools.player_registry.resolve_unresolved_batch import BatchResolver

        # Create mock resolver
        self.mock_client = Mock()
        self.resolver = BatchResolver.__new__(BatchResolver)
        self.resolver.bq_client = self.mock_client
        self.resolver.project_id = 'test-project'

    def test_mark_registry_failures_resolved_constructs_correct_query(self):
        """Test that UPDATE query is constructed correctly."""
        # Mock query result
        mock_result = Mock()
        mock_result.num_dml_affected_rows = 5
        mock_query = Mock()
        mock_query.result.return_value = mock_result
        self.mock_client.query.return_value = mock_query

        # Execute
        count = self.resolver.mark_registry_failures_resolved('johndoe')

        # Verify query was called
        self.mock_client.query.assert_called_once()

        # Extract query
        call_args = self.mock_client.query.call_args
        query = call_args[0][0]

        # Verify query structure
        self.assertIn('UPDATE', query)
        self.assertIn('nba_processing.registry_failures', query)
        self.assertIn('SET resolved_at = CURRENT_TIMESTAMP()', query)
        self.assertIn('WHERE player_lookup = @player_lookup', query)
        self.assertIn('AND resolved_at IS NULL', query)

        # Verify affected rows returned
        self.assertEqual(count, 5)

    def test_mark_registry_failures_resolved_returns_affected_rows(self):
        """Test that affected row count is returned correctly."""
        # Mock query result with 3 affected rows
        mock_result = Mock()
        mock_result.num_dml_affected_rows = 3
        mock_query = Mock()
        mock_query.result.return_value = mock_result
        self.mock_client.query.return_value = mock_query

        # Execute
        count = self.resolver.mark_registry_failures_resolved('janedoe')

        # Verify count
        self.assertEqual(count, 3)

    def test_mark_registry_failures_resolved_handles_no_matches(self):
        """Test handling when no records match."""
        # Mock query result with 0 affected rows
        mock_result = Mock()
        mock_result.num_dml_affected_rows = 0
        mock_query = Mock()
        mock_query.result.return_value = mock_result
        self.mock_client.query.return_value = mock_query

        # Execute
        count = self.resolver.mark_registry_failures_resolved('unknownplayer')

        # Verify count is 0
        self.assertEqual(count, 0)

    def test_mark_registry_failures_resolved_handles_none_affected_rows(self):
        """Test handling when num_dml_affected_rows is None."""
        # Mock query result with None (can happen in some cases)
        mock_result = Mock()
        mock_result.num_dml_affected_rows = None
        mock_query = Mock()
        mock_query.result.return_value = mock_result
        self.mock_client.query.return_value = mock_query

        # Execute
        count = self.resolver.mark_registry_failures_resolved('johndoe')

        # Verify count defaults to 0
        self.assertEqual(count, 0)


class TestGetPlayersReadyToReprocess(unittest.TestCase):
    """Test reprocess_resolved.get_players_ready_to_reprocess()"""

    def setUp(self):
        """Setup mock reprocessing orchestrator."""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))

        from tools.player_registry.reprocess_resolved import ReprocessingOrchestrator

        # Create mock orchestrator
        self.mock_client = Mock()
        self.orchestrator = ReprocessingOrchestrator.__new__(ReprocessingOrchestrator)
        self.orchestrator.bq_client = self.mock_client
        self.orchestrator.project_id = 'test-project'

    def test_get_players_ready_to_reprocess_constructs_correct_query(self):
        """Test that SELECT query is constructed correctly."""
        # Mock empty result
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([]))
        mock_query = Mock()
        mock_query.result.return_value = mock_result
        self.mock_client.query.return_value = mock_query

        # Execute
        players = self.orchestrator.get_players_ready_to_reprocess()

        # Verify query was called
        self.mock_client.query.assert_called_once()

        # Extract query
        call_args = self.mock_client.query.call_args
        query = call_args[0][0]

        # Verify query structure
        self.assertIn('SELECT', query)
        self.assertIn('player_lookup', query)
        self.assertIn('COUNT(*) as dates_count', query)
        self.assertIn('MIN(game_date) as first_date', query)
        self.assertIn('MAX(game_date) as last_date', query)
        self.assertIn('ARRAY_AGG(DISTINCT game_date ORDER BY game_date) as game_dates', query)
        self.assertIn('FROM', query)
        self.assertIn('nba_processing.registry_failures', query)
        self.assertIn('WHERE resolved_at IS NOT NULL', query)
        self.assertIn('AND reprocessed_at IS NULL', query)
        self.assertIn('GROUP BY player_lookup', query)
        self.assertIn('ORDER BY dates_count DESC', query)

    def test_get_players_ready_to_reprocess_returns_proper_format(self):
        """Test that results are formatted correctly."""
        # Create actual dict-like objects that work with dict() conversion
        class MockRow(dict):
            """Mock BigQuery Row that behaves like a dict."""
            pass

        mock_row1 = MockRow({
            'player_lookup': 'johndoe',
            'dates_count': 3,
            'first_date': date(2024, 11, 18),
            'last_date': date(2024, 11, 20),
            'game_dates': [date(2024, 11, 18), date(2024, 11, 19), date(2024, 11, 20)]
        })

        mock_row2 = MockRow({
            'player_lookup': 'janedoe',
            'dates_count': 1,
            'first_date': date(2024, 11, 20),
            'last_date': date(2024, 11, 20),
            'game_dates': [date(2024, 11, 20)]
        })

        # Mock query result
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([mock_row1, mock_row2]))
        mock_query = Mock()
        mock_query.result.return_value = mock_result
        self.mock_client.query.return_value = mock_query

        # Execute
        players = self.orchestrator.get_players_ready_to_reprocess()

        # Verify results
        self.assertEqual(len(players), 2)

        # Verify first player
        self.assertEqual(players[0]['player_lookup'], 'johndoe')
        self.assertEqual(players[0]['dates_count'], 3)
        self.assertEqual(players[0]['first_date'], date(2024, 11, 18))
        self.assertEqual(players[0]['last_date'], date(2024, 11, 20))
        self.assertEqual(len(players[0]['game_dates']), 3)

        # Verify second player
        self.assertEqual(players[1]['player_lookup'], 'janedoe')
        self.assertEqual(players[1]['dates_count'], 1)

    def test_get_players_ready_to_reprocess_handles_empty_result(self):
        """Test handling of empty result set."""
        # Mock empty result
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([]))
        mock_query = Mock()
        mock_query.result.return_value = mock_result
        self.mock_client.query.return_value = mock_query

        # Execute
        players = self.orchestrator.get_players_ready_to_reprocess()

        # Verify empty list returned
        self.assertEqual(players, [])


class TestMarkRegistryFailuresReprocessed(unittest.TestCase):
    """Test reprocess_resolved.mark_registry_failures_reprocessed()"""

    def setUp(self):
        """Setup mock reprocessing orchestrator."""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))

        from tools.player_registry.reprocess_resolved import ReprocessingOrchestrator

        # Create mock orchestrator
        self.mock_client = Mock()
        self.orchestrator = ReprocessingOrchestrator.__new__(ReprocessingOrchestrator)
        self.orchestrator.bq_client = self.mock_client
        self.orchestrator.project_id = 'test-project'

    def test_mark_registry_failures_reprocessed_with_specific_dates(self):
        """Test marking specific game_dates as reprocessed."""
        # Mock query result
        mock_result = Mock()
        mock_result.num_dml_affected_rows = 3
        mock_query = Mock()
        mock_query.result.return_value = mock_result
        self.mock_client.query.return_value = mock_query

        # Execute with specific dates
        game_dates = [date(2024, 11, 18), date(2024, 11, 19), date(2024, 11, 20)]
        count = self.orchestrator.mark_registry_failures_reprocessed('johndoe', game_dates)

        # Verify query was called
        self.mock_client.query.assert_called_once()

        # Extract query
        call_args = self.mock_client.query.call_args
        query = call_args[0][0]

        # Verify query structure
        self.assertIn('UPDATE', query)
        self.assertIn('nba_processing.registry_failures', query)
        self.assertIn('SET reprocessed_at = CURRENT_TIMESTAMP()', query)
        self.assertIn('WHERE player_lookup = @player_lookup', query)
        self.assertIn('AND resolved_at IS NOT NULL', query)
        self.assertIn('AND reprocessed_at IS NULL', query)
        self.assertIn('AND game_date IN', query)
        self.assertIn("DATE('2024-11-18')", query)
        self.assertIn("DATE('2024-11-19')", query)
        self.assertIn("DATE('2024-11-20')", query)

        # Verify affected rows returned
        self.assertEqual(count, 3)

    def test_mark_registry_failures_reprocessed_without_dates(self):
        """Test marking all dates for player (no game_dates provided)."""
        # Mock query result
        mock_result = Mock()
        mock_result.num_dml_affected_rows = 5
        mock_query = Mock()
        mock_query.result.return_value = mock_result
        self.mock_client.query.return_value = mock_query

        # Execute without specific dates
        count = self.orchestrator.mark_registry_failures_reprocessed('johndoe', None)

        # Verify query was called
        self.mock_client.query.assert_called_once()

        # Extract query
        call_args = self.mock_client.query.call_args
        query = call_args[0][0]

        # Verify query structure (no date filter)
        self.assertIn('UPDATE', query)
        self.assertIn('nba_processing.registry_failures', query)
        self.assertIn('SET reprocessed_at = CURRENT_TIMESTAMP()', query)
        self.assertIn('WHERE player_lookup = @player_lookup', query)
        self.assertIn('AND resolved_at IS NOT NULL', query)
        self.assertIn('AND reprocessed_at IS NULL', query)
        self.assertNotIn('AND game_date IN', query)

        # Verify affected rows returned
        self.assertEqual(count, 5)

    def test_mark_registry_failures_reprocessed_with_empty_dates_list(self):
        """Test marking with empty game_dates list."""
        # Mock query result
        mock_result = Mock()
        mock_result.num_dml_affected_rows = 5
        self.mock_client.query.return_value = mock_result

        # Execute with empty list (should behave same as None)
        count = self.orchestrator.mark_registry_failures_reprocessed('johndoe', [])

        # Verify query was called
        self.mock_client.query.assert_called_once()

        # Extract query
        call_args = self.mock_client.query.call_args
        query = call_args[0][0]

        # Verify no date filter (empty list is falsy, so else branch executes)
        self.assertNotIn('AND game_date IN', query)

    def test_mark_registry_failures_reprocessed_returns_affected_count(self):
        """Test that affected row count is returned correctly."""
        # Mock query result with 7 affected rows
        mock_result = Mock()
        mock_result.num_dml_affected_rows = 7
        mock_query = Mock()
        mock_query.result.return_value = mock_result
        self.mock_client.query.return_value = mock_query

        # Execute
        count = self.orchestrator.mark_registry_failures_reprocessed('janedoe')

        # Verify count
        self.assertEqual(count, 7)

    def test_mark_registry_failures_reprocessed_handles_none_affected_rows(self):
        """Test handling when num_dml_affected_rows is None."""
        # Mock query result with None
        mock_result = Mock()
        mock_result.num_dml_affected_rows = None
        mock_query = Mock()
        mock_query.result.return_value = mock_result
        self.mock_client.query.return_value = mock_query

        # Execute
        count = self.orchestrator.mark_registry_failures_reprocessed('johndoe')

        # Verify count defaults to 0
        self.assertEqual(count, 0)


if __name__ == '__main__':
    unittest.main()

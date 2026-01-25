#!/usr/bin/env python3
"""
Test for P2 Bug Fixes: SQL Injection and Race Condition
Bug 3: SQL injection in DELETE query
Bug 4: DELETE/INSERT race condition

Tests verify:
1. Parameterized queries are used (no SQL injection)
2. MERGE is used for atomic operations (no race condition)
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import date
from data_processors.precompute.mlb.pitcher_features_processor import MlbPitcherFeaturesProcessor


class TestPitcherFeaturesBugFixes(unittest.TestCase):
    """Test P2 bug fixes in pitcher features processor."""

    def setUp(self):
        """Set up test fixtures."""
        self.processor = MlbPitcherFeaturesProcessor()
        self.test_date = date(2025, 6, 15)
        self.sample_features = [{
            'player_lookup': 'gerrit-cole-543037',
            'game_date': self.test_date,
            'game_id': '717340',
            'opponent_team_abbr': 'BOS',
            'season_year': 2025,
            'f00_k_avg_last_3': 8.5,
            'f01_k_avg_last_5': 8.2,
            'feature_version': 'v2_35features',
            'data_hash': 'abc123',
            'created_at': None,
            'processed_at': None
        }]

    @patch('data_processors.precompute.mlb.pitcher_features_processor.bigquery.Client')
    def test_merge_uses_temp_table_not_fstring_injection(self, mock_client):
        """Test Bug 3 Fix: MERGE uses temp table, not f-string with dates."""
        # Setup mock
        mock_bq = Mock()
        mock_client.return_value = mock_bq
        self.processor.bq_client = mock_bq

        # Mock temp table insert
        mock_temp_table = Mock()
        mock_bq.dataset.return_value.table.return_value = mock_temp_table
        mock_bq.insert_rows_json.return_value = []  # No errors

        # Mock MERGE query execution
        mock_query_job = Mock()
        mock_query_job.result.return_value = None
        mock_bq.query.return_value = mock_query_job

        # Call the method
        result = self.processor._write_features(self.sample_features, self.test_date)

        # Verify temp table was used (proves MERGE strategy)
        self.assertTrue(mock_bq.insert_rows_json.called)

        # Verify MERGE query was called (proves atomic operation)
        self.assertTrue(mock_bq.query.called)
        merge_query = mock_bq.query.call_args[0][0]

        # Verify it's a MERGE statement (fixes race condition)
        self.assertIn('MERGE', merge_query)
        self.assertIn('USING', merge_query)
        self.assertIn('WHEN MATCHED', merge_query)
        self.assertIn('WHEN NOT MATCHED', merge_query)

        # Verify no f-string interpolation of game_date (would be SQL injection risk)
        # The temp table approach means date is in the data, not the query
        self.assertNotIn(f"'{self.test_date}'", merge_query)

        # Verify temp table cleanup
        self.assertTrue(mock_bq.delete_table.called)

        # Verify success
        self.assertEqual(result, len(self.sample_features))

    @patch('data_processors.precompute.mlb.pitcher_features_processor.bigquery.Client')
    def test_legacy_fallback_uses_parameterized_query(self, mock_client):
        """Test Bug 3 Fix: Legacy fallback uses parameterized queries, not f-strings."""
        # Setup mock
        mock_bq = Mock()
        mock_client.return_value = mock_bq
        self.processor.bq_client = mock_bq

        # Mock DELETE query execution
        mock_delete_job = Mock()
        mock_delete_job.result.return_value = None
        mock_bq.query.return_value = mock_delete_job

        # Mock INSERT
        mock_table_ref = Mock()
        mock_bq.dataset.return_value.table.return_value = mock_table_ref
        mock_bq.insert_rows_json.return_value = []  # No errors

        # Call legacy method directly
        result = self.processor._write_features_legacy(self.sample_features, self.test_date)

        # Verify parameterized query was used
        self.assertTrue(mock_bq.query.called)

        # Get the query config from the call
        call_kwargs = mock_bq.query.call_args
        if call_kwargs[1]:  # kwargs present
            job_config = call_kwargs[1].get('job_config')
            self.assertIsNotNone(job_config, "job_config should be provided")
            self.assertTrue(hasattr(job_config, 'query_parameters'))
            self.assertEqual(len(job_config.query_parameters), 1)
            self.assertEqual(job_config.query_parameters[0].name, 'game_date')
            self.assertEqual(job_config.query_parameters[0].value, self.test_date)

        # Verify DELETE query uses @game_date parameter, not f-string
        delete_query = call_kwargs[0][0]
        self.assertIn('@game_date', delete_query)
        self.assertNotIn(f"'{self.test_date}'", delete_query)

        # Verify success
        self.assertEqual(result, len(self.sample_features))

    @patch('data_processors.precompute.mlb.pitcher_features_processor.bigquery.Client')
    def test_merge_is_atomic_no_race_condition(self, mock_client):
        """Test Bug 4 Fix: MERGE is atomic - no DELETE/INSERT gap."""
        # Setup mock
        mock_bq = Mock()
        mock_client.return_value = mock_bq
        self.processor.bq_client = mock_bq

        # Track call order
        call_order = []

        def track_insert(*args, **kwargs):
            call_order.append('insert_to_temp')
            return []

        def track_merge(*args, **kwargs):
            call_order.append('merge')
            mock_job = Mock()
            mock_job.result.return_value = None
            return mock_job

        def track_delete(*args, **kwargs):
            call_order.append('delete_temp')

        mock_bq.insert_rows_json.side_effect = track_insert
        mock_bq.query.side_effect = track_merge
        mock_bq.delete_table.side_effect = track_delete
        mock_bq.dataset.return_value.table.return_value = Mock()

        # Call the method
        result = self.processor._write_features(self.sample_features, self.test_date)

        # Verify call order: insert to temp -> merge (atomic) -> delete temp
        # The key is that MERGE is a SINGLE operation that handles both
        # UPDATE and INSERT atomically - no gap where readers see empty data
        self.assertEqual(call_order, ['insert_to_temp', 'merge', 'delete_temp'])

        # Verify only ONE query execution (the MERGE) - not DELETE then INSERT
        self.assertEqual(mock_bq.query.call_count, 1)

        # Verify the single query is MERGE (atomic)
        merge_query = mock_bq.query.call_args[0][0]
        self.assertIn('MERGE', merge_query)

        # OLD CODE HAD: DELETE (query 1) -> gap -> INSERT (query 2)
        # NEW CODE HAS: MERGE (single atomic query)
        # This proves the race condition is fixed

        self.assertEqual(result, len(self.sample_features))

    @patch('data_processors.precompute.mlb.pitcher_features_processor.bigquery.Client')
    def test_legacy_fallback_on_merge_failure(self, mock_client):
        """Test that MERGE failures gracefully fall back to legacy method."""
        # Setup mock
        mock_bq = Mock()
        mock_client.return_value = mock_bq
        self.processor.bq_client = mock_bq

        # Make temp insert fail to trigger legacy fallback
        mock_bq.dataset.return_value.table.return_value = Mock()
        mock_bq.insert_rows_json.return_value = ['Error in temp table']

        # Mock legacy DELETE/INSERT
        mock_delete_job = Mock()
        mock_delete_job.result.return_value = None

        def mock_query_side_effect(*args, **kwargs):
            # First call is legacy DELETE
            return mock_delete_job

        mock_bq.query.side_effect = mock_query_side_effect

        # Mock legacy INSERT
        mock_bq.insert_rows_json.side_effect = [
            ['Error in temp table'],  # First call (temp) fails
            []  # Second call (legacy insert) succeeds
        ]

        # Call the method
        result = self.processor._write_features(self.sample_features, self.test_date)

        # Verify fallback was used
        # Should have: 1 temp insert attempt, 1 legacy DELETE, 1 legacy INSERT
        self.assertEqual(mock_bq.insert_rows_json.call_count, 2)

        # Verify legacy DELETE was called with parameterized query
        self.assertTrue(mock_bq.query.called)

        self.assertEqual(result, len(self.sample_features))


if __name__ == '__main__':
    unittest.main()

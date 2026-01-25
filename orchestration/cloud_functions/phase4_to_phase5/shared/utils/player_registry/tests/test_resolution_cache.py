#!/usr/bin/env python3
"""
Unit tests for ResolutionCache class.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
import json
from datetime import datetime

from shared.utils.player_registry.ai_resolver import AIResolution
from shared.utils.player_registry.resolution_cache import ResolutionCache


class TestResolutionCacheInit(unittest.TestCase):
    """Test ResolutionCache initialization."""

    @patch('shared.utils.player_registry.resolution_cache.bigquery.Client')
    def test_init_default_project(self, mock_client_class):
        """Test initialization with default project."""
        mock_client = Mock()
        mock_client.get_table.return_value = Mock()  # Table exists
        mock_client_class.return_value = mock_client

        cache = ResolutionCache()

        self.assertEqual(cache.project_id, 'nba-props-platform')
        self.assertIn('ai_resolution_cache', cache.table_id)

    @patch('shared.utils.player_registry.resolution_cache.bigquery.Client')
    def test_init_creates_table_if_missing(self, mock_client_class):
        """Test that table is created if it doesn't exist."""
        mock_client = Mock()
        mock_client.get_table.side_effect = Exception('Not found')
        mock_client_class.return_value = mock_client

        with patch('shared.utils.player_registry.resolution_cache.bigquery.Table') as mock_table:
            cache = ResolutionCache()

            mock_client.create_table.assert_called_once()


class TestResolutionCacheGet(unittest.TestCase):
    """Test cache retrieval methods."""

    def setUp(self):
        """Set up cache with mocked client."""
        self.mock_client = Mock()
        self.mock_client.get_table.return_value = Mock()

        with patch('shared.utils.player_registry.resolution_cache.bigquery.Client',
                   return_value=self.mock_client):
            self.cache = ResolutionCache()

    def test_get_cached_found(self):
        """Test getting cached resolution."""
        mock_row = Mock()
        mock_row.unresolved_lookup = 'marcusmorris'
        mock_row.resolution_type = 'MATCH'
        mock_row.resolved_to = 'marcusmorrissr'
        mock_row.confidence = 0.98
        mock_row.reasoning = 'Missing Sr. suffix'
        mock_row.ai_model = 'claude-3-haiku-20240307'
        mock_row.api_call_id = 'msg_123'

        mock_query_result = Mock()
        mock_query_result.result.return_value = [mock_row]
        self.mock_client.query.return_value = mock_query_result

        result = self.cache.get_cached('marcusmorris')

        self.assertIsNotNone(result)
        self.assertEqual(result.unresolved_lookup, 'marcusmorris')
        self.assertEqual(result.resolution_type, 'MATCH')
        self.assertEqual(result.canonical_lookup, 'marcusmorrissr')

    def test_get_cached_not_found(self):
        """Test getting non-existent cached resolution."""
        mock_query_result = Mock()
        mock_query_result.result.return_value = []
        self.mock_client.query.return_value = mock_query_result

        result = self.cache.get_cached('nonexistent')

        self.assertIsNone(result)

    def test_get_cached_increments_usage(self):
        """Test that cache hit increments usage count."""
        mock_row = Mock()
        mock_row.unresolved_lookup = 'test'
        mock_row.resolution_type = 'MATCH'
        mock_row.resolved_to = 'testsr'
        mock_row.confidence = 0.9
        mock_row.reasoning = 'Test'
        mock_row.ai_model = 'claude-3-haiku-20240307'
        mock_row.api_call_id = 'msg_123'

        mock_query_result = Mock()
        mock_query_result.result.return_value = [mock_row]
        self.mock_client.query.return_value = mock_query_result

        result = self.cache.get_cached('test')

        # Should be at least 2 queries: SELECT and UPDATE (increment)
        self.assertGreaterEqual(self.mock_client.query.call_count, 1)

    def test_get_cached_handles_error(self):
        """Test that errors return None."""
        self.mock_client.query.side_effect = Exception('Query failed')

        result = self.cache.get_cached('test')

        self.assertIsNone(result)


class TestResolutionCacheStore(unittest.TestCase):
    """Test cache storage methods."""

    def setUp(self):
        """Set up cache with mocked client."""
        self.mock_client = Mock()
        self.mock_client.get_table.return_value = Mock()

        with patch('shared.utils.player_registry.resolution_cache.bigquery.Client',
                   return_value=self.mock_client):
            self.cache = ResolutionCache()

    def test_cache_resolution_success(self):
        """Test successful caching."""
        self.mock_client.insert_rows_json.return_value = []

        resolution = AIResolution(
            unresolved_lookup='marcusmorris',
            resolution_type='MATCH',
            canonical_lookup='marcusmorrissr',
            confidence=0.98,
            reasoning='Missing Sr. suffix',
            ai_model='claude-3-haiku-20240307',
            api_call_id='msg_123',
            input_tokens=100,
            output_tokens=50
        )

        context = {
            'team_abbr': 'LAC',
            'season': '2021-22',
            'candidates': ['marcusmorrissr', 'marcusmorrisjr']
        }

        result = self.cache.cache_resolution(resolution, context)

        self.assertTrue(result)
        self.mock_client.insert_rows_json.assert_called_once()

        # Verify the row content
        call_args = self.mock_client.insert_rows_json.call_args
        row = call_args[0][1][0]
        self.assertEqual(row['unresolved_lookup'], 'marcusmorris')
        self.assertEqual(row['resolved_to'], 'marcusmorrissr')
        self.assertEqual(row['team_abbr'], 'LAC')

    def test_cache_resolution_insert_error(self):
        """Test caching with insert error."""
        self.mock_client.insert_rows_json.return_value = [{'errors': ['test']}]

        resolution = AIResolution(
            unresolved_lookup='test',
            resolution_type='MATCH',
            canonical_lookup='testsr',
            confidence=0.9,
            reasoning='Test',
            ai_model='claude-3-haiku-20240307',
            api_call_id='msg_123',
            input_tokens=100,
            output_tokens=50
        )

        result = self.cache.cache_resolution(resolution, {})

        self.assertFalse(result)

    def test_cache_resolution_handles_exception(self):
        """Test caching handles exceptions."""
        self.mock_client.insert_rows_json.side_effect = Exception('Insert failed')

        resolution = AIResolution(
            unresolved_lookup='test',
            resolution_type='MATCH',
            canonical_lookup='testsr',
            confidence=0.9,
            reasoning='Test',
            ai_model='claude-3-haiku-20240307',
            api_call_id='msg_123',
            input_tokens=100,
            output_tokens=50
        )

        result = self.cache.cache_resolution(resolution, {})

        self.assertFalse(result)


class TestResolutionCacheCostCalculation(unittest.TestCase):
    """Test cost calculation methods."""

    def setUp(self):
        """Set up cache with mocked client."""
        self.mock_client = Mock()
        self.mock_client.get_table.return_value = Mock()

        with patch('shared.utils.player_registry.resolution_cache.bigquery.Client',
                   return_value=self.mock_client):
            self.cache = ResolutionCache()

    def test_calculate_cost(self):
        """Test cost calculation."""
        resolution = AIResolution(
            unresolved_lookup='test',
            resolution_type='MATCH',
            canonical_lookup='testsr',
            confidence=0.9,
            reasoning='Test',
            ai_model='claude-3-haiku-20240307',
            api_call_id='msg_123',
            input_tokens=1000,  # $0.25 / 1M = $0.00025
            output_tokens=100   # $1.25 / 1M = $0.000125
        )

        cost = self.cache._calculate_cost(resolution)

        # Expected: (1000 * 0.25/1M) + (100 * 1.25/1M) = 0.00025 + 0.000125 = 0.000375
        self.assertAlmostEqual(cost, 0.000375, places=6)

    def test_calculate_cost_zero_tokens(self):
        """Test cost calculation with zero tokens."""
        resolution = AIResolution(
            unresolved_lookup='test',
            resolution_type='MATCH',
            canonical_lookup='testsr',
            confidence=0.9,
            reasoning='Test',
            ai_model='claude-3-haiku-20240307',
            api_call_id='msg_123',
            input_tokens=0,
            output_tokens=0
        )

        cost = self.cache._calculate_cost(resolution)

        self.assertEqual(cost, 0.0)


class TestResolutionCacheStats(unittest.TestCase):
    """Test cache statistics methods."""

    def setUp(self):
        """Set up cache with mocked client."""
        self.mock_client = Mock()
        self.mock_client.get_table.return_value = Mock()

        with patch('shared.utils.player_registry.resolution_cache.bigquery.Client',
                   return_value=self.mock_client):
            self.cache = ResolutionCache()

    def test_get_stats(self):
        """Test getting cache statistics."""
        mock_row = Mock()
        mock_row.total_entries = 100
        mock_row.total_cache_hits = 500
        mock_row.avg_confidence = 0.92
        mock_row.total_cost = 0.05
        mock_row.matches = 80
        mock_row.new_players = 15
        mock_row.data_errors = 5

        mock_query_result = Mock()
        mock_query_result.result.return_value = [mock_row]
        self.mock_client.query.return_value = mock_query_result

        result = self.cache.get_stats()

        self.assertEqual(result['total_entries'], 100)
        self.assertEqual(result['total_cache_hits'], 500)
        self.assertAlmostEqual(result['avg_confidence'], 0.92)
        self.assertEqual(result['by_type']['MATCH'], 80)

    def test_get_stats_empty_cache(self):
        """Test stats with empty cache."""
        mock_row = Mock()
        mock_row.total_entries = None
        mock_row.total_cache_hits = None
        mock_row.avg_confidence = None
        mock_row.total_cost = None
        mock_row.matches = None
        mock_row.new_players = None
        mock_row.data_errors = None

        mock_query_result = Mock()
        mock_query_result.result.return_value = [mock_row]
        self.mock_client.query.return_value = mock_query_result

        result = self.cache.get_stats()

        self.assertEqual(result['total_entries'], 0)
        self.assertEqual(result['total_cache_hits'], 0)

    def test_get_stats_handles_error(self):
        """Test stats error handling."""
        self.mock_client.query.side_effect = Exception('Query failed')

        result = self.cache.get_stats()

        self.assertEqual(result, {})


class TestResolutionCacheClear(unittest.TestCase):
    """Test cache clearing methods."""

    def setUp(self):
        """Set up cache with mocked client."""
        self.mock_client = Mock()
        self.mock_client.get_table.return_value = Mock()

        with patch('shared.utils.player_registry.resolution_cache.bigquery.Client',
                   return_value=self.mock_client):
            self.cache = ResolutionCache()

    def test_clear_cache_all(self):
        """Test clearing all cache entries."""
        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.num_dml_affected_rows = 50
        self.mock_client.query.return_value = mock_job

        result = self.cache.clear_cache()

        self.assertEqual(result, 50)
        # Verify no date filter
        call_args = self.mock_client.query.call_args
        query = call_args[0][0]
        self.assertIn('DELETE', query)
        self.assertIn('WHERE TRUE', query)

    def test_clear_cache_before_date(self):
        """Test clearing cache entries before date."""
        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.num_dml_affected_rows = 25
        self.mock_client.query.return_value = mock_job

        result = self.cache.clear_cache(before_date='2024-01-01')

        self.assertEqual(result, 25)
        # Verify date filter in query
        call_args = self.mock_client.query.call_args
        query = call_args[0][0]
        self.assertIn('before_date', query)

    def test_clear_cache_handles_error(self):
        """Test clear cache error handling."""
        self.mock_client.query.side_effect = Exception('Delete failed')

        result = self.cache.clear_cache()

        self.assertEqual(result, 0)


class TestResolutionCacheIncrementUsage(unittest.TestCase):
    """Test usage increment method."""

    def setUp(self):
        """Set up cache with mocked client."""
        self.mock_client = Mock()
        self.mock_client.get_table.return_value = Mock()

        with patch('shared.utils.player_registry.resolution_cache.bigquery.Client',
                   return_value=self.mock_client):
            self.cache = ResolutionCache()

    def test_increment_usage_success(self):
        """Test successful usage increment."""
        mock_job = Mock()
        mock_job.result.return_value = None
        self.mock_client.query.return_value = mock_job

        # Should not raise
        self.cache._increment_usage('test')

        # Verify UPDATE query was called
        call_args = self.mock_client.query.call_args
        query = call_args[0][0]
        self.assertIn('UPDATE', query)
        self.assertIn('used_count', query)

    def test_increment_usage_handles_error(self):
        """Test that increment errors don't raise."""
        self.mock_client.query.side_effect = Exception('Update failed')

        # Should not raise
        self.cache._increment_usage('test')


if __name__ == '__main__':
    unittest.main()

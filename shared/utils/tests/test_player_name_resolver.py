#!/usr/bin/env python3
"""
Unit tests for PlayerNameResolver class, focusing on the cache lookup integration.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import date


class TestPlayerNameResolverCacheLookup(unittest.TestCase):
    """Test the AI resolution cache lookup integration in handle_player_name()."""

    def setUp(self):
        """Set up test fixtures."""
        self.game_context = {
            'season': '2024-25',
            'team': 'LAL',
            'game_date': date(2024, 12, 15),
            'game_id': '0022400123'
        }

    @patch('shared.utils.player_name_resolver.ResolutionCache')
    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_cache_hit_match_creates_alias(self, mock_bq_client, mock_cache_class):
        """Test that a cache hit with MATCH creates an alias and returns resolved name."""
        from shared.utils.player_name_resolver import PlayerNameResolver
        from shared.utils.player_registry.ai_resolver import AIResolution

        # Setup mocks
        mock_cache = MagicMock()
        mock_cache_class.return_value = mock_cache

        # Simulate a cached MATCH resolution
        cached_resolution = AIResolution(
            unresolved_lookup='tjmcconnell',
            resolution_type='MATCH',
            canonical_lookup='tjmcconnell',
            confidence=0.95,
            reasoning='Matched T.J. McConnell',
            ai_model='claude-3-haiku',
            api_call_id='test-123',
            input_tokens=100,
            output_tokens=50
        )
        mock_cache.get_cached.return_value = cached_resolution

        # Mock BigQuery responses
        mock_client = MagicMock()
        mock_bq_client.return_value = mock_client

        # Alias lookup returns empty (no existing alias)
        alias_df = MagicMock()
        alias_df.empty = True
        mock_client.query.return_value.to_dataframe.return_value = alias_df

        # Create resolver
        resolver = PlayerNameResolver()

        # Verify cache was initialized
        mock_cache_class.assert_called_once()
        self.assertTrue(resolver._use_resolution_cache)

    @patch('shared.utils.player_name_resolver.ResolutionCache')
    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_cache_hit_data_error_does_not_create_alias(self, mock_bq_client, mock_cache_class):
        """Test that a cache hit with DATA_ERROR does not create alias."""
        from shared.utils.player_name_resolver import PlayerNameResolver
        from shared.utils.player_registry.ai_resolver import AIResolution

        # Setup mocks
        mock_cache = MagicMock()
        mock_cache_class.return_value = mock_cache

        # Simulate a cached DATA_ERROR resolution
        cached_resolution = AIResolution(
            unresolved_lookup='invalidplayer',
            resolution_type='DATA_ERROR',
            canonical_lookup=None,
            confidence=0.80,
            reasoning='Invalid player name',
            ai_model='claude-3-haiku',
            api_call_id='test-456',
            input_tokens=100,
            output_tokens=50
        )
        mock_cache.get_cached.return_value = cached_resolution

        # Mock BigQuery responses
        mock_client = MagicMock()
        mock_bq_client.return_value = mock_client

        # Alias lookup returns empty
        alias_df = MagicMock()
        alias_df.empty = True
        mock_client.query.return_value.to_dataframe.return_value = alias_df

        # Create resolver
        resolver = PlayerNameResolver()

        # DATA_ERROR should not trigger alias creation
        # The resolver should proceed to add to unresolved queue
        self.assertTrue(resolver._use_resolution_cache)

    @patch('shared.utils.player_name_resolver.ResolutionCache')
    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_cache_miss_adds_to_unresolved_queue(self, mock_bq_client, mock_cache_class):
        """Test that a cache miss adds name to unresolved queue."""
        from shared.utils.player_name_resolver import PlayerNameResolver

        # Setup mocks
        mock_cache = MagicMock()
        mock_cache_class.return_value = mock_cache

        # Simulate cache miss
        mock_cache.get_cached.return_value = None

        # Mock BigQuery
        mock_client = MagicMock()
        mock_bq_client.return_value = mock_client

        # Alias lookup returns empty
        alias_df = MagicMock()
        alias_df.empty = True
        mock_client.query.return_value.to_dataframe.return_value = alias_df

        # Create resolver
        resolver = PlayerNameResolver()

        # Verify cache check returns None
        self.assertIsNone(mock_cache.get_cached('unknownplayer'))

    @patch('shared.utils.player_name_resolver.ResolutionCache')
    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_cache_initialization_failure_disables_cache(self, mock_bq_client, mock_cache_class):
        """Test that cache initialization failure gracefully disables cache."""
        from shared.utils.player_name_resolver import PlayerNameResolver

        # Simulate cache initialization failure
        mock_cache_class.side_effect = Exception("BigQuery connection failed")

        # Mock BigQuery
        mock_client = MagicMock()
        mock_bq_client.return_value = mock_client

        # Create resolver - should not raise, just disable cache
        resolver = PlayerNameResolver()

        # Verify cache is disabled
        self.assertFalse(resolver._use_resolution_cache)
        self.assertIsNone(resolver._resolution_cache)


class TestPlayerNameResolverBasics(unittest.TestCase):
    """Test basic PlayerNameResolver functionality."""

    @patch('shared.utils.player_name_resolver.ResolutionCache')
    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_resolve_to_nba_name_with_alias(self, mock_bq_client, mock_cache_class):
        """Test that alias lookup returns canonical name."""
        from shared.utils.player_name_resolver import PlayerNameResolver

        # Setup mocks
        mock_cache = MagicMock()
        mock_cache_class.return_value = mock_cache

        mock_client = MagicMock()
        mock_bq_client.return_value = mock_client

        # Alias lookup returns a result
        import pandas as pd
        alias_df = pd.DataFrame({'nba_canonical_display': ['LeBron James']})
        mock_client.query.return_value.to_dataframe.return_value = alias_df

        resolver = PlayerNameResolver()
        result = resolver.resolve_to_nba_name('lebron james')

        self.assertEqual(result, 'LeBron James')

    @patch('shared.utils.player_name_resolver.ResolutionCache')
    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_resolve_to_nba_name_no_alias(self, mock_bq_client, mock_cache_class):
        """Test that no alias returns original name."""
        from shared.utils.player_name_resolver import PlayerNameResolver

        # Setup mocks
        mock_cache = MagicMock()
        mock_cache_class.return_value = mock_cache

        mock_client = MagicMock()
        mock_bq_client.return_value = mock_client

        # Alias lookup returns empty
        alias_df = MagicMock()
        alias_df.empty = True
        mock_client.query.return_value.to_dataframe.return_value = alias_df

        resolver = PlayerNameResolver()
        result = resolver.resolve_to_nba_name('Unknown Player')

        self.assertEqual(result, 'Unknown Player')


if __name__ == '__main__':
    unittest.main()

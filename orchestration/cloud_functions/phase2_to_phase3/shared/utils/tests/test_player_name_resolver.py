#!/usr/bin/env python3
"""
Unit tests for PlayerNameResolver class, focusing on the cache lookup integration
and the complete handle_player_name() flow.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import date
import pandas as pd


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
    def test_cache_hit_match_creates_alias_and_returns_name(self, mock_bq_client, mock_cache_class):
        """Test that a cache hit with MATCH creates an alias and returns resolved name."""
        from shared.utils.player_name_resolver import PlayerNameResolver
        from shared.utils.player_registry.ai_resolver import AIResolution

        # Setup cache mock
        mock_cache = MagicMock()
        mock_cache_class.return_value = mock_cache

        # Setup BigQuery mock
        mock_client = MagicMock()
        mock_bq_client.return_value = mock_client

        # Create resolver
        resolver = PlayerNameResolver()

        # Setup the cached MATCH resolution
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

        # Mock the internal methods
        resolver.resolve_to_nba_name = MagicMock(return_value='T.J. McConnell')
        resolver.is_valid_nba_player = MagicMock(return_value=False)  # Force cache lookup path
        resolver._get_canonical_display_name = MagicMock(return_value='T.J. McConnell')
        resolver.create_alias_mapping = MagicMock(return_value=True)
        resolver.add_to_unresolved_queue = MagicMock()

        # Call handle_player_name
        result = resolver.handle_player_name('T.J. McConnell', 'bdl', self.game_context)

        # Verify result
        self.assertEqual(result, 'T.J. McConnell')

        # Verify alias was created
        resolver.create_alias_mapping.assert_called_once()
        call_kwargs = resolver.create_alias_mapping.call_args
        self.assertEqual(call_kwargs[1]['alias_name'], 'T.J. McConnell')
        self.assertEqual(call_kwargs[1]['canonical_name'], 'T.J. McConnell')
        self.assertEqual(call_kwargs[1]['alias_type'], 'ai_resolved')
        self.assertEqual(call_kwargs[1]['created_by'], 'ai_cache_lookup')

        # Verify NOT added to unresolved queue
        resolver.add_to_unresolved_queue.assert_not_called()

    @patch('shared.utils.player_name_resolver.ResolutionCache')
    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_cache_hit_data_error_returns_none_without_queue_add(self, mock_bq_client, mock_cache_class):
        """Test that a cache hit with DATA_ERROR returns None without adding to unresolved queue."""
        from shared.utils.player_name_resolver import PlayerNameResolver
        from shared.utils.player_registry.ai_resolver import AIResolution

        # Setup cache mock
        mock_cache = MagicMock()
        mock_cache_class.return_value = mock_cache

        # Setup BigQuery mock
        mock_client = MagicMock()
        mock_bq_client.return_value = mock_client

        # Create resolver
        resolver = PlayerNameResolver()

        # Setup the cached DATA_ERROR resolution
        cached_resolution = AIResolution(
            unresolved_lookup='invalidplayer',
            resolution_type='DATA_ERROR',
            canonical_lookup=None,
            confidence=0.80,
            reasoning='Invalid player name - appears to be a data entry error',
            ai_model='claude-3-haiku',
            api_call_id='test-456',
            input_tokens=100,
            output_tokens=50
        )
        mock_cache.get_cached.return_value = cached_resolution

        # Mock the internal methods
        resolver.resolve_to_nba_name = MagicMock(return_value='invalidplayer')
        resolver.is_valid_nba_player = MagicMock(return_value=False)  # Force cache lookup path
        resolver.create_alias_mapping = MagicMock()
        resolver.add_to_unresolved_queue = MagicMock()

        # Call handle_player_name
        result = resolver.handle_player_name('invalidplayer', 'bdl', self.game_context)

        # Verify result is None
        self.assertIsNone(result)

        # Verify alias was NOT created
        resolver.create_alias_mapping.assert_not_called()

        # Verify NOT added to unresolved queue (this is the key test)
        resolver.add_to_unresolved_queue.assert_not_called()

    @patch('shared.utils.player_name_resolver.ResolutionCache')
    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_cache_miss_adds_to_unresolved_queue(self, mock_bq_client, mock_cache_class):
        """Test that a cache miss adds name to unresolved queue."""
        from shared.utils.player_name_resolver import PlayerNameResolver

        # Setup cache mock
        mock_cache = MagicMock()
        mock_cache_class.return_value = mock_cache

        # Simulate cache miss
        mock_cache.get_cached.return_value = None

        # Setup BigQuery mock
        mock_client = MagicMock()
        mock_bq_client.return_value = mock_client

        # Create resolver
        resolver = PlayerNameResolver()

        # Mock the internal methods
        resolver.resolve_to_nba_name = MagicMock(return_value='Unknown Player')
        resolver.is_valid_nba_player = MagicMock(return_value=False)  # Not in registry
        resolver.add_to_unresolved_queue = MagicMock()

        # Call handle_player_name
        result = resolver.handle_player_name('Unknown Player', 'espn', self.game_context)

        # Verify result is None
        self.assertIsNone(result)

        # Verify added to unresolved queue
        resolver.add_to_unresolved_queue.assert_called_once_with(
            source='espn',
            original_name='Unknown Player',
            game_context=self.game_context
        )

    @patch('shared.utils.player_name_resolver.ResolutionCache')
    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_alias_creation_failure_still_returns_resolved_name(self, mock_bq_client, mock_cache_class):
        """Test that alias creation failure still returns the resolved name from cache."""
        from shared.utils.player_name_resolver import PlayerNameResolver
        from shared.utils.player_registry.ai_resolver import AIResolution

        # Setup cache mock
        mock_cache = MagicMock()
        mock_cache_class.return_value = mock_cache

        # Setup BigQuery mock
        mock_client = MagicMock()
        mock_bq_client.return_value = mock_client

        # Create resolver
        resolver = PlayerNameResolver()

        # Setup the cached MATCH resolution
        cached_resolution = AIResolution(
            unresolved_lookup='kjmartin',
            resolution_type='MATCH',
            canonical_lookup='kjmartin',
            confidence=0.92,
            reasoning='Matched KJ Martin',
            ai_model='claude-3-haiku',
            api_call_id='test-789',
            input_tokens=100,
            output_tokens=50
        )
        mock_cache.get_cached.return_value = cached_resolution

        # Mock the internal methods
        resolver.resolve_to_nba_name = MagicMock(return_value='KJ Martin')
        resolver.is_valid_nba_player = MagicMock(return_value=False)  # Force cache lookup path
        resolver._get_canonical_display_name = MagicMock(return_value='KJ Martin')
        resolver.create_alias_mapping = MagicMock(return_value=False)  # Simulate failure!
        resolver.add_to_unresolved_queue = MagicMock()

        # Call handle_player_name
        result = resolver.handle_player_name('Kenyon Martin Jr.', 'bdl', self.game_context)

        # Verify result is still returned despite alias creation failure
        self.assertEqual(result, 'KJ Martin')

        # Verify alias creation was attempted
        resolver.create_alias_mapping.assert_called_once()

        # Verify NOT added to unresolved queue (we have a valid resolution)
        resolver.add_to_unresolved_queue.assert_not_called()

    @patch('shared.utils.player_name_resolver.ResolutionCache')
    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_cache_initialization_failure_disables_cache(self, mock_bq_client, mock_cache_class):
        """Test that cache initialization failure gracefully disables cache."""
        from shared.utils.player_name_resolver import PlayerNameResolver

        # Simulate cache initialization failure
        mock_cache_class.side_effect = Exception("BigQuery connection failed")

        # Setup BigQuery mock
        mock_client = MagicMock()
        mock_bq_client.return_value = mock_client

        # Create resolver - should not raise, just disable cache
        resolver = PlayerNameResolver()

        # Verify cache is disabled
        self.assertFalse(resolver._use_resolution_cache)
        self.assertIsNone(resolver._resolution_cache)

    @patch('shared.utils.player_name_resolver.ResolutionCache')
    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_new_player_resolution_type_falls_through_to_queue(self, mock_bq_client, mock_cache_class):
        """Test that NEW_PLAYER resolution type falls through to unresolved queue."""
        from shared.utils.player_name_resolver import PlayerNameResolver
        from shared.utils.player_registry.ai_resolver import AIResolution

        # Setup cache mock
        mock_cache = MagicMock()
        mock_cache_class.return_value = mock_cache

        # Setup BigQuery mock
        mock_client = MagicMock()
        mock_bq_client.return_value = mock_client

        # Create resolver
        resolver = PlayerNameResolver()

        # Setup the cached NEW_PLAYER resolution
        cached_resolution = AIResolution(
            unresolved_lookup='rookieplayer',
            resolution_type='NEW_PLAYER',
            canonical_lookup=None,
            confidence=0.85,
            reasoning='Appears to be a new rookie not yet in registry',
            ai_model='claude-3-haiku',
            api_call_id='test-new',
            input_tokens=100,
            output_tokens=50
        )
        mock_cache.get_cached.return_value = cached_resolution

        # Mock the internal methods
        resolver.resolve_to_nba_name = MagicMock(return_value='Rookie Player')
        resolver.is_valid_nba_player = MagicMock(return_value=False)
        resolver.add_to_unresolved_queue = MagicMock()

        # Call handle_player_name
        result = resolver.handle_player_name('Rookie Player', 'bdl', self.game_context)

        # Verify result is None
        self.assertIsNone(result)

        # Verify added to unresolved queue (NEW_PLAYER needs roster update)
        resolver.add_to_unresolved_queue.assert_called_once()

    @patch('shared.utils.player_name_resolver.ResolutionCache')
    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_valid_registry_player_returns_immediately(self, mock_bq_client, mock_cache_class):
        """Test that a player already in registry returns without cache lookup."""
        from shared.utils.player_name_resolver import PlayerNameResolver

        # Setup cache mock
        mock_cache = MagicMock()
        mock_cache_class.return_value = mock_cache

        # Setup BigQuery mock
        mock_client = MagicMock()
        mock_bq_client.return_value = mock_client

        # Create resolver
        resolver = PlayerNameResolver()

        # Mock the internal methods
        resolver.resolve_to_nba_name = MagicMock(return_value='LeBron James')
        resolver.is_valid_nba_player = MagicMock(return_value=True)  # Already valid!
        resolver.add_to_unresolved_queue = MagicMock()

        # Call handle_player_name
        result = resolver.handle_player_name('LeBron James', 'nba', self.game_context)

        # Verify result
        self.assertEqual(result, 'LeBron James')

        # Verify cache was NOT checked (short-circuit on registry validation)
        mock_cache.get_cached.assert_not_called()

        # Verify NOT added to unresolved queue
        resolver.add_to_unresolved_queue.assert_not_called()


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

    @patch('shared.utils.player_name_resolver.ResolutionCache')
    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_handle_player_name_with_empty_input(self, mock_bq_client, mock_cache_class):
        """Test that empty input returns None."""
        from shared.utils.player_name_resolver import PlayerNameResolver

        # Setup mocks
        mock_cache = MagicMock()
        mock_cache_class.return_value = mock_cache

        mock_client = MagicMock()
        mock_bq_client.return_value = mock_client

        resolver = PlayerNameResolver()

        # Test empty string
        result = resolver.handle_player_name('', 'bdl', {})
        self.assertIsNone(result)

        # Test None
        result = resolver.handle_player_name(None, 'bdl', {})
        self.assertIsNone(result)


class TestPlayerNameResolverCacheException(unittest.TestCase):
    """Test exception handling in cache lookup."""

    @patch('shared.utils.player_name_resolver.ResolutionCache')
    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_cache_lookup_exception_falls_through_to_queue(self, mock_bq_client, mock_cache_class):
        """Test that cache lookup exception falls through to unresolved queue."""
        from shared.utils.player_name_resolver import PlayerNameResolver

        # Setup cache mock
        mock_cache = MagicMock()
        mock_cache_class.return_value = mock_cache

        # Make cache lookup raise exception
        mock_cache.get_cached.side_effect = Exception("Cache query failed")

        # Setup BigQuery mock
        mock_client = MagicMock()
        mock_bq_client.return_value = mock_client

        # Create resolver
        resolver = PlayerNameResolver()

        # Mock the internal methods
        resolver.resolve_to_nba_name = MagicMock(return_value='Some Player')
        resolver.is_valid_nba_player = MagicMock(return_value=False)
        resolver.add_to_unresolved_queue = MagicMock()

        game_context = {
            'season': '2024-25',
            'team': 'LAL',
            'game_date': date(2024, 12, 15),
            'game_id': '0022400123'
        }

        # Call handle_player_name - should not raise
        result = resolver.handle_player_name('Some Player', 'bdl', game_context)

        # Verify result is None
        self.assertIsNone(result)

        # Verify added to unresolved queue (graceful fallback)
        resolver.add_to_unresolved_queue.assert_called_once()


if __name__ == '__main__':
    unittest.main()

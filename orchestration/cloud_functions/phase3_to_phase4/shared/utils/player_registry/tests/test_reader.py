#!/usr/bin/env python3
"""
File: shared/utils/player_registry/tests/test_reader.py

Unit tests for RegistryReader class.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime, date
import pandas as pd

from shared.utils.player_registry import (
    RegistryReader,
    PlayerNotFoundError,
    MultipleRecordsError,
    AmbiguousNameError,
    RegistryConnectionError
)


class TestRegistryReaderInit(unittest.TestCase):
    """Test RegistryReader initialization."""
    
    @patch('shared.utils.player_registry.reader.bigquery.Client')
    def test_init_creates_client(self, mock_client_class):
        """Test that RegistryReader creates BigQuery client if not provided."""
        mock_client = Mock()
        mock_client.project = 'test-project'
        mock_client_class.return_value = mock_client
        
        registry = RegistryReader(source_name='test_source')
        
        self.assertEqual(registry.source_name, 'test_source')
        self.assertEqual(registry.bq_client, mock_client)
        mock_client_class.assert_called_once()
    
    def test_init_uses_provided_client(self):
        """Test that RegistryReader uses provided BigQuery client."""
        mock_client = Mock()
        mock_client.project = 'test-project'
        
        registry = RegistryReader(
            bq_client=mock_client,
            source_name='test_source'
        )
        
        self.assertEqual(registry.bq_client, mock_client)
    
    def test_init_test_mode(self):
        """Test that test mode uses test tables."""
        mock_client = Mock()
        mock_client.project = 'test-project'
        
        registry = RegistryReader(
            bq_client=mock_client,
            source_name='test_source',
            test_mode=True
        )
        
        self.assertIn('test_FIXED2', registry.registry_table)
        self.assertIn('test_FIXED2', registry.unresolved_table)


class TestRegistryReaderContext(unittest.TestCase):
    """Test context management."""
    
    def setUp(self):
        mock_client = Mock()
        mock_client.project = 'test-project'
        self.registry = RegistryReader(
            bq_client=mock_client,
            source_name='test_source'
        )
    
    def test_set_default_context(self):
        """Test setting default context."""
        self.registry.set_default_context(season='2024-25', team_abbr='LAL')
        
        self.assertEqual(self.registry._default_context['season'], '2024-25')
        self.assertEqual(self.registry._default_context['team_abbr'], 'LAL')
    
    def test_merge_context(self):
        """Test merging default and call-specific context."""
        self.registry.set_default_context(season='2024-25')
        
        merged = self.registry._merge_context({'game_id': 'ABC123'})
        
        self.assertEqual(merged['season'], '2024-25')
        self.assertEqual(merged['game_id'], 'ABC123')
    
    def test_merge_context_override(self):
        """Test that call context overrides default."""
        self.registry.set_default_context(season='2023-24')
        
        merged = self.registry._merge_context({'season': '2024-25'})
        
        self.assertEqual(merged['season'], '2024-25')


class TestRegistryReaderCache(unittest.TestCase):
    """Test caching functionality."""
    
    def setUp(self):
        mock_client = Mock()
        mock_client.project = 'test-project'
        self.registry = RegistryReader(
            bq_client=mock_client,
            source_name='test_source',
            cache_ttl_seconds=60
        )
    
    def test_cache_put_and_get(self):
        """Test putting and getting from cache."""
        self.registry._put_in_cache('test_key', 'test_value')
        
        result = self.registry._get_from_cache('test_key')
        
        self.assertEqual(result, 'test_value')
        self.assertEqual(self.registry._cache_hits, 1)
    
    def test_cache_miss(self):
        """Test cache miss."""
        result = self.registry._get_from_cache('nonexistent_key')
        
        self.assertIsNone(result)
        self.assertEqual(self.registry._cache_misses, 1)
    
    def test_cache_disabled(self):
        """Test that cache is disabled when TTL is 0."""
        registry = RegistryReader(
            bq_client=Mock(),
            source_name='test_source',
            cache_ttl_seconds=0
        )
        
        registry._put_in_cache('key', 'value')
        result = registry._get_from_cache('key')
        
        self.assertIsNone(result)
    
    def test_clear_cache(self):
        """Test clearing entire cache."""
        self.registry._put_in_cache('key1', 'value1')
        self.registry._put_in_cache('key2', 'value2')
        
        self.registry.clear_cache()
        
        self.assertEqual(len(self.registry._cache), 0)
    
    def test_clear_cache_for_player(self):
        """Test clearing cache for specific player."""
        self.registry._put_in_cache('uid:lebronjames', 'id123')
        self.registry._put_in_cache('player:lebronjames:2024-25', {'name': 'LeBron'})
        self.registry._put_in_cache('uid:stephencurry', 'id456')
        
        self.registry.clear_cache_for_player('lebronjames')
        
        self.assertIsNone(self.registry._get_from_cache('uid:lebronjames'))
        self.assertIsNone(self.registry._get_from_cache('player:lebronjames:2024-25'))
        self.assertIsNotNone(self.registry._get_from_cache('uid:stephencurry'))
    
    def test_get_cache_stats(self):
        """Test cache statistics."""
        self.registry._put_in_cache('key', 'value')
        self.registry._get_from_cache('key')  # hit
        self.registry._get_from_cache('missing')  # miss
        
        stats = self.registry.get_cache_stats()
        
        self.assertEqual(stats['hits'], 1)
        self.assertEqual(stats['misses'], 1)
        self.assertEqual(stats['hit_rate'], 0.5)
        self.assertEqual(stats['cache_size'], 1)


class TestRegistryReaderGetUniversalId(unittest.TestCase):
    """Test get_universal_id method."""
    
    def setUp(self):
        self.mock_client = Mock()
        self.mock_client.project = 'test-project'
        self.registry = RegistryReader(
            bq_client=self.mock_client,
            source_name='test_source'
        )
    
    def test_get_universal_id_found(self):
        """Test getting universal ID for existing player."""
        # Mock BigQuery result
        mock_df = pd.DataFrame([{'universal_player_id': 'lebronjames_001'}])
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        self.mock_client.query.return_value = mock_query_job
        
        result = self.registry.get_universal_id('lebronjames')
        
        self.assertEqual(result, 'lebronjames_001')
        self.mock_client.query.assert_called_once()
    
    def test_get_universal_id_not_found_required(self):
        """Test exception when player not found and required=True."""
        # Mock empty result
        mock_df = pd.DataFrame()
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        self.mock_client.query.return_value = mock_query_job
        
        with self.assertRaises(PlayerNotFoundError) as ctx:
            self.registry.get_universal_id('unknownplayer', required=True)
        
        self.assertEqual(ctx.exception.player_lookup, 'unknownplayer')
    
    def test_get_universal_id_not_found_optional(self):
        """Test returning None when player not found and required=False."""
        # Mock empty result
        mock_df = pd.DataFrame()
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        self.mock_client.query.return_value = mock_query_job
        
        result = self.registry.get_universal_id('unknownplayer', required=False)
        
        self.assertIsNone(result)
    
    def test_get_universal_id_caching(self):
        """Test that results are cached."""
        registry = RegistryReader(
            bq_client=self.mock_client,
            source_name='test_source',
            cache_ttl_seconds=60
        )
        
        mock_df = pd.DataFrame([{'universal_player_id': 'lebronjames_001'}])
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        self.mock_client.query.return_value = mock_query_job
        
        # First call - should query
        result1 = registry.get_universal_id('lebronjames')
        # Second call - should use cache
        result2 = registry.get_universal_id('lebronjames')
        
        self.assertEqual(result1, result2)
        self.mock_client.query.assert_called_once()  # Only called once
    
    def test_get_universal_id_connection_error(self):
        """Test connection error handling."""
        self.mock_client.query.side_effect = Exception("Connection failed")
        
        with self.assertRaises(RegistryConnectionError):
            self.registry.get_universal_id('lebronjames')


class TestRegistryReaderGetPlayer(unittest.TestCase):
    """Test get_player method."""
    
    def setUp(self):
        self.mock_client = Mock()
        self.mock_client.project = 'test-project'
        self.registry = RegistryReader(
            bq_client=self.mock_client,
            source_name='test_source'
        )
    
    def test_get_player_found(self):
        """Test getting complete player record."""
        mock_df = pd.DataFrame([{
            'universal_player_id': 'lebronjames_001',
            'player_name': 'LeBron James',
            'player_lookup': 'lebronjames',
            'team_abbr': 'LAL',
            'season': '2024-25',
            'games_played': 50,
            'first_game_date': pd.Timestamp('2024-10-22'),
            'last_game_date': pd.Timestamp('2025-01-15'),
            'jersey_number': 23,
            'position': 'F',
            'source_priority': 'nba_gamebook',
            'confidence_score': 1.0,
            'last_processor': 'gamebook',
            'processed_at': pd.Timestamp('2025-01-15 10:00:00')
        }])
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        self.mock_client.query.return_value = mock_query_job
        
        result = self.registry.get_player('lebronjames', season='2024-25')
        
        self.assertEqual(result['player_name'], 'LeBron James')
        self.assertEqual(result['team_abbr'], 'LAL')
        self.assertEqual(result['games_played'], 50)
    
    def test_get_player_multiple_teams(self):
        """Test error when player on multiple teams without filter."""
        mock_df = pd.DataFrame([
            {'player_lookup': 'jamesharden', 'team_abbr': 'PHI', 'season': '2023-24'},
            {'player_lookup': 'jamesharden', 'team_abbr': 'LAC', 'season': '2023-24'}
        ])
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        self.mock_client.query.return_value = mock_query_job
        
        with self.assertRaises(MultipleRecordsError) as ctx:
            self.registry.get_player('jamesharden', season='2023-24')
        
        self.assertEqual(ctx.exception.player_lookup, 'jamesharden')
        self.assertIn('PHI', ctx.exception.teams)
        self.assertIn('LAC', ctx.exception.teams)


class TestRegistryReaderBatchOperations(unittest.TestCase):
    """Test batch operation methods."""
    
    def setUp(self):
        self.mock_client = Mock()
        self.mock_client.project = 'test-project'
        self.registry = RegistryReader(
            bq_client=self.mock_client,
            source_name='test_source'
        )
    
    def test_get_universal_ids_batch(self):
        """Test batch universal ID lookup."""
        mock_df = pd.DataFrame([
            {'player_lookup': 'lebronjames', 'universal_player_id': 'lebronjames_001'},
            {'player_lookup': 'stephencurry', 'universal_player_id': 'stephencurry_001'}
        ])
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        self.mock_client.query.return_value = mock_query_job
        
        players = ['lebronjames', 'stephencurry', 'unknownplayer']
        result = self.registry.get_universal_ids_batch(players)
        
        self.assertEqual(result['lebronjames'], 'lebronjames_001')
        self.assertEqual(result['stephencurry'], 'stephencurry_001')
        self.assertNotIn('unknownplayer', result)
    
    def test_get_universal_ids_batch_chunking(self):
        """Test that large batches are chunked."""
        # Create 150 players (exceeds MAX_BATCH_SIZE of 100)
        players = [f'player{i}' for i in range(150)]
        
        mock_df = pd.DataFrame([
            {'player_lookup': p, 'universal_player_id': f'{p}_001'} 
            for p in players[:50]  # Return first 50
        ])
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        self.mock_client.query.return_value = mock_query_job
        
        result = self.registry.get_universal_ids_batch(players)
        
        # Should make 2 queries (100 + 50)
        self.assertEqual(self.mock_client.query.call_count, 2)


class TestRegistryReaderUnresolvedTracking(unittest.TestCase):
    """Test unresolved player tracking."""
    
    def setUp(self):
        self.mock_client = Mock()
        self.mock_client.project = 'test-project'
        self.registry = RegistryReader(
            bq_client=self.mock_client,
            source_name='test_source'
        )
    
    def test_log_unresolved_player(self):
        """Test logging unresolved player."""
        self.registry._log_unresolved_player('unknownplayer', {'game_id': 'ABC123'})
        
        self.assertIn('unknownplayer', self.registry._unresolved_queue)
        self.assertEqual(len(self.registry._unresolved_queue['unknownplayer']), 1)
    
    def test_flush_unresolved_players(self):
        """Test flushing unresolved players."""
        self.mock_client.insert_rows_json.return_value = []
        
        self.registry.set_default_context(season='2024-25')
        self.registry._log_unresolved_player('player1', {'game_id': 'ABC'})
        self.registry._log_unresolved_player('player1', {'game_id': 'DEF'})
        self.registry._log_unresolved_player('player2', {'game_id': 'GHI'})
        
        self.registry.flush_unresolved_players()
        
        # Should call insert_rows_json with 2 records (player1 and player2)
        self.mock_client.insert_rows_json.assert_called_once()
        call_args = self.mock_client.insert_rows_json.call_args
        records = call_args[0][1]
        
        self.assertEqual(len(records), 2)
        
        # Check player1 record
        player1_record = [r for r in records if r['normalized_lookup'] == 'player1'][0]
        self.assertEqual(player1_record['occurrences'], 2)
        self.assertIn('ABC', player1_record['example_games'])
        self.assertIn('DEF', player1_record['example_games'])
        
        # Queue should be cleared
        self.assertEqual(len(self.registry._unresolved_queue), 0)
    
    def test_flush_unresolved_empty_queue(self):
        """Test flushing when queue is empty."""
        self.registry.flush_unresolved_players()
        
        self.mock_client.insert_rows_json.assert_not_called()


class TestRegistryReaderContextManager(unittest.TestCase):
    """Test context manager support."""
    
    def setUp(self):
        self.mock_client = Mock()
        self.mock_client.project = 'test-project'
    
    def test_context_manager_with_auto_flush(self):
        """Test context manager with auto_flush."""
        self.mock_client.insert_rows_json.return_value = []
        
        with RegistryReader(
            bq_client=self.mock_client,
            source_name='test_source',
            auto_flush=True
        ) as registry:
            registry._log_unresolved_player('player1')
        
        # Should auto-flush on exit
        self.mock_client.insert_rows_json.assert_called_once()
    
    def test_context_manager_without_auto_flush(self):
        """Test context manager without auto_flush."""
        with RegistryReader(
            bq_client=self.mock_client,
            source_name='test_source',
            auto_flush=False
        ) as registry:
            registry._log_unresolved_player('player1')
        
        # Should NOT auto-flush
        self.mock_client.insert_rows_json.assert_not_called()


class TestRegistryReaderTeamQueries(unittest.TestCase):
    """Test team-related queries."""
    
    def setUp(self):
        self.mock_client = Mock()
        self.mock_client.project = 'test-project'
        self.registry = RegistryReader(
            bq_client=self.mock_client,
            source_name='test_source'
        )
    
    def test_get_team_roster(self):
        """Test getting team roster."""
        mock_df = pd.DataFrame([
            {'player_name': 'LeBron James', 'player_lookup': 'lebronjames'},
            {'player_name': 'Anthony Davis', 'player_lookup': 'anthonydavis'}
        ])
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        self.mock_client.query.return_value = mock_query_job
        
        result = self.registry.get_team_roster('LAL', '2024-25')
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['player_name'], 'LeBron James')
    
    def test_get_active_teams(self):
        """Test getting active teams."""
        mock_df = pd.DataFrame([
            {'team_abbr': 'LAL'},
            {'team_abbr': 'BOS'},
            {'team_abbr': 'GSW'}
        ])
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        self.mock_client.query.return_value = mock_query_job
        
        result = self.registry.get_active_teams('2024-25')
        
        self.assertEqual(len(result), 3)
        self.assertIn('LAL', result)
        self.assertIn('BOS', result)


class TestRegistryReaderValidation(unittest.TestCase):
    """Test validation methods."""
    
    def setUp(self):
        self.mock_client = Mock()
        self.mock_client.project = 'test-project'
        self.registry = RegistryReader(
            bq_client=self.mock_client,
            source_name='test_source'
        )
    
    def test_validate_player_team_valid(self):
        """Test validating valid player-team combination."""
        mock_df = pd.DataFrame([{'count': 1}])
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        self.mock_client.query.return_value = mock_query_job
        
        result = self.registry.validate_player_team('lebronjames', 'LAL', '2024-25')
        
        self.assertTrue(result)
    
    def test_validate_player_team_invalid(self):
        """Test validating invalid player-team combination."""
        mock_df = pd.DataFrame([{'count': 0}])
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        self.mock_client.query.return_value = mock_query_job
        
        result = self.registry.validate_player_team('lebronjames', 'BOS', '2024-25')
        
        self.assertFalse(result)
    
    def test_player_exists(self):
        """Test player_exists method."""
        mock_df = pd.DataFrame([{'universal_player_id': 'lebronjames_001'}])
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        self.mock_client.query.return_value = mock_query_job
        
        result = self.registry.player_exists('lebronjames')
        
        self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()
#!/usr/bin/env python3
"""
Unit tests for AliasManager class.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from shared.utils.player_registry.alias_manager import (
    AliasManager,
    AliasRecord
)


class TestAliasRecord(unittest.TestCase):
    """Test AliasRecord dataclass."""

    def test_create_minimal(self):
        """Test creating alias with required fields."""
        alias = AliasRecord(
            alias_lookup='marcusmorris',
            nba_canonical_lookup='marcusmorrissr',
            alias_display='Marcus Morris',
            nba_canonical_display='Marcus Morris Sr.',
            alias_type='suffix_difference',
            alias_source='ai_resolver'
        )
        self.assertEqual(alias.alias_lookup, 'marcusmorris')
        self.assertEqual(alias.nba_canonical_lookup, 'marcusmorrissr')
        self.assertEqual(alias.confidence, 1.0)  # default
        self.assertIsNone(alias.ai_model)
        self.assertIsNone(alias.notes)

    def test_create_full(self):
        """Test creating alias with all fields."""
        alias = AliasRecord(
            alias_lookup='marcusmorris',
            nba_canonical_lookup='marcusmorrissr',
            alias_display='Marcus Morris',
            nba_canonical_display='Marcus Morris Sr.',
            alias_type='suffix_difference',
            alias_source='ai_resolver',
            confidence=0.98,
            ai_model='claude-3-haiku-20240307',
            resolution_id='msg_123',
            notes='Test note'
        )
        self.assertEqual(alias.confidence, 0.98)
        self.assertEqual(alias.ai_model, 'claude-3-haiku-20240307')
        self.assertEqual(alias.notes, 'Test note')


class TestAliasManagerInit(unittest.TestCase):
    """Test AliasManager initialization."""

    @patch('shared.utils.player_registry.alias_manager.bigquery.Client')
    def test_init_default_project(self, mock_client_class):
        """Test initialization with default project."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        manager = AliasManager()

        self.assertEqual(manager.project_id, 'nba-props-platform')
        self.assertIn('nba_reference.player_aliases', manager.table_id)

    @patch('shared.utils.player_registry.alias_manager.bigquery.Client')
    def test_init_custom_project(self, mock_client_class):
        """Test initialization with custom project."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        manager = AliasManager(project_id='custom-project')

        self.assertEqual(manager.project_id, 'custom-project')
        mock_client_class.assert_called_with(project='custom-project')


class TestAliasManagerCreate(unittest.TestCase):
    """Test alias creation methods."""

    def setUp(self):
        """Set up manager with mocked client."""
        self.mock_client = Mock()
        with patch('shared.utils.player_registry.alias_manager.bigquery.Client',
                   return_value=self.mock_client):
            self.manager = AliasManager()

    def test_create_alias_success(self):
        """Test successful single alias creation."""
        # Mock no existing aliases
        mock_query_result = Mock()
        mock_query_result.result.return_value = []
        self.mock_client.query.return_value = mock_query_result

        # Mock successful insert
        self.mock_client.insert_rows_json.return_value = []

        alias = AliasRecord(
            alias_lookup='marcusmorris',
            nba_canonical_lookup='marcusmorrissr',
            alias_display='Marcus Morris',
            nba_canonical_display='Marcus Morris Sr.',
            alias_type='suffix_difference',
            alias_source='ai_resolver'
        )

        result = self.manager.create_alias(alias)

        self.assertTrue(result)
        self.mock_client.insert_rows_json.assert_called_once()

    def test_create_alias_already_exists(self):
        """Test that existing alias is not recreated."""
        # Mock alias already exists
        mock_result = Mock()
        mock_result.alias_lookup = 'marcusmorris'
        mock_query_result = Mock()
        mock_query_result.result.return_value = [mock_result]
        self.mock_client.query.return_value = mock_query_result

        alias = AliasRecord(
            alias_lookup='marcusmorris',
            nba_canonical_lookup='marcusmorrissr',
            alias_display='Marcus Morris',
            nba_canonical_display='Marcus Morris Sr.',
            alias_type='suffix_difference',
            alias_source='ai_resolver'
        )

        result = self.manager.create_alias(alias)

        self.assertFalse(result)
        self.mock_client.insert_rows_json.assert_not_called()

    def test_bulk_create_aliases_empty(self):
        """Test bulk create with empty list."""
        result = self.manager.bulk_create_aliases([])
        self.assertEqual(result, 0)

    def test_bulk_create_aliases_filters_existing(self):
        """Test that existing aliases are filtered out."""
        # Mock one existing alias
        mock_result = Mock()
        mock_result.alias_lookup = 'existing'
        mock_query_result = Mock()
        mock_query_result.result.return_value = [mock_result]
        self.mock_client.query.return_value = mock_query_result

        # Mock successful insert
        self.mock_client.insert_rows_json.return_value = []

        aliases = [
            AliasRecord(
                alias_lookup='existing',
                nba_canonical_lookup='existingsr',
                alias_display='Existing',
                nba_canonical_display='Existing Sr.',
                alias_type='suffix_difference',
                alias_source='ai_resolver'
            ),
            AliasRecord(
                alias_lookup='new',
                nba_canonical_lookup='newjr',
                alias_display='New',
                nba_canonical_display='New Jr.',
                alias_type='suffix_difference',
                alias_source='ai_resolver'
            )
        ]

        result = self.manager.bulk_create_aliases(aliases)

        self.assertEqual(result, 1)  # Only 'new' was created
        # Verify only one row was inserted
        call_args = self.mock_client.insert_rows_json.call_args
        rows = call_args[0][1]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['alias_lookup'], 'new')

    def test_bulk_create_handles_insert_errors(self):
        """Test bulk create returns partial count on errors."""
        # Mock no existing aliases
        mock_query_result = Mock()
        mock_query_result.result.return_value = []
        self.mock_client.query.return_value = mock_query_result

        # Mock insert with one error
        self.mock_client.insert_rows_json.return_value = [{'errors': ['test']}]

        aliases = [
            AliasRecord(
                alias_lookup='test1',
                nba_canonical_lookup='test1sr',
                alias_display='Test 1',
                nba_canonical_display='Test 1 Sr.',
                alias_type='suffix_difference',
                alias_source='ai_resolver'
            ),
            AliasRecord(
                alias_lookup='test2',
                nba_canonical_lookup='test2sr',
                alias_display='Test 2',
                nba_canonical_display='Test 2 Sr.',
                alias_type='suffix_difference',
                alias_source='ai_resolver'
            )
        ]

        result = self.manager.bulk_create_aliases(aliases)

        # 2 aliases - 1 error = 1 success
        self.assertEqual(result, 1)


class TestAliasManagerGet(unittest.TestCase):
    """Test alias retrieval methods."""

    def setUp(self):
        """Set up manager with mocked client."""
        self.mock_client = Mock()
        with patch('shared.utils.player_registry.alias_manager.bigquery.Client',
                   return_value=self.mock_client):
            self.manager = AliasManager()

    def test_get_alias_found(self):
        """Test getting existing alias."""
        mock_row = Mock()
        mock_row.alias_lookup = 'marcusmorris'
        mock_row.nba_canonical_lookup = 'marcusmorrissr'
        mock_row.alias_display = 'Marcus Morris'
        mock_row.nba_canonical_display = 'Marcus Morris Sr.'
        mock_row.alias_type = 'suffix_difference'
        mock_row.alias_source = 'ai_resolver'
        mock_row.notes = None

        mock_query_result = Mock()
        mock_query_result.result.return_value = [mock_row]
        self.mock_client.query.return_value = mock_query_result

        result = self.manager.get_alias('marcusmorris')

        self.assertIsNotNone(result)
        self.assertEqual(result.alias_lookup, 'marcusmorris')
        self.assertEqual(result.nba_canonical_lookup, 'marcusmorrissr')

    def test_get_alias_not_found(self):
        """Test getting non-existent alias."""
        mock_query_result = Mock()
        mock_query_result.result.return_value = []
        self.mock_client.query.return_value = mock_query_result

        result = self.manager.get_alias('nonexistent')

        self.assertIsNone(result)

    def test_get_alias_handles_error(self):
        """Test that errors return None."""
        self.mock_client.query.side_effect = Exception('Query failed')

        result = self.manager.get_alias('test')

        self.assertIsNone(result)


class TestAliasManagerDeactivate(unittest.TestCase):
    """Test alias deactivation."""

    def setUp(self):
        """Set up manager with mocked client."""
        self.mock_client = Mock()
        with patch('shared.utils.player_registry.alias_manager.bigquery.Client',
                   return_value=self.mock_client):
            self.manager = AliasManager()

    def test_deactivate_alias_success(self):
        """Test successful deactivation."""
        mock_job = Mock()
        mock_job.result.return_value = None
        self.mock_client.query.return_value = mock_job

        result = self.manager.deactivate_alias('marcusmorris', 'Incorrect mapping')

        self.assertTrue(result)

    def test_deactivate_alias_handles_error(self):
        """Test deactivation error handling."""
        self.mock_client.query.side_effect = Exception('Update failed')

        result = self.manager.deactivate_alias('test', 'reason')

        self.assertFalse(result)


class TestAliasManagerStats(unittest.TestCase):
    """Test alias statistics."""

    def setUp(self):
        """Set up manager with mocked client."""
        self.mock_client = Mock()
        with patch('shared.utils.player_registry.alias_manager.bigquery.Client',
                   return_value=self.mock_client):
            self.manager = AliasManager()

    def test_get_all_active_aliases(self):
        """Test getting all active aliases."""
        mock_row1 = Mock()
        mock_row1.alias_lookup = 'alias1'
        mock_row1.nba_canonical_lookup = 'canonical1'
        mock_row1.alias_display = 'Alias 1'
        mock_row1.nba_canonical_display = 'Canonical 1'
        mock_row1.alias_type = 'suffix_difference'
        mock_row1.alias_source = 'ai_resolver'
        mock_row1.notes = None

        mock_row2 = Mock()
        mock_row2.alias_lookup = 'alias2'
        mock_row2.nba_canonical_lookup = 'canonical2'
        mock_row2.alias_display = 'Alias 2'
        mock_row2.nba_canonical_display = 'Canonical 2'
        mock_row2.alias_type = 'encoding_difference'
        mock_row2.alias_source = 'manual'
        mock_row2.notes = 'Test note'

        mock_query_result = Mock()
        mock_query_result.result.return_value = [mock_row1, mock_row2]
        self.mock_client.query.return_value = mock_query_result

        result = self.manager.get_all_active_aliases()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].alias_lookup, 'alias1')
        self.assertEqual(result[1].alias_lookup, 'alias2')

    def test_get_alias_stats(self):
        """Test getting alias statistics."""
        mock_stats = Mock()
        mock_stats.total = 10
        mock_stats.active = 8
        mock_stats.inactive = 2

        mock_type1 = Mock()
        mock_type1.alias_type = 'suffix_difference'
        mock_type1.count = 5

        mock_type2 = Mock()
        mock_type2.alias_type = 'encoding_difference'
        mock_type2.count = 3

        self.mock_client.query.side_effect = [
            Mock(result=Mock(return_value=[mock_stats])),
            Mock(result=Mock(return_value=[mock_type1, mock_type2]))
        ]

        result = self.manager.get_alias_stats()

        self.assertEqual(result['total'], 10)
        self.assertEqual(result['active'], 8)
        self.assertEqual(result['by_type']['suffix_difference'], 5)

    def test_get_alias_stats_handles_error(self):
        """Test stats error handling."""
        self.mock_client.query.side_effect = Exception('Query failed')

        result = self.manager.get_alias_stats()

        self.assertEqual(result['total'], 0)
        self.assertEqual(result['active'], 0)


class TestGetExistingAliases(unittest.TestCase):
    """Test _get_existing_aliases helper method."""

    def setUp(self):
        """Set up manager with mocked client."""
        self.mock_client = Mock()
        with patch('shared.utils.player_registry.alias_manager.bigquery.Client',
                   return_value=self.mock_client):
            self.manager = AliasManager()

    def test_get_existing_aliases_empty_list(self):
        """Test with empty input list."""
        result = self.manager._get_existing_aliases([])
        self.assertEqual(result, set())

    def test_get_existing_aliases_returns_set(self):
        """Test that existing aliases are returned as set."""
        mock_row1 = Mock()
        mock_row1.alias_lookup = 'alias1'
        mock_row2 = Mock()
        mock_row2.alias_lookup = 'alias2'

        mock_query_result = Mock()
        mock_query_result.result.return_value = [mock_row1, mock_row2]
        self.mock_client.query.return_value = mock_query_result

        result = self.manager._get_existing_aliases(['alias1', 'alias2', 'alias3'])

        self.assertEqual(result, {'alias1', 'alias2'})

    def test_get_existing_aliases_handles_error(self):
        """Test error handling returns empty set."""
        self.mock_client.query.side_effect = Exception('Query failed')

        result = self.manager._get_existing_aliases(['test'])

        self.assertEqual(result, set())


if __name__ == '__main__':
    unittest.main()

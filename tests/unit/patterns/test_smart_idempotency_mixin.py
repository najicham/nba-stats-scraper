#!/usr/bin/env python3
"""
Unit Tests for Smart Idempotency Mixin (Phase 2 Pattern)

Tests the SmartIdempotencyMixin directly with mocked dependencies.
This ensures the pattern works correctly across all Phase 2 processors.

Key test areas:
- Hash computation (SHA256, normalization, deterministic)
- Hash field addition to transformed_data
- BigQuery hash querying
- Skip write logic (MERGE_UPDATE vs APPEND_ALWAYS)
- Statistics tracking
"""

import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, List, Any

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin


class MockProcessor(SmartIdempotencyMixin):
    """Mock processor for testing the mixin."""

    HASH_FIELDS = ['game_id', 'player_lookup', 'points', 'assists']
    PRIMARY_KEYS = ['game_id', 'player_lookup']

    def __init__(self):
        self.table_name = 'nba_raw.test_table'
        self.bq_client = Mock()
        self.processing_strategy = 'MERGE_UPDATE'
        self.transformed_data = []
        self._idempotency_stats = {}


class TestHashComputation(unittest.TestCase):
    """Test hash computation logic."""

    def setUp(self):
        """Set up test processor."""
        self.processor = MockProcessor()

    def test_compute_hash_basic(self):
        """Test basic hash computation."""
        record = {
            'game_id': '0022400561',
            'player_lookup': 'lebronjames',
            'points': 25,
            'assists': 8
        }

        hash_value = self.processor.compute_data_hash(record)

        # Verify hash format
        self.assertIsInstance(hash_value, str)
        self.assertEqual(len(hash_value), 16)  # 16 hex chars
        self.assertTrue(all(c in '0123456789abcdef' for c in hash_value))

    def test_compute_hash_deterministic(self):
        """Test hash is deterministic (same input = same hash)."""
        record = {
            'game_id': '0022400561',
            'player_lookup': 'lebronjames',
            'points': 25,
            'assists': 8
        }

        hash1 = self.processor.compute_data_hash(record)
        hash2 = self.processor.compute_data_hash(record)

        self.assertEqual(hash1, hash2)

    def test_compute_hash_changes_with_data(self):
        """Test hash changes when data changes."""
        record1 = {
            'game_id': '0022400561',
            'player_lookup': 'lebronjames',
            'points': 25,
            'assists': 8
        }

        record2 = {
            'game_id': '0022400561',
            'player_lookup': 'lebronjames',
            'points': 30,  # Changed!
            'assists': 8
        }

        hash1 = self.processor.compute_data_hash(record1)
        hash2 = self.processor.compute_data_hash(record2)

        self.assertNotEqual(hash1, hash2)

    def test_compute_hash_with_none_values(self):
        """Test hash computation with None values."""
        record = {
            'game_id': '0022400561',
            'player_lookup': 'lebronjames',
            'points': None,
            'assists': 8
        }

        hash_value = self.processor.compute_data_hash(record)

        self.assertIsInstance(hash_value, str)
        self.assertEqual(len(hash_value), 16)

    def test_compute_hash_with_numeric_types(self):
        """Test hash computation handles int and float correctly."""
        record_int = {
            'game_id': '0022400561',
            'player_lookup': 'lebronjames',
            'points': 25,
            'assists': 8
        }

        record_float = {
            'game_id': '0022400561',
            'player_lookup': 'lebronjames',
            'points': 25.0,
            'assists': 8.0
        }

        hash_int = self.processor.compute_data_hash(record_int)
        hash_float = self.processor.compute_data_hash(record_float)

        # Note: int and float produce different string representations
        # str(25) = "25" vs str(25.0) = "25.0"
        # This is intentional - hash should be sensitive to data type
        self.assertNotEqual(hash_int, hash_float)

        # But same type should produce same hash
        record_int2 = {
            'game_id': '0022400561',
            'player_lookup': 'lebronjames',
            'points': 25,
            'assists': 8
        }
        hash_int2 = self.processor.compute_data_hash(record_int2)
        self.assertEqual(hash_int, hash_int2)

    def test_compute_hash_with_string_whitespace(self):
        """Test hash computation strips whitespace from strings."""
        record1 = {
            'game_id': '0022400561',
            'player_lookup': 'lebronjames',
            'points': 25,
            'assists': 8
        }

        record2 = {
            'game_id': '0022400561',
            'player_lookup': '  lebronjames  ',  # Whitespace
            'points': 25,
            'assists': 8
        }

        hash1 = self.processor.compute_data_hash(record1)
        hash2 = self.processor.compute_data_hash(record2)

        self.assertEqual(hash1, hash2)

    def test_compute_hash_field_order_independent(self):
        """Test hash is same regardless of field order in record."""
        # Hash computation sorts fields internally
        record1 = {
            'game_id': '0022400561',
            'player_lookup': 'lebronjames',
            'points': 25,
            'assists': 8
        }

        # Different order, same values
        record2 = {
            'assists': 8,
            'game_id': '0022400561',
            'points': 25,
            'player_lookup': 'lebronjames'
        }

        hash1 = self.processor.compute_data_hash(record1)
        hash2 = self.processor.compute_data_hash(record2)

        self.assertEqual(hash1, hash2)

    def test_compute_hash_missing_field_raises_error(self):
        """Test error when hash field missing from record."""
        record = {
            'game_id': '0022400561',
            'player_lookup': 'lebronjames',
            # Missing 'points' and 'assists'
        }

        with self.assertRaises(ValueError) as context:
            self.processor.compute_data_hash(record)

        self.assertIn("not found in record", str(context.exception))

    def test_compute_hash_no_hash_fields_raises_error(self):
        """Test error when HASH_FIELDS not defined."""
        processor = SmartIdempotencyMixin()
        processor.HASH_FIELDS = []

        record = {'game_id': '0022400561'}

        with self.assertRaises(ValueError) as context:
            processor.compute_data_hash(record)

        self.assertIn("must define HASH_FIELDS", str(context.exception))


class TestAddDataHash(unittest.TestCase):
    """Test add_data_hash() method."""

    def setUp(self):
        """Set up test processor."""
        self.processor = MockProcessor()

    def test_add_data_hash_to_list(self):
        """Test adding hash to list of records."""
        self.processor.transformed_data = [
            {
                'game_id': '0022400561',
                'player_lookup': 'lebronjames',
                'points': 25,
                'assists': 8
            },
            {
                'game_id': '0022400562',
                'player_lookup': 'stephencurry',
                'points': 30,
                'assists': 6
            }
        ]

        self.processor.add_data_hash()

        # Verify hash added to all records
        self.assertEqual(len(self.processor.transformed_data), 2)
        self.assertIn('data_hash', self.processor.transformed_data[0])
        self.assertIn('data_hash', self.processor.transformed_data[1])

        # Verify hashes are different (different data)
        hash1 = self.processor.transformed_data[0]['data_hash']
        hash2 = self.processor.transformed_data[1]['data_hash']
        self.assertNotEqual(hash1, hash2)

    def test_add_data_hash_to_single_dict(self):
        """Test adding hash to single record (dict format)."""
        self.processor.transformed_data = {
            'game_id': '0022400561',
            'player_lookup': 'lebronjames',
            'points': 25,
            'assists': 8
        }

        self.processor.add_data_hash()

        # Verify hash added
        self.assertIn('data_hash', self.processor.transformed_data)
        self.assertEqual(len(self.processor.transformed_data['data_hash']), 16)

    def test_add_data_hash_empty_list(self):
        """Test add_data_hash with empty list."""
        self.processor.transformed_data = []

        # Should not raise error
        self.processor.add_data_hash()

        # Verify no hashes added (no data)
        stats = self.processor.get_idempotency_stats()
        self.assertEqual(stats['hashes_computed'], 0)

    def test_add_data_hash_updates_stats(self):
        """Test that statistics are updated."""
        self.processor.transformed_data = [
            {
                'game_id': '0022400561',
                'player_lookup': 'lebronjames',
                'points': 25,
                'assists': 8
            }
        ]

        self.processor.add_data_hash()

        stats = self.processor.get_idempotency_stats()
        self.assertEqual(stats['hashes_computed'], 1)

    def test_add_data_hash_handles_error_gracefully(self):
        """Test error handling when hash computation fails."""
        self.processor.transformed_data = [
            {
                'game_id': '0022400561',
                # Missing required hash fields
            }
        ]

        # Should not raise error, adds None hash
        self.processor.add_data_hash()

        # Verify None hash added for consistency
        self.assertIn('data_hash', self.processor.transformed_data[0])
        self.assertIsNone(self.processor.transformed_data[0]['data_hash'])


class TestQueryExistingHash(unittest.TestCase):
    """Test query_existing_hash() method."""

    def setUp(self):
        """Set up test processor."""
        self.processor = MockProcessor()

    def test_query_existing_hash_found(self):
        """Test querying hash when record exists."""
        # Mock BigQuery response
        mock_row = Mock()
        mock_row.data_hash = 'abc123def456'

        mock_job = Mock()
        mock_job.result.return_value = [mock_row]

        self.processor.bq_client.query.return_value = mock_job

        # Query hash
        pk_dict = {'game_id': '0022400561', 'player_lookup': 'lebronjames'}
        hash_value = self.processor.query_existing_hash(pk_dict)

        # Verify
        self.assertEqual(hash_value, 'abc123def456')
        self.assertTrue(self.processor.bq_client.query.called)

    def test_query_existing_hash_not_found(self):
        """Test querying hash when record doesn't exist."""
        # Mock empty BigQuery response
        mock_job = Mock()
        mock_job.result.return_value = []

        self.processor.bq_client.query.return_value = mock_job

        # Query hash
        pk_dict = {'game_id': '0022400561', 'player_lookup': 'lebronjames'}
        hash_value = self.processor.query_existing_hash(pk_dict)

        # Verify
        self.assertIsNone(hash_value)

    def test_query_existing_hash_with_date_field(self):
        """Test query includes date partition column."""
        mock_job = Mock()
        mock_job.result.return_value = []
        self.processor.bq_client.query.return_value = mock_job

        # Query with date field
        pk_dict = {
            'game_id': '0022400561',
            'player_lookup': 'lebronjames',
            'game_date': '2024-11-20'
        }

        self.processor.query_existing_hash(pk_dict)

        # Verify query includes DATE() function for date
        query = self.processor.bq_client.query.call_args[0][0]
        self.assertIn("game_date = DATE('2024-11-20')", query)

    def test_query_existing_hash_with_none_value(self):
        """Test query handles None values with IS NULL."""
        mock_job = Mock()
        mock_job.result.return_value = []
        self.processor.bq_client.query.return_value = mock_job

        # Query with None
        pk_dict = {
            'game_id': '0022400561',
            'player_lookup': None
        }

        self.processor.query_existing_hash(pk_dict)

        # Verify query uses IS NULL
        query = self.processor.bq_client.query.call_args[0][0]
        self.assertIn("player_lookup IS NULL", query)

    def test_query_existing_hash_escapes_quotes(self):
        """Test query escapes single quotes in strings."""
        mock_job = Mock()
        mock_job.result.return_value = []
        self.processor.bq_client.query.return_value = mock_job

        # Query with quote in value
        pk_dict = {
            'game_id': "game'id",
            'player_lookup': 'lebronjames'
        }

        self.processor.query_existing_hash(pk_dict)

        # Verify quote escaped
        query = self.processor.bq_client.query.call_args[0][0]
        self.assertIn("game\\'id", query)

    def test_query_existing_hash_no_client(self):
        """Test query returns None when no BigQuery client."""
        self.processor.bq_client = None

        pk_dict = {'game_id': '0022400561'}
        hash_value = self.processor.query_existing_hash(pk_dict)

        self.assertIsNone(hash_value)

    def test_query_existing_hash_handles_exception(self):
        """Test query returns None on exception."""
        # Mock exception
        self.processor.bq_client.query.side_effect = Exception("Query failed")

        pk_dict = {'game_id': '0022400561'}
        hash_value = self.processor.query_existing_hash(pk_dict)

        self.assertIsNone(hash_value)


class TestShouldSkipWrite(unittest.TestCase):
    """Test should_skip_write() decision logic."""

    def setUp(self):
        """Set up test processor."""
        self.processor = MockProcessor()

    def test_should_skip_write_append_always_never_skips(self):
        """Test APPEND_ALWAYS strategy never skips."""
        self.processor.processing_strategy = 'APPEND_ALWAYS'
        self.processor.transformed_data = [
            {
                'game_id': '0022400561',
                'player_lookup': 'lebronjames',
                'points': 25,
                'assists': 8,
                'data_hash': 'abc123'
            }
        ]

        skip = self.processor.should_skip_write()

        self.assertFalse(skip)

        stats = self.processor.get_idempotency_stats()
        self.assertEqual(stats['strategy'], 'APPEND_ALWAYS')
        self.assertFalse(stats['skip_check_performed'])

    def test_should_skip_write_merge_all_match(self):
        """Test MERGE_UPDATE skips when all hashes match."""
        self.processor.processing_strategy = 'MERGE_UPDATE'
        self.processor.transformed_data = [
            {
                'game_id': '0022400561',
                'player_lookup': 'lebronjames',
                'points': 25,
                'assists': 8,
                'data_hash': 'abc123'
            }
        ]

        # Mock existing hash matches
        def mock_query_hash(pk_dict, table_id=None):
            return 'abc123'  # Matches!

        self.processor.query_existing_hash = mock_query_hash

        skip = self.processor.should_skip_write()

        self.assertTrue(skip)

        stats = self.processor.get_idempotency_stats()
        self.assertEqual(stats['hashes_matched'], 1)
        self.assertEqual(stats['rows_skipped'], 1)

    def test_should_skip_write_merge_one_differs(self):
        """Test MERGE_UPDATE doesn't skip when any hash differs."""
        self.processor.transformed_data = [
            {
                'game_id': '0022400561',
                'player_lookup': 'lebronjames',
                'points': 25,
                'assists': 8,
                'data_hash': 'abc123'
            },
            {
                'game_id': '0022400562',
                'player_lookup': 'stephencurry',
                'points': 30,
                'assists': 6,
                'data_hash': 'def456'
            }
        ]

        # Mock first matches, second differs
        call_count = [0]
        def mock_query_hash(pk_dict, table_id=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return 'abc123'  # Matches
            else:
                return 'xyz999'  # Different!

        self.processor.query_existing_hash = mock_query_hash

        skip = self.processor.should_skip_write()

        self.assertFalse(skip)

        stats = self.processor.get_idempotency_stats()
        # Should stop checking after first mismatch
        self.assertEqual(stats['hashes_matched'], 1)
        self.assertEqual(stats['rows_skipped'], 0)

    def test_should_skip_write_no_existing_hash(self):
        """Test doesn't skip when no existing hash (new record)."""
        self.processor.transformed_data = [
            {
                'game_id': '0022400561',
                'player_lookup': 'lebronjames',
                'points': 25,
                'assists': 8,
                'data_hash': 'abc123'
            }
        ]

        # Mock no existing hash
        self.processor.query_existing_hash = lambda pk, table_id=None: None

        skip = self.processor.should_skip_write()

        self.assertFalse(skip)

    def test_should_skip_write_empty_data(self):
        """Test doesn't skip when no data."""
        self.processor.transformed_data = []

        skip = self.processor.should_skip_write()

        self.assertFalse(skip)

    def test_should_skip_write_no_primary_keys(self):
        """Test doesn't skip when PRIMARY_KEYS not defined."""
        self.processor.PRIMARY_KEYS = None
        self.processor.transformed_data = [
            {
                'game_id': '0022400561',
                'player_lookup': 'lebronjames',
                'points': 25,
                'assists': 8,
                'data_hash': 'abc123'
            }
        ]

        skip = self.processor.should_skip_write()

        self.assertFalse(skip)

    def test_should_skip_write_includes_partition_column(self):
        """Test query includes partition column in lookup."""
        self.processor.PARTITION_COLUMN = 'game_date'
        self.processor.transformed_data = [
            {
                'game_id': '0022400561',
                'player_lookup': 'lebronjames',
                'points': 25,
                'assists': 8,
                'game_date': '2024-11-20',
                'data_hash': 'abc123'
            }
        ]

        # Track calls to verify partition included
        queries = []
        def mock_query_hash(pk_dict, table_id=None):
            queries.append(pk_dict)
            return 'abc123'

        self.processor.query_existing_hash = mock_query_hash
        self.processor.should_skip_write()

        # Verify partition column included
        self.assertIn('game_date', queries[0])
        self.assertEqual(queries[0]['game_date'], '2024-11-20')


class TestIdempotencyStats(unittest.TestCase):
    """Test get_idempotency_stats() method."""

    def setUp(self):
        """Set up test processor."""
        self.processor = MockProcessor()

    def test_get_stats_initial(self):
        """Test stats before any operations."""
        stats = self.processor.get_idempotency_stats()

        self.assertEqual(stats['hashes_computed'], 0)
        self.assertEqual(stats['hashes_matched'], 0)
        self.assertEqual(stats['rows_skipped'], 0)
        self.assertIn('strategy', stats)

    def test_get_stats_after_hash_computation(self):
        """Test stats after computing hashes."""
        self.processor.transformed_data = [
            {
                'game_id': '0022400561',
                'player_lookup': 'lebronjames',
                'points': 25,
                'assists': 8
            }
        ]

        self.processor.add_data_hash()
        stats = self.processor.get_idempotency_stats()

        self.assertEqual(stats['hashes_computed'], 1)

    def test_get_stats_after_skip(self):
        """Test stats after skipping write."""
        self.processor.transformed_data = [
            {
                'game_id': '0022400561',
                'player_lookup': 'lebronjames',
                'points': 25,
                'assists': 8,
                'data_hash': 'abc123'
            }
        ]

        # Mock hash match
        self.processor.query_existing_hash = lambda pk, table_id=None: 'abc123'
        self.processor.should_skip_write()

        stats = self.processor.get_idempotency_stats()

        self.assertEqual(stats['hashes_matched'], 1)
        self.assertEqual(stats['rows_skipped'], 1)
        self.assertEqual(stats['strategy'], 'MERGE_UPDATE')
        self.assertTrue(stats['skip_check_performed'])


def suite():
    """Create test suite."""
    suite = unittest.TestSuite()

    suite.addTest(unittest.makeSuite(TestHashComputation))
    suite.addTest(unittest.makeSuite(TestAddDataHash))
    suite.addTest(unittest.makeSuite(TestQueryExistingHash))
    suite.addTest(unittest.makeSuite(TestShouldSkipWrite))
    suite.addTest(unittest.makeSuite(TestIdempotencyStats))

    return suite


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite())

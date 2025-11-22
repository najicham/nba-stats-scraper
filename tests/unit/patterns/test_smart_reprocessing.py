#!/usr/bin/env python3
"""
Unit Tests for Smart Reprocessing Pattern

Tests the Phase 3 smart reprocessing logic with mocked BigQuery data.
This ensures processors correctly skip processing when Phase 2 source data unchanged.
"""

import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone
from typing import Dict, Optional

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from data_processors.analytics.analytics_base import AnalyticsProcessorBase


class MockAnalyticsProcessor(AnalyticsProcessorBase):
    """Mock processor for testing smart reprocessing."""

    def __init__(self):
        super().__init__()
        self.table_name = "test_analytics_table"
        self.dataset_id = "nba_analytics"
        self.project_id = "test-project"

    def get_dependencies(self) -> dict:
        """Define test dependencies."""
        return {
            'test_source_1': {
                'field_prefix': 'source_test1',
                'check_type': 'date_range',
                'expected_count_min': 100,
                'critical': True
            },
            'test_source_2': {
                'field_prefix': 'source_test2',
                'check_type': 'date_range',
                'expected_count_min': 50,
                'critical': False
            }
        }


class TestSmartReprocessing(unittest.TestCase):
    """Test smart reprocessing pattern."""

    def setUp(self):
        """Set up test processor."""
        self.processor = MockAnalyticsProcessor()
        self.processor.bq_client = Mock()

    def test_get_previous_source_hashes_with_data(self):
        """Test retrieving previous hashes when data exists."""
        # Mock BigQuery response
        mock_row = {
            'source_test1_hash': 'hash123',
            'source_test2_hash': 'hash456'
        }

        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([mock_row]))
        self.processor.bq_client.query.return_value.result.return_value = mock_result

        # Test
        hashes = self.processor.get_previous_source_hashes('2024-11-20', 'game001')

        # Verify
        self.assertEqual(hashes['source_test1_hash'], 'hash123')
        self.assertEqual(hashes['source_test2_hash'], 'hash456')

    def test_get_previous_source_hashes_no_data(self):
        """Test retrieving previous hashes when no previous data."""
        # Mock empty BigQuery response
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([]))
        self.processor.bq_client.query.return_value.result.return_value = mock_result

        # Test
        hashes = self.processor.get_previous_source_hashes('2024-11-20')

        # Verify
        self.assertEqual(hashes, {})

    def test_get_previous_source_hashes_query_error(self):
        """Test handling of query errors."""
        # Mock BigQuery error
        self.processor.bq_client.query.side_effect = Exception("Query failed")

        # Test
        hashes = self.processor.get_previous_source_hashes('2024-11-20')

        # Verify returns empty dict on error
        self.assertEqual(hashes, {})

    def test_should_skip_processing_all_unchanged(self):
        """Test skip decision when all sources unchanged."""
        # Set current hashes (from dependency check)
        self.processor.source_test1_hash = 'hash123'
        self.processor.source_test2_hash = 'hash456'

        # Mock previous hashes (same as current)
        with patch.object(self.processor, 'get_previous_source_hashes') as mock_get:
            mock_get.return_value = {
                'source_test1_hash': 'hash123',
                'source_test2_hash': 'hash456'
            }

            # Test - check primary source only
            skip, reason = self.processor.should_skip_processing('2024-11-20')

            # Verify - should skip
            self.assertTrue(skip)
            self.assertIn("unchanged", reason.lower())

    def test_should_skip_processing_primary_changed(self):
        """Test skip decision when primary source changed."""
        # Set current hashes
        self.processor.source_test1_hash = 'hash999'  # Changed!
        self.processor.source_test2_hash = 'hash456'

        # Mock previous hashes
        with patch.object(self.processor, 'get_previous_source_hashes') as mock_get:
            mock_get.return_value = {
                'source_test1_hash': 'hash123',
                'source_test2_hash': 'hash456'
            }

            # Test
            skip, reason = self.processor.should_skip_processing('2024-11-20')

            # Verify - should not skip
            self.assertFalse(skip)
            self.assertIn("changed", reason.lower())
            self.assertIn("test_source_1", reason)

    def test_should_skip_processing_check_all_sources(self):
        """Test skip decision when checking all sources (stricter mode)."""
        # Set current hashes
        self.processor.source_test1_hash = 'hash123'  # Unchanged
        self.processor.source_test2_hash = 'hash999'  # Changed!

        # Mock previous hashes
        with patch.object(self.processor, 'get_previous_source_hashes') as mock_get:
            mock_get.return_value = {
                'source_test1_hash': 'hash123',
                'source_test2_hash': 'hash456'
            }

            # Test with check_all_sources=False (should skip - primary unchanged)
            skip_lenient, reason_lenient = self.processor.should_skip_processing(
                '2024-11-20',
                check_all_sources=False
            )

            # Test with check_all_sources=True (should not skip - secondary changed)
            skip_strict, reason_strict = self.processor.should_skip_processing(
                '2024-11-20',
                check_all_sources=True
            )

            # Verify
            self.assertTrue(skip_lenient, "Lenient mode should skip (primary unchanged)")
            self.assertFalse(skip_strict, "Strict mode should not skip (secondary changed)")
            self.assertIn("test_source_2", reason_strict)

    def test_should_skip_processing_no_previous_data(self):
        """Test skip decision when no previous data (first run)."""
        # Set current hashes
        self.processor.source_test1_hash = 'hash123'

        # Mock no previous hashes
        with patch.object(self.processor, 'get_previous_source_hashes') as mock_get:
            mock_get.return_value = {}

            # Test
            skip, reason = self.processor.should_skip_processing('2024-11-20')

            # Verify - should not skip (first run)
            self.assertFalse(skip)
            self.assertIn("no previous data", reason.lower())

    def test_should_skip_processing_no_current_hash(self):
        """Test skip decision when current hash missing."""
        # Don't set current hashes (simulate dependency check failure)

        # Mock previous hashes exist
        with patch.object(self.processor, 'get_previous_source_hashes') as mock_get:
            mock_get.return_value = {
                'source_test1_hash': 'hash123'
            }

            # Test
            skip, reason = self.processor.should_skip_processing('2024-11-20')

            # Verify - should not skip (can't compare)
            self.assertFalse(skip)
            self.assertIn("no current hashes", reason.lower())

    def test_should_skip_processing_with_game_id(self):
        """Test skip decision with specific game_id."""
        # Set current hashes
        self.processor.source_test1_hash = 'hash123'

        # Mock previous hashes
        with patch.object(self.processor, 'get_previous_source_hashes') as mock_get:
            mock_get.return_value = {
                'source_test1_hash': 'hash123'
            }

            # Test with game_id
            skip, reason = self.processor.should_skip_processing(
                '2024-11-20',
                game_id='game001'
            )

            # Verify get_previous_source_hashes called with game_id
            mock_get.assert_called_once_with('2024-11-20', 'game001')
            self.assertTrue(skip)

    def test_should_skip_processing_null_hash_values(self):
        """Test skip decision when hash values are None."""
        # Set current hash to None
        self.processor.source_test1_hash = None

        # Mock previous hash exists
        with patch.object(self.processor, 'get_previous_source_hashes') as mock_get:
            mock_get.return_value = {
                'source_test1_hash': 'hash123'
            }

            # Test
            skip, reason = self.processor.should_skip_processing('2024-11-20')

            # Verify - should not skip (can't compare None)
            self.assertFalse(skip)
            # Reason could be "no current hashes" or "new/missing" depending on scenario
            self.assertTrue("hash" in reason.lower() or "missing" in reason.lower())


class TestSmartReprocessingIntegration(unittest.TestCase):
    """Test smart reprocessing integration with processors."""

    def test_processor_sets_hashes_from_dependency_check(self):
        """Test that dependency check populates hash attributes."""
        processor = MockAnalyticsProcessor()
        processor.bq_client = Mock()

        # Mock dependency check result with hash
        dep_result = {
            'exists': True,
            'row_count': 100,
            'last_updated': datetime.now(timezone.utc),
            'completeness_pct': 100.0,
            'age_hours': 2.0,
            'data_hash': 'test_hash_123'
        }

        dep_check = {
            'success': True,
            'details': {
                'test_source_1': dep_result,
                'test_source_2': dep_result
            }
        }

        # Track source usage (this should set hash attributes)
        processor.track_source_usage(dep_check)

        # Verify hash attributes set
        self.assertEqual(processor.source_test1_hash, 'test_hash_123')
        self.assertEqual(processor.source_test2_hash, 'test_hash_123')

    def test_build_source_tracking_fields_includes_hash(self):
        """Test that source tracking fields include hash."""
        processor = MockAnalyticsProcessor()

        # Set hash attributes
        processor.source_test1_hash = 'hash123'
        processor.source_test1_last_updated = datetime.now(timezone.utc)
        processor.source_test1_rows_found = 100
        processor.source_test1_completeness_pct = 100.0

        # Build fields
        fields = processor.build_source_tracking_fields()

        # Verify hash included
        self.assertEqual(fields['source_test1_hash'], 'hash123')
        self.assertEqual(fields['source_test1_rows_found'], 100)
        self.assertEqual(fields['source_test1_completeness_pct'], 100.0)


def suite():
    """Create test suite."""
    suite = unittest.TestSuite()

    # Add all test methods
    suite.addTest(unittest.makeSuite(TestSmartReprocessing))
    suite.addTest(unittest.makeSuite(TestSmartReprocessingIntegration))

    return suite


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite())

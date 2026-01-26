#!/usr/bin/env python3
"""
Unit Tests for Dependency Tracking (Phase 3 Pattern)

Tests the dependency checking and source tracking methods in AnalyticsProcessorBase.
This ensures Phase 3 processors correctly validate upstream Phase 2 data and track
source metadata (including hashes for smart reprocessing).

Key test areas:
- check_dependencies() - validates upstream data exists and is fresh
- _check_table_data() - queries BigQuery for dependency info
- track_source_usage() - populates source metadata and hash attributes
- build_source_tracking_fields() - builds output tracking fields
"""

import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from data_processors.analytics.analytics_base import AnalyticsProcessorBase


class MockAnalyticsProcessor(AnalyticsProcessorBase):
    """Mock analytics processor for testing dependency tracking."""

    def __init__(self):
        super().__init__()
        self.table_name = "test_analytics_table"
        self.dataset_id = "nba_analytics"

    def get_dependencies(self) -> dict:
        """Define test dependencies."""
        return {
            'nba_raw.test_source_1': {
                'field_prefix': 'source_test1',
                'description': 'Test source 1',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 100,
                'max_age_hours_warn': 24,
                'max_age_hours_fail': 72,
                'critical': True
            },
            'nba_raw.test_source_2': {
                'field_prefix': 'source_test2',
                'description': 'Test source 2',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 50,
                'max_age_hours_warn': 12,
                'max_age_hours_fail': 48,
                'critical': False
            },
            'nba_raw.test_reference_table': {
                'field_prefix': 'source_reference',
                'description': 'Reference table',
                'date_field': 'game_date',
                'check_type': 'existence',
                'expected_count_min': 1,
                'critical': False
            }
        }


class TestCheckDependencies(unittest.TestCase):
    """Test check_dependencies() method."""

    def setUp(self):
        """Set up test processor."""
        self.processor = MockAnalyticsProcessor()
        self.processor.bq_client = Mock()

    def test_check_dependencies_all_present_and_fresh(self):
        """Test when all dependencies exist and are fresh."""
        # Mock _check_table_data to return success for all dependencies
        def mock_check_table(table_name, start_date, end_date, config):
            return True, {
                'exists': True,
                'row_count': 150,
                'expected_count_min': config.get('expected_count_min', 1),
                'age_hours': 2.0,
                'last_updated': datetime.now(timezone.utc).isoformat(),
                'data_hash': 'test_hash_123'
            }

        self.processor._check_table_data = mock_check_table

        result = self.processor.check_dependencies('2024-11-20', '2024-11-20')

        # Verify success
        self.assertTrue(result['all_critical_present'])
        self.assertTrue(result['all_fresh'])
        self.assertFalse(result['has_stale_fail'])
        self.assertFalse(result['has_stale_warn'])
        self.assertEqual(len(result['missing']), 0)
        self.assertEqual(len(result['stale_fail']), 0)
        self.assertEqual(len(result['stale_warn']), 0)
        self.assertEqual(len(result['details']), 3)  # 3 dependencies

    def test_check_dependencies_missing_critical(self):
        """Test when critical dependency is missing."""
        # Mock first source missing, others present
        call_count = [0]
        def mock_check_table(table_name, start_date, end_date, config):
            call_count[0] += 1
            if call_count[0] == 1:  # First source missing
                return False, {
                    'exists': False,
                    'row_count': 0,
                    'data_hash': None,
                    'error': 'No data found'
                }
            else:  # Others present
                return True, {
                    'exists': True,
                    'row_count': 100,
                    'expected_count_min': 50,
                    'age_hours': 2.0,
                    'last_updated': datetime.now(timezone.utc).isoformat(),
                    'data_hash': 'test_hash'
                }

        self.processor._check_table_data = mock_check_table

        result = self.processor.check_dependencies('2024-11-20', '2024-11-20')

        # Verify failure
        self.assertFalse(result['all_critical_present'])
        self.assertEqual(len(result['missing']), 1)
        self.assertIn('nba_raw.test_source_1', result['missing'])

    def test_check_dependencies_missing_optional(self):
        """Test when optional dependency is missing."""
        # Mock second source (optional) missing, others present
        call_count = [0]
        def mock_check_table(table_name, start_date, end_date, config):
            call_count[0] += 1
            if call_count[0] == 2:  # Second source missing (optional)
                return False, {
                    'exists': False,
                    'row_count': 0,
                    'data_hash': None
                }
            else:  # Others present
                return True, {
                    'exists': True,
                    'row_count': 100,
                    'expected_count_min': 50,
                    'age_hours': 2.0,
                    'last_updated': datetime.now(timezone.utc).isoformat(),
                    'data_hash': 'test_hash'
                }

        self.processor._check_table_data = mock_check_table

        result = self.processor.check_dependencies('2024-11-20', '2024-11-20')

        # Verify optional missing doesn't fail critical check
        self.assertTrue(result['all_critical_present'])
        self.assertEqual(len(result['missing']), 0)  # Optional not in missing

    def test_check_dependencies_stale_fail_threshold(self):
        """Test when dependency exceeds FAIL age threshold."""
        # Mock stale data (80 hours old, fail threshold 72)
        def mock_check_table(table_name, start_date, end_date, config):
            return True, {
                'exists': True,
                'row_count': 100,
                'expected_count_min': 50,
                'age_hours': 80.0,  # Exceeds fail threshold
                'last_updated': (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat(),
                'data_hash': 'test_hash'
            }

        self.processor._check_table_data = mock_check_table

        result = self.processor.check_dependencies('2024-11-20', '2024-11-20')

        # Verify stale failure
        self.assertFalse(result['all_fresh'])
        self.assertTrue(result['has_stale_fail'])
        self.assertGreater(len(result['stale_fail']), 0)

    def test_check_dependencies_stale_warn_threshold(self):
        """Test when dependency exceeds WARN but not FAIL threshold."""
        # Mock stale data (30 hours old, warn=24, fail=72)
        def mock_check_table(table_name, start_date, end_date, config):
            return True, {
                'exists': True,
                'row_count': 100,
                'expected_count_min': 50,
                'age_hours': 30.0,  # Exceeds warn, not fail
                'last_updated': (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(),
                'data_hash': 'test_hash'
            }

        self.processor._check_table_data = mock_check_table

        result = self.processor.check_dependencies('2024-11-20', '2024-11-20')

        # Verify warning but not failure
        self.assertTrue(result['all_critical_present'])
        self.assertTrue(result['has_stale_warn'])
        self.assertFalse(result['has_stale_fail'])
        self.assertGreater(len(result['stale_warn']), 0)

    def test_check_dependencies_no_dependencies_defined(self):
        """Test when processor has no dependencies."""
        # Create processor without dependencies
        processor = AnalyticsProcessorBase()
        processor.bq_client = Mock()

        result = processor.check_dependencies('2024-11-20', '2024-11-20')

        # Verify success (no dependencies = always successful)
        self.assertTrue(result['all_critical_present'])
        self.assertTrue(result['all_fresh'])
        self.assertEqual(len(result['details']), 0)


class TestCheckTableData(unittest.TestCase):
    """Test _check_table_data() method."""

    def setUp(self):
        """Set up test processor."""
        self.processor = MockAnalyticsProcessor()
        self.processor.bq_client = Mock()
        self.processor.project_id = 'test-project'

    def test_check_table_data_date_range_exists(self):
        """Test checking table with date_range and data exists."""
        # Mock BigQuery response
        mock_row = Mock()
        mock_row.row_count = 150
        mock_row.last_updated = datetime.now(timezone.utc)
        mock_row.representative_hash = 'abc123def456'

        mock_job = Mock()
        mock_job.result.return_value = [mock_row]

        self.processor.bq_client.query.return_value = mock_job

        config = {
            'check_type': 'date_range',
            'date_field': 'game_date',
            'expected_count_min': 100
        }

        exists, details = self.processor._check_table_data(
            'nba_raw.test_table',
            '2024-11-20',
            '2024-11-20',
            config
        )

        # Verify success
        self.assertTrue(exists)
        self.assertEqual(details['row_count'], 150)
        self.assertEqual(details['data_hash'], 'abc123def456')
        self.assertIsNotNone(details['last_updated'])
        self.assertIsNotNone(details['age_hours'])
        self.assertEqual(details['expected_count_min'], 100)

    def test_check_table_data_below_minimum_count(self):
        """Test when row count below expected minimum."""
        # Mock BigQuery response with low count
        mock_row = Mock()
        mock_row.row_count = 50  # Below minimum
        mock_row.last_updated = datetime.now(timezone.utc)
        mock_row.representative_hash = 'abc123'

        mock_job = Mock()
        mock_job.result.return_value = [mock_row]

        self.processor.bq_client.query.return_value = mock_job

        config = {
            'check_type': 'date_range',
            'date_field': 'game_date',
            'expected_count_min': 100  # Expecting 100, only got 50
        }

        exists, details = self.processor._check_table_data(
            'nba_raw.test_table',
            '2024-11-20',
            '2024-11-20',
            config
        )

        # Verify LENIENT behavior - exists=True (data present) but sufficient=False
        self.assertTrue(exists)  # LENIENT: any data = exists
        self.assertFalse(details['sufficient'])  # Below minimum
        self.assertEqual(details['row_count'], 50)
        self.assertEqual(details['expected_count_min'], 100)

    def test_check_table_data_existence_check(self):
        """Test checking table with existence check type."""
        # Mock BigQuery response
        mock_row = Mock()
        mock_row.row_count = 10
        mock_row.last_updated = datetime.now(timezone.utc)
        mock_row.representative_hash = 'abc123'

        mock_job = Mock()
        mock_job.result.return_value = [mock_row]

        self.processor.bq_client.query.return_value = mock_job

        config = {
            'check_type': 'existence',
            'expected_count_min': 1
        }

        exists, details = self.processor._check_table_data(
            'nba_raw.test_reference',
            '2024-11-20',
            '2024-11-20',
            config
        )

        # Verify success
        self.assertTrue(exists)
        self.assertEqual(details['row_count'], 10)

    def test_check_table_data_no_results(self):
        """Test when BigQuery returns no results."""
        # Mock empty BigQuery response
        mock_job = Mock()
        mock_job.result.return_value = []

        self.processor.bq_client.query.return_value = mock_job

        config = {
            'check_type': 'date_range',
            'date_field': 'game_date',
            'expected_count_min': 1
        }

        exists, details = self.processor._check_table_data(
            'nba_raw.test_table',
            '2024-11-20',
            '2024-11-20',
            config
        )

        # Verify failure
        self.assertFalse(exists)
        self.assertIn('error', details)
        self.assertEqual(details['row_count'], 0)

    def test_check_table_data_hash_extraction(self):
        """Test that data_hash is extracted correctly."""
        # Mock BigQuery response with hash
        mock_row = Mock()
        mock_row.row_count = 100
        mock_row.last_updated = datetime.now(timezone.utc)
        mock_row.representative_hash = 'test_hash_value'

        mock_job = Mock()
        mock_job.result.return_value = [mock_row]

        self.processor.bq_client.query.return_value = mock_job

        config = {
            'check_type': 'date_range',
            'date_field': 'game_date',
            'expected_count_min': 50
        }

        exists, details = self.processor._check_table_data(
            'nba_raw.test_table',
            '2024-11-20',
            '2024-11-20',
            config
        )

        # Verify hash extracted
        self.assertTrue(exists)
        self.assertEqual(details['data_hash'], 'test_hash_value')

    def test_check_table_data_query_error(self):
        """Test error handling when BigQuery query fails."""
        # Mock BigQuery error - need to import GoogleAPIError
        from google.api_core.exceptions import GoogleAPIError

        # Create a proper GoogleAPIError
        mock_error = GoogleAPIError("Query failed")
        self.processor.bq_client.query.side_effect = mock_error

        config = {
            'check_type': 'date_range',
            'date_field': 'game_date',
            'expected_count_min': 1
        }

        exists, details = self.processor._check_table_data(
            'nba_raw.test_table',
            '2024-11-20',
            '2024-11-20',
            config
        )

        # Verify failure
        self.assertFalse(exists)
        self.assertIn('error', details)
        self.assertIsNone(details['data_hash'])

    def test_check_table_data_age_calculation(self):
        """Test age calculation for different timezone scenarios."""
        # Mock BigQuery response with timezone-aware datetime
        last_updated = datetime.now(timezone.utc) - timedelta(hours=5)
        mock_row = Mock()
        mock_row.row_count = 100
        mock_row.last_updated = last_updated
        mock_row.representative_hash = 'abc123'

        mock_job = Mock()
        mock_job.result.return_value = [mock_row]

        self.processor.bq_client.query.return_value = mock_job

        config = {
            'check_type': 'date_range',
            'date_field': 'game_date',
            'expected_count_min': 50
        }

        exists, details = self.processor._check_table_data(
            'nba_raw.test_table',
            '2024-11-20',
            '2024-11-20',
            config
        )

        # Verify age calculated (approximately 5 hours)
        self.assertTrue(exists)
        self.assertIsNotNone(details['age_hours'])
        self.assertAlmostEqual(details['age_hours'], 5.0, delta=0.5)


class TestTrackSourceUsage(unittest.TestCase):
    """Test track_source_usage() method."""

    def setUp(self):
        """Set up test processor."""
        self.processor = MockAnalyticsProcessor()

    def test_track_source_usage_all_present(self):
        """Test tracking when all sources present."""
        dep_check = {
            'details': {
                'nba_raw.test_source_1': {
                    'exists': True,
                    'row_count': 150,
                    'expected_count_min': 100,
                    'age_hours': 2.5,
                    'last_updated': '2024-11-20T12:00:00',
                    'data_hash': 'hash_source1'
                },
                'nba_raw.test_source_2': {
                    'exists': True,
                    'row_count': 75,
                    'expected_count_min': 50,
                    'age_hours': 1.0,
                    'last_updated': '2024-11-20T13:00:00',
                    'data_hash': 'hash_source2'
                },
                'nba_raw.test_reference_table': {
                    'exists': True,
                    'row_count': 10,
                    'expected_count_min': 1,
                    'age_hours': 0.5,
                    'last_updated': '2024-11-20T14:00:00',
                    'data_hash': 'hash_reference'
                }
            }
        }

        self.processor.track_source_usage(dep_check)

        # Verify attributes set for source 1
        self.assertEqual(self.processor.source_test1_last_updated, '2024-11-20T12:00:00')
        self.assertEqual(self.processor.source_test1_rows_found, 150)
        self.assertEqual(self.processor.source_test1_completeness_pct, 100.0)  # 150/100 = 150%, capped at 100
        self.assertEqual(self.processor.source_test1_hash, 'hash_source1')

        # Verify attributes set for source 2
        self.assertEqual(self.processor.source_test2_last_updated, '2024-11-20T13:00:00')
        self.assertEqual(self.processor.source_test2_rows_found, 75)
        self.assertEqual(self.processor.source_test2_completeness_pct, 100.0)  # 75/50 = 150%, capped
        self.assertEqual(self.processor.source_test2_hash, 'hash_source2')

        # Verify metadata dict
        self.assertEqual(len(self.processor.source_metadata), 3)
        self.assertIn('nba_raw.test_source_1', self.processor.source_metadata)

    def test_track_source_usage_completeness_calculation(self):
        """Test completeness percentage calculation."""
        dep_check = {
            'details': {
                'nba_raw.test_source_1': {
                    'exists': True,
                    'row_count': 75,  # 75% of expected
                    'expected_count_min': 100,
                    'age_hours': 2.0,
                    'last_updated': '2024-11-20T12:00:00',
                    'data_hash': 'hash_123'
                }
            }
        }

        self.processor.track_source_usage(dep_check)

        # Verify completeness (75/100 = 75%)
        self.assertEqual(self.processor.source_test1_completeness_pct, 75.0)

    def test_track_source_usage_missing_source(self):
        """Test tracking when source is missing."""
        dep_check = {
            'details': {
                'nba_raw.test_source_1': {
                    'exists': False,
                    'row_count': 0,
                    'data_hash': None
                }
            }
        }

        self.processor.track_source_usage(dep_check)

        # Verify all fields set to None
        self.assertIsNone(self.processor.source_test1_last_updated)
        self.assertIsNone(self.processor.source_test1_rows_found)
        self.assertIsNone(self.processor.source_test1_completeness_pct)
        self.assertIsNone(self.processor.source_test1_hash)

    def test_track_source_usage_hash_extraction(self):
        """Test that data_hash is extracted and stored."""
        dep_check = {
            'details': {
                'nba_raw.test_source_1': {
                    'exists': True,
                    'row_count': 100,
                    'expected_count_min': 100,
                    'age_hours': 2.0,
                    'last_updated': '2024-11-20T12:00:00',
                    'data_hash': 'abc123def456'  # Hash from Phase 2
                }
            }
        }

        self.processor.track_source_usage(dep_check)

        # Verify hash stored as attribute
        self.assertEqual(self.processor.source_test1_hash, 'abc123def456')

        # Verify hash in metadata
        self.assertEqual(self.processor.source_metadata['nba_raw.test_source_1']['data_hash'], 'abc123def456')


class TestBuildSourceTrackingFields(unittest.TestCase):
    """Test build_source_tracking_fields() method."""

    def setUp(self):
        """Set up test processor."""
        self.processor = MockAnalyticsProcessor()

    def test_build_source_tracking_fields_all_set(self):
        """Test building fields when all attributes set."""
        # Set attributes manually
        self.processor.source_test1_last_updated = '2024-11-20T12:00:00'
        self.processor.source_test1_rows_found = 150
        self.processor.source_test1_completeness_pct = 100.0
        self.processor.source_test1_hash = 'hash_test1'

        self.processor.source_test2_last_updated = '2024-11-20T13:00:00'
        self.processor.source_test2_rows_found = 75
        self.processor.source_test2_completeness_pct = 75.0
        self.processor.source_test2_hash = 'hash_test2'

        fields = self.processor.build_source_tracking_fields()

        # Verify all fields present (4 fields per source)
        self.assertEqual(fields['source_test1_last_updated'], '2024-11-20T12:00:00')
        self.assertEqual(fields['source_test1_rows_found'], 150)
        self.assertEqual(fields['source_test1_completeness_pct'], 100.0)
        self.assertEqual(fields['source_test1_hash'], 'hash_test1')

        self.assertEqual(fields['source_test2_last_updated'], '2024-11-20T13:00:00')
        self.assertEqual(fields['source_test2_rows_found'], 75)
        self.assertEqual(fields['source_test2_completeness_pct'], 75.0)
        self.assertEqual(fields['source_test2_hash'], 'hash_test2')

        # Verify count (3 sources × 4 fields = 12)
        self.assertEqual(len(fields), 12)

    def test_build_source_tracking_fields_with_none(self):
        """Test building fields when some attributes are None."""
        # Set some attributes to None (missing source)
        self.processor.source_test1_last_updated = None
        self.processor.source_test1_rows_found = None
        self.processor.source_test1_completeness_pct = None
        self.processor.source_test1_hash = None

        fields = self.processor.build_source_tracking_fields()

        # Verify None fields included
        self.assertIn('source_test1_last_updated', fields)
        self.assertIsNone(fields['source_test1_last_updated'])
        self.assertIsNone(fields['source_test1_hash'])

    def test_build_source_tracking_fields_no_dependencies(self):
        """Test building fields when processor has no dependencies."""
        # Create processor without dependencies
        processor = AnalyticsProcessorBase()

        fields = processor.build_source_tracking_fields()

        # Verify empty dict
        self.assertEqual(len(fields), 0)

    def test_build_source_tracking_fields_includes_hash(self):
        """Test that hash field is included in output."""
        # Set hash attribute
        self.processor.source_test1_hash = 'test_hash_value'
        self.processor.source_test1_last_updated = '2024-11-20T12:00:00'
        self.processor.source_test1_rows_found = 100
        self.processor.source_test1_completeness_pct = 100.0

        fields = self.processor.build_source_tracking_fields()

        # Verify hash field present
        self.assertIn('source_test1_hash', fields)
        self.assertEqual(fields['source_test1_hash'], 'test_hash_value')


class TestDependencyTrackingIntegration(unittest.TestCase):
    """Test integration between dependency methods."""

    def setUp(self):
        """Set up test processor."""
        self.processor = MockAnalyticsProcessor()
        self.processor.bq_client = Mock()

    def test_full_dependency_flow(self):
        """Test full flow: check_dependencies → track_source_usage → build_fields."""
        # Mock _check_table_data
        def mock_check_table(table_name, start_date, end_date, config):
            return True, {
                'exists': True,
                'row_count': 100,
                'expected_count_min': 50,
                'age_hours': 2.0,
                'last_updated': '2024-11-20T12:00:00',
                'data_hash': f'hash_{table_name}'
            }

        self.processor._check_table_data = mock_check_table

        # Step 1: Check dependencies
        dep_check = self.processor.check_dependencies('2024-11-20', '2024-11-20')

        # Step 2: Track source usage
        self.processor.track_source_usage(dep_check)

        # Step 3: Build tracking fields
        fields = self.processor.build_source_tracking_fields()

        # Verify flow worked
        self.assertTrue(dep_check['all_critical_present'])
        self.assertEqual(len(fields), 12)  # 3 sources × 4 fields
        self.assertIn('source_test1_hash', fields)
        self.assertIsNotNone(fields['source_test1_hash'])


def suite():
    """Create test suite."""
    suite = unittest.TestSuite()

    suite.addTest(unittest.makeSuite(TestCheckDependencies))
    suite.addTest(unittest.makeSuite(TestCheckTableData))
    suite.addTest(unittest.makeSuite(TestTrackSourceUsage))
    suite.addTest(unittest.makeSuite(TestBuildSourceTrackingFields))
    suite.addTest(unittest.makeSuite(TestDependencyTrackingIntegration))

    return suite


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite())

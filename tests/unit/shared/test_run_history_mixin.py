"""
Unit tests for RunHistoryMixin deduplication functionality.

Tests:
- Immediate 'running' status write
- Deduplication check logic
- Stale run detection
"""

import pytest
from datetime import datetime, timezone, timedelta, date
from unittest.mock import Mock, patch, MagicMock

# This will need to be adjusted based on actual import path
from shared.processors.mixins.run_history_mixin import RunHistoryMixin


class MockTestProcessor(RunHistoryMixin):
    """Test processor for RunHistoryMixin testing."""

    PHASE = 'phase_test'
    OUTPUT_TABLE = 'test_table'
    OUTPUT_DATASET = 'test_dataset'

    def __init__(self):
        self.project_id = 'test-project'
        self.bq_client = Mock()  # Will be configured in tests


class TestRunHistoryMixinImmediateWrite:
    """Test immediate 'running' status write on start_run_tracking()."""

    def test_start_run_tracking_writes_running_status(self):
        """Test that start_run_tracking() writes 'running' status immediately."""
        processor = MockTestProcessor()

        # Mock the insert method
        processor._insert_run_history = Mock()

        # Start tracking
        run_id = processor.start_run_tracking(
            data_date='2025-11-28',
            trigger_source='pubsub'
        )

        # Verify insert was called
        assert processor._insert_run_history.called
        call_args = processor._insert_run_history.call_args[0][0]

        # Verify record has 'running' status
        assert call_args['status'] == 'running'
        assert call_args['processor_name'] == 'MockTestProcessor'
        assert call_args['data_date'] == '2025-11-28'
        assert 'run_id' in call_args
        assert 'started_at' in call_args

    def test_start_run_tracking_handles_insert_failure_gracefully(self):
        """Test that insert failure doesn't crash processor."""
        processor = MockTestProcessor()

        # Mock insert to raise exception
        processor._insert_run_history = Mock(side_effect=Exception("BigQuery error"))

        # Should not raise - just log warning
        run_id = processor.start_run_tracking(data_date='2025-11-28')

        # Verify it returned a run_id despite failure
        assert run_id is not None


class TestRunHistoryMixinDeduplication:
    """Test deduplication check functionality."""

    def test_check_already_processed_returns_false_when_no_history(self):
        """Test returns False when no previous run exists."""
        processor = MockTestProcessor()

        # Configure the processor's bq_client mock
        processor.bq_client.project = 'test-project'

        # Create proper mock chain: query() returns object with result() method
        mock_query_result = Mock()
        mock_query_result.result = Mock(return_value=[])  # Empty list
        processor.bq_client.query = Mock(return_value=mock_query_result)

        result = processor.check_already_processed(
            processor_name='TestProcessor',
            data_date='2025-11-28'
        )

        assert result is False  # Should allow processing

    def test_check_already_processed_returns_true_for_success_status(self):
        """Test returns True when status='success' exists."""
        processor = MockTestProcessor()

        # Mock BigQuery to return success status
        mock_row = Mock()
        mock_row.status = 'success'
        mock_row.run_id = 'test-run-123'

        # Configure the processor's bq_client mock
        processor.bq_client.project = 'test-project'

        # Create proper mock chain: query() returns object with result() method
        mock_query_result = Mock()
        mock_query_result.result = Mock(return_value=[mock_row])
        processor.bq_client.query = Mock(return_value=mock_query_result)

        result = processor.check_already_processed(
            processor_name='TestProcessor',
            data_date='2025-11-28'
        )

        assert result is True  # Should skip - already processed

    def test_check_already_processed_handles_stale_running_status(self):
        """Test returns False for stale 'running' status (> 2 hours)."""
        processor = MockTestProcessor()

        # Mock BigQuery to return stale 'running' status
        mock_row = Mock()
        mock_row.status = 'running'
        mock_row.started_at = datetime.now(timezone.utc) - timedelta(hours=3)  # 3 hours ago
        mock_row.run_id = 'test-run-123'

        # Configure the processor's bq_client mock
        processor.bq_client.project = 'test-project'

        # Create proper mock chain: query() returns object with result() method
        mock_query_result = Mock()
        mock_query_result.result = Mock(return_value=[mock_row])
        processor.bq_client.query = Mock(return_value=mock_query_result)

        result = processor.check_already_processed(
            processor_name='TestProcessor',
            data_date='2025-11-28',
            stale_threshold_hours=2
        )

        assert result is False  # Should allow retry - stale

    def test_check_already_processed_handles_recent_running_status(self):
        """Test returns True for recent 'running' status (< 2 hours)."""
        processor = MockTestProcessor()

        # Mock BigQuery to return recent 'running' status
        mock_row = Mock()
        mock_row.status = 'running'
        mock_row.started_at = datetime.now(timezone.utc) - timedelta(minutes=30)  # 30 min ago
        mock_row.run_id = 'test-run-123'

        # Configure the processor's bq_client mock
        processor.bq_client.project = 'test-project'

        # Create proper mock chain: query() returns object with result() method
        mock_query_result = Mock()
        mock_query_result.result = Mock(return_value=[mock_row])
        processor.bq_client.query = Mock(return_value=mock_query_result)

        result = processor.check_already_processed(
            processor_name='TestProcessor',
            data_date='2025-11-28',
            stale_threshold_hours=2
        )

        assert result is True  # Should skip - currently running

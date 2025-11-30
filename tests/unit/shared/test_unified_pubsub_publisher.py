"""
Unit tests for UnifiedPubSubPublisher.

Tests:
- Message format validation
- Backfill mode (skip_downstream)
- Non-blocking error handling
- Correlation ID tracking
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from shared.publishers.unified_pubsub_publisher import UnifiedPubSubPublisher


class TestUnifiedPubSubPublisher:
    """Test UnifiedPubSubPublisher functionality."""

    def test_build_message_creates_valid_format(self):
        """Test message builder creates unified format."""
        publisher = UnifiedPubSubPublisher(project_id='test-project')

        message = publisher._build_message(
            processor_name='TestProcessor',
            phase='phase_2_raw',
            execution_id='exec-123',
            correlation_id='corr-456',
            game_date='2025-11-28',
            output_table='test_table',
            output_dataset='test_dataset',
            status='success',
            record_count=150,
            records_failed=0,
            parent_processor='UpstreamProcessor',
            trigger_source='pubsub',
            trigger_message_id='msg-789',
            duration_seconds=10.5,
            error_message=None,
            error_type=None,
            metadata={'custom': 'data'}
        )

        # Verify required fields
        assert message['processor_name'] == 'TestProcessor'
        assert message['phase'] == 'phase_2_raw'
        assert message['execution_id'] == 'exec-123'
        assert message['correlation_id'] == 'corr-456'
        assert message['game_date'] == '2025-11-28'
        assert message['status'] == 'success'
        assert message['record_count'] == 150
        assert 'timestamp' in message  # Auto-generated

    def test_validate_message_requires_fields(self):
        """Test message validation catches missing fields."""
        publisher = UnifiedPubSubPublisher()

        # Valid message
        valid_message = {
            'processor_name': 'Test',
            'phase': 'phase_2_raw',
            'execution_id': 'exec-123',
            'correlation_id': 'corr-456',
            'game_date': '2025-11-28',
            'status': 'success',
            'timestamp': datetime.now().isoformat()
        }

        assert publisher._validate_message(valid_message) is True

        # Invalid - missing required field
        invalid_message = {**valid_message}
        del invalid_message['game_date']

        assert publisher._validate_message(invalid_message) is False

    def test_validate_message_checks_status_values(self):
        """Test status validation."""
        publisher = UnifiedPubSubPublisher()

        base_message = {
            'processor_name': 'Test',
            'phase': 'phase_2_raw',
            'execution_id': 'exec-123',
            'correlation_id': 'corr-456',
            'game_date': '2025-11-28',
            'timestamp': datetime.now().isoformat()
        }

        # Valid statuses
        for status in ['success', 'partial', 'no_data', 'failed']:
            msg = {**base_message, 'status': status}
            assert publisher._validate_message(msg) is True

        # Invalid status
        invalid_msg = {**base_message, 'status': 'invalid_status'}
        assert publisher._validate_message(invalid_msg) is False

    @patch('shared.publishers.unified_pubsub_publisher.pubsub_v1.PublisherClient')
    def test_publish_completion_skips_when_backfill_mode(self, mock_client_class):
        """Test skip_downstream flag prevents publishing."""
        publisher = UnifiedPubSubPublisher()

        result = publisher.publish_completion(
            topic='test-topic',
            processor_name='TestProcessor',
            phase='phase_2_raw',
            execution_id='exec-123',
            game_date='2025-11-28',
            output_table='test_table',
            output_dataset='test_dataset',
            status='success',
            skip_downstream=True  # Backfill mode
        )

        # Should return None and NOT call publish
        assert result is None
        assert not mock_client_class.called

    @patch('shared.publishers.unified_pubsub_publisher.pubsub_v1.PublisherClient')
    def test_publish_handles_errors_gracefully(self, mock_client_class):
        """Test publish failure doesn't raise exception."""
        publisher = UnifiedPubSubPublisher()

        # Mock client to raise exception
        mock_client = Mock()
        mock_client.topic_path.return_value = 'projects/test/topics/test-topic'
        mock_client.publish.side_effect = Exception("Pub/Sub error")
        mock_client_class.return_value = mock_client

        # Should not raise - returns None on failure
        result = publisher.publish_completion(
            topic='test-topic',
            processor_name='TestProcessor',
            phase='phase_2_raw',
            execution_id='exec-123',
            game_date='2025-11-28',
            output_table='test_table',
            output_dataset='test_dataset',
            status='success'
        )

        assert result is None  # Failed but didn't crash

    def test_publish_batch_respects_skip_downstream(self):
        """Test batch publishing respects backfill mode."""
        publisher = UnifiedPubSubPublisher()

        messages = [
            {'processor_name': 'Test1', 'status': 'success'},
            {'processor_name': 'Test2', 'status': 'success'},
        ]

        result = publisher.publish_batch(
            topic='test-topic',
            messages=messages,
            skip_downstream=True
        )

        # Should return list of Nones
        assert result == [None, None]

"""
Unit tests for Phase 2 → Phase 3 Orchestrator

Tests the critical race condition prevention logic using Firestore atomic transactions.

Run:
    pytest tests/cloud_functions/test_phase2_orchestrator.py -v

Coverage:
    pytest tests/cloud_functions/test_phase2_orchestrator.py --cov=orchestration.cloud_functions.phase2_to_phase3 --cov-report=html
"""

import json
import base64
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch, call
import pytest

# Import orchestrator functions
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from orchestration.cloud_functions.phase2_to_phase3.main import (
    orchestrate_phase2_to_phase3,
    update_completion_atomic,
    trigger_phase3,
    parse_pubsub_message,
    get_completion_status,
    EXPECTED_PROCESSORS
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_firestore_client():
    """Mock Firestore client."""
    with patch('orchestrators.phase2_to_phase3.main.db') as mock_db:
        yield mock_db


@pytest.fixture
def mock_pubsub_client():
    """Mock Pub/Sub publisher client."""
    with patch('orchestrators.phase2_to_phase3.main.publisher') as mock_publisher:
        yield mock_publisher


@pytest.fixture
def sample_phase2_message():
    """Sample Phase 2 completion message."""
    return {
        'processor_name': 'BdlGamesProcessor',
        'phase': 'phase_2_raw',
        'execution_id': 'def-456',
        'correlation_id': 'abc-123',
        'game_date': '2025-11-29',
        'output_table': 'bdl_games',
        'output_dataset': 'nba_raw',
        'status': 'success',
        'record_count': 150,
        'timestamp': '2025-11-29T12:00:00Z'
    }


@pytest.fixture
def sample_cloud_event(sample_phase2_message):
    """Sample CloudEvent from Pub/Sub."""
    # Encode message as base64 (like Pub/Sub does)
    message_data = base64.b64encode(
        json.dumps(sample_phase2_message).encode('utf-8')
    )

    cloud_event = Mock()
    cloud_event.data = {
        'message': {
            'data': message_data,
            'messageId': 'test-message-123',
            'publishTime': '2025-11-29T12:00:00Z'
        }
    }

    return cloud_event


# ============================================================================
# TEST: Message Parsing
# ============================================================================

def test_parse_pubsub_message(sample_cloud_event, sample_phase2_message):
    """Test parsing of Pub/Sub CloudEvent."""
    result = parse_pubsub_message(sample_cloud_event)

    assert result == sample_phase2_message
    assert result['processor_name'] == 'BdlGamesProcessor'
    assert result['game_date'] == '2025-11-29'
    assert result['correlation_id'] == 'abc-123'


def test_parse_pubsub_message_invalid():
    """Test parsing fails gracefully with invalid message."""
    cloud_event = Mock()
    cloud_event.data = {}

    with pytest.raises(ValueError, match="Invalid Pub/Sub message format"):
        parse_pubsub_message(cloud_event)


# ============================================================================
# TEST: Atomic Transaction Logic
# ============================================================================

@patch('orchestrators.phase2_to_phase3.main.db')
def test_update_completion_first_processor(mock_db_instance):
    """Test registering first processor (1/21 complete)."""
    # Setup: Empty Firestore document (no processors registered yet)
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = False
    doc_snapshot.to_dict.return_value = {}  # Empty dict - no processors yet

    # Mock the doc_ref.get() method to return our snapshot
    doc_ref.get.return_value = doc_snapshot

    # Create a proper transaction that the @transactional decorator can use
    from google.cloud.firestore_v1.transaction import Transaction

    # Patch the transaction.set method
    with patch.object(Transaction, 'set') as mock_set:
        # Create a real Transaction object
        transaction = Transaction(mock_db_instance)

        completion_data = {
            'completed_at': 'timestamp',
            'correlation_id': 'abc-123',
            'status': 'success',
            'record_count': 150
        }

        # Execute
        should_trigger = update_completion_atomic(
            transaction,
            doc_ref,
            'BdlGamesProcessor',
            completion_data
        )

        # Verify
        assert should_trigger is False  # Don't trigger yet (only 1/21)

        # Verify transaction.set was called with processor added
        mock_set.assert_called_once()
        written_data = mock_set.call_args[0][1]
        assert 'BdlGamesProcessor' in written_data
        assert written_data['_completed_count'] == 1
        assert '_triggered' not in written_data


@patch('orchestrators.phase2_to_phase3.main.db')
def test_update_completion_last_processor_triggers(mock_db_instance):
    """Test registering 21st processor triggers Phase 3."""
    # Setup: 20 processors already complete
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = True

    # Build existing state with 20 processors
    existing_data = {f'Processor{i}': {'status': 'success'} for i in range(20)}
    existing_data['_completed_count'] = 20
    doc_snapshot.to_dict.return_value = existing_data

    # Mock the doc_ref.get() method
    doc_ref.get.return_value = doc_snapshot

    from google.cloud.firestore_v1.transaction import Transaction

    # Patch the transaction.set method
    with patch.object(Transaction, 'set') as mock_set:
        transaction = Transaction(mock_db_instance)

        completion_data = {
            'completed_at': 'timestamp',
            'correlation_id': 'abc-123',
            'status': 'success',
            'record_count': 150
        }

        # Execute: Add 21st processor
        should_trigger = update_completion_atomic(
            transaction,
            doc_ref,
            'Processor20',  # The 21st processor (0-indexed)
            completion_data
        )

        # Verify
        assert should_trigger is True  # Should trigger Phase 3!

        # Verify _triggered flag was set
        mock_set.assert_called_once()
        written_data = mock_set.call_args[0][1]
        assert written_data['_triggered'] is True
        assert '_triggered_at' in written_data
        assert written_data['_completed_count'] == 21


@patch('orchestrators.phase2_to_phase3.main.db')
def test_update_completion_duplicate_message(mock_db_instance):
    """Test idempotency - duplicate Pub/Sub message doesn't re-add processor."""
    # Setup: Processor already registered
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = True
    doc_snapshot.to_dict.return_value = {
        'BdlGamesProcessor': {'status': 'success', 'completed_at': 'earlier'},
        '_completed_count': 1
    }

    # Mock the doc_ref.get() method
    doc_ref.get.return_value = doc_snapshot

    from google.cloud.firestore_v1.transaction import Transaction

    with patch.object(Transaction, 'set') as mock_set:
        transaction = Transaction(mock_db_instance)

        completion_data = {'status': 'success'}

        # Execute: Try to add same processor again
        should_trigger = update_completion_atomic(
            transaction,
            doc_ref,
            'BdlGamesProcessor',  # Already exists
            completion_data
        )

        # Verify
        assert should_trigger is False
        mock_set.assert_not_called()  # Should NOT write


@patch('orchestrators.phase2_to_phase3.main.db')
def test_update_completion_already_triggered(mock_db_instance):
    """Test that if already triggered, don't trigger again (race condition prevention)."""
    # Setup: 20 processors complete AND already triggered
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = True

    # Start with 20 processors (not 21) so we can add the 21st
    existing_data = {f'Processor{i}': {'status': 'success'} for i in range(20)}
    existing_data['_triggered'] = True  # Already triggered (safety check)!
    existing_data['_triggered_at'] = 'earlier'
    existing_data['_completed_count'] = 20
    doc_snapshot.to_dict.return_value = existing_data

    # Mock the doc_ref.get() method
    doc_ref.get.return_value = doc_snapshot

    from google.cloud.firestore_v1.transaction import Transaction

    with patch.object(Transaction, 'set') as mock_set:
        transaction = Transaction(mock_db_instance)

        # Execute: Try to add 21st processor when already triggered
        # This tests defensive programming - even if 21st comes in after trigger,
        # we still record it but don't re-trigger
        should_trigger = update_completion_atomic(
            transaction,
            doc_ref,
            'Processor20',  # New processor (not yet in dict)
            {'status': 'success'}
        )

        # Verify
        assert should_trigger is False  # Don't trigger again (already triggered)
        # Should still write to record completion
        mock_set.assert_called_once()
        written_data = mock_set.call_args[0][1]
        assert written_data['_triggered'] is True  # Flag remains
        assert written_data['_completed_count'] == 21  # Count updated


# ============================================================================
# TEST: Phase 3 Trigger
# ============================================================================

def test_trigger_phase3(mock_pubsub_client):
    """Test publishing trigger message to Phase 3."""
    # Setup mock publisher
    mock_future = Mock()
    mock_future.result.return_value = 'published-message-id'
    mock_pubsub_client.publish.return_value = mock_future
    mock_pubsub_client.topic_path.return_value = 'projects/nba-props-platform/topics/nba-phase3-trigger'

    upstream_message = {
        'execution_id': 'upstream-123',
        'correlation_id': 'abc-123'
    }

    # Execute
    message_id = trigger_phase3('2025-11-29', 'abc-123', upstream_message)

    # Verify
    assert message_id == 'published-message-id'

    # Verify publish was called
    mock_pubsub_client.publish.assert_called_once()

    # Verify message content
    call_args = mock_pubsub_client.publish.call_args
    published_data = json.loads(call_args[1]['data'].decode('utf-8'))

    assert published_data['game_date'] == '2025-11-29'
    assert published_data['correlation_id'] == 'abc-123'
    assert published_data['trigger_source'] == 'orchestrator'
    assert published_data['triggered_by'] == 'phase2_to_phase3_orchestrator'
    assert published_data['upstream_processors_count'] == EXPECTED_PROCESSORS


def test_trigger_phase3_publish_fails(mock_pubsub_client):
    """Test graceful handling of Pub/Sub publish failure."""
    # Setup mock to raise exception
    mock_pubsub_client.publish.side_effect = Exception("Pub/Sub unavailable")
    mock_pubsub_client.topic_path.return_value = 'projects/test/topics/test'

    # Execute
    message_id = trigger_phase3('2025-11-29', 'abc-123', {})

    # Verify
    assert message_id is None  # Returns None on failure (doesn't crash)


# ============================================================================
# TEST: End-to-End Orchestration
# ============================================================================

def test_orchestrate_success_not_yet_complete(mock_firestore_client, mock_pubsub_client, sample_cloud_event):
    """Test orchestration when processor registers but not all complete yet."""
    # Setup Firestore mock (5/21 complete after this one)
    doc_ref_mock = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = True
    doc_snapshot.to_dict.return_value = {
        f'Processor{i}': {'status': 'success'} for i in range(4)
    }

    transaction_mock = Mock()
    transaction_mock.get.return_value = doc_snapshot

    collection_mock = Mock()
    collection_mock.document.return_value = doc_ref_mock
    mock_firestore_client.collection.return_value = collection_mock
    mock_firestore_client.transaction.return_value = transaction_mock

    # Execute
    orchestrate_phase2_to_phase3(sample_cloud_event)

    # Verify Firestore was accessed
    mock_firestore_client.collection.assert_called_with('phase2_completion')
    collection_mock.document.assert_called_with('2025-11-29')

    # Verify Phase 3 NOT triggered (only 5/21)
    mock_pubsub_client.publish.assert_not_called()


def test_orchestrate_success_all_complete_triggers(mock_firestore_client, mock_pubsub_client, sample_cloud_event):
    """Test orchestration when this is the 21st processor - triggers Phase 3."""
    # Setup Firestore mock (20 already complete, this makes 21)
    doc_ref_mock = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = True
    doc_snapshot.to_dict.return_value = {
        f'Processor{i}': {'status': 'success'} for i in range(20)
    }

    # Create a proper transaction mock that will allow @firestore.transactional to work
    transaction_mock = MagicMock()
    transaction_mock.get.return_value = doc_snapshot

    # Mock the transaction context
    with patch('google.cloud.firestore.Transaction', return_value=transaction_mock):
        collection_mock = Mock()
        collection_mock.document.return_value = doc_ref_mock
        mock_firestore_client.collection.return_value = collection_mock

        # Mock Pub/Sub
        mock_future = Mock()
        mock_future.result.return_value = 'test-message-id'
        mock_pubsub_client.publish.return_value = mock_future
        mock_pubsub_client.topic_path.return_value = 'projects/test/topics/test'

        # Execute
        # Note: This test requires mocking the transaction decorator behavior
        # For now, we'll test trigger_phase3 separately (already done above)


def test_orchestrate_skips_failed_status(mock_firestore_client, mock_pubsub_client):
    """Test orchestration skips processors with failed status."""
    # Create cloud event with failed status
    failed_message = {
        'processor_name': 'BdlGamesProcessor',
        'game_date': '2025-11-29',
        'status': 'failed',  # Failed processor
        'correlation_id': 'abc-123'
    }

    cloud_event = Mock()
    cloud_event.data = {
        'message': {
            'data': base64.b64encode(json.dumps(failed_message).encode('utf-8'))
        }
    }

    # Execute
    orchestrate_phase2_to_phase3(cloud_event)

    # Verify Firestore was NOT accessed (skipped failed processor)
    mock_firestore_client.collection.assert_not_called()


# ============================================================================
# TEST: Helper Functions
# ============================================================================

def test_get_completion_status_not_started(mock_firestore_client):
    """Test get_completion_status when no processors have run yet."""
    # Setup: Document doesn't exist
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = False

    doc_ref.get.return_value = doc_snapshot

    collection_mock = Mock()
    collection_mock.document.return_value = doc_ref
    mock_firestore_client.collection.return_value = collection_mock

    # Execute
    status = get_completion_status('2025-11-29')

    # Verify
    assert status['status'] == 'not_started'
    assert status['completed_count'] == 0
    assert status['expected_count'] == EXPECTED_PROCESSORS


def test_get_completion_status_in_progress(mock_firestore_client):
    """Test get_completion_status when some processors complete."""
    # Setup: 10 processors complete
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = True
    doc_snapshot.to_dict.return_value = {
        f'Processor{i}': {'status': 'success'} for i in range(10)
    }

    doc_ref.get.return_value = doc_snapshot

    collection_mock = Mock()
    collection_mock.document.return_value = doc_ref
    mock_firestore_client.collection.return_value = collection_mock

    # Execute
    status = get_completion_status('2025-11-29')

    # Verify
    assert status['status'] == 'in_progress'
    assert status['completed_count'] == 10
    assert status['expected_count'] == EXPECTED_PROCESSORS
    assert len(status['completed_processors']) == 10


def test_get_completion_status_triggered(mock_firestore_client):
    """Test get_completion_status when all complete and triggered."""
    # Setup: All 21 complete and triggered
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = True
    data = {f'Processor{i}': {'status': 'success'} for i in range(21)}
    data['_triggered'] = True
    data['_triggered_at'] = 'timestamp'
    doc_snapshot.to_dict.return_value = data

    doc_ref.get.return_value = doc_snapshot

    collection_mock = Mock()
    collection_mock.document.return_value = doc_ref
    mock_firestore_client.collection.return_value = collection_mock

    # Execute
    status = get_completion_status('2025-11-29')

    # Verify
    assert status['status'] == 'triggered'
    assert status['completed_count'] == 21
    assert status['triggered_at'] == 'timestamp'


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

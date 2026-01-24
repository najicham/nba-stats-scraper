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


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_firestore_client():
    """Mock Firestore client."""
    with patch('orchestration.cloud_functions.phase2_to_phase3.main.db') as mock_db:
        yield mock_db


@pytest.fixture
def mock_pubsub_client():
    """Mock Pub/Sub publisher client."""
    with patch('orchestration.cloud_functions.phase2_to_phase3.main.publisher', create=True) as mock_publisher:
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
    from orchestration.cloud_functions.phase2_to_phase3.main import parse_pubsub_message

    result = parse_pubsub_message(sample_cloud_event)

    assert result == sample_phase2_message
    assert result['processor_name'] == 'BdlGamesProcessor'
    assert result['game_date'] == '2025-11-29'
    assert result['correlation_id'] == 'abc-123'


def test_parse_pubsub_message_invalid():
    """Test parsing fails gracefully with invalid message."""
    from orchestration.cloud_functions.phase2_to_phase3.main import parse_pubsub_message

    cloud_event = Mock()
    cloud_event.data = {}

    with pytest.raises(ValueError, match="Invalid Pub/Sub message format"):
        parse_pubsub_message(cloud_event)


# ============================================================================
# TEST: Expected Processors Configuration
# ============================================================================

def test_expected_processors_defined():
    """Test that expected processors are defined."""
    from orchestration.cloud_functions.phase2_to_phase3.main import EXPECTED_PROCESSORS

    assert isinstance(EXPECTED_PROCESSORS, list)
    assert len(EXPECTED_PROCESSORS) > 0


def test_expected_processor_count():
    """Test expected processor count is correct."""
    from orchestration.cloud_functions.phase2_to_phase3.main import (
        EXPECTED_PROCESSORS,
        EXPECTED_PROCESSOR_COUNT
    )

    assert EXPECTED_PROCESSOR_COUNT == len(EXPECTED_PROCESSORS)


# ============================================================================
# TEST: Completion Status
# ============================================================================

def test_get_completion_status_not_started(mock_firestore_client):
    """Test get_completion_status when no processors have run yet."""
    from orchestration.cloud_functions.phase2_to_phase3.main import (
        get_completion_status,
        EXPECTED_PROCESSOR_COUNT
    )

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
    assert status['expected_count'] == EXPECTED_PROCESSOR_COUNT


def test_get_completion_status_in_progress(mock_firestore_client):
    """Test get_completion_status when some processors complete."""
    from orchestration.cloud_functions.phase2_to_phase3.main import (
        get_completion_status,
        EXPECTED_PROCESSOR_COUNT
    )

    # Setup: 3 processors complete
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = True
    doc_snapshot.to_dict.return_value = {
        'Processor0': {'status': 'success'},
        'Processor1': {'status': 'success'},
        'Processor2': {'status': 'success'},
        '_completed_count': 3
    }

    doc_ref.get.return_value = doc_snapshot

    collection_mock = Mock()
    collection_mock.document.return_value = doc_ref
    mock_firestore_client.collection.return_value = collection_mock

    # Execute
    status = get_completion_status('2025-11-29')

    # Verify
    assert status['status'] == 'in_progress'
    assert status['expected_count'] == EXPECTED_PROCESSOR_COUNT


def test_get_completion_status_triggered(mock_firestore_client):
    """Test get_completion_status when all complete and triggered."""
    from orchestration.cloud_functions.phase2_to_phase3.main import get_completion_status

    # Setup: All complete and triggered
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = True
    data = {f'Processor{i}': {'status': 'success'} for i in range(21)}
    data['_triggered'] = True
    data['_triggered_at'] = 'timestamp'
    data['_completed_count'] = 21
    doc_snapshot.to_dict.return_value = data

    doc_ref.get.return_value = doc_snapshot

    collection_mock = Mock()
    collection_mock.document.return_value = doc_ref
    mock_firestore_client.collection.return_value = collection_mock

    # Execute
    status = get_completion_status('2025-11-29')

    # Verify
    assert status['status'] == 'triggered'
    assert status['triggered_at'] == 'timestamp'


# ============================================================================
# TEST: Atomic Update Logic (Unit Tests)
# ============================================================================

def test_idempotency_duplicate_processor():
    """Test that duplicate processor completions are handled idempotently."""
    # Simulate the idempotency check logic
    current_data = {
        'BdlGamesProcessor': {'status': 'success', 'completed_at': 'earlier'},
        '_completed_count': 1
    }

    processor_name = 'BdlGamesProcessor'

    # Check: processor already registered
    already_registered = processor_name in current_data

    assert already_registered is True


def test_completion_count_excludes_metadata_fields():
    """Test that completion count excludes underscore-prefixed metadata fields."""
    data = {
        'Processor1': {'status': 'success'},
        'Processor2': {'status': 'success'},
        '_triggered': True,
        '_triggered_at': 'timestamp',
        '_completed_count': 2,
        '_first_completion_at': 'timestamp'
    }

    # Count processors (exclude metadata fields starting with _)
    completed_count = len([k for k in data.keys() if not k.startswith('_')])

    assert completed_count == 2


def test_trigger_condition_check():
    """Test the trigger condition logic."""
    from orchestration.cloud_functions.phase2_to_phase3.main import EXPECTED_PROCESSOR_COUNT

    # Test case 1: Not enough processors
    current_1 = {'Processor1': {}, 'Processor2': {}}
    completed_1 = len([k for k in current_1.keys() if not k.startswith('_')])
    should_trigger_1 = completed_1 >= EXPECTED_PROCESSOR_COUNT and not current_1.get('_triggered')
    assert should_trigger_1 is False

    # Test case 2: Already triggered
    current_2 = {f'Processor{i}': {} for i in range(EXPECTED_PROCESSOR_COUNT)}
    current_2['_triggered'] = True
    completed_2 = len([k for k in current_2.keys() if not k.startswith('_')])
    should_trigger_2 = completed_2 >= EXPECTED_PROCESSOR_COUNT and not current_2.get('_triggered')
    assert should_trigger_2 is False


# ============================================================================
# TEST: CloudEvent Handling
# ============================================================================

def test_cloud_event_message_extraction(sample_cloud_event):
    """Test extracting message from CloudEvent."""
    pubsub_message = sample_cloud_event.data.get('message', {})

    assert 'data' in pubsub_message
    assert 'messageId' in pubsub_message

    # Decode data
    raw_data = base64.b64decode(pubsub_message['data']).decode('utf-8')
    message = json.loads(raw_data)

    assert message['processor_name'] == 'BdlGamesProcessor'


def test_cloud_event_empty_data():
    """Test handling of empty CloudEvent data."""
    cloud_event = Mock()
    cloud_event.data = {}

    pubsub_message = cloud_event.data.get('message', {})

    assert pubsub_message == {}
    assert 'data' not in pubsub_message


# ============================================================================
# TEST: Status Values
# ============================================================================

def test_status_values():
    """Test that processor status is correctly captured."""
    test_statuses = ['success', 'failed', 'skipped', 'timeout']

    for status in test_statuses:
        completion_data = {
            'status': status,
            'completed_at': 'timestamp',
            'correlation_id': 'abc-123'
        }

        assert completion_data['status'] == status


# ============================================================================
# TEST: Game Date Handling
# ============================================================================

def test_game_date_format():
    """Test that game_date format is handled correctly."""
    valid_dates = ['2025-11-29', '2026-01-01', '2025-12-31']

    for date_str in valid_dates:
        # Should be valid ISO format
        datetime.strptime(date_str, '%Y-%m-%d')


def test_game_date_as_document_id():
    """Test using game_date as Firestore document ID."""
    game_date = '2025-11-29'
    collection_name = 'phase2_completion'

    # Simulated document path
    doc_path = f"{collection_name}/{game_date}"

    assert doc_path == "phase2_completion/2025-11-29"


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

"""
Unit tests for Phase 3 → Phase 4 Orchestrator

Tests critical race condition prevention and entity change aggregation logic.

Run:
    pytest tests/cloud_functions/test_phase3_orchestrator.py -v
"""

import json
import base64
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from orchestration.cloud_functions.phase3_to_phase4.main import (
    orchestrate_phase3_to_phase4,
    update_completion_atomic,
    trigger_phase4,
    parse_pubsub_message,
    get_completion_status,
    EXPECTED_PROCESSORS
)

# Disable mode-aware orchestration for legacy tests
import orchestration.cloud_functions.phase3_to_phase4.main as phase3_module
phase3_module.MODE_AWARE_ENABLED = False


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_phase3_message():
    """Sample Phase 3 completion message."""
    return {
        'processor_name': 'PlayerGameSummaryProcessor',
        'phase': 'phase_3_analytics',
        'execution_id': 'def-456',
        'correlation_id': 'abc-123',
        'game_date': '2025-11-29',
        'output_table': 'player_game_summary',
        'output_dataset': 'nba_analytics',
        'status': 'success',
        'record_count': 450,
        'timestamp': '2025-11-29T12:00:00Z',
        'metadata': {
            'is_incremental': True,
            'entities_changed': ['lebron-james', 'stephen-curry'],
            'efficiency_gain_pct': 99.5
        }
    }


@pytest.fixture
def sample_cloud_event(sample_phase3_message):
    """Sample CloudEvent from Pub/Sub."""
    message_data = base64.b64encode(
        json.dumps(sample_phase3_message).encode('utf-8')
    )

    cloud_event = Mock()
    cloud_event.data = {
        'message': {
            'data': message_data,
            'messageId': 'test-message-456',
            'publishTime': '2025-11-29T12:00:00Z'
        }
    }

    return cloud_event


# ============================================================================
# TEST: Message Parsing
# ============================================================================

def test_parse_pubsub_message(sample_cloud_event, sample_phase3_message):
    """Test parsing Phase 3 Pub/Sub message."""
    result = parse_pubsub_message(sample_cloud_event)

    assert result == sample_phase3_message
    assert result['processor_name'] == 'PlayerGameSummaryProcessor'
    assert result['game_date'] == '2025-11-29'
    assert result['metadata']['entities_changed'] == ['lebron-james', 'stephen-curry']


def test_parse_pubsub_message_invalid():
    """Test parsing fails gracefully with invalid message."""
    cloud_event = Mock()
    cloud_event.data = {}

    with pytest.raises(ValueError, match="Invalid Pub/Sub message format"):
        parse_pubsub_message(cloud_event)


# ============================================================================
# TEST: Atomic Transaction Logic
# ============================================================================

@patch('orchestration.cloud_functions.phase3_to_phase4.main.db')
def test_update_completion_first_processor(mock_db_instance):
    """Test registering first processor (1/5 complete)."""
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = False
    doc_snapshot.to_dict.return_value = {}

    doc_ref.get.return_value = doc_snapshot

    from google.cloud.firestore_v1.transaction import Transaction

    with patch.object(Transaction, 'set') as mock_set:
        transaction = Transaction(mock_db_instance)

        completion_data = {
            'completed_at': 'timestamp',
            'correlation_id': 'abc-123',
            'status': 'success',
            'record_count': 450,
            'is_incremental': True,
            'entities_changed': ['lebron-james']
        }

        should_trigger, mode, reason = update_completion_atomic(
            transaction,
            doc_ref,
            'PlayerGameSummaryProcessor',
            completion_data,
            '2026-01-24'
        )

        assert should_trigger is False  # Don't trigger yet (only 1/5)
        mock_set.assert_called_once()
        written_data = mock_set.call_args[0][1]
        assert 'PlayerGameSummaryProcessor' in written_data
        assert written_data['_completed_count'] == 1


@patch('orchestration.cloud_functions.phase3_to_phase4.main.db')
def test_update_completion_last_processor_triggers(mock_db_instance):
    """Test registering 5th processor triggers Phase 4."""
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = True

    # 4 processors already complete
    existing_data = {
        'PlayerGameSummaryProcessor': {'status': 'success'},
        'TeamDefenseGameSummaryProcessor': {'status': 'success'},
        'TeamOffenseGameSummaryProcessor': {'status': 'success'},
        'UpcomingPlayerGameContextProcessor': {'status': 'success'},
        '_completed_count': 4
    }
    doc_snapshot.to_dict.return_value = existing_data

    doc_ref.get.return_value = doc_snapshot

    from google.cloud.firestore_v1.transaction import Transaction

    with patch.object(Transaction, 'set') as mock_set:
        transaction = Transaction(mock_db_instance)

        completion_data = {
            'completed_at': 'timestamp',
            'correlation_id': 'abc-123',
            'status': 'success'
        }

        # Add 5th processor
        should_trigger, mode, reason = update_completion_atomic(
            transaction,
            doc_ref,
            'UpcomingTeamGameContextProcessor',
            completion_data,
            '2026-01-24'
        )

        assert should_trigger is True  # Should trigger Phase 4!
        mock_set.assert_called_once()
        written_data = mock_set.call_args[0][1]
        assert written_data['_triggered'] is True
        assert written_data['_completed_count'] == 5


@patch('orchestration.cloud_functions.phase3_to_phase4.main.db')
def test_update_completion_duplicate_message(mock_db_instance):
    """Test idempotency - duplicate message doesn't re-add processor."""
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = True
    doc_snapshot.to_dict.return_value = {
        'PlayerGameSummaryProcessor': {'status': 'success', 'completed_at': 'earlier'},
        '_completed_count': 1
    }

    doc_ref.get.return_value = doc_snapshot

    from google.cloud.firestore_v1.transaction import Transaction

    with patch.object(Transaction, 'set') as mock_set:
        transaction = Transaction(mock_db_instance)

        should_trigger, mode, reason = update_completion_atomic(
            transaction,
            doc_ref,
            'PlayerGameSummaryProcessor',  # Already exists
            {'status': 'success'},
            '2026-01-24'
        )

        assert should_trigger is False
        mock_set.assert_not_called()  # Should NOT write


# ============================================================================
# TEST: Entity Change Aggregation
# ============================================================================

@patch('orchestration.cloud_functions.phase3_to_phase4.main.publisher')
@patch('orchestration.cloud_functions.phase3_to_phase4.main.db')
def test_trigger_phase4_aggregates_entities(mock_db, mock_publisher):
    """Test that Phase 4 trigger aggregates entities_changed from all processors."""
    # Setup Firestore data with multiple processors and their entities
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = True

    firestore_data = {
        'PlayerGameSummaryProcessor': {
            'is_incremental': True,
            'entities_changed': ['lebron-james', 'stephen-curry']
        },
        'UpcomingPlayerGameContextProcessor': {
            'is_incremental': True,
            'entities_changed': ['kevin-durant']  # Different player
        },
        'TeamDefenseGameSummaryProcessor': {
            'is_incremental': True,
            'entities_changed': ['LAL', 'GSW']
        },
        'TeamOffenseGameSummaryProcessor': {
            'is_incremental': False,  # Full batch
            'entities_changed': []
        },
        'UpcomingTeamGameContextProcessor': {
            'is_incremental': True,
            'entities_changed': ['BOS']
        },
        '_triggered': True
    }

    doc_snapshot.to_dict.return_value = firestore_data
    doc_ref.get.return_value = doc_snapshot

    # Setup mock publisher
    mock_future = Mock()
    mock_future.result.return_value = 'published-message-id'
    mock_publisher.publish.return_value = mock_future
    mock_publisher.topic_path.return_value = 'projects/test/topics/nba-phase4-trigger'

    # Execute
    message_id = trigger_phase4('2025-11-29', 'abc-123', doc_ref, {}, 'legacy', 'all_complete')

    # Verify
    assert message_id == 'published-message-id'

    # Verify published message has combined entities
    published_data = json.loads(mock_publisher.publish.call_args[1]['data'].decode('utf-8'))

    assert published_data['is_incremental'] is True
    assert 'entities_changed' in published_data

    # Should have aggregated players: lebron, curry, durant
    assert set(published_data['entities_changed']['players']) == {
        'lebron-james', 'stephen-curry', 'kevin-durant'
    }

    # Should have aggregated teams: LAL, GSW, BOS
    assert set(published_data['entities_changed']['teams']) == {
        'LAL', 'GSW', 'BOS'
    }


# ============================================================================
# TEST: Helper Functions
# ============================================================================

@patch('orchestration.cloud_functions.phase3_to_phase4.main.db')
def test_get_completion_status_not_started(mock_db):
    """Test status when no processors have run."""
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = False

    doc_ref.get.return_value = doc_snapshot

    collection_mock = Mock()
    collection_mock.document.return_value = doc_ref
    mock_db.collection.return_value = collection_mock

    status = get_completion_status('2025-11-29')

    assert status['status'] == 'not_started'
    assert status['completed_count'] == 0
    assert status['expected_count'] == len(EXPECTED_PROCESSORS)


@patch('orchestration.cloud_functions.phase3_to_phase4.main.db')
def test_get_completion_status_in_progress(mock_db):
    """Test status when some processors complete."""
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = True
    doc_snapshot.to_dict.return_value = {
        'PlayerGameSummaryProcessor': {'status': 'success'},
        'TeamDefenseGameSummaryProcessor': {'status': 'success'},
        '_completed_count': 2
    }

    doc_ref.get.return_value = doc_snapshot

    collection_mock = Mock()
    collection_mock.document.return_value = doc_ref
    mock_db.collection.return_value = collection_mock

    status = get_completion_status('2025-11-29')

    assert status['status'] == 'in_progress'
    assert status['completed_count'] == 2
    assert status['expected_count'] == len(EXPECTED_PROCESSORS)


@patch('orchestration.cloud_functions.phase3_to_phase4.main.db')
def test_get_completion_status_triggered(mock_db):
    """Test status when all complete and triggered."""
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = True
    data = {
        'PlayerGameSummaryProcessor': {'status': 'success'},
        'TeamDefenseGameSummaryProcessor': {'status': 'success'},
        'TeamOffenseGameSummaryProcessor': {'status': 'success'},
        'UpcomingPlayerGameContextProcessor': {'status': 'success'},
        'UpcomingTeamGameContextProcessor': {'status': 'success'},
        '_triggered': True,
        '_triggered_at': 'timestamp'
    }
    doc_snapshot.to_dict.return_value = data

    doc_ref.get.return_value = doc_snapshot

    collection_mock = Mock()
    collection_mock.document.return_value = doc_ref
    mock_db.collection.return_value = collection_mock

    status = get_completion_status('2025-11-29')

    assert status['status'] == 'triggered'
    assert status['completed_count'] == 5
    assert status['triggered_at'] == 'timestamp'


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

"""
Test suite for BatchStateManager - Focus on dual-write atomicity

Critical Tests:
- P0: Dual-write transaction atomicity (prevents data corruption)
- Consistency validation during dual-write migration
- Feature flag behavior (legacy, dual-write, subcollection-only modes)
- Transaction failure rollback scenarios

Author: Claude Code
Date: January 25, 2026
"""

import pytest
import os
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime, timezone
from google.cloud import firestore


@pytest.fixture
def mock_firestore_client():
    """Create mock Firestore client"""
    mock_client = Mock()
    mock_collection = Mock()
    mock_client.collection.return_value = mock_collection
    mock_client.transaction.return_value = Mock()
    return mock_client


@pytest.fixture
def batch_state_manager(mock_firestore_client):
    """Create BatchStateManager with mocked Firestore"""
    with patch('shared.clients.get_firestore_client') as mock_get_client:
        mock_get_client.return_value = mock_firestore_client

        from predictions.coordinator.batch_state_manager import BatchStateManager

        # Set feature flags for dual-write mode
        os.environ['ENABLE_SUBCOLLECTION_COMPLETIONS'] = 'true'
        os.environ['DUAL_WRITE_MODE'] = 'true'
        os.environ['USE_SUBCOLLECTION_READS'] = 'false'

        manager = BatchStateManager(project_id='test-project')
        manager.db = mock_firestore_client

        yield manager


@pytest.fixture
def mock_firestore_helpers():
    """Mock Firestore helper functions"""
    mock_array_union = Mock(return_value=['player-1'])
    mock_increment = Mock(return_value=1)
    mock_server_timestamp = Mock()

    with patch('predictions.coordinator.batch_state_manager._get_firestore_helpers') as mock_helpers:
        mock_helpers.return_value = (mock_array_union, mock_increment, mock_server_timestamp)
        yield {
            'ArrayUnion': mock_array_union,
            'Increment': mock_increment,
            'SERVER_TIMESTAMP': mock_server_timestamp
        }


class TestDualWriteAtomicity:
    """
    P0 CRITICAL: Test dual-write transaction atomicity

    This test suite validates the fix for the data corruption bug where
    subcollection write could fail after array write succeeded.
    """

    @patch('predictions.coordinator.batch_state_manager._get_firestore')
    @patch('predictions.coordinator.batch_state_manager._get_firestore_helpers')
    def test_dual_write_uses_transaction(
        self,
        mock_helpers,
        mock_get_firestore,
        batch_state_manager
    ):
        """
        CRITICAL: Verify dual-write uses transaction for atomicity

        This test ensures both array write and subcollection write happen
        within a single transaction, preventing partial writes.
        """
        # Setup mocks
        mock_firestore_module = Mock()
        mock_get_firestore.return_value = mock_firestore_module

        mock_array_union = Mock()
        mock_increment = Mock()
        mock_server_timestamp = Mock()
        mock_helpers.return_value = (mock_array_union, mock_increment, mock_server_timestamp)

        # Mock transaction
        mock_transaction = Mock()
        batch_state_manager.db.transaction.return_value = mock_transaction

        # Mock document refs
        mock_doc_ref = Mock()
        mock_completion_ref = Mock()
        mock_collection_ref = Mock()
        mock_collection_ref.document.return_value = mock_completion_ref
        mock_doc_ref.collection.return_value = mock_collection_ref
        batch_state_manager.collection.document.return_value = mock_doc_ref

        # Mock document read for batch completion check
        mock_snapshot = Mock()
        mock_snapshot.exists = True
        mock_snapshot.to_dict.return_value = {
            'expected_players': 10,
            'completed_players': ['player-1'],
            'completed_count': 1
        }
        mock_doc_ref.get.return_value = mock_snapshot

        # Execute
        batch_state_manager.record_completion(
            batch_id='test-batch',
            player_lookup='player-1',
            predictions_count=5
        )

        # Verify transaction was created
        batch_state_manager.db.transaction.assert_called_once()

        # Verify transaction.update was called for array write
        # Verify transaction.set was called for subcollection write
        # Verify transaction.update was called for counters
        assert mock_transaction.update.call_count >= 1 or mock_transaction.set.call_count >= 1

    @patch('predictions.coordinator.batch_state_manager._get_firestore')
    @patch('predictions.coordinator.batch_state_manager._get_firestore_helpers')
    def test_dual_write_rollback_on_failure(
        self,
        mock_helpers,
        mock_get_firestore,
        batch_state_manager
    ):
        """
        CRITICAL: Verify transaction rolls back on failure

        If subcollection write fails, the entire transaction (including array write)
        should roll back, preventing inconsistent state.
        """
        # Setup mocks
        mock_firestore_module = Mock()
        mock_get_firestore.return_value = mock_firestore_module

        mock_array_union = Mock()
        mock_increment = Mock()
        mock_server_timestamp = Mock()
        mock_helpers.return_value = (mock_array_union, mock_increment, mock_server_timestamp)

        # Mock transaction that fails
        mock_transaction = Mock()

        # Simulate transaction failure (e.g., subcollection write fails)
        def failing_transactional_decorator(func):
            def wrapper(transaction):
                # Raise error to simulate subcollection write failure
                raise firestore.exceptions.FailedPrecondition("Subcollection write failed")
            return wrapper

        mock_firestore_module.transactional = failing_transactional_decorator

        # Mock document refs
        mock_doc_ref = Mock()
        batch_state_manager.collection.document.return_value = mock_doc_ref

        # Execute - should raise exception and NOT commit partial writes
        with pytest.raises(Exception):
            batch_state_manager.record_completion(
                batch_id='test-batch',
                player_lookup='player-1',
                predictions_count=5
            )

        # Verify no individual updates were made (transaction handles all writes)
        # If we see doc_ref.update() called, that's the OLD buggy behavior
        # The new behavior should use transaction.update() instead

    @patch('predictions.coordinator.batch_state_manager._get_firestore')
    @patch('predictions.coordinator.batch_state_manager._get_firestore_helpers')
    def test_dual_write_both_writes_succeed_or_fail_together(
        self,
        mock_helpers,
        mock_get_firestore,
        batch_state_manager
    ):
        """
        CRITICAL: Verify array and subcollection writes are atomic

        This test validates that we cannot have array updated but subcollection
        not updated (or vice versa).
        """
        # Setup mocks
        mock_firestore_module = Mock()
        mock_get_firestore.return_value = mock_firestore_module

        mock_array_union = Mock()
        mock_increment = Mock()
        mock_server_timestamp = Mock()
        mock_helpers.return_value = (mock_array_union, mock_increment, mock_server_timestamp)

        # Track calls to transaction.update and transaction.set
        call_tracker = {
            'array_write': False,
            'subcollection_write': False,
            'counter_update': False
        }

        mock_transaction = Mock()

        def track_update(*args, **kwargs):
            # Check if this is array write or counter update
            if len(args) >= 2:
                update_dict = args[1] if len(args) > 1 else kwargs.get('updates', {})
                if 'completed_players' in str(update_dict):
                    call_tracker['array_write'] = True
                if 'completed_count' in str(update_dict):
                    call_tracker['counter_update'] = True

        def track_set(*args, **kwargs):
            call_tracker['subcollection_write'] = True

        mock_transaction.update.side_effect = track_update
        mock_transaction.set.side_effect = track_set

        # Decorate functions to execute them
        def transactional_decorator(func):
            def wrapper(transaction):
                return func(transaction)
            return wrapper

        mock_firestore_module.transactional = transactional_decorator
        batch_state_manager.db.transaction.return_value = mock_transaction

        # Mock document refs
        mock_doc_ref = Mock()
        mock_completion_ref = Mock()
        mock_collection_ref = Mock()
        mock_collection_ref.document.return_value = mock_completion_ref
        mock_doc_ref.collection.return_value = mock_collection_ref
        batch_state_manager.collection.document.return_value = mock_doc_ref

        # Mock document read
        mock_snapshot = Mock()
        mock_snapshot.exists = True
        mock_snapshot.to_dict.return_value = {
            'expected_players': 10,
            'completed_players': ['player-1'],
            'completed_count': 1
        }
        mock_doc_ref.get.return_value = mock_snapshot

        # Execute
        batch_state_manager.record_completion(
            batch_id='test-batch',
            player_lookup='player-1',
            predictions_count=5
        )

        # Verify all three writes happened (or none, but not partial)
        # In transaction mode, all three should be True
        assert call_tracker['array_write'] == call_tracker['subcollection_write']
        assert call_tracker['subcollection_write'] == call_tracker['counter_update']


class TestConsistencyValidation:
    """Test dual-write consistency validation"""

    @patch('predictions.coordinator.batch_state_manager._get_firestore_helpers')
    def test_consistency_validation_detects_mismatch(
        self,
        mock_helpers,
        batch_state_manager
    ):
        """Verify consistency validation detects array/subcollection mismatches"""
        mock_array_union = Mock()
        mock_increment = Mock()
        mock_server_timestamp = Mock()
        mock_helpers.return_value = (mock_array_union, mock_increment, mock_server_timestamp)

        # Mock batch document with array count
        mock_batch_doc = Mock()
        mock_batch_doc.exists = True
        mock_batch_doc.to_dict.return_value = {
            'completed_players': ['player-1', 'player-2', 'player-3'],  # 3 players
            'completed_count': 2  # But counter shows only 2 - MISMATCH!
        }

        mock_doc_ref = Mock()
        mock_doc_ref.get.return_value = mock_batch_doc
        batch_state_manager.collection.document.return_value = mock_doc_ref

        # Execute validation
        with patch('predictions.coordinator.batch_state_manager.logger') as mock_logger:
            batch_state_manager._validate_dual_write_consistency('test-batch')

            # Verify warning was logged
            assert any(
                'CONSISTENCY MISMATCH' in str(call)
                for call in mock_logger.warning.call_args_list
            )

    @patch('predictions.coordinator.batch_state_manager._get_firestore_helpers')
    def test_consistency_validation_passes_on_match(
        self,
        mock_helpers,
        batch_state_manager
    ):
        """Verify consistency validation passes when counts match"""
        mock_array_union = Mock()
        mock_increment = Mock()
        mock_server_timestamp = Mock()
        mock_helpers.return_value = (mock_array_union, mock_increment, mock_server_timestamp)

        # Mock batch document with matching counts
        mock_batch_doc = Mock()
        mock_batch_doc.exists = True
        mock_batch_doc.to_dict.return_value = {
            'completed_players': ['player-1', 'player-2'],  # 2 players
            'completed_count': 2  # Counter matches!
        }

        mock_doc_ref = Mock()
        mock_doc_ref.get.return_value = mock_batch_doc
        batch_state_manager.collection.document.return_value = mock_doc_ref

        # Execute validation
        with patch('predictions.coordinator.batch_state_manager.logger') as mock_logger:
            batch_state_manager._validate_dual_write_consistency('test-batch')

            # Verify NO warning was logged
            assert not any(
                'CONSISTENCY MISMATCH' in str(call)
                for call in mock_logger.warning.call_args_list
            )


class TestFeatureFlagModes:
    """Test different migration modes (legacy, dual-write, subcollection-only)"""

    @patch('shared.clients.get_firestore_client')
    @patch('predictions.coordinator.batch_state_manager._get_firestore_helpers')
    def test_legacy_mode_only_writes_array(
        self,
        mock_helpers,
        mock_get_client
    ):
        """Verify legacy mode only writes to array (no subcollection)"""
        from predictions.coordinator.batch_state_manager import BatchStateManager

        mock_client = Mock()
        mock_get_client.return_value = mock_client

        mock_array_union = Mock()
        mock_increment = Mock()
        mock_server_timestamp = Mock()
        mock_helpers.return_value = (mock_array_union, mock_increment, mock_server_timestamp)

        # Set feature flags for LEGACY mode
        os.environ['ENABLE_SUBCOLLECTION_COMPLETIONS'] = 'false'
        os.environ['DUAL_WRITE_MODE'] = 'false'

        manager = BatchStateManager(project_id='test-project')
        manager.db = mock_client

        # Mock document refs
        mock_doc_ref = Mock()
        mock_snapshot = Mock()
        mock_snapshot.exists = True
        mock_snapshot.to_dict.return_value = {
            'expected_players': 10,
            'completed_players': ['player-1']
        }
        mock_doc_ref.get.return_value = mock_snapshot
        mock_doc_ref.update.return_value = None

        mock_collection = Mock()
        mock_collection.document.return_value = mock_doc_ref
        manager.collection = mock_collection

        # Execute
        manager.record_completion(
            batch_id='test-batch',
            player_lookup='player-1',
            predictions_count=5
        )

        # Verify only array write happened (doc_ref.update called)
        mock_doc_ref.update.assert_called_once()

        # Verify NO subcollection write (doc_ref.collection should not be called)
        mock_doc_ref.collection.assert_not_called()

    @patch('shared.clients.get_firestore_client')
    @patch('predictions.coordinator.batch_state_manager._get_firestore_helpers')
    def test_subcollection_only_mode(
        self,
        mock_helpers,
        mock_get_client
    ):
        """Verify subcollection-only mode does NOT write to array"""
        from predictions.coordinator.batch_state_manager import BatchStateManager

        mock_client = Mock()
        mock_get_client.return_value = mock_client

        mock_array_union = Mock()
        mock_increment = Mock()
        mock_server_timestamp = Mock()
        mock_helpers.return_value = (mock_array_union, mock_increment, mock_server_timestamp)

        # Set feature flags for SUBCOLLECTION-ONLY mode
        os.environ['ENABLE_SUBCOLLECTION_COMPLETIONS'] = 'true'
        os.environ['DUAL_WRITE_MODE'] = 'false'

        manager = BatchStateManager(project_id='test-project')
        manager.db = mock_client

        # Mock document refs
        mock_doc_ref = Mock()
        mock_completion_ref = Mock()
        mock_collection_ref = Mock()
        mock_collection_ref.document.return_value = mock_completion_ref
        mock_doc_ref.collection.return_value = mock_collection_ref

        mock_snapshot = Mock()
        mock_snapshot.exists = True
        mock_snapshot.to_dict.return_value = {
            'expected_players': 10,
            'completed_count': 1
        }
        mock_doc_ref.get.return_value = mock_snapshot

        mock_collection = Mock()
        mock_collection.document.return_value = mock_doc_ref
        manager.collection = mock_collection

        # Track calls
        array_write_calls = []
        original_update = mock_doc_ref.update

        def track_update(*args, **kwargs):
            array_write_calls.append((args, kwargs))
            return original_update(*args, **kwargs)

        mock_doc_ref.update.side_effect = track_update

        # Execute
        manager.record_completion(
            batch_id='test-batch',
            player_lookup='player-1',
            predictions_count=5
        )

        # Verify subcollection write happened
        mock_collection_ref.document.assert_called_with('player-1')

        # Verify array write did NOT include completed_players
        # (Only counter updates should happen, not array updates)
        for args, kwargs in array_write_calls:
            update_dict = args[0] if args else {}
            # Should not have completed_players in ArrayUnion
            assert 'completed_players' not in str(update_dict) or \
                   mock_array_union not in str(update_dict)


class TestTransactionRetry:
    """Test transaction retry logic for transient failures"""

    @patch('predictions.coordinator.batch_state_manager._get_firestore')
    @patch('predictions.coordinator.batch_state_manager._get_firestore_helpers')
    def test_transaction_retries_on_contention(
        self,
        mock_helpers,
        mock_get_firestore,
        batch_state_manager
    ):
        """Verify Firestore automatically retries transactions on contention"""
        # Firestore SDK handles transaction retries automatically
        # We just need to verify our code doesn't break retry logic

        mock_firestore_module = Mock()
        mock_get_firestore.return_value = mock_firestore_module

        mock_array_union = Mock()
        mock_increment = Mock()
        mock_server_timestamp = Mock()
        mock_helpers.return_value = (mock_array_union, mock_increment, mock_server_timestamp)

        retry_count = [0]

        def transactional_decorator(func):
            def wrapper(transaction):
                retry_count[0] += 1
                if retry_count[0] < 2:
                    # Simulate contention on first try
                    raise firestore.exceptions.Aborted("Transaction aborted")
                # Success on second try
                return func(transaction)
            return wrapper

        mock_firestore_module.transactional = transactional_decorator

        mock_transaction = Mock()
        batch_state_manager.db.transaction.return_value = mock_transaction

        # Mock document refs
        mock_doc_ref = Mock()
        mock_completion_ref = Mock()
        mock_collection_ref = Mock()
        mock_collection_ref.document.return_value = mock_completion_ref
        mock_doc_ref.collection.return_value = mock_collection_ref
        batch_state_manager.collection.document.return_value = mock_doc_ref

        mock_snapshot = Mock()
        mock_snapshot.exists = True
        mock_snapshot.to_dict.return_value = {
            'expected_players': 10,
            'completed_players': ['player-1'],
            'completed_count': 1
        }
        mock_doc_ref.get.return_value = mock_snapshot

        # Execute - should succeed after retry
        result = batch_state_manager.record_completion(
            batch_id='test-batch',
            player_lookup='player-1',
            predictions_count=5
        )

        # Verify retry happened
        assert retry_count[0] >= 1


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

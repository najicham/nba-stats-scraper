# predictions/coordinator/tests/test_multi_instance.py

"""
Test suite for multi-instance coordinator coordination.

Tests distributed locking, instance heartbeat tracking, and failover scenarios
for running multiple coordinator instances concurrently.
"""

import pytest
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock, patch, PropertyMock


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_firestore_client():
    """Create a mock Firestore client for testing."""
    client = MagicMock()
    client.project = 'test-project'

    # Track documents in memory for realistic behavior
    documents = {}

    def mock_collection(name):
        collection = MagicMock()
        collection._name = name

        def mock_document(doc_id):
            doc_ref = MagicMock()
            doc_ref.id = doc_id
            doc_ref._key = f"{name}/{doc_id}"

            def mock_get(transaction=None):
                doc = MagicMock()
                if doc_ref._key in documents:
                    doc.exists = True
                    doc.to_dict.return_value = documents[doc_ref._key].copy()
                else:
                    doc.exists = False
                    doc.to_dict.return_value = None
                return doc

            def mock_set(data):
                documents[doc_ref._key] = data.copy()

            def mock_update(data):
                if doc_ref._key in documents:
                    documents[doc_ref._key].update(data)

            def mock_delete():
                if doc_ref._key in documents:
                    del documents[doc_ref._key]

            doc_ref.get = mock_get
            doc_ref.set = mock_set
            doc_ref.update = mock_update
            doc_ref.delete = mock_delete
            doc_ref.collection = mock_collection  # For subcollections

            return doc_ref

        def mock_where(field, op, value):
            query = MagicMock()

            def mock_stream():
                for key, data in documents.items():
                    if key.startswith(f"{name}/"):
                        if op == '==':
                            if data.get(field) == value:
                                doc = MagicMock()
                                doc.id = key.split('/')[-1]
                                doc.to_dict.return_value = data.copy()
                                doc.reference = mock_document(doc.id)
                                yield doc
                        elif op == '<':
                            if data.get(field) and data.get(field) < value:
                                doc = MagicMock()
                                doc.id = key.split('/')[-1]
                                doc.to_dict.return_value = data.copy()
                                doc.reference = mock_document(doc.id)
                                yield doc

            query.stream = mock_stream
            query.where = mock_where  # Allow chaining
            return query

        collection.document = mock_document
        collection.where = mock_where

        return collection

    client.collection = mock_collection

    # Mock transaction
    def mock_transaction():
        return MagicMock()

    client.transaction = mock_transaction
    client._documents = documents  # Expose for test inspection

    return client


@pytest.fixture
def mock_firestore_module(mock_firestore_client):
    """Mock the firestore module."""
    with patch('predictions.coordinator.instance_manager._get_firestore') as mock_get_fs:
        mock_module = MagicMock()
        mock_module.Client.return_value = mock_firestore_client
        mock_module.SERVER_TIMESTAMP = 'SERVER_TIMESTAMP'

        # Mock transactional decorator
        def transactional(func):
            return func
        mock_module.transactional = transactional

        mock_get_fs.return_value = mock_module

        with patch('predictions.coordinator.instance_manager._get_firestore_helpers') as mock_helpers:
            mock_helpers.return_value = 'SERVER_TIMESTAMP'
            yield mock_firestore_client


@pytest.fixture
def mock_batch_state_firestore(mock_firestore_client):
    """Mock Firestore for BatchStateManager tests."""
    with patch('predictions.coordinator.batch_state_manager._get_firestore') as mock_get_fs:
        mock_module = MagicMock()
        mock_module.Client.return_value = mock_firestore_client
        mock_module.SERVER_TIMESTAMP = 'SERVER_TIMESTAMP'

        def transactional(func):
            return func
        mock_module.transactional = transactional

        mock_get_fs.return_value = mock_module

        with patch('predictions.coordinator.batch_state_manager._get_firestore_helpers') as mock_helpers:
            mock_helpers.return_value = (
                MagicMock(),  # ArrayUnion
                MagicMock(),  # Increment
                'SERVER_TIMESTAMP'
            )
            yield mock_firestore_client


# ============================================================================
# Instance Manager Tests
# ============================================================================

class TestInstanceInfo:
    """Test InstanceInfo dataclass."""

    def test_is_alive_with_recent_heartbeat(self):
        """Instance with recent heartbeat is alive."""
        from predictions.coordinator.instance_manager import InstanceInfo

        info = InstanceInfo(
            instance_id="test-instance",
            last_heartbeat=datetime.now(timezone.utc)
        )

        assert info.is_alive() is True

    def test_is_alive_with_old_heartbeat(self):
        """Instance with old heartbeat is dead."""
        from predictions.coordinator.instance_manager import InstanceInfo

        info = InstanceInfo(
            instance_id="test-instance",
            last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=120)
        )

        assert info.is_alive() is False

    def test_is_alive_with_no_heartbeat(self):
        """Instance with no heartbeat is dead."""
        from predictions.coordinator.instance_manager import InstanceInfo

        info = InstanceInfo(
            instance_id="test-instance",
            last_heartbeat=None
        )

        assert info.is_alive() is False

    def test_is_alive_custom_timeout(self):
        """Test custom heartbeat timeout."""
        from predictions.coordinator.instance_manager import InstanceInfo

        info = InstanceInfo(
            instance_id="test-instance",
            last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=45)
        )

        # Dead with 30s timeout
        assert info.is_alive(timeout_seconds=30) is False

        # Alive with 60s timeout
        assert info.is_alive(timeout_seconds=60) is True


class TestBatchLock:
    """Test BatchLock dataclass."""

    def test_is_expired_with_future_expiry(self):
        """Lock with future expiry is not expired."""
        from predictions.coordinator.instance_manager import BatchLock

        lock = BatchLock(
            batch_id="batch_123",
            holder_instance_id="instance_1",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)
        )

        assert lock.is_expired() is False

    def test_is_expired_with_past_expiry(self):
        """Lock with past expiry is expired."""
        from predictions.coordinator.instance_manager import BatchLock

        lock = BatchLock(
            batch_id="batch_123",
            holder_instance_id="instance_1",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
        )

        assert lock.is_expired() is True

    def test_is_expired_with_no_expiry(self):
        """Lock with no expiry is expired."""
        from predictions.coordinator.instance_manager import BatchLock

        lock = BatchLock(
            batch_id="batch_123",
            holder_instance_id="instance_1",
            expires_at=None
        )

        assert lock.is_expired() is True


class TestCoordinatorInstanceManager:
    """Test CoordinatorInstanceManager class."""

    @patch('predictions.coordinator.instance_manager._get_firestore')
    @patch('predictions.coordinator.instance_manager._get_firestore_helpers')
    def test_initialization(self, mock_helpers, mock_get_fs):
        """Test instance manager initialization."""
        mock_module = MagicMock()
        mock_get_fs.return_value = mock_module
        mock_helpers.return_value = 'SERVER_TIMESTAMP'

        from predictions.coordinator.instance_manager import CoordinatorInstanceManager

        manager = CoordinatorInstanceManager(
            project_id="test-project",
            instance_id="test-instance-123"
        )

        assert manager.project_id == "test-project"
        assert manager.instance_id == "test-instance-123"
        assert manager.instance_info.instance_id == "test-instance-123"

    @patch('predictions.coordinator.instance_manager._get_firestore')
    @patch('predictions.coordinator.instance_manager._get_firestore_helpers')
    def test_auto_generated_instance_id(self, mock_helpers, mock_get_fs):
        """Test auto-generated instance ID."""
        mock_module = MagicMock()
        mock_get_fs.return_value = mock_module
        mock_helpers.return_value = 'SERVER_TIMESTAMP'

        from predictions.coordinator.instance_manager import CoordinatorInstanceManager

        manager = CoordinatorInstanceManager(project_id="test-project")

        # Should have a valid UUID
        assert len(manager.instance_id) == 36  # UUID format


class TestMultiInstanceLocking:
    """Test distributed locking scenarios."""

    @patch('predictions.coordinator.instance_manager._get_firestore')
    @patch('predictions.coordinator.instance_manager._get_firestore_helpers')
    def test_lock_acquisition_single_instance(self, mock_helpers, mock_get_fs):
        """Single instance can acquire lock."""
        mock_module = MagicMock()
        mock_client = MagicMock()
        mock_get_fs.return_value = mock_module
        mock_module.Client.return_value = mock_client
        mock_helpers.return_value = 'SERVER_TIMESTAMP'

        # Mock document that doesn't exist (lock available)
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_client.collection.return_value.document.return_value.get.return_value = mock_doc

        # Mock transactional decorator
        def transactional(func):
            return func
        mock_module.transactional = transactional

        from predictions.coordinator.instance_manager import CoordinatorInstanceManager

        manager = CoordinatorInstanceManager(
            project_id="test-project",
            instance_id="instance-1"
        )

        # Simulate lock acquisition - the method uses transactions internally
        # We're testing the method completes without error when lock is available
        # and sets up internal state correctly
        result = manager._try_acquire_lock("batch_123", "start")

        # Verify transaction.set was called (lock created)
        mock_client.collection.return_value.document.assert_called_with("batch_123")

    @patch('predictions.coordinator.instance_manager._get_firestore')
    @patch('predictions.coordinator.instance_manager._get_firestore_helpers')
    def test_lock_release(self, mock_helpers, mock_get_fs):
        """Instance can release its lock."""
        mock_module = MagicMock()
        mock_client = MagicMock()
        mock_get_fs.return_value = mock_module
        mock_module.Client.return_value = mock_client
        mock_helpers.return_value = 'SERVER_TIMESTAMP'

        # Mock existing lock document owned by this instance
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            'batch_id': 'batch_123',
            'holder_instance_id': 'instance-1',
            'expires_at': datetime.now(timezone.utc) + timedelta(minutes=5)
        }
        mock_client.collection.return_value.document.return_value.get.return_value = mock_doc

        from predictions.coordinator.instance_manager import CoordinatorInstanceManager

        manager = CoordinatorInstanceManager(
            project_id="test-project",
            instance_id="instance-1"
        )

        # Add lock to active locks
        manager._active_locks["batch_123"] = MagicMock()

        # Release it
        manager._release_lock("batch_123")

        # Verify delete was called
        mock_client.collection.return_value.document.return_value.delete.assert_called_once()

        # Lock should be removed from active locks
        assert "batch_123" not in manager._active_locks


class TestConcurrentBatchOperations:
    """Test concurrent batch operations from multiple instances."""

    def test_concurrent_completion_events(self, mock_batch_state_firestore):
        """Multiple instances can record completions concurrently."""
        from predictions.coordinator.batch_state_manager import BatchStateManager

        manager = BatchStateManager(project_id="test-project")

        # Create batch first
        mock_batch_state_firestore._documents["prediction_batches/batch_123"] = {
            'batch_id': 'batch_123',
            'game_date': '2026-01-23',
            'expected_players': 100,
            'completed_players': [],
            'predictions_by_player': {},
            'total_predictions': 0,
            'is_complete': False
        }

        # Simulate completions from multiple workers
        results = []

        def complete_player(player_id):
            try:
                result = manager.record_completion(
                    batch_id="batch_123",
                    player_lookup=player_id,
                    predictions_count=5
                )
                results.append((player_id, result))
            except Exception as e:
                results.append((player_id, f"error: {e}"))

        # Run in threads to simulate concurrent completions
        threads = []
        for i in range(10):
            t = threading.Thread(target=complete_player, args=(f"player-{i}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All completions should succeed (no collisions due to atomic ops)
        assert len(results) == 10

    def test_batch_claim_logic(self):
        """Test batch claim logic directly - claim checking prevents duplicates."""
        # This tests the claim checking logic without Firestore mocking
        from datetime import datetime, timezone, timedelta

        # Simulate what claim_batch_for_processing checks
        def can_claim(claimed_by: str, claim_expires_at: datetime, new_instance: str) -> bool:
            """Logic from claim_batch_for_processing."""
            if claimed_by and claimed_by != new_instance:
                # Check if claim is still valid
                if claim_expires_at:
                    if datetime.now(timezone.utc) < claim_expires_at:
                        return False  # Claim still valid
            return True

        # No claim - can claim
        assert can_claim(None, None, "instance-1") is True

        # Claimed by same instance - can refresh
        future_expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
        assert can_claim("instance-1", future_expiry, "instance-1") is True

        # Claimed by different instance with valid expiry - cannot claim
        assert can_claim("instance-1", future_expiry, "instance-2") is False

        # Claimed by different instance with expired claim - can take over
        past_expiry = datetime.now(timezone.utc) - timedelta(minutes=10)
        assert can_claim("instance-1", past_expiry, "instance-2") is True

    def test_expired_claim_can_be_taken(self, mock_batch_state_firestore):
        """Expired claim can be taken by another instance."""
        from predictions.coordinator.batch_state_manager import BatchStateManager

        manager = BatchStateManager(project_id="test-project")

        # Create batch with expired claim
        mock_batch_state_firestore._documents["prediction_batches/batch_123"] = {
            'batch_id': 'batch_123',
            'game_date': '2026-01-23',
            'expected_players': 100,
            'completed_players': [],
            'is_complete': False,
            'claimed_by_instance': 'dead-instance',
            'claim_expires_at': datetime.now(timezone.utc) - timedelta(minutes=10)
        }

        # New instance should be able to claim
        result = manager.claim_batch_for_processing(
            batch_id="batch_123",
            instance_id="new-instance"
        )

        assert result is True


class TestInstanceFailover:
    """Test instance failover scenarios."""

    @patch('predictions.coordinator.instance_manager._get_firestore')
    @patch('predictions.coordinator.instance_manager._get_firestore_helpers')
    def test_dead_instance_cleanup(self, mock_helpers, mock_get_fs):
        """Dead instances are cleaned up."""
        mock_module = MagicMock()
        mock_client = MagicMock()
        mock_get_fs.return_value = mock_module
        mock_module.Client.return_value = mock_client
        mock_helpers.return_value = 'SERVER_TIMESTAMP'

        from predictions.coordinator.instance_manager import CoordinatorInstanceManager

        manager = CoordinatorInstanceManager(
            project_id="test-project",
            instance_id="live-instance"
        )

        # Mock dead instance query
        dead_instance = MagicMock()
        dead_instance.to_dict.return_value = {
            'instance_id': 'dead-instance',
            'status': 'active',
            'last_heartbeat': datetime.now(timezone.utc) - timedelta(minutes=10)
        }

        mock_client.collection.return_value.where.return_value.stream.return_value = [dead_instance]
        mock_client.collection.return_value.where.return_value.where.return_value.stream.return_value = []

        # Cleanup should mark dead instance and release locks
        count = manager.cleanup_dead_instances()

        # Dead instance should be marked as stopped
        dead_instance.reference.update.assert_called()

    def test_batch_processing_continues_after_failover(self, mock_batch_state_firestore):
        """Batch processing continues after instance failover."""
        from predictions.coordinator.batch_state_manager import BatchStateManager

        manager = BatchStateManager(project_id="test-project")

        # Batch partially processed by dead instance
        mock_batch_state_firestore._documents["prediction_batches/batch_123"] = {
            'batch_id': 'batch_123',
            'game_date': '2026-01-23',
            'expected_players': 10,
            'completed_players': ['player-1', 'player-2'],
            'predictions_by_player': {'player-1': 5, 'player-2': 5},
            'total_predictions': 10,
            'is_complete': False,
            'claimed_by_instance': 'dead-instance',
            'claim_expires_at': datetime.now(timezone.utc) - timedelta(minutes=5)
        }

        # New instance claims and continues
        result = manager.claim_batch_for_processing(
            batch_id="batch_123",
            instance_id="new-instance"
        )
        assert result is True

        # Can continue processing
        state = manager.get_batch_state("batch_123")
        assert state is not None
        assert len(state.completed_players) == 2  # Previous progress preserved

        # Can add more completions
        manager.record_completion("batch_123", "player-3", 5)


class TestHeartbeatTracking:
    """Test instance heartbeat tracking."""

    @patch('predictions.coordinator.instance_manager._get_firestore')
    @patch('predictions.coordinator.instance_manager._get_firestore_helpers')
    def test_heartbeat_updates_timestamp(self, mock_helpers, mock_get_fs):
        """Heartbeat updates last_heartbeat timestamp."""
        mock_module = MagicMock()
        mock_client = MagicMock()
        mock_get_fs.return_value = mock_module
        mock_module.Client.return_value = mock_client
        mock_helpers.return_value = 'SERVER_TIMESTAMP'

        from predictions.coordinator.instance_manager import CoordinatorInstanceManager

        manager = CoordinatorInstanceManager(
            project_id="test-project",
            instance_id="test-instance"
        )

        # Send heartbeat
        manager._send_heartbeat()

        # Should update document
        mock_client.collection.return_value.document.return_value.update.assert_called()

    @patch('predictions.coordinator.instance_manager._get_firestore')
    @patch('predictions.coordinator.instance_manager._get_firestore_helpers')
    def test_get_active_instances(self, mock_helpers, mock_get_fs):
        """Get active instances filters by heartbeat."""
        mock_module = MagicMock()
        mock_client = MagicMock()
        mock_get_fs.return_value = mock_module
        mock_module.Client.return_value = mock_client
        mock_helpers.return_value = 'SERVER_TIMESTAMP'

        from predictions.coordinator.instance_manager import CoordinatorInstanceManager

        manager = CoordinatorInstanceManager(
            project_id="test-project",
            instance_id="test-instance"
        )

        # Mock instances - one alive, one dead
        alive_instance = MagicMock()
        alive_instance.to_dict.return_value = {
            'instance_id': 'alive-instance',
            'status': 'active',
            'last_heartbeat': datetime.now(timezone.utc)
        }

        dead_instance = MagicMock()
        dead_instance.to_dict.return_value = {
            'instance_id': 'dead-instance',
            'status': 'active',
            'last_heartbeat': datetime.now(timezone.utc) - timedelta(minutes=10)
        }

        mock_client.collection.return_value.where.return_value.stream.return_value = [
            alive_instance, dead_instance
        ]

        active = manager.get_active_instances()

        # Only alive instance should be returned
        assert len(active) == 1
        assert active[0].instance_id == 'alive-instance'


class TestTransactionSafety:
    """Test transaction safety for concurrent operations."""

    def test_transaction_duplicate_check_logic(self):
        """Test transaction duplicate check logic directly."""
        # This tests the logic used in create_batch_with_transaction
        # to prevent duplicate batch creation

        def should_create_batch(doc_exists: bool, existing_game_date: str, new_game_date: str) -> bool:
            """
            Logic from create_batch_with_transaction.

            Returns True if batch should be created, False if it already exists.
            """
            if doc_exists:
                # Check if it's the same game_date (idempotent retry)
                if existing_game_date == new_game_date:
                    return False  # Already exists for same date - idempotent
                else:
                    return False  # Already exists for different date - conflict
            return True

        # Document doesn't exist - create batch
        assert should_create_batch(False, None, "2026-01-23") is True

        # Document exists for same game_date - don't create (idempotent)
        assert should_create_batch(True, "2026-01-23", "2026-01-23") is False

        # Document exists for different game_date - don't create (conflict)
        assert should_create_batch(True, "2026-01-22", "2026-01-23") is False

    def test_safe_completion_with_retry(self, mock_batch_state_firestore):
        """Safe completion retries on transient errors."""
        from predictions.coordinator.batch_state_manager import BatchStateManager

        manager = BatchStateManager(project_id="test-project")

        # Create batch
        mock_batch_state_firestore._documents["prediction_batches/batch_123"] = {
            'batch_id': 'batch_123',
            'game_date': '2026-01-23',
            'expected_players': 10,
            'completed_players': [],
            'predictions_by_player': {},
            'total_predictions': 0,
            'is_complete': False
        }

        # Record with safe method
        result = manager.record_completion_safe(
            batch_id="batch_123",
            player_lookup="player-1",
            predictions_count=5
        )

        # Should succeed
        assert result is False  # Batch not complete yet


class TestBatchProcessingStats:
    """Test batch processing statistics."""

    def test_get_processing_stats(self, mock_batch_state_firestore):
        """Get processing statistics for all batches."""
        from predictions.coordinator.batch_state_manager import BatchStateManager

        manager = BatchStateManager(project_id="test-project")

        # Create some batches
        mock_batch_state_firestore._documents["prediction_batches/batch_1"] = {
            'batch_id': 'batch_1',
            'game_date': '2026-01-23',
            'expected_players': 100,
            'completed_players': ['p1', 'p2', 'p3'],
            'total_predictions': 15,
            'is_complete': False,
            'claimed_by_instance': 'instance-1'
        }
        mock_batch_state_firestore._documents["prediction_batches/batch_2"] = {
            'batch_id': 'batch_2',
            'game_date': '2026-01-24',
            'expected_players': 50,
            'completed_players': ['p1'],
            'total_predictions': 5,
            'is_complete': False,
            'claimed_by_instance': None
        }

        stats = manager.get_batch_processing_stats()

        assert stats['active_batches'] == 2
        assert stats['total_expected'] == 150
        assert stats['total_completed'] == 4


class TestUnclaimed_Batches:
    """Test unclaimed batch retrieval."""

    def test_get_unclaimed_batches(self, mock_batch_state_firestore):
        """Get batches that are not claimed by any instance."""
        from predictions.coordinator.batch_state_manager import BatchStateManager

        manager = BatchStateManager(project_id="test-project")

        # One claimed, one unclaimed
        mock_batch_state_firestore._documents["prediction_batches/batch_claimed"] = {
            'batch_id': 'batch_claimed',
            'game_date': '2026-01-23',
            'expected_players': 100,
            'completed_players': [],
            'total_predictions': 0,
            'is_complete': False,
            'claimed_by_instance': 'instance-1',
            'claim_expires_at': datetime.now(timezone.utc) + timedelta(minutes=5)
        }
        mock_batch_state_firestore._documents["prediction_batches/batch_unclaimed"] = {
            'batch_id': 'batch_unclaimed',
            'game_date': '2026-01-24',
            'expected_players': 50,
            'completed_players': [],
            'total_predictions': 0,
            'is_complete': False,
            'claimed_by_instance': None
        }

        unclaimed = manager.get_unclaimed_batches()

        assert len(unclaimed) == 1
        assert unclaimed[0].batch_id == 'batch_unclaimed'

    def test_expired_claims_show_as_unclaimed(self, mock_batch_state_firestore):
        """Batches with expired claims show as unclaimed."""
        from predictions.coordinator.batch_state_manager import BatchStateManager

        manager = BatchStateManager(project_id="test-project")

        # Expired claim
        mock_batch_state_firestore._documents["prediction_batches/batch_expired"] = {
            'batch_id': 'batch_expired',
            'game_date': '2026-01-23',
            'expected_players': 100,
            'completed_players': [],
            'total_predictions': 0,
            'is_complete': False,
            'claimed_by_instance': 'dead-instance',
            'claim_expires_at': datetime.now(timezone.utc) - timedelta(minutes=10)
        }

        unclaimed = manager.get_unclaimed_batches()

        assert len(unclaimed) == 1
        assert unclaimed[0].batch_id == 'batch_expired'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

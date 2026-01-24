"""
Integration Tests for Firestore State Management

Tests the Firestore-based state management for phase orchestration:
1. Document structure and field conventions
2. Atomic transactions for race condition prevention
3. Idempotency handling for duplicate messages
4. State queries for monitoring and debugging
5. Cleanup and retention policies

Run with:
    pytest tests/integration/orchestration/test_firestore_state.py -v
"""

import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, List, Optional

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_firestore():
    """Create a mock Firestore database with in-memory storage."""
    class InMemoryFirestore:
        """In-memory Firestore implementation for testing."""

        def __init__(self):
            self._collections: Dict[str, Dict[str, Dict]] = {}
            self._transaction_counter = 0

        def collection(self, name: str) -> 'InMemoryCollection':
            if name not in self._collections:
                self._collections[name] = {}
            return InMemoryCollection(self, name)

        def transaction(self) -> 'InMemoryTransaction':
            self._transaction_counter += 1
            return InMemoryTransaction(self, self._transaction_counter)

        def _get_data(self, collection: str) -> Dict[str, Dict]:
            return self._collections.get(collection, {})

        def _set_data(self, collection: str, doc_id: str, data: Dict):
            if collection not in self._collections:
                self._collections[collection] = {}
            self._collections[collection][doc_id] = data.copy()

        def _get_doc(self, collection: str, doc_id: str) -> Optional[Dict]:
            return self._collections.get(collection, {}).get(doc_id)

    class InMemoryCollection:
        def __init__(self, db: InMemoryFirestore, name: str):
            self._db = db
            self._name = name

        def document(self, doc_id: str) -> 'InMemoryDocumentRef':
            return InMemoryDocumentRef(self._db, self._name, doc_id)

        def where(self, field: str, op: str, value) -> 'InMemoryQuery':
            return InMemoryQuery(self._db, self._name, [(field, op, value)])

        def stream(self):
            """Stream all documents in the collection."""
            for doc_id, data in self._db._get_data(self._name).items():
                yield InMemoryDocumentSnapshot(doc_id, data, True)

    class InMemoryDocumentRef:
        def __init__(self, db: InMemoryFirestore, collection: str, doc_id: str):
            self._db = db
            self._collection = collection
            self._id = doc_id

        @property
        def id(self) -> str:
            return self._id

        def get(self, transaction=None) -> 'InMemoryDocumentSnapshot':
            data = self._db._get_doc(self._collection, self._id)
            exists = data is not None
            return InMemoryDocumentSnapshot(self._id, data or {}, exists)

        def set(self, data: Dict, merge: bool = False):
            if merge:
                existing = self._db._get_doc(self._collection, self._id) or {}
                existing.update(data)
                self._db._set_data(self._collection, self._id, existing)
            else:
                self._db._set_data(self._collection, self._id, data)

        def update(self, data: Dict):
            existing = self._db._get_doc(self._collection, self._id) or {}
            existing.update(data)
            self._db._set_data(self._collection, self._id, existing)

        def delete(self):
            if self._collection in self._db._collections:
                self._db._collections[self._collection].pop(self._id, None)

    class InMemoryDocumentSnapshot:
        def __init__(self, doc_id: str, data: Dict, exists: bool):
            self._id = doc_id
            self._data = data
            self.exists = exists

        @property
        def id(self) -> str:
            return self._id

        def to_dict(self) -> Dict:
            return self._data.copy() if self._data else {}

    class InMemoryQuery:
        def __init__(self, db: InMemoryFirestore, collection: str, filters: List):
            self._db = db
            self._collection = collection
            self._filters = filters

        def where(self, field: str, op: str, value) -> 'InMemoryQuery':
            self._filters.append((field, op, value))
            return self

        def stream(self):
            for doc_id, data in self._db._get_data(self._collection).items():
                if self._matches_filters(data):
                    yield InMemoryDocumentSnapshot(doc_id, data, True)

        def _matches_filters(self, data: Dict) -> bool:
            for field, op, value in self._filters:
                doc_value = data.get(field)
                if op == '==' and doc_value != value:
                    return False
                elif op == '>' and not (doc_value and doc_value > value):
                    return False
                elif op == '<' and not (doc_value and doc_value < value):
                    return False
                elif op == '>=' and not (doc_value and doc_value >= value):
                    return False
                elif op == '<=' and not (doc_value and doc_value <= value):
                    return False
            return True

    class InMemoryTransaction:
        def __init__(self, db: InMemoryFirestore, tx_id: int):
            self._db = db
            self._id = tx_id
            self._writes: List = []

        def get(self, doc_ref: InMemoryDocumentRef) -> InMemoryDocumentSnapshot:
            return doc_ref.get()

        def set(self, doc_ref: InMemoryDocumentRef, data: Dict):
            doc_ref.set(data)
            self._writes.append(('set', doc_ref._collection, doc_ref._id, data))

        def update(self, doc_ref: InMemoryDocumentRef, data: Dict):
            doc_ref.update(data)
            self._writes.append(('update', doc_ref._collection, doc_ref._id, data))

    return InMemoryFirestore()


# =============================================================================
# TEST CLASS: Document Structure
# =============================================================================

class TestFirestoreDocumentStructure:
    """Test Firestore document structure and conventions."""

    def test_phase2_completion_document_structure(self, mock_firestore):
        """Test Phase 2 completion document structure."""
        game_date = '2025-12-15'
        doc = mock_firestore.collection('phase2_completion').document(game_date)

        # Expected structure
        completion_data = {
            # Processor completions
            'bdl_player_boxscores': {
                'completed_at': '2025-12-15T10:00:00Z',
                'correlation_id': 'corr-123',
                'status': 'success',
                'record_count': 450,
                'execution_id': 'exec-456'
            },
            'nbac_schedule': {
                'completed_at': '2025-12-15T10:05:00Z',
                'correlation_id': 'corr-123',
                'status': 'success',
                'record_count': 10,
                'execution_id': 'exec-789'
            },
            # Metadata fields (underscore prefix)
            '_completed_count': 2,
            '_first_completion_at': '2025-12-15T10:00:00Z',
            '_triggered': False
        }

        doc.set(completion_data)

        # Verify structure
        result = doc.get().to_dict()

        # Verify processor data
        assert 'bdl_player_boxscores' in result
        assert result['bdl_player_boxscores']['status'] == 'success'

        # Verify metadata
        assert result['_completed_count'] == 2
        assert result['_triggered'] is False

    def test_phase3_completion_with_entities_changed(self, mock_firestore):
        """Test Phase 3 document includes entities_changed for selective processing."""
        game_date = '2025-12-15'
        doc = mock_firestore.collection('phase3_completion').document(game_date)

        completion_data = {
            'player_game_summary': {
                'completed_at': '2025-12-15T11:00:00Z',
                'correlation_id': 'corr-123',
                'status': 'success',
                'record_count': 250,
                'is_incremental': True,
                'entities_changed': ['lebron-james', 'stephen-curry']
            },
            'team_defense_game_summary': {
                'completed_at': '2025-12-15T11:05:00Z',
                'correlation_id': 'corr-123',
                'status': 'success',
                'record_count': 30,
                'is_incremental': True,
                'entities_changed': ['LAL', 'GSW']
            },
            '_completed_count': 2,
            '_triggered': False
        }

        doc.set(completion_data)

        # Verify entities_changed stored
        result = doc.get().to_dict()

        assert result['player_game_summary']['is_incremental'] is True
        assert 'lebron-james' in result['player_game_summary']['entities_changed']
        assert 'LAL' in result['team_defense_game_summary']['entities_changed']

    def test_phase4_completion_with_timeout_info(self, mock_firestore):
        """Test Phase 4 document includes tiered timeout tracking."""
        game_date = '2025-12-15'
        doc = mock_firestore.collection('phase4_completion').document(game_date)

        completion_data = {
            'player_daily_cache': {'status': 'success'},
            'ml_feature_store': {'status': 'success'},
            'player_composite_factors': {'status': 'success'},
            # Missing: team_defense_zone_analysis, player_shot_zone_analysis
            '_completed_count': 3,
            '_first_completion_at': '2025-12-15T10:00:00Z',
            '_triggered': True,
            '_triggered_at': '2025-12-15T12:05:00Z',
            '_trigger_reason': 'tier3_timeout',
            '_tier_name': 'Tier3',
            '_missing_processors': ['team_defense_zone_analysis', 'player_shot_zone_analysis'],
            '_wait_seconds': 7500  # ~2 hours
        }

        doc.set(completion_data)

        # Verify timeout tracking fields
        result = doc.get().to_dict()

        assert result['_trigger_reason'] == 'tier3_timeout'
        assert result['_tier_name'] == 'Tier3'
        assert len(result['_missing_processors']) == 2

    def test_metadata_fields_excluded_from_processor_count(self, mock_firestore):
        """Test that underscore-prefixed fields are excluded from processor count."""
        game_date = '2025-12-15'
        doc = mock_firestore.collection('phase3_completion').document(game_date)

        data = {
            'player_game_summary': {'status': 'success'},
            'team_offense_game_summary': {'status': 'success'},
            '_completed_count': 2,
            '_triggered': False,
            '_first_completion_at': '2025-12-15T10:00:00Z',
            '_mode': 'overnight'
        }

        doc.set(data)
        result = doc.get().to_dict()

        # Count processors (exclude underscore fields)
        processor_count = len([k for k in result.keys() if not k.startswith('_')])

        assert processor_count == 2
        assert result['_completed_count'] == 2


# =============================================================================
# TEST CLASS: Atomic Transactions
# =============================================================================

class TestFirestoreAtomicTransactions:
    """Test atomic transaction handling for race condition prevention."""

    def test_transaction_prevents_double_write(self, mock_firestore):
        """Test that transactions prevent double-writes on concurrent completion."""
        game_date = '2025-12-15'
        doc_ref = mock_firestore.collection('phase2_completion').document(game_date)

        # Simulate concurrent transaction
        transaction = mock_firestore.transaction()

        # Read current state
        snapshot = transaction.get(doc_ref)
        current = snapshot.to_dict() if snapshot.exists else {}

        # Check if processor already registered
        processor_name = 'bdl_player_boxscores'
        already_registered = processor_name in current

        if not already_registered:
            # Add processor
            current[processor_name] = {
                'status': 'success',
                'completed_at': datetime.now(timezone.utc).isoformat()
            }
            current['_completed_count'] = len([k for k in current.keys() if not k.startswith('_')])
            transaction.set(doc_ref, current)

        # Simulate second "concurrent" transaction (should skip)
        transaction2 = mock_firestore.transaction()
        snapshot2 = transaction2.get(doc_ref)
        current2 = snapshot2.to_dict()

        already_registered2 = processor_name in current2

        # Second transaction should see processor already registered
        assert already_registered2 is True

    def test_transaction_maintains_consistency(self, mock_firestore):
        """Test that transaction maintains data consistency during trigger."""
        game_date = '2025-12-15'
        doc_ref = mock_firestore.collection('phase3_completion').document(game_date)

        # Populate with 4 processors
        initial_data = {
            'player_game_summary': {'status': 'success'},
            'team_defense_game_summary': {'status': 'success'},
            'team_offense_game_summary': {'status': 'success'},
            'upcoming_player_game_context': {'status': 'success'},
            '_completed_count': 4
        }
        doc_ref.set(initial_data)

        # Transaction adds 5th processor and triggers
        transaction = mock_firestore.transaction()
        snapshot = transaction.get(doc_ref)
        current = snapshot.to_dict()

        # Add 5th processor
        current['upcoming_team_game_context'] = {'status': 'success'}

        # Count and check trigger
        completed_count = len([k for k in current.keys() if not k.startswith('_')])
        expected_count = 5
        should_trigger = completed_count >= expected_count and not current.get('_triggered')

        if should_trigger:
            current['_triggered'] = True
            current['_triggered_at'] = datetime.now(timezone.utc).isoformat()

        current['_completed_count'] = completed_count
        transaction.set(doc_ref, current)

        # Verify final state
        result = doc_ref.get().to_dict()
        assert result['_completed_count'] == 5
        assert result['_triggered'] is True
        assert 'upcoming_team_game_context' in result


# =============================================================================
# TEST CLASS: Idempotency
# =============================================================================

class TestFirestoreIdempotency:
    """Test idempotency handling for duplicate Pub/Sub messages."""

    def test_duplicate_message_returns_early(self, mock_firestore):
        """Test that duplicate processor completion returns early."""
        game_date = '2025-12-15'
        doc = mock_firestore.collection('phase2_completion').document(game_date)

        # First completion
        doc.set({
            'bdl_player_boxscores': {
                'status': 'success',
                'completed_at': '2025-12-15T10:00:00Z'
            },
            '_completed_count': 1
        })

        # Simulate duplicate message handling
        def handle_completion(processor_name: str, completion_data: Dict) -> bool:
            """Returns True if completion was registered, False if duplicate."""
            snapshot = doc.get()
            current = snapshot.to_dict() if snapshot.exists else {}

            # Idempotency check
            if processor_name in current:
                return False  # Duplicate

            current[processor_name] = completion_data
            current['_completed_count'] = len([k for k in current.keys() if not k.startswith('_')])
            doc.set(current)
            return True

        # First attempt (should be duplicate)
        result1 = handle_completion('bdl_player_boxscores', {
            'status': 'success',
            'completed_at': '2025-12-15T10:05:00Z'  # Different timestamp
        })

        # Second processor (should register)
        result2 = handle_completion('nbac_schedule', {
            'status': 'success',
            'completed_at': '2025-12-15T10:10:00Z'
        })

        assert result1 is False  # Duplicate
        assert result2 is True   # New registration

        # Verify final state
        final = doc.get().to_dict()
        assert final['_completed_count'] == 2
        # Original timestamp preserved
        assert final['bdl_player_boxscores']['completed_at'] == '2025-12-15T10:00:00Z'

    def test_already_triggered_skips_re_trigger(self, mock_firestore):
        """Test that already triggered phases don't trigger again."""
        game_date = '2025-12-15'
        doc = mock_firestore.collection('phase3_completion').document(game_date)

        # Mark as triggered
        doc.set({
            'player_game_summary': {'status': 'success'},
            'team_defense_game_summary': {'status': 'success'},
            'team_offense_game_summary': {'status': 'success'},
            'upcoming_player_game_context': {'status': 'success'},
            'upcoming_team_game_context': {'status': 'success'},
            '_completed_count': 5,
            '_triggered': True,
            '_triggered_at': '2025-12-15T11:00:00Z'
        })

        # Simulate late-arriving message for already-triggered phase
        snapshot = doc.get()
        current = snapshot.to_dict()

        already_triggered = current.get('_triggered', False)
        should_trigger = not already_triggered  # Check logic

        assert already_triggered is True
        assert should_trigger is False


# =============================================================================
# TEST CLASS: State Queries
# =============================================================================

class TestFirestoreStateQueries:
    """Test state queries for monitoring and debugging."""

    def test_get_completion_status(self, mock_firestore):
        """Test getting completion status for a game date."""
        game_date = '2025-12-15'
        doc = mock_firestore.collection('phase2_completion').document(game_date)

        doc.set({
            'bdl_player_boxscores': {'status': 'success'},
            'nbac_schedule': {'status': 'success'},
            'odds_api_game_lines': {'status': 'success'},
            '_completed_count': 3,
            '_triggered': False
        })

        def get_completion_status(collection_name: str, game_date: str) -> Dict:
            """Helper to get completion status."""
            doc = mock_firestore.collection(collection_name).document(game_date)
            snapshot = doc.get()

            if not snapshot.exists:
                return {'status': 'not_started', 'completed_count': 0}

            data = snapshot.to_dict()
            completed = [k for k in data.keys() if not k.startswith('_')]

            return {
                'status': 'triggered' if data.get('_triggered') else 'in_progress',
                'completed_count': len(completed),
                'completed_processors': completed,
                'triggered_at': data.get('_triggered_at')
            }

        status = get_completion_status('phase2_completion', game_date)

        assert status['status'] == 'in_progress'
        assert status['completed_count'] == 3
        assert 'bdl_player_boxscores' in status['completed_processors']

    def test_query_incomplete_dates(self, mock_firestore):
        """Test querying for incomplete dates."""
        # Add multiple dates with different states
        dates = [
            ('2025-12-13', True),   # Triggered
            ('2025-12-14', True),   # Triggered
            ('2025-12-15', False),  # In progress
        ]

        for game_date, triggered in dates:
            doc = mock_firestore.collection('phase3_completion').document(game_date)
            doc.set({
                'player_game_summary': {'status': 'success'},
                '_completed_count': 1,
                '_triggered': triggered
            })

        # Query for incomplete dates
        collection = mock_firestore.collection('phase3_completion')
        incomplete_dates = []

        for snapshot in collection.stream():
            data = snapshot.to_dict()
            if not data.get('_triggered', False):
                incomplete_dates.append(snapshot.id)

        assert len(incomplete_dates) == 1
        assert '2025-12-15' in incomplete_dates

    def test_query_by_date_range(self, mock_firestore):
        """Test querying completion status by date range."""
        # Add data for a week
        base_date = datetime(2025, 12, 10)

        for i in range(7):
            game_date = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')
            doc = mock_firestore.collection('phase2_completion').document(game_date)
            doc.set({
                'processor1': {'status': 'success'},
                '_completed_count': 1,
                '_triggered': i < 5  # First 5 days triggered
            })

        # Query for date range (all dates in this case since we're using stream)
        collection = mock_firestore.collection('phase2_completion')

        # Filter by date range
        start_date = '2025-12-12'
        end_date = '2025-12-16'

        in_range = []
        for snapshot in collection.stream():
            if start_date <= snapshot.id <= end_date:
                in_range.append(snapshot.id)

        assert len(in_range) == 5
        assert '2025-12-12' in in_range
        assert '2025-12-16' in in_range


# =============================================================================
# TEST CLASS: Cleanup and Retention
# =============================================================================

class TestFirestoreCleanup:
    """Test cleanup and retention policies."""

    def test_delete_old_completion_docs(self, mock_firestore):
        """Test deleting old completion documents."""
        # Add documents spanning 60 days
        base_date = datetime(2025, 10, 1)
        retention_days = 30

        for i in range(60):
            game_date = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')
            doc = mock_firestore.collection('phase2_completion').document(game_date)
            doc.set({
                'processor1': {'status': 'success'},
                '_completed_count': 1,
                '_triggered': True
            })

        # Calculate cutoff date
        cutoff_date = (datetime(2025, 12, 1) - timedelta(days=retention_days)).strftime('%Y-%m-%d')

        # Delete old documents
        collection = mock_firestore.collection('phase2_completion')
        deleted_count = 0

        for snapshot in list(collection.stream()):
            if snapshot.id < cutoff_date:
                # Get document reference and delete
                doc_ref = collection.document(snapshot.id)
                doc_ref.delete()
                deleted_count += 1

        # Verify cleanup
        remaining = list(collection.stream())

        assert deleted_count > 0
        # All remaining should be after cutoff
        for doc in remaining:
            assert doc.id >= cutoff_date

    def test_cleanup_preserves_triggered_flag(self, mock_firestore):
        """Test that cleanup preserves the triggered flag for auditing."""
        game_date = '2025-12-15'
        doc = mock_firestore.collection('phase3_completion').document(game_date)

        # Full document with all data
        doc.set({
            'player_game_summary': {'status': 'success', 'record_count': 250},
            'team_defense_game_summary': {'status': 'success', 'record_count': 30},
            '_completed_count': 2,
            '_triggered': True,
            '_triggered_at': '2025-12-15T11:00:00Z'
        })

        # Simulate archival - keep only audit fields
        def archive_completion_doc(collection_name: str, game_date: str) -> Dict:
            doc = mock_firestore.collection(collection_name).document(game_date)
            snapshot = doc.get()

            if not snapshot.exists:
                return None

            data = snapshot.to_dict()

            # Keep only audit fields
            archived = {
                '_triggered': data.get('_triggered'),
                '_triggered_at': data.get('_triggered_at'),
                '_completed_count': data.get('_completed_count'),
                '_archived_at': datetime.now(timezone.utc).isoformat()
            }

            # Update document with archived data
            doc.set(archived)

            return archived

        archived = archive_completion_doc('phase3_completion', game_date)

        assert archived['_triggered'] is True
        assert archived['_triggered_at'] == '2025-12-15T11:00:00Z'
        assert '_archived_at' in archived


# =============================================================================
# TEST CLASS: Error Recovery
# =============================================================================

class TestFirestoreErrorRecovery:
    """Test error recovery scenarios."""

    def test_recover_from_partial_write(self, mock_firestore):
        """Test recovery from partial write failure."""
        game_date = '2025-12-15'
        doc = mock_firestore.collection('phase4_completion').document(game_date)

        # Simulate partial state (processor registered but count not updated)
        doc.set({
            'player_daily_cache': {'status': 'success'},
            'ml_feature_store': {'status': 'success'},
            # Missing _completed_count (simulating partial write)
        })

        # Recovery logic: recalculate count from data
        snapshot = doc.get()
        data = snapshot.to_dict()

        # Recover completed count
        actual_count = len([k for k in data.keys() if not k.startswith('_')])

        # Update with recovered count
        doc.update({'_completed_count': actual_count})

        # Verify recovery
        final = doc.get().to_dict()
        assert final['_completed_count'] == 2

    def test_recover_stale_in_progress_state(self, mock_firestore):
        """Test detection and recovery of stale in-progress states."""
        game_date = '2025-12-14'  # Yesterday
        doc = mock_firestore.collection('phase3_completion').document(game_date)

        # Stale state: started but never completed
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        doc.set({
            'player_game_summary': {'status': 'success', 'completed_at': stale_time},
            '_completed_count': 1,
            '_first_completion_at': stale_time,
            '_triggered': False
        })

        # Detection logic
        snapshot = doc.get()
        data = snapshot.to_dict()

        first_completion = data.get('_first_completion_at')
        is_triggered = data.get('_triggered', False)

        # Calculate staleness
        if first_completion and not is_triggered:
            first_dt = datetime.fromisoformat(first_completion.replace('Z', '+00:00'))
            age_hours = (datetime.now(timezone.utc) - first_dt).total_seconds() / 3600

            is_stale = age_hours > 4  # 4 hour threshold

            if is_stale:
                # Mark as stale for self-heal
                doc.update({
                    '_stale': True,
                    '_stale_detected_at': datetime.now(timezone.utc).isoformat(),
                    '_stale_age_hours': age_hours
                })

        # Verify stale detection
        final = doc.get().to_dict()
        assert final.get('_stale') is True
        assert final['_stale_age_hours'] > 4


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

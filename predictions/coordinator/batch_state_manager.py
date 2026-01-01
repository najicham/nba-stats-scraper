"""
Batch State Manager - Persistent state storage for prediction batches

This module provides persistent state storage using Firestore to survive
container restarts and enable stateless coordinator operation.

Key Problem Solved:
- Coordinator containers can restart (scale to zero, deployments, crashes)
- In-memory state (ProgressTracker) is lost on restart
- Completion events are ignored → consolidation never triggers
- Solution: Store all batch state in Firestore

Firestore Schema:
Collection: prediction_batches
Document ID: {batch_id}
Fields:
  - batch_id: str (e.g., "batch_2026-01-01_1767268807")
  - game_date: str (e.g., "2026-01-01")
  - expected_players: int (e.g., 120)
  - completed_players: list of str (e.g., ["lebron-james", ...])
  - failed_players: list of str
  - predictions_by_player: map (e.g., {"lebron-james": 25, ...})
  - total_predictions: int
  - is_complete: bool
  - start_time: timestamp
  - completion_time: timestamp (optional)
  - correlation_id: str (optional)
  - dataset_prefix: str (optional)
  - created_at: timestamp (server timestamp)
  - updated_at: timestamp (server timestamp)

Author: Claude Code
Date: January 1, 2026
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Set, Optional
from google.cloud import firestore
from google.cloud.firestore import ArrayUnion, Increment, SERVER_TIMESTAMP
import logging

logger = logging.getLogger(__name__)


@dataclass
class BatchState:
    """
    Represents the state of a prediction batch

    This dataclass mirrors the ProgressTracker state but is designed
    for Firestore serialization (no Sets, uses Lists instead).
    """
    batch_id: str
    game_date: str
    expected_players: int
    completed_players: List[str] = field(default_factory=list)
    failed_players: List[str] = field(default_factory=list)
    predictions_by_player: Dict[str, int] = field(default_factory=dict)
    total_predictions: int = 0
    is_complete: bool = False
    start_time: Optional[datetime] = None
    completion_time: Optional[datetime] = None
    correlation_id: Optional[str] = None
    dataset_prefix: str = ""

    def to_firestore_dict(self) -> dict:
        """Convert to Firestore-compatible dictionary"""
        data = asdict(self)

        # Firestore doesn't like None timestamps - remove them
        if data.get('start_time') is None:
            data['start_time'] = firestore.SERVER_TIMESTAMP
        if data.get('completion_time') is None:
            del data['completion_time']

        # Add metadata
        data['updated_at'] = firestore.SERVER_TIMESTAMP
        if 'created_at' not in data:
            data['created_at'] = firestore.SERVER_TIMESTAMP

        return data

    @staticmethod
    def from_firestore_dict(data: dict) -> 'BatchState':
        """Create BatchState from Firestore document"""
        # Remove Firestore metadata that's not in our dataclass
        clean_data = {
            'batch_id': data.get('batch_id', ''),
            'game_date': data.get('game_date', ''),
            'expected_players': data.get('expected_players', 0),
            'completed_players': data.get('completed_players', []),
            'failed_players': data.get('failed_players', []),
            'predictions_by_player': data.get('predictions_by_player', {}),
            'total_predictions': data.get('total_predictions', 0),
            'is_complete': data.get('is_complete', False),
            'start_time': data.get('start_time'),
            'completion_time': data.get('completion_time'),
            'correlation_id': data.get('correlation_id'),
            'dataset_prefix': data.get('dataset_prefix', ''),
        }
        return BatchState(**clean_data)

    def get_completion_percentage(self) -> float:
        """Calculate completion percentage"""
        if self.expected_players == 0:
            return 0.0
        return (len(self.completed_players) / self.expected_players) * 100


class BatchStateManager:
    """
    Manages persistent batch state in Firestore

    This class handles all Firestore operations for batch tracking,
    making the coordinator stateless and resilient to restarts.

    Usage:
        manager = BatchStateManager(project_id="my-project")

        # Start a new batch
        state = manager.create_batch(
            batch_id="batch_2026-01-01_123",
            game_date="2026-01-01",
            expected_players=120
        )

        # Process completion event (thread-safe)
        is_complete = manager.record_completion(
            batch_id="batch_2026-01-01_123",
            player_lookup="lebron-james",
            predictions_count=25
        )

        # Get current state
        state = manager.get_batch_state("batch_2026-01-01_123")
    """

    COLLECTION_NAME = "prediction_batches"

    def __init__(self, project_id: str):
        """
        Initialize Firestore client

        Args:
            project_id: GCP project ID
        """
        self.project_id = project_id
        self.db = firestore.Client(project=project_id)
        self.collection = self.db.collection(self.COLLECTION_NAME)

        logger.info(f"BatchStateManager initialized for project: {project_id}")

    def create_batch(
        self,
        batch_id: str,
        game_date: str,
        expected_players: int,
        correlation_id: Optional[str] = None,
        dataset_prefix: str = ""
    ) -> BatchState:
        """
        Create a new batch and persist to Firestore

        Args:
            batch_id: Unique batch identifier
            game_date: Game date (YYYY-MM-DD)
            expected_players: Number of players expected
            correlation_id: Optional correlation ID for tracing
            dataset_prefix: Optional dataset prefix for testing

        Returns:
            BatchState object
        """
        state = BatchState(
            batch_id=batch_id,
            game_date=game_date,
            expected_players=expected_players,
            start_time=datetime.now(timezone.utc),
            correlation_id=correlation_id,
            dataset_prefix=dataset_prefix
        )

        # Write to Firestore
        doc_ref = self.collection.document(batch_id)
        doc_ref.set(state.to_firestore_dict())

        logger.info(
            f"Created batch state: {batch_id} "
            f"(expected_players={expected_players}, game_date={game_date})"
        )

        return state

    def get_batch_state(self, batch_id: str) -> Optional[BatchState]:
        """
        Retrieve batch state from Firestore

        Args:
            batch_id: Batch identifier

        Returns:
            BatchState object or None if not found
        """
        doc_ref = self.collection.document(batch_id)
        doc = doc_ref.get()

        if not doc.exists:
            logger.warning(f"Batch state not found: {batch_id}")
            return None

        return BatchState.from_firestore_dict(doc.to_dict())

    def record_completion(
        self,
        batch_id: str,
        player_lookup: str,
        predictions_count: int
    ) -> bool:
        """
        Record a player completion event using atomic operations (no transactions!)

        This avoids transaction contention when multiple workers complete simultaneously.
        Uses Firestore's atomic operations: ArrayUnion and Increment.

        Args:
            batch_id: Batch identifier
            player_lookup: Player identifier
            predictions_count: Number of predictions generated

        Returns:
            True if batch is now complete, False otherwise
        """
        try:
            doc_ref = self.collection.document(batch_id)

            # Atomic update - no read required, no contention!
            doc_ref.update({
                'completed_players': ArrayUnion([player_lookup]),
                'predictions_by_player.{}'.format(player_lookup): predictions_count,
                'total_predictions': Increment(predictions_count),
                'updated_at': SERVER_TIMESTAMP
            })

            logger.info(f"Recorded completion for {player_lookup} in batch {batch_id}")

            # Check if batch is complete (separate read, non-blocking)
            snapshot = doc_ref.get()
            if not snapshot.exists:
                logger.warning(f"Batch {batch_id} not found after update")
                return False

            data = snapshot.to_dict()
            completed = len(data.get('completed_players', []))
            expected = data.get('expected_players', 0)

            is_complete = completed >= expected

            if is_complete:
                # Mark as complete atomically
                doc_ref.update({
                    'is_complete': True,
                    'completion_time': SERVER_TIMESTAMP
                })
                logger.info(f"🎉 Batch {batch_id} complete! ({completed}/{expected} players)")
            else:
                logger.debug(f"Batch {batch_id} progress: {completed}/{expected}")

            return is_complete

        except Exception as e:
            logger.error(f"Error recording completion for {player_lookup}: {e}", exc_info=True)
            # Non-fatal - batch can continue
            return False

    def record_failure(
        self,
        batch_id: str,
        player_lookup: str,
        error: str
    ) -> None:
        """
        Record a player failure event

        Args:
            batch_id: Batch identifier
            player_lookup: Player identifier
            error: Error message
        """
        doc_ref = self.collection.document(batch_id)

        @firestore.transactional
        def update_in_transaction(transaction):
            snapshot = doc_ref.get(transaction=transaction)

            if not snapshot.exists:
                logger.error(f"Batch not found: {batch_id}")
                return

            data = snapshot.to_dict()
            failed_players = data.get('failed_players', [])

            if player_lookup not in failed_players:
                failed_players.append(player_lookup)

                transaction.update(doc_ref, {
                    'failed_players': failed_players,
                    'updated_at': firestore.SERVER_TIMESTAMP
                })

                logger.warning(
                    f"Player {player_lookup} failed: {error} "
                    f"(batch={batch_id})"
                )

        transaction = self.db.transaction()
        update_in_transaction(transaction)

    def mark_batch_complete(self, batch_id: str) -> None:
        """
        Explicitly mark a batch as complete

        Args:
            batch_id: Batch identifier
        """
        doc_ref = self.collection.document(batch_id)
        doc_ref.update({
            'is_complete': True,
            'completion_time': firestore.SERVER_TIMESTAMP,
            'updated_at': firestore.SERVER_TIMESTAMP
        })

        logger.info(f"Marked batch as complete: {batch_id}")

    def get_active_batches(self) -> List[BatchState]:
        """
        Get all active (incomplete) batches

        Returns:
            List of BatchState objects
        """
        query = self.collection.where('is_complete', '==', False)
        docs = query.stream()

        return [BatchState.from_firestore_dict(doc.to_dict()) for doc in docs]

    def cleanup_old_batches(self, days: int = 7) -> int:
        """
        Delete batch records older than specified days

        Args:
            days: Number of days to keep (default: 7)

        Returns:
            Number of batches deleted
        """
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        query = self.collection.where('start_time', '<', cutoff)
        docs = query.stream()

        count = 0
        for doc in docs:
            doc.reference.delete()
            count += 1
            logger.info(f"Deleted old batch: {doc.id}")

        logger.info(f"Cleaned up {count} old batch records")
        return count


# Singleton instance
_batch_state_manager: Optional[BatchStateManager] = None


def get_batch_state_manager(project_id: str) -> BatchStateManager:
    """
    Get or create singleton BatchStateManager instance

    Args:
        project_id: GCP project ID

    Returns:
        BatchStateManager instance
    """
    global _batch_state_manager

    if _batch_state_manager is None:
        _batch_state_manager = BatchStateManager(project_id)

    return _batch_state_manager

"""
Batch State Manager - Persistent state storage for prediction batches

This module provides persistent state storage using Firestore to survive
container restarts and enable stateless coordinator operation.

Key Problem Solved:
- Coordinator containers can restart (scale to zero, deployments, crashes)
- In-memory state (ProgressTracker) is lost on restart
- Completion events are ignored → consolidation never triggers
- Solution: Store all batch state in Firestore

Firestore Schema (Legacy - ArrayUnion):
Collection: prediction_batches
Document ID: {batch_id}
Fields:
  - batch_id: str (e.g., "batch_2026-01-01_1767268807")
  - game_date: str (e.g., "2026-01-01")
  - expected_players: int (e.g., 120)
  - completed_players: list of str (e.g., ["lebron-james", ...])  ⚠️ LIMIT: 1000 elements
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

Week 1 Update - Subcollection Migration:
New Schema (unlimited scalability):
Collection: prediction_batches/{batch_id}/completions
Document ID: {player_lookup}
Fields:
  - player_lookup: str
  - completed_at: timestamp
  - predictions_count: int

Additional batch fields for subcollection mode:
  - completed_count: int (counter, replaces array length)
  - total_predictions_subcoll: int (subcollection total)

Migration Strategy:
1. Dual-write mode: Write to both array AND subcollection (default)
2. Validate consistency between both structures
3. Switch reads to subcollection
4. Stop writing to array
5. Clean up array after validation

Author: Claude Code
Date: January 1, 2026
Updated: January 20, 2026 (Week 1 - Subcollection migration)
Updated: January 2026 (Multi-instance coordination support)
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Set, Optional, Callable
import logging
import os
import sys
import time

# Import Firestore retry utilities
from shared.utils.firestore_retry import (
    retry_on_firestore_error,
    retry_firestore_transaction,
    retry_firestore_critical,
)

# Add path for slack utilities (use relative path for Docker/cloud compatibility)
_current_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.dirname(os.path.dirname(_current_dir))
sys.path.append(os.path.join(_repo_root, 'orchestration', 'cloud_functions', 'self_heal'))

logger = logging.getLogger(__name__)

# Lazy-load firestore to avoid Python 3.13 import errors at module load time
def _get_firestore():
    """Lazy-load Firestore module to avoid import errors."""
    from google.cloud import firestore
    return firestore

def _get_firestore_helpers():
    """Lazy-load Firestore helper functions."""
    from google.cloud.firestore import ArrayUnion, Increment, SERVER_TIMESTAMP
    return ArrayUnion, Increment, SERVER_TIMESTAMP


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

        # Lazy-load Firestore helpers
        _, _, SERVER_TIMESTAMP = _get_firestore_helpers()

        # Firestore doesn't like None timestamps - remove them
        if data.get('start_time') is None:
            data['start_time'] = SERVER_TIMESTAMP
        if data.get('completion_time') is None:
            del data['completion_time']

        # Add metadata
        data['updated_at'] = SERVER_TIMESTAMP
        if 'created_at' not in data:
            data['created_at'] = SERVER_TIMESTAMP

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

        # Use pooled Firestore client
        from shared.clients import get_firestore_client
        self.db = get_firestore_client(project_id)
        self.collection = self.db.collection(self.COLLECTION_NAME)

        # Week 1: Feature flags for ArrayUnion → Subcollection migration
        self.enable_subcollection = os.getenv('ENABLE_SUBCOLLECTION_COMPLETIONS', 'false').lower() == 'true'
        self.dual_write_mode = os.getenv('DUAL_WRITE_MODE', 'true').lower() == 'true'
        self.use_subcollection_reads = os.getenv('USE_SUBCOLLECTION_READS', 'false').lower() == 'true'

        logger.info(
            f"BatchStateManager initialized for project: {project_id} "
            f"(subcollection_enabled={self.enable_subcollection}, "
            f"dual_write={self.dual_write_mode}, "
            f"subcollection_reads={self.use_subcollection_reads})"
        )

    @retry_on_firestore_error(max_attempts=3, base_delay=1.0)
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

    @retry_on_firestore_error(max_attempts=3, base_delay=0.5)
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

    @retry_firestore_critical
    def record_completion(
        self,
        batch_id: str,
        player_lookup: str,
        predictions_count: int
    ) -> bool:
        """
        Record a player completion event using atomic operations (no transactions!)

        Week 1 Update: Now supports dual-write pattern for ArrayUnion → Subcollection migration.

        CRITICAL FIX (Jan 25, 2026): Dual-write mode now uses transactions to prevent data corruption.
        Previously, array write and subcollection write were separate operations - if subcollection
        write failed after array write succeeded, data became inconsistent. Now both writes happen
        atomically within a single transaction.

        This avoids transaction contention when multiple workers complete simultaneously.
        Uses Firestore's atomic operations: ArrayUnion and Increment.

        Migration Modes (controlled by feature flags):
        1. Legacy mode (subcollection disabled): Write only to array
        2. Dual-write mode (default): Write to both array AND subcollection (TRANSACTIONAL)
        3. Subcollection-only mode: Write only to subcollection

        Note: This method uses @retry_firestore_critical decorator for aggressive retry
        (7 attempts, 2s base delay) because completion events MUST be recorded.

        Args:
            batch_id: Batch identifier
            player_lookup: Player identifier
            predictions_count: Number of predictions generated

        Returns:
            True if batch is now complete, False otherwise
        """
        try:
            doc_ref = self.collection.document(batch_id)

            # Lazy-load Firestore helpers
            ArrayUnion, Increment, SERVER_TIMESTAMP = _get_firestore_helpers()

            # Week 1: Implement dual-write pattern
            if self.enable_subcollection:
                if self.dual_write_mode:
                    # DUAL-WRITE MODE: Write to both old and new (TRANSACTIONAL)
                    logger.debug(f"Dual-write mode: Recording {player_lookup} to both structures (transactional)")

                    # Use transaction to ensure atomicity
                    self._record_completion_dual_write_transactional(
                        batch_id,
                        player_lookup,
                        predictions_count
                    )

                    # Validate consistency (every 10th completion to reduce overhead)
                    import random
                    if random.random() < 0.1:  # 10% sampling
                        self._validate_dual_write_consistency(batch_id)

                else:
                    # NEW STRUCTURE ONLY: Only write to subcollection
                    logger.debug(f"Subcollection mode: Recording {player_lookup} to subcollection only")
                    self._record_completion_subcollection(batch_id, player_lookup, predictions_count)

            else:
                # OLD BEHAVIOR: Only ArrayUnion (legacy mode)
                # NOTE: Removed predictions_by_player.{player} field path update
                # because hyphens in player_lookup cause Firestore ValueError:
                # "Non-alphanum char in element with leading alpha: player-name"
                logger.debug(f"Legacy mode: Recording {player_lookup} to array only")
                doc_ref.update({
                    'completed_players': ArrayUnion([player_lookup]),
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

            # Week 1: Use appropriate source for completion count
            if self.enable_subcollection and self.use_subcollection_reads:
                # Read from subcollection counter
                completed = data.get('completed_count', 0)
            else:
                # Read from array
                completed = len(data.get('completed_players', []))

            expected = data.get('expected_players', 0)

            is_complete = completed >= expected
            completion_pct = (completed / expected * 100) if expected > 0 else 0

            if is_complete:
                # Mark as complete atomically
                doc_ref.update({
                    'is_complete': True,
                    'completion_time': SERVER_TIMESTAMP
                })
                logger.info(f"🎉 Batch {batch_id} complete! ({completed}/{expected} players)")
            else:
                logger.debug(f"Batch {batch_id} progress: {completed}/{expected} ({completion_pct:.1f}%)")

                # Check if we should trigger stall completion (95%+ and waiting)
                # This runs on every completion event after 95% threshold
                if completion_pct >= 95.0:
                    stall_completed = self.check_and_complete_stalled_batch(
                        batch_id=batch_id,
                        stall_threshold_minutes=10,
                        min_completion_pct=95.0
                    )
                    if stall_completed:
                        return True

            return is_complete

        except Exception as e:
            logger.error(f"Error recording completion for {player_lookup}: {e}", exc_info=True)
            # Non-fatal - batch can continue
            return False

    @retry_firestore_transaction
    def record_failure(
        self,
        batch_id: str,
        player_lookup: str,
        error: str
    ) -> None:
        """
        Record a player failure event

        Note: Uses @retry_firestore_transaction decorator because this method
        uses Firestore transactions which can fail due to contention.

        Args:
            batch_id: Batch identifier
            player_lookup: Player identifier
            error: Error message
        """
        doc_ref = self.collection.document(batch_id)

        # Lazy-load Firestore helpers
        firestore = _get_firestore()
        _, _, SERVER_TIMESTAMP = _get_firestore_helpers()

        @firestore.transactional
        def update_in_transaction(transaction):
            snapshot = doc_ref.get(transaction=transaction)

            if not snapshot.exists:
                logger.error(f"Batch not found: {batch_id}", exc_info=True)
                return

            data = snapshot.to_dict()
            failed_players = data.get('failed_players', [])

            if player_lookup not in failed_players:
                failed_players.append(player_lookup)

                transaction.update(doc_ref, {
                    'failed_players': failed_players,
                    'updated_at': SERVER_TIMESTAMP
                })

                logger.warning(
                    f"Player {player_lookup} failed: {error} "
                    f"(batch={batch_id})"
                )

        transaction = self.db.transaction()
        update_in_transaction(transaction)

    # ============================================================================
    # Week 1: Subcollection Migration Methods
    # ============================================================================

    def _record_completion_dual_write_transactional(
        self,
        batch_id: str,
        player_lookup: str,
        predictions_count: int
    ) -> None:
        """
        CRITICAL FIX (Jan 25, 2026): Transactional dual-write to prevent data corruption.

        Writes to both array (old) and subcollection (new) structures atomically.
        If either write fails, both are rolled back to maintain consistency.

        This fixes the P0 bug where subcollection write could fail after array write
        succeeded, causing data inconsistency.

        Args:
            batch_id: Batch identifier
            player_lookup: Player identifier
            predictions_count: Number of predictions generated
        """
        firestore = _get_firestore()
        ArrayUnion, Increment, SERVER_TIMESTAMP = _get_firestore_helpers()

        batch_ref = self.collection.document(batch_id)
        completion_ref = batch_ref.collection('completions').document(player_lookup)

        @firestore.transactional
        def dual_write_in_transaction(transaction):
            """
            Perform both writes atomically within transaction.

            This ensures that either both writes succeed or both fail.
            No partial state is possible.
            """
            # Write to OLD structure (ArrayUnion)
            # NOTE: Removed predictions_by_player.{player} field path update
            # because hyphens in player_lookup cause Firestore ValueError
            transaction.update(batch_ref, {
                'completed_players': ArrayUnion([player_lookup]),
                'total_predictions': Increment(predictions_count),
                'updated_at': SERVER_TIMESTAMP
            })

            # Write to NEW structure (subcollection)
            transaction.set(completion_ref, {
                'completed_at': SERVER_TIMESTAMP,
                'predictions_count': predictions_count,
                'player_lookup': player_lookup
            })

            # Update subcollection counters
            transaction.update(batch_ref, {
                'completed_count': Increment(1),
                'total_predictions_subcoll': Increment(predictions_count),
                'last_updated': SERVER_TIMESTAMP
            })

        # Execute transaction
        transaction = self.db.transaction()
        dual_write_in_transaction(transaction)

        logger.debug(f"Recorded completion for {player_lookup} in both structures (transactional)")

    def _record_completion_subcollection(
        self,
        batch_id: str,
        player_lookup: str,
        predictions_count: int
    ) -> None:
        """
        Week 1: Record completion in subcollection (new approach).

        Structure:
        prediction_batches/{batch_id}/completions/{player_lookup}
        {
            completed_at: timestamp,
            predictions_count: int,
            player_lookup: str
        }

        Args:
            batch_id: Batch identifier
            player_lookup: Player identifier
            predictions_count: Number of predictions generated
        """
        # Lazy-load Firestore helpers
        _, Increment, SERVER_TIMESTAMP = _get_firestore_helpers()

        batch_ref = self.collection.document(batch_id)
        completion_ref = batch_ref.collection('completions').document(player_lookup)

        # Write completion document
        completion_ref.set({
            'completed_at': SERVER_TIMESTAMP,
            'predictions_count': predictions_count,
            'player_lookup': player_lookup
        })

        # Update counters atomically
        batch_ref.update({
            'completed_count': Increment(1),
            'total_predictions_subcoll': Increment(predictions_count),
            'last_updated': SERVER_TIMESTAMP
        })

        logger.debug(f"Recorded completion for {player_lookup} in subcollection")

    def _get_completed_players_subcollection(self, batch_id: str) -> List[str]:
        """
        Week 1: Get completed players from subcollection (new approach).

        Args:
            batch_id: Batch identifier

        Returns:
            List of player_lookup strings
        """
        batch_ref = self.collection.document(batch_id)
        completions = batch_ref.collection('completions').stream()

        completed_players = [comp.id for comp in completions]
        logger.debug(f"Retrieved {len(completed_players)} completed players from subcollection")

        return completed_players

    def _get_completion_count_subcollection(self, batch_id: str) -> int:
        """
        Week 1: Get completion count from counter (efficient).

        Args:
            batch_id: Batch identifier

        Returns:
            Number of completions
        """
        batch_ref = self.collection.document(batch_id)
        batch_doc = batch_ref.get()

        if batch_doc.exists:
            return batch_doc.to_dict().get('completed_count', 0)

        return 0

    def _validate_dual_write_consistency(self, batch_id: str) -> None:
        """
        Week 1: Validate that array and subcollection have same count.
        Log warning if mismatch detected.

        Args:
            batch_id: Batch identifier
        """
        try:
            # Get array count
            batch_doc = self.collection.document(batch_id).get()
            if not batch_doc.exists:
                return

            data = batch_doc.to_dict()
            array_count = len(data.get('completed_players', []))

            # Get subcollection count
            subcoll_count = self._get_completion_count_subcollection(batch_id)

            if array_count != subcoll_count:
                error_msg = (
                    f"⚠️ CONSISTENCY MISMATCH: Batch {batch_id} has {array_count} "
                    f"in array but {subcoll_count} in subcollection!"
                )
                logger.warning(error_msg)

                # Send Slack alert to dedicated Week 1 consistency monitoring channel
                try:
                    from shared.utils.slack_channels import send_to_slack
                    # Use dedicated consistency channel (e.g., #week-1-consistency-monitoring)
                    # Falls back to general warnings channel if not set
                    webhook_url = os.environ.get('SLACK_WEBHOOK_URL_CONSISTENCY') or \
                                  os.environ.get('SLACK_WEBHOOK_URL_WARNING')
                    if webhook_url:
                        alert_text = f"""🚨 *Dual-Write Consistency Mismatch*

*Batch*: `{batch_id}`
*Array Count*: {array_count}
*Subcollection Count*: {subcoll_count}
*Difference*: {abs(array_count - subcoll_count)}

This indicates a problem with the Week 1 dual-write migration. Investigate immediately.

_Check Cloud Logging for detailed error traces._"""

                        sent = send_to_slack(
                            webhook_url=webhook_url,
                            text=alert_text,
                            username="Prediction Coordinator",
                            icon_emoji=":rotating_light:"
                        )
                        if sent:
                            logger.info(f"Sent consistency mismatch alert to Slack for batch {batch_id}")
                        else:
                            logger.error(f"Failed to send Slack alert for batch {batch_id}", exc_info=True)
                    else:
                        logger.warning("SLACK_WEBHOOK_URL_WARNING not configured, skipping alert")
                except Exception as slack_error:
                    logger.error(f"Error sending Slack alert: {slack_error}", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to validate dual-write consistency: {e}", exc_info=True)

    def get_completed_players(self, batch_id: str) -> List[str]:
        """
        Week 1: Get completed players with feature flag support.

        Args:
            batch_id: Batch identifier

        Returns:
            List of player_lookup strings
        """
        if self.enable_subcollection and self.use_subcollection_reads:
            # NEW: Read from subcollection
            logger.debug(f"Reading completed players from subcollection for {batch_id}")
            return self._get_completed_players_subcollection(batch_id)
        else:
            # OLD: Read from array
            logger.debug(f"Reading completed players from array for {batch_id}")
            batch_doc = self.collection.document(batch_id).get()
            if batch_doc.exists:
                return batch_doc.to_dict().get('completed_players', [])
            return []

    def get_completion_progress(self, batch_id: str) -> Dict:
        """
        Week 1: Get batch completion progress with feature flag support.

        Args:
            batch_id: Batch identifier

        Returns:
            Dictionary with completion stats
        """
        batch_doc = self.collection.document(batch_id).get()

        if not batch_doc.exists:
            return {
                'batch_id': batch_id,
                'completed': 0,
                'total': 0,
                'completion_pct': 0.0
            }

        data = batch_doc.to_dict()

        if self.enable_subcollection and self.use_subcollection_reads:
            # NEW: Use counter
            completed_count = data.get('completed_count', 0)
        else:
            # OLD: Count array length
            completed_count = len(data.get('completed_players', []))

        total_players = data.get('expected_players', 0)
        completion_pct = (completed_count / total_players * 100) if total_players > 0 else 0

        return {
            'batch_id': batch_id,
            'completed': completed_count,
            'total': total_players,
            'completion_pct': completion_pct,
            'is_complete': data.get('is_complete', False)
        }

    def monitor_dual_write_consistency(self) -> List[Dict]:
        """
        Week 1: Background job to monitor dual-write consistency.

        Run this periodically (e.g., every hour) during migration to detect
        any mismatches between array and subcollection counts.

        Returns:
            List of batches with consistency mismatches
        """
        if not (self.enable_subcollection and self.dual_write_mode):
            logger.info("Dual-write not enabled, skipping consistency monitoring")
            return []

        # Get all active batches
        batches = self.collection.where('is_complete', '==', False).stream()

        mismatches = []

        for batch_doc in batches:
            batch_id = batch_doc.id
            data = batch_doc.to_dict()

            # Array count
            array_count = len(data.get('completed_players', []))

            # Subcollection count
            subcoll_count = self._get_completion_count_subcollection(batch_id)

            if array_count != subcoll_count:
                mismatch = {
                    'batch_id': batch_id,
                    'array_count': array_count,
                    'subcollection_count': subcoll_count,
                    'diff': abs(array_count - subcoll_count)
                }
                mismatches.append(mismatch)
                logger.warning(
                    f"Consistency mismatch in {batch_id}: "
                    f"array={array_count}, subcollection={subcoll_count}"
                )

        if mismatches:
            logger.error(f"Found {len(mismatches)} consistency mismatches in active batches", exc_info=True)
        else:
            logger.info("✅ All active batches consistent between array and subcollection")

        return mismatches

    @retry_on_firestore_error(max_attempts=5, base_delay=1.0)
    def mark_batch_complete(self, batch_id: str) -> None:
        """
        Explicitly mark a batch as complete

        Note: Uses retry decorator because this is a critical state transition.

        Args:
            batch_id: Batch identifier
        """
        # Lazy-load Firestore helpers
        _, _, SERVER_TIMESTAMP = _get_firestore_helpers()

        doc_ref = self.collection.document(batch_id)
        doc_ref.update({
            'is_complete': True,
            'completion_time': SERVER_TIMESTAMP,
            'updated_at': SERVER_TIMESTAMP
        })

        logger.info(f"Marked batch as complete: {batch_id}")

    def check_and_complete_stalled_batch(
        self,
        batch_id: str,
        stall_threshold_minutes: int = 10,
        min_completion_pct: float = 95.0,
        max_batch_age_minutes: int = 30,
    ) -> bool:
        """
        Check if a batch is stalled and complete it with partial results.

        A batch is considered stalled if EITHER:
        1. It has reached min_completion_pct AND no progress for stall_threshold_minutes
        2. It has exceeded max_batch_age_minutes regardless of completion (Session 159)

        Session 159: Added max_batch_age_minutes to auto-fail batches that have been
        running too long. Previously, a batch at 0% would never be cleaned up because
        it didn't meet the 95% completion threshold. This caused Feb 7-8 2026 outage
        where stuck batches blocked new predictions for 4+ hours.

        Args:
            batch_id: Batch identifier
            stall_threshold_minutes: Minutes without progress = stalled
            min_completion_pct: Minimum % complete to allow partial completion
            max_batch_age_minutes: Absolute timeout - force-complete regardless of progress

        Returns:
            True if batch was marked complete (was stalled), False otherwise
        """
        from datetime import timedelta

        state = self.get_batch_state(batch_id)
        if not state:
            logger.warning(f"Batch {batch_id} not found for stall check")
            return False

        if state.is_complete:
            logger.debug(f"Batch {batch_id} already complete")
            return False

        completion_pct = state.get_completion_percentage()

        # Get batch document for timestamp checks
        doc_ref = self.collection.document(batch_id)
        doc = doc_ref.get()
        data = doc.to_dict()

        # Session 159: Check absolute batch age first (bypasses completion % check)
        start_time = data.get('start_time')
        if start_time:
            if hasattr(start_time, 'timestamp'):
                batch_start = datetime.fromtimestamp(start_time.timestamp(), tz=timezone.utc)
            else:
                batch_start = start_time

            batch_age = datetime.now(timezone.utc) - batch_start
            if batch_age > timedelta(minutes=max_batch_age_minutes):
                completed = len(state.completed_players)
                expected = state.expected_players

                logger.warning(
                    f"⚠️ Batch {batch_id} TIMED OUT after {batch_age.total_seconds()/60:.0f} min "
                    f"at {completed}/{expected} ({completion_pct:.1f}%) - "
                    f"force-completing (max_batch_age={max_batch_age_minutes} min)"
                )

                _, _, SERVER_TIMESTAMP = _get_firestore_helpers()
                doc_ref.update({
                    'is_complete': True,
                    'completion_time': SERVER_TIMESTAMP,
                    'updated_at': SERVER_TIMESTAMP,
                    'stall_completed': True,
                    'stall_reason': (
                        f"Batch timeout: {batch_age.total_seconds()/60:.0f} min > "
                        f"{max_batch_age_minutes} min limit at {completion_pct:.1f}%"
                    )
                })

                logger.info(
                    f"✅ Marked timed-out batch {batch_id} as complete "
                    f"({completed}/{expected} players, {state.total_predictions} predictions)"
                )
                return True

        # Check completion percentage for stall-based completion
        if completion_pct < min_completion_pct:
            logger.debug(
                f"Batch {batch_id} at {completion_pct:.1f}% - below threshold "
                f"({min_completion_pct}%), not marking complete"
            )
            return False

        # Check for stall (no updates for threshold minutes)
        updated_at = data.get('updated_at')
        if updated_at:
            if hasattr(updated_at, 'timestamp'):
                last_update = datetime.fromtimestamp(updated_at.timestamp(), tz=timezone.utc)
            else:
                last_update = updated_at

            time_since_update = datetime.now(timezone.utc) - last_update
            stall_threshold = timedelta(minutes=stall_threshold_minutes)

            if time_since_update < stall_threshold:
                logger.debug(
                    f"Batch {batch_id} last updated {time_since_update.total_seconds():.0f}s ago - "
                    f"not stalled yet (threshold: {stall_threshold_minutes} min)"
                )
                return False

        # Batch is stalled - mark complete with partial results
        completed = len(state.completed_players)
        expected = state.expected_players

        logger.warning(
            f"⚠️ Batch {batch_id} STALLED at {completed}/{expected} ({completion_pct:.1f}%) - "
            f"marking complete with partial results"
        )

        _, _, SERVER_TIMESTAMP = _get_firestore_helpers()

        doc_ref.update({
            'is_complete': True,
            'completion_time': SERVER_TIMESTAMP,
            'updated_at': SERVER_TIMESTAMP,
            'stall_completed': True,
            'stall_reason': f"No progress for {stall_threshold_minutes} min at {completion_pct:.1f}%"
        })

        logger.info(
            f"✅ Marked stalled batch {batch_id} as complete "
            f"({completed}/{expected} players, {state.total_predictions} predictions)"
        )

        return True

    @retry_on_firestore_error(max_attempts=3, base_delay=0.5)
    def get_active_batches(self) -> List[BatchState]:
        """
        Get all active (incomplete) batches

        Returns:
            List of BatchState objects
        """
        query = self.collection.where('is_complete', '==', False)
        docs = query.stream()

        return [BatchState.from_firestore_dict(doc.to_dict()) for doc in docs]

    @retry_on_firestore_error(max_attempts=3, base_delay=1.0)
    def cleanup_old_batches(self, days: int = 7) -> int:
        """
        Delete batch records older than specified days

        Note: Uses retry decorator for transient failures during cleanup.

        Args:
            days: Number of days to keep (default: 7)

        Returns:
            Number of batches deleted
        """
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

    # ============================================================================
    # Multi-Instance Coordination Methods
    # ============================================================================

    @retry_firestore_transaction
    def create_batch_with_transaction(
        self,
        batch_id: str,
        game_date: str,
        expected_players: int,
        correlation_id: Optional[str] = None,
        dataset_prefix: str = "",
        instance_id: Optional[str] = None
    ) -> Optional[BatchState]:
        """
        Create a new batch using Firestore transaction to prevent duplicates.

        This is safe for multi-instance deployment - only one instance can
        create a batch for a given batch_id.

        Note: Uses @retry_firestore_transaction decorator for aggressive retry
        on transaction conflicts.

        Args:
            batch_id: Unique batch identifier
            game_date: Game date (YYYY-MM-DD)
            expected_players: Number of players expected
            correlation_id: Optional correlation ID for tracing
            dataset_prefix: Optional dataset prefix for testing
            instance_id: Optional instance ID for tracking

        Returns:
            BatchState if created, None if already exists
        """
        firestore = _get_firestore()
        _, _, SERVER_TIMESTAMP = _get_firestore_helpers()

        doc_ref = self.collection.document(batch_id)

        @firestore.transactional
        def create_in_transaction(transaction):
            snapshot = doc_ref.get(transaction=transaction)

            if snapshot.exists:
                existing = snapshot.to_dict()
                # Check if it's the same game_date (idempotent retry)
                if existing.get('game_date') == game_date:
                    logger.info(f"Batch {batch_id} already exists for {game_date} (idempotent)")
                    return None
                else:
                    logger.warning(
                        f"Batch {batch_id} exists for different date: "
                        f"{existing.get('game_date')} vs {game_date}"
                    )
                    return None

            # Create new batch
            state = BatchState(
                batch_id=batch_id,
                game_date=game_date,
                expected_players=expected_players,
                start_time=datetime.now(timezone.utc),
                correlation_id=correlation_id,
                dataset_prefix=dataset_prefix
            )

            data = state.to_firestore_dict()
            if instance_id:
                data['created_by_instance'] = instance_id

            transaction.set(doc_ref, data)
            return state

        transaction = self.db.transaction()
        try:
            result = create_in_transaction(transaction)
            if result:
                logger.info(
                    f"Created batch state with transaction: {batch_id} "
                    f"(expected_players={expected_players}, game_date={game_date})"
                )
            return result
        except Exception as e:
            logger.error(f"Transaction error creating batch: {e}", exc_info=True)
            raise

    @retry_firestore_transaction
    def claim_batch_for_processing(
        self,
        batch_id: str,
        instance_id: str,
        claim_timeout_seconds: int = 300
    ) -> bool:
        """
        Claim a batch for processing by an instance.

        Uses Firestore transaction to ensure only one instance can claim.
        The claim has a timeout to handle crashed instances.

        Note: Uses @retry_firestore_transaction decorator for aggressive retry
        on transaction conflicts during multi-instance coordination.

        Args:
            batch_id: Batch identifier
            instance_id: Instance claiming the batch
            claim_timeout_seconds: How long the claim is valid (default 5 min)

        Returns:
            True if claim successful, False if already claimed
        """
        firestore = _get_firestore()
        _, _, SERVER_TIMESTAMP = _get_firestore_helpers()

        doc_ref = self.collection.document(batch_id)

        @firestore.transactional
        def claim_in_transaction(transaction):
            snapshot = doc_ref.get(transaction=transaction)

            if not snapshot.exists:
                logger.error(f"Cannot claim non-existent batch: {batch_id}", exc_info=True)
                return False

            data = snapshot.to_dict()

            # Check if already claimed
            claimed_by = data.get('claimed_by_instance')
            claim_expires = data.get('claim_expires_at')

            if claimed_by and claimed_by != instance_id:
                # Check if claim is still valid
                if claim_expires:
                    if hasattr(claim_expires, 'timestamp'):
                        claim_expires_dt = datetime.fromtimestamp(
                            claim_expires.timestamp(), tz=timezone.utc
                        )
                    else:
                        claim_expires_dt = claim_expires

                    if datetime.now(timezone.utc) < claim_expires_dt:
                        logger.info(
                            f"Batch {batch_id} already claimed by {claimed_by} "
                            f"(expires {claim_expires_dt})"
                        )
                        return False

                # Claim expired - can take over
                logger.warning(
                    f"Taking over expired claim on {batch_id} from {claimed_by}"
                )

            # Set claim
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=claim_timeout_seconds)
            transaction.update(doc_ref, {
                'claimed_by_instance': instance_id,
                'claim_expires_at': expires_at,
                'claimed_at': SERVER_TIMESTAMP
            })

            return True

        transaction = self.db.transaction()
        try:
            result = claim_in_transaction(transaction)
            if result:
                logger.info(f"Claimed batch {batch_id} for instance {instance_id}")
            return result
        except Exception as e:
            logger.error(f"Transaction error claiming batch: {e}", exc_info=True)
            return False

    @retry_firestore_transaction
    def release_batch_claim(self, batch_id: str, instance_id: str) -> bool:
        """
        Release a batch claim held by an instance.

        Note: Uses @retry_firestore_transaction decorator for aggressive retry
        on transaction conflicts.

        Args:
            batch_id: Batch identifier
            instance_id: Instance releasing the claim

        Returns:
            True if released, False if not held by this instance
        """
        firestore = _get_firestore()
        _, _, SERVER_TIMESTAMP = _get_firestore_helpers()

        doc_ref = self.collection.document(batch_id)

        @firestore.transactional
        def release_in_transaction(transaction):
            snapshot = doc_ref.get(transaction=transaction)

            if not snapshot.exists:
                return False

            data = snapshot.to_dict()
            claimed_by = data.get('claimed_by_instance')

            if claimed_by != instance_id:
                logger.warning(
                    f"Cannot release claim on {batch_id}: held by {claimed_by}, "
                    f"not {instance_id}"
                )
                return False

            transaction.update(doc_ref, {
                'claimed_by_instance': None,
                'claim_expires_at': None,
                'claimed_at': None
            })
            return True

        transaction = self.db.transaction()
        try:
            result = release_in_transaction(transaction)
            if result:
                logger.info(f"Released claim on batch {batch_id} by instance {instance_id}")
            return result
        except Exception as e:
            logger.error(f"Transaction error releasing claim: {e}", exc_info=True)
            return False

    @retry_on_firestore_error(max_attempts=3, base_delay=0.5)
    def refresh_batch_claim(
        self,
        batch_id: str,
        instance_id: str,
        claim_timeout_seconds: int = 300
    ) -> bool:
        """
        Refresh an existing batch claim to prevent expiration.

        Call periodically during long operations.

        Note: Uses retry decorator with shorter delays for quick operations.

        Args:
            batch_id: Batch identifier
            instance_id: Instance refreshing the claim
            claim_timeout_seconds: New timeout duration

        Returns:
            True if refreshed, False if claim not held
        """
        doc_ref = self.collection.document(batch_id)

        try:
            doc = doc_ref.get()
            if not doc.exists:
                return False

            data = doc.to_dict()
            if data.get('claimed_by_instance') != instance_id:
                logger.warning(f"Cannot refresh claim: not held by {instance_id}")
                return False

            expires_at = datetime.now(timezone.utc) + timedelta(seconds=claim_timeout_seconds)
            doc_ref.update({'claim_expires_at': expires_at})

            logger.debug(f"Refreshed claim on {batch_id} for {instance_id}")
            return True

        except Exception as e:
            logger.error(f"Error refreshing claim: {e}", exc_info=True)
            return False

    def get_unclaimed_batches(self) -> List[BatchState]:
        """
        Get all active batches that are not claimed by any instance.

        Useful for work distribution among instances.

        Returns:
            List of unclaimed BatchState objects
        """
        # Get all active batches
        active_batches = self.get_active_batches()
        unclaimed = []

        for batch in active_batches:
            # Check claim status
            doc = self.collection.document(batch.batch_id).get()
            if doc.exists:
                data = doc.to_dict()
                claimed_by = data.get('claimed_by_instance')
                claim_expires = data.get('claim_expires_at')

                if not claimed_by:
                    unclaimed.append(batch)
                elif claim_expires:
                    # Check if expired
                    if hasattr(claim_expires, 'timestamp'):
                        claim_expires_dt = datetime.fromtimestamp(
                            claim_expires.timestamp(), tz=timezone.utc
                        )
                    else:
                        claim_expires_dt = claim_expires

                    if datetime.now(timezone.utc) >= claim_expires_dt:
                        unclaimed.append(batch)

        logger.debug(f"Found {len(unclaimed)} unclaimed batches")
        return unclaimed

    def record_completion_safe(
        self,
        batch_id: str,
        player_lookup: str,
        predictions_count: int,
        instance_id: Optional[str] = None
    ) -> bool:
        """
        Record a player completion with retry logic for transient failures.

        This is a safer version of record_completion that handles
        transient Firestore errors with exponential backoff.

        Args:
            batch_id: Batch identifier
            player_lookup: Player identifier
            predictions_count: Number of predictions generated
            instance_id: Optional instance ID for tracking

        Returns:
            True if batch is now complete, False otherwise
        """
        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                return self.record_completion(batch_id, player_lookup, predictions_count)
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Completion recording attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(
                        f"Failed to record completion after {max_retries} attempts: {e}",
                        exc_info=True
                    )
                    raise

        return False

    def get_batch_processing_stats(self) -> Dict:
        """
        Get statistics about batch processing across all instances.

        Returns:
            Dictionary with processing statistics
        """
        active_batches = self.get_active_batches()

        stats = {
            'active_batches': len(active_batches),
            'total_expected': sum(b.expected_players for b in active_batches),
            'total_completed': sum(len(b.completed_players) for b in active_batches),
            'total_predictions': sum(b.total_predictions for b in active_batches),
            'batches': []
        }

        for batch in active_batches:
            doc = self.collection.document(batch.batch_id).get()
            data = doc.to_dict() if doc.exists else {}

            batch_info = {
                'batch_id': batch.batch_id,
                'game_date': batch.game_date,
                'expected': batch.expected_players,
                'completed': len(batch.completed_players),
                'completion_pct': batch.get_completion_percentage(),
                'claimed_by': data.get('claimed_by_instance'),
                'created_by': data.get('created_by_instance')
            }
            stats['batches'].append(batch_info)

        return stats


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

# predictions/worker/distributed_lock.py

"""
Distributed Lock for Preventing Concurrent Consolidations

Uses Firestore to implement a distributed lock that prevents race conditions
in concurrent consolidation operations. This prevents the duplicate-write bug
where two MERGE operations both INSERT the same business key with different
prediction_ids.

Root Cause:
- When two consolidations run concurrently for overlapping data (same game_date)
- Both check main table for existing rows with same business key
- Both find "NOT MATCHED" (before either commits)
- Both INSERT → duplicate rows with different prediction_ids

Fix:
- Use Firestore document with TTL as distributed lock
- Lock key is game_date (prevents concurrent consolidations for same date)
- 5-minute timeout to prevent deadlocks from crashed processes
- Automatic cleanup via Firestore TTL

Usage:
    from distributed_lock import ConsolidationLock

    lock = ConsolidationLock(project_id=PROJECT_ID)

    with lock.acquire(game_date="2026-01-17", batch_id="batch123"):
        # Only one consolidation can run at a time for this game_date
        result = consolidator.consolidate_batch(batch_id, game_date)
"""

import logging
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

from google.cloud import firestore
from google.api_core import exceptions as gcp_exceptions

logger = logging.getLogger(__name__)

# Lock configuration
LOCK_COLLECTION = "consolidation_locks"
LOCK_TIMEOUT_SECONDS = 300  # 5 minutes - prevents deadlocks from crashed processes
MAX_ACQUIRE_ATTEMPTS = 60  # Max retries (60 * 5s = 5 minutes total wait)
RETRY_DELAY_SECONDS = 5  # Wait between lock acquisition attempts


class LockAcquisitionError(Exception):
    """Raised when unable to acquire distributed lock after max retries."""
    pass


class ConsolidationLock:
    """
    Distributed lock for preventing concurrent consolidations.

    Uses Firestore to ensure only one consolidation runs at a time
    for a given game_date. This prevents race conditions that cause
    duplicate rows with different prediction_ids.

    The lock is scoped to game_date (not batch_id) because multiple
    batches can target the same game_date (e.g., retry + scheduled run).

    Features:
    - Automatic timeout (5 minutes) to prevent deadlocks
    - Retry logic with backoff
    - Context manager for automatic release
    - Firestore TTL for cleanup of stale locks
    """

    def __init__(self, project_id: str):
        """
        Initialize the distributed lock.

        Args:
            project_id: GCP project ID
        """
        self.project_id = project_id
        self.db = firestore.Client(project=project_id)
        self.lock_doc_ref: Optional[firestore.DocumentReference] = None

    def _generate_lock_key(self, game_date: str) -> str:
        """
        Generate a unique lock key for a game_date.

        Lock is scoped to game_date (not batch_id) because:
        - Multiple batches can target the same game_date
        - We need to prevent ALL concurrent consolidations for a date
        - Race condition occurs when MERGING to same date's data

        Args:
            game_date: Game date in YYYY-MM-DD format

        Returns:
            Lock key string
        """
        return f"consolidation_{game_date}"

    def _try_acquire(self, lock_key: str, batch_id: str, holder_id: str) -> bool:
        """
        Attempt to acquire the lock (single try).

        Uses Firestore transaction to atomically check and set the lock.

        Args:
            lock_key: Unique lock identifier
            batch_id: Batch identifier (for tracking)
            holder_id: Unique identifier for this lock holder

        Returns:
            True if lock acquired, False if already held
        """
        lock_ref = self.db.collection(LOCK_COLLECTION).document(lock_key)

        @firestore.transactional
        def acquire_in_transaction(transaction):
            """Atomically check and acquire lock in transaction."""
            snapshot = lock_ref.get(transaction=transaction)

            if snapshot.exists:
                # Lock exists - check if expired
                lock_data = snapshot.to_dict()
                expires_at = lock_data.get('expires_at')

                if expires_at and expires_at.timestamp() > time.time():
                    # Lock still valid and held by someone else
                    current_holder = lock_data.get('batch_id', 'unknown')
                    logger.info(
                        f"Lock {lock_key} is held by batch {current_holder}, "
                        f"expires in {int(expires_at.timestamp() - time.time())}s"
                    )
                    return False
                else:
                    # Lock expired - can acquire
                    logger.warning(
                        f"Lock {lock_key} expired (held by {lock_data.get('batch_id')}), "
                        f"acquiring for batch {batch_id}"
                    )

            # Lock doesn't exist or expired - acquire it
            lock_data = {
                'batch_id': batch_id,
                'holder_id': holder_id,
                'acquired_at': firestore.SERVER_TIMESTAMP,
                'expires_at': datetime.utcnow() + timedelta(seconds=LOCK_TIMEOUT_SECONDS),
                'lock_key': lock_key
            }
            transaction.set(lock_ref, lock_data)
            return True

        # Execute transaction
        transaction = self.db.transaction()
        try:
            acquired = acquire_in_transaction(transaction)
            if acquired:
                self.lock_doc_ref = lock_ref
                logger.info(
                    f"✅ Acquired consolidation lock: {lock_key} "
                    f"(batch={batch_id}, timeout={LOCK_TIMEOUT_SECONDS}s)"
                )
            return acquired
        except gcp_exceptions.GoogleAPICallError as e:
            logger.error(f"Firestore error acquiring lock: {e}")
            return False

    @contextmanager
    def acquire(
        self,
        game_date: str,
        batch_id: str,
        max_wait_seconds: Optional[int] = None,
        holder_id: Optional[str] = None
    ):
        """
        Acquire distributed lock with automatic release.

        Context manager that acquires the lock, yields, then releases.
        Retries acquisition for up to max_wait_seconds if lock is held.

        Args:
            game_date: Game date to lock (YYYY-MM-DD)
            batch_id: Batch identifier (for tracking)
            max_wait_seconds: Maximum seconds to wait for lock (default: 5 minutes)
            holder_id: Unique identifier for this holder (default: batch_id)

        Yields:
            None (lock is held during yield)

        Raises:
            LockAcquisitionError: If unable to acquire lock after max_wait_seconds

        Example:
            lock = ConsolidationLock(project_id)
            with lock.acquire(game_date="2026-01-17", batch_id="batch123"):
                # Only one consolidation runs at a time for this game_date
                consolidator.consolidate_batch(batch_id, game_date)
        """
        lock_key = self._generate_lock_key(game_date)
        holder_id = holder_id or batch_id
        max_wait = max_wait_seconds or (MAX_ACQUIRE_ATTEMPTS * RETRY_DELAY_SECONDS)

        start_time = time.time()
        attempts = 0

        logger.info(
            f"Attempting to acquire consolidation lock for game_date={game_date}, "
            f"batch={batch_id}, max_wait={max_wait}s"
        )

        # Try to acquire lock with retries
        acquired = False
        while not acquired and (time.time() - start_time) < max_wait:
            attempts += 1
            acquired = self._try_acquire(lock_key, batch_id, holder_id)

            if not acquired:
                elapsed = int(time.time() - start_time)
                logger.info(
                    f"Lock acquisition attempt {attempts} failed, "
                    f"retrying in {RETRY_DELAY_SECONDS}s (elapsed={elapsed}s, max_wait={max_wait}s)"
                )
                time.sleep(RETRY_DELAY_SECONDS)

        if not acquired:
            elapsed = int(time.time() - start_time)
            error_msg = (
                f"Failed to acquire consolidation lock for game_date={game_date} "
                f"after {attempts} attempts ({elapsed}s). "
                f"Another consolidation may be running or a lock is stuck. "
                f"Check Firestore collection '{LOCK_COLLECTION}' for lock: {lock_key}"
            )
            logger.error(error_msg)
            raise LockAcquisitionError(error_msg)

        try:
            # Lock acquired - yield to caller
            logger.info(f"Lock acquired after {attempts} attempt(s), proceeding with consolidation")
            yield

        finally:
            # Always release lock (even if exception occurs)
            self._release(lock_key, batch_id)

    def _release(self, lock_key: str, batch_id: str):
        """
        Release the distributed lock.

        Deletes the Firestore document. Safe to call even if lock doesn't exist.

        Args:
            lock_key: Lock key to release
            batch_id: Batch identifier (for logging)
        """
        if not self.lock_doc_ref:
            logger.warning(f"No lock reference to release for {lock_key}")
            return

        try:
            self.lock_doc_ref.delete()
            logger.info(f"🔓 Released consolidation lock: {lock_key} (batch={batch_id})")
            self.lock_doc_ref = None
        except gcp_exceptions.NotFound:
            # Lock already deleted (e.g., TTL expired)
            logger.info(f"Lock {lock_key} already released (not found)")
            self.lock_doc_ref = None
        except Exception as e:
            logger.error(f"Error releasing lock {lock_key}: {e}")
            # Don't raise - lock will expire via TTL

    def force_release(self, game_date: str):
        """
        Force release a lock for a game_date.

        USE WITH CAUTION: Only call this if you're certain no consolidation
        is running and the lock is stuck (e.g., process crashed).

        Args:
            game_date: Game date whose lock to release
        """
        lock_key = self._generate_lock_key(game_date)
        lock_ref = self.db.collection(LOCK_COLLECTION).document(lock_key)

        try:
            lock_ref.delete()
            logger.warning(f"⚠️  FORCE RELEASED lock: {lock_key}")
        except gcp_exceptions.NotFound:
            logger.info(f"Lock {lock_key} not found (already released)")
        except Exception as e:
            logger.error(f"Error force releasing lock {lock_key}: {e}")
            raise

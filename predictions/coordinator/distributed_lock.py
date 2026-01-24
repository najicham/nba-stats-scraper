# predictions/worker/distributed_lock.py

"""
Distributed Lock for Preventing Concurrent Operations

Uses Firestore to implement a distributed lock that prevents race conditions
in concurrent operations. This prevents duplicate-write bugs where two operations
both INSERT the same business key.

Supported Lock Types:
- consolidation: Prevents concurrent prediction consolidations
- grading: Prevents concurrent grading operations

Root Cause of Duplicates:
- When two operations run concurrently for same game_date
- Both check main table for existing rows with same business key
- Both find "NOT MATCHED" or empty table (before either commits)
- Both INSERT → duplicate rows with different IDs

Fix:
- Use Firestore document with TTL as distributed lock
- Lock key is game_date (prevents concurrent operations for same date)
- 5-minute timeout to prevent deadlocks from crashed processes
- Automatic cleanup via Firestore TTL

Usage:
    from distributed_lock import DistributedLock

    # For consolidation
    lock = DistributedLock(project_id=PROJECT_ID, lock_type="consolidation")
    with lock.acquire(game_date="2026-01-17", operation_id="batch123"):
        result = consolidator.consolidate_batch(batch_id, game_date)

    # For grading
    lock = DistributedLock(project_id=PROJECT_ID, lock_type="grading")
    with lock.acquire(game_date="2026-01-17", operation_id="grading"):
        result = processor.process_date(game_date)
"""

import logging
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

from google.api_core import exceptions as gcp_exceptions

logger = logging.getLogger(__name__)

# Lazy-load firestore to avoid Python 3.13 import errors at module load time
def _get_firestore_client():
    """Lazy-load Firestore client to avoid import errors."""
    from google.cloud import firestore
    return firestore

# Lock configuration
LOCK_TIMEOUT_SECONDS = 300  # 5 minutes - prevents deadlocks from crashed processes
MAX_ACQUIRE_ATTEMPTS = 60  # Max retries (60 * 5s = 5 minutes total wait)
RETRY_DELAY_SECONDS = 5  # Wait between lock acquisition attempts


class LockAcquisitionError(Exception):
    """Raised when unable to acquire distributed lock after max retries."""
    pass


class DistributedLock:
    """
    Distributed lock for preventing concurrent operations.

    Uses Firestore to ensure only one operation runs at a time
    for a given game_date. This prevents race conditions that cause
    duplicate rows.

    Supports multiple lock types:
    - "consolidation": For prediction consolidation operations
    - "grading": For grading operations

    The lock is scoped to game_date (not operation_id) because multiple
    operations can target the same game_date (e.g., retry + scheduled run).

    Features:
    - Automatic timeout (5 minutes) to prevent deadlocks
    - Retry logic with backoff
    - Context manager for automatic release
    - Firestore TTL for cleanup of stale locks
    - Separate collections per lock type
    """

    def __init__(self, project_id: str, lock_type: str = "consolidation"):
        """
        Initialize the distributed lock.

        Args:
            project_id: GCP project ID
            lock_type: Type of lock ("consolidation" or "grading")
        """
        self.project_id = project_id
        self.lock_type = lock_type
        self.collection_name = f"{lock_type}_locks"
        firestore = _get_firestore_client()
        self.db = firestore.Client(project=project_id)
        self.lock_doc_ref: Optional[object] = None  # firestore.DocumentReference lazy-loaded

        logger.info(f"Initialized DistributedLock (type={lock_type}, collection={self.collection_name})")

    def _generate_lock_key(self, game_date: str) -> str:
        """
        Generate a unique lock key for a game_date.

        Lock is scoped to game_date (not operation_id) because:
        - Multiple operations can target the same game_date
        - We need to prevent ALL concurrent operations for a date
        - Race condition occurs when writing to same date's data

        Args:
            game_date: Game date in YYYY-MM-DD format

        Returns:
            Lock key string (e.g., "consolidation_2026-01-17" or "grading_2026-01-17")
        """
        return f"{self.lock_type}_{game_date}"

    def _try_acquire(self, lock_key: str, operation_id: str, holder_id: str) -> bool:
        """
        Attempt to acquire the lock (single try).

        Uses Firestore transaction to atomically check and set the lock.

        Args:
            lock_key: Unique lock identifier
            operation_id: Operation identifier (for tracking)
            holder_id: Unique identifier for this lock holder

        Returns:
            True if lock acquired, False if already held
        """
        lock_ref = self.db.collection(self.collection_name).document(lock_key)

        firestore = _get_firestore_client()

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
                    current_holder = lock_data.get('operation_id', 'unknown')
                    logger.info(
                        f"Lock {lock_key} is held by operation {current_holder}, "
                        f"expires in {int(expires_at.timestamp() - time.time())}s"
                    )
                    return False
                else:
                    # Lock expired - can acquire
                    logger.warning(
                        f"Lock {lock_key} expired (held by {lock_data.get('operation_id')}), "
                        f"acquiring for operation {operation_id}"
                    )

            # Lock doesn't exist or expired - acquire it
            lock_data = {
                'operation_id': operation_id,
                'holder_id': holder_id,
                'lock_type': self.lock_type,
                'acquired_at': _get_firestore_client().SERVER_TIMESTAMP,
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
                    f"✅ Acquired {self.lock_type} lock: {lock_key} "
                    f"(operation={operation_id}, timeout={LOCK_TIMEOUT_SECONDS}s)"
                )
            return acquired
        except gcp_exceptions.GoogleAPICallError as e:
            logger.error(f"Firestore error acquiring lock: {e}", exc_info=True)
            return False

    @contextmanager
    def acquire(
        self,
        game_date: str,
        operation_id: str,
        max_wait_seconds: Optional[int] = None,
        holder_id: Optional[str] = None
    ):
        """
        Acquire distributed lock with automatic release.

        Context manager that acquires the lock, yields, then releases.
        Retries acquisition for up to max_wait_seconds if lock is held.

        Args:
            game_date: Game date to lock (YYYY-MM-DD)
            operation_id: Operation identifier (for tracking)
            max_wait_seconds: Maximum seconds to wait for lock (default: 5 minutes)
            holder_id: Unique identifier for this holder (default: operation_id)

        Yields:
            None (lock is held during yield)

        Raises:
            LockAcquisitionError: If unable to acquire lock after max_wait_seconds

        Example:
            # Consolidation
            lock = DistributedLock(project_id, lock_type="consolidation")
            with lock.acquire(game_date="2026-01-17", operation_id="batch123"):
                consolidator.consolidate_batch(batch_id, game_date)

            # Grading
            lock = DistributedLock(project_id, lock_type="grading")
            with lock.acquire(game_date="2026-01-17", operation_id="grading"):
                processor.process_date(game_date)
        """
        lock_key = self._generate_lock_key(game_date)
        holder_id = holder_id or operation_id
        max_wait = max_wait_seconds or (MAX_ACQUIRE_ATTEMPTS * RETRY_DELAY_SECONDS)

        start_time = time.time()
        attempts = 0

        logger.info(
            f"Attempting to acquire {self.lock_type} lock for game_date={game_date}, "
            f"operation={operation_id}, max_wait={max_wait}s"
        )

        # Try to acquire lock with retries
        acquired = False
        while not acquired and (time.time() - start_time) < max_wait:
            attempts += 1
            acquired = self._try_acquire(lock_key, operation_id, holder_id)

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
                f"Failed to acquire {self.lock_type} lock for game_date={game_date} "
                f"after {attempts} attempts ({elapsed}s). "
                f"Another {self.lock_type} operation may be running or a lock is stuck. "
                f"Check Firestore collection '{self.collection_name}' for lock: {lock_key}"
            )
            logger.error(error_msg)
            raise LockAcquisitionError(error_msg)

        try:
            # Lock acquired - yield to caller
            logger.info(f"Lock acquired after {attempts} attempt(s), proceeding with {self.lock_type}")
            yield

        finally:
            # Always release lock (even if exception occurs)
            self._release(lock_key, operation_id)

    def _release(self, lock_key: str, operation_id: str):
        """
        Release the distributed lock.

        Deletes the Firestore document. Safe to call even if lock doesn't exist.

        Args:
            lock_key: Lock key to release
            operation_id: Operation identifier (for logging)
        """
        if not self.lock_doc_ref:
            logger.warning(f"No lock reference to release for {lock_key}")
            return

        try:
            self.lock_doc_ref.delete()
            logger.info(f"🔓 Released {self.lock_type} lock: {lock_key} (operation={operation_id})")
            self.lock_doc_ref = None
        except gcp_exceptions.NotFound:
            # Lock already deleted (e.g., TTL expired)
            logger.info(f"Lock {lock_key} already released (not found)")
            self.lock_doc_ref = None
        except Exception as e:
            logger.error(f"Error releasing lock {lock_key}: {e}", exc_info=True)
            # Don't raise - lock will expire via TTL

    def force_release(self, game_date: str):
        """
        Force release a lock for a game_date.

        USE WITH CAUTION: Only call this if you're certain no operation
        is running and the lock is stuck (e.g., process crashed).

        Args:
            game_date: Game date whose lock to release
        """
        lock_key = self._generate_lock_key(game_date)
        lock_ref = self.db.collection(self.collection_name).document(lock_key)

        try:
            lock_ref.delete()
            logger.warning(f"⚠️  FORCE RELEASED {self.lock_type} lock: {lock_key}")
        except gcp_exceptions.NotFound:
            logger.info(f"Lock {lock_key} not found (already released)")
        except Exception as e:
            logger.error(f"Error force releasing lock {lock_key}: {e}", exc_info=True)
            raise


# Backward compatibility alias
ConsolidationLock = DistributedLock

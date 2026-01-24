# predictions/coordinator/instance_manager.py

"""
Multi-Instance Coordinator Manager

Enables multiple coordinator instances to run concurrently with proper
distributed locking and coordination using Firestore.

Key Features:
- Instance heartbeat tracking (detect dead instances)
- Leader election for batch-level operations
- Distributed locking for critical sections
- Graceful failover when instances crash

Architecture:
- Each instance registers with unique ID and heartbeat
- Leader election uses Firestore transactions for atomicity
- Heartbeat timeout triggers failover (default 60s)
- Batch operations require acquiring batch-level lock

Firestore Schema:

Collection: coordinator_instances
Document ID: {instance_id}
Fields:
  - instance_id: str (UUID)
  - started_at: timestamp
  - last_heartbeat: timestamp
  - status: str (active, stopping, stopped)
  - hostname: str
  - pod_name: str (from K8S_POD_NAME env)
  - version: str

Collection: coordinator_batch_locks
Document ID: {batch_id}
Fields:
  - batch_id: str
  - holder_instance_id: str
  - acquired_at: timestamp
  - expires_at: timestamp
  - operation: str (start, complete, consolidate)

Author: Claude Code
Date: January 2026
"""

import logging
import os
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from google.cloud import firestore

logger = logging.getLogger(__name__)


# Configuration
HEARTBEAT_INTERVAL_SECONDS = 30  # How often to update heartbeat
HEARTBEAT_TIMEOUT_SECONDS = 90  # Instance considered dead after this
LOCK_TIMEOUT_SECONDS = 300  # 5 minutes - batch lock timeout
LOCK_RETRY_DELAY_SECONDS = 2  # Wait between lock acquisition attempts
MAX_LOCK_RETRIES = 30  # Max retries (30 * 2s = 60s max wait)


def _get_firestore():
    """Lazy-load Firestore module to avoid import errors."""
    from google.cloud import firestore
    return firestore


def _get_firestore_helpers():
    """Lazy-load Firestore helper functions."""
    from google.cloud.firestore import SERVER_TIMESTAMP
    return SERVER_TIMESTAMP


@dataclass
class InstanceInfo:
    """Information about a coordinator instance."""
    instance_id: str
    started_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    status: str = "active"
    hostname: str = ""
    pod_name: str = ""
    version: str = "1.0"

    def is_alive(self, timeout_seconds: int = HEARTBEAT_TIMEOUT_SECONDS) -> bool:
        """Check if instance is still alive based on heartbeat."""
        if not self.last_heartbeat:
            return False
        elapsed = (datetime.now(timezone.utc) - self.last_heartbeat).total_seconds()
        return elapsed < timeout_seconds

    def to_firestore_dict(self) -> dict:
        """Convert to Firestore-compatible dictionary."""
        SERVER_TIMESTAMP = _get_firestore_helpers()
        return {
            'instance_id': self.instance_id,
            'started_at': self.started_at or SERVER_TIMESTAMP,
            'last_heartbeat': SERVER_TIMESTAMP,
            'status': self.status,
            'hostname': self.hostname,
            'pod_name': self.pod_name,
            'version': self.version
        }

    @staticmethod
    def from_firestore_dict(data: dict) -> 'InstanceInfo':
        """Create InstanceInfo from Firestore document."""
        return InstanceInfo(
            instance_id=data.get('instance_id', ''),
            started_at=data.get('started_at'),
            last_heartbeat=data.get('last_heartbeat'),
            status=data.get('status', 'unknown'),
            hostname=data.get('hostname', ''),
            pod_name=data.get('pod_name', ''),
            version=data.get('version', '')
        )


@dataclass
class BatchLock:
    """Represents a distributed lock on a batch operation."""
    batch_id: str
    holder_instance_id: str
    acquired_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    operation: str = "unknown"

    def is_expired(self) -> bool:
        """Check if lock has expired."""
        if not self.expires_at:
            return True
        return datetime.now(timezone.utc) > self.expires_at

    def to_firestore_dict(self) -> dict:
        """Convert to Firestore-compatible dictionary."""
        SERVER_TIMESTAMP = _get_firestore_helpers()
        return {
            'batch_id': self.batch_id,
            'holder_instance_id': self.holder_instance_id,
            'acquired_at': SERVER_TIMESTAMP,
            'expires_at': datetime.now(timezone.utc) + timedelta(seconds=LOCK_TIMEOUT_SECONDS),
            'operation': self.operation
        }

    @staticmethod
    def from_firestore_dict(data: dict) -> 'BatchLock':
        """Create BatchLock from Firestore document."""
        return BatchLock(
            batch_id=data.get('batch_id', ''),
            holder_instance_id=data.get('holder_instance_id', ''),
            acquired_at=data.get('acquired_at'),
            expires_at=data.get('expires_at'),
            operation=data.get('operation', 'unknown')
        )


class LockAcquisitionError(Exception):
    """Raised when unable to acquire a distributed lock."""
    pass


class InstanceFailoverError(Exception):
    """Raised when an instance fails over during an operation."""
    pass


class CoordinatorInstanceManager:
    """
    Manages coordinator instances for multi-instance deployment.

    Handles:
    - Instance registration and heartbeat
    - Distributed locking for batch operations
    - Failover detection and handling
    - Instance cleanup

    Usage:
        manager = CoordinatorInstanceManager(project_id="my-project")

        # Start heartbeat thread
        manager.start()

        # Acquire lock for batch operation
        with manager.acquire_batch_lock("batch_123", operation="start"):
            # Critical section - only one instance can run this
            process_batch()

        # Clean shutdown
        manager.stop()
    """

    INSTANCES_COLLECTION = "coordinator_instances"
    LOCKS_COLLECTION = "coordinator_batch_locks"

    def __init__(self, project_id: str, instance_id: Optional[str] = None):
        """
        Initialize the instance manager.

        Args:
            project_id: GCP project ID
            instance_id: Unique instance identifier (auto-generated if not provided)
        """
        self.project_id = project_id
        self.instance_id = instance_id or str(uuid.uuid4())

        # Lazy-load Firestore client
        firestore = _get_firestore()
        self.db = firestore.Client(project=project_id)
        self.instances_collection = self.db.collection(self.INSTANCES_COLLECTION)
        self.locks_collection = self.db.collection(self.LOCKS_COLLECTION)

        # Instance info
        self.instance_info = InstanceInfo(
            instance_id=self.instance_id,
            hostname=socket.gethostname(),
            pod_name=os.environ.get('K8S_POD_NAME', os.environ.get('HOSTNAME', '')),
            version=os.environ.get('COORDINATOR_VERSION', '1.0')
        )

        # Heartbeat thread
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._active_locks: Dict[str, BatchLock] = {}

        logger.info(
            f"CoordinatorInstanceManager initialized: instance_id={self.instance_id}, "
            f"hostname={self.instance_info.hostname}"
        )

    def start(self):
        """
        Start the instance manager.

        Registers this instance and starts the heartbeat thread.
        """
        # Register instance
        self._register_instance()

        # Start heartbeat thread
        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"heartbeat-{self.instance_id[:8]}",
            daemon=True
        )
        self._heartbeat_thread.start()

        logger.info(f"Instance manager started: {self.instance_id}")

    def stop(self):
        """
        Stop the instance manager.

        Releases all locks and marks instance as stopped.
        """
        # Signal heartbeat thread to stop
        self._stop_event.set()

        # Release all active locks
        for batch_id in list(self._active_locks.keys()):
            try:
                self._release_lock(batch_id)
            except Exception as e:
                logger.error(f"Error releasing lock for {batch_id}: {e}", exc_info=True)

        # Mark instance as stopped
        try:
            self._update_instance_status("stopped")
        except Exception as e:
            logger.error(f"Error updating instance status: {e}", exc_info=True)

        # Wait for heartbeat thread
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=5.0)

        logger.info(f"Instance manager stopped: {self.instance_id}")

    def _register_instance(self):
        """Register this instance in Firestore."""
        doc_ref = self.instances_collection.document(self.instance_id)
        doc_ref.set(self.instance_info.to_firestore_dict())
        logger.info(f"Registered instance: {self.instance_id}")

    def _update_instance_status(self, status: str):
        """Update instance status in Firestore."""
        SERVER_TIMESTAMP = _get_firestore_helpers()
        doc_ref = self.instances_collection.document(self.instance_id)
        doc_ref.update({
            'status': status,
            'last_heartbeat': SERVER_TIMESTAMP
        })

    def _heartbeat_loop(self):
        """Background thread that sends periodic heartbeats."""
        logger.info(f"Heartbeat thread started for instance {self.instance_id}")

        while not self._stop_event.is_set():
            try:
                self._send_heartbeat()
            except Exception as e:
                logger.error(f"Heartbeat error: {e}", exc_info=True)

            # Wait for next heartbeat or stop signal
            self._stop_event.wait(timeout=HEARTBEAT_INTERVAL_SECONDS)

        logger.info(f"Heartbeat thread stopped for instance {self.instance_id}")

    def _send_heartbeat(self):
        """Send a heartbeat to Firestore."""
        SERVER_TIMESTAMP = _get_firestore_helpers()
        doc_ref = self.instances_collection.document(self.instance_id)
        doc_ref.update({
            'last_heartbeat': SERVER_TIMESTAMP,
            'status': 'active'
        })
        logger.debug(f"Heartbeat sent for instance {self.instance_id}")

    def get_active_instances(self) -> List[InstanceInfo]:
        """
        Get all active coordinator instances.

        Returns:
            List of active InstanceInfo objects
        """
        instances = []
        docs = self.instances_collection.where('status', '==', 'active').stream()

        for doc in docs:
            info = InstanceInfo.from_firestore_dict(doc.to_dict())
            if info.is_alive():
                instances.append(info)

        logger.debug(f"Found {len(instances)} active instances")
        return instances

    def cleanup_dead_instances(self) -> int:
        """
        Clean up instances that have stopped sending heartbeats.

        Marks dead instances as 'stopped' and releases their locks.

        Returns:
            Number of instances cleaned up
        """
        count = 0
        docs = self.instances_collection.where('status', '==', 'active').stream()

        for doc in docs:
            info = InstanceInfo.from_firestore_dict(doc.to_dict())
            if not info.is_alive():
                # Mark as stopped
                doc.reference.update({'status': 'stopped'})

                # Release any locks held by this instance
                self._release_locks_for_instance(info.instance_id)

                count += 1
                logger.warning(
                    f"Cleaned up dead instance: {info.instance_id} "
                    f"(last heartbeat: {info.last_heartbeat})"
                )

        if count > 0:
            logger.info(f"Cleaned up {count} dead instances")

        return count

    def _release_locks_for_instance(self, instance_id: str):
        """Release all locks held by a specific instance."""
        docs = self.locks_collection.where(
            'holder_instance_id', '==', instance_id
        ).stream()

        for doc in docs:
            doc.reference.delete()
            logger.info(f"Released orphaned lock: {doc.id} (held by dead instance {instance_id})")

    @contextmanager
    def acquire_batch_lock(
        self,
        batch_id: str,
        operation: str = "unknown",
        max_wait_seconds: Optional[int] = None
    ):
        """
        Acquire a distributed lock for a batch operation.

        Context manager that acquires the lock, yields, then releases.
        Uses Firestore transactions for atomic lock acquisition.

        Args:
            batch_id: Batch identifier to lock
            operation: Operation type (for logging/debugging)
            max_wait_seconds: Maximum seconds to wait for lock

        Yields:
            None (lock is held during yield)

        Raises:
            LockAcquisitionError: If unable to acquire lock

        Example:
            with manager.acquire_batch_lock("batch_123", operation="consolidate"):
                # Only one instance can run this at a time
                consolidate_batch("batch_123")
        """
        max_wait = max_wait_seconds or (MAX_LOCK_RETRIES * LOCK_RETRY_DELAY_SECONDS)
        start_time = time.time()
        attempts = 0

        logger.info(
            f"Attempting to acquire batch lock: batch_id={batch_id}, "
            f"operation={operation}, instance={self.instance_id}"
        )

        # Try to acquire lock with retries
        acquired = False
        while not acquired and (time.time() - start_time) < max_wait:
            attempts += 1

            try:
                acquired = self._try_acquire_lock(batch_id, operation)
            except Exception as e:
                logger.error(f"Error acquiring lock: {e}", exc_info=True)

            if not acquired:
                elapsed = int(time.time() - start_time)
                logger.debug(
                    f"Lock acquisition attempt {attempts} failed, "
                    f"retrying in {LOCK_RETRY_DELAY_SECONDS}s (elapsed={elapsed}s)"
                )
                time.sleep(LOCK_RETRY_DELAY_SECONDS)

        if not acquired:
            elapsed = int(time.time() - start_time)
            error_msg = (
                f"Failed to acquire batch lock for {batch_id} after {attempts} "
                f"attempts ({elapsed}s). Another instance may be processing this batch."
            )
            logger.error(error_msg)
            raise LockAcquisitionError(error_msg)

        try:
            logger.info(
                f"Acquired batch lock: batch_id={batch_id}, operation={operation}, "
                f"instance={self.instance_id}"
            )
            yield

        finally:
            # Always release lock
            self._release_lock(batch_id)

    def _try_acquire_lock(self, batch_id: str, operation: str) -> bool:
        """
        Attempt to acquire a batch lock using Firestore transaction.

        Args:
            batch_id: Batch identifier
            operation: Operation type

        Returns:
            True if lock acquired, False otherwise
        """
        lock_ref = self.locks_collection.document(batch_id)
        firestore = _get_firestore()

        @firestore.transactional
        def acquire_in_transaction(transaction):
            """Atomically check and acquire lock in transaction."""
            snapshot = lock_ref.get(transaction=transaction)

            if snapshot.exists:
                # Lock exists - check if expired or held by dead instance
                lock_data = snapshot.to_dict()
                lock = BatchLock.from_firestore_dict(lock_data)

                if not lock.is_expired():
                    # Check if holder is still alive
                    holder_instance = self._get_instance_info(lock.holder_instance_id)
                    if holder_instance and holder_instance.is_alive():
                        # Lock is valid and holder is alive
                        logger.debug(
                            f"Lock {batch_id} held by active instance {lock.holder_instance_id}"
                        )
                        return False

                # Lock expired or holder dead - can acquire
                logger.warning(
                    f"Taking over lock {batch_id} (holder {lock.holder_instance_id} "
                    f"is {'expired' if lock.is_expired() else 'dead'})"
                )

            # Acquire lock
            new_lock = BatchLock(
                batch_id=batch_id,
                holder_instance_id=self.instance_id,
                operation=operation
            )
            transaction.set(lock_ref, new_lock.to_firestore_dict())
            return True

        # Execute transaction
        transaction = self.db.transaction()
        try:
            acquired = acquire_in_transaction(transaction)
            if acquired:
                self._active_locks[batch_id] = BatchLock(
                    batch_id=batch_id,
                    holder_instance_id=self.instance_id,
                    operation=operation,
                    acquired_at=datetime.now(timezone.utc),
                    expires_at=datetime.now(timezone.utc) + timedelta(seconds=LOCK_TIMEOUT_SECONDS)
                )
            return acquired
        except Exception as e:
            logger.error(f"Transaction error acquiring lock: {e}", exc_info=True)
            return False

    def _release_lock(self, batch_id: str):
        """
        Release a batch lock.

        Args:
            batch_id: Batch identifier
        """
        try:
            lock_ref = self.locks_collection.document(batch_id)

            # Verify we hold the lock before deleting
            doc = lock_ref.get()
            if doc.exists:
                lock_data = doc.to_dict()
                if lock_data.get('holder_instance_id') == self.instance_id:
                    lock_ref.delete()
                    logger.info(f"Released batch lock: {batch_id}")
                else:
                    logger.warning(
                        f"Cannot release lock {batch_id} - held by different instance "
                        f"({lock_data.get('holder_instance_id')})"
                    )
            else:
                logger.debug(f"Lock {batch_id} already released")

            # Remove from active locks
            self._active_locks.pop(batch_id, None)

        except Exception as e:
            logger.error(f"Error releasing lock {batch_id}: {e}", exc_info=True)

    def _get_instance_info(self, instance_id: str) -> Optional[InstanceInfo]:
        """Get info for a specific instance."""
        doc_ref = self.instances_collection.document(instance_id)
        doc = doc_ref.get()

        if doc.exists:
            return InstanceInfo.from_firestore_dict(doc.to_dict())
        return None

    def refresh_lock(self, batch_id: str) -> bool:
        """
        Refresh the expiration time on a held lock.

        Call this periodically for long-running operations to prevent
        the lock from expiring.

        Args:
            batch_id: Batch identifier

        Returns:
            True if lock refreshed, False if we don't hold it
        """
        if batch_id not in self._active_locks:
            logger.warning(f"Cannot refresh lock {batch_id} - not in active locks")
            return False

        try:
            lock_ref = self.locks_collection.document(batch_id)

            # Verify we still hold the lock
            doc = lock_ref.get()
            if not doc.exists:
                logger.warning(f"Lock {batch_id} no longer exists")
                self._active_locks.pop(batch_id, None)
                return False

            lock_data = doc.to_dict()
            if lock_data.get('holder_instance_id') != self.instance_id:
                logger.warning(f"Lock {batch_id} taken by another instance")
                self._active_locks.pop(batch_id, None)
                return False

            # Refresh expiration
            new_expires = datetime.now(timezone.utc) + timedelta(seconds=LOCK_TIMEOUT_SECONDS)
            lock_ref.update({'expires_at': new_expires})

            # Update local tracking
            self._active_locks[batch_id].expires_at = new_expires

            logger.debug(f"Refreshed lock {batch_id}, new expiry: {new_expires}")
            return True

        except Exception as e:
            logger.error(f"Error refreshing lock {batch_id}: {e}", exc_info=True)
            return False

    def get_lock_holder(self, batch_id: str) -> Optional[str]:
        """
        Get the instance ID holding a batch lock.

        Args:
            batch_id: Batch identifier

        Returns:
            Instance ID or None if not locked
        """
        lock_ref = self.locks_collection.document(batch_id)
        doc = lock_ref.get()

        if doc.exists:
            lock = BatchLock.from_firestore_dict(doc.to_dict())
            if not lock.is_expired():
                return lock.holder_instance_id

        return None

    def is_lock_held_by_me(self, batch_id: str) -> bool:
        """
        Check if this instance holds a batch lock.

        Args:
            batch_id: Batch identifier

        Returns:
            True if this instance holds the lock
        """
        return self.get_lock_holder(batch_id) == self.instance_id

    def force_release_lock(self, batch_id: str):
        """
        Force release a lock regardless of holder.

        USE WITH CAUTION: Only call if you're certain no operation is in progress.

        Args:
            batch_id: Batch identifier
        """
        try:
            lock_ref = self.locks_collection.document(batch_id)
            doc = lock_ref.get()

            if doc.exists:
                lock_data = doc.to_dict()
                lock_ref.delete()
                logger.warning(
                    f"FORCE RELEASED lock {batch_id} "
                    f"(was held by {lock_data.get('holder_instance_id')})"
                )
            else:
                logger.info(f"Lock {batch_id} not found (already released)")

        except Exception as e:
            logger.error(f"Error force releasing lock {batch_id}: {e}", exc_info=True)
            raise


# Singleton instance
_instance_manager: Optional[CoordinatorInstanceManager] = None


def get_instance_manager(project_id: str) -> CoordinatorInstanceManager:
    """
    Get or create singleton CoordinatorInstanceManager instance.

    Args:
        project_id: GCP project ID

    Returns:
        CoordinatorInstanceManager instance
    """
    global _instance_manager

    if _instance_manager is None:
        _instance_manager = CoordinatorInstanceManager(project_id)

    return _instance_manager

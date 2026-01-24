"""
Processor Heartbeat System
===========================
Enables quick detection of stuck/stale processors (15 min instead of 4 hours).

Key Components:
1. ProcessorHeartbeat - Emits heartbeats during processing
2. HeartbeatMonitor - Detects stale processors and auto-recovers

Architecture:
- Processors emit heartbeat to Firestore every 60 seconds
- Monitor Cloud Function runs every 5 minutes
- If heartbeat missing for 15 minutes, processor is marked stale
- Auto-recovery: mark failed, clear locks, optionally retry

This was created after the Jan 23, 2026 incident where a processor
stuck in "running" state for 4 hours blocked downstream processing.

Version: 1.0
Created: 2026-01-24
"""

import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Callable
from dataclasses import dataclass
from enum import Enum

from google.cloud import firestore
from google.cloud import bigquery

logger = logging.getLogger(__name__)


class ProcessorState(Enum):
    """Processor health states."""
    HEALTHY = "healthy"           # Heartbeat within threshold
    STALE = "stale"              # Missing heartbeat 5-15 min
    DEAD = "dead"                # Missing heartbeat > 15 min
    COMPLETED = "completed"      # Normal completion
    FAILED = "failed"            # Failed with error


@dataclass
class HeartbeatConfig:
    """Configuration for heartbeat system."""
    heartbeat_interval_seconds: int = 60     # Emit heartbeat every 60s
    stale_threshold_seconds: int = 300       # 5 minutes - investigate
    dead_threshold_seconds: int = 900        # 15 minutes - auto-recover
    collection_name: str = "processor_heartbeats"


class ProcessorHeartbeat:
    """
    Emits heartbeats during processor execution.

    Usage:
        heartbeat = ProcessorHeartbeat(
            processor_name="MLFeatureStoreProcessor",
            run_id="abc-123",
            data_date="2026-01-24"
        )

        heartbeat.start()
        try:
            # ... do processing ...
            heartbeat.update_progress(50, 100, "Processing players")
        finally:
            heartbeat.stop()
    """

    def __init__(
        self,
        processor_name: str,
        run_id: str,
        data_date: str,
        config: HeartbeatConfig = None,
        project_id: str = None
    ):
        """
        Initialize heartbeat emitter.

        Args:
            processor_name: Name of the processor
            run_id: Unique run identifier
            data_date: Data date being processed
            config: Heartbeat configuration
            project_id: GCP project ID
        """
        self.processor_name = processor_name
        self.run_id = run_id
        self.data_date = data_date
        self.config = config or HeartbeatConfig()
        self.project_id = project_id or os.environ.get('GCP_PROJECT', 'nba-props-platform')

        self._firestore = None
        self._running = False
        self._thread = None
        self._progress = 0
        self._total = 0
        self._status_message = ""
        self._started_at = None

    @property
    def firestore(self) -> firestore.Client:
        """Lazy-load Firestore client."""
        if self._firestore is None:
            self._firestore = firestore.Client(project=self.project_id)
        return self._firestore

    @property
    def doc_id(self) -> str:
        """Document ID for this processor run."""
        return f"{self.processor_name}_{self.data_date}_{self.run_id}"

    def start(self):
        """Start emitting heartbeats in background thread."""
        if self._running:
            return

        self._running = True
        self._started_at = datetime.now(timezone.utc)

        # Write initial heartbeat
        self._emit_heartbeat()

        # Start background thread
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()

        logger.info(f"Started heartbeat for {self.processor_name} (run_id={self.run_id})")

    def stop(self, final_status: str = "completed"):
        """
        Stop emitting heartbeats.

        Args:
            final_status: Final status to record (completed, failed, etc.)
        """
        self._running = False

        if self._thread:
            self._thread.join(timeout=5)

        # Write final heartbeat with completion status
        self._emit_heartbeat(final_status=final_status)

        logger.info(f"Stopped heartbeat for {self.processor_name} (status={final_status})")

    def update_progress(self, current: int, total: int, message: str = ""):
        """
        Update progress information.

        Args:
            current: Current progress count
            total: Total expected count
            message: Status message
        """
        self._progress = current
        self._total = total
        self._status_message = message

    def _heartbeat_loop(self):
        """Background loop that emits heartbeats."""
        while self._running:
            time.sleep(self.config.heartbeat_interval_seconds)
            if self._running:  # Check again after sleep
                try:
                    self._emit_heartbeat()
                except Exception as e:
                    logger.error(f"Failed to emit heartbeat: {e}")

    def _emit_heartbeat(self, final_status: str = None):
        """Write heartbeat to Firestore."""
        now = datetime.now(timezone.utc)

        doc_data = {
            'processor_name': self.processor_name,
            'run_id': self.run_id,
            'data_date': self.data_date,
            'last_heartbeat': now,
            'started_at': self._started_at,
            'status': final_status or 'running',
            'progress': self._progress,
            'total': self._total,
            'status_message': self._status_message,
            'updated_at': now
        }

        if final_status:
            doc_data['completed_at'] = now
            duration = (now - self._started_at).total_seconds() if self._started_at else 0
            doc_data['duration_seconds'] = duration

        self.firestore.collection(self.config.collection_name).document(self.doc_id).set(
            doc_data,
            merge=True
        )


class HeartbeatMonitor:
    """
    Monitors processor heartbeats and detects stale/dead processors.

    Usage (typically in a Cloud Function):
        monitor = HeartbeatMonitor()
        stale_processors = monitor.check_all()

        for proc in stale_processors:
            if proc['state'] == ProcessorState.DEAD:
                monitor.auto_recover(proc)
    """

    def __init__(
        self,
        config: HeartbeatConfig = None,
        project_id: str = None
    ):
        """
        Initialize heartbeat monitor.

        Args:
            config: Heartbeat configuration
            project_id: GCP project ID
        """
        self.config = config or HeartbeatConfig()
        self.project_id = project_id or os.environ.get('GCP_PROJECT', 'nba-props-platform')
        self._firestore = None
        self._bigquery = None

    @property
    def firestore(self) -> firestore.Client:
        """Lazy-load Firestore client."""
        if self._firestore is None:
            self._firestore = firestore.Client(project=self.project_id)
        return self._firestore

    @property
    def bigquery(self) -> bigquery.Client:
        """Lazy-load BigQuery client."""
        if self._bigquery is None:
            self._bigquery = bigquery.Client(project=self.project_id)
        return self._bigquery

    def check_all(self) -> list:
        """
        Check all active processor heartbeats.

        Returns:
            List of processors with issues (stale or dead)
        """
        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(seconds=self.config.stale_threshold_seconds)
        dead_threshold = now - timedelta(seconds=self.config.dead_threshold_seconds)

        issues = []

        # Query for all running processors
        docs = (
            self.firestore.collection(self.config.collection_name)
            .where('status', '==', 'running')
            .stream()
        )

        for doc in docs:
            data = doc.to_dict()
            last_heartbeat = data.get('last_heartbeat')

            if not last_heartbeat:
                continue

            # Convert to datetime if needed
            if hasattr(last_heartbeat, 'timestamp'):
                last_heartbeat = datetime.fromtimestamp(last_heartbeat.timestamp(), tz=timezone.utc)

            # Determine state
            if last_heartbeat < dead_threshold:
                state = ProcessorState.DEAD
            elif last_heartbeat < stale_threshold:
                state = ProcessorState.STALE
            else:
                state = ProcessorState.HEALTHY

            if state in (ProcessorState.STALE, ProcessorState.DEAD):
                age_seconds = (now - last_heartbeat).total_seconds()
                issues.append({
                    'doc_id': doc.id,
                    'processor_name': data.get('processor_name'),
                    'run_id': data.get('run_id'),
                    'data_date': data.get('data_date'),
                    'last_heartbeat': last_heartbeat,
                    'age_seconds': age_seconds,
                    'state': state,
                    'progress': data.get('progress', 0),
                    'total': data.get('total', 0),
                    'status_message': data.get('status_message', '')
                })

        return issues

    def auto_recover(self, processor_info: Dict) -> Dict:
        """
        Auto-recover a dead processor.

        Steps:
        1. Mark heartbeat as failed
        2. Update processor_run_history to failed
        3. Clear any locks
        4. Optionally trigger retry

        Args:
            processor_info: Processor information from check_all()

        Returns:
            Recovery result
        """
        doc_id = processor_info['doc_id']
        processor_name = processor_info['processor_name']
        data_date = processor_info['data_date']
        run_id = processor_info['run_id']

        logger.warning(
            f"Auto-recovering stale processor: {processor_name} "
            f"(data_date={data_date}, run_id={run_id}, "
            f"last_heartbeat={processor_info['age_seconds']:.0f}s ago)"
        )

        result = {
            'processor_name': processor_name,
            'data_date': data_date,
            'run_id': run_id,
            'actions': []
        }

        # 1. Mark heartbeat as failed
        try:
            self.firestore.collection(self.config.collection_name).document(doc_id).update({
                'status': 'failed',
                'failure_reason': 'auto_recovery_stale_heartbeat',
                'recovered_at': datetime.now(timezone.utc)
            })
            result['actions'].append('marked_heartbeat_failed')
        except Exception as e:
            logger.error(f"Failed to update heartbeat doc: {e}")

        # 2. Update processor_run_history
        try:
            update_query = f"""
            UPDATE `{self.project_id}.nba_reference.processor_run_history`
            SET status = 'failed',
                failure_category = 'STALE_HEARTBEAT',
                skip_reason = 'Auto-recovered: heartbeat stale for {processor_info["age_seconds"]:.0f}s'
            WHERE processor_name = @processor_name
              AND data_date = @data_date
              AND run_id = @run_id
              AND status = 'running'
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("processor_name", "STRING", processor_name),
                    bigquery.ScalarQueryParameter("data_date", "DATE", data_date),
                    bigquery.ScalarQueryParameter("run_id", "STRING", run_id),
                ]
            )

            self.bigquery.query(update_query, job_config=job_config).result()
            result['actions'].append('updated_run_history')
        except Exception as e:
            logger.error(f"Failed to update run history: {e}")

        # 3. Clear locks
        try:
            lock_id = f"{processor_name}_{data_date}"
            self.firestore.collection('processing_locks').document(lock_id).delete()
            result['actions'].append('cleared_lock')
        except Exception as e:
            logger.debug(f"No lock to clear or error: {e}")

        result['success'] = len(result['actions']) > 0
        return result

    def cleanup_old_heartbeats(self, max_age_days: int = 7):
        """
        Clean up old heartbeat documents.

        Args:
            max_age_days: Delete heartbeats older than this many days
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

        docs = (
            self.firestore.collection(self.config.collection_name)
            .where('updated_at', '<', cutoff)
            .limit(500)  # Batch delete
            .stream()
        )

        batch = self.firestore.batch()
        count = 0

        for doc in docs:
            batch.delete(doc.reference)
            count += 1

        if count > 0:
            batch.commit()
            logger.info(f"Cleaned up {count} old heartbeat documents")

        return count

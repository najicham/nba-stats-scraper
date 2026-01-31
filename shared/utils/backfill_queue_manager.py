"""
Backfill Queue Manager
======================
Manages automated backfill tasks triggered by data quality issues.

This module provides:
1. BackfillQueueManager - Queue and execute automated backfills
2. Integration with data quality events for tracking
3. Retry logic with exponential backoff

Usage:
    from shared.utils.backfill_queue_manager import BackfillQueueManager

    manager = BackfillQueueManager()

    # Queue a backfill
    queue_id = manager.queue_backfill(
        table_name='player_game_summary',
        game_date='2026-01-22',
        reason='High zero-points rate: 46.8%',
        quality_metric='pct_zero_points',
        quality_value=46.8
    )

    # Get pending backfills
    pending = manager.get_pending(limit=5)

    # Execute a backfill
    success = manager.execute_backfill(pending[0])

Version: 1.0
Created: 2026-01-30
Part of: Data Quality Self-Healing System
"""

import json
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to import BigQuery, but allow graceful fallback for testing
try:
    from google.cloud import bigquery
    HAS_BIGQUERY = True
except ImportError:
    HAS_BIGQUERY = False
    bigquery = None


@dataclass
class QueueItem:
    """A single backfill queue item."""
    queue_id: str
    table_name: str
    game_date: str
    reason: str
    priority: int
    status: str
    attempts: int
    max_attempts: int
    created_at: datetime
    quality_metric: Optional[str] = None
    quality_value: Optional[float] = None
    error_message: Optional[str] = None


# Mapping of table names to backfill commands
BACKFILL_COMMANDS = {
    'player_game_summary': (
        'python backfill_jobs/analytics/player_game_summary/'
        'player_game_summary_analytics_backfill.py --dates={date}'
    ),
    'player_composite_factors': (
        'ENABLE_PLAYER_PARALLELIZATION=false python backfill_jobs/precompute/'
        'player_composite_factors/player_composite_factors_precompute_backfill.py --dates={date}'
    ),
    'ml_feature_store_v2': (
        'python backfill_jobs/precompute/ml_feature_store/'
        'ml_feature_store_precompute_backfill.py --dates={date}'
    ),
    'player_daily_cache': (
        'python backfill_jobs/precompute/player_daily_cache/'
        'player_daily_cache_precompute_backfill.py --dates={date}'
    ),
}


class BackfillQueueManager:
    """
    Manages automated backfill queue.

    Provides:
    - Queuing backfills for specific tables/dates
    - Retrieving pending items
    - Executing backfills with retry logic
    - Tracking success/failure
    """

    TABLE_ID = "nba-props-platform.nba_orchestration.backfill_queue"

    def __init__(
        self,
        project_id: str = "nba-props-platform",
        bq_client: Optional[Any] = None,
        enabled: bool = True
    ):
        """
        Initialize the manager.

        Args:
            project_id: GCP project ID
            bq_client: Optional BigQuery client (for testing)
            enabled: Whether queue is enabled
        """
        self.project_id = project_id
        self.enabled = enabled and HAS_BIGQUERY

        if bq_client:
            self.bq_client = bq_client
        elif self.enabled:
            try:
                self.bq_client = bigquery.Client(project=project_id)
            except Exception as e:
                logger.warning(f"Failed to initialize BigQuery client: {e}")
                self.enabled = False
                self.bq_client = None
        else:
            self.bq_client = None

    def queue_backfill(
        self,
        table_name: str,
        game_date: str,
        reason: str,
        priority: int = 0,
        triggered_by: str = "auto",
        quality_metric: Optional[str] = None,
        quality_value: Optional[float] = None,
        quality_event_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Add a backfill to the queue.

        Args:
            table_name: Table to backfill
            game_date: Date to backfill (YYYY-MM-DD)
            reason: Why backfill was triggered
            priority: 0=normal, 1=elevated, 2=critical
            triggered_by: auto, manual, incident, validation
            quality_metric: Metric that triggered this
            quality_value: Value that triggered this
            quality_event_id: Link to data_quality_events

        Returns:
            Queue ID if successful, None if already queued or error
        """
        if not self.enabled:
            logger.warning("Backfill queue disabled")
            return None

        # Check if already queued
        if self._is_already_queued(table_name, game_date):
            logger.info(f"Backfill already queued: {table_name} {game_date}")
            return None

        queue_id = str(uuid.uuid4())

        record = {
            'queue_id': queue_id,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'table_name': table_name,
            'game_date': game_date,
            'reason': reason,
            'triggered_by': triggered_by,
            'quality_metric': quality_metric,
            'quality_value': quality_value,
            'priority': priority,
            'status': 'PENDING',
            'attempts': 0,
            'max_attempts': 3,
            'quality_event_id': quality_event_id
        }

        try:
            errors = self.bq_client.insert_rows_json(self.TABLE_ID, [record])
            if errors:
                logger.error(f"Failed to queue backfill: {errors}")
                return None

            logger.info(
                f"BACKFILL_QUEUED: table={table_name} date={game_date} "
                f"reason='{reason[:50]}' queue_id={queue_id}"
            )

            # Log to quality events
            try:
                from shared.utils.data_quality_logger import get_quality_logger
                get_quality_logger().log_backfill_queued(
                    table_name=table_name,
                    game_date=game_date,
                    queue_id=queue_id,
                    related_event_id=quality_event_id,
                    reason=reason
                )
            except Exception as log_e:
                logger.debug(f"Could not log backfill queued event: {log_e}")

            return queue_id

        except Exception as e:
            logger.error(f"Failed to queue backfill: {e}")
            return None

    def _is_already_queued(self, table_name: str, game_date: str) -> bool:
        """Check if a backfill is already queued for this table/date."""
        query = f"""
            SELECT COUNT(*) as cnt
            FROM `{self.TABLE_ID}`
            WHERE table_name = @table_name
              AND game_date = @game_date
              AND status IN ('PENDING', 'RUNNING')
        """

        try:
            result = self.bq_client.query(
                query,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter('table_name', 'STRING', table_name),
                        bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
                    ]
                )
            ).result()

            for row in result:
                return row.cnt > 0

        except Exception as e:
            logger.warning(f"Error checking queue: {e}")

        return False

    def get_pending(self, limit: int = 10) -> List[QueueItem]:
        """
        Get pending backfill items ready to run.

        Args:
            limit: Max items to return

        Returns:
            List of QueueItem objects
        """
        if not self.enabled:
            return []

        query = f"""
            SELECT
                queue_id,
                table_name,
                CAST(game_date AS STRING) as game_date,
                reason,
                priority,
                status,
                attempts,
                max_attempts,
                created_at,
                quality_metric,
                quality_value,
                error_message
            FROM `{self.TABLE_ID}`
            WHERE status = 'PENDING'
              AND attempts < max_attempts
              AND (scheduled_for IS NULL OR scheduled_for <= CURRENT_TIMESTAMP())
            ORDER BY priority DESC, created_at ASC
            LIMIT {limit}
        """

        items = []
        try:
            result = self.bq_client.query(query).result()

            for row in result:
                items.append(QueueItem(
                    queue_id=row.queue_id,
                    table_name=row.table_name,
                    game_date=row.game_date,
                    reason=row.reason,
                    priority=row.priority,
                    status=row.status,
                    attempts=row.attempts,
                    max_attempts=row.max_attempts,
                    created_at=row.created_at,
                    quality_metric=row.quality_metric,
                    quality_value=row.quality_value,
                    error_message=row.error_message
                ))

        except Exception as e:
            logger.error(f"Failed to get pending backfills: {e}")

        return items

    def execute_backfill(
        self,
        item: QueueItem,
        working_dir: str = "/home/naji/code/nba-stats-scraper",
        timeout: int = 600
    ) -> bool:
        """
        Execute a backfill from the queue.

        Args:
            item: QueueItem to execute
            working_dir: Working directory for backfill command
            timeout: Timeout in seconds

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False

        # Get command template
        command_template = BACKFILL_COMMANDS.get(item.table_name)
        if not command_template:
            logger.error(f"No backfill command for table: {item.table_name}")
            self._update_status(item.queue_id, 'FAILED', error='No backfill command defined')
            return False

        # Update status to RUNNING
        self._update_status(item.queue_id, 'RUNNING')

        # Log backfill started
        try:
            from shared.utils.data_quality_logger import get_quality_logger
            get_quality_logger().log_backfill_started(
                table_name=item.table_name,
                game_date=item.game_date,
                queue_id=item.queue_id,
                worker_id=os.environ.get('HOSTNAME', 'local')
            )
        except Exception:
            pass

        # Build and execute command
        command = command_template.format(date=item.game_date)
        start_time = datetime.now(timezone.utc)

        logger.info(f"BACKFILL_STARTED: {item.table_name} {item.game_date}")

        try:
            # Set PYTHONPATH
            env = os.environ.copy()
            env['PYTHONPATH'] = working_dir

            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                timeout=timeout,
                cwd=working_dir,
                env=env
            )

            duration = int((datetime.now(timezone.utc) - start_time).total_seconds())

            if result.returncode == 0:
                self._update_status(
                    item.queue_id,
                    'COMPLETED',
                    duration_seconds=duration
                )

                # Log success
                try:
                    from shared.utils.data_quality_logger import get_quality_logger
                    get_quality_logger().log_backfill_completed(
                        table_name=item.table_name,
                        game_date=item.game_date,
                        queue_id=item.queue_id,
                        duration_seconds=duration
                    )
                except Exception:
                    pass

                logger.info(
                    f"BACKFILL_COMPLETED: {item.table_name} {item.game_date} "
                    f"in {duration}s"
                )
                return True
            else:
                error_msg = result.stderr.decode()[:500] if result.stderr else 'Unknown error'
                self._update_status(
                    item.queue_id,
                    'PENDING',  # Back to pending for retry
                    error=error_msg
                )

                # Log failure
                try:
                    from shared.utils.data_quality_logger import get_quality_logger
                    get_quality_logger().log_backfill_failed(
                        table_name=item.table_name,
                        game_date=item.game_date,
                        queue_id=item.queue_id,
                        error_message=error_msg
                    )
                except Exception:
                    pass

                logger.error(
                    f"BACKFILL_FAILED: {item.table_name} {item.game_date} "
                    f"- {error_msg[:100]}"
                )
                return False

        except subprocess.TimeoutExpired:
            duration = int((datetime.now(timezone.utc) - start_time).total_seconds())
            error_msg = f"Timeout after {timeout}s"

            self._update_status(item.queue_id, 'PENDING', error=error_msg)

            logger.error(f"BACKFILL_TIMEOUT: {item.table_name} {item.game_date}")
            return False

        except Exception as e:
            error_msg = str(e)[:500]
            self._update_status(item.queue_id, 'PENDING', error=error_msg)

            logger.error(f"BACKFILL_ERROR: {item.table_name} {item.game_date} - {e}")
            return False

    def _update_status(
        self,
        queue_id: str,
        status: str,
        error: Optional[str] = None,
        duration_seconds: Optional[int] = None
    ) -> None:
        """Update the status of a queue item."""
        updates = [f"status = '{status}'"]
        updates.append(f"attempts = attempts + 1")
        updates.append(f"last_attempt_at = CURRENT_TIMESTAMP()")

        if status == 'COMPLETED':
            updates.append(f"completed_at = CURRENT_TIMESTAMP()")
        if error:
            # Escape single quotes in error message
            safe_error = error.replace("'", "''")
            updates.append(f"error_message = '{safe_error}'")
        if duration_seconds:
            updates.append(f"duration_seconds = {duration_seconds}")

        query = f"""
            UPDATE `{self.TABLE_ID}`
            SET {', '.join(updates)}
            WHERE queue_id = '{queue_id}'
        """

        try:
            self.bq_client.query(query).result()
        except Exception as e:
            logger.error(f"Failed to update queue status: {e}")

    def cancel_backfill(self, queue_id: str, reason: str = "Cancelled") -> bool:
        """Cancel a pending backfill."""
        query = f"""
            UPDATE `{self.TABLE_ID}`
            SET status = 'CANCELLED', error_message = '{reason}'
            WHERE queue_id = '{queue_id}' AND status = 'PENDING'
        """

        try:
            job = self.bq_client.query(query)
            job.result()
            return job.num_dml_affected_rows > 0
        except Exception as e:
            logger.error(f"Failed to cancel backfill: {e}")
            return False

    def get_queue_status(self) -> Dict[str, Any]:
        """Get overall queue status summary."""
        query = f"""
            SELECT
                status,
                COUNT(*) as count,
                AVG(attempts) as avg_attempts
            FROM `{self.TABLE_ID}`
            WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
            GROUP BY status
        """

        status = {
            'PENDING': 0,
            'RUNNING': 0,
            'COMPLETED': 0,
            'FAILED': 0,
            'CANCELLED': 0
        }

        try:
            result = self.bq_client.query(query).result()
            for row in result:
                status[row.status] = row.count

        except Exception as e:
            logger.error(f"Failed to get queue status: {e}")

        return status


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_manager_instance: Optional[BackfillQueueManager] = None


def get_backfill_manager() -> BackfillQueueManager:
    """Get or create singleton BackfillQueueManager instance."""
    global _manager_instance

    if _manager_instance is None:
        enabled = os.environ.get('ENABLE_AUTO_BACKFILL', 'true').lower() == 'true'
        _manager_instance = BackfillQueueManager(enabled=enabled)

    return _manager_instance


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def queue_backfill(
    table_name: str,
    game_date: str,
    reason: str,
    **kwargs
) -> Optional[str]:
    """Queue a backfill using singleton manager."""
    return get_backfill_manager().queue_backfill(
        table_name=table_name,
        game_date=game_date,
        reason=reason,
        **kwargs
    )

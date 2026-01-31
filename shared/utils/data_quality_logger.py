"""
Data Quality Event Logger
=========================
Logs data quality events to BigQuery for audit trail and visibility.
Tracks when quality was low, when issues were detected, and when data self-healed.

This module provides:
1. DataQualityLogger - Main logger class
2. Event types for quality lifecycle (detection, alerting, remediation)
3. Integration with notification system

Usage:
    from shared.utils.data_quality_logger import DataQualityLogger, QualityEventType

    logger = DataQualityLogger()

    # Log a quality issue
    event_id = logger.log_quality_issue(
        table_name='player_game_summary',
        game_date='2026-01-22',
        metric_name='pct_zero_points',
        metric_value=46.8,
        severity='CRITICAL',
        description='High zero-points rate detected: 46.8%'
    )

    # Log self-healing
    logger.log_self_healed(
        related_event_id=event_id,
        table_name='player_game_summary',
        game_date='2026-01-22',
        metric_name='pct_zero_points',
        new_value=8.5,
        description='Data quality restored after backfill'
    )

Version: 1.0
Created: 2026-01-30
Part of: Data Quality Self-Healing System
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to import BigQuery, but allow graceful fallback for testing
try:
    from google.cloud import bigquery
    HAS_BIGQUERY = True
except ImportError:
    HAS_BIGQUERY = False
    bigquery = None


class QualityEventType(Enum):
    """Types of data quality events."""
    QUALITY_ISSUE_DETECTED = "QUALITY_ISSUE_DETECTED"
    BACKFILL_QUEUED = "BACKFILL_QUEUED"
    BACKFILL_STARTED = "BACKFILL_STARTED"
    BACKFILL_COMPLETED = "BACKFILL_COMPLETED"
    BACKFILL_FAILED = "BACKFILL_FAILED"
    SELF_HEALED = "SELF_HEALED"
    VALIDATION_BLOCKED = "VALIDATION_BLOCKED"
    ALERT_SENT = "ALERT_SENT"
    MANUAL_FIX_APPLIED = "MANUAL_FIX_APPLIED"


class Severity(Enum):
    """Severity levels for quality events."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ResolutionStatus(Enum):
    """Resolution status for quality issues."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"


@dataclass
class QualityEvent:
    """A single data quality event."""
    event_id: str
    event_timestamp: datetime
    event_type: QualityEventType
    severity: Severity
    description: str

    # Context
    table_name: Optional[str] = None
    game_date: Optional[date] = None
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    threshold_breached: Optional[str] = None

    # Details
    details_json: Optional[str] = None
    resolution_status: Optional[ResolutionStatus] = None

    # Remediation tracking
    backfill_queue_id: Optional[str] = None
    triggered_by: Optional[str] = None
    related_event_id: Optional[str] = None
    duration_seconds: Optional[int] = None

    # Metadata
    processor_name: Optional[str] = None
    session_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for BigQuery insert."""
        return {
            'event_id': self.event_id,
            'event_timestamp': self.event_timestamp.isoformat(),
            'event_type': self.event_type.value,
            'table_name': self.table_name,
            'game_date': str(self.game_date) if self.game_date else None,
            'metric_name': self.metric_name,
            'metric_value': self.metric_value,
            'threshold_breached': self.threshold_breached,
            'severity': self.severity.value,
            'description': self.description,
            'details_json': self.details_json,
            'resolution_status': self.resolution_status.value if self.resolution_status else None,
            'backfill_queue_id': self.backfill_queue_id,
            'triggered_by': self.triggered_by,
            'related_event_id': self.related_event_id,
            'duration_seconds': self.duration_seconds,
            'processor_name': self.processor_name,
            'session_id': self.session_id,
        }


class DataQualityLogger:
    """
    Logs data quality events to BigQuery.

    Provides visibility into:
    - When data quality was low
    - When issues were detected
    - When remediation was attempted
    - When data self-healed
    """

    TABLE_ID = "nba-props-platform.nba_orchestration.data_quality_events"

    def __init__(
        self,
        project_id: str = "nba-props-platform",
        bq_client: Optional[Any] = None,
        enabled: bool = True
    ):
        """
        Initialize the logger.

        Args:
            project_id: GCP project ID
            bq_client: Optional BigQuery client (for testing)
            enabled: Whether logging is enabled
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

        # Buffer for batch writes
        self._event_buffer: List[Dict] = []
        self._buffer_size = 10

    def log_quality_issue(
        self,
        table_name: str,
        metric_name: str,
        metric_value: float,
        severity: str,
        description: str,
        game_date: Optional[str] = None,
        threshold_breached: Optional[str] = None,
        details: Optional[Dict] = None,
        triggered_by: str = "daily_check",
        processor_name: Optional[str] = None
    ) -> str:
        """
        Log a quality issue detection.

        Args:
            table_name: Affected table
            metric_name: Name of quality metric
            metric_value: Value that triggered the issue
            severity: INFO, WARNING, or CRITICAL
            description: Human-readable description
            game_date: Affected date (YYYY-MM-DD string)
            threshold_breached: 'warning' or 'critical'
            details: Additional details dict
            triggered_by: What triggered detection
            processor_name: Processor that detected issue

        Returns:
            Event ID for linking related events
        """
        event_id = str(uuid.uuid4())

        event = QualityEvent(
            event_id=event_id,
            event_timestamp=datetime.now(timezone.utc),
            event_type=QualityEventType.QUALITY_ISSUE_DETECTED,
            severity=Severity[severity.upper()],
            description=description,
            table_name=table_name,
            game_date=date.fromisoformat(game_date) if game_date else None,
            metric_name=metric_name,
            metric_value=metric_value,
            threshold_breached=threshold_breached,
            details_json=json.dumps(details) if details else None,
            resolution_status=ResolutionStatus.PENDING,
            triggered_by=triggered_by,
            processor_name=processor_name
        )

        self._write_event(event)

        logger.info(
            f"QUALITY_ISSUE_DETECTED: table={table_name} metric={metric_name} "
            f"value={metric_value} severity={severity} event_id={event_id}"
        )

        return event_id

    def log_backfill_queued(
        self,
        table_name: str,
        game_date: str,
        queue_id: str,
        related_event_id: Optional[str] = None,
        reason: Optional[str] = None
    ) -> str:
        """Log that a backfill was queued."""
        event_id = str(uuid.uuid4())

        event = QualityEvent(
            event_id=event_id,
            event_timestamp=datetime.now(timezone.utc),
            event_type=QualityEventType.BACKFILL_QUEUED,
            severity=Severity.INFO,
            description=f"Auto-backfill queued for {table_name} {game_date}" + (f": {reason}" if reason else ""),
            table_name=table_name,
            game_date=date.fromisoformat(game_date) if game_date else None,
            backfill_queue_id=queue_id,
            related_event_id=related_event_id,
            triggered_by="quality_check"
        )

        self._write_event(event)
        return event_id

    def log_backfill_started(
        self,
        table_name: str,
        game_date: str,
        queue_id: str,
        worker_id: Optional[str] = None
    ) -> str:
        """Log that a backfill started."""
        event_id = str(uuid.uuid4())

        event = QualityEvent(
            event_id=event_id,
            event_timestamp=datetime.now(timezone.utc),
            event_type=QualityEventType.BACKFILL_STARTED,
            severity=Severity.INFO,
            description=f"Backfill started for {table_name} {game_date}",
            table_name=table_name,
            game_date=date.fromisoformat(game_date) if game_date else None,
            backfill_queue_id=queue_id,
            processor_name=worker_id
        )

        self._write_event(event)
        return event_id

    def log_backfill_completed(
        self,
        table_name: str,
        game_date: str,
        queue_id: str,
        duration_seconds: int,
        records_processed: Optional[int] = None,
        related_event_id: Optional[str] = None
    ) -> str:
        """Log that a backfill completed successfully."""
        event_id = str(uuid.uuid4())

        details = {'records_processed': records_processed} if records_processed else None

        event = QualityEvent(
            event_id=event_id,
            event_timestamp=datetime.now(timezone.utc),
            event_type=QualityEventType.BACKFILL_COMPLETED,
            severity=Severity.INFO,
            description=f"Backfill completed for {table_name} {game_date} in {duration_seconds}s",
            table_name=table_name,
            game_date=date.fromisoformat(game_date) if game_date else None,
            backfill_queue_id=queue_id,
            related_event_id=related_event_id,
            duration_seconds=duration_seconds,
            details_json=json.dumps(details) if details else None,
            resolution_status=ResolutionStatus.IN_PROGRESS
        )

        self._write_event(event)
        return event_id

    def log_backfill_failed(
        self,
        table_name: str,
        game_date: str,
        queue_id: str,
        error_message: str,
        related_event_id: Optional[str] = None
    ) -> str:
        """Log that a backfill failed."""
        event_id = str(uuid.uuid4())

        event = QualityEvent(
            event_id=event_id,
            event_timestamp=datetime.now(timezone.utc),
            event_type=QualityEventType.BACKFILL_FAILED,
            severity=Severity.WARNING,
            description=f"Backfill failed for {table_name} {game_date}: {error_message[:100]}",
            table_name=table_name,
            game_date=date.fromisoformat(game_date) if game_date else None,
            backfill_queue_id=queue_id,
            related_event_id=related_event_id,
            details_json=json.dumps({'error': error_message}),
            resolution_status=ResolutionStatus.FAILED
        )

        self._write_event(event)
        return event_id

    def log_self_healed(
        self,
        table_name: str,
        game_date: str,
        metric_name: str,
        old_value: float,
        new_value: float,
        related_event_id: str,
        description: Optional[str] = None
    ) -> str:
        """
        Log that data quality was restored (self-healed).

        This is the key event that shows the system fixed itself.
        """
        event_id = str(uuid.uuid4())

        improvement = old_value - new_value
        desc = description or f"Data quality restored: {metric_name} improved from {old_value:.1f} to {new_value:.1f}"

        event = QualityEvent(
            event_id=event_id,
            event_timestamp=datetime.now(timezone.utc),
            event_type=QualityEventType.SELF_HEALED,
            severity=Severity.INFO,
            description=desc,
            table_name=table_name,
            game_date=date.fromisoformat(game_date) if game_date else None,
            metric_name=metric_name,
            metric_value=new_value,
            related_event_id=related_event_id,
            resolution_status=ResolutionStatus.RESOLVED,
            details_json=json.dumps({
                'old_value': old_value,
                'new_value': new_value,
                'improvement': improvement
            }),
            triggered_by="backfill"
        )

        self._write_event(event)

        # Also update the original issue's resolution status
        self._update_issue_resolved(related_event_id)

        logger.info(
            f"SELF_HEALED: table={table_name} metric={metric_name} "
            f"old={old_value:.1f} new={new_value:.1f} event_id={event_id}"
        )

        return event_id

    def log_validation_blocked(
        self,
        table_name: str,
        game_date: Optional[str],
        player_lookup: Optional[str],
        violations: List[str],
        processor_name: Optional[str] = None
    ) -> str:
        """Log that pre-write validation blocked records."""
        event_id = str(uuid.uuid4())

        event = QualityEvent(
            event_id=event_id,
            event_timestamp=datetime.now(timezone.utc),
            event_type=QualityEventType.VALIDATION_BLOCKED,
            severity=Severity.WARNING,
            description=f"Pre-write validation blocked record: {violations[0][:100] if violations else 'unknown'}",
            table_name=table_name,
            game_date=date.fromisoformat(game_date) if game_date else None,
            details_json=json.dumps({
                'player_lookup': player_lookup,
                'violations': violations[:5]  # Limit to 5
            }),
            processor_name=processor_name,
            triggered_by="validation"
        )

        self._write_event(event)
        return event_id

    def log_alert_sent(
        self,
        table_name: str,
        metric_name: str,
        severity: str,
        channel: str,
        related_event_id: Optional[str] = None
    ) -> str:
        """Log that an alert was sent."""
        event_id = str(uuid.uuid4())

        event = QualityEvent(
            event_id=event_id,
            event_timestamp=datetime.now(timezone.utc),
            event_type=QualityEventType.ALERT_SENT,
            severity=Severity[severity.upper()],
            description=f"Alert sent via {channel} for {table_name}.{metric_name}",
            table_name=table_name,
            metric_name=metric_name,
            related_event_id=related_event_id,
            details_json=json.dumps({'channel': channel}),
            triggered_by="alerting"
        )

        self._write_event(event)
        return event_id

    def log_manual_fix(
        self,
        table_name: str,
        game_date: str,
        description: str,
        related_event_id: Optional[str] = None
    ) -> str:
        """Log that a manual fix was applied."""
        event_id = str(uuid.uuid4())

        event = QualityEvent(
            event_id=event_id,
            event_timestamp=datetime.now(timezone.utc),
            event_type=QualityEventType.MANUAL_FIX_APPLIED,
            severity=Severity.INFO,
            description=description,
            table_name=table_name,
            game_date=date.fromisoformat(game_date) if game_date else None,
            related_event_id=related_event_id,
            resolution_status=ResolutionStatus.RESOLVED,
            triggered_by="manual"
        )

        self._write_event(event)

        if related_event_id:
            self._update_issue_resolved(related_event_id)

        return event_id

    def _write_event(self, event: QualityEvent) -> None:
        """Write event to BigQuery."""
        if not self.enabled:
            logger.debug(f"Quality logging disabled, skipping: {event.event_type.value}")
            return

        try:
            self._event_buffer.append(event.to_dict())

            if len(self._event_buffer) >= self._buffer_size:
                self.flush()
        except Exception as e:
            logger.error(f"Failed to buffer quality event: {e}")

    def flush(self) -> None:
        """Flush buffered events to BigQuery."""
        if not self._event_buffer or not self.enabled:
            return

        try:
            errors = self.bq_client.insert_rows_json(
                self.TABLE_ID,
                self._event_buffer
            )

            if errors:
                logger.error(f"BigQuery insert errors: {errors[:3]}")
            else:
                logger.debug(f"Flushed {len(self._event_buffer)} quality events")

            self._event_buffer = []
        except Exception as e:
            logger.error(f"Failed to flush quality events: {e}")

    def _update_issue_resolved(self, event_id: str) -> None:
        """Update the resolution status of an issue to RESOLVED."""
        # This would require an UPDATE query which is more complex
        # For now, we track resolution through the SELF_HEALED event chain
        pass

    def __del__(self):
        """Flush remaining events on destruction."""
        try:
            self.flush()
        except Exception:
            pass


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_logger_instance: Optional[DataQualityLogger] = None


def get_quality_logger() -> DataQualityLogger:
    """Get or create singleton DataQualityLogger instance."""
    global _logger_instance

    if _logger_instance is None:
        enabled = os.environ.get('ENABLE_QUALITY_LOGGING', 'true').lower() == 'true'
        _logger_instance = DataQualityLogger(enabled=enabled)

    return _logger_instance


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def log_quality_issue(
    table_name: str,
    metric_name: str,
    metric_value: float,
    severity: str,
    description: str,
    **kwargs
) -> str:
    """Log a quality issue using singleton logger."""
    return get_quality_logger().log_quality_issue(
        table_name=table_name,
        metric_name=metric_name,
        metric_value=metric_value,
        severity=severity,
        description=description,
        **kwargs
    )


def log_self_healed(
    table_name: str,
    game_date: str,
    metric_name: str,
    old_value: float,
    new_value: float,
    related_event_id: str,
    **kwargs
) -> str:
    """Log self-healing using singleton logger."""
    return get_quality_logger().log_self_healed(
        table_name=table_name,
        game_date=game_date,
        metric_name=metric_name,
        old_value=old_value,
        new_value=new_value,
        related_event_id=related_event_id,
        **kwargs
    )

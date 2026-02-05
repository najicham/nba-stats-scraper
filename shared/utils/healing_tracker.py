"""
Healing Event Tracker (Session 135 - Self-Healing with Observability)

Tracks all self-healing actions with full audit trail to enable:
1. Root cause analysis
2. Pattern detection
3. Prevention recommendations
4. Alert escalation when healing too frequent

Philosophy: "Auto-heal, but track everything so we can prevent recurrence"

Usage:
    from shared.utils.healing_tracker import HealingTracker

    tracker = HealingTracker(project_id='nba-props-platform')

    # Record a healing action
    healing_id = tracker.record_healing(
        healing_type='batch_cleanup',
        trigger_reason='Batch stalled at 87% for 15+ minutes',
        action_taken='Force completed batch batch_2026-02-05_xyz',
        before_state={'completed': 119, 'expected': 136, 'is_complete': False},
        after_state={'completed': 119, 'expected': 136, 'is_complete': True},
        success=True,
        metadata={
            'batch_id': 'batch_2026-02-05_xyz',
            'stall_duration_minutes': 17,
            'completion_pct': 87.5,
            'injured_player_count': 17
        }
    )

    # Check for healing patterns
    pattern = tracker.check_healing_pattern('batch_cleanup', hours=1)
    if pattern.should_alert:
        # Send alert to humans - healing too frequent

Created: 2026-02-05
"""

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

from google.cloud import firestore, bigquery

logger = logging.getLogger(__name__)


@dataclass
class HealingEvent:
    """Represents a single self-healing action."""

    healing_id: str
    timestamp: datetime
    healing_type: str  # 'batch_cleanup', 'retry', 'fallback', 'circuit_breaker_reset', etc.
    trigger_reason: str  # Why healing was needed (root cause)
    action_taken: str  # What we did to heal
    before_state: Dict[str, Any]  # State before healing
    after_state: Dict[str, Any]  # State after healing
    success: bool  # Did healing work?
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for Firestore/BigQuery."""
        return {
            'healing_id': self.healing_id,
            'timestamp': self.timestamp,
            'healing_type': self.healing_type,
            'trigger_reason': self.trigger_reason,
            'action_taken': self.action_taken,
            'before_state': self.before_state,
            'after_state': self.after_state,
            'success': self.success,
            'metadata': self.metadata
        }


@dataclass
class HealingPattern:
    """Analysis of healing frequency and patterns."""

    healing_type: str
    count: int  # Number of healing events in window
    time_window_hours: int
    should_alert: bool  # True if healing too frequent
    alert_level: str  # 'yellow', 'red', 'critical'
    message: str
    recent_events: List[HealingEvent] = field(default_factory=list)


class HealingTracker:
    """
    Tracks self-healing actions with full audit trail.

    Stores events in both Firestore (real-time) and BigQuery (analytics).
    Detects patterns and alerts when healing becomes too frequent.
    """

    # Alert thresholds
    YELLOW_THRESHOLD = 3  # Same healing 3+ times in 1 hour
    RED_THRESHOLD = 10  # Same healing 10+ times in 1 day
    CRITICAL_FAILURE_RATE = 0.2  # 20% failure rate

    def __init__(
        self,
        project_id: str,
        firestore_collection: str = 'healing_events',
        bigquery_table: str = 'nba_orchestration.healing_events'
    ):
        """
        Initialize healing tracker.

        Args:
            project_id: GCP project ID
            firestore_collection: Firestore collection for real-time tracking
            bigquery_table: BigQuery table for analytics
        """
        self.project_id = project_id
        self.firestore_collection = firestore_collection
        self.bigquery_table = bigquery_table

        # Initialize clients
        self.db = firestore.Client(project=project_id)
        self.bq_client = bigquery.Client(project=project_id)

    def record_healing(
        self,
        healing_type: str,
        trigger_reason: str,
        action_taken: str,
        before_state: Dict[str, Any],
        after_state: Dict[str, Any],
        success: bool,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record a self-healing action with full audit trail.

        Args:
            healing_type: Type of healing (batch_cleanup, retry, fallback, etc.)
            trigger_reason: Why healing was needed (root cause)
            action_taken: What action was taken
            before_state: State before healing
            after_state: State after healing
            success: Whether healing succeeded
            metadata: Additional context-specific data

        Returns:
            healing_id: Unique ID for this healing event
        """
        healing_id = f"heal_{uuid.uuid4().hex[:12]}"
        timestamp = datetime.now(timezone.utc)

        event = HealingEvent(
            healing_id=healing_id,
            timestamp=timestamp,
            healing_type=healing_type,
            trigger_reason=trigger_reason,
            action_taken=action_taken,
            before_state=before_state,
            after_state=after_state,
            success=success,
            metadata=metadata or {}
        )

        # Write to Firestore (real-time tracking)
        try:
            self.db.collection(self.firestore_collection).document(healing_id).set({
                **event.to_dict(),
                'timestamp': firestore.SERVER_TIMESTAMP
            })
            logger.info(
                f"🩹 Healing event recorded: {healing_type} - {trigger_reason} "
                f"(success={success}, id={healing_id})"
            )
        except Exception as e:
            logger.error(f"Failed to write healing event to Firestore: {e}")

        # Write to BigQuery (analytics, non-blocking)
        try:
            self._write_to_bigquery(event)
        except Exception as e:
            logger.warning(f"Failed to write healing event to BigQuery: {e}")

        # Check for patterns (alert if healing too frequent)
        try:
            pattern = self.check_healing_pattern(healing_type, hours=1)
            if pattern.should_alert:
                self._send_pattern_alert(pattern)
        except Exception as e:
            logger.warning(f"Failed to check healing pattern: {e}")

        return healing_id

    def check_healing_pattern(
        self,
        healing_type: str,
        hours: int = 1
    ) -> HealingPattern:
        """
        Check if healing is happening too frequently (indicates root cause).

        Args:
            healing_type: Type of healing to check
            hours: Time window to analyze

        Returns:
            HealingPattern with analysis and alert recommendation
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Query recent events from Firestore
        events_ref = self.db.collection(self.firestore_collection) \
            .where('healing_type', '==', healing_type) \
            .where('timestamp', '>=', cutoff) \
            .order_by('timestamp', direction=firestore.Query.DESCENDING)

        events = []
        for doc in events_ref.stream():
            data = doc.to_dict()
            events.append(HealingEvent(
                healing_id=data['healing_id'],
                timestamp=data['timestamp'],
                healing_type=data['healing_type'],
                trigger_reason=data['trigger_reason'],
                action_taken=data['action_taken'],
                before_state=data['before_state'],
                after_state=data['after_state'],
                success=data['success'],
                metadata=data.get('metadata', {})
            ))

        count = len(events)
        failure_count = sum(1 for e in events if not e.success)
        failure_rate = failure_count / count if count > 0 else 0

        # Determine alert level
        should_alert = False
        alert_level = 'none'
        message = f"{count} {healing_type} events in last {hours}h"

        if failure_rate > self.CRITICAL_FAILURE_RATE:
            should_alert = True
            alert_level = 'critical'
            message = (
                f"🚨 CRITICAL: {healing_type} has {failure_rate:.0%} failure rate "
                f"({failure_count}/{count} failed in {hours}h)"
            )
        elif hours == 24 and count >= self.RED_THRESHOLD:
            should_alert = True
            alert_level = 'red'
            message = (
                f"🔴 RED ALERT: {healing_type} triggered {count} times in {hours}h "
                f"(threshold: {self.RED_THRESHOLD})"
            )
        elif hours == 1 and count >= self.YELLOW_THRESHOLD:
            should_alert = True
            alert_level = 'yellow'
            message = (
                f"⚠️ YELLOW ALERT: {healing_type} triggered {count} times in {hours}h "
                f"(threshold: {self.YELLOW_THRESHOLD})"
            )

        return HealingPattern(
            healing_type=healing_type,
            count=count,
            time_window_hours=hours,
            should_alert=should_alert,
            alert_level=alert_level,
            message=message,
            recent_events=events[:5]  # Most recent 5
        )

    def _write_to_bigquery(self, event: HealingEvent) -> None:
        """Write healing event to BigQuery for analytics."""
        row = {
            'healing_id': event.healing_id,
            'timestamp': event.timestamp.isoformat(),
            'healing_type': event.healing_type,
            'trigger_reason': event.trigger_reason,
            'action_taken': event.action_taken,
            'before_state': str(event.before_state),  # JSON as string
            'after_state': str(event.after_state),
            'success': event.success,
            'metadata': str(event.metadata)
        }

        errors = self.bq_client.insert_rows_json(self.bigquery_table, [row])
        if errors:
            logger.warning(f"BigQuery insert errors: {errors}")

    def _send_pattern_alert(self, pattern: HealingPattern) -> None:
        """Send Slack alert when healing is too frequent."""
        try:
            from shared.utils.slack_alerts import send_slack_alert

            # Build detailed message
            lines = [
                f"*Healing Pattern Alert: {pattern.healing_type}*",
                "",
                pattern.message,
                "",
                "*Recent Events:*"
            ]

            for event in pattern.recent_events[:3]:
                lines.append(f"• {event.timestamp.strftime('%H:%M:%S')}: {event.trigger_reason}")

            lines.extend([
                "",
                "*Action Required:*",
                "1. Review healing events to identify root cause",
                "2. Implement prevention fix if pattern is systemic",
                "3. Query: `SELECT * FROM nba_orchestration.healing_events WHERE healing_type = "
                f"'{pattern.healing_type}' ORDER BY timestamp DESC LIMIT 20`"
            ])

            message = "\n".join(lines)

            # Send to appropriate channel based on severity
            channel = {
                'critical': '#app-error-alerts',
                'red': '#nba-alerts',
                'yellow': '#nba-alerts'
            }.get(pattern.alert_level, '#nba-alerts')

            send_slack_alert(
                message=message,
                channel=channel,
                alert_type=f"HEALING_PATTERN_{pattern.alert_level.upper()}"
            )

        except Exception as e:
            logger.error(f"Failed to send pattern alert: {e}")

    def get_healing_summary(
        self,
        start_date: datetime,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Get summary of healing events for analysis.

        Args:
            start_date: Start of analysis period
            end_date: End of analysis period (default: now)

        Returns:
            Summary dict with counts, success rates, common triggers
        """
        if end_date is None:
            end_date = datetime.now(timezone.utc)

        query = f"""
        SELECT
            healing_type,
            COUNT(*) as total_events,
            SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed,
            ARRAY_AGG(DISTINCT trigger_reason LIMIT 5) as common_triggers
        FROM `{self.project_id}.{self.bigquery_table}`
        WHERE timestamp >= @start_date
          AND timestamp <= @end_date
        GROUP BY healing_type
        ORDER BY total_events DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "TIMESTAMP", start_date),
                bigquery.ScalarQueryParameter("end_date", "TIMESTAMP", end_date)
            ]
        )

        result = list(self.bq_client.query(query, job_config=job_config).result())

        summary = {
            'period_start': start_date.isoformat(),
            'period_end': end_date.isoformat(),
            'by_type': []
        }

        for row in result:
            summary['by_type'].append({
                'healing_type': row.healing_type,
                'total': row.total_events,
                'successful': row.successful,
                'failed': row.failed,
                'success_rate': row.successful / row.total_events if row.total_events > 0 else 0,
                'common_triggers': row.common_triggers
            })

        return summary

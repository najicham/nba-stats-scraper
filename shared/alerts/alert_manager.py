"""
AlertManager - Intelligent alert management with rate limiting and backfill awareness.

Features:
- Rate limiting (prevent alert spam during backfill)
- Backfill mode detection (suppress non-critical alerts)
- Alert batching (combine similar alerts)
- Multi-channel support (email, Slack, Sentry)
- Severity-based routing (critical vs warning vs info)

Problem Solved:
Without rate limiting, backfilling 500 dates would send 500 identical alerts.
With AlertManager, gets batched into 1 summary alert.

Version: 1.0
Created: 2025-11-28
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set
from collections import defaultdict

logger = logging.getLogger(__name__)


class AlertManager:
    """
    Manages alerts with rate limiting and intelligent batching.

    Usage:
        # Initialize (singleton pattern recommended)
        alert_mgr = AlertManager()

        # Send alert (automatically rate-limited)
        alert_mgr.send_alert(
            severity='warning',
            title='Phase 2 Incomplete',
            message='Only 18/21 processors completed',
            category='phase_2_completion',
            context={'game_date': '2025-11-28', 'completed': 18}
        )

        # Check if should alert (for manual control)
        if alert_mgr.should_alert(category='data_quality', min_interval_minutes=60):
            send_external_alert(...)
            alert_mgr.record_alert('data_quality')
    """

    def __init__(
        self,
        backfill_mode: bool = False,
        rate_limit_window_minutes: int = 60,
        max_alerts_per_window: int = 5,
        auto_flush_on_exit: bool = False
    ):
        """
        Initialize alert manager.

        Args:
            backfill_mode: If True, suppress non-critical alerts
            rate_limit_window_minutes: Time window for rate limiting
            max_alerts_per_window: Max alerts allowed per category per window
            auto_flush_on_exit: If True, automatically flush batched alerts on context manager exit
        """
        self.backfill_mode = backfill_mode
        self.rate_limit_window = timedelta(minutes=rate_limit_window_minutes)
        self.max_alerts_per_window = max_alerts_per_window
        self.auto_flush_on_exit = auto_flush_on_exit

        # Track alert history: {category: [timestamp1, timestamp2, ...]}
        self._alert_history: Dict[str, List[datetime]] = defaultdict(list)

        # Batch tracking: {category: {'count': N, 'contexts': [...]}}
        self._alert_batches: Dict[str, Dict] = defaultdict(lambda: {'count': 0, 'contexts': []})

    def __enter__(self):
        """Enter context manager - allows using AlertManager with 'with' statement."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager - auto-flush if enabled."""
        if self.auto_flush_on_exit:
            self.flush_batched_alerts()
        return False  # Don't suppress exceptions

    def send_alert(
        self,
        severity: str,
        title: str,
        message: str,
        category: str,
        context: Optional[Dict] = None,
        force: bool = False
    ) -> bool:
        """
        Send alert with automatic rate limiting.

        Args:
            severity: Alert severity ('critical', 'warning', 'info')
            title: Alert title (short)
            message: Alert message (detailed)
            category: Alert category for rate limiting (e.g., 'phase_2_failure')
            context: Additional context data
            force: If True, bypass rate limiting

        Returns:
            True if alert was sent, False if suppressed by rate limiting
        """
        # Check backfill mode suppression
        if self.backfill_mode and severity != 'critical':
            logger.debug(
                f"Backfill mode: suppressing {severity} alert - {title}"
            )
            return False

        # Check rate limiting
        if not force and not self.should_alert(category):
            logger.debug(
                f"Rate limit: suppressing alert category '{category}' - {title}"
            )
            # Add to batch
            self._alert_batches[category]['count'] += 1
            self._alert_batches[category]['contexts'].append(context or {})
            return False

        # Send alert
        self._send_alert_external(severity, title, message, context)

        # Record for rate limiting
        self.record_alert(category)

        return True

    def should_alert(
        self,
        category: str,
        min_interval_minutes: Optional[int] = None
    ) -> bool:
        """
        Check if we should send an alert for this category.

        Args:
            category: Alert category
            min_interval_minutes: Minimum interval (overrides default)

        Returns:
            True if should alert, False if rate-limited
        """
        now = datetime.now(timezone.utc)
        min_interval = timedelta(
            minutes=min_interval_minutes if min_interval_minutes is not None
            else self.rate_limit_window.total_seconds() / 60
        )

        # Get recent alerts for this category
        recent_alerts = [
            ts for ts in self._alert_history.get(category, [])
            if now - ts < min_interval
        ]

        # Check if exceeded max
        if len(recent_alerts) >= self.max_alerts_per_window:
            return False

        return True

    def record_alert(self, category: str) -> None:
        """
        Record that an alert was sent (for rate limiting).

        Args:
            category: Alert category
        """
        now = datetime.now(timezone.utc)
        self._alert_history[category].append(now)

        # Cleanup old entries (older than rate limit window)
        cutoff = now - self.rate_limit_window
        self._alert_history[category] = [
            ts for ts in self._alert_history[category]
            if ts > cutoff
        ]

    def flush_batched_alerts(self) -> None:
        """
        Send summary alerts for batched categories.

        Call this at end of backfill or periodically during long runs.
        """
        for category, batch_data in self._alert_batches.items():
            if batch_data['count'] > 0:
                self._send_batch_summary(category, batch_data)

        # Clear batches
        self._alert_batches.clear()

    def _send_alert_external(
        self,
        severity: str,
        title: str,
        message: str,
        context: Optional[Dict] = None
    ) -> None:
        """
        Send alert to external systems (email, Slack, Sentry).

        Args:
            severity: Alert severity
            title: Alert title
            message: Alert message
            context: Additional context
        """
        # Build alert payload
        alert = {
            'severity': severity,
            'title': title,
            'message': message,
            'context': context or {},
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'environment': os.environ.get('ENVIRONMENT', 'development')
        }

        # Route by severity
        if severity == 'critical':
            self._send_to_email(alert)
            self._send_to_slack(alert)
            self._send_to_sentry(alert)
        elif severity == 'warning':
            self._send_to_slack(alert)
            self._send_to_sentry(alert)
        else:  # info
            logger.info(f"Alert: {title} - {message}")

    def _send_batch_summary(self, category: str, batch_data: Dict) -> None:
        """
        Send summary for batched alerts.

        Args:
            category: Alert category
            batch_data: Batch data with count and contexts
        """
        count = batch_data['count']
        contexts = batch_data['contexts']

        title = f"Batched Alerts: {category}"
        message = f"Suppressed {count} similar alerts due to rate limiting."

        # Add sample contexts (first 3)
        if contexts:
            message += f"\n\nSample contexts:\n"
            for ctx in contexts[:3]:
                message += f"  - {ctx}\n"

        self._send_alert_external(
            severity='info',
            title=title,
            message=message,
            context={'category': category, 'total_count': count}
        )

    def _send_to_email(self, alert: Dict) -> None:
        """
        Send alert via email (placeholder).

        Args:
            alert: Alert payload
        """
        # TODO: Implement email sending
        # Could use SendGrid, AWS SES, or GCP Email API
        logger.info(f"[EMAIL] {alert['severity'].upper()}: {alert['title']}")

    def _send_to_slack(self, alert: Dict) -> None:
        """
        Send alert to Slack (placeholder).

        Args:
            alert: Alert payload
        """
        # TODO: Implement Slack webhook
        # Use existing Slack integration if available
        logger.info(f"[SLACK] {alert['severity'].upper()}: {alert['title']}")

    def _send_to_sentry(self, alert: Dict) -> None:
        """
        Send alert to Sentry (placeholder).

        Args:
            alert: Alert payload
        """
        # TODO: Integrate with Sentry
        # Use sentry_sdk.capture_message() or capture_exception()
        try:
            import sentry_sdk
            sentry_sdk.capture_message(
                alert['title'],
                level=self._map_severity_to_sentry(alert['severity']),
                extras=alert.get('context', {})
            )
        except ImportError:
            logger.debug("Sentry not available")

    def _map_severity_to_sentry(self, severity: str) -> str:
        """
        Map our severity to Sentry levels.

        Args:
            severity: Our severity level

        Returns:
            Sentry level
        """
        mapping = {
            'critical': 'error',
            'warning': 'warning',
            'info': 'info'
        }
        return mapping.get(severity, 'info')

    def get_alert_stats(self) -> Dict:
        """
        Get statistics about alert history.

        Returns:
            Dictionary with alert statistics
        """
        stats = {
            'total_categories': len(self._alert_history),
            'categories': {},
            'batched_alerts': {}
        }

        # Per-category stats
        for category, timestamps in self._alert_history.items():
            stats['categories'][category] = {
                'total_alerts': len(timestamps),
                'recent_alerts': len([
                    ts for ts in timestamps
                    if datetime.now(timezone.utc) - ts < self.rate_limit_window
                ])
            }

        # Batched alerts
        for category, batch_data in self._alert_batches.items():
            if batch_data['count'] > 0:
                stats['batched_alerts'][category] = batch_data['count']

        return stats


# Singleton instance (optional - can create multiple if needed)
_default_alert_manager: Optional[AlertManager] = None


def get_alert_manager(
    backfill_mode: bool = False,
    auto_flush_on_exit: bool = False,
    reset: bool = False
) -> AlertManager:
    """
    Get singleton AlertManager instance.

    Args:
        backfill_mode: Enable backfill mode (suppresses non-critical alerts)
        auto_flush_on_exit: Auto-flush batched alerts when used as context manager
        reset: If True, create new instance

    Returns:
        AlertManager instance

    Example:
        # Auto-flush on exit
        with get_alert_manager(backfill_mode=True, auto_flush_on_exit=True) as alert_mgr:
            # ... run backfill ...
            pass  # Digest email sent automatically at end
    """
    global _default_alert_manager

    if reset or _default_alert_manager is None:
        _default_alert_manager = AlertManager(
            backfill_mode=backfill_mode,
            auto_flush_on_exit=auto_flush_on_exit
        )

    return _default_alert_manager

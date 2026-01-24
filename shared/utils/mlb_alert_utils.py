"""
MLB Alert Utilities
====================
Shared alert utilities for MLB services (analytics, precompute, grading).

Consolidates duplicate get_mlb_alert_manager() and send_mlb_alert() functions
from main_mlb_*_service.py files.

Usage:
    from shared.utils.mlb_alert_utils import send_mlb_alert, get_mlb_alert_manager

    # Send an alert
    send_mlb_alert(
        severity='warning',
        title='Processing Warning',
        message='Some players missing data',
        category='mlb_analytics_failure',
        context={'game_date': '2026-01-24'}
    )

Version: 1.0
Created: 2026-01-24
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import AlertManager
try:
    from shared.utils.alerting import get_alert_manager
    ALERTING_ENABLED = True
except ImportError:
    ALERTING_ENABLED = False
    logger.warning("AlertManager not available, MLB alerts disabled")

    def get_alert_manager(**kwargs):
        return None


def get_mlb_alert_manager():
    """
    Get AlertManager instance with MLB-specific configuration.

    Respects BACKFILL_MODE environment variable to suppress alerts during backfills.

    Returns:
        AlertManager instance or None if alerting is disabled
    """
    if not ALERTING_ENABLED:
        return None

    backfill_mode = os.environ.get('BACKFILL_MODE', 'false').lower() == 'true'
    return get_alert_manager(backfill_mode=backfill_mode)


def send_mlb_alert(
    severity: str,
    title: str,
    message: str,
    category: str,
    context: Optional[dict] = None
) -> bool:
    """
    Send alert via AlertManager with rate limiting.

    Args:
        severity: Alert severity ('info', 'warning', 'error', 'critical')
        title: Alert title
        message: Alert message body
        category: Alert category for rate limiting. Common values:
            - 'mlb_analytics_failure'
            - 'mlb_precompute_failure'
            - 'mlb_grading_failure'
        context: Optional context dict with additional metadata

    Returns:
        True if alert was sent successfully, False otherwise
    """
    alert_mgr = get_mlb_alert_manager()

    if not alert_mgr:
        logger.debug(f"Alert suppressed (manager unavailable): {title}")
        return False

    try:
        alert_mgr.send_alert(
            severity=severity,
            title=title,
            message=message,
            category=category,
            context=context or {}
        )
        return True

    except Exception as e:
        logger.error(f"Failed to send MLB alert: {e}")
        return False


def send_mlb_analytics_alert(
    severity: str,
    title: str,
    message: str,
    context: Optional[dict] = None
) -> bool:
    """Convenience function for analytics alerts."""
    return send_mlb_alert(severity, title, message, 'mlb_analytics_failure', context)


def send_mlb_precompute_alert(
    severity: str,
    title: str,
    message: str,
    context: Optional[dict] = None
) -> bool:
    """Convenience function for precompute alerts."""
    return send_mlb_alert(severity, title, message, 'mlb_precompute_failure', context)


def send_mlb_grading_alert(
    severity: str,
    title: str,
    message: str,
    context: Optional[dict] = None
) -> bool:
    """Convenience function for grading alerts."""
    return send_mlb_alert(severity, title, message, 'mlb_grading_failure', context)

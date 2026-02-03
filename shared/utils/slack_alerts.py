# shared/utils/slack_alerts.py
"""
Slack Alert Utility (Session 97)

Simple interface for sending Slack alerts from the prediction system.
Wraps the slack_retry module for easy use.

Usage:
    from shared.utils.slack_alerts import send_slack_alert

    send_slack_alert(
        message="Alert message",
        channel="#nba-alerts",
        alert_type="LOW_QUALITY_FEATURES"
    )

Channel Mapping:
- #nba-alerts: Uses SLACK_WEBHOOK_URL_WARNING
- #app-error-alerts: Uses SLACK_WEBHOOK_URL_ERROR
- Default: Uses SLACK_WEBHOOK_URL
"""

import logging
import os
from typing import Optional

from shared.utils.slack_retry import send_slack_webhook_with_retry

logger = logging.getLogger(__name__)

# Channel to environment variable mapping
CHANNEL_ENV_MAP = {
    '#nba-alerts': 'SLACK_WEBHOOK_URL_WARNING',
    '#app-error-alerts': 'SLACK_WEBHOOK_URL_ERROR',
    '#daily-orchestration': 'SLACK_WEBHOOK_URL',
    '#nba-predictions': 'SLACK_WEBHOOK_URL_PREDICTIONS',
    '#nba-betting-signals': 'SLACK_WEBHOOK_URL_SIGNALS',
}


def send_slack_alert(
    message: str,
    channel: str = "#nba-alerts",
    alert_type: Optional[str] = None,
    webhook_url: Optional[str] = None
) -> bool:
    """
    Send a Slack alert message.

    Args:
        message: The message to send (supports Slack markdown)
        channel: Slack channel (used to look up webhook if not provided)
        alert_type: Optional alert type for logging/tracking
        webhook_url: Optional explicit webhook URL (otherwise looked up by channel)

    Returns:
        True if message sent successfully, False otherwise
    """
    # Get webhook URL
    if webhook_url is None:
        env_var = CHANNEL_ENV_MAP.get(channel, 'SLACK_WEBHOOK_URL')
        webhook_url = os.environ.get(env_var)

        # Fall back to default webhook if channel-specific not found
        if not webhook_url and env_var != 'SLACK_WEBHOOK_URL':
            webhook_url = os.environ.get('SLACK_WEBHOOK_URL')

    if not webhook_url:
        logger.warning(f"No Slack webhook URL configured for channel {channel}")
        return False

    # Build payload
    payload = {
        "text": message,
    }

    # Send with retry
    try:
        success = send_slack_webhook_with_retry(webhook_url, payload)
        if success:
            logger.info(f"Sent Slack alert to {channel}: {alert_type or 'general'}")
        return success
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False

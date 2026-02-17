"""
Push Notifications via Pushover

Sends push notifications for alerts and reminders.
Simple REST API, no carrier registration needed.

Usage:
    from shared.utils.pushover_notifier import PushoverNotifier

    notifier = PushoverNotifier()
    notifier.send("Your message here")
    notifier.send("Urgent!", priority=1)  # High priority with sound

Environment Variables:
    PUSHOVER_USER_KEY: Pushover user key (from dashboard)
    PUSHOVER_APP_TOKEN: Pushover application API token

Session: 272 (2026-02-16)
"""

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"


class PushoverNotifier:
    """Send push notifications via Pushover."""

    def __init__(self):
        self.user_key = os.environ.get('PUSHOVER_USER_KEY')
        self.app_token = os.environ.get('PUSHOVER_APP_TOKEN')

    def is_configured(self) -> bool:
        """Check if Pushover is properly configured."""
        return bool(self.user_key and self.app_token)

    def send(self, message: str, title: Optional[str] = None,
             priority: int = 0, url: Optional[str] = None) -> bool:
        """
        Send push notification via Pushover.

        Args:
            message: Notification text
            title: Optional title (default: app name)
            priority: -2 (silent) to 2 (emergency). 0=normal, 1=high priority
            url: Optional URL to include

        Returns:
            True if sent successfully
        """
        if not self.is_configured():
            logger.warning("Pushover not configured, skipping notification")
            return False

        payload = {
            'token': self.app_token,
            'user': self.user_key,
            'message': message,
            'priority': priority,
        }

        if title:
            payload['title'] = title
        if url:
            payload['url'] = url

        try:
            resp = requests.post(PUSHOVER_API_URL, data=payload, timeout=10)
            result = resp.json()

            if result.get('status') == 1:
                logger.info("Pushover notification sent successfully")
                return True
            else:
                logger.error(f"Pushover API error: {result.get('errors', 'unknown')}")
                return False

        except Exception as e:
            logger.error(f"Failed to send Pushover notification: {e}")
            return False


def send_pushover(message: str, title: Optional[str] = None,
                  priority: int = 0) -> bool:
    """Convenience function to send a Pushover notification."""
    try:
        notifier = PushoverNotifier()
        return notifier.send(message, title=title, priority=priority)
    except Exception as e:
        logger.error(f"Failed to send Pushover notification: {e}")
        return False


if __name__ == '__main__':
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        notifier = PushoverNotifier()
        if notifier.is_configured():
            success = notifier.send(
                "NBA Props - Pushover test notification working!",
                title="NBA Props Test"
            )
            sys.exit(0 if success else 1)
        else:
            logger.error("Pushover not configured. Set PUSHOVER_USER_KEY and PUSHOVER_APP_TOKEN")
            sys.exit(1)
    else:
        print("Usage: python pushover_notifier.py --test")
        print("\nRequired env vars:")
        print("  PUSHOVER_USER_KEY")
        print("  PUSHOVER_APP_TOKEN")

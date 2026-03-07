"""Signal Decay Monitor — Cloud Function wrapper.

Delegates to signal_decay_monitor_impl (copied alongside main.py by deploy).
Scheduled daily at 12 PM ET via Cloud Scheduler.

Created: Session 430.
"""

import functions_framework
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@functions_framework.http
def signal_decay_monitor(request):
    """HTTP entry point for Cloud Scheduler."""
    try:
        from signal_decay_monitor_impl import http_handler
        return http_handler(request)
    except Exception as e:
        logger.error(f"Signal decay monitor failed: {e}")
        return (f'{{"status": "error", "message": "{e}"}}', 200,
                {'Content-Type': 'application/json'})


main = signal_decay_monitor

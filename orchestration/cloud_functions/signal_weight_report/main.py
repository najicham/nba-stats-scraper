"""Signal Weight Report — Cloud Function wrapper.

Delegates to signal_weight_report_impl (copied alongside main.py by deploy).
Scheduled weekly Monday at 10 AM ET via Cloud Scheduler.

Created: Session 430.
"""

import functions_framework
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@functions_framework.http
def signal_weight_report(request):
    """HTTP entry point for Cloud Scheduler."""
    try:
        from signal_weight_report_impl import http_handler
        return http_handler(request)
    except Exception as e:
        logger.error(f"Signal weight report failed: {e}")
        return (f'{{"status": "error", "message": "{e}"}}', 200,
                {'Content-Type': 'application/json'})


main = signal_weight_report

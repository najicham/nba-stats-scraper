"""Data Source Health Canary — Cloud Function wrapper.

Delegates to data_source_health_canary_impl (copied alongside main.py by deploy).
Scheduled daily at 7 AM ET via Cloud Scheduler.

Created: Session 430.
"""

import functions_framework
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@functions_framework.http
def data_source_health_canary(request):
    """HTTP entry point for Cloud Scheduler."""
    try:
        from data_source_health_canary_impl import http_handler
        return http_handler(request)
    except Exception as e:
        logger.error(f"Data source health canary failed: {e}")
        return (f'{{"status": "error", "message": "{e}"}}', 200,
                {'Content-Type': 'application/json'})


main = data_source_health_canary

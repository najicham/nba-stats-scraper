"""Bias Decay Monitor — Cloud Function wrapper.

Delegates to bias_decay_monitor_impl (copied alongside main.py by deploy).
Scheduled daily at 11:30 AM ET via Cloud Scheduler, mirrors the
filter-counterfactual-evaluator window.

Created: 2026-05-16 (anomaly follow-up — see
docs/08-projects/current/2026-05-15-2025-26-anomaly-rootcause/).
"""

import functions_framework
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@functions_framework.http
def bias_decay_monitor(request):
    """HTTP entry point for Cloud Scheduler."""
    try:
        from bias_decay_monitor_impl import http_handler
        return http_handler(request)
    except Exception as e:
        logger.error(f"Bias decay monitor failed: {e}")
        return (f'{{"status": "error", "message": "{e}"}}', 200,
                {'Content-Type': 'application/json'})


main = bias_decay_monitor

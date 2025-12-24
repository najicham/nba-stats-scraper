"""
Rate-limited alerting system.

Prevents notification floods by:
1. Rate limiting - Max N emails per hour for same error signature
2. Deduplication - Same error = 1 email after cooldown
3. Aggregation - Count occurrences and send summary

Usage:
    from shared.alerts import get_alert_manager, should_send_alert

    # Check if alert should be sent (rate limited)
    if should_send_alert(processor_name="NbacScheduleProcessor", error_type="TypeError"):
        send_email(...)

    # Or use AlertManager directly
    alert_mgr = get_alert_manager()
    alert_mgr.send_alert(
        severity='error',
        title='Processor Failed',
        message='...',
        category='NbacScheduleProcessor_TypeError'
    )
"""

from .rate_limiter import (
    AlertManager,
    get_alert_manager,
    should_send_alert,
    get_error_signature,
    RateLimitConfig,
)

__all__ = [
    'AlertManager',
    'get_alert_manager',
    'should_send_alert',
    'get_error_signature',
    'RateLimitConfig',
]

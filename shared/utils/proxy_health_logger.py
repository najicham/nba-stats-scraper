# shared/utils/proxy_health_logger.py
"""
Proxy Health Logger - tracks proxy success/failure metrics to BigQuery.

Usage:
    from shared.utils.proxy_health_logger import log_proxy_result

    # After a proxy request:
    log_proxy_result(
        scraper_name="bp_player_props",
        target_host="api.bettingpros.com",
        http_status_code=403,
        response_time_ms=1250,
        success=False,
        error_type="forbidden"
    )
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Lazy-loaded BigQuery client
_bq_client = None

def _get_bq_client():
    """Lazy-load BigQuery client."""
    global _bq_client
    if _bq_client is None:
        try:
            from google.cloud import bigquery
            _bq_client = bigquery.Client()
        except Exception as e:
            logger.warning(f"Failed to initialize BigQuery client: {e}")
            return None
    return _bq_client


def log_proxy_result(
    scraper_name: str,
    target_host: str,
    http_status_code: Optional[int] = None,
    response_time_ms: Optional[int] = None,
    success: bool = False,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
    proxy_ip: Optional[str] = None,
    proxy_provider: str = "proxyfuel"
) -> bool:
    """
    Log a proxy request result to BigQuery.

    Args:
        scraper_name: Name of the scraper (e.g., "bp_player_props")
        target_host: Target hostname (e.g., "api.bettingpros.com")
        http_status_code: HTTP response code (200, 403, etc.)
        response_time_ms: Response time in milliseconds
        success: Whether the request was successful
        error_type: Type of error (e.g., "forbidden", "timeout", "connection_refused")
        error_message: Detailed error message
        proxy_ip: The proxy IP used (if known)
        proxy_provider: Proxy provider name (default: "proxyfuel")

    Returns:
        True if logged successfully, False otherwise
    """
    try:
        client = _get_bq_client()
        if client is None:
            return False

        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scraper_name": scraper_name,
            "target_host": target_host,
            "proxy_provider": proxy_provider,
            "http_status_code": http_status_code,
            "response_time_ms": response_time_ms,
            "success": success,
            "error_type": error_type,
            "error_message": error_message[:500] if error_message else None,
            "proxy_ip": proxy_ip
        }

        # Insert to BigQuery (streaming insert)
        table_ref = "nba-props-platform.nba_orchestration.proxy_health_metrics"
        errors = client.insert_rows_json(table_ref, [row])

        if errors:
            logger.warning(f"BigQuery insert errors: {errors}")
            return False

        return True

    except Exception as e:
        logger.warning(f"Failed to log proxy result: {e}")
        return False


def extract_host_from_url(url: str) -> str:
    """Extract hostname from URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc or "unknown"
    except (ValueError, AttributeError) as e:
        # ValueError: invalid URL format
        # AttributeError: url is not a string
        return "unknown"


def classify_error(status_code: Optional[int] = None, exception: Optional[Exception] = None) -> str:
    """Classify error type from status code or exception."""
    if exception:
        exc_name = type(exception).__name__.lower()
        if "timeout" in exc_name:
            return "timeout"
        if "connection" in exc_name or "proxy" in exc_name:
            return "connection_error"
        return exc_name

    if status_code:
        if status_code == 403:
            return "forbidden"
        if status_code == 407:
            return "proxy_auth_failed"
        if status_code == 429:
            return "rate_limited"
        if status_code >= 500:
            return "server_error"
        if status_code >= 400:
            return f"client_error_{status_code}"

    return "unknown"

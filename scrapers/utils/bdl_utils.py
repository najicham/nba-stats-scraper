"""
File: scrapers/utils/bdl_utils.py

Shared helpers for every BALLDONTLIE scraper.

Usage:
    from scrapers.bdl.bdl_utils import (
        API_ROOT, get_json, cursor_paginate, yesterday, today_utc
    )
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, Optional

import httpx

# Import notification system
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Import rate limit handler
from shared.utils.rate_limit_handler import get_rate_limit_handler

# Import Secret Manager utilities
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from shared.utils.auth_utils import get_api_key

API_ROOT: str = "https://api.balldontlie.io/v1/"
# Try Secret Manager first, fallback to environment variable for local dev
_API_KEY: Optional[str] = get_api_key(
    secret_name='BDL_API_KEY',
    default_env_var='BDL_API_KEY'
)

if not _API_KEY:
    error_msg = (
        "Environment variable BDL_API_KEY is missing. "
        "Add it via Secret Manager or your local .env."
    )
    
    # Notify on missing API key - this affects all Ball Don't Lie scrapers
    try:
        notify_error(
            title="Ball Don't Lie API: Missing API Key",
            message="BDL_API_KEY environment variable not configured",
            details={
                'component': 'bdl_utils',
                'error': 'Missing BDL_API_KEY environment variable',
                'impact': 'All Ball Don Lie scrapers will fail',
                'action': 'Add BDL_API_KEY to Secret Manager or .env file'
            },
            processor_name="Ball Don't Lie Utils"
        )
    except Exception as notify_ex:
        # Can't even notify - just log to stderr
        import sys
        print(f"CRITICAL: {error_msg}", file=sys.stderr)
        print(f"Failed to send notification: {notify_ex}", file=sys.stderr)
    
    raise RuntimeError(error_msg)

_REQ_HEADERS: Dict[str, str] = {"Authorization": _API_KEY}
_DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

# Track rate limiting for monitoring
_rate_limit_counter = 0
_rate_limit_notification_threshold = 10

# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #
UTC = timezone.utc
today_utc = lambda: datetime.now(tz=UTC).date()
yesterday = lambda: today_utc() - timedelta(days=1)

# --------------------------------------------------------------------------- #
# Networking helpers
# --------------------------------------------------------------------------- #
def _request(
    method: str, url: str, params: Optional[Dict[str, Any]] = None
) -> httpx.Response:
    return httpx.request(
        method=method,
        url=url,
        params=params,
        headers=_REQ_HEADERS,
        timeout=_DEFAULT_TIMEOUT,
    )


def get_json(
    url: str, *, params: Optional[Dict[str, Any]] = None, max_retries: int = 3
) -> Dict[str, Any]:
    """
    Wrapper around HTTP GET that handles retries and 429 back‑off.

    Uses RateLimitHandler for intelligent rate limit handling with:
    - Exponential backoff with jitter
    - Circuit breaker for persistent rate limiting
    - Retry-After header support (future-proof, though BDL doesn't send it yet)
    """
    global _rate_limit_counter

    # Get rate limit handler
    rate_limiter = get_rate_limit_handler()
    domain = "api.balldontlie.io"

    attempt = 0
    consecutive_429s = 0

    while True:
        try:
            resp = _request("GET", url, params=params)

            if resp.status_code == 429:
                # Track rate limiting for notifications
                consecutive_429s += 1
                _rate_limit_counter += 1

                # Use RateLimitHandler to determine if we should retry
                should_retry, wait_time = rate_limiter.should_retry(
                    resp, attempt, domain
                )

                if not should_retry:
                    # Circuit breaker open or max retries exceeded
                    error_msg = f"Rate limit exceeded for {url} (circuit breaker or max retries)"

                    try:
                        notify_error(
                            title="Ball Don't Lie API: Rate Limit Circuit Breaker",
                            message=error_msg,
                            details={
                                'component': 'bdl_utils',
                                'url': url,
                                'consecutive_429s': consecutive_429s,
                                'attempts': attempt + 1,
                                'circuit_breaker_open': rate_limiter.is_circuit_open(domain),
                                'action': 'Reduce API call frequency or wait for circuit breaker to reset'
                            },
                            processor_name="Ball Don't Lie Utils"
                        )
                    except Exception as notify_ex:
                        logger.debug(f"Failed to send rate limit alert: {notify_ex}")

                    raise RuntimeError(error_msg)

                # Notify on persistent rate limiting (every N hits)
                if _rate_limit_counter >= _rate_limit_notification_threshold:
                    try:
                        notify_warning(
                            title="Ball Don't Lie API: Persistent Rate Limiting",
                            message=f"Hit rate limit {_rate_limit_counter} times across all scrapers",
                            details={
                                'component': 'bdl_utils',
                                'url': url,
                                'rate_limit_count': _rate_limit_counter,
                                'consecutive_in_request': consecutive_429s,
                                'wait_time_seconds': wait_time,
                                'circuit_breaker_failures': rate_limiter.circuit_breakers[domain].consecutive_failures if domain in rate_limiter.circuit_breakers else 0,
                                'action': 'Check API quota usage or reduce scraper frequency'
                            }
                        )
                        # Reset counter after notifying
                        _rate_limit_counter = 0
                    except Exception as notify_ex:
                        logger.debug(f"Failed to send persistent rate limit notification: {notify_ex}")

                # Back off with intelligent wait time
                time.sleep(wait_time)

            elif resp.is_success:
                # Record success for circuit breaker
                rate_limiter.record_success(domain)

                # Reset rate limit counter on success
                if _rate_limit_counter > 0:
                    _rate_limit_counter = max(0, _rate_limit_counter - 1)
                return resp.json()

            else:
                # Non-429 HTTP error
                resp.raise_for_status()
                
        except httpx.HTTPStatusError as e:
            # HTTP error (not 429, not success)
            if attempt >= max_retries - 1:
                # About to fail - notify
                try:
                    notify_error(
                        title="Ball Don't Lie API: HTTP Error After Retries",
                        message=f"HTTP {e.response.status_code} error after {max_retries} attempts",
                        details={
                            'component': 'bdl_utils',
                            'url': url,
                            'status_code': e.response.status_code,
                            'attempts': attempt + 1,
                            'error': str(e),
                            'params': str(params)[:200] if params else None
                        },
                        processor_name="Ball Don't Lie Utils"
                    )
                except Exception as notify_ex:
                    logger.debug(f"Failed to send HTTP error notification: {notify_ex}")
                raise

        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as e:
            # Network/timeout error
            if attempt >= max_retries - 1:
                # About to fail - notify
                try:
                    notify_error(
                        title="Ball Don't Lie API: Connection Failure",
                        message=f"Network error after {max_retries} attempts: {type(e).__name__}",
                        details={
                            'component': 'bdl_utils',
                            'url': url,
                            'error_type': type(e).__name__,
                            'attempts': attempt + 1,
                            'error': str(e),
                            'action': 'Check network connectivity or Ball Don Lie API status'
                        },
                        processor_name="Ball Don't Lie Utils"
                    )
                except Exception as notify_ex:
                    logger.debug(f"Failed to send connection error notification: {notify_ex}")
                raise

        except Exception as e:
            # Unexpected error
            try:
                notify_error(
                    title="Ball Don't Lie API: Unexpected Error",
                    message=f"Unexpected error in Ball Don't Lie API call: {type(e).__name__}",
                    details={
                        'component': 'bdl_utils',
                        'url': url,
                        'error_type': type(e).__name__,
                        'error': str(e),
                        'attempt': attempt + 1
                    },
                    processor_name="Ball Don't Lie Utils"
                )
            except Exception as notify_ex:
                logger.debug(f"Failed to send unexpected error notification: {notify_ex}")
            raise

        attempt += 1
        if attempt >= max_retries:
            error_msg = f"Exceeded {max_retries} retries for {url}"
            
            # Notify on max retries exceeded
            try:
                notify_error(
                    title="Ball Don't Lie API: Max Retries Exceeded",
                    message=f"Failed after {max_retries} retry attempts",
                    details={
                        'component': 'bdl_utils',
                        'url': url,
                        'max_retries': max_retries,
                        'consecutive_429s': consecutive_429s,
                        'params': str(params)[:200] if params else None,
                        'impact': 'Scraper will fail for this endpoint'
                    },
                    processor_name="Ball Don't Lie Utils"
                )
            except Exception as notify_ex:
                logger.debug(f"Failed to send max retries notification: {notify_ex}")

            raise RuntimeError(error_msg)


def cursor_paginate(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    per_page: int = 100,
    max_pages: int = 1000,
) -> Iterator[Dict[str, Any]]:
    """
    Generator that transparently walks BALLDONTLIE's cursor‑based pagination.

    Args:
        path: API endpoint path
        params: Query parameters
        per_page: Results per page (default 100)
        max_pages: Maximum pages to fetch (default 1000, prevents infinite loops)

    Example:
        for row in cursor_paginate("players", {"search": "curry"}):
            ...
    """
    q: Dict[str, Any] = dict(params or {})
    q["per_page"] = per_page
    cursor: Optional[str] = None
    page_count = 0

    while True:
        page_count += 1
        if page_count > max_pages:
            logger.warning(
                f"cursor_paginate: Hit max_pages limit ({max_pages}) for path={path}. "
                f"This may indicate an API issue or unusually large dataset."
            )
            break

        if cursor:
            q["cursor"] = cursor

        try:
            data = get_json(f"{API_ROOT}{path}", params=q)
        except Exception as e:
            # get_json already notified on failure, just log and re-raise
            raise

        yield from data["data"]

        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break
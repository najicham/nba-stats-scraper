"""
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

API_ROOT: str = "https://api.balldontlie.io/v1/"
_API_KEY: Optional[str] = os.getenv("BDL_API_KEY")

if not _API_KEY:
    raise RuntimeError(
        "Environment variable BDL_API_KEY is missing. "
        "Add it via Secret Manager or your local .env."
    )

_REQ_HEADERS: Dict[str, str] = {"Authorization": _API_KEY}
_DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

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
    """
    attempt = 0
    while True:
        resp = _request("GET", url, params=params)
        if resp.status_code == 429:
            # Back‑off: BALLDONTLIE doesn't send Retry‑After, so sleep 1.2 s
            time.sleep(1.2)
        elif resp.is_success:
            return resp.json()
        else:
            resp.raise_for_status()

        attempt += 1
        if attempt >= max_retries:
            raise RuntimeError(f"Exceeded retries for {url}")


def cursor_paginate(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    per_page: int = 100,
) -> Iterator[Dict[str, Any]]:
    """
    Generator that transparently walks BALLDONTLIE's cursor‑based pagination.

    Example:
        for row in cursor_paginate("players", {"search": "curry"}):
            ...
    """
    q: Dict[str, Any] = dict(params or {})
    q["per_page"] = per_page
    cursor: Optional[str] = None

    while True:
        if cursor:
            q["cursor"] = cursor
        data = get_json(f"{API_ROOT}{path}", params=q)
        yield from data["data"]

        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break

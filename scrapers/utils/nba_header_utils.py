"""
Centralised helpers for NBA‑site request headers.

There are three patterns:

1.  STATS_NBA_HEADERS   – classic stats.nba.com endpoints
2.  DATA_NBA_HEADERS    – cdn.nba.com / data.nba.com JSON (play‑by‑play, shotcharts)
3.  CORE_API_HEADERS    – core-api.nba.com (gamecardfeed, play‑by‑play meta)

Each helper returns a *copy* so callers can safely mutate individual fields.
"""

from copy import deepcopy
import random

USER_AGENTS = [
    # Rotate a few modern desktop agents to look more “organic”
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"),
]

def _ua():
    """Return a random desktop User‑Agent each call."""
    return random.choice(USER_AGENTS)


def stats_nba_headers() -> dict:
    base = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Host": "stats.nba.com",
        "Origin": "https://www.nba.com",
        "Pragma": "no-cache",
        "Referer": "https://www.nba.com/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": _ua(),
        "x-nba-stats-origin": "stats",
        "x-nba-stats-token": "true",
    }
    return deepcopy(base)


def data_nba_headers() -> dict:
    # CDN endpoints are far less picky; UA + Referer is enough.
    base = {
        "User-Agent": _ua(),
        "Referer": "https://www.nba.com/",
        "Origin": "https://www.nba.com",
    }
    return deepcopy(base)


def core_api_headers() -> dict:
    base = {
        "User-Agent": _ua(),
        "Referer": "https://www.nba.com/",
        "Origin": "https://www.nba.com",
        "Accept": "application/json",
    }
    return deepcopy(base)

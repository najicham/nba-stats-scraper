"""
Centralised helpers for NBA-site request headers.

There are three patterns:

1.  STATS_NBA_HEADERS   - classic stats.nba.com endpoints
2.  DATA_NBA_HEADERS    - cdn.nba.com / data.nba.com JSON (play-by-play, shotcharts)
3.  CORE_API_HEADERS    - core-api.nba.com (gamecardfeed, play-by-play meta)

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

# ---------------------------------------------------------------------------
#  Light‑weight headers for ALL stats.nba.com JSON endpoints
# ---------------------------------------------------------------------------
def stats_api_headers() -> dict:
    """
    Minimal but sufficient header block for stats.nba.com.
    Keeps request size small while passing Akamai checks.
    """
    return {
        "User-Agent":         _ua(),
        "Referer":            "https://stats.nba.com",
        "Origin":             "https://stats.nba.com",
        "Accept":             "application/json, text/plain, */*",
        "x-nba-stats-origin": "stats",
        "x-nba-stats-token":  "true",
    }

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


def cdn_nba_headers() -> dict:
    """
    Headers that satisfy Akamai for cdn.nba.com JSON feeds
    (liveData/scoreboard, static schedule, etc.).
    """
    base = stats_nba_headers()           # reuse UA, Accept, cache flags
    # Remove host‑specific and stats‑only headers
    base.pop("Host", None)
    base.pop("x-nba-stats-origin", None)
    base.pop("x-nba-stats-token", None)
    # Ensure compulsory Origin & Referer
    base["Origin"]  = "https://www.nba.com"
    base["Referer"] = "https://www.nba.com/"
    return deepcopy(base)

# -- helpers/nba_header_utils.py ---------------------------------
def data_nba_headers() -> dict:
    """Headers for cdn.nba.com / data.nba.com JSON feeds."""
    base = {
        "User-Agent": _ua(),
        "Accept": "application/json, text/plain, */*",   # optional
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.nba.com/",
        "Origin": "https://www.nba.com",
    }
    return deepcopy(base)

# backward‑compat alias if any code still imports cdn_nba_headers
cdn_nba_headers = data_nba_headers

def core_api_headers() -> dict:
    base = {
        "User-Agent": _ua(),
        "Referer": "https://www.nba.com/",
        "Origin": "https://www.nba.com",
        "Accept": "application/json",
    }
    return deepcopy(base)

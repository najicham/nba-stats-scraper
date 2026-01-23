"""
Centralised helpers for NBA-site request headers.

There are three patterns:

1.  STATS_NBA_HEADERS   - classic stats.nba.com endpoints
2.  DATA_NBA_HEADERS    - cdn.nba.com / data.nba.com JSON (play-by-play, shotcharts)
3.  CORE_API_HEADERS    - core-api.nba.com (gamecardfeed, play-by-play meta)

Each helper returns a *copy* so callers can safely mutate individual fields.
"""

from copy import deepcopy
import logging
import os
import random

logger = logging.getLogger(__name__)

USER_AGENTS = [
    # Updated to Chrome 140 (matches nba_api Sept 2025 update - PR #571)
    # Modern Chrome version fixes connection issues with stats.nba.com
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
]

# Chrome Client Hints header - must match Chrome version in USER_AGENTS
SEC_CH_UA = '"Chromium";v="140", "Google Chrome";v="140", "Not;A=Brand";v="24"'

def _ua():
    """Return a random desktop User‑Agent each call."""
    return random.choice(USER_AGENTS)

# ---------------------------------------------------------------------------
#  Light‑weight headers for ALL stats.nba.com JSON endpoints
# ---------------------------------------------------------------------------
def stats_api_headers() -> dict:
    """
    Minimal but sufficient header block for stats.nba.com.
    Updated Sept 2025 to match nba_api library - removes deprecated headers.
    """
    return {
        "User-Agent": _ua(),
        "Referer": "https://stats.nba.com/",
        "Origin": "https://stats.nba.com",
        "Accept": "application/json, text/plain, */*",
        "Sec-Ch-Ua": SEC_CH_UA,
        "Sec-Ch-Ua-Mobile": "?0",
        # NOTE: x-nba-stats-origin and x-nba-stats-token removed (deprecated Sept 2025)
    }

def stats_nba_headers() -> dict:
    """
    Modern header block for stats.nba.com.

    Updated to match nba_api library (Sept 2025, PR #571):
    - Chrome 140 User-Agent
    - Added Sec-Ch-Ua headers (Chrome Client Hints)
    - Removed deprecated x-nba-stats-origin and x-nba-stats-token
    """
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
        # Chrome Client Hints (required for modern stats.nba.com)
        "Sec-Ch-Ua": SEC_CH_UA,
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        # Fetch metadata headers
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": _ua(),
        # NOTE: x-nba-stats-origin and x-nba-stats-token removed (deprecated Sept 2025)
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
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.nba.com/",
        "Origin": "https://www.nba.com",
        "Sec-Ch-Ua": SEC_CH_UA,
        "Sec-Ch-Ua-Mobile": "?0",
    }
    return deepcopy(base)

# backward‑compat alias if any code still imports cdn_nba_headers
cdn_nba_headers = data_nba_headers

def core_api_headers() -> dict:
    """Headers for core-api.nba.com endpoints."""
    base = {
        "User-Agent": _ua(),
        "Referer": "https://www.nba.com/",
        "Origin": "https://www.nba.com",
        "Accept": "application/json",
        "Sec-Ch-Ua": SEC_CH_UA,
        "Sec-Ch-Ua-Mobile": "?0",
    }
    return deepcopy(base)

def bettingpros_headers() -> dict:
    """
    Headers for BettingPros API endpoints.
    Based on observed browser patterns for api.bettingpros.com requests.

    NOTE: Brotli package is now installed (2026-01-12), so br encoding could be
    added back. However, we keep only gzip/deflate for stability since:
    1. scraper_base.py now handles manual brotli decompression as fallback
    2. CDN may cache responses with different encodings
    """
    api_key = os.environ.get('BETTINGPROS_API_KEY', '')
    if not api_key:
        logger.warning(
            "BETTINGPROS_API_KEY environment variable not set - API calls will fail"
        )

    base = {
        "User-Agent": _ua(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",  # Keep simple - brotli fallback in scraper_base
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Origin": "https://www.bettingpros.com",
        "Pragma": "no-cache",
        "Referer": "https://www.bettingpros.com/nba/odds/player-props/points/",
        # Updated Jan 2026: Use modern Chrome version to avoid bot detection
        "Sec-Ch-Ua": SEC_CH_UA,  # Uses Chrome 140 from global constant
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',  # Windows less suspicious than Linux
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "X-Api-Key": api_key,
    }
    return deepcopy(base)

# File: scrapers/external/nba_tracking_stats.py
"""
NBA.com Player Tracking Stats Scraper                          v1.1 - 2026-06-29
---------------------------------------------------------------------------------
Scrapes player tracking stats from NBA.com via nba_api or direct HTTP.

Endpoints (v1.1 fix — v1.0 used leaguedashplayerstats?MeasureType=Usage which does
NOT return TOUCHES/DRIVES/CATCH_SHOOT_FGA; those come from leaguedashptstats):
  - leaguedashptstats?PtMeasureType=Possessions → TOUCHES, FRONT_CT_TOUCHES, TIME_OF_POSS
  - leaguedashptstats?PtMeasureType=Drives      → DRIVES, DRIVE_PTS, DRIVE_FGA
  - leaguedashptstats?PtMeasureType=CatchShoot  → CATCH_SHOOT_FGA, CATCH_SHOOT_FG_PCT
  - leaguedashptstats?PtMeasureType=PaintTouch  → PAINT_TOUCHES
  - leaguedashplayerstats?MeasureType=Usage     → USG_PCT, PACE (joined on PLAYER_ID)

Data: Touches, drives, catch-and-shoot, paint touches, minutes, usage per player.
Access: Public API, rate-limited (proxy recommended — Cloud IPs often blocked).
Timing: Updates after each game day (~5 AM ET).

Usage:
  python scrapers/external/nba_tracking_stats.py --date 2026-03-04 --debug
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

from shared.utils.notification_system import notify_error, notify_warning, notify_info

logger = logging.getLogger("scraper_base")

# Try importing nba_api — may not be installed in all environments
try:
    from nba_api.stats.endpoints import LeagueDashPlayerStats, LeagueDashPtStats
    NBA_API_AVAILABLE = True
except ImportError:
    try:
        from nba_api.stats.endpoints import LeagueDashPlayerStats
        LeagueDashPtStats = None
        NBA_API_AVAILABLE = True
    except ImportError:
        LeagueDashPtStats = None
        NBA_API_AVAILABLE = False
        logger.info("nba_api not available, will use direct HTTP fallback")

# NBA.com team abbreviation mapping (API returns full team abbreviations)
NBA_TEAM_ABBREVIATIONS = {
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN",
    "DET", "GSW", "HOU", "IND", "LAC", "LAL", "MEM", "MIA",
    "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX",
    "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}

# Headers required for direct stats.nba.com requests
NBA_STATS_HEADERS = {
    'Host': 'stats.nba.com',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:72.0) Gecko/20100101 Firefox/72.0',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.5',
    'Referer': 'https://www.nba.com/',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
    'Connection': 'keep-alive',
    'Origin': 'https://www.nba.com',
}

# API URLs
NBA_STATS_URL = "https://stats.nba.com/stats/leaguedashplayerstats"
NBA_PT_STATS_URL = "https://stats.nba.com/stats/leaguedashptstats"

# PtMeasureType values and the key columns each returns
PT_MEASURE_TYPES = [
    "Possessions",   # TOUCHES, FRONT_CT_TOUCHES, TIME_OF_POSS, AVG_DRIB_PER_TOUCH
    "Drives",        # DRIVES, DRIVE_PTS, DRIVE_FGA, DRIVE_FG_PCT
    "CatchShoot",    # CATCH_SHOOT_FGA, CATCH_SHOOT_FGM, CATCH_SHOOT_FG_PCT
    "PaintTouch",    # PAINT_TOUCHES, PAINT_TOUCH_FGA, PAINT_TOUCH_FG_PCT
]


def normalize_player_name(name: str) -> str:
    """Convert player name to player_lookup format (lowercase, hyphenated)."""
    if not name:
        return ""
    # Remove suffixes
    for suffix in [" Jr.", " Sr.", " Jr", " Sr", " III", " II", " IV"]:
        name = name.replace(suffix, "")
    # Lowercase, replace spaces with hyphens, remove non-alphanumeric except hyphens
    normalized = name.lower().strip()
    normalized = re.sub(r'[^a-z\s-]', '', normalized)
    normalized = re.sub(r'\s+', '-', normalized)
    return normalized


def _get_current_season() -> str:
    """Return the current NBA season string, e.g. '2025-26'."""
    now = datetime.now()
    # NBA season starts in October. If we're before October, season started last year.
    if now.month >= 10:
        start_year = now.year
    else:
        start_year = now.year - 1
    end_year_short = str(start_year + 1)[-2:]
    return f"{start_year}-{end_year_short}"


class NBATrackingStatsScraper(ScraperBase, ScraperFlaskMixin):
    """Scrape player tracking/usage stats from NBA.com."""

    # Flask Mixin Configuration
    scraper_name = "nba_tracking_stats"
    required_params = ["date"]
    optional_params = {}

    # ScraperBase Configuration
    required_opts: List[str] = ["date"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = None
    proxy_enabled: bool = True

    CRAWL_DELAY_SECONDS = 3.0  # Respectful rate limiting for stats.nba.com

    GCS_PATH_KEY = "nba_tracking_stats"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/nba_tracking_stats_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
    ]

    def set_url(self) -> None:
        """Set URL placeholder. Actual fetching is done in download_and_decode."""
        self.url = NBA_STATS_URL
        logger.info("NBA tracking stats URL: %s", self.url)

    def set_headers(self) -> None:
        """Set headers for stats.nba.com (used by direct HTTP fallback)."""
        self.headers = NBA_STATS_HEADERS.copy()

    def download_and_decode(self):
        """Fetch player tracking stats from multiple stats.nba.com endpoints.

        Overrides ScraperBase.download_and_decode(). Calls leaguedashptstats with
        multiple PtMeasureType values (Possessions, Drives, CatchShoot, PaintTouch)
        plus leaguedashplayerstats?MeasureType=Usage for USG_PCT/PACE. Results are
        stored as a dict keyed by measure type and joined in transform_data().

        Uses proxy infrastructure from ScraperBase to avoid stats.nba.com blocking.
        """
        season = _get_current_season()
        logger.info("Fetching NBA tracking stats for season %s", season)

        proxy_url = self._get_proxy_url()
        if proxy_url:
            logger.info("Using proxy for stats.nba.com: %s", proxy_url[:30] + "...")
        else:
            logger.warning("No proxy available — stats.nba.com may block cloud IPs")

        if NBA_API_AVAILABLE and LeagueDashPtStats is not None:
            self.decoded_data = self._fetch_all_via_nba_api(season, proxy_url)
        else:
            self.decoded_data = self._fetch_all_via_http(season, proxy_url)

    def _get_proxy_url(self) -> Optional[str]:
        """Get a healthy proxy URL from the proxy rotation infrastructure."""
        try:
            from scrapers.utils.proxy_utils import get_healthy_proxy_urls_for_target
            proxy_pool = get_healthy_proxy_urls_for_target(
                "stats.nba.com", shuffle=True
            )
            if proxy_pool:
                return proxy_pool[0]
        except Exception as e:
            logger.debug("Failed to get proxy from pool: %s", e)

        # Fallback: check if proxy_url was set via opts or env
        if hasattr(self, 'proxy_url') and self.proxy_url:
            return self.proxy_url

        proxy_env = os.environ.get('NBA_SCRAPER_PROXY')
        if proxy_env:
            return proxy_env

        return None

    def _fetch_all_via_nba_api(self, season: str, proxy_url: Optional[str] = None) -> Dict[str, Any]:
        """Fetch all tracking datasets via nba_api, falling back to HTTP on failure."""
        logger.info("Using nba_api library for tracking stats")
        results = {}

        # Fetch each PtMeasureType
        for pt_type in PT_MEASURE_TYPES:
            try:
                kwargs = {
                    'pt_measure_type': pt_type,
                    'season': season,
                    'per_mode_simple': 'PerGame',
                    'timeout': 60,
                }
                if proxy_url:
                    kwargs['proxy'] = proxy_url
                stats = LeagueDashPtStats(**kwargs)
                results[pt_type] = stats.get_dict()
                logger.info("nba_api PtMeasureType=%s OK", pt_type)
                time.sleep(1.0)
            except Exception as e:
                logger.warning("nba_api PtMeasureType=%s failed: %s — falling back", pt_type, e)
                results[pt_type] = self._http_single(season, pt_type, proxy_url, is_pt=True)

        # Fetch Usage for USG_PCT and PACE
        try:
            kwargs = {
                'measure_type_detailed_defense': 'Usage',
                'season': season,
                'per_mode_detailed': 'PerGame',
                'timeout': 60,
            }
            if proxy_url:
                kwargs['proxy'] = proxy_url
            stats = LeagueDashPlayerStats(**kwargs)
            results['Usage'] = stats.get_dict()
            logger.info("nba_api MeasureType=Usage OK")
        except Exception as e:
            logger.warning("nba_api Usage failed: %s — falling back to HTTP", e)
            results['Usage'] = self._http_single(season, 'Usage', proxy_url, is_pt=False)

        return results

    def _fetch_all_via_http(self, season: str, proxy_url: Optional[str] = None) -> Dict[str, Any]:
        """Fetch all tracking datasets via direct HTTP to stats.nba.com."""
        logger.info("Using direct HTTP for tracking stats")
        results = {}
        for pt_type in PT_MEASURE_TYPES:
            results[pt_type] = self._http_single(season, pt_type, proxy_url, is_pt=True)
            time.sleep(1.5)
        results['Usage'] = self._http_single(season, 'Usage', proxy_url, is_pt=False)
        return results

    def _http_single(
        self, season: str, measure: str, proxy_url: Optional[str], is_pt: bool
    ) -> Dict[str, Any]:
        """Make a single stats.nba.com request with retry/backoff."""
        import requests

        if is_pt:
            url = NBA_PT_STATS_URL
            params = {
                'PtMeasureType': measure,
                'PerMode': 'PerGame',
                'Season': season,
                'SeasonType': 'Regular Season',
                'LeagueID': '00',
                'PaceAdjust': 'N',
                'PlusMinus': 'N',
                'Rank': 'N',
            }
        else:
            url = NBA_STATS_URL
            params = {
                'MeasureType': measure,
                'PerMode': 'PerGame',
                'Season': season,
                'SeasonType': 'Regular Season',
                'LeagueID': '00',
                'PaceAdjust': 'N',
                'PlusMinus': 'N',
                'Rank': 'N',
            }

        session = requests.Session()
        session.headers.update(NBA_STATS_HEADERS)
        proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else {}

        for attempt in range(1, 4):
            try:
                response = session.get(url, params=params, proxies=proxies, timeout=120)
                response.raise_for_status()
                logger.info("HTTP %s attempt %d OK (%d bytes)", measure, attempt, len(response.content))
                return response.json()
            except Exception as e:
                logger.warning("HTTP %s attempt %d/%d failed: %s", measure, attempt, 3, e)
                if attempt == 3:
                    raise
                time.sleep(5 * attempt)

    def validate_download_data(self) -> None:
        """Validate we received valid NBA stats API responses for all measure types."""
        if not isinstance(self.decoded_data, dict):
            raise ValueError("Expected dict of resultSets from multi-endpoint fetch")

        for measure, data in self.decoded_data.items():
            result_sets = data.get("resultSets", [])
            if not result_sets:
                raise ValueError(f"No resultSets for measure={measure}")
            first_set = result_sets[0]
            if not first_set.get("headers"):
                raise ValueError(f"No headers for measure={measure}")
            rows = first_set.get("rowSet", [])
            logger.info("Validated %s: %d players", measure, len(rows))

    def transform_data(self) -> None:
        """Join tracking datasets from multiple endpoints, keyed by PLAYER_ID."""
        # Parse each result set into {player_id: {col: val}} dicts
        per_player: Dict[int, Dict[str, Any]] = {}

        def _parse_result(data: Dict[str, Any], measure: str) -> None:
            result_sets = data.get("resultSets", [])
            if not result_sets:
                return
            first_set = result_sets[0]
            headers = [h.upper() for h in first_set.get("headers", [])]
            rows = first_set.get("rowSet", [])
            for row in rows:
                row_dict = dict(zip(headers, row))
                pid = row_dict.get("PLAYER_ID")
                if pid is None:
                    continue
                pid = int(pid)
                if pid not in per_player:
                    per_player[pid] = {}
                per_player[pid].update(row_dict)

        for measure, data in self.decoded_data.items():
            _parse_result(data, measure)

        players = []
        for pid, d in per_player.items():
            record = self._extract_player_record_from_dict(d)
            if record:
                players.append(record)

        # Sort by touches descending
        players.sort(key=lambda p: p.get("touches", 0), reverse=True)

        self.data = {
            "source": "nba_tracking",
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "player_count": len(players),
            "players": players,
        }

        logger.info("Parsed tracking stats for %d players", len(players))

    def _extract_player_record_from_dict(self, d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Build a player record from the joined per-player column dict."""
        def _get(col: str, default=None):
            return d.get(col.upper(), default)

        player_name = _get("PLAYER_NAME") or _get("PLAYER_NAME_LAST_FIRST", "")
        if not player_name:
            return None

        minutes = _get("MIN", 0.0)
        if not minutes or _safe_float(minutes) <= 0:
            return None

        return {
            "player_name": player_name,
            "player_lookup": normalize_player_name(player_name),
            "team": _get("TEAM_ABBREVIATION", ""),
            "minutes": _safe_float(minutes),
            # From PtMeasureType=Possessions (leaguedashptstats)
            "touches": _safe_float(_get("TOUCHES", 0)),
            "front_ct_touches": _safe_float(_get("FRONT_CT_TOUCHES", 0)),
            "time_of_poss": _safe_float(_get("TIME_OF_POSS", 0)),
            "avg_drib_per_touch": _safe_float(_get("AVG_DRIB_PER_TOUCH", 0)),
            # From PtMeasureType=Drives
            "drives": _safe_float(_get("DRIVES", 0)),
            "drive_pts": _safe_float(_get("DRIVE_PTS", 0)),
            "drive_fga": _safe_float(_get("DRIVE_FGA", 0)),
            "drive_fg_pct": _safe_float(_get("DRIVE_FG_PCT", 0)),
            # From PtMeasureType=CatchShoot
            "catch_shoot_fga": _safe_float(_get("CATCH_SHOOT_FGA", 0)),
            "catch_shoot_fg_pct": _safe_float(_get("CATCH_SHOOT_FG_PCT", 0)),
            # From PtMeasureType=PaintTouch
            "paint_touches": _safe_float(_get("PAINT_TOUCHES", 0)),
            "paint_touch_fga": _safe_float(_get("PAINT_TOUCH_FGA", 0)),
            "paint_touch_fg_pct": _safe_float(_get("PAINT_TOUCH_FG_PCT", 0)),
            # From MeasureType=Usage (leaguedashplayerstats)
            "usage_pct": _safe_float(_get("USG_PCT", 0)),
            "pace": _safe_float(_get("PACE", 0)),
            "poss": _safe_float(_get("POSS", 0)),
        }

    def get_scraper_stats(self) -> dict:
        return {
            "date": self.opts.get("date"),
            "player_count": self.data.get("player_count", 0),
            "nba_api_used": NBA_API_AVAILABLE,
        }


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to float."""
    if value is None:
        return default
    try:
        return round(float(value), 3)
    except (ValueError, TypeError):
        return default


create_app = convert_existing_flask_scraper(NBATrackingStatsScraper)

if __name__ == "__main__":
    main = NBATrackingStatsScraper.create_cli_and_flask_main()
    main()

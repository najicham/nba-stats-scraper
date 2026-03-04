# File: scrapers/external/nba_tracking_stats.py
"""
NBA.com Player Tracking Stats Scraper                          v1.0 - 2026-03-04
---------------------------------------------------------------------------------
Scrapes player usage/tracking stats from NBA.com via nba_api or direct HTTP.

Endpoint: leaguedashplayerstats with MeasureType=Usage
Data: Touches, drives, catch-and-shoot, pull-up, paint touches, minutes per player.
Access: Public API, rate-limited (proxy recommended).
Timing: Updates after each game day (~5 AM ET).

Provides touch-based usage data that complements box-score averages for
prediction features (e.g., usage_spike_score, expected_scoring_possessions).

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
    from nba_api.stats.endpoints import LeagueDashPlayerStats
    NBA_API_AVAILABLE = True
except ImportError:
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

# Direct API URL for fallback
NBA_STATS_URL = "https://stats.nba.com/stats/leaguedashplayerstats"


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
        """Fetch player tracking stats via nba_api or direct HTTP fallback.

        Overrides ScraperBase.download_and_decode() because we either use the
        nba_api library (preferred) or make a custom request with specific
        parameters, rather than downloading a single URL.
        """
        season = _get_current_season()
        logger.info("Fetching NBA tracking stats for season %s", season)

        time.sleep(self.CRAWL_DELAY_SECONDS)

        if NBA_API_AVAILABLE:
            self.decoded_data = self._fetch_via_nba_api(season)
        else:
            self.decoded_data = self._fetch_via_http(season)

    def _fetch_via_nba_api(self, season: str) -> Dict[str, Any]:
        """Fetch data using the nba_api library."""
        logger.info("Using nba_api library for tracking stats")
        try:
            stats = LeagueDashPlayerStats(
                measure_type_detailed_defense='Usage',
                season=season,
                per_mode_detailed='PerGame',
                timeout=30,
            )
            result = stats.get_dict()
            logger.info("nba_api returned data successfully")
            return result
        except Exception as e:
            logger.warning("nba_api call failed: %s — falling back to HTTP", e)
            return self._fetch_via_http(season)

    def _fetch_via_http(self, season: str) -> Dict[str, Any]:
        """Fetch data via direct HTTP request to stats.nba.com."""
        import requests

        logger.info("Using direct HTTP fallback for tracking stats")

        params = {
            'MeasureType': 'Usage',
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

        # Use proxy if configured via ScraperBase
        proxies = {}
        if self.proxy_enabled and hasattr(self, 'proxy_url') and self.proxy_url:
            proxies = {
                'http': self.proxy_url,
                'https': self.proxy_url,
            }

        # Retry with backoff — stats.nba.com blocks cloud IPs intermittently
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = session.get(
                    NBA_STATS_URL,
                    params=params,
                    proxies=proxies,
                    timeout=120,
                )
                response.raise_for_status()
                data = response.json()
                logger.info("Direct HTTP request succeeded on attempt %d (%d bytes)", attempt, len(response.content))
                return data
            except Exception as e:
                logger.warning("HTTP attempt %d/%d failed: %s", attempt, max_retries, e)
                if attempt == max_retries:
                    logger.error("All %d HTTP attempts failed", max_retries)
                    raise
                time.sleep(5 * attempt)  # 5s, 10s backoff

    def validate_download_data(self) -> None:
        """Validate we received valid NBA stats API response."""
        if not isinstance(self.decoded_data, dict):
            raise ValueError("Expected dict response from NBA stats API")

        result_sets = self.decoded_data.get("resultSets", [])
        if not result_sets:
            raise ValueError("No resultSets in NBA stats API response")

        first_set = result_sets[0]
        headers = first_set.get("headers", [])
        rows = first_set.get("rowSet", [])

        if not headers:
            raise ValueError("No headers in resultSets[0]")
        if not rows:
            raise ValueError("No player rows in resultSets[0]")

        logger.info(
            "Validated tracking stats: %d columns, %d players",
            len(headers),
            len(rows),
        )

    def transform_data(self) -> None:
        """Transform NBA stats API response into structured player data."""
        result_sets = self.decoded_data.get("resultSets", [])
        first_set = result_sets[0]
        headers = first_set["headers"]
        rows = first_set["rowSet"]

        # Build column index map for flexible column access
        col_idx = {h.upper(): i for i, h in enumerate(headers)}

        players = []
        for row in rows:
            player_record = self._extract_player_record(row, col_idx)
            if player_record:
                players.append(player_record)

        # Sort by touches descending (most involved players first)
        players.sort(key=lambda p: p.get("touches", 0), reverse=True)

        self.data = {
            "source": "nba_tracking",
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "player_count": len(players),
            "players": players,
        }

        logger.info("Parsed tracking stats for %d players", len(players))

    def _extract_player_record(
        self, row: list, col_idx: Dict[str, int]
    ) -> Optional[Dict[str, Any]]:
        """Extract a single player record from a result row."""

        def _get(col_name: str, default=None):
            """Safely get a column value by name."""
            idx = col_idx.get(col_name.upper())
            if idx is not None and idx < len(row):
                return row[idx]
            return default

        player_name = _get("PLAYER_NAME", "")
        if not player_name:
            return None

        team_abbr = _get("TEAM_ABBREVIATION", "")
        minutes = _get("MIN", 0.0)

        # Skip players with no minutes (inactive / not yet played)
        if not minutes or minutes <= 0:
            return None

        record = {
            "player_name": player_name,
            "player_lookup": normalize_player_name(player_name),
            "team": team_abbr,
            "minutes": _safe_float(minutes),
            # Usage / tracking columns from MeasureType=Usage
            "touches": _safe_float(_get("TOUCHES", 0)),
            "drives": _safe_float(_get("DRIVES", 0)),
            "catch_shoot_fga": _safe_float(_get("CATCH_SHOOT_FGA", 0)),
            "catch_shoot_fg_pct": _safe_float(_get("CATCH_SHOOT_FG_PCT", 0)),
            "pull_up_fga": _safe_float(_get("PULL_UP_FGA", 0)),
            "pull_up_fg_pct": _safe_float(_get("PULL_UP_FG_PCT", 0)),
            "paint_touches": _safe_float(_get("PAINT_TOUCHES", 0)),
            # Additional usage stats available from this endpoint
            "usage_pct": _safe_float(_get("USG_PCT", 0)),
            "pace": _safe_float(_get("PACE", 0)),
            "poss": _safe_float(_get("POSS", 0)),
        }

        return record

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

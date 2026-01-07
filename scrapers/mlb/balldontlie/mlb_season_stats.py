"""
File: scrapers/mlb/balldontlie/mlb_season_stats.py

MLB Ball Don't Lie - Season Statistics                          v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Season aggregate statistics for MLB players.

API Endpoint: https://api.balldontlie.io/mlb/v1/season_stats

Key Pitching Fields:
- strikeouts_pitched: Total Ks for season
- ERA: Earned Run Average
- WHIP: Walks + Hits per IP
- innings_pitched: Total IP
- wins, losses, saves

Usage:
  python scrapers/mlb/balldontlie/mlb_season_stats.py --season 2025 --debug
  python scrapers/mlb/balldontlie/mlb_season_stats.py --season 2025 --team_id 1
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from ...scraper_base import DownloadType, ExportMode, ScraperBase
    from ...scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from ...utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

logger = logging.getLogger(__name__)


class MlbSeasonStatsScraper(ScraperBase, ScraperFlaskMixin):
    """Scraper for MLB season statistics."""

    scraper_name = "mlb_season_stats"
    required_params = ["season"]
    optional_params = {
        "player_ids": None,
        "team_id": None,
        "postseason": None,
        "sort_by": None,
        "sort_order": None,
        "api_key": None,
    }

    required_opts: List[str] = ["season"]
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    GCS_PATH_KEY = "mlb_season_stats"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_season_stats_%(season)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    _API_ROOT = "https://api.balldontlie.io/mlb/v1/season_stats"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        params = [f"season={self.opts['season']}", "per_page=100"]

        if self.opts.get("player_ids"):
            for pid in str(self.opts["player_ids"]).split(","):
                params.append(f"player_ids[]={pid.strip()}")

        if self.opts.get("team_id"):
            params.append(f"team_id={self.opts['team_id']}")

        if self.opts.get("postseason"):
            params.append(f"postseason={self.opts['postseason']}")

        if self.opts.get("sort_by"):
            params.append(f"sort_by={self.opts['sort_by']}")

        if self.opts.get("sort_order"):
            params.append(f"sort_order={self.opts['sort_order']}")

        self.url = f"{self.base_url}?{'&'.join(params)}"
        logger.debug("MLB Season Stats URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_MLB_API_KEY") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "mlb-season-stats-scraper/1.0",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = api_key

    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("MLB season stats response malformed")

    def transform_data(self) -> None:
        stats: List[Dict[str, Any]] = list(self.decoded_data["data"])
        cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")
        pages_fetched = 1

        while cursor:
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params={"cursor": cursor, "per_page": 100},
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            page_json = resp.json()
            stats.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")
            pages_fetched += 1

        # Filter to pitcher stats
        pitcher_stats = [s for s in stats if self._has_pitching_stats(s)]

        self.data = {
            "season": self.opts["season"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "totalPlayers": len(stats),
            "pitcherCount": len(pitcher_stats),
            "seasonStats": stats,
            "pitcherSeasonStats": pitcher_stats,
        }

        logger.info("Fetched %d season stats (%d pitchers) for %s",
                   len(stats), len(pitcher_stats), self.opts["season"])

    def _has_pitching_stats(self, stat: Dict[str, Any]) -> bool:
        """Check if stat record has pitching data."""
        pitching_fields = ['strikeouts_pitched', 'era', 'whip', 'innings_pitched', 'wins', 'losses', 'saves']
        for field in pitching_fields:
            if stat.get(field) is not None and stat.get(field) != 0:
                return True
        return False

    def get_scraper_stats(self) -> dict:
        return {
            "season": self.opts["season"],
            "totalPlayers": self.data.get("totalPlayers", 0),
            "pitcherCount": self.data.get("pitcherCount", 0),
        }


create_app = convert_existing_flask_scraper(MlbSeasonStatsScraper)

if __name__ == "__main__":
    main = MlbSeasonStatsScraper.create_cli_and_flask_main()
    main()

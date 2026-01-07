"""
File: scrapers/mlb/balldontlie/mlb_active_players.py

MLB Ball Don't Lie - Active Players                             v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Active MLB players from the Ball Don't Lie API.

API Endpoint: https://api.balldontlie.io/mlb/v1/players/active

Useful for:
- Getting list of active pitchers
- Player IDs for other API calls
- Position filtering

Usage:
  python scrapers/mlb/balldontlie/mlb_active_players.py --debug
  python scrapers/mlb/balldontlie/mlb_active_players.py --team_ids 1,2,3
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


class MlbActivePlayersScraper(ScraperBase, ScraperFlaskMixin):
    """Scraper for active MLB players."""

    scraper_name = "mlb_active_players"
    required_params = []
    optional_params = {
        "team_ids": None,
        "player_ids": None,
        "search": None,
        "api_key": None,
    }

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    GCS_PATH_KEY = "mlb_active_players"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_active_players_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts["date"] = datetime.now(timezone.utc).date().isoformat()

    _API_ROOT = "https://api.balldontlie.io/mlb/v1/players/active"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        params = ["per_page=100"]

        if self.opts.get("team_ids"):
            for tid in str(self.opts["team_ids"]).split(","):
                params.append(f"team_ids[]={tid.strip()}")

        if self.opts.get("player_ids"):
            for pid in str(self.opts["player_ids"]).split(","):
                params.append(f"player_ids[]={pid.strip()}")

        if self.opts.get("search"):
            params.append(f"search={self.opts['search']}")

        self.url = f"{self.base_url}?{'&'.join(params)}"
        logger.debug("MLB Active Players URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_MLB_API_KEY") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "mlb-active-players-scraper/1.0",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = api_key

    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("MLB active players response malformed")

    def transform_data(self) -> None:
        players: List[Dict[str, Any]] = list(self.decoded_data["data"])
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
            players.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")
            pages_fetched += 1

        # Separate pitchers for easy access
        pitchers = [p for p in players if self._is_pitcher(p)]

        players.sort(key=lambda p: (p.get("team", {}).get("id", 0), p.get("last_name", "")))

        self.data = {
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "playerCount": len(players),
            "pitcherCount": len(pitchers),
            "players": players,
            "pitchers": pitchers,
        }

        logger.info("Fetched %d active players (%d pitchers) across %d pages",
                   len(players), len(pitchers), pages_fetched)

    def _is_pitcher(self, player: Dict[str, Any]) -> bool:
        """Check if player is a pitcher based on position."""
        position = player.get("position", "").lower()
        return "pitcher" in position or position in ["sp", "rp", "cp", "p"]

    def get_scraper_stats(self) -> dict:
        return {
            "playerCount": self.data.get("playerCount", 0),
            "pitcherCount": self.data.get("pitcherCount", 0),
        }


create_app = convert_existing_flask_scraper(MlbActivePlayersScraper)

if __name__ == "__main__":
    main = MlbActivePlayersScraper.create_cli_and_flask_main()
    main()

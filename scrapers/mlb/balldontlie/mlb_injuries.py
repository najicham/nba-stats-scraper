"""
File: scrapers/mlb/balldontlie/mlb_injuries.py

MLB Ball Don't Lie - Player Injuries                            v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Current injury reports for MLB players.

API Endpoint: https://api.balldontlie.io/mlb/v1/player_injuries

Key Fields:
- player: Player info
- injury: Injury description
- status: IL status (10-day IL, 15-day IL, 60-day IL)
- return_date: Expected return

Important for strikeout predictions:
- Identify injured pitchers to exclude from predictions
- Track pitcher availability

Usage:
  python scrapers/mlb/balldontlie/mlb_injuries.py --debug
  python scrapers/mlb/balldontlie/mlb_injuries.py --team_ids 1,2,3
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


class MlbInjuriesScraper(ScraperBase, ScraperFlaskMixin):
    """Scraper for MLB player injuries."""

    scraper_name = "mlb_injuries"
    required_params = []
    optional_params = {
        "team_ids": None,
        "player_ids": None,
        "api_key": None,
    }

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    GCS_PATH_KEY = "mlb_injuries"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_injuries_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts["date"] = datetime.now(timezone.utc).date().isoformat()

    _API_ROOT = "https://api.balldontlie.io/mlb/v1/player_injuries"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        params = ["per_page=100"]

        if self.opts.get("team_ids"):
            for tid in str(self.opts["team_ids"]).split(","):
                params.append(f"team_ids[]={tid.strip()}")

        if self.opts.get("player_ids"):
            for pid in str(self.opts["player_ids"]).split(","):
                params.append(f"player_ids[]={pid.strip()}")

        self.url = f"{self.base_url}?{'&'.join(params)}"
        logger.debug("MLB Injuries URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_MLB_API_KEY") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "mlb-injuries-scraper/1.0",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = api_key

    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("MLB injuries response malformed")

    def transform_data(self) -> None:
        injuries: List[Dict[str, Any]] = list(self.decoded_data["data"])
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
            injuries.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")
            pages_fetched += 1

        # Separate pitcher injuries for easy filtering
        pitcher_injuries = [i for i in injuries if self._is_pitcher_injury(i)]

        self.data = {
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "injuryCount": len(injuries),
            "pitcherInjuryCount": len(pitcher_injuries),
            "injuries": injuries,
            "pitcherInjuries": pitcher_injuries,
        }

        logger.info("Fetched %d injuries (%d pitchers) across %d pages",
                   len(injuries), len(pitcher_injuries), pages_fetched)

    def _is_pitcher_injury(self, injury: Dict[str, Any]) -> bool:
        """Check if injury is for a pitcher."""
        player = injury.get("player", {})
        position = player.get("position", "").lower()
        return "pitcher" in position or position in ["sp", "rp", "cp", "p"]

    def get_scraper_stats(self) -> dict:
        return {
            "injuryCount": self.data.get("injuryCount", 0),
            "pitcherInjuryCount": self.data.get("pitcherInjuryCount", 0),
        }


create_app = convert_existing_flask_scraper(MlbInjuriesScraper)

if __name__ == "__main__":
    main = MlbInjuriesScraper.create_cli_and_flask_main()
    main()

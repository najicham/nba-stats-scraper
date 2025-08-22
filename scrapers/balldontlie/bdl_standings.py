"""
BALLDONTLIE - Standings endpoint                              v1.1 - 2025-06-24
-------------------------------------------------------------------------------
Conference / division standings

    https://api.balldontlie.io/v1/standings

Params
------
--season  2024 = 2024-25 season. If omitted, derive from today's date:
            - month >= Sep -> season = current year
            - otherwise   -> current year - 1

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_standings \
      --season 2024 \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_standings.py --season 2024 --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_standings.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_standings
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_standings.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

logger = logging.getLogger(__name__)


def _current_nba_season() -> int:
    today = datetime.now(timezone.utc)
    return today.year if today.month >= 9 else today.year - 1


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class BdlStandingsScraper(ScraperBase, ScraperFlaskMixin):
    """Daily or on-demand scraper for /standings."""

    # Flask Mixin Configuration
    scraper_name = "bdl_standings"
    required_params = ["season"]  # No required parameters
    optional_params = {
        "api_key": None,    # Falls back to env var
    }

    # Original scraper config
    required_opts: List[str] = ["season"]
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "bdl_standings"
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # Normal artifact
        {
            "type": "file",
            "filename": "/tmp/bdl_standings_%(season)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
        # Capture RAW
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        # Capture EXP
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DECODED,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts                                                    #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        season_year = int(self.opts.get("season") or _current_nba_season())
        self.opts["season"] = season_year
        # Simple formatting - no complex derivation needed
        self.opts["season_formatted"] = f"{season_year}-{str(season_year + 1)[-2:]}"
        self.opts["date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/standings"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}?season={self.opts['season']}&per_page=100"
        logger.debug("Standings URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-standings/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Unexpected standings JSON structure")

    # ------------------------------------------------------------------ #
    # Transform (cursor-aware)                                           #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        rows: List[Dict[str, Any]] = list(self.decoded_data["data"])
        cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")

        while cursor:
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params={"cursor": cursor, "per_page": 100},
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            page_json: Dict[str, Any] = resp.json()
            rows.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")

        rows.sort(key=lambda r: (r.get("conference"), r.get("conference_rank")))

        self.data = {
            "season": self.opts["season"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "teamCount": len(rows),
            "standings": rows,
        }
        logger.info("Fetched standings for %d teams (season %s)",
                    len(rows), self.opts["season"])

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "teamCount": self.data.get("teamCount", 0),
            "season": self.opts["season"],
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlStandingsScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlStandingsScraper.create_cli_and_flask_main()
    main()
    
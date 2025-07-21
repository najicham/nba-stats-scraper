"""
BALLDONTLIE - Player-Detail endpoint                         v1.1 - 2025-06-24
-------------------------------------------------------------------------------
Fetch the JSON object for a single NBA player:

    https://api.balldontlie.io/v1/players/{playerId}

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_player_detail \
      --playerId 237 \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_player_detail.py --playerId 237 --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_player_detail.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_player_detail
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_player_detail.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class BdlPlayerDetailScraper(ScraperBase, ScraperFlaskMixin):
    """Simple GET /players/{id} scraper."""

    # Flask Mixin Configuration
    scraper_name = "bdl_player_detail"
    required_params = ["playerId"]  # playerId is required
    optional_params = {
        "apiKey": None,  # Falls back to env var
    }

    # Original scraper config
    required_opts: List[str] = ["playerId"]
    download_type = DownloadType.JSON
    decode_download_data = True

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": "balldontlie/player-detail/%(playerId)s_%(run_id)s.raw.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        # Normal artifact
        {
            "type": "file",
            "filename": "/tmp/bdl_player_%(playerId)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
        # Capture RAW + EXP
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DECODED,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/players"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}/{self.opts['playerId']}"
        logger.debug("Player-detail URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-player-detail/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """
        BDL v1.4 wraps responses in {"data": {...}}.
        Accept both wrapped and legacy bare objects.
        """
        if "id" in self.decoded_data:
            player = self.decoded_data                       # legacy format
        elif "data" in self.decoded_data and "id" in self.decoded_data["data"]:
            player = self.decoded_data["data"]               # new format
        else:
            raise ValueError(f"PlayerId {self.opts['playerId']} not found in BallDontLie")

        if player["id"] != int(self.opts["playerId"]):
            raise ValueError("Returned playerId does not match requested playerId")

        # Unwrap so transform/exporters work consistently
        self.decoded_data = player

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        self.data = {
            "playerId": self.opts["playerId"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "player": self.decoded_data,
        }
        logger.info("Fetched player detail for playerId=%s", self.opts["playerId"])

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"playerId": self.opts["playerId"]}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlPlayerDetailScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlPlayerDetailScraper.create_cli_and_flask_main()
    main()
    
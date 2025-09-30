"""
File: scrapers/balldontlie/bdl_game_detail.py

BALLDONTLIE - Game-Detail endpoint                         v1.1 - 2025-06-24
-------------------------------------------------------------------------------
Retrieve the JSON object for one NBA game:

    https://api.balldontlie.io/v1/games/{gameId}

Typical uses
------------
- Populate a game-info cache just before tip-off.
- Re-query historical games to fix missing data.

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_game_detail \
      --gameId 18444564 \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_game_detail.py --gameId 18444564 --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_game_detail.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_game_detail
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_game_detail.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

# Notification system imports
try:
    from shared.utils.notification_system import (
        notify_error,
        notify_warning,
        notify_info
    )
except ImportError:
    # Graceful fallback if notification system not available
    def notify_error(*args, **kwargs): pass
    def notify_warning(*args, **kwargs): pass
    def notify_info(*args, **kwargs): pass

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class BdlGameDetailScraper(ScraperBase, ScraperFlaskMixin):
    """Lightweight scraper for /games/{id}."""

    # Flask Mixin Configuration
    scraper_name = "bdl_game_detail"
    required_params = ["gameId"]  # gameId is required
    optional_params = {
        "api_key": None,  # Falls back to env var
    }

    # Original scraper config
    required_opts: List[str] = ["gameId"]
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "bdl_game_detail"
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
            "filename": "/tmp/bdl_game_%(gameId)s.json",
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
    _API_ROOT = "https://api.balldontlie.io/v1/games"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}/{self.opts['gameId']}"
        logger.debug("Game-detail URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-game-detail/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """
        BDL v1.4 wraps single-resource responses in {"data": {...}}.
        Older versions returned the object bare.  Accept both.
        """
        try:
            if "id" in self.decoded_data:            # old format
                game = self.decoded_data
            elif "data" in self.decoded_data and "id" in self.decoded_data["data"]:
                game = self.decoded_data["data"]     # new wrapped format
            else:
                raise ValueError(f"GameId {self.opts['gameId']} not found in BallDontLie")

            if game["id"] != int(self.opts["gameId"]):
                raise ValueError("Returned gameId does not match requested gameId")

            # Replace decoded_data with the unwrapped object so downstream
            # transform / exporters don't care which format we got.
            self.decoded_data = game

        except Exception as e:
            # Send error notification for validation failure
            try:
                notify_error(
                    title="BDL Game Detail - Validation Failed",
                    message=f"Data validation failed for gameId {self.opts.get('gameId', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_game_detail',
                        'game_id': self.opts.get('gameId'),
                        'error_type': type(e).__name__,
                        'url': self.url,
                        'has_data': self.decoded_data is not None,
                        'note': 'Game may not exist or API format changed'
                    },
                    processor_name="Ball Don't Lie Game Detail"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send validation error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        try:
            self.data = {
                "gameId": self.opts["gameId"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "game": self.decoded_data,
            }
            logger.info("Fetched game detail for gameId=%s", self.opts["gameId"])

            # Success notification
            try:
                notify_info(
                    title="BDL Game Detail - Success",
                    message=f"Successfully fetched game detail for gameId {self.opts.get('gameId', 'unknown')}",
                    details={
                        'scraper': 'bdl_game_detail',
                        'game_id': self.opts.get('gameId'),
                        'home_team': self.decoded_data.get('home_team', {}).get('full_name', 'unknown'),
                        'visitor_team': self.decoded_data.get('visitor_team', {}).get('full_name', 'unknown'),
                        'status': self.decoded_data.get('status', 'unknown')
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send success notification: {notify_ex}")

        except Exception as e:
            # General transformation error
            try:
                notify_error(
                    title="BDL Game Detail - Transform Failed",
                    message=f"Data transformation failed for gameId {self.opts.get('gameId', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_game_detail',
                        'game_id': self.opts.get('gameId'),
                        'error_type': type(e).__name__,
                        'has_decoded_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Game Detail"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send transform error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"gameId": self.opts["gameId"]}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlGameDetailScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlGameDetailScraper.create_cli_and_flask_main()
    main()
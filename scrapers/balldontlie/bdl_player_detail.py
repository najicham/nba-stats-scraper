"""
File: scrapers/balldontlie/bdl_player_detail.py

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
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_player_detail.py
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
    def notify_warning(*args, **kwargs): pass  #
    def notify_info(*args, **kwargs): pass  #

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
        "api_key": None,  # Falls back to env var
    }

    # Original scraper config
    required_opts: List[str] = ["playerId"]
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "bdl_player_detail"
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
        api_key = self.opts.get("api_key") or os.getenv("BDL_API_KEY")
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
        try:
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

        except Exception as e:
            # Send error notification for validation failure
            try:
                notify_error(
                    title="BDL Player Detail - Validation Failed",
                    message=f"Data validation failed for playerId {self.opts.get('playerId', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_player_detail',
                        'player_id': self.opts.get('playerId'),
                        'error_type': type(e).__name__,
                        'url': self.url,
                        'has_data': self.decoded_data is not None,
                        'note': 'Player may not exist or API format changed'
                    },
                    processor_name="Ball Don't Lie Player Detail"
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
                "playerId": self.opts["playerId"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "player": self.decoded_data,
            }
            logger.info("Fetched player detail for playerId=%s", self.opts["playerId"])

            # Success notification
            try:
                notify_info(
                    title="BDL Player Detail - Success",
                    message=f"Successfully fetched player detail for playerId {self.opts.get('playerId', 'unknown')}",
                    details={
                        'scraper': 'bdl_player_detail',
                        'player_id': self.opts.get('playerId'),
                        'player_name': f"{self.decoded_data.get('first_name', '')} {self.decoded_data.get('last_name', '')}".strip(),
                        'team': self.decoded_data.get('team', {}).get('full_name', 'unknown')
                    },
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send success notification: {notify_ex}")

        except Exception as e:
            # General transformation error
            try:
                notify_error(
                    title="BDL Player Detail - Transform Failed",
                    message=f"Data transformation failed for playerId {self.opts.get('playerId', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_player_detail',
                        'player_id': self.opts.get('playerId'),
                        'error_type': type(e).__name__,
                        'has_decoded_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Player Detail"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send transform error notification: {notify_ex}")
            raise

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
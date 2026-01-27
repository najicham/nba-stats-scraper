"""
File: scrapers/balldontlie/bdl_team_detail.py

BALLDONTLIE - Team Detail endpoint                         v1.2  2025-06-24
---------------------------------------------------------------------------
Fetch a single NBA franchise record:

    https://api.balldontlie.io/v1/teams/{teamId}

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_team_detail \
      --teamId 14 \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_team_detail.py --teamId 14 --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_team_detail.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_team_detail
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_team_detail.py
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
    def notify_warning(*args, **kwargs,
    processor_name=self.__class__.__name__
    ): pass
    def notify_info(*args, **kwargs,
    processor_name=self.__class__.__name__
    ): pass

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class BdlTeamDetailScraper(ScraperBase, ScraperFlaskMixin):
    """GET /teams/{id}"""

    # Flask Mixin Configuration
    scraper_name = "bdl_team_detail"
    required_params = ["teamId"]  # teamId is required
    optional_params = {
        "api_key": None,  # Falls back to env var
    }

    # Original scraper config
    required_opts: List[str] = ["teamId"]
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "bdl_team_detail"
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/bdl_team_%(teamId)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "export_mode": ExportMode.DECODED,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL and headers                                                    #
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        self.base_url = "https://api.balldontlie.io/v1/teams"
        self.url = f"{self.base_url}/{self.opts['teamId']}"
        logger.debug("Team detail URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-team-detail/1.2 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        try:
            if not isinstance(self.decoded_data, dict):
                raise ValueError("Team detail response is not a JSON object")

            # BallDontLie wraps single objects in {"data": {...}}
            payload = self.decoded_data.get("data", self.decoded_data)
            if payload.get("id") != int(self.opts["teamId"]):
                raise ValueError(
                    f"Returned teamId {payload.get('id')} does not match requested {self.opts['teamId']}"
                )

            # Cache for transform
            self._team_obj = payload

        except Exception as e:
            # Send error notification for validation failure
            try:
                notify_error(
                    title="BDL Team Detail - Validation Failed",
                    message=f"Data validation failed for teamId {self.opts.get('teamId', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_team_detail',
                        'team_id': self.opts.get('teamId'),
                        'error_type': type(e).__name__,
                        'url': self.url,
                        'has_data': self.decoded_data is not None,
                        'note': 'Team may not exist or API format changed'
                    },
                    processor_name="Ball Don't Lie Team Detail"
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
                "teamId": self.opts["teamId"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "team": self._team_obj,
            }
            logger.info("Fetched team detail for teamId=%s", self.opts["teamId"])

            # Success notification
            try:
                notify_info(
                    title="BDL Team Detail - Success",
                    message=f"Successfully fetched team detail for teamId {self.opts.get('teamId', 'unknown')}",
                    details={
                        'scraper': 'bdl_team_detail',
                        'team_id': self.opts.get('teamId'),
                        'team_name': self._team_obj.get('full_name', 'unknown'),
                        'abbreviation': self._team_obj.get('abbreviation', 'unknown'),
                        'conference': self._team_obj.get('conference', 'unknown')
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send success notification: {notify_ex}")

        except Exception as e:
            # General transformation error
            try:
                notify_error(
                    title="BDL Team Detail - Transform Failed",
                    message=f"Data transformation failed for teamId {self.opts.get('teamId', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_team_detail',
                        'team_id': self.opts.get('teamId'),
                        'error_type': type(e).__name__,
                        'has_team_obj': hasattr(self, '_team_obj')
                    },
                    processor_name="Ball Don't Lie Team Detail"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send transform error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"teamId": self.opts["teamId"]}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlTeamDetailScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlTeamDetailScraper.create_cli_and_flask_main()
    main()
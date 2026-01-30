"""
File: scrapers/balldontlie/bdl_injuries.py

BALLDONTLIE - Player Injuries endpoint                       v1.1 - 2025-06-24
-------------------------------------------------------------------------------
Current injuries:

    https://api.balldontlie.io/v1/player_injuries

Optional query params:
  --teamId     restrict to one team
  --playerId   restrict to one player

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_injuries \
      --teamId 3 \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_injuries.py --teamId 3 --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_injuries.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_injuries
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_injuries.py
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
class BdlInjuriesScraper(ScraperBase, ScraperFlaskMixin):
    """Hourly or ad-hoc scraper for /player_injuries."""

    # Flask Mixin Configuration
    scraper_name = "bdl_injuries"
    required_params = []  # No required parameters
    optional_params = {
        "teamId": None,
        "playerId": None,
        "api_key": None,  # Falls back to env var
    }

    # Original scraper config
    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "bdl_injuries"
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
            "filename": "/tmp/bdl_injuries_%(ident)s.json",
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
    # Additional opts - ident string                                     #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        if self.opts.get("playerId"):
            self.opts["ident"] = f"player_{self.opts['playerId']}"
        elif self.opts.get("teamId"):
            self.opts["ident"] = f"team_{self.opts['teamId']}"
        else:
            self.opts["ident"] = "league"

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/player_injuries"

    def set_url(self) -> None:
        params = {"per_page": 100}
        if self.opts.get("teamId"):
            params["team_ids[]"] = self.opts["teamId"]
        if self.opts.get("playerId"):
            params["player_ids[]"] = self.opts["playerId"]

        query = "&".join(f"{k}={v}" for k, v in params.items())
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}?{query}"
        logger.debug("Injuries URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-injuries/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        try:
            if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
                raise ValueError("Injuries response malformed: missing 'data' key")
        except Exception as e:
            # Send error notification for validation failure
            try:
                notify_error(
                    title="BDL Injuries - Validation Failed",
                    message=f"Data validation failed for {self.opts.get('ident', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_injuries',
                        'ident': self.opts.get('ident'),
                        'error_type': type(e).__name__,
                        'url': self.url,
                        'has_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Injuries"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send validation error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        try:
            injuries: List[Dict[str, Any]] = list(self.decoded_data["data"])
            cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")
            pages_fetched = 1

            # Paginate through all results
            while cursor:
                try:
                    resp = self.http_downloader.get(
                        self.base_url,
                        headers=self.headers,
                        params={"cursor": cursor, "per_page": 100},
                        timeout=self.timeout_http,
                    )
                    resp.raise_for_status()
                    page_json: Dict[str, Any] = resp.json()
                    injuries.extend(page_json.get("data", []))
                    cursor = page_json.get("meta", {}).get("next_cursor")
                    pages_fetched += 1
                except Exception as e:
                    # Pagination failure
                    try:
                        notify_error(
                            title="BDL Injuries - Pagination Failed",
                            message=f"Failed to fetch page {pages_fetched + 1} for {self.opts.get('ident', 'unknown')}: {str(e)}",
                            details={
                                'scraper': 'bdl_injuries',
                                'ident': self.opts.get('ident'),
                                'pages_fetched': pages_fetched,
                                'injuries_so_far': len(injuries),
                                'error_type': type(e).__name__,
                                'cursor': cursor
                            },
                            processor_name="Ball Don't Lie Injuries"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send pagination error notification: {notify_ex}")
                    raise

            injuries.sort(key=lambda r: (r.get("team", {}).get("id"), r.get("player_id")))

            self.data = {
                "ident": self.opts["ident"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "rowCount": len(injuries),
                "injuries": injuries,
            }
            
            logger.info("Fetched %d injury rows for %s across %d pages", 
                       len(injuries), self.opts["ident"], pages_fetched)

            # Data quality checks
            if self.opts["ident"] == "league" and len(injuries) > 150:
                # Unusually high league-wide injury count (might indicate data issue)
                try:
                    notify_warning(
                        title="BDL Injuries - High Injury Count",
                        message=f"Unusually high injury count: {len(injuries)} injuries reported league-wide",
                        details={
                            'scraper': 'bdl_injuries',
                            'ident': 'league',
                            'injury_count': len(injuries),
                            'note': 'Verify if this is accurate or a data quality issue'
                        },
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send high count warning: {notify_ex}")
            
            # Success notification (injuries can be 0, which is normal)
            try:
                notify_info(
                    title="BDL Injuries - Success",
                    message=f"Successfully scraped {len(injuries)} injury records ({self.opts.get('ident', 'unknown')})",
                    details={
                        'scraper': 'bdl_injuries',
                        'ident': self.opts.get('ident'),
                        'injury_count': len(injuries),
                        'pages_fetched': pages_fetched,
                        'note': 'Zero injuries is normal if no players are currently injured'
                    },
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send success notification: {notify_ex}")

        except Exception as e:
            # General transformation error
            try:
                notify_error(
                    title="BDL Injuries - Transform Failed",
                    message=f"Data transformation failed for {self.opts.get('ident', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_injuries',
                        'ident': self.opts.get('ident'),
                        'error_type': type(e).__name__,
                        'has_decoded_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Injuries"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send transform error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"rowCount": self.data.get("rowCount", 0), "ident": self.opts["ident"]}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlInjuriesScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlInjuriesScraper.create_cli_and_flask_main()
    main()
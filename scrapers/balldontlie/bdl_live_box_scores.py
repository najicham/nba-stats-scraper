"""
File: scrapers/balldontlie/bdl_live_box_scores.py

BALLDONTLIE - Live Box-Scores endpoint                      v1.1 - 2025-06-24
-------------------------------------------------------------------------------
Continuously updated box scores:

    https://api.balldontlie.io/v1/box_scores/live

Endpoint returns all games in progress; empty array when none.

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_live_box_scores \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_live_box_scores.py --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_live_box_scores.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_live_box_scores
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_live_box_scores.py
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
class BdlLiveBoxScoresScraper(ScraperBase, ScraperFlaskMixin):
    """Fast-cadence scraper for /box_scores/live."""

    # Flask Mixin Configuration
    scraper_name = "bdl_live_box_scores"
    required_params = []  # No required parameters
    optional_params = {
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
    GCS_PATH_KEY = "bdl_live_box_scores"
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # Normal artifact (timestamp keeps files unique)
        {
            "type": "file",
            "filename": "/tmp/bdl_live_boxes_%(ts)s.json",
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
    # Additional opts - timestamp token                                  #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts.setdefault("ts", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/box_scores/live"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        self.url = self._API_ROOT
        logger.debug("Live box-scores URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-live/1.1 (+github.com/your-org)",
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
                raise ValueError("Live boxes response malformed: missing 'data' key")
        except Exception as e:
            # Send error notification for validation failure
            try:
                notify_error(
                    title="BDL Live Box Scores - Validation Failed",
                    message=f"Data validation failed: {str(e)}",
                    details={
                        'scraper': 'bdl_live_box_scores',
                        'poll_id': self.opts.get('ts'),
                        'error_type': type(e).__name__,
                        'url': self.url,
                        'has_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Live Box Scores"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send validation error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        try:
            live_boxes: List[Dict[str, Any]] = list(self.decoded_data["data"])
            cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")
            pages_fetched = 1

            # Paginate through all results (unlikely for live games, but possible)
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
                    live_boxes.extend(page_json.get("data", []))
                    cursor = page_json.get("meta", {}).get("next_cursor")
                    pages_fetched += 1
                except Exception as e:
                    # Pagination failure
                    try:
                        notify_error(
                            title="BDL Live Box Scores - Pagination Failed",
                            message=f"Failed to fetch page {pages_fetched + 1}: {str(e)}",
                            details={
                                'scraper': 'bdl_live_box_scores',
                                'poll_id': self.opts.get('ts'),
                                'pages_fetched': pages_fetched,
                                'games_so_far': len(live_boxes),
                                'error_type': type(e).__name__,
                                'cursor': cursor
                            },
                            processor_name="Ball Don't Lie Live Box Scores"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send pagination error notification: {notify_ex}")
                    raise

            live_boxes.sort(key=lambda g: g.get("game", {}).get("id"))

            self.data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pollId": self.opts["ts"],
                "gameCount": len(live_boxes),
                "liveBoxes": live_boxes,
            }
            
            logger.info("Fetched live box-scores for %d in-progress games (poll: %s)", 
                       len(live_boxes), self.opts["ts"])

            # Success notification - note that 0 games is normal for off-hours
            # Only send INFO notifications when games are actually in progress
            # to avoid notification spam during off-hours
            if len(live_boxes) > 0:
                try:
                    notify_info(
                        title="BDL Live Box Scores - Success",
                        message=f"Successfully scraped live data for {len(live_boxes)} in-progress games",
                        details={
                            'scraper': 'bdl_live_box_scores',
                            'poll_id': self.opts.get('ts'),
                            'game_count': len(live_boxes),
                            'pages_fetched': pages_fetched
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send success notification: {notify_ex}")

        except Exception as e:
            # General transformation error
            try:
                notify_error(
                    title="BDL Live Box Scores - Transform Failed",
                    message=f"Data transformation failed: {str(e)}",
                    details={
                        'scraper': 'bdl_live_box_scores',
                        'poll_id': self.opts.get('ts'),
                        'error_type': type(e).__name__,
                        'has_decoded_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Live Box Scores"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send transform error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"gameCount": self.data.get("gameCount", 0), "pollId": self.opts["ts"]}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlLiveBoxScoresScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlLiveBoxScoresScraper.create_cli_and_flask_main()
    main()
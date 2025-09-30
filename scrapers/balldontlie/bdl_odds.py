"""
File: scrapers/balldontlie/bdl_odds.py

BALLDONTLIE - Odds endpoint                                   v1.2 - 2025-06-24
-------------------------------------------------------------------------------
Fetch betting odds either by calendar **date** or by **game_id**.

    /odds?date=YYYY-MM-DD
    /odds?game_id=123456

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_odds \
      --date 2025-01-15 \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_odds.py --gameId 18444564 --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_odds.py --serve --debug
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import sys
from typing import Any, Dict, List, Optional

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_odds
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_odds.py
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
class BdlOddsScraper(ScraperBase, ScraperFlaskMixin):
    """Fetch odds rows, follow cursor pagination, merge pages."""

    # Flask Mixin Configuration
    scraper_name = "bdl_odds"
    required_params = []  # No required parameters
    optional_params = {
        "gameId": None,  # Specific game ID (overrides date)
        "date": None,    # Defaults to today if neither gameId nor date provided
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
    GCS_PATH_KEY = "bdl_odds"
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
            "filename": "/tmp/bdl_odds_%(ident)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
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
    # Option derivation                                                  #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        today = _dt.date.today().isoformat()
        if self.opts.get("gameId"):
            self.opts["ident"] = f"game_{self.opts['gameId']}"
        else:
            self.opts["date"] = self.opts.get("date") or today
            self.opts["ident"] = f"date_{self.opts['date']}"

    # ------------------------------------------------------------------ #
    # HTTP setup                                                         #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/odds"

    def set_url(self) -> None:
        if self.opts.get("gameId"):
            qs = f"game_id={self.opts['gameId']}"
        else:
            qs = f"date={self.opts['date']}"
        self.base_url = self._API_ROOT
        self.url = f"{self._API_ROOT}?{qs}&per_page=100"
        logger.debug("Odds URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-odds/1.1 (+github.com/your-org)",
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
                raise ValueError("Odds response malformed: no 'data' key")
        except Exception as e:
            # Send error notification for validation failure
            try:
                notify_error(
                    title="BDL Odds - Validation Failed",
                    message=f"Data validation failed for {self.opts.get('ident', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_odds',
                        'ident': self.opts.get('ident'),
                        'game_id': self.opts.get('gameId'),
                        'date': self.opts.get('date'),
                        'error_type': type(e).__name__,
                        'url': self.url,
                        'has_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Odds"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send validation error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        try:
            rows: List[Dict[str, Any]] = list(self.decoded_data["data"])
            cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")
            pages_fetched = 1

            # Paginate through all results
            while cursor:
                try:
                    r = self.http_downloader.get(
                        self.base_url,
                        headers=self.headers,
                        params={"cursor": cursor, "per_page": 100},
                        timeout=self.timeout_http,
                    )
                    r.raise_for_status()
                    j = r.json()
                    rows.extend(j.get("data", []))
                    cursor = j.get("meta", {}).get("next_cursor")
                    pages_fetched += 1
                except Exception as e:
                    # Pagination failure
                    try:
                        notify_error(
                            title="BDL Odds - Pagination Failed",
                            message=f"Failed to fetch page {pages_fetched + 1} for {self.opts.get('ident', 'unknown')}: {str(e)}",
                            details={
                                'scraper': 'bdl_odds',
                                'ident': self.opts.get('ident'),
                                'game_id': self.opts.get('gameId'),
                                'date': self.opts.get('date'),
                                'pages_fetched': pages_fetched,
                                'rows_so_far': len(rows),
                                'error_type': type(e).__name__,
                                'cursor': cursor
                            },
                            processor_name="Ball Don't Lie Odds"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send pagination error notification: {notify_ex}")
                    raise

            def _sort_key(r):
                return (
                    r.get("game_id", 0),
                    r.get("type", ""),
                    r.get("vendor", ""),
                    r.get("updated_at", ""),
                )

            rows.sort(key=_sort_key)

            self.data = {
                "ident": self.opts["ident"],
                "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "rowCount": len(rows),
                "odds": rows,
            }
            
            logger.info("Fetched %d odds rows for %s across %d pages", 
                       len(rows), self.opts["ident"], pages_fetched)

            # Success notification
            try:
                notify_info(
                    title="BDL Odds - Success",
                    message=f"Successfully scraped {len(rows)} odds rows ({self.opts.get('ident', 'unknown')})",
                    details={
                        'scraper': 'bdl_odds',
                        'ident': self.opts.get('ident'),
                        'game_id': self.opts.get('gameId'),
                        'date': self.opts.get('date'),
                        'row_count': len(rows),
                        'pages_fetched': pages_fetched
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send success notification: {notify_ex}")

        except Exception as e:
            # General transformation error
            try:
                notify_error(
                    title="BDL Odds - Transform Failed",
                    message=f"Data transformation failed for {self.opts.get('ident', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_odds',
                        'ident': self.opts.get('ident'),
                        'game_id': self.opts.get('gameId'),
                        'date': self.opts.get('date'),
                        'error_type': type(e).__name__,
                        'has_decoded_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Odds"
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
create_app = convert_existing_flask_scraper(BdlOddsScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlOddsScraper.create_cli_and_flask_main()
    main()
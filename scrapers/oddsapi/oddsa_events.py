# scrapers/oddsapi/oddsa_events.py
"""
odds_api_events.py
Scraper for The-Odds-API v4 **current events** endpoint.

Docs
  https://the-odds-api.com/liveapi/guides/v4/#get-events

Endpoint
  GET /v4/sports/{sport}/events
Query params
  * api_key (required - but we default to env ODDS_API_KEY)
  * commenceTimeFrom / commenceTimeTo (optional ISO timestamps)
  * dateFormat=iso|unix  (optional)

The endpoint returns **a list of event objects**.

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py oddsa_events \
      --sport basketball_nba \
      --debug

  # Direct CLI execution:
  python scrapers/oddsapi/oddsa_events.py --sport basketball_nba --debug

  # Flask web service:
  python scrapers/oddsapi/oddsa_events.py --serve --debug
"""

from __future__ import annotations

import os
import logging
import sys
from urllib.parse import urlencode
from typing import Any, Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.oddsapi.oddsa_events
    from ..scraper_base import ScraperBase, ExportMode
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/oddsapi/oddsa_events.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import ScraperBase, ExportMode
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class GetOddsApiEvents(ScraperBase, ScraperFlaskMixin):
    """
    Required opts:
      • sport - e.g. basketball_nba

    Optional opts (all map 1-to-1 onto query params):
      • api_key  - falls back to env ODDS_API_KEY
      • commenceTimeFrom / commenceTimeTo
      • dateFormat
    """

    # Flask Mixin Configuration
    scraper_name = "oddsa_events"
    required_params = ["sport"]
    optional_params = {
        "api_key": None,  # Falls back to env ODDS_API_KEY
        "commenceTimeFrom": None,
        "commenceTimeTo": None,
        "dateFormat": None,
    }

    required_opts: List[str] = ["sport"]  # api_key via env if omitted
    proxy_enabled = False
    browser_enabled = False

    # ------------------------------------------------------------------ #
    # Exporters                                                          #
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "odds_api_events"
    exporters = [
        {   # RAW for prod / GCS archival
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {   # Pretty JSON for dev & capture
            "type": "file",
            "filename": "/tmp/oddsapi_events_%(sport)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "capture", "test"],
        },
        # Add capture group exporters
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
    _API_ROOT_TMPL = "https://api.the-odds-api.com/v4/sports/{sport}/events"

    def set_url(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("ODDS_API_KEY")
        if not api_key:
            raise DownloadDataException(
                "Missing api_key and env var ODDS_API_KEY not set."
            )

        base = self._API_ROOT_TMPL.format(sport=self.opts["sport"])

        query: Dict[str, Any] = {
            "apiKey": api_key,
            "commenceTimeFrom": self.opts.get("commenceTimeFrom"),
            "commenceTimeTo": self.opts.get("commenceTimeTo"),
            "dateFormat": self.opts.get("dateFormat"),
        }
        # strip None values
        query = {k: v for k, v in query.items() if v is not None}
        self.url = f"{base}?{urlencode(query, doseq=True)}"
        logger.info("Odds-API Events URL: %s", self.url)

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """
        Expect a *list* of events.  Handle API error messages.
        """
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            raise DownloadDataException(f"API error: {self.decoded_data['message']}")

        if not isinstance(self.decoded_data, list):
            raise DownloadDataException("Expected a list of events.")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        events: List[Dict[str, Any]] = self.decoded_data  # type: ignore[assignment]
        events.sort(key=lambda e: e.get("commence_time", ""))

        self.data = {
            "sport": self.opts["sport"],
            "rowCount": len(events),
            "events": events,
        }
        logger.info("Fetched %d events for %s", len(events), self.opts["sport"])

    # ------------------------------------------------------------------ #
    # Conditional save                                                   #
    # ------------------------------------------------------------------ #
    def should_save_data(self) -> bool:
        return bool(self.data.get("rowCount"))

    # ------------------------------------------------------------------ #
    # Stats line                                                         #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0),
            "sport": self.opts.get("sport"),
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetOddsApiEvents)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetOddsApiEvents.create_cli_and_flask_main()
    main()
    
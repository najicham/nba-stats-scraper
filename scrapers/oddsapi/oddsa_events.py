"""
odds_api_events.py
Scraper for The-Odds-API v4 **current events** endpoint.

Docs
  https://the-odds-api.com/liveapi/guides/v4/#get-events

Endpoint
  GET /v4/sports/{sport}/events
Query params
  * apiKey (required - but we default to env ODDS_API_KEY)
  * commenceTimeFrom / commenceTimeTo (optional ISO timestamps)
  * dateFormat=iso|unix  (optional)

The endpoint returns **a list of event objects**.
"""

from __future__ import annotations

import os
import logging
from urllib.parse import urlencode
from typing import Any, Dict, List

from scrapers.scraper_base import ScraperBase, ExportMode
from scrapers.utils.exceptions import DownloadDataException

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class GetOddsApiEvents(ScraperBase):
    """
    Required opts:
      • sport - e.g. basketball_nba

    Optional opts (all map 1-to-1 onto query params):
      • apiKey  - falls back to env ODDS_API_KEY
      • commenceTimeFrom / commenceTimeTo
      • dateFormat
    """

    required_opts: List[str] = ["sport"]  # apiKey via env if omitted
    proxy_enabled = False
    browser_enabled = False

    # ------------------------------------------------------------------ #
    # Exporters                                                          #
    # ------------------------------------------------------------------ #
    exporters = [
        {   # RAW for prod / GCS archival
            "type": "gcs",
            "key": "oddsapi/events/current/%(sport)s/%(run_id)s.raw.json",
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
    ]

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT_TMPL = "https://api.the-odds-api.com/v4/sports/{sport}/events"

    def set_url(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("ODDS_API_KEY")
        if not api_key:
            raise DownloadDataException(
                "Missing apiKey and env var ODDS_API_KEY not set."
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
# Google Cloud Function entry point                                           #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    from dotenv import load_dotenv

    load_dotenv()  # harmless in prod if .env absent

    opts = {
        "apiKey": request.args.get("apiKey"),  # env fallback is fine
        "sport": request.args.get("sport", "basketball_nba"),
        "commenceTimeFrom": request.args.get("commenceTimeFrom"),
        "commenceTimeTo": request.args.get("commenceTimeTo"),
        "dateFormat": request.args.get("dateFormat"),
        "group": request.args.get("group", "prod"),
    }
    GetOddsApiEvents().run(opts)
    return f"Odds-API current events scrape complete ({opts['sport']})", 200


# --------------------------------------------------------------------------- #
# Local CLI                                                                   #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Scrape The-Odds-API current events list"
    )
    parser.add_argument("--sport", default="basketball_nba")
    parser.add_argument("--commenceTimeFrom")
    parser.add_argument("--commenceTimeTo")
    parser.add_argument("--dateFormat", choices=["iso", "unix"])
    parser.add_argument("--apiKey", help="Optional - env ODDS_API_KEY fallback")
    parser.add_argument("--group", default="dev")
    parser.add_argument("--debug", action="store_true")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    GetOddsApiEvents().run(vars(args))

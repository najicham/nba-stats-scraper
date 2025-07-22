"""
odds_api_historical_events.py (MIXIN VERSION)
Scraper for The-Odds-API v4 "historical events" endpoint.

Endpoint:
  GET /v4/historical/sports/{sport}/events
Docs:
  https://the-odds-api.com/liveapi/guides/v4/#get-historical-events

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py oddsa_events_his \
      --sport basketball_nba \
      --date 2025-03-10T00:00:00Z \
      --debug

  # Direct CLI execution:
  python scrapers/oddsapi/oddsa_events_his.py --sport basketball_nba --date 2025-03-10T00:00:00Z --debug

  # Flask web service:
  python scrapers/oddsapi/oddsa_events_his.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from typing import Any, Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.oddsapi.oddsa_events_his
    from ..scraper_base import ScraperBase, ExportMode
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/oddsapi/oddsa_events_his.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import ScraperBase, ExportMode
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Helper - snap any datetime string to the previous 5-minute boundary
# --------------------------------------------------------------------------- #
def snap_iso_ts_to_five_minutes(iso: str) -> str:
    """
    >>> snap_iso_ts_to_five_minutes("2025-06-10T22:43:17Z")
    '2025-06-10T22:40:00Z'
    """
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    floored = dt - timedelta(minutes=dt.minute % 5,
                             seconds=dt.second,
                             microseconds=dt.microsecond)
    return floored.replace(tzinfo=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class GetOddsApiHistoricalEvents(ScraperBase, ScraperFlaskMixin):
    """
    Required opts:
      • sport  - e.g. basketball_nba
      • date   - ISO-8601 timestamp to snap (The-Odds snapshots are every 5 min)

    Optional opts:
      • apiKey - your Odds-API key (falls back to env var)
      • commenceTimeFrom / commenceTimeTo - ISO filters on event commence_time
      • eventIds  - comma-sep or list[str]
      • dateFormat - 'iso' (default) or 'unix'
    """

    # Flask Mixin Configuration
    scraper_name = "odds_api_historical_events"
    required_params = ["date"]  # apiKey handled via env var
    optional_params = {
        "apiKey": None,  # Falls back to env var
        "sport": "basketball_nba",
        "commenceTimeFrom": None,
        "commenceTimeTo": None,
        "eventIds": None,
        "dateFormat": None
    }

    # Original scraper config
    required_opts = ["sport", "date"]
    proxy_enabled = False
    browser_enabled = False

    # ------------------------------------------------------------------ #
    # Exporters                                                          #
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "odds_api_events_history"
    exporters = [
        # RAW ⇒ automatically uses GCS_BUCKET_RAW
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        # Pretty JSON for local dev or fixture capture
        {
            "type": "file",
            "filename": "/tmp/oddsapi_hist_events_%(date)s.json",
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
    # Additional opts                                                    #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        """
        Round the supplied timestamp down to the nearest 5-minute snapshot
        (doc: snapshots are 5 min granularity after 2022-09-18).
        """
        if self.opts.get("date"):
            self.opts["date"] = snap_iso_ts_to_five_minutes(self.opts["date"])

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT_TMPL = "https://api.the-odds-api.com/v4/historical/sports/{sport}/events"

    def set_url(self) -> None:
        base = self._API_ROOT_TMPL.format(sport=self.opts["sport"])

        api_key = self.opts.get("apiKey") or os.getenv("ODDS_API_KEY")
        if not api_key:
            raise DownloadDataException("Missing apiKey and no ODDS_API_KEY env var found.")

        query: Dict[str, Any] = {
            "apiKey": api_key,
            "date": self.opts["date"],
            "commenceTimeFrom": self.opts.get("commenceTimeFrom"),
            "commenceTimeTo": self.opts.get("commenceTimeTo"),
            "eventIds": self.opts.get("eventIds"),
            "dateFormat": self.opts.get("dateFormat"),
        }
        # scrub None values
        query = {k: v for k, v in query.items() if v is not None}
        self.url = f"{base}?{urlencode(query, doseq=True)}"
        logger.info("Odds-API Historical Events URL: %s", self.url)

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}  # UA not required

    # ------------------------------------------------------------------ #
    # HTTP status handling                                               #
    # ------------------------------------------------------------------ #
    def check_download_status(self) -> None:
        """
        Treat 200 **and 204** as success (204 ⇒ empty snapshot, costs 0 credits).
        """
        if self.raw_response.status_code in (200, 204):
            return
        super().check_download_status()  # will raise on other status codes

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """
        Expect wrapper dict with 'data' list.  Handle 'message' (errors).
        """
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            raise DownloadDataException(f"API error: {self.decoded_data['message']}")

        if not (isinstance(self.decoded_data, dict) and "data" in self.decoded_data):
            raise DownloadDataException("Expected dict with 'data' key.")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        wrapper: Dict[str, Any] = self.decoded_data  # type: ignore[assignment]

        events: List[Dict[str, Any]] = wrapper.get("data", [])
        events.sort(key=lambda e: e.get("commence_time", ""))

        self.data = {
            "sport": self.opts["sport"],
            "snapshot_timestamp": wrapper.get("timestamp"),
            "previous_snapshot": wrapper.get("previous_timestamp"),
            "next_snapshot": wrapper.get("next_timestamp"),
            "rowCount": len(events),
            "events": events,
        }
        logger.info("Fetched %d events @ %s", len(events), self.data["snapshot_timestamp"])

    # ------------------------------------------------------------------ #
    # Conditional save                                                   #
    # ------------------------------------------------------------------ #
    def should_save_data(self) -> bool:
        """Skip export when rowCount == 0 (i.e., 204 empty snapshot)."""
        return bool(self.data.get("rowCount"))

    # ------------------------------------------------------------------ #
    # Stats line                                                         #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0),
            "sport": self.opts.get("sport"),
            "snapshot": self.data.get("snapshot_timestamp"),
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
try:
    from ..scraper_flask_mixin import convert_existing_flask_scraper
except ImportError:
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
create_app = convert_existing_flask_scraper(GetOddsApiHistoricalEvents)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetOddsApiHistoricalEvents.create_cli_and_flask_main()
    main()
# scrapers/oddsapi/oddsa_events_his.py
"""
odds_api_historical_events.py
Scraper for The-Odds-API v4 "historical events" endpoint.

This scraper retrieves event IDs and basic event information (teams, commence times) 
for a given date and timestamp. Use this to discover available events before fetching 
their odds with the historical event odds scrapers.

SNAPSHOT TIMESTAMP STRATEGY FOR EVENTS:
  • Use 00:00:00Z (midnight UTC) to get the full day's event lineup
  • Events are typically available from early morning until they start
  • NBA games usually commence 23:00-02:00 UTC (evening US time)
  • The API returns the closest available snapshot <= your timestamp
  • Events disappear from the API when games start or shortly before

Usage examples
--------------
  # Get full daily NBA schedule (recommended for event discovery):
  python tools/fixtures/capture.py oddsa_events_his \
      --game_date 2024-01-25 \
      --snapshot_timestamp 2024-01-25T00:00:00Z \
      --debug

  # Get events as they appeared later in the day:
  python tools/fixtures/capture.py oddsa_events_his \
      --game_date 2024-01-25 \
      --snapshot_timestamp 2024-01-25T16:00:00Z \
      --debug

  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py oddsa_events_his \
      --game_date 2024-01-25 \
      --snapshot_timestamp 2024-01-25T04:00:00Z \
      --debug

  # Direct CLI execution:
  python scrapers/oddsapi/oddsa_events_his.py \
      --game_date 2024-01-25 \
      --snapshot_timestamp 2024-01-25T00:00:00Z \
      --debug

  # Flask web service:
  python scrapers/oddsapi/oddsa_events_his.py --serve --debug

WORKFLOW:
  1. Run this scraper to get event IDs for a date
  2. Use the event IDs with oddsa_player_props_his or oddsa_game_lines_his
  3. Use the same (or similar) snapshot_timestamp for consistency

OUTPUT:
  Returns event objects with:
  • id: Event ID to use with other historical scrapers
  • home_team / away_team: Team names
  • commence_time: When the game starts
  • sport_key: Always "basketball_nba" for NBA
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
      • game_date          - Eastern date for GCS directory (e.g., "2024-04-10")
      • snapshot_timestamp - UTC timestamp for API snapshot (e.g., "2024-04-10T20:00:00Z")

    Optional opts:
      • sport              - e.g. basketball_nba (defaults to basketball_nba)
      • api_key           - your Odds-API key (falls back to env var)
      • commenceTimeFrom  - ISO filters on event commence_time
      • commenceTimeTo    - ISO filters on event commence_time
      • event_ids         - comma-sep or list[str]
      • dateFormat        - 'iso' (default) or 'unix'
    """

    # Flask Mixin Configuration
    scraper_name = "odds_api_historical_events"
    required_params = ["game_date", "snapshot_timestamp"]
    optional_params = {
        "api_key": None,  # Falls back to env var
        "sport": None,  # Defaults to basketball_nba in set_additional_opts
        "commenceTimeFrom": None,
        "commenceTimeTo": None,
        "event_ids": None,
        "dateFormat": None
    }

    # Original scraper config
    required_opts = ["game_date", "snapshot_timestamp"]
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
            "check_should_save": True,  # Enable conditional save
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
        FIXED: Consistent parameter handling (super first, like props scraper).
        """
        # Call base class first for standard processing
        super().set_additional_opts()  # Base class handles game_date → date conversion
        
        # Snap the snapshot timestamp to valid 5-minute boundary for API
        if self.opts.get("snapshot_timestamp"):
            original_timestamp = self.opts["snapshot_timestamp"]
            self.opts["snapshot_timestamp"] = snap_iso_ts_to_five_minutes(original_timestamp)
            if original_timestamp != self.opts["snapshot_timestamp"]:
                logger.debug("Snapped timestamp %s → %s", original_timestamp, self.opts["snapshot_timestamp"])

        if not self.opts.get("sport"):
            self.opts["sport"] = "basketball_nba"
        if not self.opts.get("regions"):
            self.opts["regions"] = "us"
        
        # Debug logging to verify path variables
        logger.debug("Events scraper path variables: date=%s, game_date=%s, snapshot_timestamp=%s", 
                    self.opts.get("date"), self.opts.get("game_date"), self.opts.get("snapshot_timestamp"))

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT_TMPL = "https://api.the-odds-api.com/v4/historical/sports/{sport}/events"

    def set_url(self) -> None:
        base = self._API_ROOT_TMPL.format(sport=self.opts["sport"])

        api_key = self.opts.get("api_key") or os.getenv("ODDS_API_KEY")
        if not api_key:
            raise DownloadDataException("Missing api_key and no ODDS_API_KEY env var found.")

        query: Dict[str, Any] = {
            "apiKey": api_key,
            "date": self.opts["snapshot_timestamp"],  # Use snapshot_timestamp for API
            "commenceTimeFrom": self.opts.get("commenceTimeFrom"),
            "commenceTimeTo": self.opts.get("commenceTimeTo"),
            "event_ids": self.opts.get("event_ids"),
            "dateFormat": self.opts.get("dateFormat"),
        }
        # scrub None values
        query = {k: v for k, v in query.items() if v is not None}
        self.url = f"{base}?{urlencode(query, doseq=True)}"
        logger.info("Odds-API Historical Events URL: %s", self.url.replace(api_key, "***"))

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}

    # ------------------------------------------------------------------ #
    # HTTP status handling                                               #
    # ------------------------------------------------------------------ #
    def check_download_status(self) -> None:
        """
        Treat 200 **and 204** as success (204 ⇒ empty snapshot, costs 0 credits).
        """
        if self.raw_response.status_code in (200, 204):
            return
        super().check_download_status()

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """
        Expect wrapper dict with 'data' list. Handle 'message' (errors).
        Handle 204 responses gracefully.
        """
        # Handle 204 responses (empty snapshot)
        if self.raw_response.status_code == 204:
            logger.info("204 response - no events available for snapshot %s", 
                       self.opts.get("snapshot_timestamp"))
            # Create empty response structure for consistency
            self.decoded_data = {
                "data": [],
                "timestamp": self.opts.get("snapshot_timestamp"),
                "message": "No events available for this snapshot"
            }
            return

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
            "game_date": self.opts["game_date"],  # Include game_date in output
            "snapshot_timestamp": wrapper.get("timestamp"),
            "previous_snapshot": wrapper.get("previous_timestamp"),
            "next_snapshot": wrapper.get("next_timestamp"),
            "rowCount": len(events),
            "events": events,
        }
        logger.info("Fetched %d events @ %s for date %s", 
                   len(events), self.data["snapshot_timestamp"], self.opts["game_date"])

    # ------------------------------------------------------------------ #
    # Conditional save                                                   #
    # ------------------------------------------------------------------ #
    def should_save_data(self) -> bool:
        """
        Skip export when rowCount == 0 (i.e., 204 empty snapshot).
        """
        # For 204 responses, don't save empty data
        if self.raw_response and self.raw_response.status_code == 204:
            logger.info("Skipping save for 204 empty response")
            return False
            
        # Save if we have any events
        return bool(self.data.get("rowCount", 0) > 0)

    # ------------------------------------------------------------------ #
    # Stats line                                                         #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0),
            "sport": self.opts.get("sport"),
            "game_date": self.opts.get("game_date"),
            "snapshot": self.data.get("snapshot_timestamp"),
            "status_code": self.raw_response.status_code if self.raw_response else "unknown",
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
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
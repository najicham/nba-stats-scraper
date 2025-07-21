# scrapers/oddsapi/oddsa_player_props_his.py
"""
odds_api_historical_event_odds.py
Scraper for The-Odds-API v4 "historical event odds" endpoint.

Docs:
  https://the-odds-api.com/liveapi/guides/v4/#get-historical-event-odds

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py oddsa_player_props_his \
      --eventId 6f0b6f8d8cc9c5bc6375cdee \
      --date 2025-06-10T00:00:00Z \
      --debug

  # Direct CLI execution:
  python scrapers/oddsapi/oddsa_player_props_his.py \
      --eventId 6f0b6f8d8cc9c5bc6375cdee \
      --date 2025-06-10T00:00:00Z \
      --debug

  # Flask web service:
  python scrapers/oddsapi/oddsa_player_props_his.py --serve --debug
"""

from __future__ import annotations

import os
import logging
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from typing import Any, Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.oddsapi.oddsa_player_props_his
    from ..scraper_base import ScraperBase, ExportMode
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
except ImportError:
    # Direct execution: python scrapers/oddsapi/oddsa_player_props_his.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import ScraperBase, ExportMode
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helper - snap ISO timestamp to previous 5-minute boundary                   #
# --------------------------------------------------------------------------- #
def snap_iso_ts_to_five_minutes(iso_ts: str) -> str:
    """
    '2025-06-10T22:43:17Z'  ->  '2025-06-10T22:40:00Z'
    """
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    floored = dt - timedelta(minutes=dt.minute % 5,
                             seconds=dt.second,
                             microseconds=dt.microsecond)
    return (floored.replace(tzinfo=timezone.utc)
                   .isoformat(timespec="seconds")
                   .replace("+00:00", "Z"))


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class GetOddsApiHistoricalEventOdds(ScraperBase, ScraperFlaskMixin):
    """
    Required opts:
      • eventId    - e.g. 6f0b6f8d8cc9…
      • date       - snapshot timestamp (ISO-8601)

    Optional opts:
      • sport      - e.g. basketball_nba (defaults to basketball_nba)
      • regions    - comma-separated list (us, uk, eu, au) (defaults to us)
      • markets    - comma-separated list (player_points, player_assists, …) (defaults to player_points)
      • bookmakers - comma-separated list (defaults to draftkings,fanduel)
      • oddsFormat  - american | decimal | fractional
      • dateFormat  - iso | unix
      • apiKey      - if omitted, pulled from env `ODDS_API_KEY`
    """

    # Flask Mixin Configuration
    scraper_name = "oddsa_player_props_his"
    required_params = ["eventId", "date"]
    optional_params = {
        "apiKey": None,  # Falls back to env ODDS_API_KEY
        "sport": None,  # Defaults to basketball_nba in set_additional_opts
        "regions": None,  # Defaults to us in set_additional_opts
        "markets": None,  # Defaults to player_points in set_additional_opts
        "bookmakers": None,  # Defaults to draftkings,fanduel in set_additional_opts
        "oddsFormat": None,
        "dateFormat": None,
    }

    required_opts = ["eventId", "date"]
    proxy_enabled = False
    browser_enabled = False

    # ------------------------------------------------------------------ #
    # Exporters                                                          #
    # ------------------------------------------------------------------ #
    exporters = [
        {   # RAW payload for prod / GCS archival
            "type": "gcs",
            "key": "oddsapi/historical-event-odds/%(sport)s/%(eventId)s_%(date)s.raw.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {   # Pretty JSON for dev & capture
            "type": "file",
            "filename": "/tmp/oddsapi_hist_event_odds_%(sport)s_%(eventId)s.json",
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
        # Snap to valid snapshot boundary
        self.opts["date"] = snap_iso_ts_to_five_minutes(self.opts["date"])
        # ── season‑wide defaults ──────────────────────────────
        self.opts.setdefault("sport", "basketball_nba")
        self.opts.setdefault("regions", "us")
        self.opts.setdefault("markets", "player_points")
        self.opts.setdefault("bookmakers", "draftkings,fanduel")

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT_TMPL = (
        "https://api.the-odds-api.com/v4/historical/sports/"
        "{sport}/events/{eventId}/odds"
    )

    def set_url(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("ODDS_API_KEY")
        if not api_key:
            raise DownloadDataException(
                "Missing apiKey and env var ODDS_API_KEY not set."
            )

        base = self._API_ROOT_TMPL.format(
            sport=self.opts["sport"],
            eventId=self.opts["eventId"],
        )

        query: Dict[str, Any] = {
            "apiKey": api_key,
            "date": self.opts["date"],
            "regions": self.opts["regions"],
            "markets": self.opts["markets"],
            "bookmakers": self.opts["bookmakers"],
            "oddsFormat": self.opts.get("oddsFormat"),
            "dateFormat": self.opts.get("dateFormat"),
        }
        query = {k: v for k, v in query.items() if v is not None}
        self.url = f"{base}?{urlencode(query, doseq=True)}"
        logger.info("Odds-API Historical Event Odds URL: %s", self.url)

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}

    # ------------------------------------------------------------------ #
    # HTTP status handling                                               #
    # ------------------------------------------------------------------ #
    def check_download_status(self) -> None:
        """
        200 and 204 are "okay" for this endpoint.
        """
        if self.raw_response.status_code in (200, 204):
            return
        super().check_download_status()

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """
        Expect wrapper dict with 'data' object.
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
        event_odds: Dict[str, Any] = wrapper.get("data", {})

        # Count distinct bookmaker × market entries
        row_count = 0
        for bm in event_odds.get("bookmakers", []):
            for mk in bm.get("markets", []):
                row_count += len(mk.get("outcomes", [])) or 1

        self.data = {
            "sport": self.opts["sport"],
            "eventId": self.opts["eventId"],
            "snapshot_timestamp": wrapper.get("timestamp"),
            "previous_snapshot": wrapper.get("previous_timestamp"),
            "next_snapshot": wrapper.get("next_timestamp"),
            "regions": self.opts["regions"],
            "markets": self.opts["markets"],
            "rowCount": row_count,
            "eventOdds": event_odds,
        }
        logger.info(
            "Fetched %d bookmaker-market rows for event %s", row_count, self.opts["eventId"]
        )

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
            "eventId": self.opts.get("eventId"),
            "markets": self.opts.get("markets"),
            "regions": self.opts.get("regions"),
            "snapshot": self.data.get("snapshot_timestamp"),
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetOddsApiHistoricalEventOdds)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetOddsApiHistoricalEventOdds.create_cli_and_flask_main()
    main()
    
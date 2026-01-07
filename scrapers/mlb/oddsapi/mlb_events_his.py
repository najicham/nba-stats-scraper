#!/usr/bin/env python3
"""
MLB Odds API Historical Events Scraper

Fetches historical event IDs from The Odds API for MLB games at a specific snapshot.
Use this to discover available events before fetching their historical odds.

Endpoint: GET /v4/historical/sports/baseball_mlb/events

Usage:
  # Get events for a specific date at midnight snapshot:
  SPORT=mlb python scrapers/mlb/oddsapi/mlb_events_his.py \
      --game_date 2025-06-15 --snapshot_timestamp 2025-06-15T00:00:00Z --group dev

  # Flask service:
  SPORT=mlb python scrapers/mlb/oddsapi/mlb_events_his.py --serve --debug

WORKFLOW:
  1. Run this scraper to get event IDs for a date
  2. Use the event IDs with mlb_pitcher_props_his or mlb_game_lines_his
  3. Use the same (or similar) snapshot_timestamp for consistency

Created: 2026-01-06
"""

from __future__ import annotations

import os
import logging
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from typing import Any, Dict, List

try:
    from ...scraper_base import ScraperBase, ExportMode
    from ...scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from ...utils.exceptions import DownloadDataException
    from ...utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from scrapers.scraper_base import ScraperBase, ExportMode
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

from shared.utils.notification_system import notify_error, notify_warning, notify_info
from shared.utils.auth_utils import get_api_key

logger = logging.getLogger(__name__)


def snap_iso_ts_to_five_minutes(iso: str) -> str:
    """Snap timestamp to previous 5-minute boundary (API requirement)."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    floored = dt - timedelta(minutes=dt.minute % 5,
                             seconds=dt.second,
                             microseconds=dt.microsecond)
    return floored.replace(tzinfo=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class MlbEventsHistoricalScraper(ScraperBase, ScraperFlaskMixin):
    """
    MLB Historical Events Scraper for The Odds API.

    Retrieves event IDs and basic event info for a given date at a specific snapshot.

    Required opts:
      - game_date: Date for GCS directory (YYYY-MM-DD)
      - snapshot_timestamp: UTC timestamp for API snapshot (YYYY-MM-DDTHH:MM:SSZ)

    Optional opts:
      - commenceTimeFrom: Filter events by commence time
      - commenceTimeTo: Filter events by commence time
    """

    scraper_name = "mlb_events_his"
    required_params = ["game_date", "snapshot_timestamp"]
    optional_params = {
        "api_key": None,
        "commenceTimeFrom": None,
        "commenceTimeTo": None,
        "event_ids": None,
        "dateFormat": None,
    }

    required_opts: List[str] = ["game_date", "snapshot_timestamp"]
    proxy_enabled = False
    browser_enabled = False

    GCS_PATH_KEY = "mlb_odds_api_events_history"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
            "check_should_save": True,
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_events_his_%(game_date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "capture", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        """Set defaults and snap timestamp."""
        super().set_additional_opts()

        # Snap timestamp to 5-minute boundary
        if self.opts.get("snapshot_timestamp"):
            original = self.opts["snapshot_timestamp"]
            self.opts["snapshot_timestamp"] = snap_iso_ts_to_five_minutes(original)
            if original != self.opts["snapshot_timestamp"]:
                logger.debug("Snapped timestamp %s → %s", original, self.opts["snapshot_timestamp"])

    _API_ROOT = "https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/events"

    def set_url(self) -> None:
        api_key = get_api_key(
            secret_name='ODDS_API_KEY',
            default_env_var='ODDS_API_KEY'
        )
        if not api_key:
            raise DownloadDataException("Missing ODDS_API_KEY")

        query: Dict[str, Any] = {
            "apiKey": api_key,
            "date": self.opts["snapshot_timestamp"],
            "commenceTimeFrom": self.opts.get("commenceTimeFrom"),
            "commenceTimeTo": self.opts.get("commenceTimeTo"),
            "event_ids": self.opts.get("event_ids"),
            "dateFormat": self.opts.get("dateFormat"),
        }
        query = {k: v for k, v in query.items() if v is not None}
        self.url = f"{self._API_ROOT}?{urlencode(query, doseq=True)}"
        logger.info("MLB Historical Events URL: %s", self.url.replace(api_key, "***"))

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}

    def check_download_status(self) -> None:
        """Handle 200 and 204 (empty snapshot) as success."""
        if self.raw_response.status_code in (200, 204):
            if self.raw_response.status_code == 204:
                logger.info("204 response - no events at snapshot %s", self.opts.get("snapshot_timestamp"))
            return
        super().check_download_status()

    def validate_download_data(self) -> None:
        # Handle 204
        if self.raw_response.status_code == 204:
            self.decoded_data = {
                "data": [],
                "timestamp": self.opts.get("snapshot_timestamp"),
            }
            return

        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            raise DownloadDataException(f"API error: {self.decoded_data['message']}")

        if not (isinstance(self.decoded_data, dict) and "data" in self.decoded_data):
            raise DownloadDataException("Expected dict with 'data' key.")

    def transform_data(self) -> None:
        wrapper = self.decoded_data
        events = wrapper.get("data", [])
        events.sort(key=lambda e: e.get("commence_time", ""))

        self.data = {
            "sport": "baseball_mlb",
            "game_date": self.opts["game_date"],
            "snapshot_timestamp": wrapper.get("timestamp"),
            "previous_snapshot": wrapper.get("previous_timestamp"),
            "next_snapshot": wrapper.get("next_timestamp"),
            "rowCount": len(events),
            "events": events,
        }

        if len(events) == 0:
            notify_warning(
                title="No MLB Historical Events",
                message=f"No events found at snapshot for {self.opts.get('game_date')}",
                details={
                    'scraper': 'mlb_events_his',
                    'game_date': self.opts.get('game_date'),
                    'snapshot_timestamp': self.opts.get('snapshot_timestamp'),
                }
            )
        else:
            notify_info(
                title="MLB Historical Events Retrieved",
                message=f"Found {len(events)} events at snapshot",
                details={
                    'scraper': 'mlb_events_his',
                    'game_date': self.opts.get('game_date'),
                    'snapshot_timestamp': wrapper.get('timestamp'),
                    'event_count': len(events),
                }
            )

        logger.info("Fetched %d historical events @ %s", len(events), self.data["snapshot_timestamp"])

    def should_save_data(self) -> bool:
        if self.raw_response and self.raw_response.status_code == 204:
            return False
        return bool(self.data.get("rowCount", 0) > 0)

    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0) if hasattr(self, 'data') else 0,
            "sport": "baseball_mlb",
            "game_date": self.opts.get("game_date"),
            "snapshot": self.data.get("snapshot_timestamp") if hasattr(self, 'data') else None,
        }


create_app = convert_existing_flask_scraper(MlbEventsHistoricalScraper)

if __name__ == "__main__":
    main = MlbEventsHistoricalScraper.create_cli_and_flask_main()
    main()

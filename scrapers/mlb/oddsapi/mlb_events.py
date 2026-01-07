#!/usr/bin/env python3
"""
MLB Odds API Events Scraper

Fetches event IDs from The Odds API for MLB games.
Event IDs are needed to fetch player props and game lines.

Endpoint: GET /v4/sports/baseball_mlb/events

Usage:
  # Get events for a specific date:
  SPORT=mlb python scrapers/mlb/oddsapi/mlb_events.py --game_date 2025-06-15 --group dev

  # Flask service:
  SPORT=mlb python scrapers/mlb/oddsapi/mlb_events.py --serve --debug

Created: 2026-01-06
"""

from __future__ import annotations

import os
import logging
import sys
from datetime import datetime, time
from urllib.parse import urlencode
from typing import Any, Dict, List

# Support both module execution and direct execution
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


class MlbEventsOddsScraper(ScraperBase, ScraperFlaskMixin):
    """
    MLB Events Scraper for The Odds API.

    Fetches all MLB events (games) for a given date.
    Returns event IDs needed for props and game lines scrapers.

    Required opts:
      - game_date: Date to fetch events for (YYYY-MM-DD)

    Optional opts:
      - api_key: Odds API key (falls back to ODDS_API_KEY env var)
      - commenceTimeFrom/commenceTimeTo: Manual UTC time filters
    """

    # Flask Mixin Configuration
    scraper_name = "mlb_events"
    required_params = ["game_date"]
    optional_params = {
        "api_key": None,
        "commenceTimeFrom": None,
        "commenceTimeTo": None,
        "dateFormat": None,
    }

    required_opts: List[str] = ["game_date"]
    proxy_enabled = False
    browser_enabled = False

    # GCS Export Configuration
    GCS_PATH_KEY = "mlb_odds_api_events"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_events_%(game_date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "capture", "test"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        """Convert game_date to API time filters."""
        super().set_additional_opts()

        import pytz

        eastern = pytz.timezone('America/New_York')
        game_date_str = self.opts["game_date"]

        # Parse the game date
        game_date = datetime.strptime(game_date_str, "%Y-%m-%d").date()

        # Create Eastern timezone boundaries
        day_start = eastern.localize(datetime.combine(game_date, time.min))
        day_end = eastern.localize(datetime.combine(game_date, time.max))

        # Convert to UTC for API
        if not self.opts.get("commenceTimeFrom"):
            self.opts["commenceTimeFrom"] = day_start.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not self.opts.get("commenceTimeTo"):
            self.opts["commenceTimeTo"] = day_end.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.info(
            "Game date %s → commence times: %s to %s",
            game_date_str,
            self.opts["commenceTimeFrom"],
            self.opts["commenceTimeTo"]
        )

    # ------------------------------------------------------------------ #
    # URL & headers
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events"

    def set_url(self) -> None:
        api_key = get_api_key(
            secret_name='ODDS_API_KEY',
            default_env_var='ODDS_API_KEY'
        )
        if not api_key:
            raise DownloadDataException("Missing ODDS_API_KEY")

        query: Dict[str, Any] = {
            "apiKey": api_key,
            "commenceTimeFrom": self.opts.get("commenceTimeFrom"),
            "commenceTimeTo": self.opts.get("commenceTimeTo"),
            "dateFormat": self.opts.get("dateFormat"),
        }
        query = {k: v for k, v in query.items() if v is not None}
        self.url = f"{self._API_ROOT}?{urlencode(query, doseq=True)}"
        logger.info("MLB Events URL: %s", self.url.replace(api_key, "***"))

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            raise DownloadDataException(f"API error: {self.decoded_data['message']}")

        if not isinstance(self.decoded_data, list):
            raise DownloadDataException("Expected a list of events.")

    # ------------------------------------------------------------------ #
    # Transform
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        events: List[Dict[str, Any]] = self.decoded_data
        events.sort(key=lambda e: e.get("commence_time", ""))

        # Extract team info for easier processing
        for event in events:
            event["_home_team"] = event.get("home_team", "")
            event["_away_team"] = event.get("away_team", "")

        self.data = {
            "sport": "baseball_mlb",
            "game_date": self.opts.get("game_date"),
            "rowCount": len(events),
            "events": events,
        }

        if len(events) == 0:
            notify_warning(
                title="No MLB Events Available",
                message=f"No games found for {self.opts.get('game_date')}",
                details={
                    'scraper': 'mlb_events',
                    'game_date': self.opts.get('game_date'),
                }
            )
        else:
            notify_info(
                title="MLB Events Retrieved",
                message=f"Found {len(events)} MLB games",
                details={
                    'scraper': 'mlb_events',
                    'game_date': self.opts.get('game_date'),
                    'event_count': len(events),
                    'matchups': [f"{e.get('away_team')} @ {e.get('home_team')}" for e in events[:5]]
                }
            )

        logger.info("Fetched %d MLB events for %s", len(events), self.opts.get("game_date"))

    def should_save_data(self) -> bool:
        return bool(self.data.get("rowCount"))

    def get_scraper_stats(self) -> dict:
        event_ids = []
        if hasattr(self, 'data') and isinstance(self.data, dict):
            events = self.data.get("events", [])
            event_ids = [e.get("id") for e in events if e.get("id")]

        return {
            "rowCount": self.data.get("rowCount", 0) if hasattr(self, 'data') else 0,
            "sport": "baseball_mlb",
            "game_date": self.opts.get("game_date"),
            "event_ids": event_ids,
        }


# Flask and CLI entry points
create_app = convert_existing_flask_scraper(MlbEventsOddsScraper)

if __name__ == "__main__":
    main = MlbEventsOddsScraper.create_cli_and_flask_main()
    main()

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
  # Get events for a specific game date (auto-calculates Eastern day boundaries):
  python scrapers/oddsapi/oddsa_events.py \
      --sport basketball_nba \
      --game_date 2025-10-21 \
      --debug

  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py oddsa_events \
      --sport basketball_nba \
      --game_date 2025-10-21 \
      --debug

  # Manual time filtering (overrides game_date auto-calculation):
  python scrapers/oddsapi/oddsa_events.py \
      --sport basketball_nba \
      --game_date 2025-10-21 \
      --commenceTimeFrom 2025-10-21T00:00:00Z \
      --commenceTimeTo 2025-10-21T23:59:59Z \
      --debug

  # Flask web service:
  python scrapers/oddsapi/oddsa_events.py --serve --debug
"""

from __future__ import annotations

import os
import logging
import sys
from datetime import datetime, time
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

# Notification system imports
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Authentication utilities
from shared.utils.auth_utils import get_api_key

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class GetOddsApiEvents(ScraperBase, ScraperFlaskMixin):
    """
    Required opts:
      • sport - e.g. basketball_nba
      • game_date - Eastern date (e.g., "2025-10-21") - auto-calculates commence times

    Optional opts (all map 1-to-1 onto query params):
      • api_key  - falls back to env ODDS_API_KEY
      • commenceTimeFrom / commenceTimeTo - manual UTC time filters (override game_date)
      • dateFormat
    """

    # Flask Mixin Configuration
    scraper_name = "oddsa_events"
    required_params = ["sport", "game_date"]
    optional_params = {
        "api_key": None,  # Falls back to env ODDS_API_KEY
        "commenceTimeFrom": None,
        "commenceTimeTo": None,
        "dateFormat": None,
    }

    required_opts: List[str] = ["sport", "game_date"]  # api_key via env if omitted
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
    # Additional opts                                                    #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        """
        Convert game_date to API time filters.
        Matches pattern from historical events scraper.
        """
        # Call base class first for standard processing
        super().set_additional_opts()  # Base class handles game_date → date conversion
        
        # Calculate commence time boundaries (Eastern day → UTC)
        import pytz
        
        eastern = pytz.timezone('America/New_York')
        game_date_str = self.opts["game_date"]
        
        # Parse the game date (YYYY-MM-DD)
        game_date = datetime.strptime(game_date_str, "%Y-%m-%d").date()
        
        # Create Eastern timezone boundaries for the day
        day_start = eastern.localize(datetime.combine(game_date, time.min))  # 00:00:00 ET
        day_end = eastern.localize(datetime.combine(game_date, time.max))    # 23:59:59.999999 ET
        
        # Convert to UTC for API (only if not already set by user)
        if not self.opts.get("commenceTimeFrom"):
            self.opts["commenceTimeFrom"] = day_start.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not self.opts.get("commenceTimeTo"):
            self.opts["commenceTimeTo"] = day_end.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        logger.info(
            "Game date %s → commence times: %s to %s (ET day → UTC)",
            game_date_str,
            self.opts["commenceTimeFrom"],
            self.opts["commenceTimeTo"]
        )

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT_TMPL = "https://api.the-odds-api.com/v4/sports/{sport}/events"

    def set_url(self) -> None:
        # Get API key from Secret Manager (with env var fallback for local dev)
        api_key = get_api_key(
            secret_name='ODDS_API_KEY',
            default_env_var='ODDS_API_KEY'
        )
        if not api_key:
            error_msg = "Missing api_key and env var ODDS_API_KEY not set."
            
            # Send critical notification - API key missing prevents all scraping
            try:
                notify_error(
                    title="Odds API Key Missing",
                    message="Cannot scrape events - API key not configured",
                    details={
                        'scraper': 'oddsa_events',
                        'sport': self.opts.get('sport', 'unknown'),
                        'game_date': self.opts.get('game_date', 'not specified'),
                        'error': 'ODDS_API_KEY environment variable not set'
                    },
                    processor_name="Odds API Events Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise DownloadDataException(error_msg)

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
        logger.info("Odds-API Events URL: %s", self.url.replace(api_key, "***"))

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}

    # ------------------------------------------------------------------ #
    # HTTP status handling                                               #
    # ------------------------------------------------------------------ #
    def check_download_status(self) -> None:
        """Handle HTTP errors with notifications."""
        if self.raw_response.status_code == 200:
            return
        
        # Non-success status code - send error notification
        status_code = self.raw_response.status_code
        try:
            notify_error(
                title="Odds API HTTP Error",
                message=f"Events scraping failed with HTTP {status_code}",
                details={
                    'scraper': 'oddsa_events',
                    'sport': self.opts.get('sport', 'unknown'),
                    'game_date': self.opts.get('game_date', 'not specified'),
                    'status_code': status_code,
                    'commence_time_from': self.opts.get('commenceTimeFrom', 'not specified'),
                    'commence_time_to': self.opts.get('commenceTimeTo', 'not specified'),
                    'response_text': self.raw_response.text[:500] if hasattr(self.raw_response, 'text') else 'N/A'
                },
                processor_name="Odds API Events Scraper"
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")
        
        super().check_download_status()

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """
        Expect a *list* of events.  Handle API error messages.
        """
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            error_msg = self.decoded_data['message']
            
            # API returned an error message
            try:
                notify_error(
                    title="Odds API Error Response",
                    message=f"Events API returned error: {error_msg}",
                    details={
                        'scraper': 'oddsa_events',
                        'sport': self.opts.get('sport', 'unknown'),
                        'game_date': self.opts.get('game_date', 'not specified'),
                        'api_error': error_msg
                    },
                    processor_name="Odds API Events Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise DownloadDataException(f"API error: {error_msg}")

        if not isinstance(self.decoded_data, list):
            # Unexpected data format
            try:
                notify_error(
                    title="Odds API Invalid Response Format",
                    message="Events API returned unexpected data format",
                    details={
                        'scraper': 'oddsa_events',
                        'sport': self.opts.get('sport', 'unknown'),
                        'game_date': self.opts.get('game_date', 'not specified'),
                        'received_type': type(self.decoded_data).__name__,
                        'expected_type': 'list'
                    },
                    processor_name="Odds API Events Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise DownloadDataException("Expected a list of events.")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        events: List[Dict[str, Any]] = self.decoded_data  # type: ignore[assignment]
        events.sort(key=lambda e: e.get("commence_time", ""))

        self.data = {
            "sport": self.opts["sport"],
            "game_date": self.opts.get("game_date"),  # Include game_date if provided
            "rowCount": len(events),
            "events": events,
        }
        
        # Check for no events — only warn if regular-season games were expected (Session 299)
        if len(events) == 0:
            game_date_str = self.opts.get('game_date', 'unknown')
            from shared.utils.schedule_guard import has_regular_season_games
            games_expected = game_date_str == 'unknown' or has_regular_season_games(game_date_str)
            if games_expected:
                try:
                    notify_warning(
                        title="No Events Available",
                        message="Odds API returned zero events",
                        details={
                            'scraper': 'oddsa_events',
                            'sport': self.opts.get('sport', 'unknown'),
                            'game_date': game_date_str,
                            'commence_time_from': self.opts.get('commenceTimeFrom', 'not specified'),
                            'commence_time_to': self.opts.get('commenceTimeTo', 'not specified'),
                            'note': 'May be expected if no games scheduled in specified time range'
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            else:
                logger.info("No events for %s — confirmed no games scheduled (break day)", game_date_str)
        else:
            # Success! Send info notification with metrics
            try:
                # Extract earliest and latest commence times for context
                earliest_time = events[0].get("commence_time", "unknown") if events else "unknown"
                latest_time = events[-1].get("commence_time", "unknown") if events else "unknown"
                
                notify_info(
                    title="Events Scraped Successfully",
                    message=f"Retrieved {len(events)} events from Odds API",
                    details={
                        'scraper': 'oddsa_events',
                        'sport': self.opts.get('sport', 'unknown'),
                        'game_date': self.opts.get('game_date', 'not specified'),
                        'event_count': len(events),
                        'earliest_commence_time': earliest_time,
                        'latest_commence_time': latest_time,
                        'commence_time_from': self.opts.get('commenceTimeFrom', 'not specified'),
                        'commence_time_to': self.opts.get('commenceTimeTo', 'not specified')
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        
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
        """
        Return stats including event_ids for workflow orchestration.

        Event IDs are needed by downstream scrapers (oddsa_player_props, oddsa_game_lines)
        so we include them in the stats that get returned via HTTP response.
        """
        # Extract event IDs from events list (with safe handling)
        event_ids = []
        if hasattr(self, 'data') and isinstance(self.data, dict):
            events = self.data.get("events", [])
            if isinstance(events, list):
                event_ids = [event.get("id") for event in events if isinstance(event, dict) and event.get("id")]

        return {
            "rowCount": self.data.get("rowCount", 0) if hasattr(self, 'data') and isinstance(self.data, dict) else 0,
            "sport": self.opts.get("sport"),
            "game_date": self.opts.get("game_date"),
            "event_ids": event_ids,  # Include for workflow orchestration
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
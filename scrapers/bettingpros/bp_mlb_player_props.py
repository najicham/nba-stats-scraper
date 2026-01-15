# scrapers/bettingpros/bp_mlb_player_props.py
"""
BettingPros MLB Player Props API scraper                     v2 - 2026-01-14
------------------------------------------------------------------------
Gets player prop betting data for MLB player props from BettingPros API.
Inherits from NBA scraper and overrides MLB-specific settings.

URL: https://api.bettingpros.com/v3/offers?sport=MLB&market_id=XXX&event_id=...

NOTE: MLB market IDs need to be discovered when season is active. The NBA ones are:
  156: points, 157: rebounds, 151: assists, 162: threes, 160: steals, 152: blocks

For MLB, likely markets include (IDs are placeholders until discovery):
  - pitcher_strikeouts (200) - PRIMARY for pitcher strikeouts project
  - pitcher_outs (201)
  - batter_hits (210)
  - batter_home_runs (211)
  - etc.

Usage examples
--------------
  # With specific event IDs:
  python scrapers/bettingpros/bp_mlb_player_props.py --event_ids "12345,12346" --debug

  # With date (auto-fetches MLB events):
  python scrapers/bettingpros/bp_mlb_player_props.py --date 2025-06-15 --debug

  # Different prop types (once market IDs are discovered):
  python scrapers/bettingpros/bp_mlb_player_props.py --date 2025-06-15 --market_type pitcher_strikeouts --debug

  # Test with dev group (local files):
  python scrapers/bettingpros/bp_mlb_player_props.py --date 2025-06-15 --group dev

  # Discover MLB market IDs (when season active):
  python scrapers/bettingpros/bp_mlb_player_props.py --discover-markets --date 2025-06-15

Market ID Discovery:
  When MLB season is active, use discover_mlb_market_ids.py script:
  python scripts/mlb/setup/discover_mlb_market_ids.py --date 2025-06-15
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Optional

# Support both module execution and direct execution
try:
    from .bp_player_props import BettingProsPlayerProps, BOOKS
    from .bp_events import BettingProsEvents
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.bettingpros.bp_player_props import BettingProsPlayerProps, BOOKS
    from scrapers.bettingpros.bp_events import BettingProsEvents

# Notification system imports
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger("scraper_base")

# MLB market IDs - DISCOVERED from FantasyPros/BettingPros API (2026-01-14)
# API endpoint: https://api.bettingpros.com/v3/props?sport=MLB&market_id=XXX
# Note: Uses /v3/props endpoint (not /v3/offers) with FantasyPros origin
MLB_MARKETS = {
    # Pitcher props
    285: 'pitcher-strikeouts',   # PRIMARY - for pitcher strikeouts project
    # Batter props
    287: 'batter-hits',
    288: 'batter-runs',
    289: 'batter-rbis',
    291: 'batter-doubles',
    292: 'batter-triples',
    293: 'batter-total-bases',
    294: 'batter-stolen-bases',
    295: 'batter-singles',
    299: 'batter-home-runs',
}

MLB_MARKET_ID_BY_KEYWORD = {
    # Pitcher props
    'pitcher_strikeouts': 285,   # PRIMARY - for pitcher strikeouts project
    'strikeouts': 285,           # Alias
    # Batter props
    'batter_hits': 287,
    'hits': 287,                 # Alias
    'batter_runs': 288,
    'runs': 288,                 # Alias
    'batter_rbis': 289,
    'rbis': 289,                 # Alias
    'batter_doubles': 291,
    'doubles': 291,              # Alias
    'batter_triples': 292,
    'triples': 292,              # Alias
    'batter_total_bases': 293,
    'total_bases': 293,          # Alias
    'batter_stolen_bases': 294,
    'stolen_bases': 294,         # Alias
    'steals': 294,               # Alias
    'batter_singles': 295,
    'singles': 295,              # Alias
    'batter_home_runs': 299,
    'home_runs': 299,            # Alias
    'homeruns': 299,             # Alias
}


class BettingProsMLBPlayerProps(BettingProsPlayerProps):
    """
    BettingPros MLB Player Props API scraper.

    Inherits from NBA scraper and overrides MLB-specific settings.
    Uses the same BettingProsEvents scraper with sport="MLB" to fetch event IDs.

    Required opts (one of):
        event_ids: Comma-separated list of event IDs
        date: Date in YYYY-MM-DD format (will fetch MLB events first)

    Optional opts:
        market_type: Type of prop (see MLB_MARKET_ID_BY_KEYWORD)
    """

    scraper_name = "bp_mlb_player_props"

    optional_params = {
        "event_ids": None,
        "date": None,
        "sport": "MLB",  # Override to MLB
        "market_type": "pitcher_strikeouts",  # Default for MLB pitcher strikeouts project
        "page_limit": 10,
    }

    # GCS path for MLB props
    GCS_PATH_KEY = "bettingpros_mlb_player_props"

    # Use /v3/props endpoint (discovered via FantasyPros)
    # This endpoint supports event_id=ALL and returns more data
    BASE_URL = "https://api.bettingpros.com/v3/props"

    # FantasyPros origin required for this endpoint
    FANTASYPROS_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Origin': 'https://www.fantasypros.com',
        'Referer': 'https://www.fantasypros.com/',
    }

    # Retry settings for fetching MLB events (same as parent but separate for clarity)
    MLB_EVENTS_FETCH_MAX_RETRIES = 3
    MLB_EVENTS_FETCH_BACKOFF_BASE = 15  # seconds: 15, 30, 60

    # MLB-specific exporters (override parent's NBA exporters)
    exporters = [
        # ========== PRODUCTION GCS ==========
        {
            "type": "gcs",
            "key": "bettingpros-mlb-player-props/%(date)s/%(market_type)s/props.json",
            "export_mode": "DATA",
            "groups": ["prod", "gcs"],
        },

        # ========== DEVELOPMENT FILES ==========
        {
            "type": "file",
            "filename": "/tmp/bp_mlb_player_props_%(market_type)s_%(date)s.json",
            "export_mode": "DATA",
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "file",
            "filename": "/tmp/bp_mlb_player_props_%(market_type)s_raw_%(date)s.json",
            "export_mode": "RAW",
            "pretty_print": True,
            "groups": ["dev", "test"],
        },

        # ========== CAPTURE GROUP ==========
        {
            "type": "file",
            "filename": "/tmp/mlb_raw_%(run_id)s.json",
            "export_mode": "RAW",
            "groups": ["capture"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_exp_%(run_id)s.json",
            "export_mode": "DECODED",
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    def set_additional_opts(self) -> None:
        """Override to use MLB market mappings and MLB events fetcher."""
        # Set sport to MLB before any processing
        self.opts["sport"] = "MLB"

        # If date provided, fetch MLB event IDs first
        if self.opts.get("date") and not self.opts.get("event_ids"):
            self._fetch_mlb_event_ids_from_date()

        # If using event_ids without date, set a reasonable date for filenames
        if self.opts.get("event_ids") and not self.opts.get("date"):
            from datetime import datetime
            self.opts["date"] = datetime.now().strftime("%Y-%m-%d")
            logger.info("Set current date for event_ids query: %s", self.opts["date"])

        # Validate event_ids format (same as parent)
        if self.opts.get("event_ids"):
            event_ids = self.opts["event_ids"]
            if isinstance(event_ids, str):
                self.opts["event_ids_list"] = [id.strip() for id in event_ids.split(",") if id.strip()]
            elif isinstance(event_ids, list):
                self.opts["event_ids_list"] = event_ids

            if not self.opts.get("event_ids_list"):
                from scrapers.utils.exceptions import DownloadDataException
                raise DownloadDataException("No valid MLB event IDs found")

        # Convert market_type to market_id using MLB mappings
        market_type = self.opts.get("market_type", "pitcher_strikeouts")
        self.opts["market_type"] = market_type

        if market_type not in MLB_MARKET_ID_BY_KEYWORD:
            valid_markets = ", ".join(MLB_MARKET_ID_BY_KEYWORD.keys())
            logger.warning(f"Unknown MLB market_type: {market_type}. Valid: {valid_markets}")
            # Use pitcher_strikeouts as default placeholder
            self.opts["market_id"] = MLB_MARKET_ID_BY_KEYWORD.get("pitcher_strikeouts", 200)
            self.opts["market_name"] = market_type
        else:
            self.opts["market_id"] = MLB_MARKET_ID_BY_KEYWORD[market_type]
            self.opts["market_name"] = MLB_MARKETS.get(self.opts["market_id"], market_type)

        logger.info("BettingPros MLB Props for %d events, sport: %s, market: %s (ID: %s)",
                len(self.opts.get("event_ids_list", [])),
                self.opts["sport"],
                market_type,
                self.opts["market_id"])

    def set_url(self) -> None:
        """
        Build the /v3/props API URL (different from parent's /v3/offers).

        The /v3/props endpoint discovered via FantasyPros supports:
        - event_id=ALL to get all events at once
        - Better data structure with include_events, include_markets, include_books
        """
        # Build query parameters for /v3/props endpoint
        params = {
            "sport": self.opts["sport"],
            "market_id": str(self.opts["market_id"]),
            "limit": str(self.opts.get("page_limit", 25)),
            "include_events": "true",
            "include_markets": "true",
            "include_books": "true",
            "include_selections": "true",  # Need selection details for lines
        }

        # Use event_id=ALL if no specific events, otherwise use the list
        if self.opts.get("event_ids_list"):
            # Can pass multiple event IDs - API accepts comma-separated or colon-separated
            params["event_id"] = ",".join(self.opts["event_ids_list"])
        else:
            params["event_id"] = "ALL"

        # Add date if specified (for filtering)
        if self.opts.get("date"):
            params["date"] = self.opts["date"]

        # Build query string
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        self.url = f"{self.BASE_URL}?{query_string}"

        logger.info("BettingPros MLB Props URL: %s", self.url)

    def set_http_downloader(self) -> None:
        """Override to use FantasyPros headers for the /v3/props endpoint."""
        super().set_http_downloader()
        # Apply FantasyPros-specific headers
        if hasattr(self, 'http_session') and self.http_session:
            self.http_session.headers.update(self.FANTASYPROS_HEADERS)
        logger.debug("Applied FantasyPros headers for MLB props API")

    def _fetch_mlb_event_ids_from_date(self) -> None:
        """
        Fetch MLB event IDs using the BettingProsEvents scraper with sport="MLB".

        Retries up to MLB_EVENTS_FETCH_MAX_RETRIES times with exponential backoff
        (15s, 30s, 60s delays) to handle transient proxy/API failures.

        This is the MLB-specific implementation that calls the same events scraper
        but with sport="MLB" instead of "NBA".
        """
        date = self.opts["date"]
        logger.info("Fetching MLB event IDs for date: %s", date)

        last_exception = None

        for attempt in range(1, self.MLB_EVENTS_FETCH_MAX_RETRIES + 1):
            try:
                # Create fresh events scraper for each attempt
                events_scraper = BettingProsEvents()
                events_opts = {
                    "date": date,
                    "sport": "MLB",  # KEY DIFFERENCE: use MLB instead of NBA
                    "group": "capture",  # Use capture group to avoid GCS exports
                    "run_id": f"{self.run_id}_mlb_events_attempt{attempt}"
                }

                events_result = events_scraper.run(events_opts)

                if events_result and hasattr(events_scraper, 'data') and 'events' in events_scraper.data:
                    event_ids = list(events_scraper.data['events'].keys())
                    if event_ids:
                        self.opts["event_ids"] = ",".join(event_ids)
                        logger.info("Fetched %d MLB event IDs from date %s (attempt %d): %s...",
                                   len(event_ids), date, attempt, event_ids[:3])

                        # Success notification
                        try:
                            notify_info(
                                title="MLB Events Fetched",
                                message=f"Retrieved {len(event_ids)} MLB events for {date}",
                                details={
                                    'scraper': 'bp_mlb_player_props',
                                    'date': date,
                                    'event_count': len(event_ids),
                                    'attempt': attempt,
                                    'event_ids_preview': event_ids[:5]
                                }
                            )
                        except Exception as notify_ex:
                            logger.warning(f"Failed to send notification: {notify_ex}")

                        return  # Success!

                # No events in response - could be no MLB games that day or API issue
                logger.warning("No MLB events in response for date %s (attempt %d/%d)",
                              date, attempt, self.MLB_EVENTS_FETCH_MAX_RETRIES)

                from scrapers.utils.exceptions import DownloadDataException
                last_exception = DownloadDataException(f"No MLB events found for date: {date}")

            except Exception as e:
                logger.warning("MLB events fetch failed for date %s (attempt %d/%d): %s",
                              date, attempt, self.MLB_EVENTS_FETCH_MAX_RETRIES, str(e))
                last_exception = e

            # Calculate backoff: 15 * 2^(attempt-1) = 15, 30, 60 seconds
            if attempt < self.MLB_EVENTS_FETCH_MAX_RETRIES:
                backoff = self.MLB_EVENTS_FETCH_BACKOFF_BASE * (2 ** (attempt - 1))
                logger.info("Retrying MLB events fetch in %d seconds...", backoff)
                time.sleep(backoff)

        # All retries exhausted - send notification and raise
        try:
            notify_error(
                title="MLB Events Fetch Failed After Retries",
                message=f"Failed to fetch MLB events for date {date} after {self.MLB_EVENTS_FETCH_MAX_RETRIES} attempts",
                details={
                    'scraper': 'bp_mlb_player_props',
                    'date': date,
                    'sport': 'MLB',
                    'max_retries': self.MLB_EVENTS_FETCH_MAX_RETRIES,
                    'error': str(last_exception),
                    'error_type': type(last_exception).__name__ if last_exception else 'Unknown',
                    'note': 'May be off-season or no MLB games scheduled'
                },
                processor_name="BettingPros MLB Player Props Scraper"
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")

        from scrapers.utils.exceptions import DownloadDataException
        raise DownloadDataException(
            f"Failed to fetch MLB events for date {date} after {self.MLB_EVENTS_FETCH_MAX_RETRIES} retries: {last_exception}"
        )


# --------------------------------------------------------------------------- #
# Flask and CLI entry points
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    main = BettingProsMLBPlayerProps.create_cli_and_flask_main()
    main()

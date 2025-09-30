# scrapers/bettingpros/bp_events.py
"""
BettingPros Events API scraper                           v1 - 2025-08-12
------------------------------------------------------------------------
Gets event IDs and basic game info for a given date from BettingPros API.

URL: https://api.bettingpros.com/v3/events?sport=NBA&date=YYYY-MM-DD

Usage examples
--------------
  # Direct CLI execution:
  python scrapers/bettingpros/bp_events.py --date 2021-10-21 --debug

  # Flask web service:
  python scrapers/bettingpros/bp_events.py --serve --debug

  # Test with dev group (local files):
  python scrapers/bettingpros/bp_events.py --date 2021-10-21 --group dev

  python tools/fixtures/capture.py bp_events \
      --date 2021-10-21 \
      --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.bettingpros.bp_events
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/bettingpros/bp_events.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
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

logger = logging.getLogger("scraper_base")


class BettingProsEvents(ScraperBase, ScraperFlaskMixin):
    """
    BettingPros Events API scraper.
    
    Required opts:
        date: Date in YYYY-MM-DD format (e.g., 2021-10-21)
    """

    # Flask Mixin Configuration
    scraper_name = "bp_events"
    required_params = ["date"]
    optional_params = {
        "sport": "NBA",
    }
    
    required_opts = ["date"]
    download_type = DownloadType.JSON
    decode_download_data = True
    header_profile = "bettingpros"  # Use BettingPros headers from nba_header_utils
    proxy_enabled = True      # BettingPros may need proxy for high volume
    
    # Rate limiting: Add delay between requests to be respectful
    # We'll implement this in a custom method
    RATE_LIMIT_DELAY = 2.0  # 2 seconds between requests
    
    BASE_URL = "https://api.bettingpros.com/v3/events"

    # GCS path keys for organized storage
    GCS_PATH_KEY = "bettingpros_events"

    exporters = [
        # ========== PRODUCTION GCS ==========
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        
        # ========== DEVELOPMENT FILES ==========
        {
            "type": "file",
            "filename": "/tmp/bp_events_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "file",
            "filename": "/tmp/bp_events_raw_%(date)s.json",
            "export_mode": ExportMode.RAW,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        
        # ========== CAPTURE GROUP ==========
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "export_mode": ExportMode.DECODED,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]
    
    def set_additional_opts(self) -> None:
        """Add standard opts and validate date format"""
        super().set_additional_opts()
        
        # Validate date format (YYYY-MM-DD)
        date_str = self.opts["date"]
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            error_msg = f"Invalid date format: {date_str}. Use YYYY-MM-DD"
            
            # Invalid date format notification
            try:
                notify_error(
                    title="Invalid Date Format",
                    message=f"Date format invalid: {date_str}",
                    details={
                        'scraper': 'bp_events',
                        'date': date_str,
                        'expected_format': 'YYYY-MM-DD',
                        'error': 'Date validation failed'
                    },
                    processor_name="BettingPros Events Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise DownloadDataException(error_msg)
        
        # Set sport default
        if "sport" not in self.opts:
            self.opts["sport"] = "NBA"
            
        logger.info("BettingPros Events for date: %s, sport: %s", 
                   self.opts["date"], self.opts["sport"])
    
    def set_url(self) -> None:
        """Build the BettingPros events API URL"""
        params = {
            "sport": self.opts["sport"],
            "date": self.opts["date"],
        }
        
        # Build query string
        query_params = []
        for key, value in params.items():
            query_params.append(f"{key}={value}")
        
        query_string = "&".join(query_params)
        self.url = f"{self.BASE_URL}?{query_string}"
        
        logger.info("BettingPros Events URL: %s", self.url)
    
    def download_data(self):
        """Override to add rate limiting delay"""
        import time
        
        # Add rate limiting delay before request
        logger.info("Rate limiting: sleeping %.1f seconds before request", self.RATE_LIMIT_DELAY)
        time.sleep(self.RATE_LIMIT_DELAY)
        
        # Call parent download method
        super().download_data()
    
    def check_download_status(self) -> None:
        """Handle HTTP errors with notifications."""
        if self.raw_response.status_code == 200:
            return
        
        # Non-success status code - send error notification
        status_code = self.raw_response.status_code
        try:
            notify_error(
                title="BettingPros API HTTP Error",
                message=f"Events scraping failed with HTTP {status_code}",
                details={
                    'scraper': 'bp_events',
                    'date': self.opts.get('date', 'unknown'),
                    'sport': self.opts.get('sport', 'NBA'),
                    'status_code': status_code,
                    'response_text': self.raw_response.text[:500] if hasattr(self.raw_response, 'text') else 'N/A'
                },
                processor_name="BettingPros Events Scraper"
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")
        
        super().check_download_status()
    
    def validate_download_data(self) -> None:
        """Validate the BettingPros API response"""
        if not isinstance(self.decoded_data, dict):
            # Invalid response format
            try:
                notify_error(
                    title="Invalid Response Format",
                    message="BettingPros events API returned unexpected data format",
                    details={
                        'scraper': 'bp_events',
                        'date': self.opts.get('date', 'unknown'),
                        'sport': self.opts.get('sport', 'NBA'),
                        'received_type': type(self.decoded_data).__name__,
                        'expected_type': 'dict'
                    },
                    processor_name="BettingPros Events Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise DownloadDataException("Response is not a JSON object")
        
        if "events" not in self.decoded_data:
            # Missing events key
            try:
                notify_error(
                    title="Missing Events in Response",
                    message="BettingPros API response missing 'events' key",
                    details={
                        'scraper': 'bp_events',
                        'date': self.opts.get('date', 'unknown'),
                        'sport': self.opts.get('sport', 'NBA'),
                        'response_keys': list(self.decoded_data.keys())
                    },
                    processor_name="BettingPros Events Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise DownloadDataException("Missing 'events' in response")
        
        events = self.decoded_data["events"]
        if not isinstance(events, list):
            # Events not a list
            try:
                notify_error(
                    title="Invalid Events Format",
                    message="BettingPros API 'events' is not a list",
                    details={
                        'scraper': 'bp_events',
                        'date': self.opts.get('date', 'unknown'),
                        'sport': self.opts.get('sport', 'NBA'),
                        'events_type': type(events).__name__
                    },
                    processor_name="BettingPros Events Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise DownloadDataException("'events' is not a list")
        
        # Check for _parameters to ensure we got the right response
        if "_parameters" in self.decoded_data:
            params = self.decoded_data["_parameters"]
            if params.get("sport") != self.opts["sport"]:
                logger.warning("Response sport (%s) differs from requested (%s)", 
                             params.get("sport"), self.opts["sport"])
                
                # Warning for sport mismatch
                try:
                    notify_warning(
                        title="Response Parameter Mismatch",
                        message="API returned different sport than requested",
                        details={
                            'scraper': 'bp_events',
                            'date': self.opts.get('date', 'unknown'),
                            'requested_sport': self.opts["sport"],
                            'response_sport': params.get("sport"),
                            'event_count': len(events)
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                    
            if params.get("date") != self.opts["date"]:
                logger.warning("Response date (%s) differs from requested (%s)", 
                             params.get("date"), self.opts["date"])
                
                # Warning for date mismatch
                try:
                    notify_warning(
                        title="Response Parameter Mismatch",
                        message="API returned different date than requested",
                        details={
                            'scraper': 'bp_events',
                            'requested_date': self.opts["date"],
                            'response_date': params.get("date"),
                            'requested_sport': self.opts["sport"],
                            'event_count': len(events)
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
        
        # Check for no events
        if len(events) == 0:
            try:
                notify_warning(
                    title="No Events Available",
                    message="BettingPros API returned zero events for date",
                    details={
                        'scraper': 'bp_events',
                        'date': self.opts.get('date', 'unknown'),
                        'sport': self.opts.get('sport', 'NBA'),
                        'note': 'May be expected if no games scheduled for this date'
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        
        logger.info("Validation passed: %d events found for %s", 
                   len(events), self.opts["date"])

    def transform_data(self) -> None:
        """Transform BettingPros events data into structured format"""
        events_data = self.decoded_data["events"]
        
        # Extract useful event information
        processed_events = {}
        game_summary = []

        for event in events_data:
            event_id = str(event.get("id"))
            home_team = event.get("home", "")
            away_team = event.get("visitor", "")  # BettingPros uses "visitor" not "away"
            
            # Basic event info - now including lineups and other fields
            event_info = {
                "id": event_id,
                "sr_id": event.get("sr_id"),
                "home": home_team,
                "away": away_team,
                "sport": event.get("sport"),
                "scheduled": event.get("scheduled"),
                "season": event.get("season"),
                "season_type": event.get("season_type"),
                "status": event.get("status"),
                "event_name": event.get("event_name"),
                "link": event.get("link"),
                "series_summary": event.get("series_summary"),
                "venue": event.get("venue", {}),
                "popularity": event.get("popularity", 0),
            }
            
            processed_events[event_id] = event_info
            
            # Summary for logging
            game_summary.append(f"{away_team}@{home_team}")
        
        # Store processed data
        self.data = {
            "date": self.opts["date"],
            "sport": self.opts["sport"],
            "timestamp": self.opts["timestamp"],
            "source": "bettingpros_api",
            "api_response_params": self.decoded_data.get("_parameters", {}),
            "event_count": len(processed_events),
            "events": processed_events,
            # "raw_events": events_data,  # Keep original data for debugging
        }
        
        # Success notification
        if len(processed_events) > 0:
            try:
                notify_info(
                    title="Events Scraped Successfully",
                    message=f"Retrieved {len(processed_events)} events from BettingPros",
                    details={
                        'scraper': 'bp_events',
                        'date': self.opts.get('date', 'unknown'),
                        'sport': self.opts.get('sport', 'NBA'),
                        'event_count': len(processed_events),
                        'games_preview': game_summary[:5],
                        'total_games': len(game_summary)
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        
        logger.info("Processed %d events for %s: %s", 
                len(processed_events), self.opts["date"], 
                ", ".join(game_summary[:5]) + ("..." if len(game_summary) > 5 else ""))
    
    def get_scraper_stats(self) -> dict:
        """Return scraper statistics"""
        return {
            "date": self.opts["date"],
            "sport": self.opts["sport"],
            "event_count": self.data.get("event_count", 0),
            "timestamp": self.opts["timestamp"]
        }


# --------------------------------------------------------------------------- #
# Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BettingProsEvents)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BettingProsEvents.create_cli_and_flask_main()
    main()
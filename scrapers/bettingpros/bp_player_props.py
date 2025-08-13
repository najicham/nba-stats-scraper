# scrapers/bettingpros/bp_player_props.py
"""
BettingPros Player Props API scraper                     v1 - 2025-08-12
------------------------------------------------------------------------
Gets player prop betting data for NBA player props from BettingPros API.
Handles pagination and processes complex prop bet structures.

URL: https://api.bettingpros.com/v3/offers?sport=NBA&market_id=156&event_id=...

Usage examples
--------------
  # With specific event IDs (points props):
  python scrapers/bettingpros/bp_player_props.py --event_ids "20879,20880,20881" --debug

  # With date (will fetch events first):
  python scrapers/bettingpros/bp_player_props.py --date 2021-10-21 --debug

  # Different prop types:
  python scrapers/bettingpros/bp_player_props.py --date 2021-10-21 --market_type rebounds --debug
  python scrapers/bettingpros/bp_player_props.py --date 2021-10-21 --market_type assists --debug

  # Flask web service:
  python scrapers/bettingpros/bp_player_props.py --serve --debug

  # Test with dev group (local files):
  python scrapers/bettingpros/bp_player_props.py --date 2021-10-21 --group dev
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.bettingpros.bp_player_props
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
    from .bp_events import BettingProsEvents  # To fetch events if needed
except ImportError:
    # Direct execution: python scrapers/bettingpros/bp_player_props.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder
    # Import bp_events for fetching events if needed
    sys.path.insert(0, os.path.dirname(__file__))
    from bp_events import BettingProsEvents

logger = logging.getLogger("scraper_base")

# BettingPros API Mappings (from original research)
MARKETS = {
    156: 'points-by-player',
    157: 'rebounds-by-player', 
    151: 'assists-by-player',
    162: 'threes-by-player',
    160: 'steals-by-player',
    152: 'blocks-by-player',
}

MARKET_ID_BY_KEYWORD = {
    'points': 156,
    'rebounds': 157,
    'assists': 151,
    'threes': 162,
    'steals': 160,
    'blocks': 152,
}

# Sportsbooks available via BettingPros API  
BOOKS = {
    0: "BettingPros Consensus",
    19: "BetMGM",
    27: "PartyCasino", 
    10: "FanDuel",
    12: "DraftKings",
    20: "FOX Bet",
    14: "PointsBet",
    13: "Caesars",
    15: "SugarHouse",
    18: "BetRivers",
    28: "UniBet",
    21: "BetAmerica",
    29: "TwinSpires",
    22: "Oregon Lottery",
    24: "bet365",
    25: "WynnBET",
    26: "Tipico", 
    30: "Betway",
    31: "Fubo",
}


class BettingProsPlayerProps(ScraperBase, ScraperFlaskMixin):
    """
    BettingPros Player Props API scraper for NBA player props.
    
    Required opts (one of):
        event_ids: Comma-separated list of event IDs (e.g., "20879,20880,20881")
        date: Date in YYYY-MM-DD format (will fetch events first)
    
    Optional opts:
        market_type: Type of prop ('points', 'rebounds', 'assists', 'threes', 'steals', 'blocks')
    """

    # Flask Mixin Configuration
    scraper_name = "bp_player_props"
    required_params = []  # We'll validate in validate_opts since we need either event_ids OR date
    optional_params = {
        "event_ids": None,
        "date": None,
        "sport": "NBA",
        "market_type": "points",  # Default to points, can be rebounds, assists, etc.
        "page_limit": 10,  # API maximum is 10 items per page
    }
    
    required_opts = []  # We'll validate event_ids or date manually
    download_type = DownloadType.JSON
    decode_download_data = True
    header_profile = "bettingpros"  # Use BettingPros headers from nba_header_utils
    proxy_enabled = True
    
    # Rate limiting: More conservative for paginated requests
    RATE_LIMIT_DELAY = 2.5  # 2.5 seconds between requests
    
    BASE_URL = "https://api.bettingpros.com/v3/offers"

    # GCS path keys
    GCS_PATH_KEY = "bettingpros_player_props"

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
            "filename": "/tmp/bp_player_props_%(market_type)s_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "file",
            "filename": "/tmp/bp_player_props_%(market_type)s_raw_%(date)s.json",
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
    
    def validate_opts(self) -> None:
        """Custom validation: require either event_ids or date"""
        super().validate_opts()
        
        has_event_ids = self.opts.get("event_ids") is not None
        has_date = self.opts.get("date") is not None
        
        if not has_event_ids and not has_date:
            raise DownloadDataException("Either 'event_ids' or 'date' is required")
        
        if has_event_ids and has_date:
            raise DownloadDataException("Provide either 'event_ids' or 'date', not both")
    
    def set_additional_opts(self) -> None:
        """Fetch events if date provided, validate event_ids format, convert market_type to market_id"""
        super().set_additional_opts()
        
        # If date provided, fetch event IDs first
        if self.opts.get("date"):
            self._fetch_event_ids_from_date()
        
        # If using event_ids without date, set a reasonable date for filenames
        if self.opts.get("event_ids") and not self.opts.get("date"):
            from datetime import datetime
            self.opts["date"] = datetime.now().strftime("%Y-%m-%d")
            logger.info("Set current date for event_ids query: %s", self.opts["date"])
        
        # Validate event_ids format
        if self.opts.get("event_ids"):
            event_ids = self.opts["event_ids"]
            if isinstance(event_ids, str):
                # Convert comma-separated string to list
                self.opts["event_ids_list"] = [id.strip() for id in event_ids.split(",") if id.strip()]
            elif isinstance(event_ids, list):
                self.opts["event_ids_list"] = event_ids
            else:
                raise DownloadDataException("event_ids must be a string or list")
            
            if not self.opts["event_ids_list"]:
                raise DownloadDataException("No valid event IDs found")
        
        # Convert market_type to market_id
        market_type = self.opts.get("market_type", "points")
        self.opts["market_type"] = market_type
        
        if market_type not in MARKET_ID_BY_KEYWORD:
            valid_markets = ", ".join(MARKET_ID_BY_KEYWORD.keys())
            raise DownloadDataException(f"Invalid market_type: {market_type}. Valid options: {valid_markets}")
        
        self.opts["market_id"] = MARKET_ID_BY_KEYWORD[market_type]
        self.opts["market_name"] = MARKETS[self.opts["market_id"]]
        
        # Set sport default
        if "sport" not in self.opts:
            self.opts["sport"] = "NBA"
            
        logger.info("BettingPros Player Props for %d events, sport: %s, market: %s (%s)", 
                len(self.opts["event_ids_list"]), self.opts["sport"], 
                market_type, self.opts["market_id"])
    
    def _fetch_event_ids_from_date(self) -> None:
        """Fetch event IDs using the events scraper"""
        date = self.opts["date"]
        logger.info("Fetching event IDs for date: %s", date)
        
        # Create events scraper and fetch events
        events_scraper = BettingProsEvents()
        events_opts = {
            "date": date,
            "sport": self.opts.get("sport", "NBA"),
            "group": "capture",  # Use capture group to avoid GCS exports
            "run_id": f"{self.run_id}_events"  # Sub-run ID
        }
        
        try:
            events_result = events_scraper.run(events_opts)
            if events_result and hasattr(events_scraper, 'data') and 'events' in events_scraper.data:
                event_ids = list(events_scraper.data['events'].keys())  # Now already strings
                self.opts["event_ids"] = ",".join(event_ids)
                logger.info("Fetched %d event IDs from date %s: %s", 
                           len(event_ids), date, event_ids[:3])
            else:
                raise DownloadDataException(f"No events found for date: {date}")
                
        except Exception as e:
            raise DownloadDataException(f"Failed to fetch events for date {date}: {e}")
    
    def set_url(self) -> None:
        """Build the first page URL - we'll modify this for pagination"""
        event_ids_str = ":".join(self.opts["event_ids_list"])
        
        params = {
            "sport": self.opts["sport"],
            "market_id": str(self.opts["market_id"]),
            "event_id": event_ids_str,
            "book_id": "null",
            "limit": str(self.opts.get("page_limit", 10)),
            "page": "1",  # Start with page 1
        }
        
        query_params = []
        for key, value in params.items():
            query_params.append(f"{key}={value}")
        
        query_string = "&".join(query_params)
        self.url = f"{self.BASE_URL}?{query_string}"
        
        logger.info("BettingPros Props URL (page 1): %s", self.url)
    
    def download_and_decode(self) -> None:
        """Override to handle pagination with better error handling"""
        logger.info("Starting paginated download of player props")
        
        all_offers = []
        page = 1
        total_pages = None
        
        while True:
            # Update URL for current page
            self._update_url_for_page(page)
            logger.debug("Fetching page %d with URL: %s", page, self.url)
            
            # Add rate limiting delay
            if page > 1:  # No delay for first page
                logger.info("Rate limiting: sleeping %.1f seconds before page %d", 
                        self.RATE_LIMIT_DELAY, page)
                time.sleep(self.RATE_LIMIT_DELAY)
            
            try:
                # Download current page
                super().download_and_decode()
                
                # Check if response is empty or invalid
                if not self.raw_response or not self.raw_response.content:
                    logger.warning("Empty response on page %d, stopping pagination", page)
                    break
                    
                # Log response details for debugging
                logger.debug("Page %d response: status=%d, content_length=%d, content_type=%s", 
                            page, self.raw_response.status_code, 
                            len(self.raw_response.content),
                            self.raw_response.headers.get('content-type', 'unknown'))
                
                # Validate response structure
                if not isinstance(self.decoded_data, dict):
                    logger.warning("Invalid response structure on page %d (not a dict), stopping pagination", page)
                    break
                    
                if "offers" not in self.decoded_data:
                    logger.warning("No 'offers' key in response on page %d, stopping pagination", page)
                    break
                
                # Get pagination info
                pagination = self.decoded_data.get("_pagination", {})
                current_page = pagination.get("page", page)
                total_pages = pagination.get("total_pages", 1)
                offers = self.decoded_data.get("offers", [])
                
                logger.info("Page %d/%d: %d offers", current_page, total_pages, len(offers))
                
                # Add offers from this page
                all_offers.extend(offers)
                
                # If no offers on this page, we're probably done
                if not offers and page > 1:
                    logger.info("No offers found on page %d, stopping pagination", page)
                    break
                
                # Check if we're done based on pagination info
                if page >= total_pages:
                    break
                    
            except DownloadDataException as e:
                logger.error("Failed to fetch page %d: %s", page, e)
                # If it's the first page, re-raise the error
                if page == 1:
                    raise
                # For subsequent pages, just stop pagination
                logger.warning("Stopping pagination due to error on page %d", page)
                break
            
            page += 1
            
            # Safety check to prevent infinite loops
            if page > 50:  # Reasonable upper limit
                logger.warning("Reached maximum page limit (50), stopping pagination")
                break
        
        # Store combined data
        self.decoded_data["all_offers"] = all_offers
        self.decoded_data["total_offers"] = len(all_offers)
        self.decoded_data["pages_fetched"] = page - 1 if page > 1 else 1
        
        logger.info("Completed pagination: %d total offers from %d pages", 
                len(all_offers), self.decoded_data["pages_fetched"])

    def decode_download_content(self):
        """Override to handle potential encoding issues and empty responses"""
        logger.debug("Decoding raw response as '%s'", self.download_type)
        
        # Check if response is empty
        if not self.raw_response.content:
            logger.warning("Response content is empty")
            self.decoded_data = {"offers": [], "_pagination": {"page": 1, "total_pages": 1}}
            return
        
        # Log response details for debugging
        content_length = len(self.raw_response.content)
        content_type = self.raw_response.headers.get('content-type', 'unknown')
        logger.debug("Response details: length=%d, content_type=%s", content_length, content_type)
        
        if self.download_type == DownloadType.JSON:
            try:
                # Try standard UTF-8 decoding first
                self.decoded_data = json.loads(self.raw_response.content)
            except UnicodeDecodeError as e:
                logger.warning("UTF-8 decode failed, trying latin-1: %s", e)
                try:
                    # Fallback to latin-1 encoding for problematic responses
                    content_str = self.raw_response.content.decode('latin-1')
                    self.decoded_data = json.loads(content_str)
                except (UnicodeDecodeError, json.JSONDecodeError) as e2:
                    logger.error("All encoding attempts failed: %s", e2)
                    # Log first 200 chars of raw content for debugging
                    raw_preview = self.raw_response.content[:200]
                    logger.error("Raw content preview: %r", raw_preview)
                    raise DownloadDataException(f"Response encoding failed: {e2}") from e2
            except json.JSONDecodeError as ex:
                # Log content for debugging
                try:
                    content_preview = self.raw_response.content.decode('utf-8', errors='replace')[:500]
                    logger.error("JSON decode failed. Content preview: %r", content_preview)
                except Exception:
                    logger.error("JSON decode failed and couldn't preview content")
                
                # Standard JSON decode error (eligible for retry)
                raise DownloadDataException(f"JSON decode failed: {ex}") from ex
        elif self.download_type == DownloadType.HTML:
            try:
                self.decoded_data = self.raw_response.text
            except UnicodeDecodeError:
                # Fallback for HTML content
                self.decoded_data = self.raw_response.content.decode('latin-1')
        elif self.download_type == DownloadType.BINARY:
            # Still place the bytes in decoded_data so ExportMode.DECODED works
            self.decoded_data = self.raw_response.content
        else:
            pass

    def _update_url_for_page(self, page: int) -> None:
        """Update the URL for a specific page"""
        # More robust URL update - rebuild the URL properly
        base_url = self.BASE_URL
        
        # Extract current parameters
        event_ids_str = ":".join(self.opts["event_ids_list"])
        
        params = {
            "sport": self.opts["sport"],
            "market_id": str(self.opts["market_id"]),
            "event_id": event_ids_str,
            "book_id": "null",
            "limit": str(self.opts.get("page_limit", 10)),
            "page": str(page),  # Update to current page
        }
        
        query_params = []
        for key, value in params.items():
            query_params.append(f"{key}={value}")
        
        query_string = "&".join(query_params)
        self.url = f"{base_url}?{query_string}"
        
        logger.debug("Updated URL for page %d: %s", page, self.url)
    
    def decode_download_content(self):
        """Override to handle potential encoding issues from BettingPros API"""
        logger.debug("Decoding raw response as '%s'", self.download_type)
        if self.download_type == DownloadType.JSON:
            try:
                # Try standard UTF-8 decoding first
                self.decoded_data = json.loads(self.raw_response.content)
            except UnicodeDecodeError as e:
                logger.warning("UTF-8 decode failed, trying latin-1: %s", e)
                try:
                    # Fallback to latin-1 encoding for problematic responses
                    content_str = self.raw_response.content.decode('latin-1')
                    self.decoded_data = json.loads(content_str)
                except (UnicodeDecodeError, json.JSONDecodeError) as e2:
                    logger.error("All encoding attempts failed: %s", e2)
                    raise DownloadDataException(f"Response encoding failed: {e2}") from e2
            except json.JSONDecodeError as ex:
                # Standard JSON decode error (eligible for retry)
                raise DownloadDataException(f"JSON decode failed: {ex}") from ex
        elif self.download_type == DownloadType.HTML:
            try:
                self.decoded_data = self.raw_response.text
            except UnicodeDecodeError:
                # Fallback for HTML content
                self.decoded_data = self.raw_response.content.decode('latin-1')
        elif self.download_type == DownloadType.BINARY:
            # Still place the bytes in decoded_data so ExportMode.DECODED works
            self.decoded_data = self.raw_response.content
        else:
            pass
    
    def validate_download_data(self) -> None:
        """Validate the combined paginated response"""
        if not isinstance(self.decoded_data, dict):
            raise DownloadDataException("Response is not a JSON object")
        
        if "all_offers" not in self.decoded_data:
            raise DownloadDataException("Missing combined 'all_offers' in response")
        
        all_offers = self.decoded_data["all_offers"]
        if not isinstance(all_offers, list):
            raise DownloadDataException("'all_offers' is not a list")
        
        # Validate we have the expected market
        markets = self.decoded_data.get("markets", [])
        if self.opts["market_id"] not in markets:
            logger.warning("Market %s not found in response markets: %s", 
                         self.opts["market_id"], markets)
        
        logger.info("Validation passed: %d total offers found", len(all_offers))

    def transform_data(self) -> None:
        """Transform complex BettingPros props data into structured format"""
        all_offers = self.decoded_data["all_offers"]
        
        processed_props = []
        players_summary = {}
        
        for offer in all_offers:
            prop_data = self._process_single_offer(offer)
            if prop_data:
                processed_props.append(prop_data)
                
                # Track player summary
                player_name = prop_data["player_name"]
                if player_name not in players_summary:
                    players_summary[player_name] = {
                        "team": prop_data["player_team"],
                        "props_count": 0
                    }
                players_summary[player_name]["props_count"] += 1
        
        # Store processed data
        self.data = {
            "date": self.opts.get("date", "unknown"),
            "sport": self.opts["sport"],
            "market_id": self.opts["market_id"],
            "market_type": self.opts.get("market_type", "points"),
            "market_name": self.opts["market_name"],
            "event_ids": self.opts["event_ids_list"],
            "timestamp": self.opts["timestamp"],
            "source": "bettingpros_api",
            "api_response_params": self.decoded_data.get("_parameters", {}),
            "pagination_info": {
                "total_offers": self.decoded_data.get("total_offers", 0),
                "pages_fetched": self.decoded_data.get("pages_fetched", 0),
            },
            "props_count": len(processed_props),
            "players_count": len(players_summary),
            "players_summary": players_summary,
            "props": processed_props,
        }
        
        logger.info("Processed %d props for %d players", 
                   len(processed_props), len(players_summary))
        if players_summary:
            top_players = sorted(players_summary.items(), key=lambda x: x[1]["props_count"], reverse=True)[:5]
            logger.info("Top players: %s", 
                       [f"{name}({info['props_count']})" for name, info in top_players])
    
    def _process_single_offer(self, offer: dict) -> Optional[dict]:
        """Process a single prop offer into structured format"""
        try:
            # Get basic info
            offer_id = offer.get("id")
            event_id = offer.get("event_id")
            player_id = offer.get("player_id")
            
            # Get player info
            participants = offer.get("participants", [])
            if not participants:
                logger.warning("No participants found for offer %s", offer_id)
                return None
            
            participant = participants[0]  # Usually just one player
            player_info = participant.get("player", {})
            
            player_name = participant.get("name", "")
            player_team = player_info.get("team", "")
            player_position = player_info.get("position", "")
            
            # Process selections (over/under)
            selections = offer.get("selections", [])
            over_selection = None
            under_selection = None
            
            for selection in selections:
                if selection.get("selection") == "over":
                    over_selection = self._process_selection(selection)
                elif selection.get("selection") == "under":
                    under_selection = self._process_selection(selection)
            
            # Create structured prop data
            prop_data = {
                "offer_id": offer_id,
                "event_id": event_id,
                "player_id": player_id,
                "player_name": player_name,
                "player_team": player_team,
                "player_position": player_position,
                "market": self.opts.get("market_type", "points"),
                "market_id": self.opts["market_id"],
                "over": over_selection,
                "under": under_selection,
                "link": offer.get("link", ""),
                "active": offer.get("active", False),
            }
            
            return prop_data
            
        except Exception as e:
            logger.warning("Error processing offer %s: %s", 
                          offer.get("id", "unknown"), e)
            return None
    
    def _process_selection(self, selection: dict) -> dict:
        """Process over/under selection with sportsbook lines"""
        processed_selection = {
            "selection_id": selection.get("id"),
            "active": selection.get("active", False),
            "opening_line": selection.get("opening_line", {}),
            "sportsbooks": []
        }
        
        # Process sportsbook lines
        books = selection.get("books", [])
        for book in books:
            book_id = book.get("id")
            book_name = BOOKS.get(book_id, f"Unknown Book {book_id}")
            lines = book.get("lines", [])
            
            for line in lines:
                sportsbook_line = {
                    "book_id": book_id,
                    "book_name": book_name,
                    "line_id": line.get("id"),
                    "line": line.get("line"),  # The points line (e.g., 28.5)
                    "odds": line.get("cost"),  # The odds (e.g., -110)
                    "updated": line.get("updated"),
                    "active": line.get("active", False),
                    "best": line.get("best", False),
                }
                processed_selection["sportsbooks"].append(sportsbook_line)
        
        return processed_selection
    
    def get_scraper_stats(self) -> dict:
        """Return scraper statistics"""
        return {
            "date": self.opts.get("date", "unknown"),
            "market_type": self.opts.get("market_type", "points"),
            "market_id": self.opts["market_id"],
            "event_ids_count": len(self.opts.get("event_ids_list", [])),
            "props_count": self.data.get("props_count", 0),
            "players_count": self.data.get("players_count", 0),
            "pages_fetched": self.data.get("pagination_info", {}).get("pages_fetched", 0),
            "timestamp": self.opts["timestamp"]
        }


# --------------------------------------------------------------------------- #
# Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BettingProsPlayerProps)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BettingProsPlayerProps.create_cli_and_flask_main()
    main()
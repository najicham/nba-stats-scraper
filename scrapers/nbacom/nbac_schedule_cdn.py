# scrapers/nbacom/nbac_schedule_cdn.py
"""
NBA.com CDN static schedule JSON scraper                 v1 - 2025-07-17
------------------------------------------------------------------------
Uses NBA.com CDN static JSON files - very reliable backup source.

Primary URL: https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json
Backup URL:  https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json

This scraper gets the current season schedule from static CDN files.
No season parameter needed - returns current/active season automatically.

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py nbac_schedule_cdn \
      --debug

  # Direct CLI execution:
  python scrapers/nbacom/nbac_schedule_cdn.py --debug

  # Flask web service:
  python scrapers/nbacom/nbac_schedule_cdn.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.nbacom.nbac_schedule_cdn
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_schedule_cdn.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

logger = logging.getLogger("scraper_base")


class GetNbaComScheduleCdn(ScraperBase, ScraperFlaskMixin):
    """
    NBA.com CDN static schedule JSON scraper.
    
    No parameters required - gets current season from static CDN files.
    """

    # Flask Mixin Configuration
    scraper_name = "nbac_schedule_cdn"
    required_params = []  # No parameters needed for CDN static files
    optional_params = {
        "apiKey": None,
        "runId": None,
    }
    
    required_opts = []  # No parameters needed for CDN static files
    download_type = DownloadType.JSON
    decode_download_data = True
    header_profile = None  # CDN doesn't need special headers
    proxy_enabled = False  # CDN is typically accessible
    
    # Primary CDN URL (using _1 version)
    PRIMARY_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"
    
    # Backup URL (commented for future use)
    # BACKUP_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
    
    GCS_PATH_KEY = "nba_com_schedule_cdn"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # Local development files
        {
            "type": "file",
            "filename": "/tmp/nba_schedule_cdn.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        # Raw CDN response
        {
            "type": "file",
            "filename": "/tmp/nba_schedule_cdn_raw.json",
            "export_mode": ExportMode.RAW,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        # Capture group exporters
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
        super().set_additional_opts()
        
        """Set timestamp for exporters"""
        self.opts["timestamp"] = datetime.now(timezone.utc).isoformat()
        logger.info("Using NBA.com CDN static schedule endpoint")
    
    def set_url(self) -> None:
        """Set the CDN URL - no parameters needed"""
        self.url = self.PRIMARY_URL
        logger.info("NBA.com CDN schedule URL: %s", self.url)
    
    def validate_download_data(self) -> None:
        """Validate the NBA.com CDN response"""
        if not isinstance(self.decoded_data, dict):
            raise DownloadDataException("Response is not a JSON object")
        
        # Check for the expected structure (might be similar to API version)
        if "leagueSchedule" in self.decoded_data:
            # Same structure as API version
            league_schedule = self.decoded_data["leagueSchedule"]
            if "gameDates" not in league_schedule:
                raise DownloadDataException("Missing 'gameDates' in leagueSchedule")
            
            game_dates = league_schedule["gameDates"]
            if not isinstance(game_dates, list):
                raise DownloadDataException("gameDates is not a list")
            
            logger.info("Validation passed: %d game dates found (leagueSchedule format)", len(game_dates))
            
        elif "gameDates" in self.decoded_data:
            # Direct gameDates format
            game_dates = self.decoded_data["gameDates"]
            if not isinstance(game_dates, list):
                raise DownloadDataException("gameDates is not a list")
            
            logger.info("Validation passed: %d game dates found (direct format)", len(game_dates))
            
        else:
            # Log the keys to help debug the structure
            keys = list(self.decoded_data.keys()) if isinstance(self.decoded_data, dict) else []
            logger.warning("Unexpected response structure. Keys found: %s", keys)
            raise DownloadDataException(f"Expected 'leagueSchedule' or 'gameDates', found keys: {keys}")
    
    def transform_data(self) -> None:
        """Transform NBA.com CDN response into structured data"""
        
        # Handle different possible structures
        if "leagueSchedule" in self.decoded_data:
            # Same as API format
            league_schedule = self.decoded_data["leagueSchedule"]
            meta = self.decoded_data.get("meta", {})
            game_dates = league_schedule.get("gameDates", [])
            season_year = league_schedule.get("seasonYear", "Unknown")
            league_id = league_schedule.get("leagueId", "00")
            
        elif "gameDates" in self.decoded_data:
            # Direct format
            game_dates = self.decoded_data.get("gameDates", [])
            meta = self.decoded_data.get("meta", {})
            season_year = self.decoded_data.get("seasonYear", "Unknown")
            league_id = self.decoded_data.get("leagueId", "00")
            
        else:
            # Fallback - treat entire response as the data
            game_dates = []
            meta = {}
            season_year = "Unknown"
            league_id = "00"
            logger.warning("Using fallback data transformation")
        
        # Flatten all games from all dates
        all_games = []
        for game_date_obj in game_dates:
            game_date = game_date_obj.get("gameDate", "")
            games = game_date_obj.get("games", [])
            
            for game in games:
                # Add the game date to each game for easier processing
                game_with_date = {
                    **game,
                    "gameDate": game_date,
                    "source": "cdn_static"
                }
                all_games.append(game_with_date)
        
        # Sort games by date and game sequence
        all_games.sort(key=lambda x: (x.get("gameDateEst", ""), x.get("gameSequence", 0)))
        
        self.data = {
            "source": "nba_cdn_static",
            "url": self.url,
            "seasonYear": season_year,
            "leagueId": league_id,
            "timestamp": self.opts["timestamp"],
            "meta": meta,
            "game_count": len(all_games),
            "date_count": len(game_dates),
            "games": all_games,
            "gameDates": game_dates,  # Keep original structure
            "raw_response_keys": list(self.decoded_data.keys())  # For debugging
        }
        
        logger.info("Processed %d games across %d dates for %s season (CDN static)", 
                   len(all_games), len(game_dates), season_year)
    
    def get_scraper_stats(self) -> dict:
        """Return scraper statistics"""
        return {
            "source": "nba_cdn_static",
            "seasonYear": self.data.get("seasonYear", "Unknown"),
            "game_count": self.data.get("game_count", 0),
            "date_count": self.data.get("date_count", 0),
            "timestamp": self.opts["timestamp"]
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetNbaComScheduleCdn)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetNbaComScheduleCdn.create_cli_and_flask_main()
    main()
    
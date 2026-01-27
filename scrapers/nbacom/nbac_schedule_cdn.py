"""
NBA.com CDN static schedule JSON scraper                 v2 - 2025-10-19
------------------------------------------------------------------------
Uses NBA.com CDN static JSON files - very reliable backup source.

Enhanced with shared transformation logic for consistent output format.
Now produces identical output to nbac_schedule_api for seamless fallback.

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
    from ..utils.schedule_transformer import ScheduleTransformer
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_schedule_cdn.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder
    from scrapers.utils.schedule_transformer import ScheduleTransformer

# Import notification system
try:
    from shared.utils.notification_system import (
        notify_error,
        notify_warning,
        notify_info
    )
except ImportError:
    # Fallback if shared module not available
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from shared.utils.notification_system import (
        notify_error,
        notify_warning,
        notify_info
    )

logger = logging.getLogger("scraper_base")


class GetNbaComScheduleCdn(ScraperBase, ScraperFlaskMixin):
    """
    NBA.com CDN static schedule JSON scraper with enhanced transformation.
    
    Uses shared ScheduleTransformer for consistent output with API scraper.
    No parameters required - gets current season from static CDN files.
    """

    # Flask Mixin Configuration
    scraper_name = "nbac_schedule_cdn"
    required_params = []  # No parameters needed for CDN static files
    optional_params = {
        "api_key": None,
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
    METADATA_GCS_PATH_KEY = "nba_com_schedule_cdn_metadata"
    
    exporters = [
        # ========== SCHEDULE DATA EXPORTERS ==========
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
            "export_mode": ExportMode.DATA,  # Changed from DECODED to DATA
            "pretty_print": True,
            "groups": ["capture"],
        },
        
        # ========== METADATA EXPORTERS ==========
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(METADATA_GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "data_key": "metadata",  # Export self.data['metadata']
            "groups": ["prod", "gcs"],
        },
        # Local metadata files for development
        {
            "type": "file",
            "filename": "/tmp/nba_schedule_cdn_metadata.json",
            "export_mode": ExportMode.DATA,
            "data_key": "metadata",
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        # Capture group metadata
        {
            "type": "file",
            "filename": "/tmp/metadata_%(run_id)s.json",
            "export_mode": ExportMode.DATA,
            "data_key": "metadata",
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]
    
    def set_url(self) -> None:
        """Set the CDN URL - no parameters needed"""
        self.url = self.PRIMARY_URL
        logger.info("NBA.com CDN schedule URL: %s", self.url)
    
    def validate_download_data(self) -> None:
        """Validate the NBA.com CDN response"""
        try:
            if not isinstance(self.decoded_data, dict):
                try:
                    notify_error(
                        title="NBA.com CDN Schedule - Invalid Response",
                        message="Response is not a valid JSON object",
                        details={
                            'scraper': 'nbac_schedule_cdn',
                            'response_type': type(self.decoded_data).__name__,
                            'url': self.url
                        },
                        processor_name="NBA.com CDN Schedule Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException("Response is not a JSON object")
            
            # Check for the expected structure (might be similar to API version)
            if "leagueSchedule" in self.decoded_data:
                # Same structure as API version
                league_schedule = self.decoded_data["leagueSchedule"]
                if "gameDates" not in league_schedule:
                    try:
                        notify_error(
                            title="NBA.com CDN Schedule - Missing Game Dates",
                            message="Missing 'gameDates' in leagueSchedule structure",
                            details={
                                'scraper': 'nbac_schedule_cdn',
                                'available_keys': list(league_schedule.keys()),
                                'url': self.url
                            },
                            processor_name="NBA.com CDN Schedule Scraper"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                    raise DownloadDataException("Missing 'gameDates' in leagueSchedule")
                
                game_dates = league_schedule["gameDates"]
                if not isinstance(game_dates, list):
                    try:
                        notify_error(
                            title="NBA.com CDN Schedule - Invalid Game Dates Type",
                            message="gameDates is not a list (leagueSchedule format)",
                            details={
                                'scraper': 'nbac_schedule_cdn',
                                'game_dates_type': type(game_dates).__name__,
                                'url': self.url
                            },
                            processor_name="NBA.com CDN Schedule Scraper"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                    raise DownloadDataException("gameDates is not a list")
                
                logger.info("Validation passed: %d game dates found (leagueSchedule format)", len(game_dates))
                
                # Send success notification
                try:
                    notify_info(
                        title="NBA.com CDN Schedule - Download Complete",
                        message=f"Successfully downloaded schedule with {len(game_dates)} game dates (leagueSchedule format)",
                        details={
                            'scraper': 'nbac_schedule_cdn',
                            'format': 'leagueSchedule',
                            'game_dates_count': len(game_dates),
                            'season': league_schedule.get('seasonYear', 'Unknown'),
                            'url': self.url
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
            elif "gameDates" in self.decoded_data:
                # Direct gameDates format
                game_dates = self.decoded_data["gameDates"]
                if not isinstance(game_dates, list):
                    try:
                        notify_error(
                            title="NBA.com CDN Schedule - Invalid Game Dates Type",
                            message="gameDates is not a list (direct format)",
                            details={
                                'scraper': 'nbac_schedule_cdn',
                                'game_dates_type': type(game_dates).__name__,
                                'url': self.url
                            },
                            processor_name="NBA.com CDN Schedule Scraper"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                    raise DownloadDataException("gameDates is not a list")
                
                logger.info("Validation passed: %d game dates found (direct format)", len(game_dates))
                
                # Send success notification
                try:
                    notify_info(
                        title="NBA.com CDN Schedule - Download Complete",
                        message=f"Successfully downloaded schedule with {len(game_dates)} game dates (direct format)",
                        details={
                            'scraper': 'nbac_schedule_cdn',
                            'format': 'direct_gameDates',
                            'game_dates_count': len(game_dates),
                            'season': self.decoded_data.get('seasonYear', 'Unknown'),
                            'url': self.url
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
            else:
                # Log the keys to help debug the structure
                keys = list(self.decoded_data.keys()) if isinstance(self.decoded_data, dict) else []
                logger.warning("Unexpected response structure. Keys found: %s", keys)
                
                try:
                    notify_error(
                        title="NBA.com CDN Schedule - Unexpected Structure",
                        message=f"Expected 'leagueSchedule' or 'gameDates', found unexpected keys",
                        details={
                            'scraper': 'nbac_schedule_cdn',
                            'found_keys': keys,
                            'expected_keys': ['leagueSchedule', 'gameDates'],
                            'url': self.url
                        },
                        processor_name="NBA.com CDN Schedule Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                    
                raise DownloadDataException(f"Expected 'leagueSchedule' or 'gameDates', found keys: {keys}")
                
        except DownloadDataException:
            # Re-raise validation exceptions (already notified above)
            raise
        except Exception as e:
            # Catch any unexpected validation errors
            try:
                notify_error(
                    title="NBA.com CDN Schedule - Validation Failed",
                    message=f"Unexpected validation error: {str(e)}",
                    details={
                        'scraper': 'nbac_schedule_cdn',
                        'error_type': type(e).__name__,
                        'error': str(e),
                        'url': self.url
                    },
                    processor_name="NBA.com CDN Schedule Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
    
    def transform_data(self) -> None:
        """Transform NBA.com CDN response into structured data with enhanced flags"""
        
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

        # Extract actual season for path building
        if season_year and season_year != "Unknown":
            if season_year.isdigit() and len(season_year) == 4:
                # Convert year to NBA format (e.g., "2025" -> "2025-26")
                season_int = int(season_year)
                next_year = (season_int + 1) % 100
                self.opts['actual_season_nba_format'] = f"{season_int}-{next_year:02d}"
            else:
                # Already in NBA format or other format
                self.opts['actual_season_nba_format'] = season_year
        else:
            # Fallback - use current season logic
            from datetime import datetime
            current_year = datetime.now().year
            # NBA season typically starts in October, so if we're past October, it's current_year-next_year season
            if datetime.now().month >= 10:
                next_year = (current_year + 1) % 100
                self.opts['actual_season_nba_format'] = f"{current_year}-{next_year:02d}"
            else:
                # Before October, we're in the previous season
                prev_year = current_year - 1
                self.opts['actual_season_nba_format'] = f"{prev_year}-{current_year % 100:02d}"
        
        # Initialize shared transformer with season
        transformer = ScheduleTransformer(self.opts['actual_season_nba_format'])
        
        # Flatten and enhance all games from all dates
        all_games = []
        for game_date_obj in game_dates:
            game_date = game_date_obj.get("gameDate", "")
            games = game_date_obj.get("games", [])
            
            for game in games:
                # Enhance with computed flags using shared logic (same as API scraper)
                enhanced_game = transformer.enhance_game(game, game_date)
                
                # Add metadata
                enhanced_game.update({
                    "gameDate": game_date,
                    "gameDateObj": game_date_obj.get("gameDate", ""),
                    "source": "cdn_static"  # Tag to identify data source
                })
                
                all_games.append(enhanced_game)
        
        # Sort games by date and game sequence
        all_games.sort(key=lambda x: (x.get("gameDateEst", ""), x.get("gameSequence", 0)))
        
        # Generate season metadata using shared logic
        metadata = transformer.generate_metadata(all_games)
        metadata['scraped_at'] = self.opts["timestamp"]
        metadata['source'] = 'cdn_static'
        
        # Store data in same format as API scraper
        self.data = {
            "season": season_year,
            "season_nba_format": self.opts['actual_season_nba_format'],
            "seasonYear": season_year,
            "leagueId": league_id,
            "timestamp": self.opts["timestamp"],
            "meta": meta,
            "game_count": len(all_games),
            "date_count": len(game_dates),
            "games": all_games,
            "metadata": metadata,  # Add metadata like API scraper
            "source": "cdn_static"
        }
        
        logger.info("Processed %d games across %d dates for %s season (CDN static)", 
                   len(all_games), len(game_dates), self.opts['actual_season_nba_format'])
        logger.info("Generated metadata: %d total games, %d backfill eligible", 
                   metadata["total_games"], metadata["backfill"]["total_games"])
        
        # Check for suspiciously low game count
        min_games = int(os.environ.get('SCHEDULE_MIN_GAMES', '50'))
        if len(all_games) < min_games:
            try:
                notify_warning(
                    title="NBA.com CDN Schedule - Low Game Count",
                    message=f"Suspiciously low game count: {len(all_games)} games for season {self.opts['actual_season_nba_format']}",
                    details={
                        'scraper': 'nbac_schedule_cdn',
                        'game_count': len(all_games),
                        'date_count': len(game_dates),
                        'season': self.opts['actual_season_nba_format'],
                        'threshold_min': min_games
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
    
    def get_scraper_stats(self) -> dict:
        """Return scraper statistics"""
        return {
            "source": "cdn_static",
            "seasonYear": self.data.get("seasonYear", "Unknown"),
            "season_nba_format": self.data.get("season_nba_format", "Unknown"),
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
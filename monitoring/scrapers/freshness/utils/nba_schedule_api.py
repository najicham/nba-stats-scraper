"""
File: scrapers/nbacom/nbac_schedule_api.py

NBA.com stats API schedule scraper                       v3 - 2025-10-19
------------------------------------------------------------------------
Uses the current NBA.com stats API endpoint to get season schedules.
Enhanced with shared transformation logic for consistent output format.

URL: https://stats.nba.com/stats/scheduleleaguev2int

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py nbac_schedule_api \
      --season 2025 \
      --debug

  # Direct CLI execution:
  python scrapers/nbacom/nbac_schedule_api.py --season 2025 --debug

  # Flask web service:
  python scrapers/nbacom/nbac_schedule_api.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.nbacom.nbac_schedule_api
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
    from ..utils.schedule_transformer import ScheduleTransformer
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_schedule_api.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder
    from scrapers.utils.schedule_transformer import ScheduleTransformer

# Notification system imports
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger("scraper_base")


class GetNbaComScheduleApi(ScraperBase, ScraperFlaskMixin):
    """
    NBA.com stats API schedule scraper with enhanced transformation.
    
    Uses shared ScheduleTransformer for consistent output with CDN scraper.
    
    Required opts:
        season: 4-digit start year (e.g., 2025 for 2025-26 season)
    """

    # Flask Mixin Configuration
    scraper_name = "nbac_schedule_api"
    required_params = ["season"]
    optional_params = {
        "api_key": None,
    }
    
    required_opts = ["season"]
    download_type = DownloadType.JSON
    decode_download_data = True
    header_profile = "stats"  # Use NBA stats headers
    proxy_enabled = True      # stats.nba.com may need proxy
    
    BASE_URL = "https://stats.nba.com/stats/scheduleleaguev2int"

    # GCS path configuration
    GCS_PATH_KEY = "nba_com_schedule"
    METADATA_GCS_PATH_KEY = "nba_com_schedule_metadata"

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
            "filename": "/tmp/nba_schedule_%(season)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        # Raw data for debugging
        {
            "type": "file",
            "filename": "/tmp/nba_schedule_raw_%(season)s.json",
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
            "export_mode": ExportMode.DATA,
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
            "filename": "/tmp/nba_schedule_metadata_%(season)s.json",
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
    
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        """Convert season to NBA format and set timestamp"""
        # Convert 4-digit year to NBA season format (e.g., 2025 -> 2025-26)
        season_year = int(self.opts["season"])
        next_year = (season_year + 1) % 100  # Get last 2 digits of next year
        self.opts["season_nba_format"] = f"{season_year}-{next_year:02d}"
        
        # Add timestamp for exporters
        self.opts["timestamp"] = datetime.now(timezone.utc).isoformat()
        
        logger.info("Season: %s -> NBA format: %s", 
                   self.opts["season"], self.opts["season_nba_format"])
    
    def set_url(self) -> None:
        """Build the stats.nba.com schedule URL"""
        params = {
            "GameSubType": "",
            "LeagueID": "00",  # NBA league ID
            "Season": self.opts["season_nba_format"],
            # "SeasonType": "Regular Season"
        }
        
        # Build query string
        query_params = []
        for key, value in params.items():
            query_params.append(f"{key}={value}")
        
        query_string = "&".join(query_params)
        self.url = f"{self.BASE_URL}?{query_string}"
        
        logger.info("NBA.com schedule URL: %s", self.url)
    
    def validate_download_data(self) -> None:
        """Validate the NBA.com API response"""
        try:
            if not isinstance(self.decoded_data, dict):
                error_msg = "Response is not a JSON object"
                logger.error("%s for season %s", error_msg, self.opts["season"])
                try:
                    notify_error(
                        title="NBA.com Schedule API Invalid Response",
                        message=f"API response is not a JSON object for season {self.opts['season']}",
                        details={
                            'season': self.opts['season'],
                            'season_nba_format': self.opts['season_nba_format'],
                            'response_type': type(self.decoded_data).__name__,
                            'url': self.url
                        },
                        processor_name="NBA.com Schedule API Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
            
            # The actual response has 'leagueSchedule' not 'resultSets'
            if "leagueSchedule" not in self.decoded_data:
                error_msg = "Missing 'leagueSchedule' in response"
                logger.error("%s for season %s", error_msg, self.opts["season"])
                try:
                    notify_error(
                        title="NBA.com Schedule API Missing Data",
                        message=f"API response missing 'leagueSchedule' for season {self.opts['season']}",
                        details={
                            'season': self.opts['season'],
                            'season_nba_format': self.opts['season_nba_format'],
                            'response_keys': list(self.decoded_data.keys()),
                            'url': self.url
                        },
                        processor_name="NBA.com Schedule API Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
            
            league_schedule = self.decoded_data["leagueSchedule"]
            if not isinstance(league_schedule, dict):
                error_msg = "leagueSchedule is not an object"
                logger.error("%s for season %s", error_msg, self.opts["season"])
                try:
                    notify_error(
                        title="NBA.com Schedule API Invalid Structure",
                        message=f"leagueSchedule is not an object for season {self.opts['season']}",
                        details={
                            'season': self.opts['season'],
                            'season_nba_format': self.opts['season_nba_format'],
                            'league_schedule_type': type(league_schedule).__name__,
                            'url': self.url
                        },
                        processor_name="NBA.com Schedule API Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
            
            if "gameDates" not in league_schedule:
                error_msg = "Missing 'gameDates' in leagueSchedule"
                logger.error("%s for season %s", error_msg, self.opts["season"])
                try:
                    notify_error(
                        title="NBA.com Schedule API Missing Game Dates",
                        message=f"Missing 'gameDates' in API response for season {self.opts['season']}",
                        details={
                            'season': self.opts['season'],
                            'season_nba_format': self.opts['season_nba_format'],
                            'league_schedule_keys': list(league_schedule.keys()),
                            'url': self.url
                        },
                        processor_name="NBA.com Schedule API Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
            
            game_dates = league_schedule["gameDates"]
            if not isinstance(game_dates, list):
                error_msg = "gameDates is not a list"
                logger.error("%s for season %s", error_msg, self.opts["season"])
                try:
                    notify_error(
                        title="NBA.com Schedule API Invalid Game Dates",
                        message=f"gameDates is not a list for season {self.opts['season']}",
                        details={
                            'season': self.opts['season'],
                            'season_nba_format': self.opts['season_nba_format'],
                            'game_dates_type': type(game_dates).__name__,
                            'url': self.url
                        },
                        processor_name="NBA.com Schedule API Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
            
            # Warning for suspiciously low game date count
            min_game_dates = int(os.environ.get('SCHEDULE_MIN_GAME_DATES', '50'))
            if len(game_dates) < min_game_dates:
                logger.warning("Low game date count (%d) for season %s", len(game_dates), self.opts["season"])
                try:
                    notify_warning(
                        title="NBA.com Schedule API Low Game Date Count",
                        message=f"Low game date count ({len(game_dates)}) for season {self.opts['season']}",
                        details={
                            'season': self.opts['season'],
                            'season_nba_format': self.opts['season_nba_format'],
                            'game_date_count': len(game_dates),
                            'threshold': min_game_dates,
                            'url': self.url
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            logger.info("Validation passed: %d game dates found", len(game_dates))
            
        except DownloadDataException:
            # Already handled and notified above
            raise
        except Exception as e:
            # Unexpected validation errors
            logger.error("Unexpected validation error for season %s: %s", self.opts["season"], e)
            try:
                notify_error(
                    title="NBA.com Schedule API Validation Error",
                    message=f"Unexpected validation error for season {self.opts['season']}: {str(e)}",
                    details={
                        'season': self.opts['season'],
                        'season_nba_format': self.opts['season_nba_format'],
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'url': self.url
                    },
                    processor_name="NBA.com Schedule API Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Validation failed: {e}") from e

    def transform_data(self) -> None:
        """Transform NBA.com API response into structured data with enhanced flags"""
        try:
            league_schedule = self.decoded_data["leagueSchedule"]
            meta = self.decoded_data.get("meta", {})

            actual_season = league_schedule.get('seasonYear') or self.opts.get('season_nba_format')
            if actual_season:
                # If seasonYear is just a year (like "2025"), convert to NBA format
                if actual_season.isdigit() and len(actual_season) == 4:
                    season_year = int(actual_season)
                    next_year = (season_year + 1) % 100
                    self.opts['actual_season_nba_format'] = f"{season_year}-{next_year:02d}"
                else:
                    # Already in NBA format (like "2025-26")
                    self.opts['actual_season_nba_format'] = actual_season
            else:
                # Fallback to the season we computed in set_additional_opts
                self.opts['actual_season_nba_format'] = self.opts['season_nba_format']
            
            game_dates = league_schedule.get("gameDates", [])
            
            # Initialize shared transformer with season
            transformer = ScheduleTransformer(self.opts['actual_season_nba_format'])
            
            # Flatten and enhance all games from all dates
            all_games = []
            for game_date_obj in game_dates:
                game_date = game_date_obj.get("gameDate", "")
                games = game_date_obj.get("games", [])
                
                for game in games:
                    # Enhance with computed flags using shared logic
                    enhanced_game = transformer.enhance_game(game, game_date)
                    
                    # Add metadata
                    enhanced_game.update({
                        "gameDate": game_date,
                        "gameDateObj": game_date_obj.get("gameDate", ""),
                        "source": "api_stats"  # Tag to identify data source
                    })
                    
                    all_games.append(enhanced_game)
            
            # Sort games by date and game sequence
            all_games.sort(key=lambda x: (x.get("gameDateEst", ""), x.get("gameSequence", 0)))
            
            # Generate season metadata using shared logic
            metadata = transformer.generate_metadata(all_games)
            metadata['scraped_at'] = self.opts["timestamp"]
            metadata['source'] = 'api_stats'
            
            # Warning for suspiciously low game count
            min_games = int(os.environ.get('SCHEDULE_MIN_GAMES', '100'))
            if len(all_games) < min_games:
                logger.warning("Low total game count (%d) for season %s", len(all_games), self.opts["season"])
                try:
                    notify_warning(
                        title="NBA.com Schedule API Low Game Count",
                        message=f"Low total game count ({len(all_games)}) for season {self.opts['season']}",
                        details={
                            'season': self.opts['season'],
                            'season_nba_format': self.opts['season_nba_format'],
                            'game_count': len(all_games),
                            'threshold': min_games,
                            'metadata': metadata
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            # Store both schedule data and metadata
            self.data = {
                "season": self.opts["season"],
                "season_nba_format": self.opts["season_nba_format"],
                "seasonYear": league_schedule.get("seasonYear"),
                "leagueId": league_schedule.get("leagueId"),
                "timestamp": self.opts["timestamp"],
                "meta": meta,
                "game_count": len(all_games),
                "date_count": len(game_dates),
                "games": all_games,
                "metadata": metadata,
                "source": "api_stats"
            }
            
            logger.info("Processed %d games across %d dates for %s season", 
                    len(all_games), len(game_dates), self.opts["season_nba_format"])
            logger.info("Generated metadata: %d total games, %d backfill eligible", 
                    metadata["total_games"], metadata["backfill"]["total_games"])
                    
        except KeyError as e:
            logger.error("Missing expected key during transformation for season %s: %s", self.opts["season"], e)
            try:
                notify_error(
                    title="NBA.com Schedule API Transformation Failed",
                    message=f"Missing expected key during data transformation for season {self.opts['season']}: {str(e)}",
                    details={
                        'season': self.opts['season'],
                        'season_nba_format': self.opts['season_nba_format'],
                        'missing_key': str(e),
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Schedule API Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Data transformation failed: missing key {e}") from e
        except Exception as e:
            logger.error("Unexpected error during transformation for season %s: %s", self.opts["season"], e)
            try:
                notify_error(
                    title="NBA.com Schedule API Transformation Error",
                    message=f"Unexpected error during data transformation for season {self.opts['season']}: {str(e)}",
                    details={
                        'season': self.opts['season'],
                        'season_nba_format': self.opts['season_nba_format'],
                        'error': str(e),
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Schedule API Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Data transformation failed: {e}") from e
    
    def get_scraper_stats(self) -> dict:
        """Return scraper statistics"""
        return {
            "source": "api_stats",
            "season": self.opts["season"],
            "season_nba_format": self.opts["season_nba_format"],
            "game_count": self.data.get("game_count", 0),
            "timestamp": self.opts["timestamp"]
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetNbaComScheduleApi)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetNbaComScheduleApi.create_cli_and_flask_main()
    main()
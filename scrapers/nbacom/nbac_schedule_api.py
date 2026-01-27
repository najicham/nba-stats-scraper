"""
File: scrapers/nbacom/nbac_schedule_api.py

NBA.com stats API schedule scraper                       v2 - 2025-09-17
------------------------------------------------------------------------
Uses the current NBA.com stats API endpoint to get season schedules.
Enhanced with broadcaster analysis and game context flags.

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
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_schedule_api.py
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


class GetNbaComScheduleApi(ScraperBase, ScraperFlaskMixin):
    """
    NBA.com stats API schedule scraper with enhanced broadcaster and context analysis.
    
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

    # Add these constants near the top of the class
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
            "data_key": "metadata",  # Export self.metadata instead of self.data
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
                        },
                        processor_name=self.__class__.__name__
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
            
            # Flatten all games from all dates
            all_games = []
            for game_date_obj in game_dates:
                game_date = game_date_obj.get("gameDate", "")
                games = game_date_obj.get("games", [])
                
                for game in games:
                    # Remove bulky data to keep files lean
                    if 'tickets' in game:
                        del game['tickets']
                    if 'links' in game:
                        del game['links']
                    if 'promotions' in game:
                        del game['promotions']
                    if 'seriesText' in game:
                        del game['seriesText']
                    if 'pointsLeaders' in game:
                        del game['pointsLeaders']
                    
                    # Add enhanced flags and context
                    enhanced_game = self._enhance_game_with_flags(game, game_date)
                    
                    # Remove broadcaster data after extracting flags (storage optimization)
                    if 'broadcasters' in enhanced_game:
                        del enhanced_game['broadcasters']
                    
                    # Add the game date to each game for easier processing
                    enhanced_game.update({
                        "gameDate": game_date,
                        "gameDateObj": game_date_obj.get("gameDate", "")
                    })
                    
                    all_games.append(enhanced_game)
            
            # Sort games by date and game sequence
            all_games.sort(key=lambda x: (x.get("gameDateEst", ""), x.get("gameSequence", 0)))
            
            # Generate season metadata
            metadata = self._generate_season_metadata(all_games)
            
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
                        },
                        processor_name=self.__class__.__name__
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
                # "gameDates": game_dates,  # Keep original structure too
                "metadata": metadata  # Store metadata here for the exporter
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

    def _enhance_game_with_flags(self, game: dict, game_date: str) -> dict:
        """Add computed flags for fast querying while preserving raw data"""
        enhanced = game.copy()
        
        # Broadcaster flags (5 fields)
        broadcaster_info = self._analyze_broadcasters(game.get('broadcasters', {}))
        enhanced.update(broadcaster_info)
        
        # Game context flags (7 fields)
        context_info = self._analyze_game_context(game, game_date)
        enhanced.update(context_info)
        
        # Scheduling flags (3 fields)
        scheduling_info = self._analyze_scheduling(game, game_date)
        enhanced.update(scheduling_info)
        
        return enhanced

    def _analyze_broadcasters(self, broadcasters_obj: dict) -> dict:
        """Extract broadcaster flags and primary network info"""
        if not broadcasters_obj:
            return {
                'isPrimetime': False,
                'hasNationalTV': False,
                'primaryNetwork': None,
                'traditionalNetworks': [],
                'streamingPlatforms': [],
            }
        
        national_tv = broadcasters_obj.get('nationalTvBroadcasters', [])
        if not isinstance(national_tv, list):
            national_tv = []
        
        # Extract network names safely
        national_networks = []
        for broadcaster in national_tv:
            if broadcaster and isinstance(broadcaster, dict):
                display_name = broadcaster.get('broadcasterDisplay', '')
                if display_name:
                    national_networks.append(display_name)
        
        # Network configuration based on actual NBA broadcast deals
        # Updated for 2024-25 current season and 2025-26+ future seasons
        PRIMETIME_NETWORKS = {
            # Traditional broadcast networks (highest priority - Finals, marquee games)
            'ABC': {'priority': 1, 'type': 'broadcast', 'seasons': 'all'},
            'NBC': {'priority': 2, 'type': 'broadcast', 'seasons': '2025-26+'},  # Returns next season
            
            # Premium cable networks  
            'ESPN': {'priority': 3, 'type': 'cable', 'seasons': 'all'},
            'TNT': {'priority': 4, 'type': 'cable', 'seasons': '2024-25'},  # Exits after this season
            
            # Major streaming platforms (lower priority but still primetime)
            'Amazon Prime': {'priority': 5, 'type': 'streaming', 'seasons': '2025-26+'},  # New exclusive games
            'Peacock': {'priority': 6, 'type': 'streaming', 'seasons': '2025-26+'},  # NBC streaming partner
        }
        
        # National but not traditionally "primetime" 
        NATIONAL_NETWORKS = ['NBA TV', 'NBATV']
        
        # Streaming supplements (simulcasts, not exclusive)
        STREAMING_SUPPLEMENTS = ['ESPN+', 'Max', 'Disney+', 'truTV']  # Max exits with TNT
        
        # Season-aware network detection
        current_season = self.opts.get('actual_season_nba_format', '2024-25')
        
        # Filter networks based on season availability
        active_networks = {}
        for network, config in PRIMETIME_NETWORKS.items():
            seasons = config['seasons']
            if seasons == 'all':
                active_networks[network] = config
            elif seasons == '2024-25' and current_season == '2024-25':
                active_networks[network] = config
            elif seasons == '2025-26+' and current_season >= '2025-26':
                active_networks[network] = config
        
        # Parse traditional networks vs streaming platforms
        traditional_networks = []
        streaming_platforms = []
        
        for network_display in national_networks:
            # Split on '/' to handle cases like "ABC/ESPN+/Disney+"
            network_parts = [part.strip() for part in network_display.split('/')]
            
            for part in network_parts:
                part_upper = part.upper()
                
                # Check if it's a traditional primetime network
                is_traditional = False
                for network_key in active_networks.keys():
                    if network_key.upper() in part_upper:
                        if part not in traditional_networks:
                            traditional_networks.append(part)
                        is_traditional = True
                        break
                
                # Check if it's a streaming platform (if not traditional)
                if not is_traditional:
                    for streaming in STREAMING_SUPPLEMENTS:
                        if streaming.upper() in part_upper:
                            if part not in streaming_platforms:
                                streaming_platforms.append(part)
                            break
                    # Also check for standalone streaming services
                    standalone_streaming = ['PEACOCK', 'AMAZON PRIME', 'PRIME VIDEO', 'NETFLIX', 'APPLE TV']
                    for streaming in standalone_streaming:
                        if streaming in part_upper:
                            if part not in streaming_platforms:
                                streaming_platforms.append(part)
                            break
        
        # Determine primary network from traditional networks only
        primetime_networks_found = []
        is_primetime = False
        for network in traditional_networks:
            for network_key, network_info in active_networks.items():
                if network_key.upper() in network.upper():
                    is_primetime = True
                    primetime_networks_found.append((network_key, network, network_info['priority']))
                    break
        
        # Sort by priority to determine primary network
        primary_network = None
        if primetime_networks_found:
            primetime_networks_found.sort(key=lambda x: x[2])  # Sort by priority
            primary_network = primetime_networks_found[0][0]  # Take highest priority
        
        # If no primetime network, check for NBA TV in traditional networks
        if not primary_network:
            for network in traditional_networks:
                if any(nba_tv in network.upper() for nba_tv in ['NBA TV', 'NBATV']):
                    primary_network = 'NBA TV'
                    break
        
        # Create streamlined network summary with core fields only
        network_summary = {
            # === CORE BROADCASTER FLAGS (5) ===
            'isPrimetime': is_primetime,
            'hasNationalTV': len(traditional_networks) > 0 or len(streaming_platforms) > 0,
            'primaryNetwork': primary_network,
            'traditionalNetworks': traditional_networks,
            'streamingPlatforms': streaming_platforms,
        }
        
        return network_summary

    def _analyze_game_context(self, game: dict, game_date: str) -> dict:
        """Determine game type and importance context"""
        game_label = (game.get("gameLabel", "") or "").lower()
        week_name = (game.get("weekName", "") or "").lower()
        game_sublabel = (game.get("gameSubLabel", "") or "").lower()
        
        # Game type flags
        is_regular_season = week_name.startswith("week")
        is_allstar = "all-star" in game_label or "rising stars" in game_label
        is_playoffs = any(term in game_label for term in [
            "first round", "conf", "finals", "play-in"
        ]) and not is_allstar
        is_emiratescup = "emirates" in game_label or "cup" in game_label
        
        # Special game flags
        is_christmas = "christmas" in game_sublabel or "12/25" in game_date
        is_mlk_day = "mlk" in game_sublabel or "01/15" in game_date  # MLK Day games
        
        # Playoff round detection
        playoff_round = None
        if is_playoffs:
            if "first round" in game_label:
                playoff_round = "first_round"
            elif "conf" in game_label and "semi" in game_label:
                playoff_round = "conf_semifinals"
            elif "conf" in game_label and "finals" in game_label:
                playoff_round = "conf_finals"
            elif "nba finals" in game_label:
                playoff_round = "nba_finals"
            elif "play-in" in game_label:
                playoff_round = "play_in"
        
        return {
            # === CORE CONTEXT FLAGS (7) ===
            'isRegularSeason': is_regular_season,
            'isPlayoffs': is_playoffs,
            'isAllStar': is_allstar,
            'isEmiratesCup': is_emiratescup,
            'playoffRound': playoff_round,
            'isChristmas': is_christmas,
            'isMLKDay': is_mlk_day,
        }

    def _analyze_scheduling(self, game: dict, game_date: str) -> dict:
        """Extract scheduling and timing information"""
        day_of_week = game.get("day", "").lower()
        game_time_est = game.get("gameTimeEst", "")
        
        # Weekend detection
        is_weekend = day_of_week in ["fri", "sat", "sun"]
        
        # Time slot detection (rough estimates based on common NBA scheduling)
        time_slot = "unknown"
        if game_time_est:
            try:
                # Extract hour from time string (format varies)
                hour = 12  # Default noon if can't parse
                if "T" in game_time_est:
                    time_part = game_time_est.split("T")[1]
                    hour = int(time_part.split(":")[0])
                
                if hour < 15:  # Before 3 PM ET
                    time_slot = "afternoon"
                elif hour < 20:  # 3-8 PM ET
                    time_slot = "early_evening"
                else:  # 8 PM ET and later
                    time_slot = "primetime"
            except (ValueError, IndexError, AttributeError):
                # ValueError: int conversion fails; IndexError: split fails; AttributeError: None.split()
                time_slot = "unknown"
        
        return {
            # === CORE SCHEDULING FLAGS (3) ===
            'dayOfWeek': day_of_week,
            'isWeekend': is_weekend,
            'timeSlot': time_slot,
        }

    def _generate_season_metadata(self, all_games: list) -> dict:
        """Generate comprehensive season metadata for monitoring and analysis"""
        
        # Initialize counters with completion status tracking
        regular_season = {"total": 0, "completed": 0, "live": 0, "scheduled": 0}
        playoffs = {"total": 0, "completed": 0, "live": 0, "scheduled": 0}
        allstar = {"total": 0, "completed": 0, "live": 0, "scheduled": 0}
        preseason = {"total": 0, "completed": 0, "live": 0, "scheduled": 0}
        
        filtered_stats = {
            "allstar_games": 0,
            "invalid_team_codes": 0,
            "invalid_team_examples": []
        }
        
        backfill_games = 0
        
        for game in all_games:
            week_name = game.get("weekName", "").lower()
            game_label = game.get("gameLabel", "").lower()
            game_status = game.get("gameStatus", 1)  # 1=scheduled, 2=live, 3=final
            
            # Categorize by game type based on NBA.com fields
            if "all-star" in week_name or any(term in game_label for term in ["all-star", "rising stars"]):
                allstar["total"] += 1
                if game_status == 3:
                    allstar["completed"] += 1
                elif game_status == 2:
                    allstar["live"] += 1
                else:
                    allstar["scheduled"] += 1
                filtered_stats["allstar_games"] += 1
                
            elif any(term in game_label for term in ["play-in", "first round", "conf", "finals"]) and "all-star" not in game_label:
                # Playoff games: Play-In, First Round, Conference Semifinals/Finals, NBA Finals
                playoffs["total"] += 1
                if game_status == 3:
                    playoffs["completed"] += 1
                    if self._should_include_in_backfill(game):
                        backfill_games += 1
                elif game_status == 2:
                    playoffs["live"] += 1
                else:
                    playoffs["scheduled"] += 1
                        
            elif week_name.startswith("week"):
                # Regular season games have weekName like "Week 1", "Week 2", etc.
                regular_season["total"] += 1
                if game_status == 3:
                    regular_season["completed"] += 1
                    if self._should_include_in_backfill(game):
                        backfill_games += 1
                elif game_status == 2:
                    regular_season["live"] += 1
                else:
                    regular_season["scheduled"] += 1
                        
            else:
                # Games with empty weekName and gameLabel are likely preseason
                preseason["total"] += 1
                if game_status == 3:
                    preseason["completed"] += 1
                elif game_status == 2:
                    preseason["live"] += 1
                else:
                    preseason["scheduled"] += 1
                    # Note: We typically don't include preseason in backfill
            
            # Check for invalid team codes
            away_team = game.get("awayTeam", {}).get("teamTricode", "")
            home_team = game.get("homeTeam", {}).get("teamTricode", "")
            
            if len(away_team) != 3 or len(home_team) != 3 or not away_team.isalpha() or not home_team.isalpha():
                filtered_stats["invalid_team_codes"] += 1
                if len(filtered_stats["invalid_team_examples"]) < 3:
                    filtered_stats["invalid_team_examples"].append({
                        "game_code": game.get("gameCode", "unknown"),
                        "away_team": away_team,
                        "home_team": home_team
                    })
        
        total_games = (regular_season["total"] + playoffs["total"] + 
                    allstar["total"] + preseason["total"])
        
        total_completed = (regular_season["completed"] + playoffs["completed"] + 
                        allstar["completed"] + preseason["completed"])
        
        total_remaining = (regular_season["scheduled"] + playoffs["scheduled"] + 
                        allstar["scheduled"] + preseason["scheduled"])
        
        # Calculate season progress
        season_completion_pct = (total_completed / total_games * 100) if total_games > 0 else 0
        
        # Estimate remaining backfill games (scheduled regular season + playoffs)
        estimated_remaining_backfill = regular_season["scheduled"] + playoffs["scheduled"]
        
        return {
            "season": self.opts["actual_season_nba_format"],
            "scraped_at": self.opts["timestamp"],
            "total_games": total_games,
            "regular_season": regular_season,
            "playoffs": playoffs,
            "allstar": allstar,
            "preseason": preseason,
            "season_progress": {
                "completion_percentage": round(season_completion_pct, 1),
                "total_completed": total_completed,
                "total_remaining": total_remaining,
                "estimated_final_backfill": backfill_games + estimated_remaining_backfill
            },
            "backfill": {
                "total_games": backfill_games,
                "estimated_remaining": estimated_remaining_backfill,
                "description": "Regular season + playoffs, completed games only, excluding All-Star and invalid teams"
            },
            "filtered": filtered_stats
        }

    def _should_include_in_backfill(self, game: dict) -> bool:
        """Determine if a game should be included in backfill count for monitoring"""
        
        # Exclude All-Star games
        week_name = game.get("weekName", "").lower()
        game_label = game.get("gameLabel", "").lower()
        
        if "all-star" in week_name or any(term in game_label for term in ["all-star", "rising stars"]):
            return False
        
        # Exclude games with invalid team codes
        away_team = game.get("awayTeam", {}).get("teamTricode", "")
        home_team = game.get("homeTeam", {}).get("teamTricode", "")
        
        if (len(away_team) != 3 or len(home_team) != 3 or 
            not away_team.isalpha() or not home_team.isalpha()):
            return False
        
        # Only include completed games (status 3 = final)
        if game.get("gameStatus", 1) != 3:
            return False
        
        # Include regular season and playoff games
        if (week_name.startswith("week") or 
            any(term in game_label for term in ["play-in", "first round", "conf", "finals"]) and "all-star" not in game_label):
            return True
        
        # Exclude preseason games (empty weekName and gameLabel)
        return False
    
    def get_scraper_stats(self) -> dict:
        """Return scraper statistics"""
        return {
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
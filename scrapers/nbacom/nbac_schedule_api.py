# scrapers/nbacom/nbac_schedule_api.py
"""
NBA.com stats API schedule scraper                       v1 - 2025-07-17
------------------------------------------------------------------------
Uses the current NBA.com stats API endpoint to get season schedules.

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

logger = logging.getLogger("scraper_base")


class GetNbaComScheduleApi(ScraperBase, ScraperFlaskMixin):
    """
    NBA.com stats API schedule scraper.
    
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
            "export_mode": ExportMode.DECODED,
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
        if not isinstance(self.decoded_data, dict):
            raise DownloadDataException("Response is not a JSON object")
        
        # The actual response has 'leagueSchedule' not 'resultSets'
        if "leagueSchedule" not in self.decoded_data:
            raise DownloadDataException("Missing 'leagueSchedule' in response")
        
        league_schedule = self.decoded_data["leagueSchedule"]
        if not isinstance(league_schedule, dict):
            raise DownloadDataException("leagueSchedule is not an object")
        
        if "gameDates" not in league_schedule:
            raise DownloadDataException("Missing 'gameDates' in leagueSchedule")
        
        game_dates = league_schedule["gameDates"]
        if not isinstance(game_dates, list):
            raise DownloadDataException("gameDates is not a list")
        
        logger.info("Validation passed: %d game dates found", len(game_dates))

    def transform_data(self) -> None:
        """Transform NBA.com API response into structured data and generate metadata"""
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
                # Remove broadcaster data to keep files lean
                if 'broadcasters' in game:
                    del game['broadcasters']
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
                
                # Add the game date to each game for easier processing
                game_with_date = {
                    **game,
                    "gameDate": game_date,
                    "gameDateObj": game_date_obj.get("gameDate", "")
                }
                all_games.append(game_with_date)
        
        # Sort games by date and game sequence
        all_games.sort(key=lambda x: (x.get("gameDateEst", ""), x.get("gameSequence", 0)))
        
        # Generate season metadata
        metadata = self._generate_season_metadata(all_games)
        
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
            "gameDates": game_dates,  # Keep original structure too
            "metadata": metadata  # Store metadata here for the exporter
        }
        
        logger.info("Processed %d games across %d dates for %s season", 
                len(all_games), len(game_dates), self.opts["season_nba_format"])
        logger.info("Generated metadata: %d total games, %d backfill eligible", 
                metadata["total_games"], metadata["backfill"]["total_games"])

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
    
"""
NBA.com stats API schedule scraper                       v1 - 2025-07-17
------------------------------------------------------------------------
Uses the current NBA.com stats API endpoint to get season schedules.

URL: https://stats.nba.com/stats/scheduleleaguev2int

CLI:
    python -m scrapers.nbacom.nbac_data_schedule --season 2025 --group test
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaComScheduleApi(ScraperBase):
    """
    NBA.com stats API schedule scraper.
    
    Required opts:
        season: 4-digit start year (e.g., 2025 for 2025-26 season)
    """
    
    required_opts = ["season"]
    download_type = DownloadType.JSON
    decode_download_data = True
    header_profile = "stats"  # Use NBA stats headers
    proxy_enabled = True      # stats.nba.com may need proxy
    
    BASE_URL = "https://stats.nba.com/stats/scheduleleaguev2int"
    
    exporters = [
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
    ]
    
    def set_additional_opts(self) -> None:
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
            "SeasonType": "Regular Season"
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
        """Transform NBA.com API response into structured data"""
        league_schedule = self.decoded_data["leagueSchedule"]
        meta = self.decoded_data.get("meta", {})
        
        game_dates = league_schedule.get("gameDates", [])
        
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
                    "gameDateObj": game_date_obj.get("gameDate", "")
                }
                all_games.append(game_with_date)
        
        # Sort games by date and game sequence
        all_games.sort(key=lambda x: (x.get("gameDate", ""), x.get("gameSequence", 0)))
        
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
            "gameDates": game_dates  # Keep original structure too
        }
        
        logger.info("Processed %d games across %d dates for %s season", 
                len(all_games), len(game_dates), self.opts["season_nba_format"])
    
    def get_scraper_stats(self) -> dict:
        """Return scraper statistics"""
        return {
            "season": self.opts["season"],
            "season_nba_format": self.opts["season_nba_format"],
            "game_count": self.data.get("game_count", 0),
            "timestamp": self.opts["timestamp"]
        }


# Google Cloud Function entry point
def gcf_entry(request):  # type: ignore[valid-type]
    """Google Cloud Function entry point"""
    season = request.args.get("season")
    if not season:
        return ("Missing required parameter 'season'", 400)
    
    group = request.args.get("group", "prod")
    
    opts = {
        "season": season,
        "group": group,
        "apiKey": request.args.get("apiKey"),
        "runId": request.args.get("runId"),
    }
    
    try:
        result = GetNbaComScheduleApi().run(opts)
        if result:
            return f"NBA.com schedule scrape complete for {season}", 200
        else:
            return f"NBA.com schedule scrape failed for {season}", 500
    except Exception as e:
        logger.error("GCF error: %s", e)
        return f"NBA.com schedule scrape error: {str(e)}", 500


# CLI usage
if __name__ == "__main__":
    import argparse
    from scrapers.utils.cli_utils import add_common_args

    cli = argparse.ArgumentParser(description="NBA.com Stats API Schedule Scraper")
    cli.add_argument("--season", required=True, 
                    help="4-digit start year (e.g., 2025 for 2025-26 season)")
    add_common_args(cli)
    args = cli.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    GetNbaComScheduleApi().run(vars(args))

    
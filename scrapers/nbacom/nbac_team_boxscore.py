"""
Path: scrapers/nbacom/nbac_team_boxscore.py

NBA.com Team Box Score scraper                          v1.0 – 2025‑11‑01
---------------------------------------------------------------------------
* URL: https://stats.nba.com/stats/boxscoretraditionalv2
* Provides complete team-level statistics for each game
* Fields: FGM/FGA, 3PM/3PA, FTM/FTA, AST, REB, TOV, STL, BLK, PF, PTS

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py nbac_team_boxscore \
      --game_id 0022400561 \
      --game_date 2025-01-15 \
      --debug

  # Direct CLI execution:
  python scrapers/nbacom/nbac_team_boxscore.py \
      --game_id 0022400561 \
      --game_date 2025-01-15 \
      --debug

  # Flask web service:
  python scrapers/nbacom/nbac_team_boxscore.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone, date
from typing import Any, Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.nbacom.nbac_team_boxscore
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_team_boxscore.py
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


class GetNbaComTeamBoxscore(ScraperBase, ScraperFlaskMixin):
    """NBA.com Team Box Score scraper - provides complete team statistics per game."""

    # Flask Mixin Configuration
    scraper_name = "nbac_team_boxscore"
    required_params = ["game_id", "game_date"]
    optional_params = {
        "api_key": None,
    }

    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #
    required_opts = ["game_id", "game_date"]
    download_type = DownloadType.JSON
    decode_download_data = True
    header_profile = "stats"  # Use standard NBA stats headers
    proxy_enabled = True
    
    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "nba_com_team_boxscore"
    exporters = [
        # Production GCS export
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # Standard development export
        {
            "type": "file",
            "filename": "/tmp/nbac_team_boxscore_%(game_id)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
        # Capture group exports (for capture.py)
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

    # ------------------------------------------------------------------ #
    # URL Construction
    # ------------------------------------------------------------------ #
    BASE_URL = "https://stats.nba.com/stats/boxscoretraditionalv2"

    def set_url(self) -> None:
        """Set URL with game_id parameter"""
        game_id = self.opts["game_id"]
        
        # Build URL with all required parameters
        self.url = (
            f"{self.BASE_URL}?"
            f"GameID={game_id}&"
            f"StartPeriod=0&"
            f"EndPeriod=10&"
            f"StartRange=0&"
            f"EndRange=28800&"
            f"RangeType=0"
        )
        
        logger.info("NBA.com Team Boxscore URL: %s", self.url)

    def set_additional_opts(self) -> None:
        """Validate and normalize options"""
        super().set_additional_opts()
        
        # Validate game_id format (should be 10 digits: 0022400561)
        game_id = self.opts["game_id"]
        if not isinstance(game_id, str) or len(game_id) != 10 or not game_id.isdigit():
            raise DownloadDataException(
                f"game_id must be 10-digit NBA game ID (e.g., 0022400561), got: {game_id}"
            )
        
        # Validate and normalize game_date (YYYY-MM-DD or YYYYMMDD)
        game_date = str(self.opts["game_date"]).replace("-", "")
        if len(game_date) != 8 or not game_date.isdigit():
            raise DownloadDataException(
                f"game_date must be YYYYMMDD or YYYY-MM-DD format, got: {self.opts['game_date']}"
            )
        
        # Store normalized date (YYYYMMDD format for exporters)
        self.opts["game_date"] = game_date
        
        # Create display date (YYYY-MM-DD for logging)
        self.display_date = f"{game_date[0:4]}-{game_date[4:6]}-{game_date[6:8]}"

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """Validate the box score response"""
        try:
            if not isinstance(self.decoded_data, dict):
                error_msg = "Response is not a JSON object"
                logger.error("%s for game %s", error_msg, self.opts["game_id"])
                notify_error(
                    title="NBA.com Team Boxscore Invalid Response",
                    message=f"Response is not JSON for game {self.opts['game_id']}",
                    details={
                        'game_id': self.opts['game_id'],
                        'response_type': type(self.decoded_data).__name__,
                        'url': self.url
                    },
                    processor_name="NBA.com Team Boxscore Scraper"
                )
                raise DownloadDataException(error_msg)
                
            if "resultSets" not in self.decoded_data:
                error_msg = "Missing 'resultSets' in response"
                logger.error("%s for game %s", error_msg, self.opts["game_id"])
                notify_error(
                    title="NBA.com Team Boxscore Missing ResultSets",
                    message=f"Response missing 'resultSets' for game {self.opts['game_id']}",
                    details={
                        'game_id': self.opts['game_id'],
                        'response_keys': list(self.decoded_data.keys()),
                        'url': self.url
                    },
                    processor_name="NBA.com Team Boxscore Scraper"
                )
                raise DownloadDataException(error_msg)
                
            result_sets = self.decoded_data["resultSets"]
            if not isinstance(result_sets, list):
                error_msg = "resultSets is not a list"
                logger.error("%s for game %s", error_msg, self.opts["game_id"])
                notify_error(
                    title="NBA.com Team Boxscore Invalid ResultSets",
                    message=f"resultSets is not a list for game {self.opts['game_id']}",
                    details={
                        'game_id': self.opts['game_id'],
                        'resultSets_type': type(result_sets).__name__,
                        'url': self.url
                    },
                    processor_name="NBA.com Team Boxscore Scraper"
                )
                raise DownloadDataException(error_msg)
            
            # Find TeamStats result set
            team_stats = None
            for rs in result_sets:
                if rs.get("name") == "TeamStats":
                    team_stats = rs
                    break
            
            if not team_stats:
                error_msg = "TeamStats result set not found"
                logger.error("%s for game %s", error_msg, self.opts["game_id"])
                available_sets = [rs.get("name") for rs in result_sets]
                notify_error(
                    title="NBA.com Team Boxscore Missing TeamStats",
                    message=f"TeamStats not found in response for game {self.opts['game_id']}",
                    details={
                        'game_id': self.opts['game_id'],
                        'available_result_sets': available_sets,
                        'url': self.url
                    },
                    processor_name="NBA.com Team Boxscore Scraper"
                )
                raise DownloadDataException(error_msg)
            
            # Validate TeamStats structure
            if "headers" not in team_stats or "rowSet" not in team_stats:
                error_msg = "TeamStats missing headers or rowSet"
                logger.error("%s for game %s", error_msg, self.opts["game_id"])
                notify_error(
                    title="NBA.com Team Boxscore Invalid TeamStats",
                    message=f"TeamStats structure invalid for game {self.opts['game_id']}",
                    details={
                        'game_id': self.opts['game_id'],
                        'team_stats_keys': list(team_stats.keys()),
                        'url': self.url
                    },
                    processor_name="NBA.com Team Boxscore Scraper"
                )
                raise DownloadDataException(error_msg)
            
            # Validate we have data for both teams
            row_set = team_stats["rowSet"]
            if len(row_set) != 2:
                error_msg = f"Expected 2 teams for game {self.opts['game_id']}, got {len(row_set)}"
                logger.error(error_msg)
                notify_error(
                    title="NBA.com Team Boxscore Invalid Team Count",
                    message=error_msg,
                    details={
                        'game_id': self.opts['game_id'],
                        'team_count': len(row_set),
                        'url': self.url
                    },
                    processor_name="NBA.com Team Boxscore Scraper"
                )
                raise DownloadDataException(error_msg)
            
            logger.info(
                "Validation passed: %d teams found for game %s",
                len(row_set),
                self.opts["game_id"]
            )
                
        except DownloadDataException:
            raise
        except Exception as e:
            logger.error("Unexpected validation error for game %s: %s", self.opts["game_id"], e)
            notify_error(
                title="NBA.com Team Boxscore Validation Error",
                message=f"Unexpected validation error for game {self.opts['game_id']}: {str(e)}",
                details={
                    'game_id': self.opts['game_id'],
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'url': self.url
                },
                processor_name="NBA.com Team Boxscore Scraper"
            )
            raise DownloadDataException(f"Validation failed: {e}") from e

    # ------------------------------------------------------------------ #
    # Transform
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        """Transform box score data into clean team statistics"""
        try:
            # Extract TeamStats result set
            team_stats = None
            for rs in self.decoded_data["resultSets"]:
                if rs.get("name") == "TeamStats":
                    team_stats = rs
                    break
            
            if not team_stats:
                raise DownloadDataException("TeamStats not found in transform")
            
            headers = team_stats["headers"]
            headers_map = {h: i for i, h in enumerate(headers)}
            
            # Process both teams
            teams = []
            for row in team_stats["rowSet"]:
                team_data = {
                    # Identity
                    "gameId": row[headers_map["GAME_ID"]],
                    "teamId": row[headers_map["TEAM_ID"]],
                    "teamName": row[headers_map["TEAM_NAME"]],
                    "teamAbbreviation": row[headers_map["TEAM_ABBREVIATION"]],
                    "teamCity": row[headers_map["TEAM_CITY"]],
                    
                    # Game time
                    "minutes": row[headers_map["MIN"]],
                    
                    # Shooting
                    "fieldGoals": {
                        "made": row[headers_map["FGM"]],
                        "attempted": row[headers_map["FGA"]],
                        "percentage": row[headers_map["FG_PCT"]],
                    },
                    "threePointers": {
                        "made": row[headers_map["FG3M"]],
                        "attempted": row[headers_map["FG3A"]],
                        "percentage": row[headers_map["FG3_PCT"]],
                    },
                    "freeThrows": {
                        "made": row[headers_map["FTM"]],
                        "attempted": row[headers_map["FTA"]],
                        "percentage": row[headers_map["FT_PCT"]],
                    },
                    
                    # Rebounds
                    "rebounds": {
                        "offensive": row[headers_map["OREB"]],
                        "defensive": row[headers_map["DREB"]],
                        "total": row[headers_map["REB"]],
                    },
                    
                    # Other stats
                    "assists": row[headers_map["AST"]],
                    "steals": row[headers_map["STL"]],
                    "blocks": row[headers_map["BLK"]],
                    "turnovers": row[headers_map["TO"]],
                    "personalFouls": row[headers_map["PF"]],
                    "points": row[headers_map["PTS"]],
                    "plusMinus": row[headers_map["PLUS_MINUS"]],
                }
                
                teams.append(team_data)
            
            self.data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "gameId": self.opts["game_id"],
                "gameDate": self.display_date,
                "teamCount": len(teams),
                "teams": teams,
                "source": "nba_team_boxscore"
            }
            
            logger.info(
                "Processed %d teams for game %s (%s)",
                len(teams),
                self.opts["game_id"],
                self.display_date
            )
            
        except KeyError as e:
            logger.error("Transformation failed - missing key %s for game %s", e, self.opts["game_id"])
            notify_error(
                title="NBA.com Team Boxscore Transformation Failed",
                message=f"Data transformation failed - missing key for game {self.opts['game_id']}: {str(e)}",
                details={
                    'game_id': self.opts['game_id'],
                    'missing_key': str(e),
                    'error_type': 'KeyError'
                },
                processor_name="NBA.com Team Boxscore Scraper"
            )
            raise DownloadDataException(f"Transformation failed: missing key {e}") from e
        except Exception as e:
            logger.error("Transformation failed for game %s: %s", self.opts["game_id"], e)
            notify_error(
                title="NBA.com Team Boxscore Transformation Error",
                message=f"Unexpected transformation error for game {self.opts['game_id']}: {str(e)}",
                details={
                    'game_id': self.opts['game_id'],
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                processor_name="NBA.com Team Boxscore Scraper"
            )
            raise DownloadDataException(f"Transformation failed: {e}") from e

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        """Return scraper statistics"""
        return {
            "gameId": self.opts["game_id"],
            "gameDate": self.display_date,
            "teamCount": self.data.get("teamCount", 0),
            "source": "nba_team_boxscore"
        }


# --------------------------------------------------------------------------- #
# Flask and CLI entry points
# --------------------------------------------------------------------------- #

create_app = convert_existing_flask_scraper(GetNbaComTeamBoxscore)

if __name__ == "__main__":
    main = GetNbaComTeamBoxscore.create_cli_and_flask_main()
    main()
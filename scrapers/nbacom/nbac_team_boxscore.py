"""
Path: scrapers/nbacom/nbac_team_boxscore.py

NBA.com Team Box Score scraper                          v2.0 – 2026‑01‑22
---------------------------------------------------------------------------
* URL: https://stats.nba.com/stats/boxscoretraditionalv3
* Provides complete team-level statistics for each game
* Fields: FGM/FGA, 3PM/3PA, FTM/FTA, AST, REB, TOV, STL, BLK, PF, PTS
* Includes injury data via player comment field
*
* Note: V2 endpoint deprecated for 2025-26 season, migrated to V3

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
    # V3 endpoint - V2 was deprecated for 2025-26 season
    BASE_URL = "https://stats.nba.com/stats/boxscoretraditionalv3"

    def set_url(self) -> None:
        """Set URL with game_id parameter"""
        game_id = self.opts["game_id"]

        # Build URL with all required parameters
        # V3 uses same parameters as V2
        self.url = (
            f"{self.BASE_URL}?"
            f"GameID={game_id}&"
            f"StartPeriod=0&"
            f"EndPeriod=10&"
            f"StartRange=0&"
            f"EndRange=28800&"
            f"RangeType=0"
        )

        logger.info("NBA.com Team Boxscore URL (V3): %s", self.url)

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
        """Validate the V3 box score response.

        V3 response structure:
        {
            "meta": {...},
            "boxScoreTraditional": {
                "gameId": "...",
                "homeTeam": {"teamId": ..., "statistics": {...}, "players": [...]},
                "awayTeam": {"teamId": ..., "statistics": {...}, "players": [...]}
            }
        }
        """
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

            # V3 uses boxScoreTraditional instead of resultSets
            if "boxScoreTraditional" not in self.decoded_data:
                error_msg = "Missing 'boxScoreTraditional' in response"
                logger.error("%s for game %s", error_msg, self.opts["game_id"])
                notify_error(
                    title="NBA.com Team Boxscore Missing Data",
                    message=f"Response missing 'boxScoreTraditional' for game {self.opts['game_id']}",
                    details={
                        'game_id': self.opts['game_id'],
                        'response_keys': list(self.decoded_data.keys()),
                        'url': self.url
                    },
                    processor_name="NBA.com Team Boxscore Scraper"
                )
                raise DownloadDataException(error_msg)

            box_score = self.decoded_data["boxScoreTraditional"]
            if not isinstance(box_score, dict):
                error_msg = "boxScoreTraditional is not a dict"
                logger.error("%s for game %s", error_msg, self.opts["game_id"])
                notify_error(
                    title="NBA.com Team Boxscore Invalid Structure",
                    message=f"boxScoreTraditional is not a dict for game {self.opts['game_id']}",
                    details={
                        'game_id': self.opts['game_id'],
                        'box_score_type': type(box_score).__name__,
                        'url': self.url
                    },
                    processor_name="NBA.com Team Boxscore Scraper"
                )
                raise DownloadDataException(error_msg)

            # V3 has homeTeam and awayTeam nested objects
            missing_teams = []
            for team_key in ["homeTeam", "awayTeam"]:
                if team_key not in box_score:
                    missing_teams.append(team_key)

            if missing_teams:
                error_msg = f"Missing team data: {missing_teams}"
                logger.error("%s for game %s", error_msg, self.opts["game_id"])
                notify_error(
                    title="NBA.com Team Boxscore Missing Teams",
                    message=f"Missing team data for game {self.opts['game_id']}: {missing_teams}",
                    details={
                        'game_id': self.opts['game_id'],
                        'available_keys': list(box_score.keys()),
                        'url': self.url
                    },
                    processor_name="NBA.com Team Boxscore Scraper"
                )
                raise DownloadDataException(error_msg)

            # Validate both teams have statistics
            for team_key in ["homeTeam", "awayTeam"]:
                team = box_score[team_key]
                if "statistics" not in team:
                    error_msg = f"{team_key} missing 'statistics'"
                    logger.error("%s for game %s", error_msg, self.opts["game_id"])
                    notify_error(
                        title="NBA.com Team Boxscore Invalid Team Data",
                        message=f"{team_key} missing statistics for game {self.opts['game_id']}",
                        details={
                            'game_id': self.opts['game_id'],
                            'team_key': team_key,
                            'team_keys': list(team.keys()),
                            'url': self.url
                        },
                        processor_name="NBA.com Team Boxscore Scraper"
                    )
                    raise DownloadDataException(error_msg)

            logger.info(
                "Validation passed: home=%s, away=%s for game %s",
                box_score["homeTeam"].get("teamTricode", "?"),
                box_score["awayTeam"].get("teamTricode", "?"),
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
        """Transform V3 box score data into clean team statistics.

        V3 structure: boxScoreTraditional.homeTeam/awayTeam.statistics
        Also extracts injury information from player comments.
        """
        try:
            box_score = self.decoded_data["boxScoreTraditional"]

            # Process both teams
            teams = []
            injured_players = []

            for team_key in ["homeTeam", "awayTeam"]:
                team = box_score[team_key]
                stats = team["statistics"]

                team_data = {
                    # Identity
                    "gameId": box_score.get("gameId", self.opts["game_id"]),
                    "teamId": team.get("teamId"),
                    "teamName": team.get("teamName"),
                    "teamAbbreviation": team.get("teamTricode"),
                    "teamCity": team.get("teamCity"),

                    # Game time
                    "minutes": stats.get("minutes"),

                    # Shooting
                    "fieldGoals": {
                        "made": stats.get("fieldGoalsMade"),
                        "attempted": stats.get("fieldGoalsAttempted"),
                        "percentage": stats.get("fieldGoalsPercentage"),
                    },
                    "threePointers": {
                        "made": stats.get("threePointersMade"),
                        "attempted": stats.get("threePointersAttempted"),
                        "percentage": stats.get("threePointersPercentage"),
                    },
                    "freeThrows": {
                        "made": stats.get("freeThrowsMade"),
                        "attempted": stats.get("freeThrowsAttempted"),
                        "percentage": stats.get("freeThrowsPercentage"),
                    },

                    # Rebounds
                    "rebounds": {
                        "offensive": stats.get("reboundsOffensive"),
                        "defensive": stats.get("reboundsDefensive"),
                        "total": stats.get("reboundsTotal"),
                    },

                    # Other stats
                    "assists": stats.get("assists"),
                    "steals": stats.get("steals"),
                    "blocks": stats.get("blocks"),
                    "turnovers": stats.get("turnovers"),
                    "personalFouls": stats.get("foulsPersonal"),
                    "points": stats.get("points"),
                    "plusMinus": stats.get("plusMinusPoints"),

                    # V3 metadata
                    "isHome": team_key == "homeTeam",
                }

                teams.append(team_data)

                # Extract injured players from player comments (V3 feature)
                for player in team.get("players", []):
                    comment = player.get("comment", "")
                    if comment:  # Non-empty comment indicates injury/DNP
                        injured_players.append({
                            "playerId": player.get("personId"),
                            "playerName": f"{player.get('firstName', '')} {player.get('familyName', '')}".strip(),
                            "teamId": team.get("teamId"),
                            "teamAbbreviation": team.get("teamTricode"),
                            "comment": comment,
                        })

            self.data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "gameId": self.opts["game_id"],
                "gameDate": self.display_date,
                "teamCount": len(teams),
                "teams": teams,
                "injuredPlayers": injured_players,  # V3 bonus: injury info!
                "source": "nba_team_boxscore_v3"
            }

            logger.info(
                "Processed %d teams, %d injured players for game %s (%s)",
                len(teams),
                len(injured_players),
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
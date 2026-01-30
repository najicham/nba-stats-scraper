"""
File: scrapers/nbacom/nbac_player_boxscore.py

Player box-score scraper (leaguegamelog)                 v2 - 2025-06-16
-----------------------------------------------------------------------
Downloads per-player rows for a single game-date via
https://stats.nba.com/stats/leaguegamelog.

Features preserved from v1
--------------------------
* Three exporters (two local files + one GCS), all using ExportMode.RAW
* Proxy support for cloud IP blocks
* Helper add_dash_to_season()
* Flask/Cloud Run entry point and local CLI

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py nbac_player_boxscore \
      --gamedate 20250115 \
      --debug

  # Direct CLI execution:
  python scrapers/nbacom/nbac_player_boxscore.py --gamedate 20250115 --debug

  # Flask web service:
  python scrapers/nbacom/nbac_player_boxscore.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import List, Optional

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.nbacom.nbac_player_boxscore
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_player_boxscore.py
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

# Schedule service for season type detection
from shared.utils.schedule import NBAScheduleService

logger = logging.getLogger("scraper_base")


class GetNbaComPlayerBoxscore(ScraperBase, ScraperFlaskMixin):
    """Downloads per-player rows for a single game-date via leaguegamelog."""

    # Flask Mixin Configuration
    scraper_name = "nbac_player_boxscore"
    required_params = ["gamedate"]
    optional_params = {
        "season": None,
        "season_type": None,
    }

    # ------------------------------------------------------------------ #
    # Config and exporters
    # ------------------------------------------------------------------ #
    required_opts: List[str] = ["gamedate"]              # YYYYMMDD or YYYY-MM-DD
    additional_opts = ["nba_season_from_gamedate", "nba_seasontype_from_gamedate"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = "stats"
    proxy_enabled: bool = True                           # stats.nba.com often rate‑limits GCP

    GCS_PATH_KEY = "nba_com_player_boxscore"
    exporters = [
        {
            "type": "gcs",
            #"key": "nbacom/player-boxscore/%(season)s/%(gamedate)s/%(time)s.json",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DECODED,  # Changed from DATA to DECODED
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomplayerboxscore2.json",
            "export_mode": ExportMode.DATA,
            "groups": ["test", "file"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomplayerboxscore3.json",
            "export_mode": ExportMode.RAW,
            "groups": ["test", "file2"],
        },
        # ADD THESE CAPTURE EXPORTERS:
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
    # Additional opts helper - FIXED
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        
        raw_date = self.opts["gamedate"].replace("-", "")
        if len(raw_date) != 8 or not raw_date.isdigit():
            raise DownloadDataException("gamedate must be YYYYMMDD or YYYY-MM-DD")
        # normalise
        self.opts["gamedate"] = raw_date

        # NBA season logic: seasons run October to April (next year)
        year = int(raw_date[0:4])
        month = int(raw_date[4:6])
        
        # If month is Jan-Sep, it's part of the previous season start year
        if month < 10:  # January through September
            season_start_year = year - 1
        else:  # October, November, December
            season_start_year = year
        
        # FIX: Check if value is None/empty before setting
        # setdefault() doesn't work if key exists with None value
        if not self.opts.get("season"):
            self.opts["season"] = str(season_start_year)

        # Auto-detect season type if not explicitly set
        if not self.opts.get("season_type"):
            # Format date as YYYY-MM-DD for schedule lookup
            formatted_date = f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
            self.opts["season_type"] = self._detect_season_type(formatted_date)
            logger.info(f"Auto-detected season_type: {self.opts['season_type']} for date {raw_date}")

        # Skip All-Star games - they use non-NBA teams (e.g., "Team LeBron", "Team Durant")
        # and are not useful for player prop predictions
        if self.opts.get("season_type") == "All Star":
            raise DownloadDataException(
                f"Skipping All-Star game on {raw_date} - exhibition games not useful for predictions"
            )

        self.opts["time"] = datetime.now(timezone.utc).strftime("%H-%M-%S")

    # Class-level schedule service (lazy initialization)
    _schedule_service: Optional[NBAScheduleService] = None

    @classmethod
    def _get_schedule_service(cls) -> NBAScheduleService:
        """Get or create the schedule service instance."""
        if cls._schedule_service is None:
            cls._schedule_service = NBAScheduleService()
        return cls._schedule_service

    def _detect_season_type(self, game_date: str) -> str:
        """
        Auto-detect season type from schedule database.

        Uses the NBAScheduleService to look up the correct season_type
        based on actual game data, handling all game types correctly:
        - Regular Season (including Emirates NBA Cup)
        - Playoffs (First Round through NBA Finals)
        - Play-In Tournament
        - All-Star Weekend
        - Pre Season

        Args:
            game_date: Date string in YYYY-MM-DD format

        Returns:
            NBA.com API season_type string (e.g., "Regular Season", "Playoffs",
            "PlayIn", "All Star", "Pre Season")
        """
        try:
            schedule = self._get_schedule_service()
            season_type = schedule.get_season_type_for_date(game_date)
            return season_type
        except Exception as e:
            logger.warning("Failed to detect season type from schedule for %s: %s. "
                          "Falling back to Regular Season.", game_date, e)
            return "Regular Season"

    # ------------------------------------------------------------------ #
    # URL builder
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        gd = self.opts["gamedate"]
        gd_fmt = f"{gd[0:4]}-{gd[4:6]}-{gd[6:8]}"
        season_dash = self.add_dash_to_season(self.opts["season"])
        season_type = self.opts["season_type"].replace(" ", "+")
        self.url = (
            "https://stats.nba.com/stats/leaguegamelog?"
            f"Counter=1000&DateFrom={gd_fmt}&DateTo={gd_fmt}&Direction=DESC&"
            f"LeagueID=00&PlayerOrTeam=P&Season={season_dash}&SeasonType={season_type}&Sorter=DATE"
        )
        logger.info("Constructed PlayerBoxscore URL: %s", self.url)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """Validate the leaguegamelog response"""
        try:
            # Check basic response structure
            if not isinstance(self.decoded_data, dict):
                error_msg = "Response is not a JSON object"
                logger.error("%s for gamedate %s", error_msg, self.opts["gamedate"])
                try:
                    notify_error(
                        title="NBA.com Player Boxscore Invalid Response",
                        message=f"Response is not a JSON object for gamedate {self.opts['gamedate']}",
                        details={
                            'gamedate': self.opts['gamedate'],
                            'season': self.opts['season'],
                            'season_type': self.opts['season_type'],
                            'response_type': type(self.decoded_data).__name__,
                            'url': self.url
                        },
                        processor_name="NBA.com Player Boxscore Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
            
            # Check for resultSets
            rs = self.decoded_data.get("resultSets", [])
            if not rs:
                error_msg = "No resultSets in leaguegamelog JSON"
                logger.error("%s for gamedate %s", error_msg, self.opts["gamedate"])
                try:
                    notify_error(
                        title="NBA.com Player Boxscore Missing ResultSets",
                        message=f"No resultSets in response for gamedate {self.opts['gamedate']}",
                        details={
                            'gamedate': self.opts['gamedate'],
                            'season': self.opts['season'],
                            'season_type': self.opts['season_type'],
                            'response_keys': list(self.decoded_data.keys()),
                            'url': self.url
                        },
                        processor_name="NBA.com Player Boxscore Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
            
            # Check for rowSet in first result
            if "rowSet" not in rs[0]:
                error_msg = "Missing rowSet in leaguegamelog resultSets"
                logger.error("%s for gamedate %s", error_msg, self.opts["gamedate"])
                try:
                    notify_error(
                        title="NBA.com Player Boxscore Missing RowSet",
                        message=f"Missing rowSet in response for gamedate {self.opts['gamedate']}",
                        details={
                            'gamedate': self.opts['gamedate'],
                            'season': self.opts['season'],
                            'season_type': self.opts['season_type'],
                            'result_set_keys': list(rs[0].keys()) if rs and isinstance(rs[0], dict) else [],
                            'url': self.url
                        },
                        processor_name="NBA.com Player Boxscore Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
            
            # Check if rowSet is empty
            if not rs[0]["rowSet"]:
                error_msg = "No player rows in leaguegamelog JSON"
                logger.error("%s for gamedate %s", error_msg, self.opts["gamedate"])
                try:
                    notify_error(
                        title="NBA.com Player Boxscore No Players",
                        message=f"No player rows found for gamedate {self.opts['gamedate']}",
                        details={
                            'gamedate': self.opts['gamedate'],
                            'season': self.opts['season'],
                            'season_type': self.opts['season_type'],
                            'url': self.url
                        },
                        processor_name="NBA.com Player Boxscore Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
            
            player_count = len(rs[0]["rowSet"])
            logger.info("Found %d players in rowSet for gamedate=%s.", player_count, self.opts["gamedate"])
            
            # Warning for suspiciously low player count (typical NBA game has 20-30 players)
            min_players = int(os.environ.get('PLAYER_BOXSCORE_MIN_PLAYERS', '10'))
            if player_count < min_players:
                logger.warning("Low player count (%d) for gamedate %s", player_count, self.opts["gamedate"])
                try:
                    notify_warning(
                        title="NBA.com Player Boxscore Low Player Count",
                        message=f"Low player count ({player_count}) for gamedate {self.opts['gamedate']}",
                        details={
                            'gamedate': self.opts['gamedate'],
                            'season': self.opts['season'],
                            'season_type': self.opts['season_type'],
                            'player_count': player_count,
                            'threshold': min_players,
                            'url': self.url
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
        except DownloadDataException:
            # Already handled and notified above
            raise
        except Exception as e:
            logger.error("Unexpected validation error for gamedate %s: %s", self.opts["gamedate"], e)
            try:
                notify_error(
                    title="NBA.com Player Boxscore Validation Error",
                    message=f"Unexpected validation error for gamedate {self.opts['gamedate']}: {str(e)}",
                    details={
                        'gamedate': self.opts['gamedate'],
                        'season': self.opts['season'],
                        'season_type': self.opts['season_type'],
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'url': self.url
                    },
                    processor_name="NBA.com Player Boxscore Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Validation failed: {e}") from e

    # ------------------------------------------------------------------ #
    # Transform data to populate self.data for execution logging
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        """
        Transform decoded NBA.com leaguegamelog response into self.data.

        This populates self.data with player record count so that execution
        logging correctly reports 'success' instead of 'no_data'.

        Note: The actual GCS export uses ExportMode.DECODED (self.decoded_data),
        but execution logging checks self.data to determine record count.
        """
        rows = self.decoded_data.get("resultSets", [{}])[0].get("rowSet", [])
        self.data = {
            "player_count": len(rows),
            "records_found": len(rows),
            "gamedate": self.opts.get("gamedate"),
            "season": self.opts.get("season"),
            "season_type": self.opts.get("season_type"),
        }
        logger.debug(f"transform_data: populated self.data with {len(rows)} player records")

    # ------------------------------------------------------------------ #
    # should_save_data mirrors original logic
    # ------------------------------------------------------------------ #
    def should_save_data(self) -> bool:
        rows = self.decoded_data["resultSets"][0]["rowSet"]
        return len(rows) > 0

    # ------------------------------------------------------------------ #
    # Helper
    # ------------------------------------------------------------------ #
    @staticmethod
    def add_dash_to_season(season_str: str) -> str:
        return season_str if "-" in season_str else f"{season_str}-{(int(season_str)+1)%100:02d}"

    # ------------------------------------------------------------------ #
    # Stats line
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        if hasattr(self, 'data') and self.data:
            return {
                "records_found": self.data.get("player_count", 0),
                "gamedate": self.opts["gamedate"],
                "season": self.opts["season"],
                "season_type": self.opts["season_type"],
                "source": "nba_player_boxscore"
            }
        else:
            # Fallback to original logic
            rows = self.decoded_data["resultSets"][0]["rowSet"]
            return {
                "records_found": len(rows),
                "gamedate": self.opts["gamedate"],
                "season": self.opts["season"],
                "season_type": self.opts["season_type"],
            }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetNbaComPlayerBoxscore)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetNbaComPlayerBoxscore.create_cli_and_flask_main()
    main()
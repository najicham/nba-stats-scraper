"""
File: scrapers/nbacom/nbac_scoreboard_v2.py

NBA.com Scoreboard V2 scraper                           v3.2 – 2025‑07‑17
---------------------------------------------------------------------------
* URL: https://stats.nba.com/stats/scoreboardV2
* V3 endpoint is deprecated/blocked, so we go straight to V2
Updated to skip V3 and use reliable V2 endpoint directly.

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py nbac_scoreboard_v2 \
      --gamedate 20250120 \
      --debug

  # Direct CLI execution:
  python scrapers/nbacom/nbac_scoreboard_v2.py --gamedate 20250120 --debug

  # Flask web service:
  python scrapers/nbacom/nbac_scoreboard_v2.py --serve --debug
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
    # Module execution: python -m scrapers.nbacom.nbac_scoreboard_v2
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_scoreboard_v2.py
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


class GetNbaComScoreboardV2(ScraperBase, ScraperFlaskMixin):
    """NBA.com Scoreboard V2 scraper with V3 format conversion and rich data extraction."""

    # Flask Mixin Configuration
    scraper_name = "nbac_scoreboard_v2"
    required_params = ["gamedate"]
    optional_params = {
        "api_key": None,
    }

    # ------------------------------------------------------------------ #
    # Config - Updated to match other scrapers
    # ------------------------------------------------------------------ #
    required_opts = ["gamedate"]  # YYYYMMDD or YYYY-MM-DD
    download_type = DownloadType.JSON
    decode_download_data = True
    header_profile = "stats"  # Use standard NBA stats headers
    proxy_enabled = True      # NBA.com may need proxy
    
    # ------------------------------------------------------------------ #
    # Exporters - Updated to include capture group
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "nba_com_scoreboard_v2"
    exporters = [
        # Production GCS export
        {
            "type": "gcs",
            #"key": "nba/game_ids/%(gamedate)s/game_ids_stats.json",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # Standard development export
        {
            "type": "file",
            "filename": "/tmp/nba_game_ids_stats_%(gamedate)s.json",
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
    # URL helpers
    # ------------------------------------------------------------------ #
    BASE_V3 = "https://stats.nba.com/stats/scoreboardv3"
    BASE_V2 = "https://stats.nba.com/stats/scoreboardV2"

    def _yyyy_mm_dd(self) -> str:
        """Convert gamedate to YYYY-MM-DD format"""
        raw = self.opts["gamedate"].replace("-", "")
        if len(raw) != 8 or not raw.isdigit():
            raise DownloadDataException("gamedate must be YYYYMMDD or YYYY‑MM‑DD")
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"

    def _mm_dd_yyyy(self) -> str:
        """Convert gamedate to MM/DD/YYYY format for NBA.com"""
        ymd = self._yyyy_mm_dd()
        yyyy, mm, dd = ymd.split("-")
        return f"{mm}/{dd}/{yyyy}"

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        """Normalize gamedate for exporters"""
        # Normalize date for exporters (remove dashes)
        self.opts["gamedate"] = self._yyyy_mm_dd().replace("-", "")

    def download_and_decode(self) -> None:
        """Download using V2 endpoint with proper proxy handling"""
        try:
            # Use base class download methods which handle proxy logic
            super().download_and_decode()
            
            # Check if we got valid V3 format (unlikely but possible)
            if self._is_valid_v3_response():
                logger.info("Received V3 format response")
                return
                
        except Exception as exc_v3:
            logger.warning("V3/Direct download failed (%s). Trying V2 endpoint.", exc_v3)
        
        # Fallback to V2 endpoint
        mmddyyyy = self._mm_dd_yyyy()
        self.url = f"{self.BASE_V2}?GameDate={mmddyyyy}&LeagueID=00&DayOffset=0"
        logger.info("Falling back to V2 URL: %s", self.url)
        
        # Use base class download which handles proxy properly
        try:
            super().download_and_decode()
            
            # Validate and convert V2 response
            if self._is_valid_v2_response(self.decoded_data):
                # Store original for rich data extraction
                self._original_v2_data = self.decoded_data
                # Convert to V3 format
                self.decoded_data = self._v2_to_v3(self.decoded_data)
                logger.info("Successfully converted V2 response to V3 format")
            else:
                error_msg = "Invalid V2 response structure"
                logger.error("%s for gamedate %s", error_msg, self.opts["gamedate"])
                try:
                    notify_error(
                        title="NBA.com Scoreboard V2 Invalid Response",
                        message=f"Invalid V2 response structure for gamedate {self.opts['gamedate']}",
                        details={
                            'gamedate': self.opts['gamedate'],
                            'url': self.url,
                            'has_result_sets': 'resultSets' in self.decoded_data if isinstance(self.decoded_data, dict) else False,
                            'response_type': type(self.decoded_data).__name__
                        },
                        processor_name="NBA.com Scoreboard V2 Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
        except DownloadDataException:
            # Already handled above
            raise
        except Exception as e:
            error_msg = f"Both V3 and V2 download attempts failed: {e}"
            logger.error("Download failed for gamedate %s: %s", self.opts["gamedate"], e)
            try:
                notify_error(
                    title="NBA.com Scoreboard V2 Download Failed",
                    message=f"All download attempts failed for gamedate {self.opts['gamedate']}: {str(e)}",
                    details={
                        'gamedate': self.opts['gamedate'],
                        'v2_url': self.url,
                        'error': str(e),
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Scoreboard V2 Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(error_msg)

    # Also update set_url to start with V2 directly since V3 doesn't work:
    def set_url(self) -> None:
        """Set URL to V2 endpoint directly (V3 is broken)"""
        mmddyyyy = self._mm_dd_yyyy()
        self.url = f"{self.BASE_V2}?GameDate={mmddyyyy}&LeagueID=00&DayOffset=0"
        logger.info("NBA.com Scoreboard V2 URL: %s", self.url)

    # Add helper methods:
    def _is_valid_v3_response(self) -> bool:
        """Check if response is valid V3 format"""
        return (isinstance(self.decoded_data, dict) and 
                "scoreboard" in self.decoded_data and
                isinstance(self.decoded_data["scoreboard"], dict))

    def _is_valid_v2_response(self, data: dict) -> bool:
        """Check if response is valid V2 format"""
        return (isinstance(data, dict) and 
                "resultSets" in data and
                isinstance(data["resultSets"], list))

    # ------------------------------------------------------------------ #
    # Schema normalizer (V2 → V3) - Same logic as before
    # ------------------------------------------------------------------ #
    def _v2_to_v3(self, v2: dict) -> dict:
        """Convert V2 response to V3 format with scores and key details"""
        try:
            # Pull GameHeader rows
            gh = next(s for s in v2["resultSets"] if s["name"] == "GameHeader")
            idx_gh = {h: i for i, h in enumerate(gh["headers"])}

            # Build lookup from LineScore for team abbreviations AND scores
            ls = next(s for s in v2["resultSets"] if s["name"] == "LineScore")
            idx_ls = {h: i for i, h in enumerate(ls["headers"])}
            
            # Map (gameId, teamId) -> team data including scores
            team_data = {}
            for row in ls["rowSet"]:
                game_id = row[idx_ls["GAME_ID"]]
                team_id = row[idx_ls["TEAM_ID"]]
                team_data[(game_id, team_id)] = {
                    "teamTricode": row[idx_ls["TEAM_ABBREVIATION"]],
                    "teamName": row[idx_ls["TEAM_NAME"]],
                    "teamCity": row[idx_ls["TEAM_CITY_NAME"]],
                    "winsLosses": row[idx_ls["TEAM_WINS_LOSSES"]],
                    "points": row[idx_ls["PTS"]],
                    "quarters": {
                        "q1": row[idx_ls["PTS_QTR1"]],
                        "q2": row[idx_ls["PTS_QTR2"]], 
                        "q3": row[idx_ls["PTS_QTR3"]],
                        "q4": row[idx_ls["PTS_QTR4"]],
                        "ot1": row[idx_ls.get("PTS_OT1")],
                        "ot2": row[idx_ls.get("PTS_OT2")],
                    },
                    "stats": {
                        "fgPct": row[idx_ls["FG_PCT"]],
                        "ftPct": row[idx_ls["FT_PCT"]],
                        "fg3Pct": row[idx_ls["FG3_PCT"]],
                        "assists": row[idx_ls["AST"]],
                        "rebounds": row[idx_ls["REB"]],
                        "turnovers": row[idx_ls["TOV"]],
                    }
                }

            games: List[dict] = []
            for row in gh["rowSet"]:
                game_id = row[idx_gh["GAME_ID"]]
                home_id = row[idx_gh["HOME_TEAM_ID"]]
                away_id = row[idx_gh["VISITOR_TEAM_ID"]]
                
                # Get team data with scores
                home_team_data = team_data.get((game_id, home_id), {})
                away_team_data = team_data.get((game_id, away_id), {})
                
                games.append({
                    "gameId": game_id,
                    "homeTeam": {
                        "teamTricode": home_team_data.get("teamTricode"),
                        "teamName": home_team_data.get("teamName"),
                        "teamCity": home_team_data.get("teamCity"),
                        "winsLosses": home_team_data.get("winsLosses"),
                        "points": home_team_data.get("points"),
                        "quarters": home_team_data.get("quarters", {}),
                        "stats": home_team_data.get("stats", {}),
                    },
                    "awayTeam": {
                        "teamTricode": away_team_data.get("teamTricode"),
                        "teamName": away_team_data.get("teamName"), 
                        "teamCity": away_team_data.get("teamCity"),
                        "winsLosses": away_team_data.get("winsLosses"),
                        "points": away_team_data.get("points"),
                        "quarters": away_team_data.get("quarters", {}),
                        "stats": away_team_data.get("stats", {}),
                    },
                    "gameStatus": row[idx_gh["GAME_STATUS_ID"]],
                    "gameStatusText": row[idx_gh["GAME_STATUS_TEXT"]],
                    "gameEt": row[idx_gh["GAME_DATE_EST"]],
                    "gameCode": row[idx_gh["GAMECODE"]],
                    "gameSequence": row[idx_gh["GAME_SEQUENCE"]],
                    "season": row[idx_gh["SEASON"]],
                    # Add venue and broadcast info
                    "arenaName": row[idx_gh.get("ARENA_NAME")],
                    "broadcasts": {
                        "national": row[idx_gh.get("NATL_TV_BROADCASTER_ABBREVIATION")],
                        "home": row[idx_gh.get("HOME_TV_BROADCASTER_ABBREVIATION")],
                        "away": row[idx_gh.get("AWAY_TV_BROADCASTER_ABBREVIATION")],
                    },
                    # Add live game state
                    "livePeriod": row[idx_gh.get("LIVE_PERIOD")],
                    "livePcTime": row[idx_gh.get("LIVE_PC_TIME")],
                    "livePeriodTimeBcast": row[idx_gh.get("LIVE_PERIOD_TIME_BCAST")],
                })

            return {"scoreboard": {"games": games}}
            
        except KeyError as e:
            logger.error("V2 to V3 conversion failed - missing key %s for gamedate %s", e, self.opts["gamedate"])
            try:
                notify_error(
                    title="NBA.com Scoreboard V2 Conversion Failed",
                    message=f"V2 to V3 conversion failed - missing expected key for gamedate {self.opts['gamedate']}: {str(e)}",
                    details={
                        'gamedate': self.opts['gamedate'],
                        'missing_key': str(e),
                        'error_type': 'KeyError',
                        'url': self.url
                    },
                    processor_name="NBA.com Scoreboard V2 Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            # Fallback to minimal conversion if detailed fails
            return self._v2_to_v3_minimal(v2)
        except Exception as e:
            logger.error("V2 to V3 conversion failed for gamedate %s: %s", self.opts["gamedate"], e)
            try:
                notify_error(
                    title="NBA.com Scoreboard V2 Conversion Error",
                    message=f"V2 to V3 conversion error for gamedate {self.opts['gamedate']}: {str(e)}",
                    details={
                        'gamedate': self.opts['gamedate'],
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'url': self.url
                    },
                    processor_name="NBA.com Scoreboard V2 Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            # Fallback to minimal conversion if detailed fails
            return self._v2_to_v3_minimal(v2)

    def _v2_to_v3_minimal(self, v2: dict) -> dict:
        """Minimal V2 to V3 conversion as fallback"""
        try:
            gh = next(s for s in v2["resultSets"] if s["name"] == "GameHeader")
            idx_gh = {h: i for i, h in enumerate(gh["headers"])}

            ls = next(s for s in v2["resultSets"] if s["name"] == "LineScore")
            idx_ls = {h: i for i, h in enumerate(ls["headers"])}
            
            # Simple abbreviation lookup
            abbr = {
                (row[idx_ls["GAME_ID"]], row[idx_ls["TEAM_ID"]]): row[idx_ls["TEAM_ABBREVIATION"]]
                for row in ls["rowSet"]
            }

            games: List[dict] = []
            for row in gh["rowSet"]:
                game_id = row[idx_gh["GAME_ID"]]
                home_id = row[idx_gh["HOME_TEAM_ID"]]
                away_id = row[idx_gh["VISITOR_TEAM_ID"]]
                games.append({
                    "gameId": game_id,
                    "homeTeam": {"teamTricode": abbr.get((game_id, home_id))},
                    "awayTeam": {"teamTricode": abbr.get((game_id, away_id))},
                    "gameStatus": row[idx_gh["GAME_STATUS_ID"]],
                    "gameEt": row[idx_gh["GAME_DATE_EST"]],
                    "gameCode": row[idx_gh["GAMECODE"]],
                })

            logger.info("Used minimal V2 to V3 conversion for gamedate %s", self.opts["gamedate"])
            return {"scoreboard": {"games": games}}
        except Exception as e:
            error_msg = f"Both detailed and minimal V2 conversion failed: {e}"
            logger.error("Minimal conversion also failed for gamedate %s: %s", self.opts["gamedate"], e)
            try:
                notify_error(
                    title="NBA.com Scoreboard V2 All Conversions Failed",
                    message=f"Both detailed and minimal V2 conversions failed for gamedate {self.opts['gamedate']}: {str(e)}",
                    details={
                        'gamedate': self.opts['gamedate'],
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'url': self.url
                    },
                    processor_name="NBA.com Scoreboard V2 Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(error_msg)
        
    # ------------------------------------------------------------------ #
    # Validation - Updated to use base class patterns
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """Validate the scoreboard response"""
        try:
            if not isinstance(self.decoded_data, dict):
                error_msg = "Response is not a JSON object"
                logger.error("%s for gamedate %s", error_msg, self.opts["gamedate"])
                try:
                    notify_error(
                        title="NBA.com Scoreboard V2 Invalid Response Type",
                        message=f"Response is not a JSON object for gamedate {self.opts['gamedate']}",
                        details={
                            'gamedate': self.opts['gamedate'],
                            'response_type': type(self.decoded_data).__name__,
                            'url': self.url
                        },
                        processor_name="NBA.com Scoreboard V2 Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
            if "scoreboard" not in self.decoded_data:
                error_msg = "Missing 'scoreboard' in response"
                logger.error("%s for gamedate %s", error_msg, self.opts["gamedate"])
                try:
                    notify_error(
                        title="NBA.com Scoreboard V2 Missing Scoreboard",
                        message=f"Response missing 'scoreboard' key for gamedate {self.opts['gamedate']}",
                        details={
                            'gamedate': self.opts['gamedate'],
                            'response_keys': list(self.decoded_data.keys()),
                            'url': self.url
                        },
                        processor_name="NBA.com Scoreboard V2 Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
            scoreboard = self.decoded_data["scoreboard"]
            if not isinstance(scoreboard, dict):
                error_msg = "Scoreboard is not an object"
                logger.error("%s for gamedate %s", error_msg, self.opts["gamedate"])
                try:
                    notify_error(
                        title="NBA.com Scoreboard V2 Invalid Scoreboard Type",
                        message=f"Scoreboard is not an object for gamedate {self.opts['gamedate']}",
                        details={
                            'gamedate': self.opts['gamedate'],
                            'scoreboard_type': type(scoreboard).__name__,
                            'url': self.url
                        },
                        processor_name="NBA.com Scoreboard V2 Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
            if "games" not in scoreboard:
                error_msg = "Missing 'games' in scoreboard"
                logger.error("%s for gamedate %s", error_msg, self.opts["gamedate"])
                try:
                    notify_error(
                        title="NBA.com Scoreboard V2 Missing Games",
                        message=f"Scoreboard missing 'games' key for gamedate {self.opts['gamedate']}",
                        details={
                            'gamedate': self.opts['gamedate'],
                            'scoreboard_keys': list(scoreboard.keys()),
                            'url': self.url
                        },
                        processor_name="NBA.com Scoreboard V2 Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
            games = scoreboard["games"]
            if not isinstance(games, list):
                error_msg = "Games is not a list"
                logger.error("%s for gamedate %s", error_msg, self.opts["gamedate"])
                try:
                    notify_error(
                        title="NBA.com Scoreboard V2 Invalid Games Type",
                        message=f"Games is not a list for gamedate {self.opts['gamedate']}",
                        details={
                            'gamedate': self.opts['gamedate'],
                            'games_type': type(games).__name__,
                            'url': self.url
                        },
                        processor_name="NBA.com Scoreboard V2 Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
            if not games:
                logger.warning("No games on %s (possible off‑day).", self.opts["gamedate"])
                # This is a warning, not an error - NBA has off-days
                # Only notify if it's unusual (e.g., during regular season)
                # Check if it's a typical off-day (Monday or day after Sunday)
                try:
                    from datetime import datetime
                    game_date = datetime.strptime(self.opts["gamedate"], "%Y%m%d")
                    day_of_week = game_date.weekday()  # Monday=0, Sunday=6
                    
                    # Only alert if it's NOT a typical off-day (Tuesday-Saturday)
                    if day_of_week not in [0, 6]:  # Not Monday or Sunday
                        try:
                            notify_warning(
                                title="NBA.com Scoreboard V2 No Games",
                                message=f"No games found for gamedate {self.opts['gamedate']} (unusual for this day of week)",
                                details={
                                    'gamedate': self.opts['gamedate'],
                                    'day_of_week': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][day_of_week],
                                    'url': self.url
                                }
                            )
                        except Exception as notify_ex:
                            logger.warning(f"Failed to send notification: {notify_ex}")
                except Exception as date_ex:
                    logger.debug("Could not parse date for off-day check: %s", date_ex)
            else:
                logger.info("Validation passed: %d games found", len(games))
                
        except DownloadDataException:
            # Already handled and notified above
            raise
        except Exception as e:
            logger.error("Unexpected validation error for gamedate %s: %s", self.opts["gamedate"], e)
            try:
                notify_error(
                    title="NBA.com Scoreboard V2 Validation Error",
                    message=f"Unexpected validation error for gamedate {self.opts['gamedate']}: {str(e)}",
                    details={
                        'gamedate': self.opts['gamedate'],
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'url': self.url
                    },
                    processor_name="NBA.com Scoreboard V2 Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Validation failed: {e}") from e

    # ------------------------------------------------------------------ #
    # Transform - Same logic as before
    # ------------------------------------------------------------------ #
    @staticmethod
    def _status_to_state(status: int | None) -> str:
        """Convert game status to state"""
        return {1: "pre", 2: "in", 3: "post"}.get(status, "unknown")

    def transform_data(self) -> None:
        """Transform scoreboard data with rich NBA.com details"""
        try:
            games_raw: List[Dict[str, Any]] = self.decoded_data["scoreboard"]["games"]
            
            # Also extract rich data from the original V2 response if available
            rich_games = []
            
            # Check if we have access to the original V2 data for enrichment
            if hasattr(self, '_original_v2_data') and self._original_v2_data:
                rich_games = self._extract_rich_game_data(self._original_v2_data)
            
            # Process the converted V3-format games
            parsed_games = []
            for i, g in enumerate(games_raw):
                status = g.get("gameStatus")
                
                # Base game data
                game_data = {
                    "gameId": g.get("gameId"),
                    "home": g.get("homeTeam", {}).get("teamTricode"),
                    "away": g.get("awayTeam", {}).get("teamTricode"),
                    "gameStatus": status,
                    "state": self._status_to_state(status),
                    "startTimeET": g.get("gameEt"),
                    "gameCode": g.get("gameCode"),
                }
                
                # Enrich with detailed data if available
                if i < len(rich_games):
                    game_data.update(rich_games[i])
                
                parsed_games.append(game_data)

            self.data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "gamedate": self.opts["gamedate"],
                "gameCount": len(parsed_games),
                "games": parsed_games,
                "source": "nba_scoreboard_v2_enriched"
            }
            
            logger.info("Processed %d enriched games for %s", len(parsed_games), self.opts["gamedate"])
            
        except KeyError as e:
            logger.error("Transformation failed - missing key %s for gamedate %s", e, self.opts["gamedate"])
            try:
                notify_error(
                    title="NBA.com Scoreboard V2 Transformation Failed",
                    message=f"Data transformation failed - missing expected key for gamedate {self.opts['gamedate']}: {str(e)}",
                    details={
                        'gamedate': self.opts['gamedate'],
                        'missing_key': str(e),
                        'error_type': 'KeyError'
                    },
                    processor_name="NBA.com Scoreboard V2 Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Transformation failed: missing key {e}") from e
        except Exception as e:
            logger.error("Transformation failed for gamedate %s: %s", self.opts["gamedate"], e)
            try:
                notify_error(
                    title="NBA.com Scoreboard V2 Transformation Error",
                    message=f"Unexpected transformation error for gamedate {self.opts['gamedate']}: {str(e)}",
                    details={
                        'gamedate': self.opts['gamedate'],
                        'error': str(e),
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Scoreboard V2 Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Transformation failed: {e}") from e

    def _extract_rich_game_data(self, v2_data: dict) -> List[Dict[str, Any]]:
        """Extract rich game data from original V2 response
        
        FIX APPLIED: Properly match teams to home/away using HOME_TEAM_ID 
        instead of just taking teams in order they appear.
        """
        try:
            # Get GameHeader for main game info
            game_header = next(s for s in v2_data["resultSets"] if s["name"] == "GameHeader")
            gh_headers = game_header["headers"]
            gh_idx = {h: i for i, h in enumerate(gh_headers)}
            
            # Get LineScore for team stats
            line_score = next(s for s in v2_data["resultSets"] if s["name"] == "LineScore")
            ls_headers = line_score["headers"]
            ls_idx = {h: i for i, h in enumerate(ls_headers)}
            
            # First pass: Build game metadata from GameHeader
            game_metadata = {}
            for row in game_header["rowSet"]:
                game_id = row[gh_idx["GAME_ID"]]
                game_metadata[game_id] = {
                    "home_team_id": row[gh_idx["HOME_TEAM_ID"]],
                    "away_team_id": row[gh_idx["VISITOR_TEAM_ID"]],
                    "game_sequence": row[gh_idx["GAME_SEQUENCE"]],
                    "game_status_text": row[gh_idx["GAME_STATUS_TEXT"]],
                    "season": row[gh_idx["SEASON"]],
                    "arena_name": row[gh_idx.get("ARENA_NAME")],
                    "broadcasts": {
                        "national": row[gh_idx.get("NATL_TV_BROADCASTER_ABBREVIATION")],
                        "home": row[gh_idx.get("HOME_TV_BROADCASTER_ABBREVIATION")],
                        "away": row[gh_idx.get("AWAY_TV_BROADCASTER_ABBREVIATION")],
                    },
                    "live_period": row[gh_idx.get("LIVE_PERIOD")],
                    "live_pc_time": row[gh_idx.get("LIVE_PC_TIME")],
                    "live_period_time_bcast": row[gh_idx.get("LIVE_PERIOD_TIME_BCAST")],
                }
            
            # Second pass: Process LineScore and properly assign home/away
            game_teams = {}
            for row in line_score["rowSet"]:
                game_id = row[ls_idx["GAME_ID"]]
                team_id = row[ls_idx["TEAM_ID"]]
                
                if game_id not in game_teams:
                    game_teams[game_id] = {"home": None, "away": None}
                
                team_data = {
                    "teamId": team_id,
                    "abbreviation": row[ls_idx["TEAM_ABBREVIATION"]],
                    "cityName": row[ls_idx["TEAM_CITY_NAME"]],
                    "teamName": row[ls_idx["TEAM_NAME"]],
                    "winsLosses": row[ls_idx["TEAM_WINS_LOSSES"]],
                    "points": row[ls_idx["PTS"]],
                    "quarters": {
                        "q1": row[ls_idx["PTS_QTR1"]],
                        "q2": row[ls_idx["PTS_QTR2"]],
                        "q3": row[ls_idx["PTS_QTR3"]],
                        "q4": row[ls_idx["PTS_QTR4"]],
                        "ot1": row[ls_idx.get("PTS_OT1")],
                        "ot2": row[ls_idx.get("PTS_OT2")],
                    },
                    "stats": {
                        "fgPct": row[ls_idx["FG_PCT"]],
                        "ftPct": row[ls_idx["FT_PCT"]],
                        "fg3Pct": row[ls_idx["FG3_PCT"]],
                        "assists": row[ls_idx["AST"]],
                        "rebounds": row[ls_idx["REB"]],
                        "turnovers": row[ls_idx["TOV"]],
                    }
                }
                
                # =====================================================================
                # FIX: Match teams to home/away using actual HOME_TEAM_ID from metadata
                # instead of just assigning them in order they appear
                # =====================================================================
                if game_id in game_metadata:
                    if team_id == game_metadata[game_id]["home_team_id"]:
                        game_teams[game_id]["home"] = team_data
                    elif team_id == game_metadata[game_id]["away_team_id"]:
                        game_teams[game_id]["away"] = team_data
                    else:
                        logger.warning(f"Game {game_id}: Team {team_id} doesn't match home or away team ID")
                else:
                    logger.warning(f"Game {game_id}: Missing metadata, cannot determine home/away")
            
            # Build enriched game data
            enriched_games = []
            for game_id, metadata in game_metadata.items():
                enriched_data = {
                    # Game details
                    "gameSequence": metadata["game_sequence"],
                    "gameStatusText": metadata["game_status_text"],
                    "season": metadata["season"],
                    
                    # Venue info
                    "arenaName": metadata["arena_name"],
                    
                    # Broadcast info
                    "broadcasts": metadata["broadcasts"],
                    
                    # Live game state
                    "livePeriod": metadata["live_period"],
                    "livePcTime": metadata["live_pc_time"],
                    "livePeriodTimeBcast": metadata["live_period_time_bcast"],
                    
                    # Team details and stats (now correctly assigned!)
                    "teams": game_teams.get(game_id, {"home": None, "away": None}),
                    
                    # NBA.com specific IDs
                    "homeTeamId": metadata["home_team_id"],
                    "awayTeamId": metadata["away_team_id"],
                }
                
                enriched_games.append(enriched_data)
            
            logger.info(f"Extracted rich data for {len(enriched_games)} games with correct home/away assignment")
            return enriched_games
            
        except Exception as e:
            logger.warning("Failed to extract rich game data: %s", e)
            return []

    # ------------------------------------------------------------------ #
    # Stats - Same as before
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        """Return scraper statistics"""
        return {
            "gamedate": self.opts["gamedate"], 
            "gameCount": self.data.get("gameCount", 0),
            "source": "nba_scoreboard_v2_only"
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetNbaComScoreboardV2)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetNbaComScoreboardV2.create_cli_and_flask_main()
    main()
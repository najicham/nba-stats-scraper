# scrapers/nbacom/nbac_scoreboard_v2.py
"""
NBA.com Scoreboard V2 scraper                           v3.2 – 2025‑07‑17
---------------------------------------------------------------------------
* URL: https://stats.nba.com/stats/scoreboardV2
* V3 endpoint is deprecated/blocked, so we go straight to V2
Updated to skip V3 and use reliable V2 endpoint directly.

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py nbac_scoreboard_v2 \
      --scoreDate 20250120 \
      --debug

  # Direct CLI execution:
  python scrapers/nbacom/nbac_scoreboard_v2.py --scoreDate 20250120 --debug

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
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_scoreboard_v2.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaComScoreboardV2(ScraperBase, ScraperFlaskMixin):
    """NBA.com Scoreboard V2 scraper with V3 format conversion and rich data extraction."""

    # Flask Mixin Configuration
    scraper_name = "nbac_scoreboard_v2"
    required_params = ["scoreDate"]
    optional_params = {
        "apiKey": None,
        "runId": None,
    }

    # ------------------------------------------------------------------ #
    # Config - Updated to match other scrapers
    # ------------------------------------------------------------------ #
    required_opts = ["scoreDate"]  # YYYYMMDD or YYYY-MM-DD
    download_type = DownloadType.JSON
    decode_download_data = True
    header_profile = "stats"  # Use standard NBA stats headers
    proxy_enabled = True      # NBA.com may need proxy
    
    # ------------------------------------------------------------------ #
    # Exporters - Updated to include capture group
    # ------------------------------------------------------------------ #
    exporters = [
        # Standard development export
        {
            "type": "file",
            "filename": "/tmp/nba_game_ids_stats_%(scoreDate)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
        # Production GCS export
        {
            "type": "gcs",
            "key": "nba/game_ids/%(scoreDate)s/game_ids_stats.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
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
        """Convert scoreDate to YYYY-MM-DD format"""
        raw = self.opts["scoreDate"].replace("-", "")
        if len(raw) != 8 or not raw.isdigit():
            raise DownloadDataException("scoreDate must be YYYYMMDD or YYYY‑MM‑DD")
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"

    def _mm_dd_yyyy(self) -> str:
        """Convert scoreDate to MM/DD/YYYY format for NBA.com"""
        ymd = self._yyyy_mm_dd()
        yyyy, mm, dd = ymd.split("-")
        return f"{mm}/{dd}/{yyyy}"

    def set_additional_opts(self) -> None:
        """Normalize scoreDate for exporters"""
        # Normalize date for exporters (remove dashes)
        self.opts["scoreDate"] = self._yyyy_mm_dd().replace("-", "")

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
                raise DownloadDataException("Invalid V2 response structure")
                
        except Exception as e:
            raise DownloadDataException(f"Both V3 and V2 download attempts failed: {e}")

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
            
        except Exception as e:
            logger.error("V2 to V3 conversion failed: %s", e)
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

            return {"scoreboard": {"games": games}}
        except Exception as e:
            raise DownloadDataException(f"Both detailed and minimal V2 conversion failed: {e}")
        
    # ------------------------------------------------------------------ #
    # Validation - Updated to use base class patterns
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """Validate the scoreboard response"""
        if not isinstance(self.decoded_data, dict):
            raise DownloadDataException("Response is not a JSON object")
            
        if "scoreboard" not in self.decoded_data:
            raise DownloadDataException("Missing 'scoreboard' in response")
            
        scoreboard = self.decoded_data["scoreboard"]
        if not isinstance(scoreboard, dict):
            raise DownloadDataException("Scoreboard is not an object")
            
        if "games" not in scoreboard:
            raise DownloadDataException("Missing 'games' in scoreboard")
            
        games = scoreboard["games"]
        if not isinstance(games, list):
            raise DownloadDataException("Games is not a list")
            
        if not games:
            logger.warning("No games on %s (possible off‑day).", self.opts["scoreDate"])
        else:
            logger.info("Validation passed: %d games found", len(games))

    # ------------------------------------------------------------------ #
    # Transform - Same logic as before
    # ------------------------------------------------------------------ #
    @staticmethod
    def _status_to_state(status: int | None) -> str:
        """Convert game status to state"""
        return {1: "pre", 2: "in", 3: "post"}.get(status, "unknown")

    def transform_data(self) -> None:
        """Transform scoreboard data with rich NBA.com details"""
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
            "scoreDate": self.opts["scoreDate"],
            "gameCount": len(parsed_games),
            "games": parsed_games,
            "source": "nba_scoreboard_v2_enriched"
        }
        
        logger.info("Processed %d enriched games for %s", len(parsed_games), self.opts["scoreDate"])

    def _extract_rich_game_data(self, v2_data: dict) -> List[Dict[str, Any]]:
        """Extract rich game data from original V2 response"""
        try:
            # Get GameHeader for main game info
            game_header = next(s for s in v2_data["resultSets"] if s["name"] == "GameHeader")
            gh_headers = game_header["headers"]
            gh_idx = {h: i for i, h in enumerate(gh_headers)}
            
            # Get LineScore for team stats
            line_score = next(s for s in v2_data["resultSets"] if s["name"] == "LineScore")
            ls_headers = line_score["headers"]
            ls_idx = {h: i for i, h in enumerate(ls_headers)}
            
            # Group LineScore by game
            game_teams = {}
            for row in line_score["rowSet"]:
                game_id = row[ls_idx["GAME_ID"]]
                if game_id not in game_teams:
                    game_teams[game_id] = {"home": None, "away": None}
                
                team_data = {
                    "teamId": row[ls_idx["TEAM_ID"]],
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
                
                # Determine home/away (this is simplified - you might need better logic)
                if game_teams[game_id]["home"] is None:
                    game_teams[game_id]["home"] = team_data
                else:
                    game_teams[game_id]["away"] = team_data
            
            # Build enriched game data
            enriched_games = []
            for row in game_header["rowSet"]:
                game_id = row[gh_idx["GAME_ID"]]
                
                enriched_data = {
                    # Game details
                    "gameSequence": row[gh_idx["GAME_SEQUENCE"]],
                    "gameStatusText": row[gh_idx["GAME_STATUS_TEXT"]],
                    "season": row[gh_idx["SEASON"]],
                    
                    # Venue info
                    "arenaName": row[gh_idx.get("ARENA_NAME")],
                    
                    # Broadcast info
                    "broadcasts": {
                        "national": row[gh_idx.get("NATL_TV_BROADCASTER_ABBREVIATION")],
                        "home": row[gh_idx.get("HOME_TV_BROADCASTER_ABBREVIATION")],
                        "away": row[gh_idx.get("AWAY_TV_BROADCASTER_ABBREVIATION")],
                    },
                    
                    # Live game state
                    "livePeriod": row[gh_idx.get("LIVE_PERIOD")],
                    "livePcTime": row[gh_idx.get("LIVE_PC_TIME")],
                    "livePeriodTimeBcast": row[gh_idx.get("LIVE_PERIOD_TIME_BCAST")],
                    
                    # Team details and stats
                    "teams": game_teams.get(game_id, {}),
                    
                    # NBA.com specific IDs
                    "homeTeamId": row[gh_idx["HOME_TEAM_ID"]],
                    "awayTeamId": row[gh_idx["VISITOR_TEAM_ID"]],
                }
                
                enriched_games.append(enriched_data)
            
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
            "scoreDate": self.opts["scoreDate"], 
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
    
"""
File: scrapers/nbacom/nbac_roster.py

NBA.com team roster scraper                               v2.1 - 2025-06-17
--------------------------------------------------------------------------
Downloads current team rosters from NBA.com team pages by parsing embedded
JSON data. Essential for tracking active players for prop betting analysis.

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py nbac_roster \
      --team_abbr GSW \
      --debug

  # Direct CLI execution:
  python scrapers/nbacom/nbac_roster.py --team_abbr GSW --debug

  # Flask web service:
  python scrapers/nbacom/nbac_roster.py --serve --debug
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import List, Dict

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ValidationError

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.nbacom.nbac_roster
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_roster.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

from shared.config.nba_teams import NBA_TEAMS

# Notification system imports
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger("scraper_base")

# ------------------------------------------------------------------ #
# Pydantic models
# ------------------------------------------------------------------ #
class PlayerItem(BaseModel):
    PLAYER: str = Field(...)
    PLAYER_SLUG: str = Field(...)
    PLAYER_ID: int = Field(...)
    NUM: str | None = Field(...)  # Allow None for players without jersey numbers
    POSITION: str = Field(...)


class Roster(BaseModel):
    roster: List[PlayerItem]


class TeamProps(BaseModel):
    team: Roster


class PageProps(BaseModel):
    pageProps: TeamProps


class NextData(BaseModel):
    props: PageProps


# ------------------------------------------------------------------ #
class GetNbaTeamRoster(ScraperBase, ScraperFlaskMixin):
    """Parses roster JSON embedded in nba.com team pages."""

    # Flask Mixin Configuration
    scraper_name = "nbac_roster"
    required_params = ["team_abbr"]
    optional_params = {}

    required_opts = ["team_abbr"]
    header_profile: str | None = "data"
    download_type: DownloadType = DownloadType.HTML
    decode_download_data: bool = True

    # master debug flag (can be overridden by opts['debug'] from base framework)
    debug_enabled: bool = False

    GCS_PATH_KEY = "nba_com_team_roster"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/nbacom_roster_%(team_abbr)s_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
        # ADD CAPTURE EXPORTERS for testing with capture.py
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.html",
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
    ]

    # ------------------------------------------------------------ helpers
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        
        now = datetime.now(timezone.utc)
        self.opts["date"] = now.strftime("%Y-%m-%d")
        self.opts["time"] = now.strftime("%H-%M-%S")
        self.opts.setdefault("season", f"{now.year}-{(now.year + 1) % 100:02d}")

        # Use debug flag from base framework (comes from --debug CLI arg)
        self.debug_enabled = self.opts.get("debug", False)

    def _team_cfg(self) -> dict:
        for t in NBA_TEAMS:
            if t["abbr"].lower() == self.opts["team_abbr"].lower():
                return t
        raise DownloadDataException(f"Unknown team_abbr: {self.opts['team_abbr']}")

    # ------------------------------------------------------------ URL
    def set_url(self) -> None:
        cfg = self._team_cfg()
        self.opts["teamId"] = cfg["teamId"]
        self.url = f"https://www.nba.com/team/{cfg['teamId']}/{cfg['slug']}/roster"
        logger.info("Roster URL for %s: %s", self.opts["team_abbr"], self.url)

    # ------------------------------------------------------------ validation
    def validate_download_data(self) -> None:
        """Validate basic HTML response structure"""
        try:
            if not self.decoded_data:
                error_msg = "Roster page HTML is empty"
                logger.error("%s for team %s", error_msg, self.opts["team_abbr"])
                try:
                    notify_error(
                        title="NBA.com Roster HTML Empty",
                        message=f"Empty HTML response for team {self.opts['team_abbr']}",
                        details={
                            'team_abbr': self.opts['team_abbr'],
                            'teamId': self.opts.get('teamId'),
                            'url': self.url
                        },
                        processor_name="NBA.com Roster Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
            if not isinstance(self.decoded_data, str):
                error_msg = "Roster page response is not HTML text"
                logger.error("%s for team %s", error_msg, self.opts["team_abbr"])
                try:
                    notify_error(
                        title="NBA.com Roster Invalid Response Type",
                        message=f"Response is not HTML text for team {self.opts['team_abbr']}",
                        details={
                            'team_abbr': self.opts['team_abbr'],
                            'teamId': self.opts.get('teamId'),
                            'response_type': type(self.decoded_data).__name__,
                            'url': self.url
                        },
                        processor_name="NBA.com Roster Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
            if "<html" not in self.decoded_data.lower():
                error_msg = "Response does not appear to be valid HTML"
                logger.error("%s for team %s", error_msg, self.opts["team_abbr"])
                try:
                    notify_error(
                        title="NBA.com Roster Not Valid HTML",
                        message=f"Response does not appear to be valid HTML for team {self.opts['team_abbr']}",
                        details={
                            'team_abbr': self.opts['team_abbr'],
                            'teamId': self.opts.get('teamId'),
                            'response_length': len(self.decoded_data),
                            'response_preview': self.decoded_data[:200],
                            'url': self.url
                        },
                        processor_name="NBA.com Roster Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
            if len(self.decoded_data) < 1000:
                error_msg = "HTML response suspiciously short - possible error page"
                logger.error("%s for team %s: %d bytes", error_msg, self.opts["team_abbr"], len(self.decoded_data))
                try:
                    notify_error(
                        title="NBA.com Roster Suspiciously Short HTML",
                        message=f"HTML response too short ({len(self.decoded_data)} bytes) for team {self.opts['team_abbr']}",
                        details={
                            'team_abbr': self.opts['team_abbr'],
                            'teamId': self.opts.get('teamId'),
                            'response_length': len(self.decoded_data),
                            'response_preview': self.decoded_data[:500],
                            'url': self.url
                        },
                        processor_name="NBA.com Roster Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
        except DownloadDataException:
            # Already handled and notified above
            raise
        except Exception as e:
            logger.error("Unexpected validation error for team %s: %s", self.opts["team_abbr"], e)
            try:
                notify_error(
                    title="NBA.com Roster Validation Error",
                    message=f"Unexpected validation error for team {self.opts['team_abbr']}: {str(e)}",
                    details={
                        'team_abbr': self.opts['team_abbr'],
                        'teamId': self.opts.get('teamId'),
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'url': self.url
                    },
                    processor_name="NBA.com Roster Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Validation failed: {e}") from e

    # ------------------------------------------------------------ enhanced validation
    def validate_roster_data(self) -> None:
        """
        Production validation for roster data quality.
        """
        try:
            players = self.data["players"]
            
            # 1. REASONABLE PLAYER COUNT CHECK
            player_count = len(players)
            min_players = int(os.environ.get('ROSTER_MIN_PLAYERS', '8'))
            max_players = int(os.environ.get('ROSTER_MAX_PLAYERS', '25'))
            
            if player_count < min_players:
                error_msg = f"Suspiciously low player count: {player_count} (expected {min_players}-{max_players})"
                logger.error("%s for team %s", error_msg, self.opts["team_abbr"])
                try:
                    notify_error(
                        title="NBA.com Roster Low Player Count",
                        message=f"Suspiciously low player count ({player_count}) for team {self.opts['team_abbr']}",
                        details={
                            'team_abbr': self.opts['team_abbr'],
                            'teamId': self.opts.get('teamId'),
                            'player_count': player_count,
                            'min_threshold': min_players,
                            'max_threshold': max_players
                        },
                        processor_name="NBA.com Roster Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
            elif player_count > max_players:
                error_msg = f"Suspiciously high player count: {player_count} (expected {min_players}-{max_players})"
                logger.error("%s for team %s", error_msg, self.opts["team_abbr"])
                try:
                    notify_error(
                        title="NBA.com Roster High Player Count",
                        message=f"Suspiciously high player count ({player_count}) for team {self.opts['team_abbr']}",
                        details={
                            'team_abbr': self.opts['team_abbr'],
                            'teamId': self.opts.get('teamId'),
                            'player_count': player_count,
                            'min_threshold': min_players,
                            'max_threshold': max_players
                        },
                        processor_name="NBA.com Roster Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
            
            # 2. REQUIRED PLAYER FIELDS VALIDATION
            required_fields = ['name', 'slug', 'playerId', 'number', 'position']
            for i, player in enumerate(players[:5]):  # Check first 5 players
                for field in required_fields:
                    if field not in player or not player[field]:
                        error_msg = f"Player {i}: Missing or empty required field '{field}': {player}"
                        logger.error("%s for team %s", error_msg, self.opts["team_abbr"])
                        try:
                            notify_error(
                                title="NBA.com Roster Missing Player Field",
                                message=f"Player {i} missing required field '{field}' for team {self.opts['team_abbr']}",
                                details={
                                    'team_abbr': self.opts['team_abbr'],
                                    'teamId': self.opts.get('teamId'),
                                    'player_index': i,
                                    'missing_field': field,
                                    'player_data': player
                                },
                                processor_name="NBA.com Roster Scraper"
                            )
                        except Exception as notify_ex:
                            logger.warning(f"Failed to send notification: {notify_ex}")
                        raise DownloadDataException(error_msg)
            
            # 3. PLAYER ID VALIDATION
            player_ids = [p.get('playerId') for p in players if p.get('playerId')]
            if len(player_ids) != len(set(player_ids)):
                error_msg = "Duplicate player IDs found in roster"
                logger.error("%s for team %s", error_msg, self.opts["team_abbr"])
                try:
                    notify_error(
                        title="NBA.com Roster Duplicate Player IDs",
                        message=f"Duplicate player IDs found for team {self.opts['team_abbr']}",
                        details={
                            'team_abbr': self.opts['team_abbr'],
                            'teamId': self.opts.get('teamId'),
                            'total_players': len(players),
                            'unique_player_ids': len(set(player_ids))
                        },
                        processor_name="NBA.com Roster Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
            
            # Check for reasonable player ID values
            for player in players[:3]:  # Check first 3
                player_id = player.get('playerId')
                if not isinstance(player_id, int) or player_id <= 0:
                    error_msg = f"Invalid player ID: {player_id} for player {player.get('name')}"
                    logger.error("%s for team %s", error_msg, self.opts["team_abbr"])
                    try:
                        notify_error(
                            title="NBA.com Roster Invalid Player ID",
                            message=f"Invalid player ID for team {self.opts['team_abbr']}: {player_id}",
                            details={
                                'team_abbr': self.opts['team_abbr'],
                                'teamId': self.opts.get('teamId'),
                                'player_name': player.get('name'),
                                'player_id': player_id,
                                'player_id_type': type(player_id).__name__
                            },
                            processor_name="NBA.com Roster Scraper"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                    raise DownloadDataException(error_msg)
            
            # 4. POSITION VALIDATION
            valid_positions = {'G', 'F', 'C', 'PG', 'SG', 'SF', 'PF', 'G-F', 'F-G', 'F-C', 'C-F'}
            invalid_positions = []
            for player in players:
                position = player.get('position', '').upper()
                if position and position not in valid_positions:
                    invalid_positions.append(f"{player.get('name')}: {position}")
            
            if invalid_positions:
                # Log warning but don't fail - positions might have new formats
                logger.warning("Unusual position formats found for team %s: %s", 
                             self.opts["team_abbr"], invalid_positions[:3])
                try:
                    notify_warning(
                        title="NBA.com Roster Unusual Position Formats",
                        message=f"Unusual position formats found for team {self.opts['team_abbr']}",
                        details={
                            'team_abbr': self.opts['team_abbr'],
                            'teamId': self.opts.get('teamId'),
                            'invalid_positions_sample': invalid_positions[:3],
                            'total_invalid': len(invalid_positions)
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            # 5. TEAM CONSISTENCY CHECK
            team_abbr = self.data.get('team_abbr', '').upper()
            expected_abbr = self.opts.get('team_abbr', '').upper()
            if team_abbr != expected_abbr:
                logger.warning("Team abbreviation mismatch for %s: expected %s, got %s", 
                             self.opts["team_abbr"], expected_abbr, team_abbr)
                try:
                    notify_warning(
                        title="NBA.com Roster Team Abbreviation Mismatch",
                        message=f"Team abbreviation mismatch: expected {expected_abbr}, got {team_abbr}",
                        details={
                            'requested_team': expected_abbr,
                            'returned_team': team_abbr,
                            'teamId': self.opts.get('teamId')
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            logger.info(f"✅ Roster validation passed: {player_count} players for {team_abbr}")
            
        except DownloadDataException:
            # Already handled and notified above
            raise
        except KeyError as e:
            logger.error("Missing expected key during validation for team %s: %s", self.opts["team_abbr"], e)
            try:
                notify_error(
                    title="NBA.com Roster Validation Missing Key",
                    message=f"Missing expected key during validation for team {self.opts['team_abbr']}: {str(e)}",
                    details={
                        'team_abbr': self.opts['team_abbr'],
                        'teamId': self.opts.get('teamId'),
                        'missing_key': str(e),
                        'error_type': 'KeyError'
                    },
                    processor_name="NBA.com Roster Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Roster validation failed: missing key {e}") from e
        except Exception as e:
            logger.error("Unexpected validation error for team %s: %s", self.opts["team_abbr"], e)
            try:
                notify_error(
                    title="NBA.com Roster Data Validation Error",
                    message=f"Unexpected validation error for team {self.opts['team_abbr']}: {str(e)}",
                    details={
                        'team_abbr': self.opts['team_abbr'],
                        'teamId': self.opts.get('teamId'),
                        'error': str(e),
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Roster Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Roster validation failed: {e}") from e

    # ------------------------------------------------------------ transform
    def transform_data(self) -> None:
        """Parse roster data from HTML and validate"""
        try:
            soup = BeautifulSoup(self.decoded_data, "html.parser")

            # Conditional debug dumps
            if self.debug_enabled:
                self._debug_write_html()
                self._debug_write_all_scripts(soup)

            tag = soup.find("script", id="__NEXT_DATA__")
            if not tag:
                error_msg = "__NEXT_DATA__ script tag not found in HTML"
                logger.error("%s for team %s", error_msg, self.opts["team_abbr"])
                try:
                    notify_error(
                        title="NBA.com Roster Missing Script Tag",
                        message=f"__NEXT_DATA__ script tag not found for team {self.opts['team_abbr']}",
                        details={
                            'team_abbr': self.opts['team_abbr'],
                            'teamId': self.opts.get('teamId'),
                            'url': self.url
                        },
                        processor_name="NBA.com Roster Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
            if not tag.string:
                error_msg = "__NEXT_DATA__ script tag is empty"
                logger.error("%s for team %s", error_msg, self.opts["team_abbr"])
                try:
                    notify_error(
                        title="NBA.com Roster Empty Script Tag",
                        message=f"__NEXT_DATA__ script tag is empty for team {self.opts['team_abbr']}",
                        details={
                            'team_abbr': self.opts['team_abbr'],
                            'teamId': self.opts.get('teamId'),
                            'url': self.url
                        },
                        processor_name="NBA.com Roster Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)

            try:
                json_text = tag.string[tag.string.find("{") :]
                raw_json = json.loads(json_text)
                parsed = NextData(**raw_json)
            except json.JSONDecodeError as exc:
                if self.debug_enabled:
                    self._debug_write_embedded_json(tag.string)
                    self._store_fallback_json(tag.string, reason="JSONDecodeError")
                logger.error("Failed to parse embedded JSON for team %s: %s", self.opts["team_abbr"], exc)
                try:
                    notify_error(
                        title="NBA.com Roster JSON Parse Error",
                        message=f"Failed to parse embedded JSON for team {self.opts['team_abbr']}: {str(exc)}",
                        details={
                            'team_abbr': self.opts['team_abbr'],
                            'teamId': self.opts.get('teamId'),
                            'error': str(exc),
                            'json_preview': tag.string[:500] if tag.string else None,
                            'url': self.url
                        },
                        processor_name="NBA.com Roster Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(f"Failed to parse embedded JSON: {exc}")
            except ValidationError as exc:
                if self.debug_enabled:
                    self._debug_write_embedded_json(tag.string)
                    self._store_fallback_json(tag.string, reason="ValidationError")
                logger.error("Roster data structure validation failed for team %s: %s", self.opts["team_abbr"], exc)
                try:
                    notify_error(
                        title="NBA.com Roster Structure Validation Failed",
                        message=f"Roster data structure validation failed for team {self.opts['team_abbr']}: {str(exc)}",
                        details={
                            'team_abbr': self.opts['team_abbr'],
                            'teamId': self.opts.get('teamId'),
                            'error': str(exc),
                            'error_type': 'ValidationError',
                            'url': self.url
                        },
                        processor_name="NBA.com Roster Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(f"Roster data structure validation failed: {exc}")

            roster_items = parsed.props.pageProps.team.roster

            players = [
                {
                    "name": p.PLAYER,
                    "slug": p.PLAYER_SLUG,
                    "playerId": p.PLAYER_ID,
                    "number": p.NUM or "N/A",  # Handle None jersey numbers
                    "position": p.POSITION,
                }
                for p in roster_items
            ]

            self.data = {
                "metadata": {
                    "team_abbr": self.opts["team_abbr"],
                    "teamId": self.opts["teamId"],
                    "season": self.opts["season"],
                    "fetchedUtc": datetime.now(timezone.utc).isoformat(),
                    "playerCount": len(players),
                },
                "team_abbr": self.opts["team_abbr"],
                "teamId": self.opts["teamId"],
                "season": self.opts["season"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "playerCount": len(players),
                "players": players,
            }

            logger.info("Found %d players for %s", len(players), self.opts["team_abbr"])
            
            # Add production validation
            self.validate_roster_data()
            
        except DownloadDataException:
            # Already handled and notified above
            raise
        except Exception as e:
            logger.error("Transformation failed for team %s: %s", self.opts["team_abbr"], e)
            try:
                notify_error(
                    title="NBA.com Roster Transformation Error",
                    message=f"Unexpected transformation error for team {self.opts['team_abbr']}: {str(e)}",
                    details={
                        'team_abbr': self.opts['team_abbr'],
                        'teamId': self.opts.get('teamId'),
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'url': self.url
                    },
                    processor_name="NBA.com Roster Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Transformation failed: {e}") from e

    # ------------------------------------------------------------ only save if we have reasonable data
    def should_save_data(self) -> bool:
        if not isinstance(self.data, dict):
            return False
        return self.data.get("playerCount", 0) > 0

    # ------------------------------------------------------------ stats
    def get_scraper_stats(self) -> dict:
        return {
            "team_abbr": self.opts["team_abbr"],
            "teamId": self.opts.get("teamId"),
            "players": self.data.get("playerCount", 0),
        }

    # ------------------------------------------------------------ debug helpers
    def _debug_write_html(self) -> None:
        try:
            with open("/tmp/roster_page.html", "w", encoding="utf-8") as fh:
                fh.write(self.decoded_data)
            logger.info("Debug: Saved HTML to /tmp/roster_page.html")
        except Exception as exc:
            logger.warning("Failed to dump HTML: %s", exc)

    def _debug_write_all_scripts(self, soup: BeautifulSoup) -> None:
        debug_dir = "/tmp/debug_scripts"
        os.makedirs(debug_dir, exist_ok=True)
        script_count = 0
        for idx, tag in enumerate(soup.find_all("script")):
            if tag.string:  # Only write scripts with content
                path = os.path.join(debug_dir, f"script_{idx}.txt")
                try:
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(tag.string)
                    script_count += 1
                except Exception as exc:
                    logger.warning("Failed to write %s: %s", path, exc)
        logger.info(f"Debug: Saved {script_count} scripts to {debug_dir}")

    def _debug_write_embedded_json(self, text: str) -> None:
        try:
            with open("/tmp/debug_embedded.json", "w", encoding="utf-8") as fh:
                fh.write(text)
            logger.info("Debug: Saved embedded JSON to /tmp/debug_embedded.json")
        except Exception as exc:
            logger.warning("Failed to write embedded JSON: %s", exc)

    def _store_fallback_json(self, text: str, reason: str = "unknown") -> None:
        fb_dir = "/tmp/fallback_json"
        os.makedirs(fb_dir, exist_ok=True)
        filename = (
            f"roster_fallback_{self.opts.get('team_abbr','NA')}_"
            f"{self.opts.get('date','NA')}_{self.opts.get('time','NA')}_{reason}.json"
        )
        path = os.path.join(fb_dir, filename)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            logger.warning("Stored fallback JSON at %s", path)
        except Exception as exc:
            logger.warning("Failed to write fallback JSON: %s", exc)


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetNbaTeamRoster)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetNbaTeamRoster.create_cli_and_flask_main()
    main()
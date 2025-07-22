# scrapers/nbacom/nbac_roster.py
"""
NBA.com team roster scraper                               v2.1 - 2025-06-17
--------------------------------------------------------------------------
Downloads current team rosters from NBA.com team pages by parsing embedded
JSON data. Essential for tracking active players for prop betting analysis.

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py nbac_roster \
      --teamAbbr GSW \
      --debug

  # Direct CLI execution:
  python scrapers/nbacom/nbac_roster.py --teamAbbr GSW --debug

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
    required_params = ["teamAbbr"]
    optional_params = {
        "debug": None,  # Special debug parameter for extra functionality
    }

    required_opts = ["teamAbbr"]
    header_profile: str | None = "data"
    download_type: DownloadType = DownloadType.HTML
    decode_download_data: bool = True

    # master debug flag (can be overridden by opts['debug'])
    debug_enabled: bool = False

    GCS_PATH_KEY = "nba_com_team_roster"
    exporters = [
        {
            "type": "gcs",
            #"key": "nba/rosters/%(season)s/%(date)s/%(teamAbbr)s_%(time)s.json",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/nbacom_roster_%(teamAbbr)s_%(date)s.json",
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

        # interpret --debug flag (truthy → enable debug helpers)
        dbg = str(self.opts.get("debug", "0")).lower()
        self.debug_enabled = dbg in {"1", "true", "yes"}

    def _team_cfg(self) -> dict:
        for t in NBA_TEAMS:
            if t["abbr"].lower() == self.opts["teamAbbr"].lower():
                return t
        raise DownloadDataException(f"Unknown teamAbbr: {self.opts['teamAbbr']}")

    # ------------------------------------------------------------ URL
    def set_url(self) -> None:
        cfg = self._team_cfg()
        self.opts["teamId"] = cfg["teamId"]
        self.url = f"https://www.nba.com/team/{cfg['teamId']}/{cfg['slug']}/roster"
        logger.info("Roster URL: %s", self.url)

    # ------------------------------------------------------------ validation
    def validate_download_data(self) -> None:
        if not self.decoded_data:
            raise DownloadDataException("Roster page HTML is empty")
            
        if not isinstance(self.decoded_data, str):
            raise DownloadDataException("Roster page response is not HTML text")
            
        if "<html" not in self.decoded_data.lower():
            raise DownloadDataException("Response does not appear to be valid HTML")
            
        if len(self.decoded_data) < 1000:
            raise DownloadDataException("HTML response suspiciously short - possible error page")

    # ------------------------------------------------------------ enhanced validation
    def validate_roster_data(self) -> None:
        """
        Production validation for roster data quality.
        """
        players = self.data["players"]
        
        # 1. REASONABLE PLAYER COUNT CHECK
        player_count = len(players)
        if player_count < 8:
            raise DownloadDataException(f"Suspiciously low player count: {player_count} (expected 12-20)")
        elif player_count > 25:
            raise DownloadDataException(f"Suspiciously high player count: {player_count} (expected 12-20)")
        
        # 2. REQUIRED PLAYER FIELDS VALIDATION
        required_fields = ['name', 'slug', 'playerId', 'number', 'position']
        for i, player in enumerate(players[:5]):  # Check first 5 players
            for field in required_fields:
                if field not in player or not player[field]:
                    raise DownloadDataException(f"Player {i}: Missing or empty required field '{field}': {player}")
        
        # 3. PLAYER ID VALIDATION
        player_ids = [p.get('playerId') for p in players if p.get('playerId')]
        if len(player_ids) != len(set(player_ids)):
            raise DownloadDataException("Duplicate player IDs found in roster")
        
        # Check for reasonable player ID values
        for player in players[:3]:  # Check first 3
            player_id = player.get('playerId')
            if not isinstance(player_id, int) or player_id <= 0:
                raise DownloadDataException(f"Invalid player ID: {player_id} for player {player.get('name')}")
        
        # 4. POSITION VALIDATION
        valid_positions = {'G', 'F', 'C', 'PG', 'SG', 'SF', 'PF', 'G-F', 'F-G', 'F-C', 'C-F'}
        invalid_positions = []
        for player in players:
            position = player.get('position', '').upper()
            if position and position not in valid_positions:
                invalid_positions.append(f"{player.get('name')}: {position}")
        
        if invalid_positions:
            # Log warning but don't fail - positions might have new formats
            logger.warning(f"Unusual position formats found: {invalid_positions[:3]}")
        
        # 5. TEAM CONSISTENCY CHECK
        team_abbr = self.data.get('teamAbbr', '').upper()
        expected_abbr = self.opts.get('teamAbbr', '').upper()
        if team_abbr != expected_abbr:
            logger.warning(f"Team abbreviation mismatch: expected {expected_abbr}, got {team_abbr}")
        
        logger.info(f"✅ Roster validation passed: {player_count} players for {team_abbr}")

    # ------------------------------------------------------------ transform
    def transform_data(self) -> None:
        soup = BeautifulSoup(self.decoded_data, "html.parser")

        # Conditional debug dumps
        if self.debug_enabled:
            self._debug_write_html()
            self._debug_write_all_scripts(soup)

        tag = soup.find("script", id="__NEXT_DATA__")
        if not tag:
            raise DownloadDataException("__NEXT_DATA__ script tag not found in HTML")
            
        if not tag.string:
            raise DownloadDataException("__NEXT_DATA__ script tag is empty")

        try:
            json_text = tag.string[tag.string.find("{") :]
            raw_json = json.loads(json_text)
            parsed = NextData(**raw_json)
        except json.JSONDecodeError as exc:
            if self.debug_enabled:
                self._debug_write_embedded_json(tag.string)
                self._store_fallback_json(tag.string, reason="JSONDecodeError")
            raise DownloadDataException(f"Failed to parse embedded JSON: {exc}")
        except ValidationError as exc:
            if self.debug_enabled:
                self._debug_write_embedded_json(tag.string)
                self._store_fallback_json(tag.string, reason="ValidationError")
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
                "teamAbbr": self.opts["teamAbbr"],
                "teamId": self.opts["teamId"],
                "season": self.opts["season"],
                "fetchedUtc": datetime.now(timezone.utc).isoformat(),
                "playerCount": len(players),
            },
            "teamAbbr": self.opts["teamAbbr"],
            "teamId": self.opts["teamId"],
            "season": self.opts["season"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "playerCount": len(players),
            "players": players,
        }

        logger.info("Found %d players for %s", len(players), self.opts["teamAbbr"])
        
        # Add production validation
        self.validate_roster_data()

    # ------------------------------------------------------------ only save if we have reasonable data
    def should_save_data(self) -> bool:
        if not isinstance(self.data, dict):
            return False
        return self.data.get("playerCount", 0) > 0

    # ------------------------------------------------------------ stats
    def get_scraper_stats(self) -> dict:
        return {
            "teamAbbr": self.opts["teamAbbr"],
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
            f"roster_fallback_{self.opts.get('teamAbbr','NA')}_"
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
    
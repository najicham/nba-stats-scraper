"""
FILE: scrapers/espn/espn_roster_api.py
ESPN NBA Roster API scraper                           v2 - 2025-06-16
--------------------------------------------------------------------
Endpoint pattern
    https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{teamId}?enable=roster

Key upgrades vs. v1
-------------------
- header_profile="espn" -> UA managed centrally
- Strict ISO-8601 timestamp with timezone
- Handles BOTH legacy integer-inch "height" AND new {feet, inches} dict
- Adds prod to exporter groups (keeps dev/test)
- Type hints + concise log line
- UPDATED: Changed teamId to team_abbr for consistency

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py espn_roster_api \
      --team_abbr LAL \
      --debug

  # Direct CLI execution:
  python scrapers/espn/espn_roster_api.py --team_abbr LAL --debug

  # Flask web service:
  python scrapers/espn/espn_roster_api.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.espn.espn_roster_api
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/espn/espn_roster_api.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

# Notification system imports
try:
    from shared.utils.notification_system import (
        notify_error,
        notify_warning,
        notify_info
    )
except ImportError:
    # Fallback if notification system not available
    def notify_error(*args, **kwargs):
        pass
    def notify_warning(*args, **kwargs):
        pass
    def notify_info(*args, **kwargs):
        pass

logger = logging.getLogger("scraper_base")

# ESPN Team ID Mapping (abbreviation -> numeric ID)
ESPN_TEAM_IDS = {
    # ESPN Code: Team ID
    "ATL": 1,   "BOS": 2,   "BKN": 17,  "CHA": 30,  "CHI": 4,
    "CLE": 5,   "DAL": 6,   "DEN": 7,   "DET": 8,   
    "GS": 9,    # ✅ ESPN code (was GSW)
    "HOU": 10,  "IND": 11,  "LAC": 12,  "LAL": 13,  "MEM": 29,
    "MIA": 14,  "MIL": 15,  "MIN": 16,  
    "NO": 3,    # ✅ ESPN code (was NOP)
    "NY": 18,   # ✅ ESPN code (was NYK)
    "OKC": 25,  "ORL": 19,  "PHI": 20,  "PHX": 21,  "POR": 22,
    "SAC": 23,  
    "SA": 24,   # ✅ ESPN code (was SAS)
    "TOR": 28,  
    "UTAH": 26, # ✅ ESPN code (was UTA)
    "WAS": 27
}

ESPN_TO_NBA_TRICODE = {
    # ESPN codes that differ from NBA.com standard
    "GS": "GSW",
    "NY": "NYK",
    "NO": "NOP",
    "SA": "SAS",
    "UTAH": "UTA",
    # All others are the same, but include them for completeness
    "ATL": "ATL", "BOS": "BOS", "BKN": "BKN", "CHA": "CHA", "CHI": "CHI",
    "CLE": "CLE", "DAL": "DAL", "DEN": "DEN", "DET": "DET", "HOU": "HOU",
    "IND": "IND", "LAC": "LAC", "LAL": "LAL", "MEM": "MEM", "MIA": "MIA",
    "MIL": "MIL", "MIN": "MIN", "OKC": "OKC", "ORL": "ORL", "PHI": "PHI",
    "PHX": "PHX", "POR": "POR", "SAC": "SAC", "TOR": "TOR", "WAS": "WAS"
}


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class GetEspnTeamRosterAPI(ScraperBase, ScraperFlaskMixin):
    """
    Scrape a single NBA roster via ESPN's JSON API.
    """

    # Flask Mixin Configuration
    scraper_name = "espn_roster_api"
    required_params = ["team_abbr"]  # team_abbr is required
    optional_params = {}

    # Original scraper config
    required_opts: List[str] = ["team_abbr"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = "espn"

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "espn_team_roster"
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/espn_roster_api_%(team_abbr)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        # --- raw fixture for offline tests ---------------------------------
        {
            "type": "file",
            "filename": "/tmp/raw_%(team_abbr)s.json",   # <-- capture.py expects raw_*
            "export_mode": ExportMode.RAW,            # untouched bytes from ESPN
            "groups": ["capture"],
        },
        # --- golden snapshot (parsed DATA) ---------------------------------
        {
            "type": "file",
            "filename": "/tmp/exp_%(team_abbr)s.json",   # <-- capture.py expects exp_*
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        team_abbr = self.opts['team_abbr']
        team_id = ESPN_TEAM_IDS.get(team_abbr)
        
        if not team_id:
            error_msg = f"Unknown team abbreviation: {team_abbr}"
            
            # Send error notification
            try:
                notify_error(
                    title="ESPN Roster API: Invalid Team",
                    message=f"Unknown team abbreviation '{team_abbr}'",
                    details={
                        'scraper': 'espn_roster_api',
                        'team_abbr': team_abbr,
                        'valid_abbreviations': sorted(ESPN_TEAM_IDS.keys()),
                        'error': error_msg
                    },
                    processor_name="ESPN Roster API Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise ValueError(f"{error_msg}. "
                           f"Valid abbreviations: {', '.join(sorted(ESPN_TEAM_IDS.keys()))}")
        
        base = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
        self.url = f"{base}/{team_id}?enable=roster"
        logger.info("Resolved ESPN roster API URL for %s (teamId %s): %s", team_abbr, team_id, self.url)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        root = self.decoded_data
        
        if not isinstance(root, dict):
            error_msg = "Roster response is not JSON dict."
            
            # Send error notification
            try:
                notify_error(
                    title="ESPN Roster API: Invalid Response",
                    message=f"Invalid response format for team {self.opts['team_abbr']}: {error_msg}",
                    details={
                        'scraper': 'espn_roster_api',
                        'team_abbr': self.opts['team_abbr'],
                        'espn_team_id': ESPN_TEAM_IDS.get(self.opts['team_abbr']),
                        'error': error_msg,
                        'response_type': type(root).__name__
                    },
                    processor_name="ESPN Roster API Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise ValueError(error_msg)
            
        if "team" not in root or "athletes" not in root["team"]:
            error_msg = "'team.athletes' missing in JSON."
            
            # Send error notification
            try:
                notify_error(
                    title="ESPN Roster API: Missing Data",
                    message=f"Missing 'team.athletes' for team {self.opts['team_abbr']}",
                    details={
                        'scraper': 'espn_roster_api',
                        'team_abbr': self.opts['team_abbr'],
                        'espn_team_id': ESPN_TEAM_IDS.get(self.opts['team_abbr']),
                        'error': error_msg,
                        'has_team': 'team' in root,
                        'root_keys': list(root.keys()) if isinstance(root, dict) else []
                    },
                    processor_name="ESPN Roster API Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise ValueError(error_msg)

    # ------------------------------------------------------------------ #
    # Transform
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        team_obj: Dict[str, Any] = self.decoded_data["team"]
        athletes: List[dict] = team_obj.get("athletes", [])

        # Warn if no athletes found
        if len(athletes) == 0:
            try:
                notify_warning(
                    title="ESPN Roster API: Empty Roster",
                    message=f"No athletes found for team {self.opts['team_abbr']}",
                    details={
                        'scraper': 'espn_roster_api',
                        'team_abbr': self.opts['team_abbr'],
                        'espn_team_id': ESPN_TEAM_IDS.get(self.opts['team_abbr']),
                        'athlete_count': 0
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

        players: List[Dict[str, Any]] = []
        for ath in athletes:
            # --- Height parsing ------------------------------------------------------
            height_raw = ath.get("height")
            height_in: int | None = None
            if isinstance(height_raw, dict):
                try:
                    feet = int(height_raw.get("feet", 0))
                    inches = int(height_raw.get("inches", 0))
                    height_in = feet * 12 + inches
                except (TypeError, ValueError):
                    height_in = None
            elif isinstance(height_raw, (int, float, str)):
                try:
                    height_in = int(height_raw)
                except ValueError:
                    height_in = None

            players.append(
                {
                    "playerId": ath.get("id"),
                    "fullName": ath.get("fullName"),
                    "jersey": ath.get("jersey"),
                    "position": (ath.get("position") or {}).get("displayName"),
                    "heightIn": height_in,
                    "weightLb": ath.get("weight"),
                    "injuries": ath.get("injuries", []),
                }
            )

        # Get ESPN team code from opts
        espn_team_abbr = self.opts["team_abbr"]  # e.g., "GS"
        
        # Convert to NBA.com standard code
        nba_team_abbr = ESPN_TO_NBA_TRICODE.get(espn_team_abbr, espn_team_abbr)  # e.g., "GSW"
        
        # Get ESPN team ID for API call
        team_id = ESPN_TEAM_IDS.get(espn_team_abbr)

        self.data = {
            "team_abbr": nba_team_abbr,           # ✅ Store NBA.com code
            "espn_team_abbr": espn_team_abbr,     # 📝 Optional: keep original for reference
            "espn_team_id": team_id,
            "teamName": team_obj.get("displayName"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "playerCount": len(players),
            "players": players,
        }
        logger.info("Parsed %d players for %s (ESPN: %s, NBA.com: %s, ESPN ID: %s)",
                len(players), espn_team_abbr, nba_team_abbr, team_id)

        # Update success notification
        try:
            notify_info(
                title="ESPN Roster API Scraped Successfully",
                message=f"Successfully scraped {len(players)} players for {nba_team_abbr}",
                details={
                    'scraper': 'espn_roster_api',
                    'espn_team_abbr': espn_team_abbr,
                    'nba_team_abbr': nba_team_abbr,
                    'espn_team_id': team_id,
                    'team_name': team_obj.get("displayName"),
                    'player_count': len(players)
                }
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")

    def resolve_url(self) -> None:
        espn_team_abbr = self.opts['team_abbr']
        team_id = ESPN_TEAM_IDS.get(espn_team_abbr)

        if not team_id:
            error_msg = f"Unknown ESPN team abbreviation: {espn_team_abbr}"
            
            # Send error notification
            try:
                notify_error(
                    title="ESPN Roster API: Invalid Team",
                    message=f"Unknown ESPN team abbreviation '{espn_team_abbr}'",
                    details={
                        'scraper': 'espn_roster_api',
                        'espn_team_abbr': espn_team_abbr,
                        'valid_espn_abbreviations': sorted(ESPN_TEAM_IDS.keys()),
                        'error': error_msg
                    },
                    processor_name="ESPN Roster API Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            raise ValueError(f"{error_msg}. "
                        f"Valid ESPN abbreviations: {', '.join(sorted(ESPN_TEAM_IDS.keys()))}")

        nba_team_abbr = ESPN_TO_NBA_TRICODE.get(espn_team_abbr, espn_team_abbr)
        base = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
        self.url = f"{base}/{team_id}?enable=roster"
        logger.info("Resolved ESPN roster API URL for %s (ESPN: %s, NBA.com: %s, teamId %s): %s", 
                espn_team_abbr, nba_team_abbr, team_id, self.url)


    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "team_abbr": self.opts["team_abbr"], 
            "espn_team_id": ESPN_TEAM_IDS.get(self.opts["team_abbr"]),
            "playerCount": self.data.get("playerCount", 0)
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetEspnTeamRosterAPI)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetEspnTeamRosterAPI.create_cli_and_flask_main()
    main()
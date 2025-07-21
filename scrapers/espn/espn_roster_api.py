"""
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

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py espn_roster_api \
      --teamId 2 \
      --debug

  # Direct CLI execution:
  python scrapers/espn/espn_roster_api.py --teamId 2 --debug

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
except ImportError:
    # Direct execution: python scrapers/espn/espn_roster_api.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper

logger = logging.getLogger("scraper_base")


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class GetEspnTeamRosterAPI(ScraperBase, ScraperFlaskMixin):
    """
    Scrape a single NBA roster via ESPN's JSON API.
    """

    # Flask Mixin Configuration
    scraper_name = "espn_roster_api"
    required_params = ["teamId"]  # teamId is required
    optional_params = {}

    # Original scraper config
    required_opts: List[str] = ["teamId"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = "espn"

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": "espn/roster-api/%(teamId)s_%(run_id)s.raw.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/espn_roster_api_%(teamId)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        # --- raw fixture for offline tests ---------------------------------
        {
            "type": "file",
            "filename": "/tmp/raw_%(teamId)s.json",   # <-- capture.py expects raw_*
            "export_mode": ExportMode.RAW,            # untouched bytes from ESPN
            "groups": ["capture"],
        },
        # --- golden snapshot (parsed DATA) ---------------------------------
        {
            "type": "file",
            "filename": "/tmp/exp_%(teamId)s.json",   # <-- capture.py expects exp_*
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        base = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
        self.url = f"{base}/{self.opts['teamId']}?enable=roster"
        logger.info("Resolved ESPN roster API URL: %s", self.url)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        root = self.decoded_data
        if not isinstance(root, dict):
            raise ValueError("Roster response is not JSON dict.")
        if "team" not in root or "athletes" not in root["team"]:
            raise ValueError("'team.athletes' missing in JSON.")

    # ------------------------------------------------------------------ #
    # Transform
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        team_obj: Dict[str, Any] = self.decoded_data["team"]
        athletes: List[dict] = team_obj.get("athletes", [])

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

        self.data = {
            "teamId": self.opts["teamId"],
            "teamName": team_obj.get("displayName"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "playerCount": len(players),
            "players": players,
        }
        logger.info("Parsed %d players for teamId=%s", len(players), self.opts["teamId"])

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"teamId": self.opts["teamId"], "playerCount": self.data.get("playerCount", 0)}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetEspnTeamRosterAPI)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetEspnTeamRosterAPI.create_cli_and_flask_main()
    main()
    
"""
File: scrapers/mlb/mlbstatsapi/mlb_umpire_assignments.py

MLB Stats API - Daily Umpire Assignments                            v1.0 - 2026-03-07
--------------------------------------------------------------------------------
Fetches home plate umpire for each game from the MLB Stats API schedule endpoint.

Two-step data flow:
1. This scraper: game_date → home plate umpire name + ID per game
2. Umpire stats scraper (UmpScorecards): umpire name → K tendency, zone size

API: https://statsapi.mlb.com/api/v1/schedule?date={date}&sportId=1&hydrate=officials
Free, no auth, cloud-friendly.

Output: List of game-umpire assignments with home/away teams.

Usage:
  python scrapers/mlb/mlbstatsapi/mlb_umpire_assignments.py --date 2025-06-15 --debug
  python scrapers/mlb/mlbstatsapi/mlb_umpire_assignments.py --debug  # defaults to today
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

try:
    from ...scraper_base import DownloadType, ExportMode, ScraperBase
    from ...scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper

logger = logging.getLogger(__name__)


class MlbUmpireAssignmentsScraper(ScraperBase, ScraperFlaskMixin):
    """
    Fetches home plate umpire assignments for each MLB game on a given date.

    Uses the MLB Stats API schedule endpoint with officials hydration.
    Critical for K predictions — umpire strike zone size varies significantly.
    """

    scraper_name = "mlb_umpire_assignments"
    required_params = ["date"]
    optional_params = {}

    required_opts: List[str] = ["date"]
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    exporters = [
        {
            "type": "gcs",
            "key": "mlb-stats-api/umpire-assignments/%(date)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_umpire_assignments_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    _SCHEDULE_API = "https://statsapi.mlb.com/api/v1/schedule"

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        if not self.opts.get("date"):
            self.opts["date"] = datetime.now(timezone.utc).date().isoformat()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    def set_url(self) -> None:
        date = self.opts["date"]
        self.url = (
            f"{self._SCHEDULE_API}?date={date}&sportId=1"
            f"&hydrate=officials&gameTypes=R,P"
        )

    def set_headers(self) -> None:
        self.headers = {
            "User-Agent": "mlb-umpire-assignments/1.0",
            "Accept": "application/json",
        }

    def transform_data(self) -> None:
        """Extract home plate umpire for each game."""
        target_date = self.opts["date"]
        assignments = []

        all_games = []
        for date_entry in self.decoded_data.get("dates", []):
            all_games.extend(date_entry.get("games", []))

        for game in all_games:
            game_pk = game.get("gamePk")
            status = game.get("status", {}).get("detailedState", "")

            teams = game.get("teams", {})
            home_abbr = teams.get("home", {}).get("team", {}).get("abbreviation", "")
            away_abbr = teams.get("away", {}).get("team", {}).get("abbreviation", "")

            officials = game.get("officials", [])
            hp_ump = next(
                (o for o in officials if o.get("officialType") == "Home Plate"),
                None
            )

            if hp_ump:
                official = hp_ump.get("official", {})
                assignments.append({
                    "game_pk": game_pk,
                    "game_date": target_date,
                    "home_team": home_abbr,
                    "away_team": away_abbr,
                    "game_status": status,
                    "umpire_name": official.get("fullName", ""),
                    "umpire_id": official.get("id"),
                    "umpire_link": official.get("link", ""),
                })
            else:
                logger.debug("No HP umpire for game %s (%s @ %s)", game_pk, away_abbr, home_abbr)

        self.data = {
            "date": target_date,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "games_total": len(all_games),
            "assignments": assignments,
            "games_with_umpire": len(assignments),
            "games_without_umpire": len(all_games) - len(assignments),
        }

        logger.info(
            "Found %d umpire assignments for %d games on %s",
            len(assignments), len(all_games), target_date
        )

    def get_scraper_stats(self) -> dict:
        if not self.data:
            return {}
        return {
            "date": self.opts.get("date"),
            "games_total": self.data.get("games_total", 0),
            "assignments": self.data.get("games_with_umpire", 0),
        }


create_app = convert_existing_flask_scraper(MlbUmpireAssignmentsScraper)

if __name__ == "__main__":
    main = MlbUmpireAssignmentsScraper.create_cli_and_flask_main()
    main()

"""
File: scrapers/mlb/balldontlie/mlb_teams.py

MLB Ball Don't Lie - Teams                                        v1.0 - 2026-01-06
--------------------------------------------------------------------------------
MLB team reference data from Ball Don't Lie API.

API Endpoint: https://api.balldontlie.io/mlb/v1/teams

Key Fields:
- id: BDL team ID
- abbreviation: Team abbreviation (NYY, LAD, etc.)
- city, name, full_name: Team name variants
- league: AL or NL
- division: East, Central, West

Used for:
- Team ID lookups and validation
- League/division categorization
- Reference data for joins

Usage:
  python scrapers/mlb/balldontlie/mlb_teams.py --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from ...scraper_base import DownloadType, ExportMode, ScraperBase
    from ...scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from ...utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

logger = logging.getLogger(__name__)


class MlbTeamsScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for MLB team reference data from Ball Don't Lie API.

    Provides team metadata for lookups and validation.
    """

    scraper_name = "mlb_teams"
    required_params = []
    optional_params = {
        "api_key": None,
    }

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    GCS_PATH_KEY = "mlb_teams"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_teams_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts["date"] = datetime.now(timezone.utc).date().isoformat()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    _API_ROOT = "https://api.balldontlie.io/mlb/v1/teams"

    def set_url(self) -> None:
        self.url = self._API_ROOT
        logger.debug("MLB Teams URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_MLB_API_KEY") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "mlb-teams-scraper/1.0",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = api_key

    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("MLB teams response malformed")

    def transform_data(self) -> None:
        teams: List[Dict[str, Any]] = list(self.decoded_data["data"])

        # Organize by division
        by_division = {
            "AL_East": [],
            "AL_Central": [],
            "AL_West": [],
            "NL_East": [],
            "NL_Central": [],
            "NL_West": [],
        }

        # Create lookup maps
        abbr_to_id = {}
        id_to_abbr = {}

        for team in teams:
            team_id = team.get("id")
            abbr = team.get("abbreviation")
            league = team.get("league", "")
            division = team.get("division", "")

            abbr_to_id[abbr] = team_id
            id_to_abbr[team_id] = abbr

            div_key = f"{league}_{division}"
            if div_key in by_division:
                by_division[div_key].append({
                    "id": team_id,
                    "abbreviation": abbr,
                    "full_name": team.get("full_name"),
                })

        self.data = {
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "teamCount": len(teams),
            "teams": teams,
            "byDivision": by_division,
            "lookups": {
                "abbrToId": abbr_to_id,
                "idToAbbr": id_to_abbr,
            },
        }

        logger.info("Fetched %d MLB teams", len(teams))

    def get_scraper_stats(self) -> dict:
        return {
            "teamCount": self.data.get("teamCount", 0),
        }


create_app = convert_existing_flask_scraper(MlbTeamsScraper)

if __name__ == "__main__":
    main = MlbTeamsScraper.create_cli_and_flask_main()
    main()

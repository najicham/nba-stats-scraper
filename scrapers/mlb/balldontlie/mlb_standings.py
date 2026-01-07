"""
File: scrapers/mlb/balldontlie/mlb_standings.py

MLB Ball Don't Lie - Standings                                    v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Division and league standings for MLB teams.

API Endpoint: https://api.balldontlie.io/mlb/v1/standings

Key Fields:
- team: Team info
- wins, losses, win_percentage
- games_back: Games behind division leader
- division_rank, league_rank
- streak: Current win/loss streak
- last_10: Record in last 10 games

Important for strikeout predictions:
- Playoff race context (teams playing harder in meaningful games)
- is_playoff_contender feature
- games_back indicates urgency

Usage:
  python scrapers/mlb/balldontlie/mlb_standings.py --debug
  python scrapers/mlb/balldontlie/mlb_standings.py --season 2025
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


class MlbStandingsScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for MLB standings from Ball Don't Lie API.

    Provides playoff race context for predictions:
    - Teams in tight races may have pitchers throwing harder
    - Elimination scenarios affect game intensity
    - Wild card races create pressure situations
    """

    scraper_name = "mlb_standings"
    required_params = []
    optional_params = {
        "season": None,  # MLB season year (e.g., 2025)
        "api_key": None,
    }

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    GCS_PATH_KEY = "mlb_standings"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_standings_%(season)s_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts["date"] = datetime.now(timezone.utc).date().isoformat()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Default to current season based on date
        if not self.opts.get("season"):
            now = datetime.now(timezone.utc)
            # MLB season runs April-October
            # If before April, use previous year
            if now.month < 4:
                self.opts["season"] = str(now.year - 1)
            else:
                self.opts["season"] = str(now.year)

    _API_ROOT = "https://api.balldontlie.io/mlb/v1/standings"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        params = []

        if self.opts.get("season"):
            params.append(f"season={self.opts['season']}")

        if params:
            self.url = f"{self.base_url}?{'&'.join(params)}"
        else:
            self.url = self.base_url

        logger.debug("MLB Standings URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_MLB_API_KEY") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "mlb-standings-scraper/1.0",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = api_key

    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("MLB standings response malformed")

    def transform_data(self) -> None:
        standings: List[Dict[str, Any]] = list(self.decoded_data["data"])
        cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")
        pages_fetched = 1

        while cursor:
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params={"cursor": cursor, "season": self.opts.get("season")},
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            page_json = resp.json()
            standings.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")
            pages_fetched += 1

        # Organize by division
        al_east = [s for s in standings if self._get_division(s) == "AL East"]
        al_central = [s for s in standings if self._get_division(s) == "AL Central"]
        al_west = [s for s in standings if self._get_division(s) == "AL West"]
        nl_east = [s for s in standings if self._get_division(s) == "NL East"]
        nl_central = [s for s in standings if self._get_division(s) == "NL Central"]
        nl_west = [s for s in standings if self._get_division(s) == "NL West"]

        # Calculate playoff contenders (within 10 games of wild card)
        playoff_contenders = self._identify_playoff_contenders(standings)

        self.data = {
            "season": self.opts.get("season"),
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "teamCount": len(standings),
            "standings": standings,
            "byDivision": {
                "AL_East": sorted(al_east, key=lambda x: x.get("division_rank", 99)),
                "AL_Central": sorted(al_central, key=lambda x: x.get("division_rank", 99)),
                "AL_West": sorted(al_west, key=lambda x: x.get("division_rank", 99)),
                "NL_East": sorted(nl_east, key=lambda x: x.get("division_rank", 99)),
                "NL_Central": sorted(nl_central, key=lambda x: x.get("division_rank", 99)),
                "NL_West": sorted(nl_west, key=lambda x: x.get("division_rank", 99)),
            },
            "playoffContenders": playoff_contenders,
        }

        logger.info("Fetched standings for %d teams (season %s) across %d pages",
                   len(standings), self.opts.get("season"), pages_fetched)

    def _get_division(self, standing: Dict[str, Any]) -> str:
        """Extract division from standing record."""
        team = standing.get("team", {})
        division = team.get("division", "")
        league = team.get("league", "")

        if division and league:
            return f"{league} {division}"
        return standing.get("division", "Unknown")

    def _identify_playoff_contenders(self, standings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Identify teams in playoff contention.

        A team is a contender if:
        - Division rank 1-2 (division leader or close)
        - OR games_back <= 10 from wild card spot
        """
        contenders = []
        for s in standings:
            team = s.get("team", {})
            games_back = s.get("games_back", 0)
            division_rank = s.get("division_rank", 99)

            # Try to parse games_back if it's a string like "5.5"
            try:
                gb = float(games_back) if games_back else 0
            except (ValueError, TypeError):
                gb = 0

            is_contender = division_rank <= 2 or gb <= 10

            if is_contender:
                contenders.append({
                    "team_id": team.get("id"),
                    "team_abbr": team.get("abbreviation"),
                    "team_name": team.get("full_name"),
                    "division_rank": division_rank,
                    "games_back": games_back,
                    "wins": s.get("wins"),
                    "losses": s.get("losses"),
                    "is_division_leader": division_rank == 1,
                })

        return contenders

    def get_scraper_stats(self) -> dict:
        return {
            "teamCount": self.data.get("teamCount", 0),
            "playoffContenderCount": len(self.data.get("playoffContenders", [])),
            "season": self.data.get("season"),
        }


create_app = convert_existing_flask_scraper(MlbStandingsScraper)

if __name__ == "__main__":
    main = MlbStandingsScraper.create_cli_and_flask_main()
    main()

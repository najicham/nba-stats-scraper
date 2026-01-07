"""
File: scrapers/mlb/balldontlie/mlb_team_season_stats.py

MLB Ball Don't Lie - Team Season Stats                            v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Team-level season statistics for all MLB teams.

API Endpoint: https://api.balldontlie.io/mlb/v1/teams/season_stats

Key Fields:
- team: Team info
- batting: Team batting stats (strikeouts, avg, OBP, etc.)
- pitching: Team pitching stats (K/9, ERA, WHIP, etc.)

Important for strikeout predictions:
- opponent_team_k_rate: How often opposing team strikes out
- team_batting_k_pct: Team's strikeout tendency
- Helps calibrate bottom-up model expectations

Usage:
  python scrapers/mlb/balldontlie/mlb_team_season_stats.py --debug
  python scrapers/mlb/balldontlie/mlb_team_season_stats.py --season 2025
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


class MlbTeamSeasonStatsScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for MLB team season statistics from Ball Don't Lie API.

    Used for:
    - Team-level K rates (opponent_team_k_rate feature)
    - Team batting tendencies (how often they strike out)
    - Calibrating bottom-up model expectations
    """

    scraper_name = "mlb_team_season_stats"
    required_params = []
    optional_params = {
        "season": None,     # MLB season year (e.g., 2025)
        "team_ids": None,   # Specific team IDs (comma-separated)
        "api_key": None,
    }

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    GCS_PATH_KEY = "mlb_team_season_stats"
    exporters = [
        {
            "type": "gcs",
            "key": "mlb-ball-dont-lie/team-season-stats/%(season)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_team_season_stats_%(season)s_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts["date"] = datetime.now(timezone.utc).date().isoformat()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Default to current season
        if not self.opts.get("season"):
            now = datetime.now(timezone.utc)
            if now.month < 4:
                self.opts["season"] = str(now.year - 1)
            else:
                self.opts["season"] = str(now.year)

    _API_ROOT = "https://api.balldontlie.io/mlb/v1/teams/season_stats"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        params = []

        if self.opts.get("season"):
            params.append(f"season={self.opts['season']}")

        if self.opts.get("team_ids"):
            for tid in str(self.opts["team_ids"]).split(","):
                params.append(f"team_ids[]={tid.strip()}")

        if params:
            self.url = f"{self.base_url}?{'&'.join(params)}"
        else:
            self.url = self.base_url

        logger.debug("MLB Team Season Stats URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_MLB_API_KEY") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "mlb-team-season-stats-scraper/1.0",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = api_key

    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("MLB team season stats response malformed")

    def transform_data(self) -> None:
        team_stats: List[Dict[str, Any]] = list(self.decoded_data["data"])
        cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")
        pages_fetched = 1

        while cursor:
            params = {"cursor": cursor}
            if self.opts.get("season"):
                params["season"] = self.opts["season"]

            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params=params,
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            page_json = resp.json()
            team_stats.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")
            pages_fetched += 1

        # Extract K-relevant stats for easy access
        k_stats = self._extract_k_stats(team_stats)

        # Rank teams by K rate (for identifying high-K opponents)
        k_stats_sorted = sorted(k_stats, key=lambda x: x.get("batting_k_pct", 0), reverse=True)

        self.data = {
            "season": self.opts.get("season"),
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "teamCount": len(team_stats),
            "teamStats": team_stats,
            "kStats": k_stats,
            "highKTeams": k_stats_sorted[:10],  # Top 10 strikeout teams (good for pitchers)
            "lowKTeams": k_stats_sorted[-10:],   # Bottom 10 (tough matchups)
        }

        logger.info("Fetched season stats for %d teams (season %s)",
                   len(team_stats), self.opts.get("season"))

    def _extract_k_stats(self, team_stats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract strikeout-relevant statistics for each team.

        Returns simplified K stats for model features.
        """
        k_stats = []

        for ts in team_stats:
            team = ts.get("team", {})
            batting = ts.get("batting", {})
            pitching = ts.get("pitching", {})

            # Calculate batting K percentage
            at_bats = batting.get("ab", 0)
            strikeouts = batting.get("so", 0)
            batting_k_pct = (strikeouts / at_bats * 100) if at_bats > 0 else 0

            # Get pitching K rate
            pitching_k_per_9 = pitching.get("k_per_9", 0) or pitching.get("so9", 0)
            pitching_k_total = pitching.get("so", 0)
            innings_pitched = pitching.get("ip", 0)

            k_stats.append({
                "team_id": team.get("id"),
                "team_abbr": team.get("abbreviation"),
                "team_name": team.get("full_name"),
                # Batting (how often this team strikes out)
                "batting_strikeouts": strikeouts,
                "batting_at_bats": at_bats,
                "batting_k_pct": round(batting_k_pct, 2),
                "batting_avg": batting.get("avg", 0),
                "batting_obp": batting.get("obp", 0),
                # Pitching (how often this team's pitchers strike out batters)
                "pitching_k_per_9": round(float(pitching_k_per_9 or 0), 2),
                "pitching_k_total": pitching_k_total,
                "pitching_innings": innings_pitched,
                "pitching_era": pitching.get("era", 0),
                "pitching_whip": pitching.get("whip", 0),
                # Derived features for model
                "is_high_k_team": batting_k_pct > 24,  # Above average K%
                "is_low_k_team": batting_k_pct < 20,   # Below average K%
            })

        return k_stats

    def get_scraper_stats(self) -> dict:
        return {
            "teamCount": self.data.get("teamCount", 0),
            "season": self.data.get("season"),
            "highKTeamCount": len([k for k in self.data.get("kStats", []) if k.get("is_high_k_team")]),
        }


create_app = convert_existing_flask_scraper(MlbTeamSeasonStatsScraper)

if __name__ == "__main__":
    main = MlbTeamSeasonStatsScraper.create_cli_and_flask_main()
    main()

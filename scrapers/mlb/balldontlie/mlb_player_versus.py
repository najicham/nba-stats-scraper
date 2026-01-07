"""
File: scrapers/mlb/balldontlie/mlb_player_versus.py

MLB Ball Don't Lie - Player Versus (Head-to-Head)                 v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Historical head-to-head matchup data between pitchers and teams/batters.

API Endpoint: https://api.balldontlie.io/mlb/v1/players/versus

Key Fields:
- player: Pitcher info
- opponent_team: Team faced
- stats: Historical stats against that opponent
  - games, at_bats, strikeouts, hits, walks, avg, k_rate

Important for strikeout predictions:
- vs_opponent_k_rate: Pitcher's K rate against specific team
- Historical dominance or struggle against certain lineups
- Critical for matchup-specific adjustments

Usage:
  python scrapers/mlb/balldontlie/mlb_player_versus.py --player_id 12345 --debug
  python scrapers/mlb/balldontlie/mlb_player_versus.py --player_id 12345 --opponent_team_id 10
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


class MlbPlayerVersusScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for MLB player head-to-head matchup data from Ball Don't Lie API.

    Used for:
    - vs_opponent_k_rate feature (pitcher K rate vs specific team)
    - Identifying favorable/unfavorable matchups
    - Historical dominance adjustments
    """

    scraper_name = "mlb_player_versus"
    required_params = ["player_id"]  # Must specify which player
    optional_params = {
        "opponent_team_id": None,  # Specific opponent (optional)
        "season": None,            # Filter by season
        "api_key": None,
    }

    required_opts: List[str] = ["player_id"]
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    GCS_PATH_KEY = "mlb_player_versus"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_player_versus_%(player_id)s_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts["date"] = datetime.now(timezone.utc).date().isoformat()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Default season
        if not self.opts.get("season"):
            now = datetime.now(timezone.utc)
            if now.month < 4:
                self.opts["season"] = str(now.year - 1)
            else:
                self.opts["season"] = str(now.year)

    _API_ROOT = "https://api.balldontlie.io/mlb/v1/players/versus"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        params = [f"player_id={self.opts['player_id']}"]

        if self.opts.get("opponent_team_id"):
            params.append(f"opponent_team_id={self.opts['opponent_team_id']}")

        if self.opts.get("season"):
            params.append(f"season={self.opts['season']}")

        self.url = f"{self.base_url}?{'&'.join(params)}"
        logger.debug("MLB Player Versus URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_MLB_API_KEY") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "mlb-player-versus-scraper/1.0",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = api_key

    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("MLB player versus response malformed")

    def transform_data(self) -> None:
        matchups: List[Dict[str, Any]] = list(self.decoded_data["data"])
        cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")
        pages_fetched = 1

        while cursor:
            params = {
                "cursor": cursor,
                "player_id": self.opts["player_id"],
            }
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
            matchups.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")
            pages_fetched += 1

        # Calculate K rates for each matchup
        k_matchups = self._calculate_k_rates(matchups)

        # Sort by sample size (most reliable first)
        k_matchups_sorted = sorted(k_matchups, key=lambda x: x.get("batters_faced", 0), reverse=True)

        # Identify favorable and unfavorable matchups
        favorable = [m for m in k_matchups if m.get("k_rate", 0) > 25]  # High K rate
        unfavorable = [m for m in k_matchups if m.get("k_rate", 0) < 18]  # Low K rate

        self.data = {
            "player_id": self.opts["player_id"],
            "season": self.opts.get("season"),
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "matchupCount": len(matchups),
            "matchups": matchups,
            "kMatchups": k_matchups_sorted,
            "favorableMatchups": favorable,
            "unfavorableMatchups": unfavorable,
        }

        logger.info("Fetched %d matchups for player %s (season %s)",
                   len(matchups), self.opts["player_id"], self.opts.get("season"))

    def _calculate_k_rates(self, matchups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Calculate strikeout rates for each opponent matchup.
        """
        k_matchups = []

        for m in matchups:
            opponent = m.get("opponent_team", {})
            stats = m.get("stats", {})

            # Get relevant stats
            batters_faced = stats.get("bf", 0) or stats.get("batters_faced", 0)
            strikeouts = stats.get("so", 0) or stats.get("k", 0) or stats.get("strikeouts", 0)
            innings = stats.get("ip", 0)
            hits = stats.get("h", 0)
            walks = stats.get("bb", 0)
            games = stats.get("g", 0) or stats.get("games", 0)

            # Calculate K rate
            k_rate = (strikeouts / batters_faced * 100) if batters_faced > 0 else 0
            k_per_9 = (strikeouts / float(innings) * 9) if innings and float(innings) > 0 else 0

            k_matchups.append({
                "opponent_team_id": opponent.get("id"),
                "opponent_abbr": opponent.get("abbreviation"),
                "opponent_name": opponent.get("full_name"),
                # Sample size
                "games": games,
                "batters_faced": batters_faced,
                "innings_pitched": innings,
                # K stats
                "strikeouts": strikeouts,
                "k_rate": round(k_rate, 2),
                "k_per_9": round(k_per_9, 2),
                # Other stats
                "hits_allowed": hits,
                "walks": walks,
                "whip": round((hits + walks) / float(innings), 2) if innings and float(innings) > 0 else 0,
                # Reliability
                "is_reliable": batters_faced >= 20,  # Minimum sample size
                "sample_size_category": self._categorize_sample(batters_faced),
            })

        return k_matchups

    def _categorize_sample(self, batters_faced: int) -> str:
        """Categorize sample size reliability."""
        if batters_faced >= 100:
            return "large"
        elif batters_faced >= 50:
            return "medium"
        elif batters_faced >= 20:
            return "small"
        else:
            return "insufficient"

    def get_scraper_stats(self) -> dict:
        return {
            "matchupCount": self.data.get("matchupCount", 0),
            "player_id": self.data.get("player_id"),
            "favorableCount": len(self.data.get("favorableMatchups", [])),
            "unfavorableCount": len(self.data.get("unfavorableMatchups", [])),
        }


create_app = convert_existing_flask_scraper(MlbPlayerVersusScraper)

if __name__ == "__main__":
    main = MlbPlayerVersusScraper.create_cli_and_flask_main()
    main()

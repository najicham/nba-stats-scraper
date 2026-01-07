"""
File: scrapers/mlb/balldontlie/mlb_box_scores.py

MLB Ball Don't Lie - Box Scores (Final)                           v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Final box scores for completed MLB games.

API Endpoint: https://api.balldontlie.io/mlb/v1/box_scores

Key Fields:
- game: Game info (id, date, status, score)
- home_team, away_team: Team info
- home_team_stats, away_team_stats: Team totals
- players: Individual player stats (pitchers and batters)

Important for strikeout predictions:
- Post-game grading: Get actual pitcher strikeout count
- Model accuracy tracking
- Historical data for training

Usage:
  python scrapers/mlb/balldontlie/mlb_box_scores.py --debug
  python scrapers/mlb/balldontlie/mlb_box_scores.py --date 2025-06-15
  python scrapers/mlb/balldontlie/mlb_box_scores.py --game_ids 12345,12346
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
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


class MlbBoxScoresScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for final MLB box scores from Ball Don't Lie API.

    Used for:
    - Grading predictions (actual K count vs predicted)
    - Training data collection (historical results)
    - Model accuracy tracking
    """

    scraper_name = "mlb_box_scores"
    required_params = []
    optional_params = {
        "date": None,       # Single date (YYYY-MM-DD), defaults to yesterday
        "game_ids": None,   # Specific game IDs (comma-separated)
        "api_key": None,
    }

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    GCS_PATH_KEY = "mlb_box_scores"
    exporters = [
        {
            "type": "gcs",
            "key": "mlb-ball-dont-lie/box-scores/%(date)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_box_scores_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Default to yesterday (for completed games)
        if not self.opts.get("date") and not self.opts.get("game_ids"):
            yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
            self.opts["date"] = yesterday.isoformat()

    _API_ROOT = "https://api.balldontlie.io/mlb/v1/box_scores"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        params = ["per_page=100"]

        if self.opts.get("date"):
            params.append(f"date={self.opts['date']}")

        if self.opts.get("game_ids"):
            for gid in str(self.opts["game_ids"]).split(","):
                params.append(f"game_ids[]={gid.strip()}")

        self.url = f"{self.base_url}?{'&'.join(params)}"
        logger.debug("MLB Box Scores URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_MLB_API_KEY") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "mlb-box-scores-scraper/1.0",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = api_key

    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("MLB box scores response malformed")

    def transform_data(self) -> None:
        box_scores: List[Dict[str, Any]] = list(self.decoded_data["data"])
        cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")
        pages_fetched = 1

        while cursor:
            params = {"cursor": cursor, "per_page": 100}
            if self.opts.get("date"):
                params["date"] = self.opts["date"]

            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params=params,
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            page_json = resp.json()
            box_scores.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")
            pages_fetched += 1

        # Extract pitcher strikeout summaries for easy grading
        pitcher_summaries = self._extract_pitcher_summaries(box_scores)

        # Filter to only completed games
        completed_games = [
            bs for bs in box_scores
            if bs.get("game", {}).get("status", "").lower() in ["final", "completed", "f"]
        ]

        self.data = {
            "date": self.opts.get("date"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gameCount": len(box_scores),
            "completedGameCount": len(completed_games),
            "boxScores": box_scores,
            "pitcherSummaries": pitcher_summaries,
        }

        logger.info("Fetched %d box scores (%d completed) for date %s across %d pages",
                   len(box_scores), len(completed_games),
                   self.opts.get("date"), pages_fetched)

    def _extract_pitcher_summaries(self, box_scores: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract pitcher performance summaries for easy prediction grading.

        Returns a list of pitcher stats with actual strikeout counts.
        """
        summaries = []

        for bs in box_scores:
            game = bs.get("game", {})
            game_id = game.get("id")
            game_date = game.get("date")
            game_status = game.get("status", "")

            # Only process completed games
            if game_status.lower() not in ["final", "completed", "f"]:
                continue

            # Process home team pitchers
            home_team = bs.get("home_team", {})
            home_players = bs.get("players", {}).get("home", [])
            for player in home_players:
                if self._is_pitcher(player):
                    summaries.append(self._build_pitcher_summary(
                        player, game_id, game_date, home_team, "home"
                    ))

            # Process away team pitchers
            away_team = bs.get("away_team", {})
            away_players = bs.get("players", {}).get("away", [])
            for player in away_players:
                if self._is_pitcher(player):
                    summaries.append(self._build_pitcher_summary(
                        player, game_id, game_date, away_team, "away"
                    ))

        return summaries

    def _is_pitcher(self, player: Dict[str, Any]) -> bool:
        """Check if player record is for a pitcher."""
        position = player.get("position", "").lower()
        # Check for pitching stats
        has_pitching_stats = any([
            player.get("p_k"),  # Strikeouts
            player.get("p_ip"),  # Innings pitched
            player.get("p_er"),  # Earned runs
            player.get("p_h"),   # Hits allowed
        ])
        return has_pitching_stats or position in ["sp", "rp", "cp", "p", "pitcher"]

    def _build_pitcher_summary(
        self,
        player: Dict[str, Any],
        game_id: int,
        game_date: str,
        team: Dict[str, Any],
        home_away: str
    ) -> Dict[str, Any]:
        """Build a pitcher summary record for grading."""
        player_info = player.get("player", {})

        return {
            "game_id": game_id,
            "game_date": game_date,
            "player_id": player_info.get("id"),
            "player_name": player_info.get("full_name") or f"{player_info.get('first_name', '')} {player_info.get('last_name', '')}".strip(),
            "team_id": team.get("id"),
            "team_abbr": team.get("abbreviation"),
            "home_away": home_away,
            # Actual stats for grading
            "actual_strikeouts": player.get("p_k", 0),
            "innings_pitched": player.get("p_ip", 0),
            "hits_allowed": player.get("p_h", 0),
            "walks": player.get("p_bb", 0),
            "earned_runs": player.get("p_er", 0),
            "pitches": player.get("p_pitches", 0),
            "strikes": player.get("p_strikes", 0),
            # Derived
            "is_starter": player.get("p_gs", 0) == 1 or player.get("batting_order") == 0,
            "is_winning_pitcher": player.get("p_w", 0) == 1,
            "is_losing_pitcher": player.get("p_l", 0) == 1,
            "is_save": player.get("p_sv", 0) == 1,
        }

    def get_scraper_stats(self) -> dict:
        return {
            "gameCount": self.data.get("gameCount", 0),
            "completedGameCount": self.data.get("completedGameCount", 0),
            "pitcherCount": len(self.data.get("pitcherSummaries", [])),
        }


create_app = convert_existing_flask_scraper(MlbBoxScoresScraper)

if __name__ == "__main__":
    main = MlbBoxScoresScraper.create_cli_and_flask_main()
    main()

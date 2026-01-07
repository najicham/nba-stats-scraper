"""
File: scrapers/mlb/balldontlie/mlb_live_box_scores.py

MLB Ball Don't Lie - Live Box Scores                              v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Real-time box scores for games currently in progress.

API Endpoint: https://api.balldontlie.io/mlb/v1/box_scores/live

Key Fields:
- game: Game info with current inning/score
- home_team, away_team: Team info
- players: Live player stats (pitchers and batters)
- Current pitcher stats updated in real-time

Important for live betting:
- Track pitcher strikeout count during game
- Compare to betting line for live signals
- "On pace" calculations for over/under
- Early cash-out recommendations

Usage:
  python scrapers/mlb/balldontlie/mlb_live_box_scores.py --debug

  # Run every 5 minutes during games:
  watch -n 300 python scrapers/mlb/balldontlie/mlb_live_box_scores.py --debug
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


class MlbLiveBoxScoresScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for live MLB box scores from Ball Don't Lie API.

    Used for live betting features:
    - Real-time pitcher K tracking
    - On-pace calculations
    - Live betting signals
    - Early cash-out recommendations
    """

    scraper_name = "mlb_live_box_scores"
    required_params = []
    optional_params = {
        "api_key": None,
    }

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    GCS_PATH_KEY = "mlb_live_box_scores"
    exporters = [
        {
            "type": "gcs",
            "key": "mlb-ball-dont-lie/live-box-scores/%(date)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_live_box_scores_%(date)s_%(timestamp)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts["date"] = datetime.now(timezone.utc).date().isoformat()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    _API_ROOT = "https://api.balldontlie.io/mlb/v1/box_scores/live"

    def set_url(self) -> None:
        self.url = self._API_ROOT
        logger.debug("MLB Live Box Scores URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_MLB_API_KEY") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "mlb-live-box-scores-scraper/1.0",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = api_key

    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("MLB live box scores response malformed")

    def transform_data(self) -> None:
        live_games: List[Dict[str, Any]] = list(self.decoded_data["data"])

        # Extract current pitcher K status for live tracking
        live_pitcher_stats = self._extract_live_pitcher_stats(live_games)

        # Calculate on-pace projections
        for stat in live_pitcher_stats:
            stat["on_pace_projection"] = self._calculate_on_pace(stat)

        self.data = {
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gamesInProgress": len(live_games),
            "liveGames": live_games,
            "livePitcherStats": live_pitcher_stats,
        }

        if live_games:
            logger.info("Found %d games in progress with %d pitchers",
                       len(live_games), len(live_pitcher_stats))
        else:
            logger.info("No games currently in progress")

    def _extract_live_pitcher_stats(self, live_games: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract current pitcher stats from live games.

        Returns live K counts and game context for each active pitcher.
        """
        stats = []

        for game_data in live_games:
            game = game_data.get("game", {})
            game_id = game.get("id")
            current_inning = game.get("inning", 0)
            inning_half = game.get("inning_half", "")  # "top" or "bottom"

            # Home team pitchers (pitching when inning_half is "top")
            home_team = game_data.get("home_team", {})
            home_players = game_data.get("players", {}).get("home", [])
            for player in home_players:
                if self._is_active_pitcher(player):
                    stats.append(self._build_live_stat(
                        player, game_id, game, home_team, "home",
                        current_inning, inning_half
                    ))

            # Away team pitchers (pitching when inning_half is "bottom")
            away_team = game_data.get("away_team", {})
            away_players = game_data.get("players", {}).get("away", [])
            for player in away_players:
                if self._is_active_pitcher(player):
                    stats.append(self._build_live_stat(
                        player, game_id, game, away_team, "away",
                        current_inning, inning_half
                    ))

        return stats

    def _is_active_pitcher(self, player: Dict[str, Any]) -> bool:
        """Check if player is a pitcher with stats in this game."""
        # Has pitching stats
        has_pitching = any([
            player.get("p_k"),
            player.get("p_ip"),
            player.get("p_pitches"),
        ])
        return has_pitching

    def _build_live_stat(
        self,
        player: Dict[str, Any],
        game_id: int,
        game: Dict[str, Any],
        team: Dict[str, Any],
        home_away: str,
        current_inning: int,
        inning_half: str
    ) -> Dict[str, Any]:
        """Build a live pitcher stat record."""
        player_info = player.get("player", {})

        innings_pitched = player.get("p_ip", 0)
        current_ks = player.get("p_k", 0)

        # Parse innings pitched (can be like "5.2" for 5 2/3 innings)
        try:
            ip_float = float(innings_pitched) if innings_pitched else 0
            # Convert .1 and .2 notation to actual thirds
            ip_whole = int(ip_float)
            ip_fraction = ip_float - ip_whole
            if ip_fraction > 0.25:
                ip_fraction = ip_fraction * 10 / 3  # .1 = 1/3, .2 = 2/3
            innings_decimal = ip_whole + ip_fraction
        except (ValueError, TypeError):
            innings_decimal = 0

        # Determine if this pitcher is currently on the mound
        is_currently_pitching = (
            (home_away == "home" and inning_half == "top") or
            (home_away == "away" and inning_half == "bottom")
        )

        return {
            "game_id": game_id,
            "player_id": player_info.get("id"),
            "player_name": player_info.get("full_name") or f"{player_info.get('first_name', '')} {player_info.get('last_name', '')}".strip(),
            "team_id": team.get("id"),
            "team_abbr": team.get("abbreviation"),
            "home_away": home_away,
            # Game state
            "current_inning": current_inning,
            "inning_half": inning_half,
            "is_currently_pitching": is_currently_pitching,
            # Live stats
            "current_strikeouts": current_ks,
            "innings_pitched": innings_pitched,
            "innings_pitched_decimal": round(innings_decimal, 2),
            "pitches_thrown": player.get("p_pitches", 0),
            "strikes": player.get("p_strikes", 0),
            "hits_allowed": player.get("p_h", 0),
            "walks": player.get("p_bb", 0),
            "earned_runs": player.get("p_er", 0),
            # Is this the starter?
            "is_starter": player.get("p_gs", 0) == 1,
            # For projection calculations
            "k_per_inning": round(current_ks / innings_decimal, 2) if innings_decimal > 0 else 0,
        }

    def _calculate_on_pace(self, stat: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate on-pace K projection for the pitcher.

        Assumes starter goes ~6 innings, reliever ~2 innings.
        """
        current_ks = stat.get("current_strikeouts", 0)
        ip_decimal = stat.get("innings_pitched_decimal", 0)
        is_starter = stat.get("is_starter", False)

        # Expected innings
        expected_innings = 6.0 if is_starter else 2.0

        if ip_decimal > 0:
            k_per_inning = current_ks / ip_decimal
            projected_ks = k_per_inning * expected_innings
            remaining_innings = max(0, expected_innings - ip_decimal)
            projected_additional_ks = k_per_inning * remaining_innings
        else:
            k_per_inning = 0
            projected_ks = 0
            projected_additional_ks = 0

        return {
            "expected_innings": expected_innings,
            "k_per_inning_rate": round(k_per_inning, 2),
            "projected_final_ks": round(projected_ks, 1),
            "projected_additional_ks": round(projected_additional_ks, 1),
            "innings_remaining": round(max(0, expected_innings - ip_decimal), 1),
            "pct_complete": round((ip_decimal / expected_innings) * 100, 1) if expected_innings > 0 else 0,
        }

    def get_scraper_stats(self) -> dict:
        return {
            "gamesInProgress": self.data.get("gamesInProgress", 0),
            "livePitcherCount": len(self.data.get("livePitcherStats", [])),
        }


create_app = convert_existing_flask_scraper(MlbLiveBoxScoresScraper)

if __name__ == "__main__":
    main = MlbLiveBoxScoresScraper.create_cli_and_flask_main()
    main()

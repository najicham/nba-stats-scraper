"""
File: scrapers/mlb/balldontlie/mlb_player_splits.py

MLB Ball Don't Lie - Player Splits                              v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Player performance splits by various categories.

API Endpoint: https://api.balldontlie.io/mlb/v1/players/splits

Split Categories:
- Venue: Home vs Away
- Time: Day vs Night games
- Month: Monthly performance trends
- Opponent: Performance by opposing team
- Count: Performance by pitch count situations
- Recent: Last 7/15/30 days trending

Very valuable for pitcher strikeout predictions:
- Home/Away K rates
- Day/Night performance
- Recent form (last 7/15/30 days)

Usage:
  python scrapers/mlb/balldontlie/mlb_player_splits.py --player_id 123 --season 2025
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
    from ...utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

logger = logging.getLogger(__name__)


class MlbPlayerSplitsScraper(ScraperBase, ScraperFlaskMixin):
    """Scraper for MLB player performance splits."""

    scraper_name = "mlb_player_splits"
    required_params = ["player_id", "season"]
    optional_params = {
        "api_key": None,
    }

    required_opts: List[str] = ["player_id", "season"]
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    GCS_PATH_KEY = "mlb_player_splits"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_player_splits_%(player_id)s_%(season)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    _API_ROOT = "https://api.balldontlie.io/mlb/v1/players/splits"

    def set_url(self) -> None:
        player_id = self.opts["player_id"]
        season = self.opts["season"]
        self.url = f"{self._API_ROOT}?player_id={player_id}&season={season}"
        logger.debug("MLB Player Splits URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_MLB_API_KEY") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "mlb-player-splits-scraper/1.0",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = api_key

    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("MLB player splits response malformed")

    def transform_data(self) -> None:
        splits_data = self.decoded_data.get("data", {})

        # Extract splits from BDL API response
        # API returns: data.byBreakdown = [{split_name: "Home", ...}, {split_name: "Away", ...}, ...]
        by_breakdown = splits_data.get("byBreakdown", []) if isinstance(splits_data, dict) else []
        by_arena = splits_data.get("byArena", []) if isinstance(splits_data, dict) else []
        by_opponent = splits_data.get("byOpponent", []) if isinstance(splits_data, dict) else []

        # Parse byBreakdown to find Home/Away/Day/Night splits
        home_split = None
        away_split = None
        day_split = None
        night_split = None

        for split in by_breakdown:
            split_name = split.get("split_name", "").lower()
            if split_name == "home":
                home_split = split
            elif split_name == "away":
                away_split = split
            elif split_name == "day":
                day_split = split
            elif split_name == "night":
                night_split = split

        # Calculate K/9 for each split
        def calc_k_per_9(split_data: dict) -> float:
            if not split_data:
                return 0.0
            ip = split_data.get("innings_pitched", 0)
            so = split_data.get("strikeouts_pitched", 0)
            try:
                ip_float = float(ip) if ip else 0
                return (so / ip_float * 9) if ip_float > 0 else 0.0
            except (ValueError, TypeError):
                return 0.0

        home_k_per_9 = calc_k_per_9(home_split)
        away_k_per_9 = calc_k_per_9(away_split)
        day_k_per_9 = calc_k_per_9(day_split)
        night_k_per_9 = calc_k_per_9(night_split)

        # Calculate diffs (positive = better in first condition)
        home_away_k_diff = round(home_k_per_9 - away_k_per_9, 2) if home_k_per_9 and away_k_per_9 else None
        day_night_k_diff = round(day_k_per_9 - night_k_per_9, 2) if day_k_per_9 and night_k_per_9 else None

        # Build processed splits dict
        processed_splits = {
            "player_id": self.opts["player_id"],
            "season": self.opts["season"],
            # Home/Away splits
            "home": home_split or {},
            "away": away_split or {},
            "home_k_per_9": round(home_k_per_9, 2) if home_k_per_9 else None,
            "away_k_per_9": round(away_k_per_9, 2) if away_k_per_9 else None,
            "home_away_k_diff": home_away_k_diff,
            # Day/Night splits
            "day": day_split or {},
            "night": night_split or {},
            "day_k_per_9": round(day_k_per_9, 2) if day_k_per_9 else None,
            "night_k_per_9": round(night_k_per_9, 2) if night_k_per_9 else None,
            "day_night_k_diff": day_night_k_diff,
            # Additional splits
            "by_arena": by_arena,
            "by_opponent": by_opponent,
            # Raw data for debugging
            "raw_by_breakdown": by_breakdown,
        }

        self.data = {
            "player_id": self.opts["player_id"],
            "season": self.opts["season"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "splits": processed_splits,
            # Convenience fields for downstream processing
            "home_k_per_9": processed_splits["home_k_per_9"],
            "away_k_per_9": processed_splits["away_k_per_9"],
            "home_away_k_diff": home_away_k_diff,
            "day_k_per_9": processed_splits["day_k_per_9"],
            "night_k_per_9": processed_splits["night_k_per_9"],
            "day_night_k_diff": day_night_k_diff,
        }

        logger.info(
            "Fetched splits for player %s season %s: home_k_per_9=%.2f, away_k_per_9=%.2f, diff=%.2f",
            self.opts["player_id"],
            self.opts["season"],
            home_k_per_9 or 0,
            away_k_per_9 or 0,
            home_away_k_diff or 0
        )

    def get_scraper_stats(self) -> dict:
        return {
            "player_id": self.opts["player_id"],
            "season": self.opts["season"],
        }


create_app = convert_existing_flask_scraper(MlbPlayerSplitsScraper)

if __name__ == "__main__":
    main = MlbPlayerSplitsScraper.create_cli_and_flask_main()
    main()

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

        # Extract key splits for pitchers
        processed_splits = {
            "player_id": self.opts["player_id"],
            "season": self.opts["season"],
            "raw_splits": splits_data,
        }

        # Try to extract specific useful splits if they exist
        if isinstance(splits_data, dict):
            processed_splits["home"] = splits_data.get("home", {})
            processed_splits["away"] = splits_data.get("away", {})
            processed_splits["day"] = splits_data.get("day", {})
            processed_splits["night"] = splits_data.get("night", {})
            processed_splits["by_month"] = splits_data.get("by_month", {})
            processed_splits["by_opponent"] = splits_data.get("by_opponent", {})
            processed_splits["last_7_days"] = splits_data.get("last_7_days", splits_data.get("last_7", {}))
            processed_splits["last_15_days"] = splits_data.get("last_15_days", splits_data.get("last_15", {}))
            processed_splits["last_30_days"] = splits_data.get("last_30_days", splits_data.get("last_30", {}))

        self.data = {
            "player_id": self.opts["player_id"],
            "season": self.opts["season"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "splits": processed_splits,
        }

        logger.info("Fetched splits for player %s season %s",
                   self.opts["player_id"], self.opts["season"])

    def get_scraper_stats(self) -> dict:
        return {
            "player_id": self.opts["player_id"],
            "season": self.opts["season"],
        }


create_app = convert_existing_flask_scraper(MlbPlayerSplitsScraper)

if __name__ == "__main__":
    main = MlbPlayerSplitsScraper.create_cli_and_flask_main()
    main()

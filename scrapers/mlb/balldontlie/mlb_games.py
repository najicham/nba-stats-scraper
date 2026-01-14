"""
File: scrapers/mlb/balldontlie/mlb_games.py

MLB Ball Don't Lie - Games Schedule & Scores                    v1.0 - 2026-01-06
--------------------------------------------------------------------------------
MLB game schedule and scores from the Ball Don't Lie API.

API Endpoint: https://api.balldontlie.io/mlb/v1/games

Key Fields:
- id: Game ID
- date: Game date
- status: Game status (scheduled, in_progress, final)
- home_team, visitor_team: Team info
- home_team_score, visitor_team_score: Final scores
- venue: Stadium information

Usage examples:
  python scrapers/mlb/balldontlie/mlb_games.py --date 2025-06-15 --debug
  python scrapers/mlb/balldontlie/mlb_games.py --dates 2025-06-15,2025-06-16
  python scrapers/mlb/balldontlie/mlb_games.py --season 2025
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

try:
    from shared.utils.notification_system import notify_error, notify_warning, notify_info
except ImportError:
    def notify_error(*args, **kwargs): pass
    def notify_warning(*args, **kwargs): pass
    def notify_info(*args, **kwargs): pass

logger = logging.getLogger(__name__)


class MlbGamesScraper(ScraperBase, ScraperFlaskMixin):
    """Scraper for MLB game schedule and scores."""

    scraper_name = "mlb_games"
    required_params = []
    optional_params = {
        "date": None,
        "dates": None,
        "seasons": None,
        "team_ids": None,
        "postseason": None,
        "api_key": None,
    }

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    GCS_PATH_KEY = "mlb_games"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_games_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        # Use Pacific Time for MLB - ensures west coast late games are captured
        if not self.opts.get("date") and not self.opts.get("dates") and not self.opts.get("seasons"):
            from scrapers.utils.date_utils import get_yesterday_pacific
            self.opts["date"] = get_yesterday_pacific()

    _API_ROOT = "https://api.balldontlie.io/mlb/v1/games"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        params = ["per_page=100"]

        if self.opts.get("date"):
            params.append(f"dates[]={self.opts['date']}")
        elif self.opts.get("dates"):
            for d in self.opts["dates"].split(","):
                params.append(f"dates[]={d.strip()}")

        if self.opts.get("seasons"):
            for s in str(self.opts["seasons"]).split(","):
                params.append(f"seasons[]={s.strip()}")

        if self.opts.get("team_ids"):
            for tid in str(self.opts["team_ids"]).split(","):
                params.append(f"team_ids[]={tid.strip()}")

        if self.opts.get("postseason"):
            params.append(f"postseason={self.opts['postseason']}")

        self.url = f"{self.base_url}?{'&'.join(params)}"
        logger.debug("MLB Games URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_MLB_API_KEY") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "mlb-games-scraper/1.0",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = api_key

    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("MLB games response malformed: missing 'data' key")

    def transform_data(self) -> None:
        games: List[Dict[str, Any]] = list(self.decoded_data["data"])
        cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")
        pages_fetched = 1

        while cursor:
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params={"cursor": cursor, "per_page": 100},
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            page_json = resp.json()
            games.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")
            pages_fetched += 1

        games.sort(key=lambda g: (g.get("date", ""), g.get("id", 0)))

        self.data = {
            "date": self.opts.get("date", "multiple"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gameCount": len(games),
            "games": games,
        }

        logger.info("Fetched %d games for %s across %d pages",
                   len(games), self.opts.get("date", "query"), pages_fetched)

    def get_scraper_stats(self) -> dict:
        return {"gameCount": self.data.get("gameCount", 0), "date": self.opts.get("date", "multiple")}


create_app = convert_existing_flask_scraper(MlbGamesScraper)

if __name__ == "__main__":
    main = MlbGamesScraper.create_cli_and_flask_main()
    main()

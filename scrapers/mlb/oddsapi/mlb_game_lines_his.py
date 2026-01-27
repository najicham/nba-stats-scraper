#!/usr/bin/env python3
"""
MLB Odds API Historical Game Lines Scraper

Fetches historical game odds (moneyline, spreads, totals) from The Odds API.

Endpoint: GET /v4/historical/sports/baseball_mlb/odds

Usage:
  # Get historical game lines for a specific date at snapshot:
  SPORT=mlb python scrapers/mlb/oddsapi/mlb_game_lines_his.py \
      --game_date 2025-06-15 --snapshot_timestamp 2025-06-15T18:00:00Z --group dev

  # Flask service:
  SPORT=mlb python scrapers/mlb/oddsapi/mlb_game_lines_his.py --serve --debug

Created: 2026-01-06
"""

from __future__ import annotations

import os
import logging
import sys
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlencode
from typing import Any, Dict, List

try:
    from ...scraper_base import ScraperBase, ExportMode
    from ...scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from ...utils.exceptions import DownloadDataException
    from ...utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from scrapers.scraper_base import ScraperBase, ExportMode
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

from shared.utils.notification_system import notify_error, notify_warning, notify_info
from shared.utils.auth_utils import get_api_key

logger = logging.getLogger(__name__)


def snap_iso_ts_to_five_minutes(iso: str) -> str:
    """Snap timestamp to previous 5-minute boundary."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    floored = dt - timedelta(minutes=dt.minute % 5, seconds=dt.second, microseconds=dt.microsecond)
    return floored.replace(tzinfo=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class MlbGameLinesHistoricalScraper(ScraperBase, ScraperFlaskMixin):
    """
    MLB Historical Game Lines Scraper for The Odds API.

    Fetches historical moneyline, spread, and totals at a specific snapshot.

    Required opts:
      - game_date: Date for GCS directory (YYYY-MM-DD)
      - snapshot_timestamp: UTC timestamp for snapshot (YYYY-MM-DDTHH:MM:SSZ)

    Optional opts:
      - markets: Comma-sep markets (default: h2h,spreads,totals)
      - bookmakers: Comma-sep bookmakers (default: draftkings,fanduel)
      - regions: Comma-sep regions (default: us)
    """

    scraper_name = "mlb_game_lines_his"
    required_params = ["game_date", "snapshot_timestamp"]
    optional_params = {
        "api_key": None,
        "markets": None,
        "bookmakers": None,
        "regions": None,
        "oddsFormat": None,
        "commenceTimeFrom": None,
        "commenceTimeTo": None,
    }

    required_opts: List[str] = ["game_date", "snapshot_timestamp"]
    proxy_enabled = False
    browser_enabled = False

    GCS_PATH_KEY = "mlb_odds_api_game_lines_history"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
            "check_should_save": True,
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_game_lines_his_%(game_date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "capture", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        """Set defaults and snap timestamp."""
        super().set_additional_opts()

        # Snap timestamp
        if self.opts.get("snapshot_timestamp"):
            original = self.opts["snapshot_timestamp"]
            self.opts["snapshot_timestamp"] = snap_iso_ts_to_five_minutes(original)

        # Defaults
        if not self.opts.get("markets"):
            self.opts["markets"] = "h2h,spreads,totals"
        if not self.opts.get("bookmakers"):
            self.opts["bookmakers"] = "draftkings,fanduel"
        if not self.opts.get("regions"):
            self.opts["regions"] = "us"

        # Convert game_date to commence time filters
        import pytz
        eastern = pytz.timezone('America/New_York')
        game_date_str = self.opts["game_date"]
        game_date = datetime.strptime(game_date_str, "%Y-%m-%d").date()

        day_start = eastern.localize(datetime.combine(game_date, time.min))
        day_end = eastern.localize(datetime.combine(game_date, time.max))

        if not self.opts.get("commenceTimeFrom"):
            self.opts["commenceTimeFrom"] = day_start.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not self.opts.get("commenceTimeTo"):
            self.opts["commenceTimeTo"] = day_end.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    _API_ROOT = "https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/odds"

    def set_url(self) -> None:
        api_key = get_api_key(
            secret_name='ODDS_API_KEY',
            default_env_var='ODDS_API_KEY'
        )
        if not api_key:
            raise DownloadDataException("Missing ODDS_API_KEY")

        query: Dict[str, Any] = {
            "apiKey": api_key,
            "date": self.opts["snapshot_timestamp"],
            "markets": self.opts["markets"],
            "regions": self.opts["regions"],
            "bookmakers": self.opts["bookmakers"],
            "oddsFormat": self.opts.get("oddsFormat", "american"),
            "commenceTimeFrom": self.opts.get("commenceTimeFrom"),
            "commenceTimeTo": self.opts.get("commenceTimeTo"),
        }
        query = {k: v for k, v in query.items() if v is not None}
        self.url = f"{self._API_ROOT}?{urlencode(query, doseq=True)}"
        logger.info("MLB Historical Game Lines URL: %s", self.url.replace(api_key, "***"))

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}

    def check_download_status(self) -> None:
        if self.raw_response.status_code in (200, 204):
            return
        super().check_download_status()

    def validate_download_data(self) -> None:
        if self.raw_response.status_code == 204:
            self.decoded_data = {"data": [], "timestamp": self.opts.get("snapshot_timestamp")}
            return

        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            raise DownloadDataException(f"API error: {self.decoded_data['message']}")

        if not (isinstance(self.decoded_data, dict) and "data" in self.decoded_data):
            raise DownloadDataException("Expected dict with 'data' key.")

    def transform_data(self) -> None:
        wrapper = self.decoded_data
        games = wrapper.get("data", [])

        # Count outcomes
        total_outcomes = 0
        for game in games:
            for bm in game.get("bookmakers", []):
                for mkt in bm.get("markets", []):
                    total_outcomes += len(mkt.get("outcomes", []))

        self.data = {
            "sport": "baseball_mlb",
            "game_date": self.opts["game_date"],
            "snapshot_timestamp": wrapper.get("timestamp"),
            "previous_snapshot": wrapper.get("previous_timestamp"),
            "next_snapshot": wrapper.get("next_timestamp"),
            "markets": self.opts.get("markets"),
            "bookmakers": self.opts.get("bookmakers"),
            "gameCount": len(games),
            "outcomeCount": total_outcomes,
            "games": games,
        }

        if len(games) == 0:
            notify_warning(
                title="No MLB Historical Game Lines",
                message=f"No game lines found at snapshot for {self.opts.get('game_date')}",
                details={
                    'scraper': 'mlb_game_lines_his',
                    'game_date': self.opts.get('game_date'),
                    'snapshot_timestamp': self.opts.get('snapshot_timestamp'),
                },
                processor_name=self.__class__.__name__
            )
        else:
            notify_info(
                title="MLB Historical Game Lines Retrieved",
                message=f"Found lines for {len(games)} games ({total_outcomes} outcomes)",
                details={
                    'scraper': 'mlb_game_lines_his',
                    'game_date': self.opts.get('game_date'),
                    'snapshot_timestamp': wrapper.get('timestamp'),
                    'games': len(games),
                    'outcomes': total_outcomes,
                },
                processor_name=self.__class__.__name__
            )

        logger.info("Fetched historical lines for %d games @ %s", len(games), self.data["snapshot_timestamp"])

    def should_save_data(self) -> bool:
        if self.raw_response and self.raw_response.status_code == 204:
            return False
        return bool(self.data.get("gameCount", 0) > 0)

    def get_scraper_stats(self) -> dict:
        return {
            "gameCount": self.data.get("gameCount", 0) if hasattr(self, 'data') else 0,
            "outcomeCount": self.data.get("outcomeCount", 0) if hasattr(self, 'data') else 0,
            "sport": "baseball_mlb",
            "game_date": self.opts.get("game_date"),
            "snapshot": self.data.get("snapshot_timestamp") if hasattr(self, 'data') else None,
        }


create_app = convert_existing_flask_scraper(MlbGameLinesHistoricalScraper)

if __name__ == "__main__":
    main = MlbGameLinesHistoricalScraper.create_cli_and_flask_main()
    main()

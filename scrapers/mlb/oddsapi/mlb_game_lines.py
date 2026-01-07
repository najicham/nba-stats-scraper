#!/usr/bin/env python3
"""
MLB Odds API Game Lines Scraper

Fetches game odds (moneyline, spread, totals) from The Odds API.

Markets collected:
- h2h: Moneyline (who wins)
- spreads: Run line (typically -1.5/+1.5)
- totals: Over/under total runs

Endpoint: GET /v4/sports/baseball_mlb/odds

Usage:
  # Get game lines for a specific date:
  SPORT=mlb python scrapers/mlb/oddsapi/mlb_game_lines.py --game_date 2025-06-15 --group dev

  # Flask service:
  SPORT=mlb python scrapers/mlb/oddsapi/mlb_game_lines.py --serve --debug

Created: 2026-01-06
"""

from __future__ import annotations

import os
import logging
import sys
from datetime import datetime, time
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


class MlbGameLinesScraper(ScraperBase, ScraperFlaskMixin):
    """
    MLB Game Lines Scraper for The Odds API.

    Fetches moneyline, spread (run line), and totals for MLB games.
    These provide context for strikeout predictions:
    - Low totals = pitcher's duel = more K's expected
    - Large spreads = quality mismatch = starter goes deeper

    Required opts:
      - game_date: Date to fetch odds for (YYYY-MM-DD)

    Optional opts:
      - markets: Comma-sep markets (default: h2h,spreads,totals)
      - bookmakers: Comma-sep bookmakers (default: draftkings,fanduel)
      - regions: Comma-sep regions (default: us)
    """

    scraper_name = "mlb_game_lines"
    required_params = ["game_date"]
    optional_params = {
        "api_key": None,
        "markets": None,
        "bookmakers": None,
        "regions": None,
        "oddsFormat": None,
        "commenceTimeFrom": None,
        "commenceTimeTo": None,
    }

    required_opts: List[str] = ["game_date"]
    proxy_enabled = False
    browser_enabled = False

    GCS_PATH_KEY = "mlb_odds_api_game_lines"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_game_lines_%(game_date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "capture", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        """Set defaults and convert game_date to time filters."""
        super().set_additional_opts()

        # Defaults for MLB game lines
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

    _API_ROOT = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"

    def set_url(self) -> None:
        api_key = get_api_key(
            secret_name='ODDS_API_KEY',
            default_env_var='ODDS_API_KEY'
        )
        if not api_key:
            raise DownloadDataException("Missing ODDS_API_KEY")

        query: Dict[str, Any] = {
            "apiKey": api_key,
            "markets": self.opts["markets"],
            "regions": self.opts["regions"],
            "bookmakers": self.opts["bookmakers"],
            "oddsFormat": self.opts.get("oddsFormat", "american"),
            "commenceTimeFrom": self.opts.get("commenceTimeFrom"),
            "commenceTimeTo": self.opts.get("commenceTimeTo"),
        }
        query = {k: v for k, v in query.items() if v is not None}
        self.url = f"{self._API_ROOT}?{urlencode(query, doseq=True)}"
        logger.info("MLB Game Lines URL: %s", self.url.replace(api_key, "***"))

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}

    def validate_download_data(self) -> None:
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            raise DownloadDataException(f"API error: {self.decoded_data['message']}")

        if not isinstance(self.decoded_data, list):
            raise DownloadDataException("Expected a list of games with odds.")

    def transform_data(self) -> None:
        games: List[Dict[str, Any]] = self.decoded_data

        # Count total odds outcomes
        total_outcomes = 0
        for game in games:
            for bookmaker in game.get("bookmakers", []):
                for market in bookmaker.get("markets", []):
                    total_outcomes += len(market.get("outcomes", []))

        self.data = {
            "sport": "baseball_mlb",
            "game_date": self.opts.get("game_date"),
            "markets": self.opts.get("markets"),
            "bookmakers": self.opts.get("bookmakers"),
            "gameCount": len(games),
            "outcomeCount": total_outcomes,
            "games": games,
        }

        if len(games) == 0:
            notify_warning(
                title="No MLB Game Lines Available",
                message=f"No game lines found for {self.opts.get('game_date')}",
                details={'scraper': 'mlb_game_lines', 'game_date': self.opts.get('game_date')}
            )
        else:
            # Extract sample totals for logging
            sample_totals = []
            for game in games[:3]:
                for bm in game.get("bookmakers", []):
                    for mkt in bm.get("markets", []):
                        if mkt.get("key") == "totals":
                            for outcome in mkt.get("outcomes", []):
                                if outcome.get("name") == "Over":
                                    sample_totals.append(f"{game.get('away_team', 'AWAY')}@{game.get('home_team', 'HOME')}: {outcome.get('point')}")
                                    break
                    break

            notify_info(
                title="MLB Game Lines Retrieved",
                message=f"Found lines for {len(games)} games ({total_outcomes} outcomes)",
                details={
                    'scraper': 'mlb_game_lines',
                    'game_date': self.opts.get('game_date'),
                    'games': len(games),
                    'outcomes': total_outcomes,
                    'sample_totals': sample_totals[:3]
                }
            )

        logger.info("Fetched game lines for %d MLB games", len(games))

    def should_save_data(self) -> bool:
        return bool(self.data.get("gameCount"))

    def get_scraper_stats(self) -> dict:
        return {
            "gameCount": self.data.get("gameCount", 0) if hasattr(self, 'data') else 0,
            "outcomeCount": self.data.get("outcomeCount", 0) if hasattr(self, 'data') else 0,
            "sport": "baseball_mlb",
            "game_date": self.opts.get("game_date"),
            "markets": self.opts.get("markets"),
        }


create_app = convert_existing_flask_scraper(MlbGameLinesScraper)

if __name__ == "__main__":
    main = MlbGameLinesScraper.create_cli_and_flask_main()
    main()

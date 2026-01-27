#!/usr/bin/env python3
"""
MLB Odds API Pitcher Props Scraper

Fetches pitcher prop odds from The Odds API.

Markets collected:
- pitcher_strikeouts: Strikeouts over/under (PRIMARY TARGET)
- pitcher_outs: Outs recorded over/under
- pitcher_hits_allowed: Hits allowed over/under
- pitcher_walks: Walks over/under
- pitcher_earned_runs: Earned runs over/under

Endpoint: GET /v4/sports/baseball_mlb/events/{eventId}/odds

Usage:
  # Get pitcher props for a specific event:
  SPORT=mlb python scrapers/mlb/oddsapi/mlb_pitcher_props.py \
      --event_id abc123 --game_date 2025-06-15 --group dev

  # Flask service:
  SPORT=mlb python scrapers/mlb/oddsapi/mlb_pitcher_props.py --serve --debug

Created: 2026-01-06
"""

from __future__ import annotations

import os
import logging
import sys
from datetime import datetime, timezone
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

# Default pitcher prop markets to collect
DEFAULT_PITCHER_MARKETS = ",".join([
    "pitcher_strikeouts",
    "pitcher_outs",
    "pitcher_hits_allowed",
    "pitcher_walks",
    "pitcher_earned_runs",
])


class MlbPitcherPropsScraper(ScraperBase, ScraperFlaskMixin):
    """
    MLB Pitcher Props Scraper for The Odds API.

    Fetches pitcher prop betting lines, primarily strikeouts over/under.
    This is the PRIMARY target for our prediction model.

    Required opts:
      - event_id: Odds API event ID for the game
      - game_date: Game date (YYYY-MM-DD)

    Optional opts:
      - markets: Comma-sep markets (default: pitcher_strikeouts,pitcher_outs,...)
      - bookmakers: Comma-sep bookmakers (default: draftkings,fanduel)
      - regions: Comma-sep regions (default: us)
    """

    scraper_name = "mlb_pitcher_props"
    required_params = ["event_id", "game_date"]
    optional_params = {
        "api_key": None,
        "markets": None,
        "bookmakers": None,
        "regions": None,
        "oddsFormat": None,
        "teams": None,  # Team suffix for GCS path
    }

    required_opts: List[str] = ["event_id", "game_date"]
    proxy_enabled = False
    browser_enabled = False

    GCS_PATH_KEY = "mlb_odds_api_pitcher_props"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_pitcher_props_%(event_id)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "capture", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        """Set defaults for pitcher props."""
        super().set_additional_opts()

        if not self.opts.get("markets"):
            self.opts["markets"] = DEFAULT_PITCHER_MARKETS
        if not self.opts.get("bookmakers"):
            self.opts["bookmakers"] = "draftkings,fanduel"
        if not self.opts.get("regions"):
            self.opts["regions"] = "us"

    _API_ROOT_TMPL = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{eventId}/odds"

    def set_url(self) -> None:
        api_key = get_api_key(
            secret_name='ODDS_API_KEY',
            default_env_var='ODDS_API_KEY'
        )
        if not api_key:
            raise DownloadDataException("Missing ODDS_API_KEY")

        base = self._API_ROOT_TMPL.format(eventId=self.opts["event_id"])

        query: Dict[str, Any] = {
            "apiKey": api_key,
            "markets": self.opts["markets"],
            "regions": self.opts["regions"],
            "bookmakers": self.opts["bookmakers"],
            "oddsFormat": self.opts.get("oddsFormat", "american"),
        }
        query = {k: v for k, v in query.items() if v is not None}
        self.url = f"{base}?{urlencode(query, doseq=True)}"
        logger.info("MLB Pitcher Props URL: %s", self.url.replace(api_key, "***"))

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}

    def check_download_status(self) -> None:
        """Handle 200 and 204 (no markets yet) as success."""
        if self.raw_response.status_code in (200, 204):
            return
        super().check_download_status()

    def validate_download_data(self) -> None:
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            raise DownloadDataException(f"API error: {self.decoded_data['message']}")

        if not isinstance(self.decoded_data, (dict, list)):
            raise DownloadDataException("Expected dict or list for odds payload.")

    def transform_data(self) -> None:
        if not self.decoded_data:
            event_data = {}
            bookmakers = []
        elif isinstance(self.decoded_data, list):
            event_data = self.decoded_data[0] if self.decoded_data else {}
            bookmakers = event_data.get("bookmakers", [])
        else:
            event_data = self.decoded_data
            bookmakers = self.decoded_data.get("bookmakers", [])

        # Count outcomes and extract pitcher strikeout lines
        row_count = 0
        strikeout_lines = []

        for bm in bookmakers:
            for mkt in bm.get("markets", []):
                outcomes = mkt.get("outcomes", [])
                row_count += len(outcomes) or 1

                # Extract pitcher strikeout lines for summary
                if mkt.get("key") == "pitcher_strikeouts":
                    for outcome in outcomes:
                        if outcome.get("name") == "Over":
                            strikeout_lines.append({
                                "player": outcome.get("description", "Unknown"),
                                "line": outcome.get("point"),
                                "over_price": outcome.get("price"),
                                "bookmaker": bm.get("key"),
                            })

        # Extract team info for GCS path
        teams_suffix = ""
        home_team = event_data.get("home_team", "")
        away_team = event_data.get("away_team", "")
        if home_team and away_team:
            # Create abbreviated suffix (first 3 chars)
            home_abbr = home_team.replace(" ", "")[:3].upper()
            away_abbr = away_team.replace(" ", "")[:3].upper()
            teams_suffix = f"{away_abbr}{home_abbr}"
            self.opts["teams"] = teams_suffix

        # Add snap time for filename
        snap_hour = datetime.now(timezone.utc).strftime("%H%M")
        self.opts["snap"] = snap_hour

        self.data = {
            "sport": "baseball_mlb",
            "eventId": self.opts["event_id"],
            "game_date": self.opts.get("game_date"),
            "markets": self.opts.get("markets"),
            "regions": self.opts.get("regions"),
            "rowCount": row_count,
            "strikeoutLineCount": len(strikeout_lines),
            "strikeoutLines": strikeout_lines,
            "odds": self.decoded_data,
        }

        if row_count == 0:
            notify_warning(
                title="No MLB Pitcher Props Available",
                message=f"No pitcher props found for event {self.opts.get('event_id')}",
                details={
                    'scraper': 'mlb_pitcher_props',
                    'event_id': self.opts.get('event_id'),
                    'game_date': self.opts.get('game_date'),
                },
                processor_name=self.__class__.__name__
            )
        else:
            notify_info(
                title="MLB Pitcher Props Retrieved",
                message=f"Found {len(strikeout_lines)} pitcher strikeout lines",
                details={
                    'scraper': 'mlb_pitcher_props',
                    'event_id': self.opts.get('event_id'),
                    'game_date': self.opts.get('game_date'),
                    'total_outcomes': row_count,
                    'strikeout_lines': len(strikeout_lines),
                    'sample_lines': strikeout_lines[:4],
                },
                processor_name=self.__class__.__name__
            )

        logger.info(
            "Fetched %d pitcher prop outcomes (%d strikeout lines) for event %s",
            row_count, len(strikeout_lines), self.opts["event_id"]
        )

    def should_save_data(self) -> bool:
        return bool(self.data.get("rowCount"))

    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0) if hasattr(self, 'data') else 0,
            "strikeoutLineCount": self.data.get("strikeoutLineCount", 0) if hasattr(self, 'data') else 0,
            "sport": "baseball_mlb",
            "eventId": self.opts.get("event_id"),
            "game_date": self.opts.get("game_date"),
            "markets": self.opts.get("markets"),
            "teams": self.opts.get("teams", ""),
            "snap": self.opts.get("snap", ""),
        }


create_app = convert_existing_flask_scraper(MlbPitcherPropsScraper)

if __name__ == "__main__":
    main = MlbPitcherPropsScraper.create_cli_and_flask_main()
    main()

#!/usr/bin/env python3
"""
MLB Odds API Historical Pitcher Props Scraper

Fetches historical pitcher prop odds from The Odds API at a specific snapshot.
Critical for training the strikeout prediction model on historical data.

Endpoint: GET /v4/historical/sports/baseball_mlb/events/{eventId}/odds

Usage:
  # Get historical pitcher props for a specific event:
  SPORT=mlb python scrapers/mlb/oddsapi/mlb_pitcher_props_his.py \
      --event_id abc123 --game_date 2025-06-15 \
      --snapshot_timestamp 2025-06-15T18:00:00Z --group dev

  # Flask service:
  SPORT=mlb python scrapers/mlb/oddsapi/mlb_pitcher_props_his.py --serve --debug

Created: 2026-01-06
"""

from __future__ import annotations

import os
import logging
import sys
from datetime import datetime, timedelta, timezone
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

DEFAULT_PITCHER_MARKETS = ",".join([
    "pitcher_strikeouts",
    "pitcher_outs",
    "pitcher_hits_allowed",
    "pitcher_walks",
    "pitcher_earned_runs",
])


def snap_iso_ts_to_five_minutes(iso: str) -> str:
    """Snap timestamp to previous 5-minute boundary."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    floored = dt - timedelta(minutes=dt.minute % 5, seconds=dt.second, microseconds=dt.microsecond)
    return floored.replace(tzinfo=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class MlbPitcherPropsHistoricalScraper(ScraperBase, ScraperFlaskMixin):
    """
    MLB Historical Pitcher Props Scraper for The Odds API.

    Fetches pitcher prop betting lines at a specific historical snapshot.

    Required opts:
      - event_id: Odds API event ID for the game
      - game_date: Date for GCS directory (YYYY-MM-DD)
      - snapshot_timestamp: UTC timestamp for snapshot (YYYY-MM-DDTHH:MM:SSZ)

    Optional opts:
      - markets: Comma-sep markets (default: pitcher_strikeouts,...)
      - bookmakers: Comma-sep bookmakers (default: draftkings,fanduel)
      - regions: Comma-sep regions (default: us)
    """

    scraper_name = "mlb_pitcher_props_his"
    required_params = ["event_id", "game_date", "snapshot_timestamp"]
    optional_params = {
        "api_key": None,
        "markets": None,
        "bookmakers": None,
        "regions": None,
        "oddsFormat": None,
        "teams": None,
    }

    required_opts: List[str] = ["event_id", "game_date", "snapshot_timestamp"]
    proxy_enabled = False
    browser_enabled = False

    GCS_PATH_KEY = "mlb_odds_api_pitcher_props_history"
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
            "filename": "/tmp/mlb_pitcher_props_his_%(event_id)s.json",
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
            self.opts["markets"] = DEFAULT_PITCHER_MARKETS
        if not self.opts.get("bookmakers"):
            self.opts["bookmakers"] = "draftkings,fanduel"
        if not self.opts.get("regions"):
            self.opts["regions"] = "us"

    _API_ROOT_TMPL = "https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/events/{eventId}/odds"

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
            "date": self.opts["snapshot_timestamp"],
            "markets": self.opts["markets"],
            "regions": self.opts["regions"],
            "bookmakers": self.opts["bookmakers"],
            "oddsFormat": self.opts.get("oddsFormat", "american"),
        }
        query = {k: v for k, v in query.items() if v is not None}
        self.url = f"{base}?{urlencode(query, doseq=True)}"
        logger.info("MLB Historical Pitcher Props URL: %s", self.url.replace(api_key, "***"))

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}

    def check_download_status(self) -> None:
        if self.raw_response.status_code in (200, 204):
            return
        super().check_download_status()

    def validate_download_data(self) -> None:
        if self.raw_response.status_code == 204:
            self.decoded_data = {"data": {}, "timestamp": self.opts.get("snapshot_timestamp")}
            return

        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            raise DownloadDataException(f"API error: {self.decoded_data['message']}")

        if not isinstance(self.decoded_data, dict):
            raise DownloadDataException("Expected dict response.")

    def transform_data(self) -> None:
        wrapper = self.decoded_data

        # Handle wrapped vs unwrapped response
        if "data" in wrapper:
            event_data = wrapper.get("data", {})
            snapshot_timestamp = wrapper.get("timestamp")
        else:
            event_data = wrapper
            snapshot_timestamp = self.opts.get("snapshot_timestamp")

        bookmakers = event_data.get("bookmakers", []) if isinstance(event_data, dict) else []

        # Count outcomes and extract strikeout lines
        row_count = 0
        strikeout_lines = []

        for bm in bookmakers:
            for mkt in bm.get("markets", []):
                outcomes = mkt.get("outcomes", [])
                row_count += len(outcomes) or 1

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
        if isinstance(event_data, dict):
            home_team = event_data.get("home_team", "")
            away_team = event_data.get("away_team", "")
            if home_team and away_team:
                home_abbr = home_team.replace(" ", "")[:3].upper()
                away_abbr = away_team.replace(" ", "")[:3].upper()
                teams_suffix = f"{away_abbr}{home_abbr}"
                self.opts["teams"] = teams_suffix

        # Add snap time
        snap_hour = datetime.now(timezone.utc).strftime("%H%M")
        self.opts["snap"] = snap_hour

        self.data = {
            "sport": "baseball_mlb",
            "eventId": self.opts["event_id"],
            "game_date": self.opts.get("game_date"),
            "snapshot_timestamp": snapshot_timestamp,
            "previous_snapshot": wrapper.get("previous_timestamp") if "data" in wrapper else None,
            "next_snapshot": wrapper.get("next_timestamp") if "data" in wrapper else None,
            "markets": self.opts.get("markets"),
            "regions": self.opts.get("regions"),
            "rowCount": row_count,
            "strikeoutLineCount": len(strikeout_lines),
            "strikeoutLines": strikeout_lines,
            "odds": event_data,
        }

        if row_count == 0:
            notify_warning(
                title="No MLB Historical Pitcher Props",
                message=f"No pitcher props at snapshot for event {self.opts.get('event_id')}",
                details={
                    'scraper': 'mlb_pitcher_props_his',
                    'event_id': self.opts.get('event_id'),
                    'game_date': self.opts.get('game_date'),
                    'snapshot_timestamp': snapshot_timestamp,
                },
                processor_name=self.__class__.__name__
            )
        else:
            notify_info(
                title="MLB Historical Pitcher Props Retrieved",
                message=f"Found {len(strikeout_lines)} strikeout lines at snapshot",
                details={
                    'scraper': 'mlb_pitcher_props_his',
                    'event_id': self.opts.get('event_id'),
                    'game_date': self.opts.get('game_date'),
                    'snapshot_timestamp': snapshot_timestamp,
                    'total_outcomes': row_count,
                    'strikeout_lines': len(strikeout_lines),
                },
                processor_name=self.__class__.__name__
            )

        logger.info("Fetched %d historical pitcher prop outcomes (%d strikeout lines)",
                   row_count, len(strikeout_lines))

    def should_save_data(self) -> bool:
        if self.raw_response and self.raw_response.status_code == 204:
            return False
        return bool(self.data.get("rowCount"))

    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0) if hasattr(self, 'data') else 0,
            "strikeoutLineCount": self.data.get("strikeoutLineCount", 0) if hasattr(self, 'data') else 0,
            "sport": "baseball_mlb",
            "eventId": self.opts.get("event_id"),
            "game_date": self.opts.get("game_date"),
            "snapshot": self.data.get("snapshot_timestamp") if hasattr(self, 'data') else None,
        }


create_app = convert_existing_flask_scraper(MlbPitcherPropsHistoricalScraper)

if __name__ == "__main__":
    main = MlbPitcherPropsHistoricalScraper.create_cli_and_flask_main()
    main()

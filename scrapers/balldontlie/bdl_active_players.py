"""
BALLDONTLIE - Active Players endpoint                         v1.1 - 2025-06-24
-------------------------------------------------------------------------------
Lists players flagged "active" this season.

    https://api.balldontlie.io/v1/players/active

Optional query params mirror /players:
  --teamId      restrict to one franchise
  --playerId    one specific player
  --search      free-text on first/last name

If none supplied: returns the full league (~500 rows).

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_active_players \
      --teamId 3 \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_active_players.py --teamId 3 --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_active_players.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_active_players
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_active_players.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class BdlActivePlayersScraper(ScraperBase, ScraperFlaskMixin):
    """Daily (or ad-hoc) scrape of /players/active."""

    # Flask Mixin Configuration
    scraper_name = "bdl_active_players"
    required_params = []  # No required parameters
    optional_params = {
        "teamId": None,
        "playerId": None,
        "search": None,
        "apiKey": None,  # Falls back to env var
    }

    # Original scraper config
    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": "balldontlie/active-players/%(ident)s_%(run_id)s.raw.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        # Normal dev / prod artifact (keyed by ident)
        {
            "type": "file",
            "filename": "/tmp/bdl_active_players_%(ident)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
        # Capture RAW + EXP (keyed by run_id)
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DECODED,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts – build concise identifier                         #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        if self.opts.get("playerId"):
            self.opts["ident"] = f"player_{self.opts['playerId']}"
        elif self.opts.get("teamId"):
            self.opts["ident"] = f"team_{self.opts['teamId']}"
        elif self.opts.get("search"):
            self.opts["ident"] = f"search_{self.opts['search']}"
        else:
            self.opts["ident"] = "league"

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/players/active"

    def set_url(self) -> None:
        params: Dict[str, str | int] = {"per_page": 100}
        if self.opts.get("teamId"):
            params["team_ids[]"] = self.opts["teamId"]
        if self.opts.get("playerId"):
            params["player_ids[]"] = self.opts["playerId"]
        if self.opts.get("search"):
            params["search"] = self.opts["search"]

        query = "&".join(f"{k}={v}" for k, v in params.items())
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}?{query}"
        logger.debug("Active‑players URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-active/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Unexpected active‑players JSON structure")

    # ------------------------------------------------------------------ #
    # Transform (cursor walk)                                            #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        players: List[Dict[str, Any]] = list(self.decoded_data["data"])
        cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")

        while cursor:
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params={"cursor": cursor, "per_page": 100},
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            page_json: Dict[str, Any] = resp.json()
            players.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")

        players.sort(key=lambda p: p["id"])

        self.data = {
            "ident": self.opts["ident"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "playerCount": len(players),
            "activePlayers": players,
        }
        logger.info("Fetched %d active players (%s)", len(players), self.opts["ident"])

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "playerCount": self.data.get("playerCount", 0),
            "ident": self.opts["ident"],
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlActivePlayersScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlActivePlayersScraper.create_cli_and_flask_main()
    main()
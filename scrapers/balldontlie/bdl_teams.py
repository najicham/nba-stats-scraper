"""
BallDontLie - Teams endpoint                                    v1.1 - 2025-06-23
-------------------------------------------------------------------------------
Grabs the full list of NBA franchises from

    https://api.balldontlie.io/v1/teams            (no auth required for free tier)

If pagination ever appears (meta.next_page > current_page) we'll loop until done.

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_teams \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_teams.py --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_teams.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_teams
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_teams.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper

logger = logging.getLogger(__name__)  # module-specific logger


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class BdlTeams(ScraperBase, ScraperFlaskMixin):
    """Static reference table - typically run once per season."""

    # Flask Mixin Configuration
    scraper_name = "bdl_teams"
    required_params = []  # No required parameters
    optional_params = {
        "apiKey": None,  # Falls back to env var (optional for free tier)
    }

    # Original scraper config
    download_type = DownloadType.JSON
    decode_download_data = True
    required_opts: List[str] = []  # no CLI options required

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": "balldontlie/teams/teams_%(run_id)s.raw.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        # Normal dev / prod artifact
        {
            "type": "file",
            "filename": "/tmp/bdl_teams.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
        # Capture RAW
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        # Capture decoded EXP
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DECODED,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL & headers
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/teams"

    def set_url(self) -> None:
        self.url = self._API_ROOT  # no query params today
        logger.debug("Teams URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        hdrs = {
            "User-Agent": "scrape-bdl-teams/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:  # paid tier or future lockdown
            hdrs["Authorization"] = f"Bearer {api_key}"
        self.headers = hdrs

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Unexpected teams JSON structure")

    # ------------------------------------------------------------------ #
    # Transform (handles future pagination)
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        teams: List[Dict[str, Any]] = []
        page_json: Dict[str, Any] = self.decoded_data

        while True:
            teams.extend(page_json.get("data", []))

            # BDL v1 paginates with meta.next_page (int) or next_page_url (str)
            meta = page_json.get("meta", {})
            next_page = meta.get("next_page") or meta.get("next_page_url")
            if not next_page:
                break

            logger.debug("Following pagination to %s", next_page)
            page_json = self.http_downloader.get(
                next_page if isinstance(next_page, str) else self._API_ROOT,
                headers=self.headers,
                params={"page": next_page} if isinstance(next_page, int) else None,
                timeout=self.timeout_http,
            ).json()

        teams.sort(key=lambda t: t["id"])  # deterministic order

        self.data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "teamCount": len(teams),
            "teams": teams,
        }
        logger.info("Fetched %d NBA franchises", len(teams))

    # ------------------------------------------------------------------ #
    # Stats for SCRAPER_STATS
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"teamCount": self.data.get("teamCount", 0)}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlTeams)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlTeams.create_cli_and_flask_main()
    main()
    
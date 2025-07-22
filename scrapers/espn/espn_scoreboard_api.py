"""
ESPN NBA Scoreboard scraper                           v2 - 2025-06-16
--------------------------------------------------------------------
Pulls the daily scoreboard JSON from ESPN's public API and converts it
into a lightweight game list, suitable for job fan-out:

    [
        {
            "gameId": "401585725",
            "statusId": 2,
            "state": "in",          # pre / in / post
            "status": "2nd Quarter",
            "startTime": "2025-01-14T03:00Z",
            "teams": [
                {"teamId": "2",  "abbreviation": "BOS", "score": "47", ...},
                {"teamId": "17", "abbreviation": "LAL", "score": "45", ...}
            ]
        },
        ...
    ]

Improvements v2
---------------
- header_profile = "espn"  -> one-line UA updates if ESPN blocks a string
- Strict ISO-8601 timestamp
- Adds state & statusId
- Uses new _common_requests_kwargs() helper in ScraperBase

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py espn_scoreboard_api \
      --scoreDate 20250214 \
      --debug

  # Direct CLI execution:
  python scrapers/espn/espn_scoreboard_api.py --scoreDate 20250214 --debug

  # Flask web service:
  python scrapers/espn/espn_scoreboard_api.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.espn.espn_scoreboard_api
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/espn/espn_scoreboard_api.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

logger = logging.getLogger("scraper_base")


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class GetEspnScoreboard(ScraperBase, ScraperFlaskMixin):
    """
    ESPN scoreboard scraper (JSON API).
    """

    # Flask Mixin Configuration
    scraper_name = "espn_scoreboard_api"
    required_params = ["scoreDate"]  # scoreDate is required (YYYYMMDD format)
    optional_params = {}

    # Original scraper config
    required_opts: List[str] = ["scoreDate"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = "espn"

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "espn_scoreboard"
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/espn_scoreboard_%(scoreDate)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        # ---------- raw JSON fixture (offline tests) ----------
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",  # FIXED: Use run_id instead of scoreDate
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        # ---------- golden snapshot (parsed DATA) ----------
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",  # FIXED: Use run_id instead of scoreDate
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL & HEADERS
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        base = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
        self.url = f"{base}?dates={self.opts['scoreDate']}"
        logger.info("Resolved ESPN scoreboard URL: %s", self.url)

    # No set_headers needed - ScraperBase injects via header_profile

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict):
            raise ValueError("Scoreboard response is not JSON dict.")
        if "events" not in self.decoded_data:
            raise ValueError("'events' key missing in JSON.")

    # ------------------------------------------------------------------ #
    # Transform -> self.data
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        events: List[dict] = self.decoded_data.get("events", [])
        logger.info("Found %d events for %s", len(events), self.opts["scoreDate"])

        games: List[Dict[str, Any]] = []
        for event in events:
            comp = (event.get("competitions") or [{}])[0]
            status_blob = comp.get("status", {}).get("type", {})
            teams_info: List[Dict[str, Any]] = []
            for c in comp.get("competitors", []):
                tm = c.get("team", {})
                teams_info.append(
                    {
                        "teamId": tm.get("id"),
                        "displayName": tm.get("displayName"),
                        "abbreviation": tm.get("abbreviation"),
                        "score": c.get("score"),
                        "winner": c.get("winner", False),
                        "homeAway": c.get("homeAway"),
                    }
                )

            games.append(
                {
                    "gameId": comp.get("id"),
                    "statusId": status_blob.get("id"),
                    "state": status_blob.get("state"),  # pre / in / post
                    "status": status_blob.get("description"),
                    "startTime": comp.get("date"),
                    "teams": teams_info,
                }
            )

        self.data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scoreDate": self.opts["scoreDate"],
            "gameCount": len(games),
            "games": games,
        }

    # ------------------------------------------------------------------ #
    # Stats line
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"scoreDate": self.opts["scoreDate"], "gameCount": self.data.get("gameCount", 0)}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetEspnScoreboard)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetEspnScoreboard.create_cli_and_flask_main()
    main()
    
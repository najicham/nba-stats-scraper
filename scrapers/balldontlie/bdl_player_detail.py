"""
BALLDONTLIE ‑ Player‑Detail endpoint                      v1 – 2025‑06‑22
-----------------------------------------------------------------------------
Fetch the JSON object for a single NBA player:

    https://api.balldontlie.io/v1/players/{playerId}

Use‑cases
---------
* Populate a player‑info cache on demand.
* Back‑fill missing height / position fields after roster updates.

CLI
---
    python -m scrapers.bdl.bdl_player_detail --playerId 237   # LeBron
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import List

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")


class BdlPlayerDetailScraper(ScraperBase):
    """
    Simple GET /players/{id}.
    """

    # ------------------------------------------------------------------ #
    # Config                                                             #
    # ------------------------------------------------------------------ #
    required_opts: List[str] = ["playerId"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_player_%(playerId)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_player_%(playerId)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        self.base_url = "https://api.balldontlie.io/v1/players"
        self.url = f"{self.base_url}/{self.opts['playerId']}"
        logger.info("Resolved BALLDONTLIE player‑detail URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = os.getenv("BDL_API_KEY")
        if not api_key:
            raise RuntimeError("Environment variable BDL_API_KEY not set")
        self.headers = {
            "Authorization": api_key,
            "User-Agent": "Mozilla/5.0 (compatible; scrape-bdl/1.0)",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict):
            raise ValueError("Player‑detail response is not JSON object")
        if self.decoded_data.get("id") != int(self.opts["playerId"]):
            raise ValueError("Returned playerId does not match requested playerId")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        self.data = {
            "playerId": self.opts["playerId"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "player": self.decoded_data,
        }
        logger.info("Fetched player detail for playerId=%s", self.opts["playerId"])

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"playerId": self.opts["playerId"]}


# ---------------------------------------------------------------------- #
# Google Cloud Function entry point                                      #
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    player_id = request.args.get("playerId")
    if not player_id:
        return ("Missing query param 'playerId'", 400)
    group = request.args.get("group", "prod")
    BdlPlayerDetailScraper().run({"playerId": player_id, "group": group})
    return f"BALLDONTLIE player‑detail scrape complete (playerId={player_id})", 200


# ---------------------------------------------------------------------- #
# CLI usage                                                              #
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--playerId", required=True, help="NBA player ID to fetch")
    cli.add_argument("--group", default="test")
    BdlPlayerDetailScraper().run(vars(cli.parse_args()))

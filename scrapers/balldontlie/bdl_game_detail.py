"""
BALLDONTLIE ‑ Game‑Detail endpoint                        v1 – 2025‑06‑22
-----------------------------------------------------------------------------
Retrieve the JSON object for *one* NBA game:

    https://api.balldontlie.io/v1/games/{gameId}

Typical uses:
  • Populate a game‑info cache just before tip‑off.
  • Re‑query historical games to fix missing data.

CLI
---
    python -m scrapers.bdl.bdl_game_detail --gameId 486435
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")


class BdlGameDetailScraper(ScraperBase):
    """
    Lightweight scraper for /games/{id}.
    """

    # ------------------------------------------------------------------ #
    # Config                                                             #
    # ------------------------------------------------------------------ #
    required_opts: List[str] = ["gameId"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_game_%(gameId)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_game_%(gameId)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        self.base_url = "https://api.balldontlie.io/v1/games"
        self.url = f"{self.base_url}/{self.opts['gameId']}"
        logger.info("Resolved BALLDONTLIE game‑detail URL: %s", self.url)

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
        # API returns {"message":"Game not found"} when id invalid
        if "id" not in self.decoded_data:
            raise ValueError(f"GameId {self.opts['gameId']} not found in BallDontLie")
        if self.decoded_data["id"] != int(self.opts["gameId"]):
            raise ValueError("Returned gameId does not match requested gameId")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        # No cursor; just wrap the single object with metadata.
        self.data = {
            "gameId": self.opts["gameId"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "game": self.decoded_data,
        }
        logger.info("Fetched game detail for gameId=%s", self.opts["gameId"])

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"gameId": self.opts["gameId"]}


# ---------------------------------------------------------------------- #
# Google Cloud Function entry point                                      #
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    game_id = request.args.get("gameId")
    if not game_id:
        return ("Missing query param 'gameId'", 400)
    group = request.args.get("group", "prod")
    BdlGameDetailScraper().run({"gameId": game_id, "group": group})
    return f"BALLDONTLIE game‑detail scrape complete (gameId={game_id})", 200


# ---------------------------------------------------------------------- #
# CLI usage                                                              #
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--gameId", required=True, help="NBA game ID to fetch")
    cli.add_argument("--group", default="test")
    BdlGameDetailScraper().run(vars(cli.parse_args()))

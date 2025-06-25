"""
BALLDONTLIE - Game-Detail endpoint                         v1.1 • 2025-06-24
-------------------------------------------------------------------------------
Retrieve the JSON object for one NBA game:

    https://api.balldontlie.io/v1/games/{gameId}

Typical uses
------------
• Populate a game-info cache just before tip-off.
• Re-query historical games to fix missing data.

CLI
---
    python -m scrapers.balldontlie.bdl_game_detail --gameId 18444564 --debug
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import List

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class BdlGameDetailScraper(ScraperBase):
    """Lightweight scraper for /games/{id}."""

    required_opts: List[str] = ["gameId"]
    download_type = DownloadType.JSON
    decode_download_data = True

    exporters = [
        # Normal artifact
        {
            "type": "file",
            "filename": "/tmp/bdl_game_%(gameId)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        # Capture RAW + EXP
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
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/games"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}/{self.opts['gameId']}"
        logger.debug("Game-detail URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-game-detail/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """
        BDL v1.4 wraps single-resource responses in {"data": {...}}.
        Older versions returned the object bare.  Accept both.
        """
        if "id" in self.decoded_data:            # old format
            game = self.decoded_data
        elif "data" in self.decoded_data and "id" in self.decoded_data["data"]:
            game = self.decoded_data["data"]     # new wrapped format
        else:
            raise ValueError(f"GameId {self.opts['gameId']} not found in BallDontLie")

        if game["id"] != int(self.opts["gameId"]):
            raise ValueError("Returned gameId does not match requested gameId")

        # Replace decoded_data with the unwrapped object so downstream
        # transform / exporters don't care which format we got.
        self.decoded_data = game

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
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


# --------------------------------------------------------------------------- #
# Google Cloud Function entry                                                #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    game_id = request.args.get("gameId")
    if not game_id:
        return ("Missing query param 'gameId'", 400)
    opts = {
        "gameId": game_id,
        "group": request.args.get("group", "prod"),
        "apiKey": request.args.get("apiKey"),
        "runId": request.args.get("runId"),
    }
    BdlGameDetailScraper().run(opts)
    return f"BallDontLie game‑detail scrape complete (gameId={game_id})", 200


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from scrapers.utils.cli_utils import add_common_args

    parser = argparse.ArgumentParser(description="Scrape BallDontLie /games/{id}")
    parser.add_argument("--gameId", required=True, help="NBA game ID to fetch")
    add_common_args(parser)  # --group --apiKey --runId --debug
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    BdlGameDetailScraper().run(vars(args))

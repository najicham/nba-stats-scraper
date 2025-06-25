"""
BALLDONTLIE - Player-Detail endpoint                         v1.1 • 2025-06-24
-------------------------------------------------------------------------------
Fetch the JSON object for a single NBA player:

    https://api.balldontlie.io/v1/players/{playerId}

CLI
---
    python -m scrapers.balldontlie.bdl_player_detail --playerId 237 --debug
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
class BdlPlayerDetailScraper(ScraperBase):
    """Simple GET /players/{id} scraper."""

    required_opts: List[str] = ["playerId"]
    download_type = DownloadType.JSON
    decode_download_data = True

    exporters = [
        # Normal artifact
        {
            "type": "file",
            "filename": "/tmp/bdl_player_%(playerId)s.json",
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
    _API_ROOT = "https://api.balldontlie.io/v1/players"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}/{self.opts['playerId']}"
        logger.debug("Player-detail URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-player-detail/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """
        BDL v1.4 wraps responses in {"data": {...}}.
        Accept both wrapped and legacy bare objects.
        """
        if "id" in self.decoded_data:
            player = self.decoded_data                       # legacy format
        elif "data" in self.decoded_data and "id" in self.decoded_data["data"]:
            player = self.decoded_data["data"]               # new format
        else:
            raise ValueError(f"PlayerId {self.opts['playerId']} not found in BallDontLie")

        if player["id"] != int(self.opts["playerId"]):
            raise ValueError("Returned playerId does not match requested playerId")

        # Unwrap so transform/exporters work consistently
        self.decoded_data = player

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


# --------------------------------------------------------------------------- #
# Google Cloud Function entry                                                #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    player_id = request.args.get("playerId")
    if not player_id:
        return ("Missing query param 'playerId'", 400)
    opts = {
        "playerId": player_id,
        "group": request.args.get("group", "prod"),
        "apiKey": request.args.get("apiKey"),
        "runId": request.args.get("runId"),
    }
    BdlPlayerDetailScraper().run(opts)
    return f"BallDontLie player-detail scrape complete (playerId={player_id})", 200


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from scrapers.utils.cli_utils import add_common_args

    parser = argparse.ArgumentParser(description="Scrape BallDontLie /players/{id}")
    parser.add_argument("--playerId", required=True, help="NBA player ID to fetch")
    add_common_args(parser)  # --group --apiKey --runId --debug
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    BdlPlayerDetailScraper().run(vars(args))

"""
BALLDONTLIE - Active Players endpoint                         v1.1 • 2025‑06‑24
-------------------------------------------------------------------------------
Lists players flagged “active” this season.

    https://api.balldontlie.io/v1/players/active

Optional query params mirror /players:
  --teamId      restrict to one franchise
  --playerId    one specific player
  --search      free-text on first/last name

If none supplied: returns the full league (~500 rows).

CLI
---
    python -m scrapers.balldontlie.bdl_active_players          # entire league
    python -m scrapers.balldontlie.bdl_active_players --teamId 3
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Scraper
# --------------------------------------------------------------------------- #
class BdlActivePlayersScraper(ScraperBase):
    """Daily (or ad-hoc) scrape of /players/active."""

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    exporters = [
        # Normal dev / prod artifact (keyed by ident)
        {
            "type": "file",
            "filename": "/tmp/bdl_active_players_%(ident)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
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
# Google Cloud Function entry                                                #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    opts = {
        "teamId": request.args.get("teamId"),
        "playerId": request.args.get("playerId"),
        "search": request.args.get("search"),
        "group": request.args.get("group", "prod"),
        "apiKey": request.args.get("apiKey"),
        "runId": request.args.get("runId"),
    }
    BdlActivePlayersScraper().run(opts)
    ident = opts.get("playerId") or opts.get("teamId") or (
        f"search_{opts['search']}" if opts.get("search") else "league"
    )
    return f"BallDontLie active players scrape complete ({ident})", 200


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from scrapers.utils.cli_utils import add_common_args

    parser = argparse.ArgumentParser(description="Scrape BallDontLie /players/active")
    parser.add_argument("--teamId", help="Restrict to one team")
    parser.add_argument("--playerId", help="Restrict to one player")
    parser.add_argument("--search", help="Name search term")
    add_common_args(parser)                         # --group --apiKey --runId --debug
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    BdlActivePlayersScraper().run(vars(args))

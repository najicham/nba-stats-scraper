"""
BALLDONTLIE ‑ Active Players endpoint                       v1 – 2025‑06‑22
-----------------------------------------------------------------------------
Filters & cursor‑paginated list of **players who are active this season**

    https://api.balldontlie.io/v1/players/active

### Optional query parameters (mirrors `/players`)
* `teamId`    – restrict to one NBA franchise
* `search`    – free‑text search on first/last name
* `playerId`  – fetch one specific player

If **none** are supplied we grab the full league list (~500 rows).

CLI
---
    python -m scrapers.bdl.bdl_active_players_scraper            # entire league
    python -m scrapers.bdl.bdl_active_players_scraper --teamId 3 # ATL only
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")


class BdlActivePlayersScraper(ScraperBase):
    """
    Daily (or ad‑hoc) scraper for /players/active.
    """

    # ------------------------------------------------------------------ #
    # Config                                                             #
    # ------------------------------------------------------------------ #
    required_opts: List[str] = []               # everything optional
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_active_players_%(ident)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_active_players_%(ident)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts – build a concise identifier                       #
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
        logger.info("Resolved BALLDONTLIE active‑players URL: %s", self.url)

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
            raise ValueError("Active‑players response is not JSON object")
        if "data" not in self.decoded_data:
            raise ValueError("'data' field missing in active‑players JSON")

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
        logger.info(
            "Fetched %d active players (%s)", len(players), self.opts["ident"]
        )

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "playerCount": self.data.get("playerCount", 0),
            "ident": self.opts["ident"],
        }


# ---------------------------------------------------------------------- #
# Google Cloud Function entry point                                      #
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    team_id = request.args.get("teamId")
    player_id = request.args.get("playerId")
    search = request.args.get("search")
    group = request.args.get("group", "prod")

    opts = {"teamId": team_id, "playerId": player_id, "search": search, "group": group}
    BdlActivePlayersScraper().run(opts)
    ident = (
        opts.get("playerId")
        or opts.get("teamId")
        or (f"search_{search}" if search else "league")
    )
    return f"BALLDONTLIE active‑players scrape complete ({ident})", 200


# ---------------------------------------------------------------------- #
# CLI usage                                                              #
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--teamId", help="Restrict to one team")
    cli.add_argument("--playerId", help="Restrict to one player")
    cli.add_argument("--search", help="Name search term")
    cli.add_argument("--group", default="test")
    BdlActivePlayersScraper().run(vars(cli.parse_args()))

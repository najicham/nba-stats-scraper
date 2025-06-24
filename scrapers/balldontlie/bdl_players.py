"""
BALLDONTLIE ‑ Players endpoint                              v1 – 2025‑06‑22
-----------------------------------------------------------------------------
Fetches the *entire* player catalogue (~4.5 k rows) from

    https://api.balldontlie.io/v1/players

Uses cursor‑based pagination and the same requests.Session created by
ScraperBase, so proxy / retry behaviour is honoured.

CLI
---
    python -m scrapers.bdl.bdl_players_scraper
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")


class BdlPlayersScraper(ScraperBase):
    """
    Large table (~4 500 rows).  Recommended cadence: nightly at off‑peak time.
    """

    # ------------------------------------------------------------------ #
    # Class‑level config
    # ------------------------------------------------------------------ #
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    required_opts: List[str] = []

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_players_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_players_%(date)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Derived option: date stamp for filenames
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        self.opts.setdefault("date", today)

    # ------------------------------------------------------------------ #
    # URL & headers
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/players"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}?per_page=100"
        logger.info("Resolved BALLDONTLIE players URL: %s", self.url)

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
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict):
            raise ValueError("Players response is not JSON object")
        if "data" not in self.decoded_data:
            raise ValueError("'data' field missing in players JSON")

    # ------------------------------------------------------------------ #
    # Transform (full cursor walk)
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        all_players: List[Dict[str, Any]] = list(self.decoded_data["data"])
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
            all_players.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")

        all_players.sort(key=lambda p: p["id"])

        self.data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "playerCount": len(all_players),
            "players": all_players,
        }
        logger.info("Fetched %d players", len(all_players))

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"playerCount": self.data.get("playerCount", 0)}


# ---------------------------------------------------------------------- #
# Google Cloud Function entry point
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    group = request.args.get("group", "prod")
    BdlPlayersScraper().run({"group": group})
    return "BALLDONTLIE players scrape complete", 200


# ---------------------------------------------------------------------- #
# CLI usage
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--group", default="test")
    args = cli.parse_args()

    BdlPlayersScraper().run(vars(args))

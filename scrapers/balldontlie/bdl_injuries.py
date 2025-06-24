"""
BALLDONTLIE ‑ Player Injuries endpoint                    v1 – 2025‑06‑22
-----------------------------------------------------------------------------
Current injury statuses from

    https://api.balldontlie.io/v1/player_injuries

### Parameters (all optional)
* `teamId`   – restrict to one NBA team
* `playerId` – restrict to one player

If **neither** is supplied we fetch the *entire* league list.  
The endpoint is cursor‑paginated; we follow the chain until exhausted.

CLI
---
    python -m scrapers.bdl.bdl_injuries_scraper            # whole league
    python -m scrapers.bdl.bdl_injuries_scraper --teamId 2 # BOS only
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")


class BdlInjuriesScraper(ScraperBase):
    """
    Hourly or ad‑hoc scraper for /player_injuries.
    """

    # ------------------------------------------------------------------ #
    # Config                                                             #
    # ------------------------------------------------------------------ #
    required_opts: List[str] = []    # all params optional
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_injuries_%(ident)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_injuries_%(ident)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts → ident string                                     #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        """Build a concise identifier for file names & logs."""
        if "playerId" in self.opts and self.opts["playerId"]:
            self.opts["ident"] = f"player_{self.opts['playerId']}"
        elif "teamId" in self.opts and self.opts["teamId"]:
            self.opts["ident"] = f"team_{self.opts['teamId']}"
        else:
            self.opts["ident"] = "league"

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/player_injuries"

    def set_url(self) -> None:
        params = {"per_page": 100}
        if self.opts.get("teamId"):
            params["team_ids[]"] = self.opts["teamId"]
        if self.opts.get("playerId"):
            params["player_ids[]"] = self.opts["playerId"]

        query = "&".join(f"{k}={v}" for k, v in params.items())
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}?{query}"
        logger.info("Resolved BALLDONTLIE injuries URL: %s", self.url)

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
            raise ValueError("Injuries response is not JSON object")
        if "data" not in self.decoded_data:
            raise ValueError("'data' field missing in injuries JSON")

    # ------------------------------------------------------------------ #
    # Transform (cursor‑aware)                                           #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        injuries: List[Dict[str, Any]] = list(self.decoded_data["data"])
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
            injuries.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")

        injuries.sort(key=lambda r: (r.get("team", {}).get("id"), r.get("player_id")))

        self.data = {
            "ident": self.opts["ident"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rowCount": len(injuries),
            "injuries": injuries,
        }
        logger.info(
            "Fetched %d injury rows for %s", len(injuries), self.opts["ident"]
        )

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"rowCount": self.data.get("rowCount", 0), "ident": self.opts["ident"]}


# ---------------------------------------------------------------------- #
# Google Cloud Function entry point                                      #
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    team_id = request.args.get("teamId")
    player_id = request.args.get("playerId")
    group = request.args.get("group", "prod")
    opts = {"teamId": team_id, "playerId": player_id, "group": group}
    BdlInjuriesScraper().run(opts)
    ident = opts.get("playerId") or opts.get("teamId") or "league"
    return f"BALLDONTLIE injuries scrape complete ({ident})", 200


# ---------------------------------------------------------------------- #
# CLI usage                                                              #
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--teamId", help="Restrict to one team")
    cli.add_argument("--playerId", help="Restrict to one player")
    cli.add_argument("--group", default="test")
    BdlInjuriesScraper().run(vars(cli.parse_args()))

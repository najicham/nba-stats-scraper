"""
BALLDONTLIE ‑ Team‑Detail endpoint                          v1 – 2025‑06‑22
-----------------------------------------------------------------------------
Retrieve the JSON object for one NBA franchise:

    https://api.balldontlie.io/v1/teams/{teamId}

Typical uses
------------
* On‑demand lookup when a user drills into a team page.
* Enrich game rows with official team nicknames + abbreviations.
* Periodic audit to detect venue / conference re‑alignments.

CLI
---
    python -m scrapers.bdl.bdl_team_detail --teamId 14   # L.A. Lakers
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import List

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")


class BdlTeamDetailScraper(ScraperBase):
    """
    Simple GET /teams/{id}.
    """

    # ------------------------------------------------------------------ #
    # Class‑level config                                                 #
    # ------------------------------------------------------------------ #
    required_opts: List[str] = ["teamId"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_team_%(teamId)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_team_%(teamId)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        self.base_url = "https://api.balldontlie.io/v1/teams"
        self.url = f"{self.base_url}/{self.opts['teamId']}"
        logger.info("Resolved BALLDONTLIE team‑detail URL: %s", self.url)

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
            raise ValueError("Team‑detail response is not JSON object")
        if self.decoded_data.get("id") != int(self.opts["teamId"]):
            raise ValueError("Returned teamId does not match requested teamId")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        self.data = {
            "teamId": self.opts["teamId"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "team": self.decoded_data,
        }
        logger.info("Fetched team detail for teamId=%s", self.opts["teamId"])

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"teamId": self.opts["teamId"]}


# ---------------------------------------------------------------------- #
# Google Cloud Function entry point                                      #
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    team_id = request.args.get("teamId")
    if not team_id:
        return ("Missing query param 'teamId'", 400)
    group = request.args.get("group", "prod")
    BdlTeamDetailScraper().run({"teamId": team_id, "group": group})
    return f"BALLDONTLIE team‑detail scrape complete (teamId={team_id})", 200


# ---------------------------------------------------------------------- #
# CLI usage                                                              #
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--teamId", required=True, help="NBA team ID to fetch")
    cli.add_argument("--group", default="test")
    BdlTeamDetailScraper().run(vars(cli.parse_args()))

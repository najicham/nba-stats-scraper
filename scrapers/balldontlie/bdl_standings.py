"""
BALLDONTLIE ‑ Standings endpoint                          v1 – 2025‑06‑22
-----------------------------------------------------------------------------
Conference / division standings from

    https://api.balldontlie.io/v1/standings

### Parameters
* `season` – e.g. `2024` for the 2024‑25 NBA season.  
  If omitted we auto‑derive the *active* season based on today’s date:
      • If month ≥ September → season = current calendar year  
      • Else                  → season = current year − 1

CLI
---
    python -m scrapers.bdl.bdl_standings_scraper --season 2024
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")


def _current_nba_season() -> int:
    """
    Derive the season year that BALLDONTLIE expects.
    Example: 2025‑06‑22  → season 2024 (2024‑25 season).
    """
    today = datetime.now(timezone.utc)
    return today.year if today.month >= 9 else today.year - 1


class BdlStandingsScraper(ScraperBase):
    """
    Daily or on‑demand scraper for /standings.
    """

    # ------------------------------------------------------------------ #
    # Config                                                             #
    # ------------------------------------------------------------------ #
    required_opts: List[str] = []              # season derived automatically
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_standings_%(season)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_standings_%(season)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts – ensure 'season'                                  #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        self.opts["season"] = int(self.opts.get("season") or _current_nba_season())

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/standings"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}?season={self.opts['season']}&per_page=100"
        logger.info("Resolved BALLDONTLIE standings URL: %s", self.url)

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
            raise ValueError("Standings response is not JSON object")
        if "data" not in self.decoded_data:
            raise ValueError("'data' field missing in standings JSON")

    # ------------------------------------------------------------------ #
    # Transform (cursor‑aware)                                           #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        rows: List[Dict[str, Any]] = list(self.decoded_data["data"])
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
            rows.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")

        # Deterministic: conference, then rank
        rows.sort(key=lambda r: (r.get("conference"), r.get("conference_rank")))

        self.data = {
            "season": self.opts["season"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "teamCount": len(rows),
            "standings": rows,
        }
        logger.info("Fetched standings for %d teams (season %s)", len(rows), self.opts["season"])

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"teamCount": self.data.get("teamCount", 0), "season": self.opts["season"]}


# ---------------------------------------------------------------------- #
# Google Cloud Function entry point                                      #
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    season = request.args.get("season")
    group = request.args.get("group", "prod")
    BdlStandingsScraper().run({"season": season, "group": group})
    return f"BALLDONTLIE standings scrape complete (season {season or _current_nba_season()})", 200


# ---------------------------------------------------------------------- #
# CLI usage                                                              #
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--season", type=int, help="Season start year, e.g. 2024")
    cli.add_argument("--group", default="test")
    BdlStandingsScraper().run(vars(cli.parse_args()))

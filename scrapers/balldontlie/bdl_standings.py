"""
BALLDONTLIE - Standings endpoint                              v1.1 • 2025-06-24
-------------------------------------------------------------------------------
Conference / division standings

    https://api.balldontlie.io/v1/standings

Params
------
--season  2024 = 2024-25 season. If omitted, derive from today's date:
            • month ≥ Sep → season = current year
            • otherwise   → current year - 1

CLI
---
    python -m scrapers.balldontlie.bdl_standings --season 2024 --debug
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger(__name__)


def _current_nba_season() -> int:
    today = datetime.now(timezone.utc)
    return today.year if today.month >= 9 else today.year - 1


class BdlStandingsScraper(ScraperBase):
    """Daily or on‑demand scraper for /standings."""

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True

    exporters = [
        # Normal artifact
        {
            "type": "file",
            "filename": "/tmp/bdl_standings_%(season)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        # Capture RAW
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        # Capture EXP
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DECODED,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts                                                    #
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
        logger.debug("Standings URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-standings/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Unexpected standings JSON structure")

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

        rows.sort(key=lambda r: (r.get("conference"), r.get("conference_rank")))

        self.data = {
            "season": self.opts["season"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "teamCount": len(rows),
            "standings": rows,
        }
        logger.info("Fetched standings for %d teams (season %s)",
                    len(rows), self.opts["season"])

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "teamCount": self.data.get("teamCount", 0),
            "season": self.opts["season"],
        }


# --------------------------------------------------------------------------- #
# Google Cloud Function entry                                                #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    opts = {
        "season": request.args.get("season"),
        "group": request.args.get("group", "prod"),
        "apiKey": request.args.get("apiKey"),
        "runId": request.args.get("runId"),
    }
    BdlStandingsScraper().run(opts)
    return (f"BallDontLie standings scrape complete "
            f"(season {opts['season'] or _current_nba_season()})", 200)


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from scrapers.utils.cli_utils import add_common_args

    parser = argparse.ArgumentParser(description="Scrape BallDontLie /standings")
    parser.add_argument("--season", type=int, help="Season start year, e.g. 2024")
    add_common_args(parser)                           # --group --apiKey --runId --debug
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    BdlStandingsScraper().run(vars(args))

"""
BALLDONTLIE – Odds endpoint                                   v1.1 • 2025‑06‑22
-------------------------------------------------------------------------------
Fetch betting odds either by calendar **date** or by **game_id**.

    • /odds?date=YYYY‑MM‑DD
    • /odds?game_id=123456

The scraper auto‑detects which mode to use depending on the CLI /
Cloud Function parameters.
"""
from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")

# --------------------------------------------------------------------------- #
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class BdlOddsScraper(ScraperBase):
    """Fetches odds rows, follows cursor pagination, and merges pages."""

    required_opts: List[str] = []         # date/gameId default automatically
    download_type = DownloadType.JSON
    decode_download_data = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_odds_%(ident)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_odds_%(ident)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Option derivation                                                  #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        today = datetime.datetime.now(datetime.timezone.utc).date()
        if self.opts.get("gameId"):
            self.opts["ident"] = f"game_{self.opts['gameId']}"
        else:
            self.opts["date"] = self.opts.get("date") or today.isoformat()
            self.opts["ident"] = f"date_{self.opts['date']}"

    # ------------------------------------------------------------------ #
    # HTTP setup                                                         #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/odds"

    def set_url(self) -> None:
        if self.opts.get("gameId"):
            self.base_url = self._API_ROOT
            self.url = f"{self._API_ROOT}?game_id={self.opts['gameId']}&per_page=100"
        else:
            self.base_url = self._API_ROOT
            self.url = f"{self._API_ROOT}?date={self.opts['date']}&per_page=100"
        logger.info("Resolved BALLDONTLIE odds URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        if not api_key:
            raise RuntimeError("BDL API key missing; set BDL_API_KEY or pass --apiKey")
        self.headers = {
            "Authorization": api_key,
            "User-Agent": "nba-stats-scraper/1.0",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Odds response malformed: no top‑level 'data' key")

    # ------------------------------------------------------------------ #
    # Transform : cursor loop + merge                                    #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        rows: List[Dict[str, Any]] = list(self.decoded_data["data"])
        cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")

        while cursor:
            r = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params={"cursor": cursor, "per_page": 100},
                timeout=self.timeout_http,
            )
            r.raise_for_status()
            j = r.json()
            rows.extend(j.get("data", []))
            cursor = j.get("meta", {}).get("next_cursor")

        # Warn if schema unexpected
        for idx, row in enumerate(rows[:3]):  # sample first few
            if "game_id" not in row or "type" not in row:
                logger.warning("Odds row %s missing standard keys: %s", idx, row.keys())

        # Robust sort: game_id → wager type → vendor → updated_at
        def _sort_key(r):
            return (
                r.get("game_id", 0),
                r.get("type", ""),
                r.get("vendor", ""),
                r.get("updated_at", ""),
            )

        rows.sort(key=_sort_key)

        self.data = {
            "ident": self.opts["ident"],
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "rowCount": len(rows),
            "odds": rows,
        }
        logger.info("Fetched %d odds rows for %s", len(rows), self.opts["ident"])

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"rowCount": self.data.get("rowCount", 0), "ident": self.opts["ident"]}


# ---------------------------------------------------------------------- #
# Google Cloud Function entry point                                      #
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    """
    Examples:
      • /bdl-odds?date=2025-01-01
      • /bdl-odds?gameId=123456
    """
    opts = {
        "gameId": request.args.get("gameId"),
        "date": request.args.get("date"),
        "apiKey": request.args.get("apiKey"),
        "group": request.args.get("group", "prod"),
    }
    BdlOddsScraper().run(opts)

    ident = f"gameId={opts['gameId']}" if opts.get("gameId") else f"date={opts.get('date') or 'today'}"
    return f"BALLDONTLIE odds scrape complete ({ident})", 200


# ---------------------------------------------------------------------- #
# CLI usage                                                              #
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    today = datetime.date.today().isoformat()

    cli = argparse.ArgumentParser(
        description="Scrape BALLDONTLIE odds by date or gameId"
    )
    cli.add_argument("--gameId", help="NBA game ID (overrides --date)")
    cli.add_argument("--date", default=today, help=f"YYYY-MM-DD, default {today}")
    cli.add_argument("--apiKey", help="Override BDL_API_KEY env var")
    cli.add_argument("--group", default="test", help="Exporter group (dev/test/prod)")

    BdlOddsScraper().run(vars(cli.parse_args()))

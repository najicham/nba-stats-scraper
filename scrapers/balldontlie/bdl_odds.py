"""
BALLDONTLIE – Odds endpoint                                   v1.2 • 2025‑06‑24
-------------------------------------------------------------------------------
Fetch betting odds either by calendar **date** or by **game_id**.

    /odds?date=YYYY‑MM‑DD
    /odds?game_id=123456
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class BdlOddsScraper(ScraperBase):
    """Fetch odds rows, follow cursor pagination, merge pages."""

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True

    exporters = [
        # Normal artifact
        {
            "type": "file",
            "filename": "/tmp/bdl_odds_%(ident)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
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
    # Option derivation                                                  #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        today = _dt.date.today().isoformat()
        if self.opts.get("gameId"):
            self.opts["ident"] = f"game_{self.opts['gameId']}"
        else:
            self.opts["date"] = self.opts.get("date") or today
            self.opts["ident"] = f"date_{self.opts['date']}"

    # ------------------------------------------------------------------ #
    # HTTP setup                                                         #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/odds"

    def set_url(self) -> None:
        if self.opts.get("gameId"):
            qs = f"game_id={self.opts['gameId']}"
        else:
            qs = f"date={self.opts['date']}"
        self.base_url = self._API_ROOT
        self.url = f"{self._API_ROOT}?{qs}&per_page=100"
        logger.debug("Odds URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-odds/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Odds response malformed: no 'data' key")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
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
            "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "rowCount": len(rows),
            "odds": rows,
        }
        logger.info("Fetched %d odds rows for %s", len(rows), self.opts["ident"])

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"rowCount": self.data.get("rowCount", 0), "ident": self.opts["ident"]}


# --------------------------------------------------------------------------- #
# Google Cloud Function entry                                                #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    opts = {
        "gameId": request.args.get("gameId"),
        "date": request.args.get("date"),
        "apiKey": request.args.get("apiKey"),
        "group": request.args.get("group", "prod"),
        "runId": request.args.get("runId"),
    }
    BdlOddsScraper().run(opts)
    ident = opts.get("gameId") or opts.get("date") or "today"
    return f"BallDontLie odds scrape complete ({ident})", 200


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from scrapers.utils.cli_utils import add_common_args

    today = _dt.date.today().isoformat()

    parser = argparse.ArgumentParser(description="Scrape BallDontLie /odds")
    parser.add_argument("--gameId", help="NBA game ID (overrides --date)")
    parser.add_argument("--date", default=today, help=f"YYYY-MM-DD (default {today})")
    add_common_args(parser)  # --group --apiKey --runId --debug
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    BdlOddsScraper().run(vars(args))

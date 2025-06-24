"""
BALLDONTLIE ‑ Leaders endpoint                             v1 – 2025‑06‑22
-----------------------------------------------------------------------------
Top‑N league leaders for a single statistic:

    https://api.balldontlie.io/v1/leaders

### Required query parameters
* `statType` – one of:
      pts, ast, reb, stl, blk, fg_pct, fg3_pct, ft_pct,
      tov, plus_minus, off_rtg, def_rtg, ts_pct, efg_pct, usg_pct, etc.
* `season`   – season start year, e.g. 2024 for the 2024‑25 season.

If neither is supplied we default to:
    • `statType = "pts"`
    • `season    = active NBA season` (same logic as standings scraper).

CLI
---
    python -m scrapers.bdl.bdl_leaders_scraper                   # defaults
    python -m scrapers.bdl.bdl_leaders_scraper --statType ast \
            --season 2024
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _current_nba_season() -> int:
    today = datetime.now(timezone.utc)
    return today.year if today.month >= 9 else today.year - 1


_VALID_STATS = {
    "pts", "ast", "reb", "stl", "blk", "tov",
    "fg_pct", "fg3_pct", "ft_pct",
    "plus_minus", "off_rtg", "def_rtg",
    "ts_pct", "efg_pct", "usg_pct",
}


class BdlLeadersScraper(ScraperBase):
    """
    Daily (or ad‑hoc) scraper for /leaders.
    """

    # ------------------------------------------------------------------ #
    # Config                                                             #
    # ------------------------------------------------------------------ #
    required_opts: List[str] = []           # we derive sensible defaults
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_leaders_%(ident)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_leaders_%(ident)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts – defaults & ident                                 #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        stat_type = (self.opts.get("statType") or "pts").lower()
        if stat_type not in _VALID_STATS:
            raise ValueError(
                f"Invalid statType '{stat_type}'. "
                f"Allowed: {', '.join(sorted(_VALID_STATS))}"
            )
        self.opts["statType"] = stat_type
        self.opts["season"] = int(self.opts.get("season") or _current_nba_season())
        self.opts["ident"] = f"{self.opts['season']}_{self.opts['statType']}"

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/leaders"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        self.url = (
            f"{self.base_url}?season={self.opts['season']}"
            f"&stat_type={self.opts['statType']}&per_page=100"
        )
        logger.info("Resolved BALLDONTLIE leaders URL: %s", self.url)

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
            raise ValueError("Leaders response is not JSON object")
        if "data" not in self.decoded_data:
            raise ValueError("'data' field missing in leaders JSON")

    # ------------------------------------------------------------------ #
    # Transform (cursor‑aware)                                           #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        leaders: List[Dict[str, Any]] = list(self.decoded_data["data"])
        cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")

        while cursor:
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params={
                    "cursor": cursor,
                    "per_page": 100,
                    "season": self.opts["season"],
                    "stat_type": self.opts["statType"],
                },
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            page_json: Dict[str, Any] = resp.json()
            leaders.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")

        # Deterministic order: rank ascending
        leaders.sort(key=lambda r: r.get("rank", 999))

        self.data = {
            "ident": self.opts["ident"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rowCount": len(leaders),
            "leaders": leaders,
        }
        logger.info(
            "Fetched %d leader rows for %s", len(leaders), self.opts["ident"]
        )

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0),
            "ident": self.opts["ident"],
        }


# ---------------------------------------------------------------------- #
# Google Cloud Function entry point                                      #
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    stat_type = request.args.get("statType")
    season = request.args.get("season")
    group = request.args.get("group", "prod")
    opts = {"statType": stat_type, "season": season, "group": group}
    BdlLeadersScraper().run(opts)
    ident = f"{opts.get('season') or _current_nba_season()}_{opts.get('statType') or 'pts'}"
    return f"BALLDONTLIE leaders scrape complete ({ident})", 200


# ---------------------------------------------------------------------- #
# CLI usage                                                              #
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--statType", help="e.g. pts, ast, reb (default: pts)")
    cli.add_argument("--season", type=int, help="Season start year, e.g. 2024")
    cli.add_argument("--group", default="test")
    BdlLeadersScraper().run(vars(cli.parse_args()))

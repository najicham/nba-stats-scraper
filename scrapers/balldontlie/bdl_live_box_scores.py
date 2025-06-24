"""
BALLDONTLIE ‑ Live Box‑Scores endpoint                    v1 – 2025‑06‑22
-----------------------------------------------------------------------------
Continuously updated, play‑by‑play‑level box scores from

    https://api.balldontlie.io/v1/box_scores/live

The endpoint returns **all** games that are currently in progress; if no games
are underway the `"data"` array is empty.

Typical use:
• Schedule every 2 minutes between 23:00 UTC and 06:00 UTC (typical NBA hours).
• Combine with the static `/box_scores` scraper (end‑of‑game snapshot).

CLI
---
    python -m scrapers.bdl.bdl_live_box_scores_scraper
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")


class BdlLiveBoxScoresScraper(ScraperBase):
    """
    Fast‑cadence scraper for /box_scores/live.
    """

    # ------------------------------------------------------------------ #
    # Config                                                             #
    # ------------------------------------------------------------------ #
    required_opts: List[str] = []            # no params needed
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    exporters = [
        {
            "type": "file",
            # Timestamped to avoid collisions when polling every 2 min
            "filename": "/tmp/bdl_live_boxes_%(ts)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_live_boxes_%(ts)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts → timestamp token for filename                     #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.opts.setdefault("ts", ts)

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/box_scores/live"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        self.url = self._API_ROOT   # no query params
        logger.info("Resolved BALLDONTLIE live box‑scores URL: %s", self.url)

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
            raise ValueError("Live boxes response is not JSON object")
        if "data" not in self.decoded_data:
            raise ValueError("'data' field missing in live boxes JSON")

    # ------------------------------------------------------------------ #
    # Transform (cursor‑safe though endpoint is single‑page today)       #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        live_boxes: List[Dict[str, Any]] = list(self.decoded_data["data"])
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
            live_boxes.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")

        live_boxes.sort(key=lambda g: g.get("game", {}).get("id"))

        self.data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pollId": self.opts["ts"],
            "gameCount": len(live_boxes),
            "liveBoxes": live_boxes,
        }
        logger.info("Fetched live box‑scores for %d in‑progress games", len(live_boxes))

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"gameCount": self.data.get("gameCount", 0), "pollId": self.opts["ts"]}


# ---------------------------------------------------------------------- #
# Google Cloud Function entry point                                      #
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    group = request.args.get("group", "prod")
    BdlLiveBoxScoresScraper().run({"group": group})
    return "BALLDONTLIE live box‑scores scrape complete", 200


# ---------------------------------------------------------------------- #
# CLI usage                                                              #
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--group", default="test")
    BdlLiveBoxScoresScraper().run(vars(cli.parse_args()))

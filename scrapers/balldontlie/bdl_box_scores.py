"""
BALLDONTLIE ‑ Box‑Scores (final) endpoint                v1 – 2025‑06‑22
-----------------------------------------------------------------------------
Final (post‑game) box scores from

    https://api.balldontlie.io/v1/box_scores

### Parameters
* `date` – required by the API; single YYYY‑MM‑DD value.
          If omitted we default to **yesterday (UTC)** because that is the
          date most games will have finished.

The endpoint is *currently* single‑page (no cursor), but the scraper is coded
defensively to follow `next_cursor` if it ever appears.

CLI
---
    python -m scrapers.bdl.bdl_box_scores_scraper          # defaults to yesterday
    python -m scrapers.bdl.bdl_box_scores_scraper --date 2025-06-21
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")


class BdlBoxScoresScraper(ScraperBase):
    """
    Daily or on‑demand scraper for /box_scores (finished games only).
    """

    # ------------------------------------------------------------------ #
    # Config                                                             #
    # ------------------------------------------------------------------ #
    required_opts: List[str] = []            # we supply default date
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_box_scores_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_box_scores_%(date)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts – supply default date                              #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        if not self.opts.get("date"):
            # Yesterday in UTC
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
            self.opts["date"] = yesterday.isoformat()

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/box_scores"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}?date={self.opts['date']}&per_page=100"
        logger.info("Resolved BALLDONTLIE box‑scores URL: %s", self.url)

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
            raise ValueError("Box‑scores response is not JSON object")
        if "data" not in self.decoded_data:
            raise ValueError("'data' field missing in box‑scores JSON")

    # ------------------------------------------------------------------ #
    # Transform (cursor‑safe)                                            #
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

        # Deterministic order: gameId ASC, playerId ASC
        rows.sort(key=lambda r: (r.get("game", {}).get("id"), r.get("player_id")))

        self.data = {
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rowCount": len(rows),
            "boxScores": rows,
        }
        logger.info(
            "Fetched %d box‑score rows for %s", len(rows), self.opts["date"]
        )

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"rowCount": self.data.get("rowCount", 0), "date": self.opts["date"]}


# ---------------------------------------------------------------------- #
# Google Cloud Function entry point                                      #
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    date_param = request.args.get("date")
    group = request.args.get("group", "prod")
    opts = {"date": date_param, "group": group}
    BdlBoxScoresScraper().run(opts)
    return f"BALLDONTLIE box‑scores scrape complete ({opts.get('date') or 'yesterday'})", 200


# ---------------------------------------------------------------------- #
# CLI usage                                                              #
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--date", help="YYYY‑MM‑DD (default: yesterday UTC)")
    cli.add_argument("--group", default="test")
    BdlBoxScoresScraper().run(vars(cli.parse_args()))

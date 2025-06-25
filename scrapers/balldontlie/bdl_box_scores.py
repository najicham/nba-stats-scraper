"""
BALLDONTLIE – Box‑Scores (final) endpoint                 v1.1 • 2025‑06‑24
-------------------------------------------------------------------------------
Finished‑game box scores:

    https://api.balldontlie.io/v1/box_scores

--date param defaults to **yesterday (UTC)**.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class BdlBoxScoresScraper(ScraperBase):
    """Daily or on‑demand scraper for /box_scores."""

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True

    exporters = [
        # Normal artifact
        {
            "type": "file",
            "filename": "/tmp/bdl_box_scores_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
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
    # Additional opts                                                    #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        if not self.opts.get("date"):
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
            self.opts["date"] = yesterday.isoformat()

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/box_scores"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}?date={self.opts['date']}&per_page=100"
        logger.debug("Box‑scores URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-box-scores/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Box‑scores response malformed: missing 'data' key")

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

        rows.sort(key=lambda r: (r.get("game", {}).get("id"), r.get("player_id")))

        self.data = {
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rowCount": len(rows),
            "boxScores": rows,
        }
        logger.info("Fetched %d box‑score rows for %s", len(rows), self.opts["date"])

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"rowCount": self.data.get("rowCount", 0), "date": self.opts["date"]}


# --------------------------------------------------------------------------- #
# Google Cloud Function entry                                                #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    opts = {
        "date": request.args.get("date"),
        "group": request.args.get("group", "prod"),
        "apiKey": request.args.get("apiKey"),
        "runId": request.args.get("runId"),
    }
    BdlBoxScoresScraper().run(opts)
    return f"BallDontLie box‑scores scrape complete ({opts.get('date') or 'yesterday'})", 200


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from scrapers.utils.cli_utils import add_common_args

    parser = argparse.ArgumentParser(description="Scrape BallDontLie /box_scores")
    parser.add_argument("--date", help="YYYY‑MM‑DD (default: yesterday UTC)")
    add_common_args(parser)  # --group --apiKey --runId --debug
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    BdlBoxScoresScraper().run(vars(args))

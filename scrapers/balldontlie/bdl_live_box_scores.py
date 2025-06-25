"""
BALLDONTLIE - Live Box-Scores endpoint                      v1.1 • 2025-06-24
-------------------------------------------------------------------------------
Continuously updated box scores:

    https://api.balldontlie.io/v1/box_scores/live

Endpoint returns all games in progress; empty array when none.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class BdlLiveBoxScoresScraper(ScraperBase):
    """Fast-cadence scraper for /box_scores/live."""

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True

    exporters = [
        # Normal artifact (timestamp keeps files unique)
        {
            "type": "file",
            "filename": "/tmp/bdl_live_boxes_%(ts)s.json",
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
    # Additional opts – timestamp token                                  #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        self.opts.setdefault("ts", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/box_scores/live"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        self.url = self._API_ROOT
        logger.debug("Live box‑scores URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-live/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Live boxes response malformed: missing 'data' key")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
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


# --------------------------------------------------------------------------- #
# Google Cloud Function entry                                                #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    opts = {
        "group": request.args.get("group", "prod"),
        "apiKey": request.args.get("apiKey"),
        "runId": request.args.get("runId"),
    }
    BdlLiveBoxScoresScraper().run(opts)
    return "BallDontLie live box‑scores scrape complete", 200


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from scrapers.utils.cli_utils import add_common_args

    parser = argparse.ArgumentParser(description="Scrape BallDontLie /box_scores/live")
    add_common_args(parser)  # --group --apiKey --runId --debug
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    BdlLiveBoxScoresScraper().run(vars(args))

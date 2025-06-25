"""
BALLDONTLIE - Player Injuries endpoint                       v1.1 • 2025-06-24
-------------------------------------------------------------------------------
Current injuries:

    https://api.balldontlie.io/v1/player_injuries

Optional query params:
  --teamId     restrict to one team
  --playerId   restrict to one player
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
class BdlInjuriesScraper(ScraperBase):
    """Hourly or ad-hoc scraper for /player_injuries."""

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True

    exporters = [
        # Normal artifact
        {
            "type": "file",
            "filename": "/tmp/bdl_injuries_%(ident)s.json",
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
    # Additional opts – ident string                                     #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        if self.opts.get("playerId"):
            self.opts["ident"] = f"player_{self.opts['playerId']}"
        elif self.opts.get("teamId"):
            self.opts["ident"] = f"team_{self.opts['teamId']}"
        else:
            self.opts["ident"] = "league"

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/player_injuries"

    def set_url(self) -> None:
        params = {"per_page": 100}
        if self.opts.get("teamId"):
            params["team_ids[]"] = self.opts["teamId"]
        if self.opts.get("playerId"):
            params["player_ids[]"] = self.opts["playerId"]

        query = "&".join(f"{k}={v}" for k, v in params.items())
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}?{query}"
        logger.debug("Injuries URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-injuries/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Injuries response malformed: missing 'data' key")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        injuries: List[Dict[str, Any]] = list(self.decoded_data["data"])
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
            injuries.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")

        injuries.sort(key=lambda r: (r.get("team", {}).get("id"), r.get("player_id")))

        self.data = {
            "ident": self.opts["ident"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rowCount": len(injuries),
            "injuries": injuries,
        }
        logger.info("Fetched %d injury rows for %s", len(injuries), self.opts["ident"])

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
        "teamId": request.args.get("teamId"),
        "playerId": request.args.get("playerId"),
        "group": request.args.get("group", "prod"),
        "apiKey": request.args.get("apiKey"),
        "runId": request.args.get("runId"),
    }
    BdlInjuriesScraper().run(opts)
    ident = opts.get("playerId") or opts.get("teamId") or "league"
    return f"BallDontLie injuries scrape complete ({ident})", 200


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from scrapers.utils.cli_utils import add_common_args

    parser = argparse.ArgumentParser(description="Scrape BallDontLie /player_injuries")
    parser.add_argument("--teamId", help="Restrict to one team")
    parser.add_argument("--playerId", help="Restrict to one player")
    add_common_args(parser)  # --group --apiKey --runId --debug
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    BdlInjuriesScraper().run(vars(args))

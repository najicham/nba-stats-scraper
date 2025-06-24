"""
BallDontLie – Teams endpoint                                    v1.1 • 2025‑06‑23
-------------------------------------------------------------------------------
Grabs the full list of NBA franchises from

    https://api.balldontlie.io/v1/teams            (no auth required for free tier)

If pagination ever appears (meta.next_page > current_page) we’ll loop until done.

CLI
---
    python -m scrapers.balldontlie.bdl_teams --group dev
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger(__name__)  # module‑specific logger


# --------------------------------------------------------------------------- #
# Scraper
# --------------------------------------------------------------------------- #
class BdlTeams(ScraperBase):
    """Static reference table – typically run once per season."""

    # Basic config
    download_type = DownloadType.JSON
    decode_download_data = True
    required_opts: List[str] = []  # no CLI options required

    # Exporter configs
    exporters = [
        # Normal dev / prod artifact
        {
            "type": "file",
            "filename": "/tmp/bdl_teams.json",
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
        # Capture decoded EXP
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DECODED,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL & headers
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/teams"

    def set_url(self) -> None:
        self.url = self._API_ROOT  # no query params today
        logger.debug("Teams URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        hdrs = {
            "User-Agent": "scrape-bdl-teams/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:  # paid tier or future lockdown
            hdrs["Authorization"] = f"Bearer {api_key}"
        self.headers = hdrs

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Unexpected teams JSON structure")

    # ------------------------------------------------------------------ #
    # Transform (handles future pagination)
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        teams: List[Dict[str, Any]] = []
        page_json: Dict[str, Any] = self.decoded_data

        while True:
            teams.extend(page_json.get("data", []))

            # BDL v1 paginates with meta.next_page (int) or next_page_url (str)
            meta = page_json.get("meta", {})
            next_page = meta.get("next_page") or meta.get("next_page_url")
            if not next_page:
                break

            logger.debug("Following pagination to %s", next_page)
            page_json = self.http_downloader.get(
                next_page if isinstance(next_page, str) else self._API_ROOT,
                headers=self.headers,
                params={"page": next_page} if isinstance(next_page, int) else None,
                timeout=self.timeout_http,
            ).json()

        teams.sort(key=lambda t: t["id"])  # deterministic order

        self.data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "teamCount": len(teams),
            "teams": teams,
        }
        logger.info("Fetched %d NBA franchises", len(teams))

    # ------------------------------------------------------------------ #
    # Stats for SCRAPER_STATS
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"teamCount": self.data.get("teamCount", 0)}


# --------------------------------------------------------------------------- #
# Google Cloud Function entry point
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    opts = {
        "group": request.args.get("group", "prod"),
        "apiKey": request.args.get("apiKey"),  # optional override
        "runId": request.args.get("runId"),    # allow external run‑id
    }
    BdlTeams().run(opts)
    return ("BALLDONTLIE teams scrape complete", 200)


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from scrapers.utils.cli_utils import add_common_args

    parser = argparse.ArgumentParser(
        description="Scrape BallDontLie /teams endpoint"
    )
    add_common_args(parser)  # --group, --apiKey, --runId, --debug
    args = parser.parse_args()

    # Optional: flip logging level when --debug is set
    if getattr(args, "debug", False):
        logging.getLogger().setLevel(logging.DEBUG)

    BdlTeams().run(vars(args))

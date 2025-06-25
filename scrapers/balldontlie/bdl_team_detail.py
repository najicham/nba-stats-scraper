"""
BALLDONTLIE - Team Detail endpoint                         v1.2  2025-06-24
---------------------------------------------------------------------------
Fetch a single NBA franchise record:

    https://api.balldontlie.io/v1/teams/{teamId}

Example
-------
    python -m scrapers.balldontlie.bdl_team_detail --teamId 14
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import List

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.cli_utils import add_common_args

logger = logging.getLogger(__name__)


class BdlTeamDetailScraper(ScraperBase):
    """GET /teams/{id}"""

    required_opts: List[str] = ["teamId"]
    download_type = DownloadType.JSON
    decode_download_data = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_team_%(teamId)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "export_mode": ExportMode.DECODED,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL and headers                                                    #
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        self.base_url = "https://api.balldontlie.io/v1/teams"
        self.url = f"{self.base_url}/{self.opts['teamId']}"
        logger.debug("Team detail URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-team-detail/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict):
            raise ValueError("Team detail response is not a JSON object")

        # BallDontLie wraps single objects in {"data": {...}}
        payload = self.decoded_data.get("data", self.decoded_data)
        if payload.get("id") != int(self.opts["teamId"]):
            raise ValueError(
                f"Returned teamId {payload.get('id')} does not match requested {self.opts['teamId']}"
            )

        # Cache for transform
        self._team_obj = payload

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        self.data = {
            "teamId": self.opts["teamId"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "team": self._team_obj,
        }
        logger.info("Fetched team detail for teamId=%s", self.opts["teamId"])

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"teamId": self.opts["teamId"]}


# --------------------------------------------------------------------------- #
# Google Cloud Function entry                                                #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    opts = {
        "teamId": request.args.get("teamId"),
        "apiKey": request.args.get("apiKey"),
        "group": request.args.get("group", "prod"),
        "runId": request.args.get("runId"),
    }
    if not opts["teamId"]:
        return ("Missing query param 'teamId'", 400)
    BdlTeamDetailScraper().run(opts)
    return (
        f"BallDontLie team detail scrape complete (teamId={opts['teamId']})",
        200,
    )


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scrape BallDontLie /teams/{id}")
    parser.add_argument("--teamId", required=True, help="NBA team ID to fetch")
    add_common_args(parser)  # adds --group, --apiKey, --runId, --debug
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    BdlTeamDetailScraper().run(vars(args))

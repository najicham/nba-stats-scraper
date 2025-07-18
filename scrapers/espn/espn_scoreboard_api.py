# scrapers/espn_scoreboard.py
"""
ESPN NBA Scoreboard scraper                           v2 - 2025-06-16
--------------------------------------------------------------------
Pulls the daily scoreboard JSON from ESPN's public API and converts it
into a lightweight game list, suitable for job fan-out:

    [
        {
            "gameId": "401585725",
            "statusId": 2,
            "state": "in",          # pre / in / post
            "status": "2nd Quarter",
            "startTime": "2025-01-14T03:00Z",
            "teams": [
                {"teamId": "2",  "abbreviation": "BOS", "score": "47", ...},
                {"teamId": "17", "abbreviation": "LAL", "score": "45", ...}
            ]
        },
        ...
    ]

Improvements v2
---------------
*  `header_profile = "espn"`  → one-line UA updates if ESPN blocks a string
*  Strict ISO-8601 `timestamp`
*  Adds `state` & `statusId`
*  Uses new `_common_requests_kwargs()` helper in ScraperBase
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")


class GetEspnScoreboard(ScraperBase):
    """
    ESPN scoreboard scraper (JSON API).

    CLI example
    -----------
        python -m scrapers.espn_scoreboard --scoreDate 20250214
    """

    # ------------------------------------------------------------------ #
    # Class‑level configuration
    # ------------------------------------------------------------------ #
    required_opts: List[str] = ["scoreDate"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = "espn"

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/espn_scoreboard_%(scoreDate)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
        # ---------- raw JSON fixture (offline tests) ----------
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",  # FIXED: Use run_id instead of scoreDate
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        # ---------- golden snapshot (parsed DATA) ----------
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",  # FIXED: Use run_id instead of scoreDate
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL & HEADERS
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        base = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
        self.url = f"{base}?dates={self.opts['scoreDate']}"
        logger.info("Resolved ESPN scoreboard URL: %s", self.url)

    # No `set_headers` needed – ScraperBase injects via header_profile

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict):
            raise ValueError("Scoreboard response is not JSON dict.")
        if "events" not in self.decoded_data:
            raise ValueError("'events' key missing in JSON.")

    # ------------------------------------------------------------------ #
    # Transform → self.data
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        events: List[dict] = self.decoded_data.get("events", [])
        logger.info("Found %d events for %s", len(events), self.opts["scoreDate"])

        games: List[Dict[str, Any]] = []
        for event in events:
            comp = (event.get("competitions") or [{}])[0]
            status_blob = comp.get("status", {}).get("type", {})
            teams_info: List[Dict[str, Any]] = []
            for c in comp.get("competitors", []):
                tm = c.get("team", {})
                teams_info.append(
                    {
                        "teamId": tm.get("id"),
                        "displayName": tm.get("displayName"),
                        "abbreviation": tm.get("abbreviation"),
                        "score": c.get("score"),
                        "winner": c.get("winner", False),
                        "homeAway": c.get("homeAway"),
                    }
                )

            games.append(
                {
                    "gameId": comp.get("id"),
                    "statusId": status_blob.get("id"),
                    "state": status_blob.get("state"),  # pre / in / post
                    "status": status_blob.get("description"),
                    "startTime": comp.get("date"),
                    "teams": teams_info,
                }
            )

        self.data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scoreDate": self.opts["scoreDate"],
            "gameCount": len(games),
            "games": games,
        }

    # ------------------------------------------------------------------ #
    # Stats line
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"scoreDate": self.opts["scoreDate"], "gameCount": self.data.get("gameCount", 0)}


# ---------------------------------------------------------------------- #
# GCF entry point (optional)
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    score_date = request.args.get("scoreDate")
    if not score_date:
        return ("Missing query param 'scoreDate' (YYYYMMDD)", 400)

    opts = {"scoreDate": score_date, "group": request.args.get("group", "prod")}
    GetEspnScoreboard().run(opts)
    return f"ESPN Scoreboard scrape complete for {score_date}", 200


# ---------------------------------------------------------------------- #
# CLI usage
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from scrapers.utils.cli_utils import add_common_args

    cli = argparse.ArgumentParser(description="Scrape ESPN NBA Scoreboard")
    cli.add_argument("--scoreDate", required=True, help="YYYYMMDD")
    add_common_args(cli)  # This adds --group, --runId, --debug, etc.
    args = cli.parse_args()

    if args.debug:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)

    GetEspnScoreboard().run(vars(args))
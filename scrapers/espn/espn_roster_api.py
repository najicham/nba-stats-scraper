# scrapers/espn_roster_api.py
"""
ESPN NBA Roster API scraper                           v2 - 2025-06-16
--------------------------------------------------------------------
Endpoint pattern
    https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{teamId}?enable=roster

Key upgrades vs. v1
-------------------
* header_profile="espn" → UA managed centrally
* Strict ISO-8601 timestamp with timezone
* Handles BOTH legacy integer-inch “height” **and** new `{feet, inches}` dict
* Adds `prod` to exporter groups (keeps dev/test)
* Type hints + concise log line
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")


class GetEspnTeamRosterAPI(ScraperBase):
    """
    Scrape a single NBA roster via ESPN’s JSON API.

    CLI
    ---
        python -m scrapers.espn_roster_api --teamId 2
    """

    # ------------------------------------------------------------------ #
    # Class‑level config
    # ------------------------------------------------------------------ #
    required_opts: List[str] = ["teamId"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = "espn"

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/espn_roster_api_%(teamId)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
        # --- raw fixture for offline tests ---------------------------------
        {
            "type": "file",
            "filename": "/tmp/raw_%(teamId)s.json",   # <‑‑ capture.py expects raw_*
            "export_mode": ExportMode.RAW,            # untouched bytes from ESPN
            "groups": ["capture"],
        },
        # --- golden snapshot (parsed DATA) ---------------------------------
        {
            "type": "file",
            "filename": "/tmp/exp_%(teamId)s.json",   # <‑‑ capture.py expects exp_*
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        base = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
        self.url = f"{base}/{self.opts['teamId']}?enable=roster"
        logger.info("Resolved ESPN roster API URL: %s", self.url)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        root = self.decoded_data
        if not isinstance(root, dict):
            raise ValueError("Roster response is not JSON dict.")
        if "team" not in root or "athletes" not in root["team"]:
            raise ValueError("'team.athletes' missing in JSON.")

    # ------------------------------------------------------------------ #
    # Transform
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        team_obj: Dict[str, Any] = self.decoded_data["team"]
        athletes: List[dict] = team_obj.get("athletes", [])

        players: List[Dict[str, Any]] = []
        for ath in athletes:
            # --- Height parsing ------------------------------------------------------
            height_raw = ath.get("height")
            height_in: int | None = None
            if isinstance(height_raw, dict):
                try:
                    feet = int(height_raw.get("feet", 0))
                    inches = int(height_raw.get("inches", 0))
                    height_in = feet * 12 + inches
                except (TypeError, ValueError):
                    height_in = None
            elif isinstance(height_raw, (int, float, str)):
                try:
                    height_in = int(height_raw)
                except ValueError:
                    height_in = None

            players.append(
                {
                    "playerId": ath.get("id"),
                    "fullName": ath.get("fullName"),
                    "jersey": ath.get("jersey"),
                    "position": (ath.get("position") or {}).get("displayName"),
                    "heightIn": height_in,
                    "weightLb": ath.get("weight"),
                    "injuries": ath.get("injuries", []),
                }
            )

        self.data = {
            "teamId": self.opts["teamId"],
            "teamName": team_obj.get("displayName"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "playerCount": len(players),
            "players": players,
        }
        logger.info("Parsed %d players for teamId=%s", len(players), self.opts["teamId"])

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"teamId": self.opts["teamId"], "playerCount": self.data.get("playerCount", 0)}


# ---------------------------------------------------------------------- #
# GCF entry point (optional)
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    team_id = request.args.get("teamId")
    if not team_id:
        return ("Missing query param 'teamId'", 400)

    opts = {"teamId": team_id, "group": request.args.get("group", "prod")}
    GetEspnTeamRosterAPI().run(opts)
    return f"ESPN roster API scrape complete for teamId={team_id}", 200


# ---------------------------------------------------------------------- #
# CLI usage
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--teamId", required=True, help="e.g. 2 => Celtics")
    cli.add_argument("--group", default="test")
    args = cli.parse_args()

    GetEspnTeamRosterAPI().run(vars(args))

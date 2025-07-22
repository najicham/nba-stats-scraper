# scrapers/nbacom/nbac_game_score.py
"""
NBA.com Scoreboard (ScoreboardV3) scraper                v2 - 2025-06-16
------------------------------------------------------------------------
Fetches full game objects for a single calendar date.  Output schema is
almost identical to the Game‑ID collectors, but keeps every stat.nba.com
field so downstream analytics can dig deeper.

CLI example
-----------
    python -m scrapers.nbacom.nbac_game_score --gamedate 2025-03-16
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from ...scraper_base import DownloadType, ExportMode, ScraperBase
from ...utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaComGameScore(ScraperBase):
    """
    Scraper for the ScoreboardV3 endpoint on stats.nba.com.
    """

    # ------------------------------------------------------------------ #
    # Class-level configuration
    # ------------------------------------------------------------------ #
    required_opts: List[str] = ["gamedate"]          # YYYYMMDD or YYYY-MM-DD
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = "stats"             # base class injects UA + headers
    proxy_enabled: bool = True                       # stats site rate-limits GCP IPs

    exporters = [
        {
            "type": "gcs",
            "key": "nbacom/game-score/%(season)s/%(gamedate)s/%(time)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/nbacom_game_score_%(gamedate)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional options (season / time)
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        now = datetime.now(timezone.utc)
        self.opts["time"] = now.strftime("%H-%M-%S")

        raw = self.opts["gamedate"].replace("-", "")
        year = int(raw[0:4])
        self.opts["season"] = f"{year}-{(year + 1) % 100:02d}"

    # ------------------------------------------------------------------ #
    # URL builder
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        raw = self.opts["gamedate"].replace("-", "")
        if len(raw) != 8 or not raw.isdigit():
            raise DownloadDataException("gamedate must be YYYYMMDD or YYYY-MM-DD")

        yyyy, mm, dd = raw[0:4], raw[4:6], raw[6:8]
        mmddyyyy = f"{mm}/{dd}/{yyyy}"

        self.url = (
            "https://stats.nba.com/stats/scoreboardv3"
            f"?GameDate={mmddyyyy}&LeagueID=00&DayOffset=0"
        )
        logger.info("ScoreboardV3 URL: %s", self.url)

        # Normalise gamedate for exporters and stats
        self.opts["gamedate"] = raw

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        sb = self.decoded_data.get("scoreboard")
        if not sb or "games" not in sb:
            raise DownloadDataException("Missing 'scoreboard.games' in JSON.")
        if not isinstance(sb["games"], list):
            raise DownloadDataException("'games' is not a list.")
        logger.info(
            "Found %d games for gamedate=%s",
            len(sb["games"]),
            self.opts["gamedate"],
        )

    # ------------------------------------------------------------------ #
    # Transform
    # ------------------------------------------------------------------ #
    @staticmethod
    def _status_to_state(status: int | None) -> str:
        return {1: "pre", 2: "in", 3: "post"}.get(status, "unknown")

    def transform_data(self) -> None:
        games_raw: List[Dict[str, Any]] = self.decoded_data["scoreboard"]["games"]

        enriched: List[Dict[str, Any]] = []
        for g in games_raw:
            status = g.get("gameStatus")
            enriched.append(
                {
                    "gameId": g.get("gameId"),
                    "home": g.get("homeTeam", {}).get("teamTricode"),
                    "away": g.get("awayTeam", {}).get("teamTricode"),
                    "gameStatus": status,
                    "state": self._status_to_state(status),
                    "startTimeET": g.get("gameEt"),
                    "raw": g,  # keep the full object for analytics
                }
            )

        self.data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gamedate": self.opts["gamedate"],
            "season": self.opts["season"],
            "gameCount": len(enriched),
            "games": enriched,
        }

    # ------------------------------------------------------------------ #
    # Stats line
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "gamedate": self.opts["gamedate"],
            "gameCount": self.data.get("gameCount", 0),
        }


# ---------------------------------------------------------------------- #
# Cloud Function entry
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    gamedate = request.args.get("gamedate")
    if not gamedate:
        return ("Missing query param 'gamedate'", 400)

    opts = {
        "gamedate": gamedate,
        "group": request.args.get("group", "prod"),
    }
    ok = GetNbaComGameScore().run(opts)
    return (("Scoreboard scrape failed", 500) if ok is False else ("Scrape ok", 200))


# ---------------------------------------------------------------------- #
# Local CLI usage
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--gamedate", required=True, help="20250316 or 2025-03-16")
    cli.add_argument("--group", default="test")
    GetNbaComGameScore().run(vars(cli.parse_args()))

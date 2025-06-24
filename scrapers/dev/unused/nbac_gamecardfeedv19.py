"""
Game‑ID collector (Core‑API)                     v4 – June 2025
----------------------------------------------------------------
Pulls the day’s official NBA GameIDs from the protected Core‑API:

    https://core-api.nba.com/cp/api/v1.9/feeds/gamecardfeed

Cookies are harvested once via Playwright; the actual JSON is fetched
with plain `requests`, so we keep retries and exporters identical to
other ScraperBase children.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from ...scraper_base import (
    DownloadType,
    ExportMode,
    ScraperBase,
)
from ...utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaGameIdsCore(ScraperBase):
    """Collect Core‑API GameIDs for a given date."""

    # ------------------------------------------------------------------ #
    # Class‑level config
    # ------------------------------------------------------------------ #
    required_opts: List[str] = ["scoreDate"]           # YYYYMMDD | YYYY‑MM‑DD | today
    header_profile: str | None = "core"                # UA from helpers
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    # -------- Playwright switches ---------- #
    browser_enabled: bool = True                       # harvest cookies once
    # Template – we fill in YYYY‑MM‑DD at runtime
    browser_url: str | None = None
    proxy_enabled: bool = False
    proxy_url = "http://nchammas.gmail.com:bbuyfd@gate2.proxyfuel.com:2000"

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/nba_game_ids_core_%(scoreDate)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "gcs",
            "key": "nba/game_ids/%(scoreDate)s/game_ids_core.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # ---------- raw JSON fixture ----------
        {
            "type": "file",
            "filename": "/tmp/raw_%(scoreDate)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        # ---------- golden snapshot ----------
        {
            "type": "file",
            "filename": "/tmp/exp_%(scoreDate)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL & headers
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        raw = self.opts["scoreDate"].lower()
        if raw == "today":
            raw = datetime.utcnow().strftime("%Y%m%d")

        raw = raw.replace("-", "")                      # allow YYYY‑MM‑DD
        if len(raw) != 8 or not raw.isdigit():
            raise DownloadDataException("scoreDate must be YYYYMMDD, YYYY‑MM‑DD, or 'today'")

        yyyy, mm, dd = raw[0:4], raw[4:6], raw[6:8]
        mmddyyyy = f"{mm}/{dd}/{yyyy}"                  # Core‑API wants m/d/Y

        base = "https://core-api.nba.com/cp/api/v1.9/feeds/gamecardfeed"
        self.url = f"{base}?gamedate={mmddyyyy}&platform=web"
        logger.info("Resolved Core‑API URL: %s", self.url)

        # ─── Dynamic browser page & referer that match the date ───
        yyyy_mm_dd = f"{yyyy}-{mm}-{dd}"
        self.browser_url = f"https://www.nba.com/games?date={yyyy_mm_dd}"
        self.headers["Referer"] = self.browser_url   # override from set_headers()

        self.opts["scoreDate"] = raw                   # canonical form for exporters

    def set_headers(self) -> None:
        super().set_headers()
        referer = self.browser_url or "https://www.nba.com/games"
        # ----  add Akamai‑allow headers the Core‑API expects -------------
        self.headers.update({
            "Origin":             "https://www.nba.com",
            "Referer":            self.browser_url or "https://www.nba.com/games",
            "x-nba-stats-origin": "stats",
            "x-nba-stats-token":  "true",
            "Accept":             "application/json, text/plain, */*",
        })

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        games = self.decoded_data.get("games")
        if games is None:
            raise DownloadDataException("Missing 'games' key in Core‑API response.")
        if not isinstance(games, list):
            raise DownloadDataException("'games' key is not a list.")

    # ------------------------------------------------------------------ #
    # Transform
    # ------------------------------------------------------------------ #
    @staticmethod
    def _status_to_state(status: int | None) -> str:
        return {1: "pre", 2: "in", 3: "post"}.get(status, "unknown")

    def transform_data(self) -> None:
        games_raw: List[Dict[str, Any]] = self.decoded_data.get("games", [])
        logger.info("Found %d games for %s", len(games_raw), self.opts["scoreDate"])

        parsed_games = []
        for g in games_raw:
            status = g.get("gameStatus")
            parsed_games.append(
                {
                    "gameId": g.get("gameId"),
                    "home": g.get("homeTeam", {}).get("teamTricode"),
                    "away": g.get("awayTeam", {}).get("teamTricode"),
                    "gameStatus": status,                # 1 pre, 2 live, 3 final
                    "state": self._status_to_state(status),
                    "startTimeET": g.get("gameEt"),      # ISO string in ET
                }
            )

        self.data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scoreDate": self.opts["scoreDate"],
            "gameCount": len(parsed_games),
            "games": parsed_games,
        }

    # ------------------------------------------------------------------ #
    # Stats for SCRAPER_STATS log
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "scoreDate": self.opts["scoreDate"],
            "gameCount": self.data.get("gameCount", 0),
        }


# ---------------------------------------------------------------------- #
# Google Cloud Function entry
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    score_date = request.args.get("scoreDate") or "today"
    opts = {
        "scoreDate": score_date,
        "group": request.args.get("group", "prod"),
    }
    ok = GetNbaGameIdsCore().run(opts)
    return (
        ("Game‑ID scraper failed", 500) if ok is False else ("Scrape ok", 200)
    )


# ---------------------------------------------------------------------- #
# Local CLI helper
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse, sys
    cli = argparse.ArgumentParser()
    cli.add_argument("--scoreDate", default="today",
                     help="YYYYMMDD | YYYY‑MM‑DD | 'today'")
    cli.add_argument("--group", default="test")
    logger.setLevel(logging.DEBUG) 

    sys.exit(GetNbaGameIdsCore().run(vars(cli.parse_args())))

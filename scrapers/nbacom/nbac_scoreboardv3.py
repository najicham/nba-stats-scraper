# scrapers/nbacom/nbac_scoreboardv3.py
"""
Game‑ID collector (Scoreboard V3 with V2 fallback)       v3.0 – 2025‑06‑22
---------------------------------------------------------------------------
* Primary:  https://stats.nba.com/stats/scoreboardv3
* Fallback: https://stats.nba.com/stats/scoreboardV2        (same params)
Output schema is **identical** to v2 – downstream jobs need no changes.


"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, date
from typing import Any, Dict, List

import requests

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaGameIdsStats(ScraperBase):
    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #
    required_opts = ["scoreDate"]                        # YYYYMMDD or YYYY-MM-DD
    download_type = DownloadType.JSON
    decode_download_data = True
    header_profile = "stats"                             # central Stats‑API headers

    EXPORTERS = [
        {
            "type": "file",
            "filename": "/tmp/nba_game_ids_stats_%(scoreDate)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "gcs",
            "key": "nba/game_ids/%(scoreDate)s/game_ids_stats.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
    ]

    exporters = EXPORTERS  # ScraperBase expects class attr ‘exporters’

    # ------------------------------------------------------------------ #
    # URL helpers
    # ------------------------------------------------------------------ #
    BASE_V3 = "https://stats.nba.com/stats/scoreboardv3"
    BASE_V2 = "https://stats.nba.com/stats/scoreboardV2"

    def _yyyy_mm_dd(self) -> str:
        raw = self.opts["scoreDate"].replace("-", "")
        if len(raw) != 8 or not raw.isdigit():
            raise DownloadDataException("scoreDate must be YYYYMMDD or YYYY‑MM‑DD")
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"

    def _mm_dd_yyyy(self) -> str:
        ymd = self._yyyy_mm_dd()
        yyyy, mm, dd = ymd.split("-")
        return f"{mm}/{dd}/{yyyy}"

    def set_url(self) -> None:
        mmddyyyy = self._mm_dd_yyyy()
        self.url = f"{self.BASE_V3}?GameDate={mmddyyyy}&LeagueID=00&DayOffset=0"
        logger.info("Resolved Scoreboard V3 URL: %s", self.url)
        # normalise date for exporters
        self.opts["scoreDate"] = self._yyyy_mm_dd().replace("-", "")

    # ------------------------------------------------------------------ #
    # Download with fallback / retry
    # ------------------------------------------------------------------ #
    def download_and_decode(self) -> None:
        try:
            self.decoded_data = self._fetch_json(self.url)
        except Exception as exc_v3:                      # noqa: BLE001
            logger.warning("V3 failed (%s). Falling back to V2.", exc_v3)
            mmddyyyy = self._mm_dd_yyyy()
            v2_url = f"{self.BASE_V2}?GameDate={mmddyyyy}&LeagueID=00&DayOffset=0"
            self.url = v2_url
            self.decoded_data = self._fetch_json(v2_url, expect_v2=True)

    def _fetch_json(self, url: str, expect_v2: bool = False):
        # rudimentary 1‑retry on 429
        for attempt in (1, 2):
            resp = requests.get(url, headers=self.get_headers(), timeout=30)
            if resp.status_code == 429 and attempt == 1:
                logger.warning("Hit 429; sleeping 1 s then retrying.")
                time.sleep(1)
                continue
            if resp.status_code != 200:
                raise DownloadDataException(f"HTTP {resp.status_code}")
            data = resp.json()
            # quick schema check
            key = "resultSets" if expect_v2 else "scoreboard"
            if key not in data:
                raise DownloadDataException(f"Unexpected schema missing '{key}'.")
            return self._v2_to_v3(data) if expect_v2 else data
        raise DownloadDataException("Failed after retry")

    # ------------------------------------------------------------------ #
    # Schema normaliser (V2 → pseudo‑V3)
    # ------------------------------------------------------------------ #
    def _v2_to_v3(self, v2: dict) -> dict:
        # --- pull GameHeader rows ----------------------------------------
        gh = next(s for s in v2["resultSets"] if s["name"] == "GameHeader")
        idx_gh = {h: i for i, h in enumerate(gh["headers"])}

        # --- build lookup from LineScore for team abbreviations ----------
        ls = next(s for s in v2["resultSets"] if s["name"] == "LineScore")
        idx_ls = {h: i for i, h in enumerate(ls["headers"])}
        # map (gameId, teamId) -> TEAM_ABBREVIATION
        abbr = {
            (row[idx_ls["GAME_ID"]], row[idx_ls["TEAM_ID"]]): row[idx_ls["TEAM_ABBREVIATION"]]
            for row in ls["rowSet"]
        }

        games: List[dict] = []
        for row in gh["rowSet"]:
            game_id = row[idx_gh["GAME_ID"]]
            home_id = row[idx_gh["HOME_TEAM_ID"]]
            away_id = row[idx_gh["VISITOR_TEAM_ID"]]
            games.append(
                {
                    "gameId": game_id,
                    "homeTeam": {"teamTricode": abbr.get((game_id, home_id))},
                    "awayTeam": {"teamTricode": abbr.get((game_id, away_id))},
                    "gameStatus": row[idx_gh["GAME_STATUS_ID"]],
                    "gameEt": row[idx_gh["GAME_DATE_EST"]],
                    "gameCode": row[idx_gh["GAMECODE"]],
                }
            )

        return {"scoreboard": {"games": games}}


    # ------------------------------------------------------------------ #
    # Validation (after possible V2 mapping)
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not self.decoded_data["scoreboard"]["games"]:
            logger.warning("No games on %s (possible off‑day).", self.opts["scoreDate"])

    # ------------------------------------------------------------------ #
    # Transform
    # ------------------------------------------------------------------ #
    @staticmethod
    def _status_to_state(status: int | None) -> str:
        return {1: "pre", 2: "in", 3: "post"}.get(status, "unknown")

    def transform_data(self) -> None:
        games_raw: List[Dict[str, Any]] = self.decoded_data["scoreboard"]["games"]
        parsed_games = []
        for g in games_raw:
            status = g.get("gameStatus")
            parsed_games.append(
                {
                    "gameId": g.get("gameId"),
                    "home": g.get("homeTeam", {}).get("teamTricode"),
                    "away": g.get("awayTeam", {}).get("teamTricode"),
                    "gameStatus": status,
                    "state": self._status_to_state(status),
                    "startTimeET": g.get("gameEt"),
                    "gameCode": g.get("gameCode"),
                }
            )

        self.data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scoreDate": self.opts["scoreDate"],
            "gameCount": len(parsed_games),
            "games": parsed_games,
        }
        logger.info("Parsed %d games for %s", len(parsed_games), self.opts["scoreDate"])

    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"scoreDate": self.opts["scoreDate"], "gameCount": self.data["gameCount"]}

    # ------------------------------------------------------------------ #
    # Helper: central header bundle
    # ------------------------------------------------------------------ #
    def get_headers(self) -> Dict[str, str]:
        return self.headers or {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
                "Gecko/20100101 Firefox/124.0"
            ),
            "Referer": "https://www.nba.com/",
            "Origin": "https://www.nba.com",
            "x-nba-stats-token": "true",
            "Accept": "application/json, text/plain, */*",
        }


# ---------------------------------------------------------------------- #
# Cloud Function entry
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    score_date = request.args.get("scoreDate")
    if not score_date:
        return ("Missing query param 'scoreDate'", 400)

    ok = GetNbaGameIdsStats().run(
        {"scoreDate": score_date, "group": request.args.get("group", "prod")}
    )
    return (("Stats scrape failed", 500) if ok is False else ("Scrape ok", 200))


# ---------------------------------------------------------------------- #
# CLI
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument(
        "--scoreDate",
        default=date.today().isoformat(),
        help="YYYYMMDD or YYYY‑MM‑DD (default=today)",
    )
    cli.add_argument("--group", default="test")
    GetNbaGameIdsStats().run(vars(cli.parse_args()))

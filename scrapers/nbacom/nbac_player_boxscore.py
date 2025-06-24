# scrapers/nbacom/nbac_player_boxscore.py
"""
Player box-score scraper (leaguegamelog)                 v2 - 2025-06-16
-----------------------------------------------------------------------
Downloads per-player rows for a single game-date via
https://stats.nba.com/stats/leaguegamelog.

Features preserved from v1
--------------------------
* Three exporters (two local files + one GCS), all using ExportMode.RAW
* Proxy support for cloud IP blocks
* Helper add_dash_to_season()
* Cloud-Function entry point and local CLI
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaComPlayerBoxscore(ScraperBase):
    # ------------------------------------------------------------------ #
    # Config and exporters
    # ------------------------------------------------------------------ #
    required_opts: List[str] = ["gamedate"]              # YYYYMMDD or YYYY-MM-DD
    additional_opts = ["nba_season_from_gamedate", "nba_seasontype_from_gamedate"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = "stats"
    proxy_enabled: bool = True                           # stats.nba.com often rate‑limits GCP

    exporters = [
        {
            "type": "gcs",
            "key": "nbacom/player-boxscore/%(season)s/%(gamedate)s/%(time)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomplayerboxscore2.json",
            "export_mode": ExportMode.RAW,
            "groups": ["test", "file"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomplayerboxscore3.json",
            "export_mode": ExportMode.RAW,
            "groups": ["test", "file2"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts helper
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        raw_date = self.opts["gamedate"].replace("-", "")
        if len(raw_date) != 8 or not raw_date.isdigit():
            raise DownloadDataException("gamedate must be YYYYMMDD or YYYY-MM-DD")
        # normalise
        self.opts["gamedate"] = raw_date

        year = int(raw_date[0:4])
        self.opts.setdefault("season", str(year))
        self.opts.setdefault("season_type", "Regular Season")
        self.opts["time"] = datetime.now(timezone.utc).strftime("%H-%M-%S")

    # ------------------------------------------------------------------ #
    # URL builder
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        gd = self.opts["gamedate"]
        gd_fmt = f"{gd[0:4]}-{gd[4:6]}-{gd[6:8]}"
        season_dash = self.add_dash_to_season(self.opts["season"])
        season_type = self.opts["season_type"].replace(" ", "+")
        self.url = (
            "https://stats.nba.com/stats/leaguegamelog?"
            f"Counter=1000&DateFrom={gd_fmt}&DateTo={gd_fmt}&Direction=DESC&"
            f"LeagueID=00&PlayerOrTeam=P&Season={season_dash}&SeasonType={season_type}&Sorter=DATE"
        )
        logger.info("Constructed PlayerBoxscore URL: %s", self.url)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        rs = self.decoded_data.get("resultSets", [])
        if not rs or "rowSet" not in rs[0] or not rs[0]["rowSet"]:
            raise DownloadDataException("No player rows in leaguegamelog JSON.")
        logger.info(
            "Found %d players in rowSet for gamedate=%s.",
            len(rs[0]["rowSet"]),
            self.opts["gamedate"],
        )

    # ------------------------------------------------------------------ #
    # should_save_data mirrors original logic
    # ------------------------------------------------------------------ #
    def should_save_data(self) -> bool:
        rows = self.decoded_data["resultSets"][0]["rowSet"]
        return len(rows) > 0

    # ------------------------------------------------------------------ #
    # Helper
    # ------------------------------------------------------------------ #
    @staticmethod
    def add_dash_to_season(season_str: str) -> str:
        return season_str if "-" in season_str else f"{season_str}-{(int(season_str)+1)%100:02d}"

    # ------------------------------------------------------------------ #
    # Stats line
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        rows = self.decoded_data["resultSets"][0]["rowSet"]
        return {
            "records_found": len(rows),
            "gamedate": self.opts["gamedate"],
            "season": self.opts["season"],
            "season_type": self.opts["season_type"],
        }


# ---------------------------------------------------------------------- #
# Google Cloud Function entry
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    gamedate = request.args.get("gamedate")
    if not gamedate:
        return ("Missing query param 'gamedate'", 400)

    opts = {"gamedate": gamedate, "group": request.args.get("group", "prod")}
    ok = GetNbaComPlayerBoxscore().run(opts)
    return (("Player boxscore scrape failed", 500) if ok is False else ("Scrape ok", 200))


# ---------------------------------------------------------------------- #
# Local CLI usage
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description="Run NBA Player Boxscore locally")
    cli.add_argument("--gamedate", required=True, help="YYYYMMDD or YYYY-MM-DD")
    cli.add_argument("--group", default="test", help="dev / test / prod")
    GetNbaComPlayerBoxscore().run(vars(cli.parse_args()))

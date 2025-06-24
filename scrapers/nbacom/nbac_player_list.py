# scrapers/nbacom/nbac_player_list.py
"""
NBA.com season player index scraper                      v2 - 2025-06-16
------------------------------------------------------------------------
Downloads the `playerindex` feed for a given season (defaults to the
current season when none is supplied).

python -m scrapers.nbacom.nbac_player_list --season 2024

"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaComPlayerList(ScraperBase):
    # ------------------------------------------------------------------ #
    # Configuration (unchanged from v1 where possible)
    # ------------------------------------------------------------------ #
    proxy_enabled: bool = True
    header_profile: str | None = "stats"
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    additional_opts = ["nba_season_today"]  # same helper your code‑base already has

    exporters = [
        {
            "type": "gcs",
            "key": "nbacom/player-list/%(season)s/log/%(time)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "s3", "gcs"],
        },
        {
            "type": "gcs",
            "check_should_save": True,
            "key": "nbacom/player-list/%(season)s/current/current.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "s3", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomplayerlist",
            "export_mode": ExportMode.RAW,
            "groups": ["dev", "file"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomplayerlist%(season)s",
            "export_mode": ExportMode.DECODED,
            "pretty_print": True,
            "groups": ["dev", "test", "file"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Option helpers
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        # Default season → current calendar year
        if not self.opts.get("season"):
            self.opts["season"] = str(datetime.now(timezone.utc).year)
        # Timestamp for exporters
        self.opts["time"] = datetime.now(timezone.utc).strftime("%H-%M-%S")

    # ------------------------------------------------------------------ #
    # URL builder
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        season_dash = self.add_dash_to_season(self.opts["season"])
        self.url = (
            "https://stats.nba.com/stats/playerindex?"
            "College=&Country=&DraftPick=&DraftRound=&DraftYear=&Height=&"
            f"Historical=0&LeagueID=00&Season={season_dash}&"
            "SeasonType=Regular%20Season&TeamID=0&Weight="
        )
        logger.info("NBA.com PlayerList URL: %s", self.url)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        rs = self.decoded_data.get("resultSets")
        if not rs:
            raise DownloadDataException("'resultSets' missing or empty.")
        logger.info("resultSets found with length %d", len(rs))

    # ------------------------------------------------------------------ #
    # should_save_data (unchanged behaviour)
    # ------------------------------------------------------------------ #
    def should_save_data(self) -> bool:
        logger.info("Defaulting to True for should_save_data().")
        return True

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
        rows: List = (
            self.decoded_data.get("resultSets", [{}])[0]
            .get("rowSet", [])
        )
        return {
            "records_found": len(rows),
            "season": self.opts["season"],
        }


# ---------------------------------------------------------------------- #
# Google Cloud Function entry
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    season = request.args.get("season", "")  # blank → helper fills current
    group = request.args.get("group", "prod")

    ok = GetNbaComPlayerList().run({"season": season, "group": group})
    return (("Player list scrape failed", 500) if ok is False else ("Scrape ok", 200))


# ---------------------------------------------------------------------- #
# Local CLI usage
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description="Run NBA.com PlayerList locally")
    cli.add_argument("--season", default="", help="e.g. 2022 or blank for current season")
    cli.add_argument("--group", default="test")
    GetNbaComPlayerList().run(vars(cli.parse_args()))

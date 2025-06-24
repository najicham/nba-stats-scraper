"""
Full‑season schedule scraper (data.nba.com v2015)        v1 – 2025‑06‑22
Gets ANY season 2015‑present; no headers required.
-----------------------------------------------------------------------
CLI:
    python -m scrapers.nba_data_api.data_nba_season_schedule --season 2023 --group test
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import DownloadDataException
from ..utils.schedule_slicers import (
    slice_nba_season_by_date_small,
    slice_nba_season_by_date_large,
    slice_nba_season_by_team_large,
)

logger = logging.getLogger("scraper_base")


class GetDataNbaSeasonSchedule(ScraperBase):
    required_opts = ["season"]                      # 4‑digit start year
    download_type = DownloadType.JSON
    decode_download_data = True
    header_profile = None                           # open endpoint

    URL_TMPL = (
        "https://data.nba.com/data/v2015/json/mobile_teams/"
        "nba/{}/league/00_full_schedule.json"
    )

    exporters = [
        # raw
        {
            "type": "s3",
            "check_should_save": True,
            "key": "nba/schedule/{season}/raw/full_schedule.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "s3"],
        },
        # derived slices
        {
            "type": "s3",
            "check_should_save": True,
            "key": "nba/schedule/{season}/games/sliced_date_small.json",
            "export_mode": ExportMode.DATA,
            "data_key": "slice_date_small",
            "groups": ["prod", "s3"],
        },
        {
            "type": "s3",
            "check_should_save": True,
            "key": "nba/schedule/{season}/games/sliced_date_large.json",
            "export_mode": ExportMode.DATA,
            "data_key": "slice_date_large",
            "groups": ["prod", "s3"],
        },
        {
            "type": "s3",
            "check_should_save": True,
            "key": "nba/schedule/{season}/games/sliced_team_large.json",
            "export_mode": ExportMode.DATA,
            "data_key": "slice_team_large",
            "groups": ["prod", "s3"],
        },
        # local debug
        {
            "type": "file",
            "filename": "/tmp/data_nba_schedule_{season}.json",
            "export_mode": ExportMode.DECODED,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
    ]

    # ---------------- url
    def set_url(self) -> None:
        self.url = self.URL_TMPL.format(self.opts["season"])
        logger.info("Resolved data.nba.com URL: %s", self.url)

    # ---------------- download
    def download_and_decode(self) -> None:
        self.set_url()
        try:
            self.decoded_data: Dict[str, Any] = requests.get(self.url, timeout=30).json()
        except Exception as exc:  # noqa: BLE001
            raise DownloadDataException(f"Fetch failed: {exc}") from exc

        if "lscd" not in self.decoded_data:
            raise DownloadDataException("'lscd' key missing in schedule JSON")

    # ---------------- transform
    def transform_data(self) -> None:
        # convert v2015 format → leagueSchedule‑like dict so slicers reuse
        league_schedule = {"gameDates": []}
        for month in self.decoded_data["lscd"]:
            for g in month["mscd"]["g"]:
                league_schedule.setdefault("seasonYear", g["gdte"][:4] + "-" +
                                            str(int(g["gdte"][:4]) + 1)[-2:])
                league_schedule["gameDates"].append(
                    {
                        "date": g["gdte"],
                        "games": [
                            {
                                "gameId": g["gid"],
                                "gameDateUTC": g["gdtutc"],
                                "homeTeam": g["h"]["ta"],
                                "awayTeam": g["v"]["ta"],
                            }
                        ],
                    }
                )

        self.data["slice_date_small"] = slice_nba_season_by_date_small(
            {"leagueSchedule": league_schedule}, self.opts
        )
        self.data["slice_date_large"] = slice_nba_season_by_date_large(
            {"leagueSchedule": league_schedule}, self.opts
        )
        self.data["slice_team_large"] = slice_nba_season_by_team_large(
            {"leagueSchedule": league_schedule}, self.opts
        )

    # ---------------- stats
    def get_scraper_stats(self) -> dict:
        return {
            "season": self.opts["season"],
            "records_found": len(self.data["slice_date_small"]),
        }


# CLI helper
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--season", required=True, help="Start year, e.g. 2023")
    cli.add_argument("--group", default="test")
    GetDataNbaSeasonSchedule().run(vars(cli.parse_args()))

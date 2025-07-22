# scrapers/nbacom/nbac_player_list.py
"""
NBA.com season player index scraper                      v2 - 2025-06-16
------------------------------------------------------------------------
Downloads the `playerindex` feed for a given season (defaults to the
current season when none is supplied).

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py nbac_player_list \
      --season 2024 \
      --debug

  # Direct CLI execution:
  python scrapers/nbacom/nbac_player_list.py --season 2024 --debug

  # Flask web service:
  python scrapers/nbacom/nbac_player_list.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.nbacom.nbac_player_list
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_player_list.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

logger = logging.getLogger("scraper_base")


class GetNbaComPlayerList(ScraperBase, ScraperFlaskMixin):
    """Downloads NBA.com player index for a given season."""

    # Flask Mixin Configuration
    scraper_name = "nbac_player_list"
    required_params = []  # No required parameters (season defaults to current)
    optional_params = {
        "season": None,  # Defaults to current year if not provided
    }

    # ------------------------------------------------------------------ #
    # Configuration (unchanged from v1 where possible)
    # ------------------------------------------------------------------ #
    proxy_enabled: bool = True
    header_profile: str | None = "stats"
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    additional_opts = ["nba_season_today"]  # same helper your code‑base already has

    GCS_PATH_KEY = "nba_com_player_list"
    exporters = [
        {
            "type": "gcs",
            #"key": "nbacom/player-list/%(season)s/log/%(time)s.json",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "s3", "gcs"],
        },
        # {
        #     "type": "gcs",
        #     "check_should_save": True,
        #     "key": "nbacom/player-list/%(season)s/current/current.json",
        #     "export_mode": ExportMode.RAW,
        #     "groups": ["prod", "s3", "gcs"],
        # },
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
        # ADD THESE CAPTURE GROUP EXPORTERS:
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
    # Option helpers
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
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


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetNbaComPlayerList)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetNbaComPlayerList.create_cli_and_flask_main()
    main()
    
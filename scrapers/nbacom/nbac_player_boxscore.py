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
* Flask/Cloud Run entry point and local CLI

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py nbac_player_boxscore \
      --gamedate 20250115 \
      --debug

  # Direct CLI execution:
  python scrapers/nbacom/nbac_player_boxscore.py --gamedate 20250115 --debug

  # Flask web service:
  python scrapers/nbacom/nbac_player_boxscore.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.nbacom.nbac_player_boxscore
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_player_boxscore.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

logger = logging.getLogger("scraper_base")


class GetNbaComPlayerBoxscore(ScraperBase, ScraperFlaskMixin):
    """Downloads per-player rows for a single game-date via leaguegamelog."""

    # Flask Mixin Configuration
    scraper_name = "nbac_player_boxscore"
    required_params = ["gamedate"]
    optional_params = {
        "season": None,
        "season_type": None,
    }

    # ------------------------------------------------------------------ #
    # Config and exporters
    # ------------------------------------------------------------------ #
    required_opts: List[str] = ["gamedate"]              # YYYYMMDD or YYYY-MM-DD
    additional_opts = ["nba_season_from_gamedate", "nba_seasontype_from_gamedate"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = "stats"
    proxy_enabled: bool = True                           # stats.nba.com often rate‑limits GCP

    GCS_PATH_KEY = "nba_com_player_boxscore"
    exporters = [
        {
            "type": "gcs",
            #"key": "nbacom/player-boxscore/%(season)s/%(gamedate)s/%(time)s.json",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomplayerboxscore2.json",
            "export_mode": ExportMode.DATA,
            "groups": ["test", "file"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomplayerboxscore3.json",
            "export_mode": ExportMode.RAW,
            "groups": ["test", "file2"],
        },
        # ADD THESE CAPTURE EXPORTERS:
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
    # Additional opts helper
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        
        raw_date = self.opts["gamedate"].replace("-", "")
        if len(raw_date) != 8 or not raw_date.isdigit():
            raise DownloadDataException("gamedate must be YYYYMMDD or YYYY-MM-DD")
        # normalise
        self.opts["gamedate"] = raw_date

        # NBA season logic: seasons run October to April (next year)
        year = int(raw_date[0:4])
        month = int(raw_date[4:6])
        
        # If month is Jan-Sep, it's part of the previous season start year
        if month < 10:  # January through September
            season_start_year = year - 1
        else:  # October, November, December
            season_start_year = year
            
        self.opts.setdefault("season", str(season_start_year))
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
        if hasattr(self, 'data') and self.data:
            return {
                "records_found": self.data.get("player_count", 0),
                "gamedate": self.opts["gamedate"],
                "season": self.opts["season"],
                "season_type": self.opts["season_type"],
                "source": "nba_player_boxscore"
            }
        else:
            # Fallback to original logic
            rows = self.decoded_data["resultSets"][0]["rowSet"]
            return {
                "records_found": len(rows),
                "gamedate": self.opts["gamedate"],
                "season": self.opts["season"],
                "season_type": self.opts["season_type"],
            }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetNbaComPlayerBoxscore)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetNbaComPlayerBoxscore.create_cli_and_flask_main()
    main()
    
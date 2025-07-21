# scrapers/pbpstats/pbpstats_boxscore.py
"""
PBPStats **box-score** scraper                               v1 - 2025-06-17
--------------------------------------------------------------------------
Downloads NBA box‑score data via the PBPStats library.

For gameId ``0022400987`` the underlying request is:
    https://cdn.nba.com/static/json/liveData/boxscore/boxscore_0022400987.json

See: https://pbpstats.readthedocs.io/en/latest/pbpstats.data_loader.data_nba.boxscore.html

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py pbpstats_boxscore \
      --gameId 0022400987 \
      --debug

  # Direct CLI execution:
  python scrapers/pbpstats/pbpstats_boxscore.py --gameId 0022400987 --debug

  # Flask web service:
  python scrapers/pbpstats/pbpstats_boxscore.py --serve --debug
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.pbpstats.pbpstats_boxscore
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
except ImportError:
    # Direct execution: python scrapers/pbpstats/pbpstats_boxscore.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException

from pbpstats.client import Client

logger = logging.getLogger("scraper_base")


class GetNbaBoxscorePBPStats(ScraperBase, ScraperFlaskMixin):
    """Downloads NBA box‑score data via the PBPStats library."""

    # Flask Mixin Configuration
    scraper_name = "pbpstats_boxscore"
    required_params = ["gameId"]
    optional_params = {
        "debug": None,
    }

    required_opts = ["gameId"]

    # We bypass ScraperBase HTTP
    download_type = DownloadType.BINARY
    decode_download_data = False
    header_profile = "data"

    RAW_KEY = "raw_json"
    PLAYER_KEY = "player_stats"

    exporters = [
        # raw JSON --------------------------------------------------------- #
        {
            "type": "file",
            "filename": "/tmp/box_%(gameId)s_raw.json",
            "export_mode": ExportMode.DATA,
            "data_key": RAW_KEY,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "gcs",
            "key": "nba/boxscore/raw/%(season)s/%(gameId)s.json",
            "export_mode": ExportMode.DATA,
            "data_key": RAW_KEY,
            "groups": ["prod", "gcs"],
        },
        # cleaned player stats --------------------------------------------- #
        {
            "type": "file",
            "filename": "/tmp/box_%(gameId)s_playerstats.json",
            "export_mode": ExportMode.DATA,
            "data_key": PLAYER_KEY,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "gcs",
            "key": "nba/boxscore/player_stats/%(season)s/%(gameId)s.json",
            "export_mode": ExportMode.DATA,
            "data_key": PLAYER_KEY,
            "groups": ["prod", "gcs"],
        },
        # Add capture group exporters
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",
            "export_mode": ExportMode.DATA,
            "data_key": RAW_KEY,
            "groups": ["capture"],
        },
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "export_mode": ExportMode.DATA,
            "data_key": PLAYER_KEY,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------ PBPStats fetch
    def download_and_decode(self) -> None:
        gid = self.opts["gameId"]

        # season string (e.g. 00224xxxxx → 2023‑24)
        yr_prefix = int(gid[3:5]) + 2000
        self.opts["season"] = f"{yr_prefix}-{(yr_prefix + 1) % 100:02d}"

        cache_dir = "/tmp/pbp_cache"
        settings = {
            "dir": cache_dir,
            "Boxscore": {"source": "web", "data_provider": "data_nba"},
            "Games": {"source": "file", "data_provider": "data_nba"},
        }

        try:
            client = Client(settings)
            game = client.Game(gid)
        except Exception as exc:
            raise DownloadDataException(f"PBPStats failed for {gid}: {exc}") from exc

        # Raw JSON lives at game.boxscore.file_path
        try:
            with open(game.boxscore.file_path, "r", encoding="utf-8") as fh:
                self.raw_json: Dict = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            raise DownloadDataException(f"Unable to read cache file: {exc}") from exc

        # game.boxscore.data is already a plain dict — extract player stats list
        # Each item is like {'teamId': '1610612744', 'playerId': 201939, ...}
        try:
            self.player_stats: List[Dict] = game.boxscore.data["playerStats"]
        except Exception as exc:  # noqa: BLE001
            raise DownloadDataException(f"Unexpected boxscore data shape: {exc}") from exc

        if str(self.opts.get("debug", "0")).lower() in {"1", "true", "yes"}:
            logger.info("Boxscore cache path: %s", game.boxscore.file_path)

    # ------------------------------------------------------------ package for exporters
    def transform_data(self) -> None:
        self.data = {
            "metadata": {
                "gameId": self.opts["gameId"],
                "season": self.opts["season"],
                "generated": datetime.now(timezone.utc).isoformat(),
                "playerCount": len(self.player_stats),
            },
            self.RAW_KEY: self.raw_json,
            self.PLAYER_KEY: self.player_stats,
        }

    def get_export_data_for_exporter(self, exporter):
        return self.data.get(exporter.get("data_key", ""), {})

    # ------------------------------------------------------------ stats
    def get_scraper_stats(self) -> dict:
        return {
            "gameId": self.opts["gameId"],
            "players": len(self.player_stats),
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetNbaBoxscorePBPStats)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetNbaBoxscorePBPStats.create_cli_and_flask_main()
    main()
    
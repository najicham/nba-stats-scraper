# scrapers/pbpstats/pbpstats_possessions.py
"""
PBPStats *possessions* scraper                              v1 - 2025‑06‑17
--------------------------------------------------------------------------
Loads cleaned possessions for a game via the PBPStats library.

Docs: https://pbpstats.readthedocs.io/en/latest/pbpstats.data_loader.data_nba.possessions.html

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py pbpstats_possessions \
      --gameId 0022400987 \
      --debug

  # Direct CLI execution:
  python scrapers/pbpstats/pbpstats_possessions.py --gameId 0022400987 --debug

  # Flask web service:
  python scrapers/pbpstats/pbpstats_possessions.py --serve --debug
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
    # Module execution: python -m scrapers.pbpstats.pbpstats_possessions
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
except ImportError:
    # Direct execution: python scrapers/pbpstats/pbpstats_possessions.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException

from pbpstats.client import Client

logger = logging.getLogger("scraper_base")


class GetPossessionsPBPStats(ScraperBase, ScraperFlaskMixin):
    """Loads cleaned possessions for a game via the PBPStats library."""

    # Flask Mixin Configuration
    scraper_name = "pbpstats_possessions"
    required_params = ["gameId"]
    optional_params = {
        "debug": None,
    }

    required_opts = ["gameId"]

    # We bypass ScraperBase HTTP
    download_type = DownloadType.BINARY
    decode_download_data = False
    header_profile: str | None = "data"

    RAW_KEY = "raw_json"
    POSS_KEY = "possessions"

    exporters = [
        # raw JSON --------------------------------------------------------- #
        {
            "type": "file",
            "filename": "/tmp/poss_%(gameId)s_raw.json",
            "export_mode": ExportMode.DATA,
            "data_key": RAW_KEY,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "gcs",
            "key": "nba/possessions/raw/%(season)s/%(gameId)s.json",
            "export_mode": ExportMode.DATA,
            "data_key": RAW_KEY,
            "groups": ["prod", "gcs"],
        },
        # possession list -------------------------------------------------- #
        {
            "type": "file",
            "filename": "/tmp/poss_%(gameId)s_list.json",
            "export_mode": ExportMode.DATA,
            "data_key": POSS_KEY,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "gcs",
            "key": "nba/possessions/list/%(season)s/%(gameId)s.json",
            "export_mode": ExportMode.DATA,
            "data_key": POSS_KEY,
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
            "data_key": POSS_KEY,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------ fetch via PBPStats
    def download_and_decode(self) -> None:
        gid = self.opts["gameId"]

        # derive season (e.g. 00224xxxxx -> 2023‑24)
        yr_prefix = int(gid[3:5]) + 2000
        self.opts["season"] = f"{yr_prefix}-{(yr_prefix + 1) % 100:02d}"

        cache_dir = "/tmp/pbp_cache"
        settings = {
            "dir": cache_dir,
            "Possessions": {"source": "web", "data_provider": "data_nba"},
            "Games": {"source": "file", "data_provider": "data_nba"},
        }

        try:
            client = Client(settings)
            game = client.Game(gid)
        except Exception as exc:
            raise DownloadDataException(f"PBPStats error for {gid}: {exc}") from exc

        # PBPStats writes cleaned possessions JSON here:
        try:
            with open(game.possessions.file_path, "r", encoding="utf-8") as fh:
                self.raw_json: Dict | List = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            raise DownloadDataException(f"Unable to read cache file: {exc}") from exc

        # Each possession object -> plain dict
        self.possessions: List[Dict] = [p.__dict__ for p in game.possessions.items]

        if str(self.opts.get("debug", "0")).lower() in {"1", "true", "yes"}:
            logger.info("Possessions cache path: %s", game.possessions.file_path)

    # ------------------------------------------------------------ transform
    def transform_data(self) -> None:
        self.data = {
            "metadata": {
                "gameId": self.opts["gameId"],
                "season": self.opts["season"],
                "generated": datetime.now(timezone.utc).isoformat(),
                "possessionCount": len(self.possessions),
            },
            self.RAW_KEY: self.raw_json,
            self.POSS_KEY: self.possessions,
        }

    def get_export_data_for_exporter(self, exporter):
        return self.data.get(exporter.get("data_key", ""), {})

    # ------------------------------------------------------------ stats
    def get_scraper_stats(self) -> dict:
        return {"gameId": self.opts["gameId"], "possessions": len(self.possessions)}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetPossessionsPBPStats)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetPossessionsPBPStats.create_cli_and_flask_main()
    main()
    
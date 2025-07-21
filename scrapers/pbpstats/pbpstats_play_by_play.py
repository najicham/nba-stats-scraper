# scrapers/pbpstats/pbpstats_play_by_play.py
"""
PBPStats play-by-play scraper                               v2 - 2025-06-17
--------------------------------------------------------------------------
Downloads raw play-by-play via PBPStats and extracts cleaned possessions.

For `gameId=0022400987` the library downloads:
    https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_0022400987.json

See: https://pbpstats.readthedocs.io/en/latest/pbpstats.data_loader.data_nba.pbp.html

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py pbpstats_play_by_play \
      --gameId 0022400987 \
      --debug

  # Direct CLI execution:
  python scrapers/pbpstats/pbpstats_play_by_play.py --gameId 0022400987 --debug

  # Flask web service:
  python scrapers/pbpstats/pbpstats_play_by_play.py --serve --debug
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
    # Module execution: python -m scrapers.pbpstats.pbpstats_play_by_play
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
except ImportError:
    # Direct execution: python scrapers/pbpstats/pbpstats_play_by_play.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException

from pbpstats.client import Client

logger = logging.getLogger("scraper_base")


class GetNbaPlayByPlayPBPStats(ScraperBase, ScraperFlaskMixin):
    """
    Downloads raw play-by-play via PBPStats and extracts cleaned possessions.
    """

    # Flask Mixin Configuration
    scraper_name = "pbpstats_play_by_play"
    required_params = ["gameId"]
    optional_params = {
        "debug": None,
    }

    required_opts = ["gameId"]

    # We bypass ScraperBase's HTTP layer entirely
    download_type = DownloadType.BINARY
    decode_download_data = False
    header_profile = None

    RAW_KEY = "raw_json"
    POSS_KEY = "possessions"

    exporters = [
        # raw JSON --------------------------------------------------------- #
        {
            "type": "file",
            "filename": "/tmp/pbp_%(gameId)s_raw.json",
            "export_mode": ExportMode.DATA,
            "data_key": RAW_KEY,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "gcs",
            "key": "nba/pbp/raw/%(season)s/%(gameId)s.json",
            "export_mode": ExportMode.DATA,
            "data_key": RAW_KEY,
            "groups": ["prod", "gcs"],
        },
        # cleaned possessions --------------------------------------------- #
        {
            "type": "file",
            "filename": "/tmp/pbp_%(gameId)s_possessions.json",
            "export_mode": ExportMode.DATA,
            "data_key": POSS_KEY,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "gcs",
            "key": "nba/pbp/possessions/%(season)s/%(gameId)s.json",
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

    # ------------------------------------------------------------------ #
    # Override download_and_decode – use the PBPStats client
    # ------------------------------------------------------------------ #
    def download_and_decode(self) -> None:
        gid = self.opts["gameId"]
        self.step_info("download", "PBPStats fetch", extra={"gameId": gid})

        # Derive season from GameID (e.g. 00224xxxxx -> 2023‑24)
        yr_prefix = int(gid[3:5]) + 2000
        self.opts["season"] = f"{yr_prefix}-{(yr_prefix + 1) % 100:02d}"

        # -------------------------------- choose provider sequence
        providers = ["live", "stats_nba", "data_nba"]  # try live, then stats, then data
        for provider in providers:
            cache_dir = "/tmp/pbp_cache"
            settings = {
                "dir": cache_dir,
                # base play‑by‑play
                "Pbp": {"source": "web", "data_provider": provider},
                # let pbpstats create possessions from the PBP it just downloaded
                "Possessions": {"source": "web", "data_provider": provider},
                # Games loader not needed; omit for speed
            }
            try:
                client = Client(settings)          # noqa: S110
                game = client.Game(gid)
                break                              # success
            except Exception as exc:               # noqa: BLE001
                if provider == providers[-1]:
                    raise DownloadDataException(f"PBPStats error for {gid}: {exc}") from exc
                logger.warning(
                    "Provider '%s' failed (%s); trying '%s'",
                    provider, exc, providers[providers.index(provider)+1],
                )

        # raw JSON is already in-memory
        self.raw_json: Dict = game.pbp.source_data

        # Convert cleaned possession objects to plain dicts
        self.possessions_list: List[Dict] = [
            p.__dict__ for p in getattr(game, "possessions", {}).items  # type: ignore[attr-defined]
        ]

        if self.opts.get("debug") in {"1", "true", "yes"}:
            logger.info("PBPStats cache path: %s", game.pbp.file_path)

    # ------------------------------------------------------------------ #
    # Transform into exporter‑ready dict
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        self.data = {
            "metadata": {
                "gameId": self.opts["gameId"],
                "season": self.opts["season"],
                "generated": datetime.now(timezone.utc).isoformat(),
                "possessionCount": len(self.possessions_list),
            },
            self.RAW_KEY: self.raw_json,
            self.POSS_KEY: self.possessions_list,
        }

    # Map exporter.data_key to payload
    def get_export_data_for_exporter(self, exporter) -> Dict | List:
        return self.data.get(exporter.get("data_key", ""), {})

    # ------------------------------------------------------------------ #
    # Stats for SCRAPER_STATS
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "gameId": self.opts["gameId"],
            "possessions": len(self.possessions_list),
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetNbaPlayByPlayPBPStats)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetNbaPlayByPlayPBPStats.create_cli_and_flask_main()
    main()
    
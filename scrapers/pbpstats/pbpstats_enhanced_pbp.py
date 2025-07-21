# scrapers/pbpstats/pbpstats_enhanced_pbp.py
"""
PBPStats *enhanced* play‑by‑play scraper                   v1 - 2025‑06‑17
--------------------------------------------------------------------------
Downloads *enhanced* play‑by‑play via the PBPStats library.

Docs: https://pbpstats.readthedocs.io/en/latest/pbpstats.data_loader.data_nba.enhanced_pbp.html

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py pbpstats_enhanced_pbp \
      --gameId 0022400987 \
      --debug

  # Direct CLI execution:
  python scrapers/pbpstats/pbpstats_enhanced_pbp.py --gameId 0022400987 --debug

  # Flask web service:
  python scrapers/pbpstats/pbpstats_enhanced_pbp.py --serve --debug
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
    # Module execution: python -m scrapers.pbpstats.pbpstats_enhanced_pbp
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
except ImportError:
    # Direct execution: python scrapers/pbpstats/pbpstats_enhanced_pbp.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException

from pbpstats.client import Client

logger = logging.getLogger("scraper_base")


class GetEnhancedPbpPBPStats(ScraperBase, ScraperFlaskMixin):
    """Downloads *enhanced* play‑by‑play via the PBPStats library."""

    # Flask Mixin Configuration
    scraper_name = "pbpstats_enhanced_pbp"
    required_params = ["gameId"]
    optional_params = {
        "debug": None,
    }

    required_opts = ["gameId"]

    download_type = DownloadType.BINARY  # we bypass ScraperBase HTTP
    decode_download_data = False
    header_profile: str | None = "data"

    RAW_KEY = "raw_json"
    EVENTS_KEY = "events"

    exporters = [
        # raw JSON --------------------------------------------------------- #
        {
            "type": "file",
            "filename": "/tmp/enhanced_pbp_%(gameId)s_raw.json",
            "export_mode": ExportMode.DATA,
            "data_key": RAW_KEY,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "gcs",
            "key": "nba/enhanced_pbp/raw/%(season)s/%(gameId)s.json",
            "export_mode": ExportMode.DATA,
            "data_key": RAW_KEY,
            "groups": ["prod", "gcs"],
        },
        # flat events list ------------------------------------------------- #
        {
            "type": "file",
            "filename": "/tmp/enhanced_pbp_%(gameId)s_events.json",
            "export_mode": ExportMode.DATA,
            "data_key": EVENTS_KEY,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "gcs",
            "key": "nba/enhanced_pbp/events/%(season)s/%(gameId)s.json",
            "export_mode": ExportMode.DATA,
            "data_key": EVENTS_KEY,
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
            "data_key": EVENTS_KEY,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------ fetch via PBPStats
    def download_and_decode(self) -> None:
        gid = self.opts["gameId"]

        # season string, e.g. 00224xxxxx → 2023‑24
        yr_prefix = int(gid[3:5]) + 2000
        self.opts["season"] = f"{yr_prefix}-{(yr_prefix + 1) % 100:02d}"

        cache_dir = "/tmp/pbp_cache"
        settings = {
            "dir": cache_dir,
            "EnhancedPbp": {"source": "web", "data_provider": "data_nba"},
            "Games": {"source": "file", "data_provider": "data_nba"},
        }

        try:
            client = Client(settings)
            game = client.Game(gid)
        except Exception as exc:
            raise DownloadDataException(f"PBPStats error for {gid}: {exc}") from exc

        # Raw JSON path
        try:
            with open(game.enhanced_pbp.file_path, "r", encoding="utf-8") as fh:
                self.raw_json: Dict = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            raise DownloadDataException(f"Failed to read cache file: {exc}") from exc

        # Flatten event objects to dicts
        self.events: List[Dict] = [e.__dict__ for e in game.enhanced_pbp.items]

        if str(self.opts.get("debug", "0")).lower() in {"1", "true", "yes"}:
            logger.info("Enhanced PBP cache path: %s", game.enhanced_pbp.file_path)

    # ------------------------------------------------------------ transform
    def transform_data(self) -> None:
        self.data = {
            "metadata": {
                "gameId": self.opts["gameId"],
                "season": self.opts["season"],
                "generated": datetime.now(timezone.utc).isoformat(),
                "eventCount": len(self.events),
            },
            self.RAW_KEY: self.raw_json,
            self.EVENTS_KEY: self.events,
        }

    def get_export_data_for_exporter(self, exporter):
        return self.data.get(exporter.get("data_key", ""), {})

    # ------------------------------------------------------------ stats
    def get_scraper_stats(self) -> dict:
        return {"gameId": self.opts["gameId"], "events": len(self.events)}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetEnhancedPbpPBPStats)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetEnhancedPbpPBPStats.create_cli_and_flask_main()
    main()
    
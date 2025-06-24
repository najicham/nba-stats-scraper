# scrapers/pbpstats/pbpstats_enhanced_pbp.py
"""
PBPStats *enhanced* play‑by‑play scraper                   v1 - 2025‑06‑17
--------------------------------------------------------------------------
Quick‑start (local):
    python -m scrapers.pbpstats.pbpstats_enhanced_pbp --gameId 0022400987

Docs: https://pbpstats.readthedocs.io/en/latest/pbpstats.data_loader.data_nba.enhanced_pbp.html
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List

from pbpstats.client import Client

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetEnhancedPbpPBPStats(ScraperBase):
    """Downloads *enhanced* play‑by‑play via the PBPStats library."""

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


# ---------------------------------------------------------------------- #
# Google Cloud Function entry
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    gid = request.args.get("gameId")
    if not gid:
        return ("Missing gameId", 400)

    ok = GetEnhancedPbpPBPStats().run(
        {
            "gameId": gid,
            "group": request.args.get("group", "prod"),
            "debug": request.args.get("debug", "0"),
        }
    )
    return (("Enhanced PBP scrape failed", 500) if ok is False else ("Scrape ok", 200))


# ---------------------------------------------------------------------- #
# Local CLI
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description="Run PBPStats enhanced PBP scraper")
    cli.add_argument("--gameId", required=True, help="e.g. 0022400987")
    cli.add_argument("--group", default="test", help="dev / test / prod")
    cli.add_argument("--debug", default="0", help="1/true to print cache path")
    GetEnhancedPbpPBPStats().run(vars(cli.parse_args()))

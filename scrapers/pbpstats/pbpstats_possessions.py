# scrapers/pbpstats/pbpstats_possessions.py
"""
PBPStats *possessions* scraper                              v1 - 2025‑06‑17
--------------------------------------------------------------------------
Quick‑start (local):
    python -m scrapers.pbpstats.pbpstats_possessions --gameId 0022400987

Docs: https://pbpstats.readthedocs.io/en/latest/pbpstats.data_loader.data_nba.possessions.html
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


class GetPossessionsPBPStats(ScraperBase):
    """Loads cleaned possessions for a game via the PBPStats library."""

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


# ---------------------------------------------------------------------- #
# Google Cloud Function entry
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    gid = request.args.get("gameId")
    if not gid:
        return ("Missing gameId", 400)

    ok = GetPossessionsPBPStats().run(
        {
            "gameId": gid,
            "group": request.args.get("group", "prod"),
            "debug": request.args.get("debug", "0"),
        }
    )
    return (("Possession scrape failed", 500) if ok is False else ("Scrape ok", 200))


# ---------------------------------------------------------------------- #
# Local CLI
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description="Run PBPStats possessions scraper")
    cli.add_argument("--gameId", required=True, help="e.g. 0022400987")
    cli.add_argument("--group", default="test", help="dev / test / prod")
    cli.add_argument("--debug", default="0", help="1/true to print cache path")
    GetPossessionsPBPStats().run(vars(cli.parse_args()))

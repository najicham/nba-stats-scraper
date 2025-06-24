# scrapers/nbacom/nbac_pbpstats_playbyplay.py
"""
PBPStats play-by-play scraper                               v2 - 2025-06-17
--------------------------------------------------------------------------
Quick-start (local):
    python -m scrapers.nbacom.nbac_pbpstats_playbyplay --gameId 0022400987

What URL does PBPStats hit?
---------------------------
For `gameId=0022400987` the library downloads:

    https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_0022400987.json

See: https://pbpstats.readthedocs.io/en/latest/pbpstats.data_loader.data_nba.pbp.html
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List

from pbpstats.client import Client

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaPlayByPlayPBPStats(ScraperBase):
    """
    Downloads raw play-by-play via PBPStats and extracts cleaned possessions.
    """

    required_opts = ["gameId"]

    # We bypass ScraperBase’s HTTP layer entirely
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

        # PBPStats client settings with local cache dir
        cache_dir = "/tmp/pbp_cache"
        settings = {
            "dir": cache_dir,
            "Pbp": {"source": "web", "data_provider": "data_nba"},
            "Possessions": {"source": "file", "data_provider": "data_nba"},
            "Games": {"source": "file", "data_provider": "data_nba"},
        }

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


# ---------------------------------------------------------------------- #
# Google Cloud Function entry
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    gid = request.args.get("gameId")
    if not gid:
        return ("Missing gameId", 400)

    ok = GetNbaPlayByPlayPBPStats().run(
        {"gameId": gid, "group": request.args.get("group", "prod")}
    )
    return (("PBPStats scrape failed", 500) if ok is False else ("Scrape ok", 200))


# ---------------------------------------------------------------------- #
# Local CLI usage
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description="Run PBPStats play‑by‑play scraper")
    cli.add_argument("--gameId", required=True, help="e.g. 0022400987")
    cli.add_argument("--group", default="test", help="dev / test / prod")
    cli.add_argument("--debug", default="0", help="1/true to print cache path")
    GetNbaPlayByPlayPBPStats().run(vars(cli.parse_args()))

# nba_pbpstats_playbyplay.py
#
# Primary play‑by‑play scraper:
#   • Uses pbpstats Client (data_nba provider)
#   • Saves raw NBA JSON and cleaned possessions
#
# CLI:
#   python -m scrapers.nba_pbpstats_playbyplay --gameId 0022400987
#
# GCF:
#   .../nbaPbpStats?gameId=0022400987

import json
import logging
import os
from datetime import datetime
import pytz

from pbpstats.client import Client

from .scraper_base import ScraperBase, DownloadType, ExportMode
from .utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaPlayByPlayPBPStats(ScraperBase):
    """
    Downloads & cleans play‑by‑play via PBPStats.
    """

    required_opts = ["gameId"]

    # We bypass ScraperBase's HTTP downloader, so no decode.
    download_type = DownloadType.BINARY
    decode_download_data = False

    RAW_KEY = "raw_json"
    POSS_KEY = "possessions"

    exporters = [
        # ---------- raw JSON -----------------
        {
            "type": "file",
            "filename": "/tmp/pbp_%(gameId)s_raw.json",
            "export_mode": ExportMode.DATA,
            "data_key": RAW_KEY,
            "pretty_print": True,
            "groups": ["dev", "test"]
        },
        {
            "type": "gcs",
            "key": "nba/pbp/raw/%(season)s/%(gameId)s.json",
            "export_mode": ExportMode.DATA,
            "data_key": RAW_KEY,
            "groups": ["prod", "gcs"]
        },
        # ---------- possessions --------------
        {
            "type": "file",
            "filename": "/tmp/pbp_%(gameId)s_possessions.json",
            "export_mode": ExportMode.DATA,
            "data_key": POSS_KEY,
            "pretty_print": True,
            "groups": ["dev", "test"]
        },
        {
            "type": "gcs",
            "key": "nba/pbp/possessions/%(season)s/%(gameId)s.json",
            "export_mode": ExportMode.DATA,
            "data_key": POSS_KEY,
            "groups": ["prod", "gcs"]
        }
    ]

    # ---------------------------------------------------- override HTTP stage
    def download_and_decode(self):
        """
        Instead of ScraperBase HTTP, fetch via PBPStats.
        Saves:
            self.raw_json
            self.possessions_list
        """
        self.step_info("download", "PBPStats download/clean start",
                       extra={"gameId": self.opts["gameId"]})

        # Build season string from GameID (0022??xxxx – 22 = 2021‑22 season etc.)
        yr_prefix = int(self.opts["gameId"][3:5]) + 2000
        self.opts["season"] = f"{yr_prefix}-{(yr_prefix + 1) % 100:02d}"

        # Initialise pbpstats with local cache
        settings = {
            "dir": "/tmp/pbp_cache",
            "Pbp": {"source": "web", "data_provider": "data_nba"},
            "Possessions": {"source": "file", "data_provider": "data_nba"},
            "Games": {"source": "file", "data_provider": "data_nba"},
        }

        try:
            client = Client(settings)
            game = client.Game(self.opts["gameId"])
        except Exception as exc:
            raise DownloadDataException(f"PBPStats failed for {self.opts['gameId']}: {exc}")

        # Raw NBA JSON path is exposed by game.pbp.file_path
        raw_path = game.pbp.file_path
        with open(raw_path, "r", encoding="utf-8") as rf:
            self.raw_json = json.load(rf)

        # Clean possession objects
        self.possessions_list = [p.__dict__ for p in game.possessions.items]

    # ---------------------------------------------------- transform/export glue
    def transform_data(self):
        """
        Prepare self.data for the exporter system (two keys).
        """
        now_iso = datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat()
        self.data = {
            "metadata": {
                "gameId": self.opts["gameId"],
                "season": self.opts["season"],
                "generated": now_iso,
                "possessionCount": len(self.possessions_list)
            },
            self.RAW_KEY: self.raw_json,           # raw feed
            self.POSS_KEY: self.possessions_list   # cleaned possessions
        }

    # Export logic – map exporter.data_key to correct payload
    def get_export_data_for_exporter(self, exporter):
        key = exporter.get("data_key")
        return self.data.get(key, {})

    # ---------------------------------------------------- stats
    def get_scraper_stats(self):
        return {
            "gameId": self.opts["gameId"],
            "possessions": len(self.possessions_list)
        }


# ---------------------------------------------------- Google Cloud Function entry
def gcf_entry(request):
    """
    HTTP entry for Cloud Function / Cloud Run.

    ?gameId=0022400987
    ?group=test  (optional)
    """
    game_id = request.args.get("gameId")
    group   = request.args.get("group", "prod")

    if not game_id:
        return ("Missing required parameter: gameId", 400)

    opts = {"gameId": game_id, "group": group}
    scraper = GetNbaPlayByPlayPBPStats()
    ok = scraper.run(opts)

    if ok is False:
        return (f"PBPStats scrape failed for {game_id}", 500)
    return (f"PBPStats scrape completed for {game_id}", 200)


# ---------------------------------------------------- Local CLI helper
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--gameId", required=True, help="e.g. 0022400987")
    parser.add_argument("--group", default="test", help="dev, test, prod, etc.")
    args = parser.parse_args()

    scraper = GetNbaPlayByPlayPBPStats()
    scraper.run(vars(args))

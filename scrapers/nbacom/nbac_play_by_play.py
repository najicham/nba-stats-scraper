# nba_pbp_raw_backup.py
#
# One‑shot raw play‑by‑play fetcher.
# Use when PBPStats fails or when you want to re‑download a corrupt file.
#
# CLI:
#   python -m scrapers.nba_pbp_raw_backup --gameId 0022400987
#
# GCF:
#   .../nbaPbpRaw?gameId=0022400987

import logging
import pytz
from datetime import datetime

from .scraper_base import ScraperBase, DownloadType, ExportMode
from .utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaPlayByPlayRawBackup(ScraperBase):
    """
    Downloads raw play‑by‑play JSON directly from data.nba.com.
    """

    required_opts = ["gameId"]
    download_type = DownloadType.JSON
    header_profile = "data"
    decode_download_data = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/pbp_%(gameId)s_raw_backup.json",
            "export_mode": ExportMode.DECODED,
            "pretty_print": True,
            "groups": ["dev", "test"]
        },
        {
            "type": "gcs",
            "key": "nba/pbp/raw_backup/%(season)s/%(gameId)s.json",
            "export_mode": ExportMode.DECODED,
            "groups": ["prod", "gcs"]
        }
    ]

    # ------------------------------------------------------------ helpers
    def set_additional_opts(self):
        """
        Derive season from GameID (same logic as other scraper).
        """
        yr_prefix = int(self.opts["gameId"][3:5]) + 2000
        self.opts["season"] = f"{yr_prefix}-{(yr_prefix + 1) % 100:02d}"

    def set_url(self):
        gid = self.opts["gameId"]
        self.url = (
            "https://cdn.nba.com/static/json/liveData/playbyplay/"
            f"playbyplay_{gid}.json"
        )
        logger.info("Resolved play‑by‑play URL: %s", self.url)

    # ------------------------------------------------------------ validation
    def validate_download_data(self):
        if "game" not in self.decoded_data:
            raise DownloadDataException("playbyplay JSON missing 'game' root key")
        actions = self.decoded_data["game"].get("actions", [])
        if not actions:
            raise DownloadDataException("No 'actions' array in playbyplay JSON")

    # ------------------------------------------------------------ transform
    def transform_data(self):
        """
        Pass‑through JSON plus a tiny metadata wrapper.
        """
        ts = datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat()
        self.data = {
            "metadata": {
                "gameId": self.opts["gameId"],
                "season": self.opts["season"],
                "fetched": ts,
                "eventCount": len(self.decoded_data["game"]["actions"])
            },
            "playByPlay": self.decoded_data
        }

    # tell exporter which part to save (the whole dict)
    def get_export_data_for_exporter(self, exporter):
        return self.data["playByPlay"]

    # ------------------------------------------------------------ stats
    def get_scraper_stats(self):
        return {
            "gameId": self.opts["gameId"],
            "events": len(self.decoded_data["game"]["actions"])
        }


# ------------------------------------------------------------ GCF entry
def gcf_entry(request):
    """
    HTTP entry point for Cloud Function / Cloud Run.

    ?gameId=0022400987
    ?group=prod|test  (optional, default prod)
    """
    game_id = request.args.get("gameId")
    group   = request.args.get("group", "prod")

    if not game_id:
        return ("Missing required parameter: gameId", 400)

    opts = {"gameId": game_id, "group": group}
    scraper = GetNbaPlayByPlayRawBackup()
    ok = scraper.run(opts)

    if ok is False:
        return (f"Raw backup scrape failed for {game_id}", 500)
    return (f"Raw backup scrape completed for {game_id}", 200)


# ------------------------------------------------------------ Local CLI
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--gameId", required=True, help="e.g. 0022400987")
    parser.add_argument("--group", default="test", help="dev, test, prod, etc.")
    args = parser.parse_args()

    scraper = GetNbaPlayByPlayRawBackup()
    scraper.run(vars(args))

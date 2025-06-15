# scrapers/nba_com_player_movement.py

import os
import logging
from datetime import datetime

from ..scraper_base import ScraperBase, ExportMode
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaComPlayerMovement(ScraperBase):
    """
    Fetches the 'NBA_Player_Movement.json' from stats.nba.com,
    containing player movement/transaction data.
    """

    # If 'year' is not in self.opts, auto-populate with the current year
    additional_opts = ["current_year"]
    header_profile = "stats"
    # Proxy if needed; set to True if certain IPs are blocked
    proxy_enabled = False

    # Directly define the URL (some child classes do set_url, but here it's simple)
    url = "https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json"

    # Exporters referencing the new "export_mode" approach
    # all default to 'RAW' to mimic old 'use_raw=True'
    exporters = [
        {
            "type": "gcs",
            "key": "nbacom/player-movement/%(year)s/log/%(time)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "s3", "gcs"],
        },
        {
            "type": "gcs",
            "key": "nbacom/player-movement/%(year)s/current/current.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "s3", "gcs"],
        },
        {
            # local file usage
            "type": "file",
            "filename": "/tmp/getnbacomplayermovement2.json",
            "export_mode": ExportMode.RAW,
            "groups": ["dev", "file"],
        },
    ]

    def validate_download_data(self):
        """
        Ensure 'NBA_Player_Movement' and 'rows' exist, and that 'rows' is non-empty.
        Raises DownloadDataException if missing or empty.
        """
        data_root = self.decoded_data.get("NBA_Player_Movement")
        if not data_root:
            logger.error("'NBA_Player_Movement' missing in decoded data.")
            raise DownloadDataException("[NBA_Player_Movement] not found in decoded data")

        rows = data_root.get("rows")
        if rows is None:
            logger.error("'rows' not found in 'NBA_Player_Movement'. Keys are: %s", data_root.keys())
            raise DownloadDataException("[NBA_Player_Movement][rows] not found in decoded data")
        if not rows:
            logger.error("'rows' is empty in 'NBA_Player_Movement'.")
            raise DownloadDataException("[NBA_Player_Movement][rows] is empty")

        logger.info("Found %d rows in NBA_Player_Movement data for year=%s",
                    len(rows), self.opts.get("year", "unknown"))

    def get_scraper_stats(self):
        """
        Return fields for the final SCRAPER_STATS line:
        number of rows found and the year from opts.
        """
        data_root = self.decoded_data.get("NBA_Player_Movement", {})
        rows = data_root.get("rows", [])
        row_count = len(rows)

        year = self.opts.get("year", "unknown")

        return {
            "records_found": row_count,
            "year": year
        }


##############################################################################
# Cloud Function Entry Point
##############################################################################
def gcf_entry(request):
    """
    HTTP entry point for Cloud Functions.
    Example usage:
      GET .../NbaComPlayerMovement?year=2023&group=prod
      If 'year' is omitted, 'current_year' from additional_opts sets it automatically.
    """
    year = request.args.get("year", "")
    group = request.args.get("group", "prod")

    opts = {
        "year": year,   # blank => uses current_year
        "group": group
    }

    scraper = GetNbaComPlayerMovement()
    result = scraper.run(opts)
    return f"PlayerMovement run complete. Found result: {result}", 200


##############################################################################
# Local CLI Usage
##############################################################################
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run NBA Player Movement locally")
    parser.add_argument("--year", default="", help="e.g. 2023; if omitted, uses current_year.")
    parser.add_argument("--group", default="test", help="Which exporter group to run (dev/test/prod)")
    args = parser.parse_args()

    opts = vars(args)
    scraper = GetNbaComPlayerMovement()
    scraper.run(opts)

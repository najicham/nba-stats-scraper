# scrapers/nba_com_player_movement.py

import os
import logging
from datetime import datetime

from .scraper_base import ScraperBase
from .utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")

class GetNbaComPlayerMovement(ScraperBase):
    """
    Fetches the 'NBA_Player_Movement.json' from stats.nba.com,
    containing player movement/transaction data.
    """

    additional_opts = ["current_year"]
    url = "https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json"

    exporters = [
        {
            "type": "gcs",
            "key": "nbacom/player-movement/%(year)s/log/%(time)s.json",
            "use_raw": True,
            "groups": ["prod", "s3", "gcs"],
        },
        {
            "type": "gcs",
            "key": "nbacom/player-movement/%(year)s/current/current.json",
            "use_raw": True,
            "groups": ["prod", "s3", "gcs"],
        },
        {
            "active": True,
            "type": "file",
            "filename": "/tmp/getnbacomplayermovement2",
            "use_raw": True,
            "test": True,
            "groups": ["dev", "file"],
        },
    ]

    def validate_download_data(self):
        """
        Ensure 'NBA_Player_Movement' and 'rows' exist, and that 'rows' is non-empty.
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

    ##################################################################
    # Override get_scraper_stats() to include # of rows + year
    ##################################################################
    def get_scraper_stats(self):
        """
        Return fields for the final SCRAPER_STATS line:
        the number of rows found and the year from opts.
        """
        data_root = self.decoded_data.get("NBA_Player_Movement", {})
        rows = data_root.get("rows", [])
        row_count = len(rows)

        # year set by "current_year" or from user
        year = self.opts.get("year", "unknown")

        return {
            "records_found": row_count,
            "year": year
        }

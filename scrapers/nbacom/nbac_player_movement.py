# scrapers/nbacom/nbac_player_movement.py
"""
NBA Player-Movement / Transaction feed                    v2 - 2025-06-16
------------------------------------------------------------------------
Downloads player movement and transaction data from NBA.com. Useful for 
tracking roster changes, trades, signings, and player availability.

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py nbac_player_movement \
      --year 2025 \
      --debug

  # Direct CLI execution:
  python scrapers/nbacom/nbac_player_movement.py --year 2025 --debug

  # Flask web service:
  python scrapers/nbacom/nbac_player_movement.py --serve --debug
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
    # Module execution: python -m scrapers.nbacom.nbac_player_movement
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_player_movement.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

logger = logging.getLogger("scraper_base")


class GetNbaComPlayerMovement(ScraperBase, ScraperFlaskMixin):
    """
    Downloads the static JSON blob at
    https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json
    """

    # Flask Mixin Configuration
    scraper_name = "nbac_player_movement"
    required_params = []  # No required parameters (year defaults to current)
    optional_params = {
        "year": None,  # Defaults to current year if not provided
    }

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #
    additional_opts = ["year"]                # auto-fill `year` if omitted
    header_profile: str | None = "stats"
    proxy_enabled: bool = False
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    # Fixed URL (same as before)
    url = "https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json"

    GCS_PATH_KEY = "nba_com_player_movement"
    exporters = [
        {
            "type": "gcs",
            #"key": "nbacom/player-movement/%(year)s/log/%(time)s.json",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # {
        #     "type": "gcs", 
        #     "key": "nbacom/player-movement/%(year)s/current/current.json",
        #     "export_mode": ExportMode.DATA,
        #     "groups": ["prod", "gcs"],
        # },
        {
            "type": "file",
            "filename": "/tmp/nbacom_player_movement_%(year)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
        # ADD CAPTURE EXPORTERS for testing with capture.py
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json", 
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Option helpers
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        if not self.opts.get("year"):
            self.opts["year"] = str(datetime.now(timezone.utc).year)
        # exporter timestamp
        self.opts["time"] = datetime.now(timezone.utc).strftime("%H-%M-%S")

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict):
            raise DownloadDataException("Player movement response is not a valid JSON object")
            
        root = self.decoded_data.get("NBA_Player_Movement")
        if root is None:
            raise DownloadDataException("Missing 'NBA_Player_Movement' key in response")
            
        if not isinstance(root, dict):
            raise DownloadDataException("NBA_Player_Movement is not a valid object")
            
        rows = root.get("rows", [])
        if not isinstance(rows, list):
            raise DownloadDataException("NBA_Player_Movement.rows is not a list")
            
        if len(rows) == 0:
            raise DownloadDataException("NBA_Player_Movement.rows is empty - no movement data found")
            
        logger.info("Found %d movement rows for year=%s", len(rows), self.opts["year"])

    # ------------------------------------------------------------------ #
    # Enhanced validation for production use
    # ------------------------------------------------------------------ #
    def validate_player_movement_data(self) -> None:
        """
        Production validation for player movement data quality.
        """
        rows = self.data["rows"]
        
        # 1. REASONABLE RECORD COUNT CHECK
        record_count = len(rows)
        if record_count < 10:
            raise DownloadDataException(f"Suspiciously low record count: {record_count} (expected 100-15000)")
        elif record_count > 20000:
            raise DownloadDataException(f"Suspiciously high record count: {record_count} (expected 100-15000)")
        
        # 2. SAMPLE RECORD VALIDATION (check first few records)
        sample_size = min(5, len(rows))
        for i, row in enumerate(rows[:sample_size]):
            if not isinstance(row, (dict, list)):
                raise DownloadDataException(f"Row {i} is not a dict or list: {type(row)}")
                
            # For dictionary rows, check for reasonable keys
            if isinstance(row, dict):
                if len(row) < 2:
                    logger.warning(f"Row {i} has fewer keys than expected: {len(row)}")
                # Log sample keys for first row
                if i == 0:
                    sample_keys = list(row.keys())[:5]  # First 5 keys
                    logger.info(f"Sample row keys: {sample_keys}")
            
            # For list rows, check for reasonable columns  
            elif isinstance(row, list):
                if len(row) < 3:
                    logger.warning(f"Row {i} has fewer columns than expected: {len(row)}")
        
        # 3. YEAR CONSISTENCY CHECK
        current_year = int(self.opts["year"])
        current_season_years = [current_year - 1, current_year, current_year + 1]
        
        # Look for year patterns in sample data (movement data often contains dates)
        found_years = set()
        for row in rows[:10]:  # Check first 10 rows
            if isinstance(row, dict):
                # For dictionary rows, check all values
                for value in row.values():
                    if isinstance(value, str) and len(value) >= 4:
                        for year in current_season_years:
                            if str(year) in value:
                                found_years.add(year)
            elif isinstance(row, list):
                # For list rows, check all cells
                for cell in row:
                    if isinstance(cell, str) and len(cell) >= 4:
                        for year in current_season_years:
                            if str(year) in cell:
                                found_years.add(year)
        
        if found_years:
            logger.info(f"Found year references in data: {sorted(found_years)}")
        else:
            logger.info("No specific year references found in sample data")
        
        # 4. DATA STRUCTURE INSIGHTS
        if rows:
            first_row = rows[0]
            if isinstance(first_row, dict):
                logger.info(f"Dictionary-based data with {len(first_row)} fields per record")
            elif isinstance(first_row, list):
                logger.info(f"List-based data with {len(first_row)} columns per record")
        
        # Check for headers in original data structure
        data_headers = self.decoded_data.get("NBA_Player_Movement", {}).get("headers", [])
        if data_headers:
            logger.info(f"Movement data has {len(data_headers)} headers: {data_headers[:5]}")  # Show first 5
        
        logger.info(f"✅ Player movement validation passed: {record_count} records")

    # ------------------------------------------------------------------ #
    # Transform (pass-through but add meta)
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        rows = self.decoded_data["NBA_Player_Movement"]["rows"]
        headers = self.decoded_data["NBA_Player_Movement"].get("headers", [])
        
        self.data: Dict[str, any] = {
            "metadata": {
                "year": self.opts["year"],
                "fetchedUtc": datetime.now(timezone.utc).isoformat(),
                "recordCount": len(rows),
                "columnCount": len(headers) if headers else 0,
            },
            "headers": headers,
            "rows": rows,
        }
        
        # Add production validation
        self.validate_player_movement_data()

    # ------------------------------------------------------------------ #
    # Only save if we have reasonable data
    # ------------------------------------------------------------------ #
    def should_save_data(self) -> bool:
        if not isinstance(self.data, dict):
            return False
        return self.data.get("metadata", {}).get("recordCount", 0) > 0

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "year": self.opts["year"],
            "records": self.data.get("metadata", {}).get("recordCount", 0),
            "columns": self.data.get("metadata", {}).get("columnCount", 0),
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetNbaComPlayerMovement)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetNbaComPlayerMovement.create_cli_and_flask_main()
    main()
    
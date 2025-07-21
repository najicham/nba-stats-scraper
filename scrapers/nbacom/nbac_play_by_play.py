# scrapers/nbacom/nbac_play_by_play.py
"""
NBA.com Play-by-Play scraper                            v2 - 2025-06-16
-----------------------------------------------------------------------
Downloads the official play-by-play feed from data.nba.com for a given gameId.
This is NBA.com's primary play-by-play data source.

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py nbac_play_by_play \
      --gameId 0022400987 \
      --debug

  # Direct CLI execution:
  python scrapers/nbacom/nbac_play_by_play.py --gameId 0022400987 --debug

  # Flask web service:
  python scrapers/nbacom/nbac_play_by_play.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.nbacom.nbac_play_by_play
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_play_by_play.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaComPlayByPlay(ScraperBase, ScraperFlaskMixin):
    """Downloads official play-by-play JSON from NBA.com CDN."""

    # Flask Mixin Configuration
    scraper_name = "nbac_play_by_play"
    required_params = ["gameId"]
    optional_params = {
        "apiKey": None,  # Falls back to env var if needed
    }

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #
    required_opts = ["gameId"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = "data"

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/nbacom_play_by_play_%(gameId)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "gcs",
            "key": "nba/play-by-play/%(season)s/%(gameId)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
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
    # Additional opts helper (derive season)
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        # Add timestamp for exports
        now = datetime.now(timezone.utc)
        self.opts["time"] = now.strftime("%H-%M-%S")
        
        # Derive season from gameId (e.g., "0022400987" -> "2024-25")
        gid = self.opts["gameId"]
        try:
            yr_prefix = 2000 + int(gid[3:5])
            self.opts["season"] = f"{yr_prefix}-{(yr_prefix + 1) % 100:02d}"
        except (ValueError, IndexError):
            raise DownloadDataException("Invalid gameId format for season derivation")

    # ------------------------------------------------------------------ #
    # URL builder
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        gid = self.opts["gameId"]
        self.url = (
            f"https://cdn.nba.com/static/json/liveData/playbyplay/"
            f"playbyplay_{gid}.json"
        )
        logger.info("PBP URL: %s", self.url)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict):
            raise DownloadDataException("PBP response is not a valid JSON object")
            
        game = self.decoded_data.get("game")
        if game is None:
            raise DownloadDataException("PBP JSON missing 'game' key")
            
        if "actions" not in game:
            raise DownloadDataException("PBP JSON missing game.actions array")
            
        actions = game["actions"]
        if not isinstance(actions, list):
            raise DownloadDataException("game.actions is not a list")
            
        if len(actions) == 0:
            raise DownloadDataException("game.actions is empty - no play-by-play events found")

    # ------------------------------------------------------------------ #
    # Enhanced validation for production use
    # ------------------------------------------------------------------ #
    def validate_pbp_data(self) -> None:
        """
        Production validation for play-by-play data quality.
        """
        game = self.data["playByPlay"]["game"]
        actions = game["actions"]
        
        # 1. REASONABLE EVENT COUNT CHECK
        event_count = len(actions)
        if event_count < 50:
            raise DownloadDataException(f"Suspiciously low event count: {event_count} (expected 200-600)")
        elif event_count > 1000:
            raise DownloadDataException(f"Suspiciously high event count: {event_count} (expected 200-600)")
        
        # 2. BASIC DATA STRUCTURE VALIDATION  
        required_game_keys = ['gameId', 'actions']
        for key in required_game_keys:
            if key not in game:
                raise DownloadDataException(f"Missing required game key: {key}")
        
        # 3. SAMPLE ACTION VALIDATION (check first few events)
        sample_size = min(10, len(actions))
        for i, action in enumerate(actions[:sample_size]):
            if not isinstance(action, dict):
                raise DownloadDataException(f"Action {i} is not a dict: {type(action)}")
                
            # Check for essential action fields
            if 'actionType' not in action:
                logger.warning(f"Action {i} missing actionType: {action}")
        
        # 4. GAME ID CONSISTENCY
        game_id_from_data = game.get('gameId', '')
        expected_game_id = self.opts['gameId']
        if game_id_from_data != expected_game_id:
            logger.warning(f"Game ID mismatch: expected {expected_game_id}, got {game_id_from_data}")
        
        logger.info(f"✅ PBP validation passed: {event_count} events")

    # ------------------------------------------------------------------ #
    # Transform (wrap with metadata)
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        actions = self.decoded_data["game"]["actions"]

        self.data: Dict[str, Any] = {
            "metadata": {
                "gameId": self.opts["gameId"],
                "season": self.opts["season"],
                "fetchedUtc": ts,
                "eventCount": len(actions),
            },
            "playByPlay": self.decoded_data,
        }
        
        # Add production validation
        self.validate_pbp_data()

    # ------------------------------------------------------------------ #
    # Only save if we have reasonable data
    # ------------------------------------------------------------------ #
    def should_save_data(self) -> bool:
        if not isinstance(self.data, dict):
            return False
        return self.data.get("metadata", {}).get("eventCount", 0) > 0

    # ------------------------------------------------------------------ #
    # Stats line
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "gameId": self.opts["gameId"],
            "season": self.opts["season"],
            "events": self.data.get("metadata", {}).get("eventCount", 0),
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetNbaComPlayByPlay)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetNbaComPlayByPlay.create_cli_and_flask_main()
    main()
    
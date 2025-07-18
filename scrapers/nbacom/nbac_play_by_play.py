# scrapers/nbacom/nbac_play_by_play.py
"""
NBA.com Play-by-Play scraper                            v2 - 2025-06-16
-----------------------------------------------------------------------
Downloads the official play-by-play feed from data.nba.com for a given gameId.
This is NBA.com's primary play-by-play data source.

CLI example
-----------
    python -m scrapers.nbacom.nbac_play_by_play --gameId 0022400987 --debug
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaComPlayByPlay(ScraperBase):
    """Downloads official play-by-play JSON from NBA.com CDN."""

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


# ---------------------------------------------------------------------- #
# Cloud Function / Cloud Run HTTP entry
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    game_id = request.args.get("gameId")
    if not game_id:
        return ("Missing query param 'gameId'", 400)

    ok = GetNbaComPlayByPlay().run(
        {"gameId": game_id, "group": request.args.get("group", "prod")}
    )
    return (("PBP scrape failed", 500) if ok is False else ("Scrape ok", 200))


# ---------------------------------------------------------------------- #
# CLI helper with standardized arguments
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from scrapers.utils.cli_utils import add_common_args

    cli = argparse.ArgumentParser(description="NBA.com Play-by-Play Scraper")
    cli.add_argument("--gameId", required=True, help="NBA Game ID (e.g. 0022400987)")
    add_common_args(cli)  # Adds --group, --runId, --debug, etc.
    args = cli.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    GetNbaComPlayByPlay().run(vars(args))
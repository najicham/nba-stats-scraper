"""
File: scrapers/nbacom/nbac_play_by_play.py

NBA.com Play-by-Play scraper                            v2 - 2025-06-16
-----------------------------------------------------------------------
Downloads the official play-by-play feed from data.nba.com for a given game_id.
This is NBA.com's primary play-by-play data source.

Usage examples
--------------
  # Via capture tool (recommended for data collection):
   python tools/fixtures/capture.py nbac_play_by_play \
      --game_id 0022400561 \
      --gamedate 20250115
      --debug

  # Direct CLI execution:
  python scrapers/nbacom/nbac_play_by_play.py --game_id 0022400987 --debug

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
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_play_by_play.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

# Notification system imports
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger("scraper_base")


class GetNbaComPlayByPlay(ScraperBase, ScraperFlaskMixin):
    """Downloads official play-by-play JSON from NBA.com CDN."""

    # Flask Mixin Configuration
    scraper_name = "nbac_play_by_play"
    required_params = ["game_id", "gamedate"]
    optional_params = {
        "api_key": None,  # Falls back to env var if needed
    }

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #
    required_opts = ["game_id", "gamedate"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = "data"

    GCS_PATH_KEY = "nba_com_play_by_play"
    exporters = [
        {
            "type": "gcs",
            #"key": "nba/play-by-play/%(season)s/%(game_id)s.json",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/nbacom_play_by_play_%(game_id)s.json",
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
    # Additional opts helper (derive season)
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        
        # Add timestamp for exports
        now = datetime.now(timezone.utc)
        self.opts["time"] = now.strftime("%H-%M-%S")
        
        # Derive season from game_id (e.g., "0022400987" -> "2024-25")
        gid = self.opts["game_id"]
        try:
            yr_prefix = 2000 + int(gid[3:5])
            self.opts["season"] = f"{yr_prefix}-{(yr_prefix + 1) % 100:02d}"
        except (ValueError, IndexError):
            raise DownloadDataException("Invalid game_id format for season derivation")

    # ------------------------------------------------------------------ #
    # URL builder
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        gid = self.opts["game_id"]
        self.url = (
            f"https://cdn.nba.com/static/json/liveData/playbyplay/"
            f"playbyplay_{gid}.json"
        )
        logger.info("PBP URL: %s", self.url)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """Validate basic play-by-play response structure"""
        try:
            if not isinstance(self.decoded_data, dict):
                error_msg = "PBP response is not a valid JSON object"
                logger.error("%s for game_id %s", error_msg, self.opts["game_id"])
                try:
                    notify_error(
                        title="NBA.com Play-by-Play Invalid Response",
                        message=f"Response is not a valid JSON object for game_id {self.opts['game_id']}",
                        details={
                            'game_id': self.opts['game_id'],
                            'gamedate': self.opts.get('gamedate'),
                            'season': self.opts.get('season'),
                            'response_type': type(self.decoded_data).__name__,
                            'url': self.url
                        },
                        processor_name="NBA.com Play-by-Play Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
            game = self.decoded_data.get("game")
            if game is None:
                error_msg = "PBP JSON missing 'game' key"
                logger.error("%s for game_id %s", error_msg, self.opts["game_id"])
                try:
                    notify_error(
                        title="NBA.com Play-by-Play Missing Game Key",
                        message=f"Response missing 'game' key for game_id {self.opts['game_id']}",
                        details={
                            'game_id': self.opts['game_id'],
                            'gamedate': self.opts.get('gamedate'),
                            'season': self.opts.get('season'),
                            'response_keys': list(self.decoded_data.keys()),
                            'url': self.url
                        },
                        processor_name="NBA.com Play-by-Play Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
            if "actions" not in game:
                error_msg = "PBP JSON missing game.actions array"
                logger.error("%s for game_id %s", error_msg, self.opts["game_id"])
                try:
                    notify_error(
                        title="NBA.com Play-by-Play Missing Actions",
                        message=f"Response missing game.actions array for game_id {self.opts['game_id']}",
                        details={
                            'game_id': self.opts['game_id'],
                            'gamedate': self.opts.get('gamedate'),
                            'season': self.opts.get('season'),
                            'game_keys': list(game.keys()),
                            'url': self.url
                        },
                        processor_name="NBA.com Play-by-Play Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
            actions = game["actions"]
            if not isinstance(actions, list):
                error_msg = "game.actions is not a list"
                logger.error("%s for game_id %s", error_msg, self.opts["game_id"])
                try:
                    notify_error(
                        title="NBA.com Play-by-Play Invalid Actions Type",
                        message=f"game.actions is not a list for game_id {self.opts['game_id']}",
                        details={
                            'game_id': self.opts['game_id'],
                            'gamedate': self.opts.get('gamedate'),
                            'season': self.opts.get('season'),
                            'actions_type': type(actions).__name__,
                            'url': self.url
                        },
                        processor_name="NBA.com Play-by-Play Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
            if len(actions) == 0:
                error_msg = "game.actions is empty - no play-by-play events found"
                logger.error("%s for game_id %s", error_msg, self.opts["game_id"])
                try:
                    notify_error(
                        title="NBA.com Play-by-Play No Events",
                        message=f"No play-by-play events found for game_id {self.opts['game_id']}",
                        details={
                            'game_id': self.opts['game_id'],
                            'gamedate': self.opts.get('gamedate'),
                            'season': self.opts.get('season'),
                            'url': self.url
                        },
                        processor_name="NBA.com Play-by-Play Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
                
        except DownloadDataException:
            # Already handled and notified above
            raise
        except Exception as e:
            logger.error("Unexpected validation error for game_id %s: %s", self.opts["game_id"], e)
            try:
                notify_error(
                    title="NBA.com Play-by-Play Validation Error",
                    message=f"Unexpected validation error for game_id {self.opts['game_id']}: {str(e)}",
                    details={
                        'game_id': self.opts['game_id'],
                        'gamedate': self.opts.get('gamedate'),
                        'season': self.opts.get('season'),
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'url': self.url
                    },
                    processor_name="NBA.com Play-by-Play Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Validation failed: {e}") from e

    # ------------------------------------------------------------------ #
    # Enhanced validation for production use
    # ------------------------------------------------------------------ #
    def validate_pbp_data(self) -> None:
        """
        Production validation for play-by-play data quality.
        """
        try:
            game = self.data["playByPlay"]["game"]
            actions = game["actions"]
            
            # 1. REASONABLE EVENT COUNT CHECK
            event_count = len(actions)
            min_events = int(os.environ.get('PBP_MIN_EVENTS', '50'))
            max_events = int(os.environ.get('PBP_MAX_EVENTS', '1000'))
            
            if event_count < min_events:
                error_msg = f"Suspiciously low event count: {event_count} (expected {min_events}-{max_events})"
                logger.error("%s for game_id %s", error_msg, self.opts["game_id"])
                try:
                    notify_error(
                        title="NBA.com Play-by-Play Low Event Count",
                        message=f"Suspiciously low event count ({event_count}) for game_id {self.opts['game_id']}",
                        details={
                            'game_id': self.opts['game_id'],
                            'gamedate': self.opts.get('gamedate'),
                            'season': self.opts.get('season'),
                            'event_count': event_count,
                            'min_threshold': min_events,
                            'max_threshold': max_events
                        },
                        processor_name="NBA.com Play-by-Play Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
            elif event_count > max_events:
                error_msg = f"Suspiciously high event count: {event_count} (expected {min_events}-{max_events})"
                logger.error("%s for game_id %s", error_msg, self.opts["game_id"])
                try:
                    notify_error(
                        title="NBA.com Play-by-Play High Event Count",
                        message=f"Suspiciously high event count ({event_count}) for game_id {self.opts['game_id']}",
                        details={
                            'game_id': self.opts['game_id'],
                            'gamedate': self.opts.get('gamedate'),
                            'season': self.opts.get('season'),
                            'event_count': event_count,
                            'min_threshold': min_events,
                            'max_threshold': max_events
                        },
                        processor_name="NBA.com Play-by-Play Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
            
            # 2. BASIC DATA STRUCTURE VALIDATION  
            required_game_keys = ['gameId', 'actions']
            for key in required_game_keys:
                if key not in game:
                    error_msg = f"Missing required game key: {key}"
                    logger.error("%s for game_id %s", error_msg, self.opts["game_id"])
                    try:
                        notify_error(
                            title="NBA.com Play-by-Play Missing Required Key",
                            message=f"Missing required game key '{key}' for game_id {self.opts['game_id']}",
                            details={
                                'game_id': self.opts['game_id'],
                                'gamedate': self.opts.get('gamedate'),
                                'season': self.opts.get('season'),
                                'missing_key': key,
                                'game_keys': list(game.keys())
                            },
                            processor_name="NBA.com Play-by-Play Scraper"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                    raise DownloadDataException(error_msg)
            
            # 3. SAMPLE ACTION VALIDATION (check first few events)
            sample_size = min(10, len(actions))
            for i, action in enumerate(actions[:sample_size]):
                if not isinstance(action, dict):
                    error_msg = f"Action {i} is not a dict: {type(action)}"
                    logger.error("%s for game_id %s", error_msg, self.opts["game_id"])
                    try:
                        notify_error(
                            title="NBA.com Play-by-Play Invalid Action Type",
                            message=f"Action {i} is not a dict for game_id {self.opts['game_id']}",
                            details={
                                'game_id': self.opts['game_id'],
                                'gamedate': self.opts.get('gamedate'),
                                'season': self.opts.get('season'),
                                'action_index': i,
                                'action_type': type(action).__name__
                            },
                            processor_name="NBA.com Play-by-Play Scraper"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                    raise DownloadDataException(error_msg)
                    
                # Check for essential action fields
                if 'actionType' not in action:
                    logger.warning(f"Action {i} missing actionType for game_id {self.opts['game_id']}: {action}")
                    # This is a warning, not an error - some actions may legitimately not have this
            
            # 4. GAME ID CONSISTENCY
            game_id_from_data = game.get('gameId', '')
            expected_game_id = self.opts['game_id']
            if game_id_from_data != expected_game_id:
                logger.warning("Game ID mismatch for game_id %s: expected %s, got %s", 
                             self.opts['game_id'], expected_game_id, game_id_from_data)
                try:
                    notify_warning(
                        title="NBA.com Play-by-Play Game ID Mismatch",
                        message=f"Game ID mismatch for {self.opts['game_id']}: expected {expected_game_id}, got {game_id_from_data}",
                        details={
                            'game_id': self.opts['game_id'],
                            'gamedate': self.opts.get('gamedate'),
                            'season': self.opts.get('season'),
                            'expected_game_id': expected_game_id,
                            'actual_game_id': game_id_from_data
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            logger.info(f"✅ PBP validation passed: {event_count} events for game_id {self.opts['game_id']}")
            
        except DownloadDataException:
            # Already handled and notified above
            raise
        except KeyError as e:
            logger.error("Missing expected key during validation for game_id %s: %s", self.opts["game_id"], e)
            try:
                notify_error(
                    title="NBA.com Play-by-Play Data Validation Failed",
                    message=f"Missing expected key during validation for game_id {self.opts['game_id']}: {str(e)}",
                    details={
                        'game_id': self.opts['game_id'],
                        'gamedate': self.opts.get('gamedate'),
                        'season': self.opts.get('season'),
                        'missing_key': str(e),
                        'error_type': 'KeyError'
                    },
                    processor_name="NBA.com Play-by-Play Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Data validation failed: missing key {e}") from e
        except Exception as e:
            logger.error("Unexpected validation error for game_id %s: %s", self.opts["game_id"], e)
            try:
                notify_error(
                    title="NBA.com Play-by-Play Data Validation Error",
                    message=f"Unexpected validation error for game_id {self.opts['game_id']}: {str(e)}",
                    details={
                        'game_id': self.opts['game_id'],
                        'gamedate': self.opts.get('gamedate'),
                        'season': self.opts.get('season'),
                        'error': str(e),
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Play-by-Play Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Data validation failed: {e}") from e

    # ------------------------------------------------------------------ #
    # Transform (wrap with metadata)
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        """Transform play-by-play data with metadata"""
        try:
            ts = datetime.now(timezone.utc).isoformat()
            actions = self.decoded_data["game"]["actions"]

            self.data: Dict[str, Any] = {
                "metadata": {
                    "game_id": self.opts["game_id"],
                    "season": self.opts["season"],
                    "fetchedUtc": ts,
                    "eventCount": len(actions),
                },
                "playByPlay": self.decoded_data,
            }
            
            # Add production validation
            self.validate_pbp_data()
            
        except KeyError as e:
            logger.error("Transformation failed - missing key %s for game_id %s", e, self.opts["game_id"])
            try:
                notify_error(
                    title="NBA.com Play-by-Play Transformation Failed",
                    message=f"Data transformation failed - missing expected key for game_id {self.opts['game_id']}: {str(e)}",
                    details={
                        'game_id': self.opts['game_id'],
                        'gamedate': self.opts.get('gamedate'),
                        'season': self.opts.get('season'),
                        'missing_key': str(e),
                        'error_type': 'KeyError'
                    },
                    processor_name="NBA.com Play-by-Play Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Transformation failed: missing key {e}") from e
        except Exception as e:
            logger.error("Transformation failed for game_id %s: %s", self.opts["game_id"], e)
            try:
                notify_error(
                    title="NBA.com Play-by-Play Transformation Error",
                    message=f"Unexpected transformation error for game_id {self.opts['game_id']}: {str(e)}",
                    details={
                        'game_id': self.opts['game_id'],
                        'gamedate': self.opts.get('gamedate'),
                        'season': self.opts.get('season'),
                        'error': str(e),
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Play-by-Play Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"Transformation failed: {e}") from e

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
            "game_id": self.opts["game_id"],
            "game_date": self.opts.get("date"),
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
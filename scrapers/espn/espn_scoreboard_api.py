"""
ESPN NBA Scoreboard scraper                           v2 - 2025-06-16
--------------------------------------------------------------------
Pulls the daily scoreboard JSON from ESPN's public API and converts it
into a lightweight game list, suitable for job fan-out:

    [
        {
            "gameId": "401585725",
            "statusId": 2,
            "state": "in",          # pre / in / post
            "status": "2nd Quarter",
            "startTime": "2025-01-14T03:00Z",
            "teams": [
                {"teamId": "2",  "abbreviation": "BOS", "score": "47", ...},
                {"teamId": "17", "abbreviation": "LAL", "score": "45", ...}
            ]
        },
        ...
    ]

Improvements v2
---------------
- header_profile = "espn"  -> one-line UA updates if ESPN blocks a string
- Strict ISO-8601 timestamp
- Adds state & statusId
- Uses new _common_requests_kwargs() helper in ScraperBase

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py espn_scoreboard_api \
      --gamedate 20250214 \
      --debug

  # Direct CLI execution:
  python scrapers/espn/espn_scoreboard_api.py --gamedate 20250214 --debug

  # Flask web service:
  python scrapers/espn/espn_scoreboard_api.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.espn.espn_scoreboard_api
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/espn/espn_scoreboard_api.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

# Notification system imports
try:
    from shared.utils.notification_system import (
        notify_error,
        notify_warning,
        notify_info
    )
except ImportError:
    # Fallback if notification system not available
    def notify_error(*args, **kwargs):
        pass
    def notify_warning(*args, **kwargs,
    processor_name=self.__class__.__name__
    ):
        pass
    def notify_info(*args, **kwargs,
    processor_name=self.__class__.__name__
    ):
        pass

# Schedule service for season type detection
try:
    from shared.utils.schedule import NBAScheduleService
except ImportError:
    NBAScheduleService = None

logger = logging.getLogger("scraper_base")


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class GetEspnScoreboard(ScraperBase, ScraperFlaskMixin):
    """
    ESPN scoreboard scraper (JSON API).
    """

    # Flask Mixin Configuration
    scraper_name = "espn_scoreboard_api"
    required_params = ["gamedate"]  # gamedate is required (YYYYMMDD format)
    optional_params = {}

    # Original scraper config
    required_opts: List[str] = ["gamedate"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = "espn"

    # Class-level schedule service (lazy initialization)
    _schedule_service = None

    @classmethod
    def _get_schedule_service(cls):
        """Get or create the schedule service instance."""
        if NBAScheduleService is None:
            return None
        if cls._schedule_service is None:
            cls._schedule_service = NBAScheduleService()
        return cls._schedule_service

    def _detect_season_type(self, game_date: str) -> str:
        """
        Auto-detect season type from schedule database.

        Args:
            game_date: Date string in YYYYMMDD format

        Returns:
            Season type string (e.g., "Regular Season", "Playoffs", "All Star")
        """
        try:
            schedule = self._get_schedule_service()
            if schedule is None:
                return "Regular Season"

            # Convert YYYYMMDD to YYYY-MM-DD
            if len(game_date) == 8:
                formatted_date = f"{game_date[0:4]}-{game_date[4:6]}-{game_date[6:8]}"
            else:
                formatted_date = game_date

            season_type = schedule.get_season_type_for_date(formatted_date)
            return season_type
        except Exception as e:
            logger.warning("Failed to detect season type from schedule for %s: %s. "
                          "Falling back to Regular Season.", game_date, e)
            return "Regular Season"

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "espn_scoreboard"
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/espn_scoreboard_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        # ---------- raw JSON fixture (offline tests) ----------
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",  # FIXED: Use run_id instead of gamedate
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        # ---------- golden snapshot (parsed DATA) ----------
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",  # FIXED: Use run_id instead of gamedate
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL & HEADERS
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        base = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
        self.url = f"{base}?dates={self.opts['gamedate']}"
        logger.info("Resolved ESPN scoreboard URL: %s", self.url)

    # No set_headers needed - ScraperBase injects via header_profile

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        try:
            if not isinstance(self.decoded_data, dict):
                error_msg = "Scoreboard response is not JSON dict."
                
                # Send error notification
                try:
                    notify_error(
                        title="ESPN Scoreboard Validation Failed",
                        message=f"Invalid response format for {self.opts['gamedate']}: {error_msg}",
                        details={
                            'scraper': 'espn_scoreboard_api',
                            'gamedate': self.opts['gamedate'],
                            'error': error_msg,
                            'response_type': type(self.decoded_data).__name__
                        },
                        processor_name="ESPN Scoreboard Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                raise ValueError(error_msg)
                
            if "events" not in self.decoded_data:
                error_msg = "'events' key missing in JSON."
                
                # Send error notification
                try:
                    notify_error(
                        title="ESPN Scoreboard Data Missing",
                        message=f"Missing 'events' key for {self.opts['gamedate']}",
                        details={
                            'scraper': 'espn_scoreboard_api',
                            'gamedate': self.opts['gamedate'],
                            'error': error_msg,
                            'available_keys': list(self.decoded_data.keys()) if isinstance(self.decoded_data, dict) else []
                        },
                        processor_name="ESPN Scoreboard Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                raise ValueError(error_msg)
                
        except Exception as e:
            # Re-raise the original exception
            raise

    # ------------------------------------------------------------------ #
    # Transform -> self.data
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        # Auto-detect season type for proper game categorization
        season_type = self._detect_season_type(self.opts["gamedate"])
        logger.info(f"Auto-detected season_type: {season_type} for date {self.opts['gamedate']}")

        # Log info if this is an All-Star date (API should handle correctly)
        if season_type == "All Star":
            logger.info(f"Scraping All-Star games on {self.opts['gamedate']} - "
                       f"ESPN API should return All-Star game data correctly")

        events: List[dict] = self.decoded_data.get("events", [])
        logger.info("Found %d events for %s", len(events), self.opts["gamedate"])

        # Warn if no games found (might be expected on some dates, but worth noting)
        if len(events) == 0:
            try:
                notify_warning(
                    title="ESPN Scoreboard: No Games Found",
                    message=f"No games found for {self.opts['gamedate']}",
                    details={
                        'scraper': 'espn_scoreboard_api',
                        'gamedate': self.opts['gamedate'],
                        'event_count': 0
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

        games: List[Dict[str, Any]] = []
        for event in events:
            comp = (event.get("competitions") or [{}])[0]
            status_blob = comp.get("status", {}).get("type", {})
            teams_info: List[Dict[str, Any]] = []
            for c in comp.get("competitors", []):
                tm = c.get("team", {})
                teams_info.append(
                    {
                        "teamId": tm.get("id"),
                        "displayName": tm.get("displayName"),
                        "abbreviation": tm.get("abbreviation"),
                        "score": c.get("score"),
                        "winner": c.get("winner", False),
                        "homeAway": c.get("homeAway"),
                    }
                )

            games.append(
                {
                    "gameId": comp.get("id"),
                    "statusId": status_blob.get("id"),
                    "state": status_blob.get("state"),  # pre / in / post
                    "status": status_blob.get("description"),
                    "startTime": comp.get("date"),
                    "teams": teams_info,
                }
            )

        self.data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gamedate": self.opts["gamedate"],
            "season_type": season_type,
            "gameCount": len(games),
            "games": games,
        }

        # Send success notification for successful scraping
        try:
            notify_info(
                title="ESPN Scoreboard Scraped Successfully",
                message=f"Successfully scraped {len(games)} games for {self.opts['gamedate']}",
                details={
                    'scraper': 'espn_scoreboard_api',
                    'gamedate': self.opts['gamedate'],
                    'game_count': len(games)
                },
                processor_name=self.__class__.__name__
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")

    # ------------------------------------------------------------------ #
    # Stats line
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"gamedate": self.opts["gamedate"], "gameCount": self.data.get("gameCount", 0)}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetEspnScoreboard)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetEspnScoreboard.create_cli_and_flask_main()
    main()
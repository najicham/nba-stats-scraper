# scrapers/oddsapi/oddsa_team_players.py
"""
odds_api_team_players.py
Scraper for the (undocumented) The-Odds-API v4 endpoint:

  GET /v4/sports/{sport}/participants/{participantId}/players

Returns the current roster for a given team / participant.

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py oddsa_team_players \
      --sport basketball_nba \
      --participant_id team-1234 \
      --debug

  # Direct CLI execution:
  python scrapers/oddsapi/oddsa_team_players.py \
      --sport basketball_nba \
      --participant_id team-1234 \
      --debug

  # Flask web service:
  python scrapers/oddsapi/oddsa_team_players.py --serve --debug
"""

from __future__ import annotations

import os
import logging
import sys
from urllib.parse import urlencode, quote_plus
from typing import Any, Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.oddsapi.oddsa_team_players
    from ..scraper_base import ScraperBase, ExportMode
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/oddsapi/oddsa_team_players.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import ScraperBase, ExportMode
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

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class GetOddsApiTeamPlayers(ScraperBase, ScraperFlaskMixin):
    """
    Required opts:
      • sport          - e.g. basketball_nba
      • participant_id  - Odds-API team / participant key

    Optional opts:
      • api_key - falls back to env ODDS_API_KEY
    """

    # Flask Mixin Configuration
    scraper_name = "oddsa_team_players"
    required_params = ["sport", "participant_id"]
    optional_params = {
        "api_key": None,  # Falls back to env ODDS_API_KEY
    }

    required_opts = ["sport", "participant_id"]
    proxy_enabled = False
    browser_enabled = False

    # ------------------------------------------------------------------ #
    # Exporters                                                          #
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "odds_api_team_players"
    exporters = [
        {   # RAW for prod / archival
            "type": "gcs",
            # "key": (
            #     "oddsapi/team-players/%(sport)s/%(participant_id)s/"
            #     "%(run_id)s.raw.json"
            # ),
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {   # Pretty JSON for dev & capture
            "type": "file",
            "filename": "/tmp/oddsapi_team_players_%(participant_id)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "capture", "test"],
        },
        # Add capture group exporters
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DECODED,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT_TMPL = (
        "https://api.the-odds-api.com/v4/sports/"
        "{sport}/participants/{participantId}/players"
    )

    def set_url(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("ODDS_API_KEY")
        if not api_key:
            error_msg = "Missing api_key and env var ODDS_API_KEY not set."
            
            # Send critical notification - API key missing prevents all scraping
            try:
                notify_error(
                    title="Odds API Key Missing",
                    message="Cannot scrape team players - API key not configured",
                    details={
                        'scraper': 'oddsa_team_players',
                        'sport': self.opts.get('sport', 'unknown'),
                        'participant_id': self.opts.get('participant_id', 'unknown'),
                        'error': 'ODDS_API_KEY environment variable not set'
                    },
                    processor_name="Odds API Team Players Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise DownloadDataException(error_msg)

        base = self._API_ROOT_TMPL.format(
            sport=self.opts["sport"],
            # Belt-and-suspenders: ensure any slashes in participantId are encoded
            participantId=quote_plus(self.opts["participant_id"]),
        )
        self.url = f"{base}?{urlencode({'apiKey': api_key})}"
        logger.info("Odds-API Team-Players URL: %s", self.url)

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}

    # ------------------------------------------------------------------ #
    # HTTP status handling                                               #
    # ------------------------------------------------------------------ #
    def check_download_status(self) -> None:
        """
        Consider 200 and 204 as successful.
        """
        if self.raw_response.status_code in (200, 204):
            # 204 is expected for teams with no roster data
            if self.raw_response.status_code == 204:
                logger.info("204 response - no roster data for participant %s", 
                           self.opts.get("participant_id"))
            return
        
        # Non-success status code - send error notification
        status_code = self.raw_response.status_code
        try:
            notify_error(
                title="Odds API HTTP Error",
                message=f"Team players scraping failed with HTTP {status_code}",
                details={
                    'scraper': 'oddsa_team_players',
                    'sport': self.opts.get('sport', 'unknown'),
                    'participant_id': self.opts.get('participant_id', 'unknown'),
                    'status_code': status_code,
                    'response_text': self.raw_response.text[:500] if hasattr(self.raw_response, 'text') else 'N/A'
                },
                processor_name="Odds API Team Players Scraper"
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")
        
        super().check_download_status()

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            error_msg = self.decoded_data['message']
            
            # API returned an error message
            try:
                notify_error(
                    title="Odds API Error Response",
                    message=f"Team players API returned error: {error_msg}",
                    details={
                        'scraper': 'oddsa_team_players',
                        'sport': self.opts.get('sport', 'unknown'),
                        'participant_id': self.opts.get('participant_id', 'unknown'),
                        'api_error': error_msg
                    },
                    processor_name="Odds API Team Players Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise DownloadDataException(f"API error: {error_msg}")

        if not isinstance(self.decoded_data, (list, dict)):
            # Unexpected data format
            try:
                notify_error(
                    title="Odds API Invalid Response Format",
                    message="Team players API returned unexpected data format",
                    details={
                        'scraper': 'oddsa_team_players',
                        'sport': self.opts.get('sport', 'unknown'),
                        'participant_id': self.opts.get('participant_id', 'unknown'),
                        'received_type': type(self.decoded_data).__name__,
                        'expected_types': 'list or dict'
                    },
                    processor_name="Odds API Team Players Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise DownloadDataException("Expected list or dict payload.")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        players: List[Dict[str, Any]]
        if isinstance(self.decoded_data, list):
            players = self.decoded_data
        elif isinstance(self.decoded_data, dict):
            # Some back-end variants wrap the list under 'players'
            players = self.decoded_data.get("players", [])
        else:
            players = []

        self.data = {
            "sport": self.opts["sport"],
            "participantId": self.opts["participant_id"],
            "rowCount": len(players),
            "players": players,
        }
        
        # Check for no players returned
        if len(players) == 0:
            try:
                notify_warning(
                    title="No Team Players Available",
                    message="Odds API returned zero players for team",
                    details={
                        'scraper': 'oddsa_team_players',
                        'sport': self.opts.get('sport', 'unknown'),
                        'participant_id': self.opts.get('participant_id', 'unknown'),
                        'note': 'Team may not exist or roster data not available yet'
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        else:
            # Success! Send info notification with metrics
            try:
                notify_info(
                    title="Team Players Scraped Successfully",
                    message=f"Retrieved {len(players)} players for team roster",
                    details={
                        'scraper': 'oddsa_team_players',
                        'sport': self.opts.get('sport', 'unknown'),
                        'participant_id': self.opts.get('participant_id', 'unknown'),
                        'player_count': len(players)
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        
        logger.info(
            "Fetched %d players for participantId=%s",
            len(players),
            self.opts["participant_id"],
        )

    # ------------------------------------------------------------------ #
    # Conditional save                                                   #
    # ------------------------------------------------------------------ #
    def should_save_data(self) -> bool:
        return bool(self.data.get("rowCount"))

    # ------------------------------------------------------------------ #
    # Stats line                                                         #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0),
            "sport": self.opts.get("sport"),
            "participantId": self.opts.get("participant_id"),
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetOddsApiTeamPlayers)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetOddsApiTeamPlayers.create_cli_and_flask_main()
    main()
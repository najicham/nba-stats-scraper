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
      --participantId team-1234 \
      --debug

  # Direct CLI execution:
  python scrapers/oddsapi/oddsa_team_players.py \
      --sport basketball_nba \
      --participantId team-1234 \
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
except ImportError:
    # Direct execution: python scrapers/oddsapi/oddsa_team_players.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import ScraperBase, ExportMode
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class GetOddsApiTeamPlayers(ScraperBase, ScraperFlaskMixin):
    """
    Required opts:
      • sport          - e.g. basketball_nba
      • participantId  - Odds-API team / participant key

    Optional opts:
      • apiKey - falls back to env ODDS_API_KEY
    """

    # Flask Mixin Configuration
    scraper_name = "oddsa_team_players"
    required_params = ["sport", "participantId"]
    optional_params = {
        "apiKey": None,  # Falls back to env ODDS_API_KEY
    }

    required_opts = ["sport", "participantId"]
    proxy_enabled = False
    browser_enabled = False

    # ------------------------------------------------------------------ #
    # Exporters                                                          #
    # ------------------------------------------------------------------ #
    exporters = [
        {   # RAW for prod / archival
            "type": "gcs",
            "key": (
                "oddsapi/team-players/%(sport)s/%(participantId)s/"
                "%(run_id)s.raw.json"
            ),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {   # Pretty JSON for dev & capture
            "type": "file",
            "filename": "/tmp/oddsapi_team_players_%(participantId)s.json",
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
        api_key = self.opts.get("apiKey") or os.getenv("ODDS_API_KEY")
        if not api_key:
            raise DownloadDataException(
                "Missing apiKey and env var ODDS_API_KEY not set."
            )

        base = self._API_ROOT_TMPL.format(
            sport=self.opts["sport"],
            # Belt-and-suspenders: ensure any slashes in participantId are encoded
            participantId=quote_plus(self.opts["participantId"]),
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
            return
        super().check_download_status()

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            raise DownloadDataException(f"API error: {self.decoded_data['message']}")

        if not isinstance(self.decoded_data, (list, dict)):
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
            "participantId": self.opts["participantId"],
            "rowCount": len(players),
            "players": players,
        }
        logger.info(
            "Fetched %d players for participantId=%s",
            len(players),
            self.opts["participantId"],
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
            "participantId": self.opts.get("participantId"),
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
    
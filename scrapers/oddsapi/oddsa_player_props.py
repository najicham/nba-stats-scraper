# scrapers/oddsapi/oddsa_player_props.py
"""
odds_api_current_event_odds.py
Scraper for The-Odds-API v4 **current event odds** endpoint.

Docs:
  https://the-odds-api.com/liveapi/guides/v4/#get-event-odds

Endpoint:
  GET /v4/sports/{sport}/events/{eventId}/odds

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py oddsa_player_props \
      --event_id 6f0b6f8d8cc9c5bc6375cdee \
      --markets player_points \
      --debug

  # Direct CLI execution:
  python scrapers/oddsapi/oddsa_player_props.py \
      --event_id 6f0b6f8d8cc9c5bc6375cdee \
      --markets player_points \
      --debug

  # Flask web service:
  python scrapers/oddsapi/oddsa_player_props.py --serve --debug
"""

from __future__ import annotations

import os
import logging
import sys
from urllib.parse import urlencode
from typing import Any, Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.oddsapi.oddsa_player_props
    from ..scraper_base import ScraperBase, ExportMode
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
    from ..utils.nba_team_mapper import build_event_teams_suffix
except ImportError:
    # Direct execution: python scrapers/oddsapi/oddsa_player_props.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import ScraperBase, ExportMode
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder
    from scrapers.utils.nba_team_mapper import build_event_teams_suffix

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class GetOddsApiCurrentEventOdds(ScraperBase, ScraperFlaskMixin):
    """
    Required opts:
      • event_id  - Odds-API event ID

    Optional opts (map to query params):
      • sport       - e.g. basketball_nba (defaults to basketball_nba)
      • api_key      - env ODDS_API_KEY fallback
      • markets     - comma-sep (player_points, totals, …) (defaults to player_points)
      • regions     - comma-sep (us, uk, eu, au) (defaults to us)
      • bookmakers  - comma-sep (defaults to draftkings,fanduel)
      • oddsFormat  - american | decimal | fractional
      • dateFormat  - iso | unix
      • teams       - team suffix (e.g., LALDET) - if provided, skips team extraction
    """

    # Flask Mixin Configuration
    scraper_name = "oddsa_player_props"
    required_params = ["event_id"]
    optional_params = {
        "api_key": None,  # Falls back to env ODDS_API_KEY
        "sport": None,  # Defaults to basketball_nba in set_additional_opts
        "markets": None,  # Defaults to player_points in set_additional_opts
        "regions": None,  # Defaults to us in set_additional_opts
        "bookmakers": None,  # Defaults to draftkings,fanduel in set_additional_opts
        "oddsFormat": None,
        "dateFormat": None,
        "teams": None,  # Team suffix for GCS path (optional)
    }

    required_opts = ["event_id"]
    proxy_enabled = False
    browser_enabled = False

    # ------------------------------------------------------------------ #
    # Exporters                                                          #
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "odds_api_player_props"
    exporters = [
        {   # RAW payload for prod / GCS archival
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {   # Pretty JSON for dev & capture
            "type": "file",
            "filename": "/tmp/oddsapi_curr_event_odds_%(event_id)s.json",
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

    def set_additional_opts(self) -> None:
        """Fill season-wide defaults for optional opts."""
        super().set_additional_opts()
        self.opts.setdefault("sport", "basketball_nba")
        self.opts.setdefault("regions", "us")
        self.opts.setdefault("markets", "player_points")
        self.opts.setdefault("bookmakers", "draftkings,fanduel")

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT_TMPL = (
        "https://api.the-odds-api.com/v4/sports/{sport}/events/{eventId}/odds"
    )

    def set_url(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("ODDS_API_KEY")
        if not api_key:
            raise DownloadDataException(
                "Missing api_key and env var ODDS_API_KEY not set."
            )

        base = self._API_ROOT_TMPL.format(
            sport=self.opts["sport"],
            eventId=self.opts["event_id"],
        )

        query: Dict[str, Any] = {
            "apiKey": api_key,
            "markets": self.opts["markets"],
            "regions": self.opts["regions"],
            "bookmakers": self.opts["bookmakers"],
            "oddsFormat": self.opts.get("oddsFormat"),
            "dateFormat": self.opts.get("dateFormat"),
        }
        query = {k: v for k, v in query.items() if v is not None}
        self.url = f"{base}?{urlencode(query, doseq=True)}"
        logger.info("Odds-API Current Event Odds URL: %s", self.url)

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}

    # ------------------------------------------------------------------ #
    # HTTP status handling                                               #
    # ------------------------------------------------------------------ #
    def check_download_status(self) -> None:
        """
        Treat 200 and 204 as success (204 => no markets yet).
        """
        if self.raw_response.status_code in (200, 204):
            return
        super().check_download_status()

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """
        Success is an **object** with bookmakers[], or an empty list/dict if no odds.
        """
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            raise DownloadDataException(f"API error: {self.decoded_data['message']}")

        if not isinstance(self.decoded_data, (dict, list)):
            raise DownloadDataException("Expected dict or list for odds payload.")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        if not self.decoded_data:
            row_count = 0
            bookmakers: List[Dict[str, Any]] = []
            event_data = {}
        elif isinstance(self.decoded_data, list):
            # Some sports return [event] list
            event_data = self.decoded_data[0] if self.decoded_data else {}
            bookmakers = event_data.get("bookmakers", [])
        else:  # dict
            event_data = self.decoded_data
            bookmakers = self.decoded_data.get("bookmakers", [])

        # Count bookmaker × market rows
        row_count = 0
        for bm in bookmakers:
            for mk in bm.get("markets", []):
                row_count += len(mk.get("outcomes", [])) or 1

        # Extract team information and build teams suffix for GCS path
        teams_suffix = self._extract_teams_suffix(event_data)
        if teams_suffix:
            self.opts["teams"] = teams_suffix
            logger.debug("Built teams suffix for GCS path: %s", teams_suffix)

        self.data = {
            "sport": self.opts["sport"],
            "eventId": self.opts["event_id"],
            "markets": self.opts.get("markets", "player_points"),
            "regions": self.opts.get("regions", "us"),
            "rowCount": row_count,
            "odds": self.decoded_data,
        }
        logger.info(
            "Fetched %d bookmaker-market rows for event %s",
            row_count,
            self.opts["event_id"],
        )

    def _extract_teams_suffix(self, event_data: Dict[str, Any]) -> str:
        """
        Extract team information from current event odds data and build teams suffix.
        
        The current event odds endpoint returns event data including team names.
        We use this to build the teams suffix for enhanced GCS paths.
        
        Args:
            event_data: Event data from API response
            
        Returns:
            Teams suffix (e.g., "LALDET") or empty string if teams not found
        """
        # Check if teams suffix was provided directly (from job/external source)
        if self.opts.get("teams"):
            return self.opts["teams"]
        
        try:
            # The current event odds API response includes team information
            # Look for team names in various possible field names
            away_team = (event_data.get("away_team") or 
                        event_data.get("awayTeam") or
                        event_data.get("away") or
                        event_data.get("visitor_team", ""))
                        
            home_team = (event_data.get("home_team") or 
                        event_data.get("homeTeam") or
                        event_data.get("home", ""))
            
            # Some APIs nest team info under team objects
            if not away_team or not home_team:
                away_team_obj = event_data.get("away_team_obj", {}) or event_data.get("awayTeam_obj", {})
                home_team_obj = event_data.get("home_team_obj", {}) or event_data.get("homeTeam_obj", {})
                
                if away_team_obj:
                    away_team = away_team_obj.get("name", away_team_obj.get("title", ""))
                if home_team_obj:
                    home_team = home_team_obj.get("name", home_team_obj.get("title", ""))
            
            if away_team and home_team:
                # Build teams suffix using the utility
                teams_suffix = build_event_teams_suffix({
                    "away_team": away_team,
                    "home_team": home_team
                })
                logger.debug("Extracted teams from current API response: %s @ %s -> %s", 
                           away_team, home_team, teams_suffix)
                return teams_suffix
            else:
                logger.warning("Could not extract team information from current event odds data")
                logger.debug("Event data keys: %s", list(event_data.keys()) if event_data else [])
                return ""
                
        except Exception as e:
            logger.warning("Error extracting teams suffix: %s", e)
            return ""

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
            "eventId": self.opts.get("event_id"),
            "markets": self.opts.get("markets"),
            "regions": self.opts.get("regions"),
            "teams": self.opts.get("teams", ""),  # Include teams suffix in stats
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetOddsApiCurrentEventOdds)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetOddsApiCurrentEventOdds.create_cli_and_flask_main()
    main()
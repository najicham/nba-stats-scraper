"""
odds_api_team_players.py
Scraper for the (undocumented) The-Odds-API v4 endpoint:

  GET /v4/sports/{sport}/participants/{participantId}/players

Returns the current roster for a given team / participant.

python -m scrapers.oddsapi.odds_api_team_players \
    --sport=basketball_nba \
    --participantId=team-1234 \
    --group=dev --debug

"""

from __future__ import annotations

import os
import logging
from urllib.parse import urlencode, quote_plus
from typing import Any, Dict, List

from scrapers.scraper_base import ScraperBase, ExportMode
from scrapers.utils.exceptions import DownloadDataException

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class GetOddsApiTeamPlayers(ScraperBase):
    """
    Required opts:
      • sport          - e.g. basketball_nba
      • participantId  - Odds-API team / participant key

    Optional opts:
      • apiKey - falls back to env ODDS_API_KEY
    """

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
# Google Cloud Function entry point                                           #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    from dotenv import load_dotenv

    load_dotenv()

    opts = {
        "sport": request.args.get("sport", "basketball_nba"),
        "participantId": request.args["participantId"],
        "apiKey": request.args.get("apiKey"),  # optional - env fallback
        "group": request.args.get("group", "prod"),
    }
    GetOddsApiTeamPlayers().run(opts)
    return (
        f"Odds-API team-players scrape complete ({opts['participantId']})",
        200,
    )


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Scrape The-Odds-API players list for one team"
    )
    parser.add_argument("--sport", default="basketball_nba")
    parser.add_argument("--participantId", required=True)
    parser.add_argument("--apiKey", help="Optional - env ODDS_API_KEY fallback")
    parser.add_argument("--group", default="dev")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    GetOddsApiTeamPlayers().run(vars(args))

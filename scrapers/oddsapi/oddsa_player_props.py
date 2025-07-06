"""
odds_api_current_event_odds.py
Scraper for The-Odds-API v4 **current event odds** endpoint.

Docs:
  https://the-odds-api.com/liveapi/guides/v4/#get-event-odds

Endpoint:
  GET /v4/sports/{sport}/events/{eventId}/odds

python -m scrapers.oddsapi.odds_api_current_event_odds \
    --sport=basketball_nba \
    --eventId=6f0b6f8d8cc9c5bc6375cdee \
    --markets=player_points \
    --regions=us \
    --group=dev --debug

"""

from __future__ import annotations

import os
import logging
from urllib.parse import urlencode
from typing import Any, Dict, List

from scrapers.scraper_base import ScraperBase, ExportMode
from scrapers.utils.exceptions import DownloadDataException

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class GetOddsApiCurrentEventOdds(ScraperBase):
    """
    Required opts:
      • sport    - e.g. basketball_nba
      • eventId  - Odds-API event ID

    Optional opts (map to query params):
      • apiKey      - env ODDS_API_KEY fallback
      • markets     - comma-sep (player_points, totals, …)
      • regions     - comma-sep (us, uk, eu, au)
      • oddsFormat  - american | decimal | fractional
      • dateFormat  - iso | unix
    """

    # required_opts = ["sport", "eventId"]
    required_opts = ["eventId"]
    proxy_enabled = False
    browser_enabled = False

    # ------------------------------------------------------------------ #
    # Exporters                                                          #
    # ------------------------------------------------------------------ #
    exporters = [
        {   # RAW payload for prod / GCS archival
            "type": "gcs",
            "key": (
                "oddsapi/event-odds/current/%(sport)s/%(eventId)s/"
                "%(run_id)s.raw.json"
            ),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {   # Pretty JSON for dev & capture
            "type": "file",
            "filename": "/tmp/oddsapi_curr_event_odds_%(eventId)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "capture", "test"],
        },
    ]


    def set_additional_opts(self) -> None:
        """Fill season-wide defaults for optional opts."""
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
        api_key = self.opts.get("apiKey") or os.getenv("ODDS_API_KEY")
        if not api_key:
            raise DownloadDataException(
                "Missing apiKey and env var ODDS_API_KEY not set."
            )

        base = self._API_ROOT_TMPL.format(
            sport=self.opts["sport"],
            eventId=self.opts["eventId"],
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
        elif isinstance(self.decoded_data, list):
            # Some sports return [event] list
            bookmakers = self.decoded_data[0].get("bookmakers", []) if self.decoded_data else []
        else:  # dict
            bookmakers = self.decoded_data.get("bookmakers", [])

        # Count bookmaker × market rows
        row_count = 0
        for bm in bookmakers:
            for mk in bm.get("markets", []):
                row_count += len(mk.get("outcomes", [])) or 1

        self.data = {
            "sport": self.opts["sport"],
            "eventId": self.opts["eventId"],
            "markets": self.opts.get("markets", "player_points"),
            "regions": self.opts.get("regions", "us"),
            "rowCount": row_count,
            "odds": self.decoded_data,
        }
        logger.info(
            "Fetched %d bookmaker-market rows for event %s",
            row_count,
            self.opts["eventId"],
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
            "eventId": self.opts.get("eventId"),
            "markets": self.opts.get("markets"),
            "regions": self.opts.get("regions"),
        }


# --------------------------------------------------------------------------- #
# Google Cloud Function entry point                                           #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    from dotenv import load_dotenv

    load_dotenv()

    opts = {
        "sport": request.args.get("sport", "basketball_nba"),
        "eventId": request.args["eventId"],
        "apiKey": request.args.get("apiKey"),  # optional - env fallback
        "markets": request.args.get("markets", "player_points"),
        "regions": request.args.get("regions", "us"),
        "oddsFormat": request.args.get("oddsFormat"),
        "dateFormat": request.args.get("dateFormat"),
        "group": request.args.get("group", "prod"),
    }
    GetOddsApiCurrentEventOdds().run(opts)
    return (
        f"Odds-API current event-odds scrape complete ({opts['eventId']})",
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
        description="Scrape The-Odds-API current odds for one event"
    )
    parser.add_argument("--sport", default="basketball_nba")
    parser.add_argument("--eventId", required=True)
    parser.add_argument("--markets", default="player_points")
    parser.add_argument("--regions", default="us")
    parser.add_argument("--oddsFormat", choices=["american", "decimal", "fractional"])
    parser.add_argument("--dateFormat", choices=["iso", "unix"])
    parser.add_argument("--apiKey", help="Optional - env ODDS_API_KEY fallback")
    parser.add_argument("--group", default="dev")
    parser.add_argument("--runId",
                        help="Optional - capture.py injects one for fixture runs")
    parser.add_argument("--debug", action="store_true",
                        help="Verbose logging")
    parser.add_argument("--bookmakers", default="draftkings,fanduel",
                    help="comma-sep list, e.g. draftkings,fanduel")

    args = parser.parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    GetOddsApiCurrentEventOdds().run(vars(args))

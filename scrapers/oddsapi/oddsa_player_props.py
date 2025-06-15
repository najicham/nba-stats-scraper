# scrapers/odds_api_current_event_odds.py

import os
import logging
from datetime import datetime

from .scraper_base import ScraperBase, ExportMode
from .utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")

class GetOddsApiCurrentEventOdds(ScraperBase):
    """
    Scraper for The Odds API (current odds) that fetches odds for a specific NBA event.
    
    Corresponds to:
      GET /v4/sports/{sport}/events/{eventId}/odds

    Usage (local CLI):
      python odds_api_current_event_odds.py \
        --sport=basketball_nba \
        --eventId=some-event-id \
        --apiKey=MY_SECRET_KEY \
        --markets=player_points,totals \
        --regions=us \
        --oddsFormat=decimal
    """

    required_opts = ["sport", "eventId", "apiKey"]
    additional_opts = []

    # Typically no proxy needed for The Odds API
    proxy_enabled = False

    exporters = [
        {
            "type": "gcs",
            "key": "oddsapi/event-odds/current/%(sport)s/%(eventId)s/%(time)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/oddsapi_current_event_odds.json",
            "export_mode": ExportMode.RAW,
            "groups": ["dev", "file"],
        }
    ]

    def set_url(self):
        """
        Construct the URL for The Odds API endpoint (current event odds).
        e.g.:
        https://api.the-odds-api.com/v4/sports/basketball_nba/events/{eventId}/odds
            ?apiKey=KEY
            &markets=player_points
            &regions=us
            &oddsFormat=decimal
        """
        base_url = "https://api.the-odds-api.com/v4/sports"
        sport = self.opts["sport"]
        event_id = self.opts["eventId"]
        api_key = self.opts["apiKey"]

        # Optional params
        markets = self.opts.get("markets", "player_points")
        regions = self.opts.get("regions", "us")
        odds_format = self.opts.get("oddsFormat", "decimal")

        self.url = (
            f"{base_url}/{sport}/events/{event_id}/odds"
            f"?apiKey={api_key}"
            f"&markets={markets}"
            f"&regions={regions}"
            f"&oddsFormat={odds_format}"
        )

        logger.info("Constructed Odds API Current Event URL: %s", self.url)

    def set_headers(self):
        """
        Minimal headers for The Odds API. Expand if needed.
        """
        self.headers = {
            "Accept": "application/json"
        }
        logger.debug("Headers set for current event odds request: %s", self.headers)

    def validate_download_data(self):
        """
        According to Swagger, a successful response is typically an object or
        an array with odds info. If there's an error, a dict with {"message": "..."}
        might appear.
        """
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            msg = self.decoded_data["message"]
            logger.error("API returned an error message: %s", msg)
            raise DownloadDataException(f"API error: {msg}")

        if not self.decoded_data:
            logger.info("No odds data returned (empty). Possibly no markets available.")
        elif not isinstance(self.decoded_data, (dict, list)):
            logger.error("Unexpected response type: %s", type(self.decoded_data))
            raise DownloadDataException("Unexpected response type; expected dict or list of odds data.")

        logger.info("Odds data received. Type=%s", type(self.decoded_data))

    def should_save_data(self):
        """
        Decide if we skip exporting if there's no data.
        """
        if not self.decoded_data:
            logger.info("Skipping save due to empty odds data.")
            return False
        return True

    def get_scraper_stats(self):
        """
        Return fields for the final SCRAPER_STATS line: how many records found,
        plus sport/eventId for clarity.
        """
        decoded = self.decoded_data
        records_found = 0

        if isinstance(decoded, list):
            records_found = len(decoded)
        elif isinstance(decoded, dict) and decoded:
            # Non-empty dict implies 1 set of odds
            records_found = 1

        event_id = self.opts.get("eventId", "unknown")
        sport = self.opts.get("sport", "unknown")

        return {
            "records_found": records_found,
            "sport": sport,
            "event_id": event_id
        }


##############################################################################
# Cloud Function Entry Point
##############################################################################
def gcf_entry(request):
    """
    Cloud Function HTTP entry point.
    Example usage:
      GET .../OddsApiCurrentEventOdds?sport=basketball_nba&eventId=some-id&apiKey=SECRET&markets=player_points&regions=us&oddsFormat=decimal&group=prod
    """
    sport = request.args.get("sport", "basketball_nba")
    event_id = request.args.get("eventId", "")
    api_key = request.args.get("apiKey", "")
    markets = request.args.get("markets", "player_points")
    regions = request.args.get("regions", "us")
    odds_format = request.args.get("oddsFormat", "decimal")
    group = request.args.get("group", "prod")

    opts = {
        "sport": sport,
        "eventId": event_id,
        "apiKey": api_key,
        "markets": markets,
        "regions": regions,
        "oddsFormat": odds_format,
        "group": group
    }

    scraper = GetOddsApiCurrentEventOdds()
    result = scraper.run(opts)
    return f"OddsApiCurrentEventOdds run complete. Found result: {result}", 200


##############################################################################
# Local CLI Usage
##############################################################################
if __name__ == "__main__":
    import argparse

    default_api_key = os.environ.get("ODDS_API_KEY", None)

    parser = argparse.ArgumentParser(description="Run Odds API Current Event Odds locally")
    parser.add_argument("--sport", default="basketball_nba", help="Sport name, e.g. basketball_nba")
    parser.add_argument("--eventId", required=True, help="The event ID to fetch odds for")
    parser.add_argument("--markets", default="player_points", help="e.g. player_points,totals,h2h")
    parser.add_argument("--regions", default="us", help="e.g. us")
    parser.add_argument("--oddsFormat", default="decimal", help="e.g. decimal or american")
    parser.add_argument("--group", default="test", help="Exporter group (test/prod)")
    args = parser.parse_args()

    opts = vars(args)
    scraper = GetOddsApiCurrentEventOdds()
    scraper.run(opts)

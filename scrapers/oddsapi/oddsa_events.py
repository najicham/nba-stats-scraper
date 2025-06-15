import os
import logging
from datetime import datetime

from ..scraper_base import ScraperBase, ExportMode
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetOddsApiEvents(ScraperBase):
    """
    Scraper for The Odds API (current events). 
    Only requires:
      - apiKey (query param)
      - sport (in the URL, e.g. /v4/sports/basketball_nba/events)

    Optionally includes:
      - commenceTimeFrom
      - commenceTimeTo

    Example usage (local CLI):
      python odds_api_events.py --apiKey=MY_SECRET_KEY --sport=basketball_nba \
        --commenceTimeFrom=2025-06-05T00:00:00Z \
        --commenceTimeTo=2025-06-06T00:00:00Z
    """

    # We'll require 'apiKey' and 'sport'
    required_opts = ["apiKey", "sport"]
    additional_opts = []

    proxy_enabled = False  # Typically no proxy needed

    exporters = [
        {
            "type": "gcs",
            "key": "oddsapi/events/current/%(sport)s/%(time)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/oddsapi_events.json",
            "export_mode": ExportMode.RAW,
            "groups": ["dev", "test", "file"],
        }
    ]

    def set_url(self):
        """
        Base URL: https://api.the-odds-api.com/v4/sports/{sport}/events?apiKey=KEY
        Optionally add &commenceTimeFrom= and &commenceTimeTo=
        """
        base_url = f"https://api.the-odds-api.com/v4/sports/{self.opts['sport']}/events"
        api_key = self.opts["apiKey"]

        # Build base query with apiKey
        query_params = f"?apiKey={api_key}"

        # If commenceTimeFrom or commenceTimeTo are present, append them
        ctf = self.opts.get("commenceTimeFrom")  # e.g. 2025-06-05T00:00:00Z
        ctt = self.opts.get("commenceTimeTo")    # e.g. 2025-06-06T00:00:00Z

        if ctf:
            query_params += f"&commenceTimeFrom={ctf}"
        if ctt:
            query_params += f"&commenceTimeTo={ctt}"

        self.url = f"{base_url}{query_params}"
        print(self.url)
        logger.info("Constructed Odds API Events URL: %s", self.url)

    def set_headers(self):
        """
        Minimal headers for The Odds API.
        """
        self.headers = {
            "Accept": "application/json"
        }
        logger.debug("Headers set for events request: %s", self.headers)

    def validate_download_data(self):
        """
        Typically a list of event objects or a dict with {"message": "..."} if there's an error.
        """
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            msg = self.decoded_data["message"]
            logger.error("API returned an error message: %s", msg)
            raise DownloadDataException(f"API error: {msg}")

        if isinstance(self.decoded_data, list):
            count = len(self.decoded_data)
            if count == 0:
                logger.info("No events returned for sport=%s", self.opts["sport"])
            else:
                logger.info("Found %d events for sport=%s", count, self.opts["sport"])
        else:
            logger.error("Unexpected data structure; expected a list. Got %s", type(self.decoded_data))
            raise DownloadDataException("Unexpected data structure; expected a list of events.")

    def should_save_data(self):
        """
        Optionally skip saving if it's an empty list.
        """
        if isinstance(self.decoded_data, list) and len(self.decoded_data) == 0:
            logger.info("Skipping save because data is empty for sport=%s", self.opts["sport"])
            return False
        return True

    def get_scraper_stats(self):
        """
        Fields for the final SCRAPER_STATS line: # of events, plus the sport used.
        """
        if isinstance(self.decoded_data, list):
            events_found = len(self.decoded_data)
        else:
            events_found = 0

        sport = self.opts.get("sport", "unknown")
        return {
            "records_found": events_found,
            "sport": sport
        }


##############################################################################
# Cloud Function Entry Point
##############################################################################
def gcf_entry(request):
    """
    Cloud Function HTTP entry point for events.
    Example request:
      GET .../OddsApiEvents?apiKey=SECRET&sport=basketball_nba
        &commenceTimeFrom=2025-06-05T00:00:00Z
        &commenceTimeTo=2025-06-06T00:00:00Z
        &group=prod
    """
    sport = request.args.get("sport", "basketball_nba")
    api_key = request.args.get("apiKey", "")
    commence_time_from = request.args.get("commenceTimeFrom")
    commence_time_to = request.args.get("commenceTimeTo")
    group = request.args.get("group", "prod")

    opts = {
        "sport": sport,
        "apiKey": api_key,
        "commenceTimeFrom": commence_time_from,
        "commenceTimeTo": commence_time_to,
        "group": group
    }

    scraper = GetOddsApiEvents()
    result = scraper.run(opts)
    return f"OddsApiEvents run complete. Found result: {result}", 200


##############################################################################
# Local CLI Usage
##############################################################################
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Odds API Current Events scraper locally")
    parser.add_argument("--apiKey", required=True, help="Odds API key")
    parser.add_argument("--sport", default="basketball_nba", help="Sport name, e.g. basketball_nba")
    # Optional time window for commenceTime
    parser.add_argument("--commenceTimeFrom", help="e.g. 2025-06-05T00:00:00Z")
    parser.add_argument("--commenceTimeTo", help="e.g. 2025-06-06T00:00:00Z")
    parser.add_argument("--group", default="test", help="Exporter group (test/prod)")

    args = parser.parse_args()
    opts = vars(args)

    scraper = GetOddsApiEvents()
    scraper.run(opts)

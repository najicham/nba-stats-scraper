import os
import logging
from datetime import datetime

from .scraper_base import ScraperBase, ExportMode
from .utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetOddsApiHistoricalEvents(ScraperBase):
    """
    Scraper for The Odds API (historical) that fetches events for a given sport
    at a specific date/time, optionally within a commenceTime window.

    Required:
      --apiKey="YOUR_API_KEY"
      --sport="basketball_nba"
      --date="2025-06-10T00:00:00Z"

    Optional:
      --commenceTimeFrom="2025-06-09T00:00:00Z"
      --commenceTimeTo="2025-06-10T00:00:00Z"

    Example CLI usage:
      python odds_api_historical_events.py \
        --apiKey=MY_SECRET_KEY \
        --sport=basketball_nba \
        --date=2023-11-29T22:45:00Z \
        --commenceTimeFrom=2023-11-29T00:00:00Z \
        --commenceTimeTo=2023-11-29T23:59:00Z

    The final URL might look like:
    https://api.the-odds-api.com/v4/historical/sports/basketball_nba/events
      ?apiKey=XXXX
      &date=2023-11-29T22:45:00Z
      &commenceTimeFrom=2023-11-29T00:00:00Z
      &commenceTimeTo=2023-11-29T23:59:00Z
    """

    # Now we require apiKey, sport, and date
    required_opts = ["apiKey", "sport", "date"]
    additional_opts = []

    # Typically no proxy needed
    proxy_enabled = False

    # Exporters: one for GCS (prod/gcs), one for local file
    exporters = [
        {
            "type": "gcs",
            "key": "oddsapi/historical-events/%(time)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/oddsapi_historical_events.json",
            "export_mode": ExportMode.RAW,
            "groups": ["dev", "file", "test"],
        }
    ]

    def set_url(self):
        """
        Construct the URL for The Odds API historical endpoint, e.g.:
          https://api.the-odds-api.com/v4/historical/sports/{sport}/events
            ?apiKey=MY_SECRET_KEY
            &date=2025-06-10T00:00:00Z
            &commenceTimeFrom=...
            &commenceTimeTo=...
        """
        base_url = f"https://api.the-odds-api.com/v4/historical/sports/{self.opts['sport']}/events"
        api_key = self.opts["apiKey"]
        date_str = self.opts["date"]

        # Optional commenceTimeFrom / commenceTimeTo
        ctf = self.opts.get("commenceTimeFrom")
        ctt = self.opts.get("commenceTimeTo")

        # Start building the query
        query = f"?apiKey={api_key}&date={date_str}"

        if ctf:
            query += f"&commenceTimeFrom={ctf}"
        if ctt:
            query += f"&commenceTimeTo={ctt}"

        self.url = f"{base_url}{query}"
        logger.info("Constructed The Odds API Historical Events URL: %s", self.url)

    def set_headers(self):
        """
        Minimal headers for The Odds API.
        """
        self.headers = {
            "Accept": "application/json"
        }
        logger.debug("Headers set for historical events request: %s", self.headers)

    def validate_download_data(self):
        """
        The new response is a dict with top-level fields plus "data": [ ...events... ].
        If there's a "message" key, it's an error. Otherwise, we expect a "data" key with a list.
        """
        # 1) Check for error message
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            msg = self.decoded_data["message"]
            logger.error("API returned an error message: %s", msg)
            raise DownloadDataException(f"API error: {msg}")

        # 2) If top-level is a dict with 'data', extract that list
        if isinstance(self.decoded_data, dict) and "data" in self.decoded_data:
            # Replace decoded_data with just the events list
            data_list = self.decoded_data["data"]
            if not isinstance(data_list, list):
                logger.error("Field 'data' is not a list. Found type=%s", type(data_list))
                raise DownloadDataException("Unexpected data structure; 'data' key must contain a list.")

            # Overwrite self.decoded_data with the actual events list
            self.decoded_data = data_list

            # Now self.decoded_data is a list. Let's see if it's empty or has events
            if len(self.decoded_data) == 0:
                logger.info("No events returned in the 'data' array.")
            else:
                logger.info("Found %d events in 'data' array.", len(self.decoded_data))
            return

        # 3) If it's already a list, that’s fine (some other scenario)
        if isinstance(self.decoded_data, list):
            logger.info("Got a top-level list. Found %d events.", len(self.decoded_data))
            return

        # 4) Otherwise, unknown structure
        logger.error("Unexpected data structure; top-level was %s", type(self.decoded_data))
        raise DownloadDataException("Unexpected data structure; expected a dict with 'data' or a list.")

    def should_save_data(self):
        """
        Skip saving if it's an empty list.
        """
        if isinstance(self.decoded_data, list) and len(self.decoded_data) == 0:
            logger.info("Skipping save because data is empty for date=%s", self.opts["date"])
            return False
        return True

    def get_scraper_stats(self):
        """
        Fields for the final SCRAPER_STATS line: # of events, plus the date param used.
        """
        if isinstance(self.decoded_data, list):
            events_found = len(self.decoded_data)
        else:
            events_found = 0

        date_str = self.opts.get("date", "unknown")
        return {
            "records_found": events_found,
            "date": date_str
        }


##############################################################################
# Cloud Function Entry Point
##############################################################################
def gcf_entry(request):
    """
    Cloud Function (HTTP) entry point.
    Example request:
      GET .../OddsApiHistoricalEvents?apiKey=SECRET&sport=basketball_nba
        &date=2023-11-29T00:00:00Z
        &commenceTimeFrom=2023-11-29T00:00:00Z
        &commenceTimeTo=2023-11-29T23:59:00Z
        &group=prod
    """
    api_key = request.args.get("apiKey", "")
    sport = request.args.get("sport", "basketball_nba")
    date_str = request.args.get("date", "2023-11-29T00:00:00Z")
    commence_time_from = request.args.get("commenceTimeFrom")
    commence_time_to = request.args.get("commenceTimeTo")
    group = request.args.get("group", "prod")

    opts = {
        "apiKey": api_key,
        "sport": sport,
        "date": date_str,
        "commenceTimeFrom": commence_time_from,
        "commenceTimeTo": commence_time_to,
        "group": group
    }

    scraper = GetOddsApiHistoricalEvents()
    result = scraper.run(opts)
    return f"OddsApiHistoricalEvents run complete. result: {result}", 200


##############################################################################
# Local CLI Usage
##############################################################################
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Odds API Historical Events locally")
    parser.add_argument("--apiKey", required=True, help="Odds API key")
    parser.add_argument("--sport", required=True, help="e.g. basketball_nba")
    parser.add_argument("--date", required=True, help="e.g. 2023-11-29T22:45:00Z")

    parser.add_argument("--commenceTimeFrom", help="Optional: e.g. 2023-11-29T00:00:00Z")
    parser.add_argument("--commenceTimeTo", help="Optional: e.g. 2023-11-29T23:59:59Z")

    parser.add_argument("--group", default="test", help="Which exporter group to run (dev/test/prod)")
    args = parser.parse_args()

    opts = vars(args)
    scraper = GetOddsApiHistoricalEvents()
    scraper.run(opts)

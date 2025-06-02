# scrapers/odds_api_historical_events.py

import os
import logging
from datetime import datetime

from .scraper_base import ScraperBase, ExportMode
from .utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetOddsApiHistoricalEvents(ScraperBase):
    """
    Scraper for The Odds API (historical) that fetches NBA events for a specific date/time.

    Usage example (local CLI):
      python odds_api_historical_events.py \
        --apiKey=MY_SECRET_KEY \
        --date=2023-11-29T22:45:00Z \
        --regions=us \
        --markets=h2h,totals,player_points
    """

    required_opts = ["apiKey", "date"]
    additional_opts = []

    # Typically no proxy needed
    proxy_enabled = False

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
            "groups": ["dev", "file"],
        }
    ]

    def set_url(self):
        """
        Construct the URL for The Odds API endpoint (historical events).
        Example:
          https://api.the-odds-api.com/v4/historical/sports/basketball_nba/events
            ?apiKey=MY_SECRET_KEY
            &date=2023-11-29T22:45:00Z
            &regions=us
            &markets=h2h,player_points
        """
        base_url = "https://api.the-odds-api.com/v4/historical/sports/basketball_nba/events"
        api_key = self.opts["apiKey"]
        date_str = self.opts["date"]

        regions = self.opts.get("regions", "us")
        markets = self.opts.get("markets", "h2h")

        self.url = (
            f"{base_url}?apiKey={api_key}"
            f"&date={date_str}"
            f"&regions={regions}"
            f"&markets={markets}"
        )
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
        Typically a list of event objects or an error message dict {"message": "..."}.
        """
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            msg = self.decoded_data["message"]
            logger.error("API returned an error message: %s", msg)
            raise DownloadDataException(f"API error: {msg}")

        if isinstance(self.decoded_data, list):
            if len(self.decoded_data) == 0:
                logger.info("No historical events returned for date=%s", self.opts["date"])
            else:
                logger.info("Found %d historical events for date=%s",
                            len(self.decoded_data), self.opts["date"])
        else:
            logger.error("Unexpected data structure; expected a list. Got %s", type(self.decoded_data))
            raise DownloadDataException("Unexpected data structure; expected a list of events.")

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
      GET .../OddsApiHistoricalEvents?apiKey=SECRET&date=2023-11-29T00:00:00Z&regions=us&markets=h2h,player_points&group=prod
    """
    api_key = request.args.get("apiKey", "")
    date_str = request.args.get("date", "2023-11-29T00:00:00Z")
    regions = request.args.get("regions", "us")
    markets = request.args.get("markets", "h2h")
    group = request.args.get("group", "prod")

    opts = {
        "apiKey": api_key,
        "date": date_str,
        "regions": regions,
        "markets": markets,
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
    parser.add_argument("--apiKey", required=True)
    parser.add_argument("--date", required=True, help="e.g. 2023-11-29T22:45:00Z")
    parser.add_argument("--regions", default="us", help="e.g. us")
    parser.add_argument("--markets", default="h2h", help="e.g. h2h,totals,player_points")
    parser.add_argument("--group", default="test", help="Which exporter group to run (dev/test/prod)")
    args = parser.parse_args()

    opts = vars(args)
    scraper = GetOddsApiHistoricalEvents()
    scraper.run(opts)

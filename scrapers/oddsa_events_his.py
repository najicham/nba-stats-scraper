# scrapers/odds_api_historical_events.py

import os
import logging
from datetime import datetime

from .scraper_base import ScraperBase
from .utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetOddsApiHistoricalEvents(ScraperBase):
    """
    Scraper for The Odds API (historical) that fetches NBA events for a specific date/time.

    Usage example:
      python odds_api_historical_events.py \
        --apiKey=MY_SECRET_KEY \
        --date=2023-11-29T22:45:00Z \
        --regions=us \
        --markets=h2h,totals,player_points
    """

    required_opts = ["apiKey", "date"]
    additional_opts = []

    use_proxy = False  # Typically not needed for The Odds API

    exporters = [
        {
            "type": "gcs",
            "key": "oddsapi/historical-events/%(time)s.json",
            "use_raw": True,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/oddsapi_historical_events.json",
            "use_raw": True,
            "groups": ["dev", "file"],
        }
    ]

    def set_url(self):
        """
        Construct the URL for The Odds API endpoint to get historical events.

        E.g.:
        https://api.the-odds-api.com/v4/historical/sports/basketball_nba/events
            ?apiKey=MY_SECRET_KEY
            &date=2023-11-29T22:45:00Z
            &regions=us
            &markets=h2h,player_points
        """
        base_url = "https://api.the-odds-api.com/v4/historical/sports/basketball_nba/events"
        api_key = self.opts["apiKey"]
        date_str = self.opts["date"]

        # optional parameters
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
        Typically minimal headers for The Odds API.
        """
        self.headers = {
            "Accept": "application/json"
        }
        logger.debug("Headers set for historical events request: %s", self.headers)

    def validate_download_data(self):
        """
        The response is typically a list of event objects or an error message.
        Example of success: [ { "id": "...", "commence_time": "...", ... }, ... ]
        Example of failure: { "message": "...error message..." }
        """
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            msg = self.decoded_data["message"]
            logger.error("API returned an error message: %s", msg)
            raise DownloadDataException(f"API error: {msg}")

        if isinstance(self.decoded_data, list):
            if len(self.decoded_data) == 0:
                logger.info("No historical events returned. Possibly no data for the given date.")
            else:
                logger.info("Found %d historical events for date=%s", len(self.decoded_data), self.opts["date"])
        else:
            logger.error("Unexpected data structure; expected a list. Got %s", type(self.decoded_data))
            raise DownloadDataException("Unexpected data structure; expected a list of events.")

    def should_save_data(self):
        """
        Optionally skip saving if there's no data. We'll export anyway unless we specifically
        don't want an empty array.
        """
        if isinstance(self.decoded_data, list) and len(self.decoded_data) == 0:
            logger.info("Deciding not to save empty data array.")
            return False
        return True

    ##################################################################
    # Override get_scraper_stats() to log # of events + query date
    ##################################################################
    def get_scraper_stats(self):
        """
        Return fields for the final SCRAPER_STATS line:
        the number of events found and the date param used.
        """
        # If it's a list, measure its length
        if isinstance(self.decoded_data, list):
            events_found = len(self.decoded_data)
        else:
            events_found = 0

        date_str = self.opts.get("date", "unknown")

        return {
            "records_found": events_found,
            "date": date_str
        }

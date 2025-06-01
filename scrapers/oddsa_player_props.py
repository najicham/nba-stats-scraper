# scrapers/odds_api_current_event_odds.py

import os
import logging
from datetime import datetime

from .scraper_base import ScraperBase
from .utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")

class GetOddsApiCurrentEventOdds(ScraperBase):
    """
    Scraper for The Odds API (current odds) that fetches odds for a specific NBA event.
    
    Corresponds to:
      GET /v4/sports/{sport}/events/{eventId}/odds

    Usage:
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

    use_proxy = False  # Usually not needed for The Odds API

    exporters = [
        {
            "type": "gcs",
            "key": "oddsapi/event-odds/current/%(sport)s/%(eventId)s/%(time)s.json",
            "use_raw": True,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/oddsapi_current_event_odds.json",
            "use_raw": True,
            "groups": ["dev", "file"],
        }
    ]

    def set_url(self):
        """
        Construct the URL for The Odds API endpoint (current event odds).
        e.g.:
        https://api.the-odds-api.com/v4/sports/{sport}/events/{eventId}/odds
            ?apiKey=MY_KEY
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
        According to Swagger, a successful response is typically an object or an array with odds info.
        If there's an error, a dict with {"message": "..."} might appear.
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

    ##################################################################
    # Override get_scraper_stats() to track record_count + event info
    ##################################################################
    def get_scraper_stats(self):
        """
        Return fields for the final SCRAPER_STATS line:
        how many records found, plus sport/eventId for clarity.
        """
        # The response might be a dict or a list
        decoded = self.decoded_data
        records_found = 0

        if isinstance(decoded, list):
            records_found = len(decoded)
        elif isinstance(decoded, dict) and decoded:
            # If we assume a non-empty dict means one set of odds
            records_found = 1

        event_id = self.opts.get("eventId", "unknown")
        sport = self.opts.get("sport", "unknown")

        return {
            "records_found": records_found,
            "sport": sport,
            "event_id": event_id
        }

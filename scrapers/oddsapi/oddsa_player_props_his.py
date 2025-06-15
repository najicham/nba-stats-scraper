# scrapers/odds_api_player_props_history.py

import os
import logging
from datetime import datetime

from ..scraper_base import ScraperBase, ExportMode
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetOddsApiPlayerPropsHistory(ScraperBase):
    """
    Scraper for The Odds API (historical) that fetches NBA player props by event ID.

    Usage example (CLI):
      python odds_api_player_props_history.py --event_id=da359da99aa27e97d38f2df709343998 \
        --apiKey=MY_SECRET_KEY \
        --date=2023-11-29T22:45:00Z \
        --markets=player_points,h2h_q1 \
        --regions=us
    """

    required_opts = ["event_id", "apiKey", "date"]
    additional_opts = []

    # Usually no proxy needed for The Odds API
    proxy_enabled = False

    exporters = [
        {
            "type": "gcs",
            "key": "oddsapi/player-props/%(event_id)s/%(time)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/oddsapi_player_props_history.json",
            "export_mode": ExportMode.RAW,
            "groups": ["dev", "test", "file"],
        }
    ]

    def set_url(self):
        """
        Construct the URL for The Odds API historical player props endpoint.
        e.g.:
        https://api.the-odds-api.com/v4/historical/sports/basketball_nba/events/<EVENT_ID>/odds
            ?apiKey=KEY&date=DATE&regions=us&markets=player_points
        """
        base_url = "https://api.the-odds-api.com/v4/historical/sports/basketball_nba/events"
        event_id = self.opts["event_id"]
        api_key = self.opts["apiKey"]
        date_str = self.opts["date"]

        regions = self.opts.get("regions", "us")
        markets = self.opts.get("markets", "player_points")

        self.url = (
            f"{base_url}/{event_id}/odds"
            f"?apiKey={api_key}"
            f"&date={date_str}"
            f"&regions={regions}"
            f"&markets={markets}"
        )

        logger.info("Constructed Odds API Player Props URL: %s", self.url)

    def set_headers(self):
        """
        Typically minimal headers needed for The Odds API.
        """
        self.headers = {
            "Accept": "application/json"
        }
        logger.debug("Headers set for Player Props request: %s", self.headers)

    def validate_download_data(self):
        """
        If there's an error, The Odds API might return {"message": "..."} or an empty list.
        We check basic structure here.
        """
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            msg = self.decoded_data["message"]
            logger.error("API returned an error message: %s", msg)
            raise DownloadDataException(f"API error: {msg}")

        if isinstance(self.decoded_data, list):
            if len(self.decoded_data) == 0:
                logger.info("No player props returned. Possibly none available for this event.")
            else:
                logger.info("Found %d items in player props data for event_id=%s",
                            len(self.decoded_data), self.opts["event_id"])
        else:
            logger.error("Unexpected data structure: expected a list, got %s", type(self.decoded_data))
            raise DownloadDataException("Unexpected data structure; expected a list of odds info.")

    def should_save_data(self):
        """
        Skip exporting if there's no data (empty list).
        """
        if isinstance(self.decoded_data, list) and len(self.decoded_data) == 0:
            logger.info("Skipping export because decoded_data is an empty list.")
            return False
        return True

    def get_scraper_stats(self):
        """
        Return fields for the final SCRAPER_STATS line:
        the number of props found, event_id, and date.
        """
        if isinstance(self.decoded_data, list):
            records_found = len(self.decoded_data)
        else:
            records_found = 0

        event_id = self.opts.get("event_id", "unknown")
        date_str = self.opts.get("date", "unknown")

        return {
            "records_found": records_found,
            "event_id": event_id,
            "date": date_str
        }


##############################################################################
# Cloud Function Entry Point
##############################################################################
def gcf_entry(request):
    """
    HTTP entry point for Cloud Functions.
    Example usage:
      GET .../OddsApiPlayerPropsHistory?event_id=XXXX&apiKey=SECRET&date=YYYY&regions=us&markets=player_points&group=prod
    """
    event_id = request.args.get("event_id", "")
    api_key = request.args.get("apiKey", "")
    date_str = request.args.get("date", "2023-11-29T00:00:00Z")
    regions = request.args.get("regions", "us")
    markets = request.args.get("markets", "player_points")
    group = request.args.get("group", "prod")

    opts = {
        "event_id": event_id,
        "apiKey": api_key,
        "date": date_str,
        "regions": regions,
        "markets": markets,
        "group": group
    }

    scraper = GetOddsApiPlayerPropsHistory()
    result = scraper.run(opts)
    return f"OddsApiPlayerPropsHistory run complete. Found result: {result}", 200


##############################################################################
# Local CLI Usage
##############################################################################
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Odds API Player Props History locally")
    parser.add_argument("--event_id", required=True, help="Event ID to fetch props for")
    parser.add_argument("--apiKey", required=True, help="Odds API key")
    parser.add_argument("--date", required=True, help="e.g. 2023-11-29T22:45:00Z")
    parser.add_argument("--regions", default="us", help="Possible values: us, etc.")
    parser.add_argument("--markets", default="player_points", help="e.g. player_points,h2h_q1")
    parser.add_argument("--group", default="test", help="Which exporter group to run (dev/test/prod)")
    args = parser.parse_args()

    opts = vars(args)
    scraper = GetOddsApiPlayerPropsHistory()
    scraper.run(opts)

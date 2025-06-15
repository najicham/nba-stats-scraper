# scrapers/odds_api_team_players.py

import os
import logging
from datetime import datetime

from .scraper_base import ScraperBase, ExportMode
from .utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetOddsApiTeamPlayers(ScraperBase):
    """
    Scraper for The Odds API endpoint that returns a list of players for a given team.

    Example usage:
      python odds_api_team_players.py \
        --sport=basketball_nba \
        --participantId=team-1234 \
        --apiKey=MY_SECRET_KEY

    Endpoint (undocumented):
      GET https://api.the-odds-api.com/v4/sports/{sport}/participants/{participantId}/players?apiKey={apiKey}

    We assume the response is a list of player info for the given team.
    """

    required_opts = ["sport", "participantId", "apiKey"]
    additional_opts = []

    # Typically not needed for The Odds API
    proxy_enabled = False

    exporters = [
        {
            "type": "gcs",
            "key": "oddsapi/team-players/%(sport)s/%(participantId)s/%(time)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/oddsapi_team_players.json",
            "export_mode": ExportMode.RAW,
            "groups": ["dev", "file"],
        }
    ]

    def set_url(self):
        """
        Construct the /players endpoint for a given sport, participant/team ID, and API key.

        Example:
          https://api.the-odds-api.com/v4/sports/basketball_nba/participants/team-1234/players?apiKey=MYKEY
        """
        base_url = "https://api.the-odds-api.com/v4/sports"
        sport = self.opts["sport"]
        participant_id = self.opts["participantId"]
        api_key = self.opts["apiKey"]

        self.url = (
            f"{base_url}/{sport}/participants/{participant_id}/players"
            f"?apiKey={api_key}"
        )
        logger.info("Constructed Team Players URL: %s", self.url)

    def set_headers(self):
        """
        Minimal headers for The Odds API. Expand if needed.
        """
        self.headers = {
            "Accept": "application/json"
        }
        logger.debug("Headers set for team players request: %s", self.headers)

    def validate_download_data(self):
        """
        Because this endpoint is not documented, we assume the response is either:
         - a list of players, or
         - a dict with an error: {"message": "..."}.
        """
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            msg = self.decoded_data["message"]
            logger.error("API returned error: %s", msg)
            raise DownloadDataException(f"API error: {msg}")

        if isinstance(self.decoded_data, list):
            if len(self.decoded_data) == 0:
                logger.info("No players returned for participantId=%s", self.opts["participantId"])
        else:
            logger.error("Unexpected response structure. Expected list or error dict. Got: %s",
                         type(self.decoded_data))
            raise DownloadDataException("Unexpected response structure; expected a list or error dict.")

    def should_save_data(self):
        """
        Optionally skip saving if the list is empty.
        We'll proceed to save anyway unless we explicitly want to skip an empty response.
        """
        if isinstance(self.decoded_data, list) and len(self.decoded_data) == 0:
            logger.info("Skipping save because the team players list is empty.")
            return False
        return True

    def get_scraper_stats(self):
        """
        Return fields for the final SCRAPER_STATS line:
        how many players found, plus the sport & participantId.
        """
        records_found = 0
        if isinstance(self.decoded_data, list):
            records_found = len(self.decoded_data)

        sport = self.opts.get("sport", "unknown")
        participant_id = self.opts.get("participantId", "unknown")

        return {
            "records_found": records_found,
            "sport": sport,
            "participantId": participant_id
        }


##############################################################################
# Cloud Function Entry Point
##############################################################################
def gcf_entry(request):
    """
    HTTP entry point for Cloud Functions to fetch team players via The Odds API.
    Example usage:
      GET .../OddsApiTeamPlayers?sport=basketball_nba&participantId=team-1234&apiKey=SECRET&group=prod
    """
    sport = request.args.get("sport", "basketball_nba")
    participant_id = request.args.get("participantId", "")
    api_key = request.args.get("apiKey", "")
    group = request.args.get("group", "prod")

    opts = {
        "sport": sport,
        "participantId": participant_id,
        "apiKey": api_key,
        "group": group
    }

    scraper = GetOddsApiTeamPlayers()
    result = scraper.run(opts)
    return f"OddsApiTeamPlayers run complete. Found result: {result}", 200


##############################################################################
# Local CLI Usage
##############################################################################
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run The Odds API Team Players locally")
    parser.add_argument("--sport", default="basketball_nba", help="e.g. basketball_nba")
    parser.add_argument("--participantId", required=True, help="Team ID e.g. 'team-1234'")
    parser.add_argument("--apiKey", required=True, help="Odds API key")
    parser.add_argument("--group", default="test", help="Which exporter group to run (dev/test/prod)")
    args = parser.parse_args()

    opts = vars(args)
    scraper = GetOddsApiTeamPlayers()
    scraper.run(opts)

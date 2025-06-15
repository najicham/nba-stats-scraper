import logging
import json
import pytz
import requests
from datetime import datetime

from ..scraper_base import ScraperBase, DownloadType, ExportMode
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")

class GetEspnTeamRosterAPI(ScraperBase):
    """
    Scraper for ESPN's roster API endpoint for a specific NBA teamId.
      e.g. teamId=2 => Boston Celtics

    Usage:
      python -m scrapers.espn_roster_api --teamId 2
    """

    required_opts = ["teamId"]
    download_type = DownloadType.JSON  # We'll parse JSON directly
    decode_download_data = True

    # example exporter writing JSON to /tmp
    exporters = [
        {
            "type": "file",
            "filename": "/tmp/espn_roster_api_%(teamId)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"]
        }
    ]

    def __init__(self):
        super().__init__()
        self.players = []

    def set_url(self):
        """
        ESPN's team API endpoint:
          https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{teamId}?enable=roster
        """
        base_api = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
        self.url = f"{base_api}/{self.opts['teamId']}?enable=roster"
        logger.info(f"Resolved ESPN roster API URL: {self.url}")

    def set_headers(self):
        """Use a typical 'real browser' style user-agent."""
        self.headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}

    def validate_download_data(self):
        """
        Make sure we got JSON and that 'team'->'athletes' key is present.
        """
        if not isinstance(self.decoded_data, dict):
            raise DownloadDataException("Decoded data is not a dictionary.")

        team_obj = self.decoded_data.get("team")
        if not team_obj:
            raise DownloadDataException("No 'team' object found in ESPN API JSON.")

        # We expect an "athletes" array inside team
        if "athletes" not in team_obj:
            raise DownloadDataException("No 'athletes' found in team object.")

    def transform_data(self):
        """
        The actual roster entries live in decoded_data["team"]["athletes"].
        We'll loop through each athlete dict and collect basic fields.
        """
        self.step_info("transform", "Parsing ESPN roster API JSON")

        team_id = self.opts["teamId"]
        team_obj = self.decoded_data["team"]
        athlete_list = team_obj.get("athletes", [])

        for athlete in athlete_list:
            player_id = athlete.get("id")
            full_name = athlete.get("fullName")
            jersey = athlete.get("jersey")
            position_dict = athlete.get("position", {})
            position_name = position_dict.get("displayName") or position_dict.get("name")
            height_in = athlete.get("height")  # if ESPN is storing integer inches
            weight_lb = athlete.get("weight")
            injuries_list = athlete.get("injuries", [])

            # We can gather some or all fields:
            self.players.append({
                "playerId": player_id,
                "fullName": full_name,
                "jersey": jersey,
                "position": position_name,
                "height": height_in,
                "weight": weight_lb,
                # sample of additional data if you want:
                "injuries": injuries_list, 
            })

        # finalize self.data
        now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat()
        self.data = {
            "teamId": team_id,
            "timestamp": now_utc,
            "players": self.players,
        }
        logger.info(f"Parsed {len(self.players)} players for teamId={team_id}")

    def get_scraper_stats(self):
        return {
            "teamId": self.opts["teamId"],
            "playerCount": len(self.players),
        }


# -----------------------------------------------------------------------------
# Local CLI usage
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--teamId", required=True, help="e.g. 2 => Boston Celtics")
    parser.add_argument("--group", default="dev", help="dev, test, prod, etc.")
    args = parser.parse_args()

    scraper = GetEspnTeamRosterAPI()
    scraper.run(vars(args))

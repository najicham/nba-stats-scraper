import logging
import json
import pytz
from datetime import datetime

import requests

from .scraper_base import ScraperBase, DownloadType, ExportMode
from .utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetEspnScoreboard(ScraperBase):
    """
    ESPN scoreboard scraper that uses ESPN's scoreboard API JSON.

    Usage:
      python -m scrapers.espn_scoreboard --scoreDate 20231116

    Relies on the normal base class workflow:
      - sets self.url to the ESPN scoreboard API
      - sets download_type=JSON
      - transform_data() to parse decoded_data
      - exports self.data as configured
    """

    required_opts = ["scoreDate"]

    # Since we want to parse JSON from ESPN’s scoreboard API:
    download_type = DownloadType.JSON
    decode_download_data = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/espn_scoreboard_%(scoreDate)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"]
        }
    ]

    def __init__(self):
        super().__init__()
        self.games = []

    ##########################################################################
    # Overriding set_url so the base class will download from ESPN scoreboard API
    ##########################################################################
    def set_url(self):
        """
        Build the ESPN scoreboard API URL:
        e.g. https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD
        """
        base_api = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
        self.url = f"{base_api}?dates={self.opts['scoreDate']}"
        logger.info(f"Resolved ESPN scoreboard API URL: {self.url}")

    def set_headers(self):
        """
        Use a typical 'real browser' style user-agent.
        """
        self.headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}

    ##########################################################################
    # Validation
    ##########################################################################
    def validate_download_data(self):
        """
        Ensure 'events' is present in self.decoded_data.
        """
        if not isinstance(self.decoded_data, dict):
            raise DownloadDataException("Decoded data is not a dictionary.")
        if "events" not in self.decoded_data:
            raise DownloadDataException("No 'events' key found in scoreboard JSON.")

    ##########################################################################
    # Transform
    ##########################################################################
    def transform_data(self):
        """
        Read self.decoded_data["events"], parse each event, store in self.games,
        then finalize self.data. The base class will export self.data.
        """
        self.step_info("transform", "Parsing ESPN scoreboard JSON")
        events = self.decoded_data.get("events", [])
        logger.info(f"Found {len(events)} events for date={self.opts['scoreDate']}")

        for event in events:
            comps = event.get("competitions", [])
            if not comps:
                continue

            comp = comps[0]
            game_id = comp.get("id")
            teams_info = []
            for c in comp.get("competitors", []):
                tm = c.get("team", {})
                teams_info.append({
                    "teamId": tm.get("id"),
                    "displayName": tm.get("displayName"),
                    "abbreviation": tm.get("abbreviation"),
                    "score": c.get("score"),
                    "winner": c.get("winner", False),
                    "homeAway": c.get("homeAway"),
                })

            game = {
                "gameId": game_id,
                "teams": teams_info,
                "status": comp.get("status", {}).get("type", {}).get("description", ""),
                "startTime": comp.get("date"),
            }
            self.games.append(game)

        # final scoreboard data
        now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat()
        self.data = {
            "timestamp": now_utc,
            "scoreDate": self.opts["scoreDate"],
            "games": self.games
        }
        logger.info(f"Parsed {len(self.games)} games for date={self.opts['scoreDate']}")

    ##########################################################################
    # Stats for Final Log
    ##########################################################################
    def get_scraper_stats(self):
        """
        Additional fields for final log line
        """
        return {
            "scoreDate": self.opts["scoreDate"],
            "gameCount": len(self.games),
        }


# -----------------------------------------------------------------------------
# GCF entry point (optional)
# -----------------------------------------------------------------------------
def gcf_entry(request):
    """
    Google Cloud Function entry point for ESPN Scoreboard.
      Expects `scoreDate` (yyyyMMdd) in query string, e.g. ?scoreDate=20231116
      Optional `group` param defaults to 'prod'.
    """
    scoreDate = request.args.get("scoreDate")
    group = request.args.get("group", "prod")

    if not scoreDate:
        return ("Missing required parameter: scoreDate", 400)

    opts = {"scoreDate": scoreDate, "group": group}
    scraper = GetEspnScoreboard()
    result = scraper.run(opts)

    return f"ESPN Scoreboard run complete for date={scoreDate}. Result={result}", 200


# -----------------------------------------------------------------------------
# Local CLI usage
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--scoreDate", required=True, help="e.g. 20231116")
    parser.add_argument("--group", default="test", help="dev, test, prod, etc.")
    args = parser.parse_args()

    scraper = GetEspnScoreboard()
    # The base class run() method orchestrates everything
    scraper.run(vars(args))

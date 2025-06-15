# scrapers/nba_com_game_score.py

import os
from datetime import datetime
import logging

from ..scraper_base import ScraperBase, ExportMode
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaComGameScore(ScraperBase):
    """
    Scraper for the NBA.com scoreboard (game scores).
    Utilizes the new exporter classes and the revised ScraperBase approach.
    """

    # This scraper requires 'gamedate'
    required_opts = ["gamedate"]
    additional_opts = ["nba_season_from_gamedate"]
    # Use the shared stats‑site headers from ScraperBase
    header_profile = "stats"
    # We want to enable proxy usage (formerly 'use_proxy = True')
    proxy_enabled = True

    # Define our exporters with new 'export_mode' usage
    exporters = [
        {
            # GCS export: store raw bytes (unmodified HTTP response) if desired
            # or if you prefer the decoded JSON as-is, switch to ExportMode.DECODED.
            "type": "gcs",
            "key": "nbacom/game-score/%(season)s/%(gamedate)s/%(time)s.json",
            "export_mode": ExportMode.RAW,  # Previously was "use_raw": True
            "groups": ["prod", "gcs"],
        },
        {
            # File export: store the decoded JSON (Python dict) with indentation
            "type": "file",
            "filename": "/tmp/getnbacomgamescore.json",
            "export_mode": ExportMode.DECODED,  # Previously "use_decoded_data": True
            "pretty_print": True,
            "groups": ["test", "file"],
        }
    ]

    def set_url(self):
        """
        Build the scoreboard endpoint URL for a given gamedate (YYYY-MM-DD).
        """
        gamedate = self.opts["gamedate"]
        self.url = f"https://stats.nba.com/stats/scoreboardv3?GameDate={gamedate}&LeagueID=00"
        logger.info("GameScore URL constructed: %s", self.url)

    def validate_download_data(self):
        """
        Ensure the JSON has a top-level 'scoreboard' with a 'games' list.
        Raise DownloadDataException if missing or invalid.
        """
        scoreboard = self.decoded_data.get("scoreboard")
        if not scoreboard:
            logger.error("Missing 'scoreboard' in decoded data.")
            raise DownloadDataException("[scoreboard] missing in decoded data")

        if "games" not in scoreboard:
            logger.error("Missing 'games' key in scoreboard: %s", scoreboard.keys())
            raise DownloadDataException("[scoreboard][games] missing in decoded data")

        if not isinstance(scoreboard["games"], list):
            logger.error("'games' is not a list: type=%s", type(scoreboard["games"]))
            raise DownloadDataException("[scoreboard][games] is not a list")

        game_count = len(scoreboard["games"])
        logger.info("Found %d games for gamedate=%s", game_count, self.opts["gamedate"])

    def get_scraper_stats(self):
        """
        Returns extra fields for the final SCRAPER_STATS line:
        e.g., number of games found, plus the gamedate used.
        """
        scoreboard = self.decoded_data.get("scoreboard", {})
        games = scoreboard.get("games", [])
        game_count = len(games)

        return {
            "records_found": game_count,
            "gamedate": self.opts.get("gamedate", "unknown"),
        }


##############################################################################
# Cloud Function Entry Point
##############################################################################
def gcf_entry(request):
    """
    Cloud Function entry point.
    Triggered by Cloud Workflows or Scheduler calling the HTTP endpoint.
    """
    gamedate = request.args.get("gamedate", "2023-12-01")
    group = request.args.get("group", "prod")

    opts = {
        "gamedate": gamedate,
        "group": group
    }

    scraper = GetNbaComGameScore()
    result = scraper.run(opts)

    return f"Scraper run complete. Found result: {result}", 200


##############################################################################
# Local CLI Usage
##############################################################################
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run NBA Game Score locally")
    parser.add_argument("--gamedate", required=True)
    parser.add_argument("--group", default="test")
    args = parser.parse_args()

    opts = vars(args)

    scraper = GetNbaComGameScore()
    scraper.run(opts)

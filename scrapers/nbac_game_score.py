# scrapers/nba_com_game_score.py

import os
from datetime import datetime
import logging

from .scraper_base import ScraperBase
from .utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")

class GetNbaComGameScore(ScraperBase):
    """
    Scraper for the NBA.com scoreboard (game scores).
    Utilizes the new exporter classes via 'type': 'gcs' or 'file'.
    """

    required_opts = ["gamedate"]
    additional_opts = ["nba_season_from_gamedate"]

    use_proxy = True

    exporters = [
        {
            "type": "gcs", 
            "key": "nbacom/game-score/%(season)s/%(gamedate)s/%(time)s.json",
            "use_raw": True,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomgamescore.json",
            "use_raw": True,
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

    def set_headers(self):
        """
        Set standard NBA stats headers to mimic a browser.
        """
        self.headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Host": "stats.nba.com",
            "Origin": "https://www.nba.com",
            "Pragma": "no-cache",
            "Referer": "https://www.nba.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/90.0.4430.85 Safari/537.36"
            ),
            "x-nba-stats-origin": "stats",
            "x-nba-stats-token": "true"
        }
        logger.debug("Headers set for NBA scoreboard request: %s", self.headers)

    def validate_download_data(self):
        """
        Ensure the JSON has a top-level 'scoreboard' and nested 'games' list.
        Raises DownloadDataException if missing.
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

    # OPTIONAL: skip saving if no games are found
    # def should_save_data(self):
    #     games = self.decoded_data["scoreboard"].get("games", [])
    #     logger.info("should_save_data? Found %d games", len(games))
    #     return len(games) > 0

    ##################################################################
    # Override get_scraper_stats() to include # of games found, gamedate
    ##################################################################
    def get_scraper_stats(self):
        """
        Returns fields for the final SCRAPER_STATS line. We'll log how many games and the gamedate.
        """
        # Attempt to find the scoreboard/games structure
        scoreboard = self.decoded_data.get("scoreboard", {})
        games = scoreboard.get("games", [])
        game_count = len(games)

        return {
            "records_found": game_count,
            "gamedate": self.opts.get("gamedate", "unknown"),
        }

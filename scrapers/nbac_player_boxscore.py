# scrapers/nba_com_player_boxscore.py

import os
import logging
from datetime import datetime

from .scraper_base import ScraperBase
from .utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")

class GetNbaComPlayerBoxscore(ScraperBase):
    """
    Scraper for the leaguegamelog endpoint on stats.nba.com, focusing on player boxscores.

    Usage example:
      python nba_com_player_boxscore.py --gamedate=2022-01-01
    """

    required_opts = ["gamedate"]
    additional_opts = ["nba_season_from_gamedate", "nba_seasontype_from_gamedate"]

    use_proxy = True

    exporters = [
        {
            "type": "gcs",
            "key": "nbacom/player-boxscore/%(season)s/%(gamedate)s/%(time)s.json",
            "use_raw": True,
            "groups": ["prod", "s3", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomplayerboxscore2",
            "use_raw": True,
            "groups": ["test", "file"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomplayerboxscore3",
            "use_raw": True,
            "groups": ["test", "file2"],
        }
    ]

    def set_url(self):
        """
        Construct the leaguegamelog URL using self.opts:
          - self.opts["gamedate"]
          - self.opts["season"]
          - self.opts["season_type"]
        """
        date_from = self.opts["gamedate"]
        date_to = date_from
        season_type = self.opts["season_type"]  
        season_with_dash = self.add_dash_to_season(self.opts["season"])

        self.url = (
            "https://stats.nba.com/stats/leaguegamelog?"
            f"Counter=1000&DateFrom={date_from}&DateTo={date_to}&"
            f"Direction=DESC&LeagueID=00&PlayerOrTeam=P&Season={season_with_dash}&"
            f"SeasonType={season_type}&Sorter=DATE"
        )

        logger.info("Constructed PlayerBoxscore URL: %s", self.url)

    def set_headers(self):
        """
        Mimic a standard browser for stats.nba.com requests.
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
        logger.debug("Headers set for PlayerBoxscore request: %s", self.headers)

    def validate_download_data(self):
        """
        Ensure 'resultSets' with 'rowSet' exist and are non-empty.
        Raises DownloadDataException if invalid.
        """
        if "resultSets" not in self.decoded_data:
            logger.error("Missing 'resultSets' in decoded data.")
            raise DownloadDataException("[resultSets] not found in decoded data.")

        if not self.decoded_data["resultSets"]:
            logger.error("'resultSets' is an empty list.")
            raise DownloadDataException("[resultSets] is empty.")

        if "rowSet" not in self.decoded_data["resultSets"][0]:
            logger.error("'rowSet' missing in first resultSets entry.")
            raise DownloadDataException("[rowSet] missing in [resultSets][0].")

        rowset = self.decoded_data["resultSets"][0]["rowSet"]
        if not rowset:
            logger.error("rowSet is empty.")
            raise DownloadDataException("[rowSet] is empty.")

        logger.info("Found %d players in rowSet for gamedate=%s.", len(rowset), self.opts["gamedate"])

    def should_save_data(self):
        """
        Only export if there's at least 1 player record in 'rowSet'.
        """
        rowset = self.decoded_data["resultSets"][0]["rowSet"]
        players_found = len(rowset)

        logger.info("Should we save data? Found %d players, returning %s",
                    players_found, players_found > 0)

        return players_found > 0

    @staticmethod
    def add_dash_to_season(season_str):
        """
        If '2022' -> '2022-23'. If there's already a dash, return as is.
        """
        if "-" in season_str:
            return season_str
        year_int = int(season_str)
        return f"{season_str}-{str(year_int + 1)[-2:]}"

    ##################################################################
    # Override get_scraper_stats() to include # of players, gamedate, season, season_type
    ##################################################################
    def get_scraper_stats(self):
        """
        Return fields for the final SCRAPER_STATS line: number of players found, 
        plus gamedate, season, and season_type if available.
        """
        # Attempt to read rowSet
        rowset = []
        try:
            rowset = self.decoded_data["resultSets"][0]["rowSet"]
        except (KeyError, IndexError, TypeError):
            pass
        records_found = len(rowset)

        # Possibly read from self.opts
        gamedate = self.opts.get("gamedate", "unknown")
        season = self.opts.get("season", "unknown")
        season_type = self.opts.get("season_type", "unknown")

        return {
            "records_found": records_found,
            "gamedate": gamedate,
            "season": season,
            "season_type": season_type
        }

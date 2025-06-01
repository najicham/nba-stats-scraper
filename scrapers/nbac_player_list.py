# scrapers/nba_com_player_list.py

import os
import logging
from datetime import datetime

from .scraper_base import ScraperBase
from .utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")

class GetNbaComPlayerList(ScraperBase):
    """
    Fetches NBA player list from stats.nba.com using the 'playerindex' endpoint.
    This scraper uses additional_opts = ["nba_season_today"] to auto-populate 'season' if not provided.
    """

    use_proxy = True
    additional_opts = ["nba_season_today"]  # If 'season' isn't set, we get today's default

    exporters = [
        {
            "type": "gcs",
            "key": "nbacom/player-list/%(season)s/log/%(time)s.json",
            "use_raw": True,
            "groups": ["prod", "s3", "gcs"],
        },
        {
            "type": "gcs",
            "check_should_save": True,
            "key": "nbacom/player-list/%(season)s/current/current.json",
            "use_raw": True,
            "groups": ["prod", "s3", "gcs"],
        },
        {
            "active": 1,
            "type": "file",
            "filename": "/tmp/getnbacomplayerlist",
            "use_raw": True,
            "test": True,
            "groups": ["dev", "file"],
        },
        {
            "active": 1,
            "type": "file",
            "filename": "/tmp/getnbacomplayerlist2",
            "use_raw": True,
            "test": True,
            "groups": ["dev", "file"],
        },
        # Slack or other exporters could go here if you have them in your registry
    ]

    def set_url(self):
        """
        Build the 'playerindex' URL for a specified or auto-detected 'season'.
        Example: '2022' -> '2022-23'.
        """
        season = self.add_dash_to_season(self.opts["season"])
        seasontype = "Regular%20Season"
        historical = "0"

        self.url = (
            "https://stats.nba.com/stats/playerindex?"
            "College=&Country=&DraftPick=&DraftRound=&DraftYear=&Height=&"
            f"Historical={historical}&LeagueID=00&Season={season}&"
            f"SeasonType={seasontype}&TeamID=0&Weight="
        )
        logger.info("NBA.com PlayerList URL: %s", self.url)

    def set_headers(self):
        """
        Set standard NBA stats headers to mimic a typical browser request.
        """
        self.headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Host": "stats.nba.com",
            "Origin": "https://www.nba.com",
            "Referer": "https://www.nba.com/",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "Linux",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/90.0.4430.85 Safari/537.36"
            ),
        }
        logger.debug("Headers set for PlayerList request: %s", self.headers)

    def validate_download_data(self):
        """
        Verify the JSON has 'resultSets' and it's not empty.
        """
        if "resultSets" not in self.decoded_data:
            logger.error("'resultSets' missing in decoded data.")
            raise DownloadDataException("[resultSets] missing in decoded data")

        if not self.decoded_data["resultSets"]:
            logger.error("ResultSets is an empty list.")
            raise DownloadDataException("[resultSets] is empty")

        logger.info("Found resultSets in the player list data. Possibly more validation needed here.")

    def should_save_data(self):
        """
        Decide if we want to actually save the data. 
        Right now, returns True by default.
        """
        logger.info("Defaulting to True for should_save_data().")
        return True

    def add_dash_to_season(self, season_str):
        """
        If season is '2022' -> '2022-23'. If it already has a dash, return as is.
        """
        if "-" in season_str:
            return season_str
        year_int = int(season_str)
        return f"{season_str}-{str(year_int + 1)[-2:]}"

    ##################################################################
    # Override get_scraper_stats() to include # of players from rowSet, plus season
    ##################################################################
    def get_scraper_stats(self):
        """
        Return fields for the final SCRAPER_STATS line: 
        e.g. number of players, and the 'season' we used.
        """
        records_found = 0
        try:
            # example: self.decoded_data["resultSets"][0]["rowSet"]
            first_rs = self.decoded_data["resultSets"][0]
            rowset = first_rs.get("rowSet", [])
            records_found = len(rowset)
        except (IndexError, KeyError, TypeError):
            pass

        # get the season from self.opts
        season = self.opts.get("season", "unknown")

        return {
            "records_found": records_found,
            "season": season,
        }

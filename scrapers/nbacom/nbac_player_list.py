# scrapers/nba_com_player_list.py

import os
import logging
from datetime import datetime

from ..scraper_base import ScraperBase, ExportMode
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaComPlayerList(ScraperBase):
    """
    Fetches NBA player list from stats.nba.com using the 'playerindex' endpoint.
    Uses additional_opts = ["nba_season_today"] to auto-populate 'season' if not provided.
    """

    # Enable proxy usage if needed
    proxy_enabled = True
    header_profile = "stats"
    # If 'season' is missing, we derive it from today's date
    additional_opts = ["nba_season_today"]

    # Exporters referencing the new "export_mode" approach
    exporters = [
        {
            "type": "gcs",
            "key": "nbacom/player-list/%(season)s/log/%(time)s.json",
            "export_mode": ExportMode.RAW, 
            "groups": ["prod", "s3", "gcs"],
        },
        {
            "type": "gcs",
            "check_should_save": True,
            "key": "nbacom/player-list/%(season)s/current/current.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "s3", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomplayerlist",
            "export_mode": ExportMode.RAW,
            "groups": ["dev", "file"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomplayerlist%(season)s",
            "export_mode": ExportMode.DECODED,  # Previously "use_decoded_data": True
            "pretty_print": True,
            "groups": ["dev", "test", "file"],
        },
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
        # https://stats.nba.com/stats/playerindex?
        # College=&Country=&DraftPick=&DraftRound=&DraftYear=&Height=&
        # Historical=1&LeagueID=00&Season=2024-25&SeasonType=Playoffs&TeamID=0&Weight=

        logger.info("NBA.com PlayerList URL: %s", self.url)

    def validate_download_data(self):
        """
        Verify the JSON has 'resultSets' and it's not empty.
        Raise DownloadDataException if missing or empty.
        """
        if "resultSets" not in self.decoded_data:
            logger.error("'resultSets' missing in decoded data.")
            raise DownloadDataException("[resultSets] missing in decoded data")

        if not self.decoded_data["resultSets"]:
            logger.error("ResultSets is an empty list.")
            raise DownloadDataException("[resultSets] is empty")

        logger.info("Found resultSets in the player list data. Possibly more validation needed.")

    def should_save_data(self):
        """
        Decide if we want to actually save the data.
        Currently returns True by default.
        """
        logger.info("Defaulting to True for should_save_data().")
        return True

    def add_dash_to_season(self, season_str):
        """
        If '2022' -> '2022-23'. If it already has a dash, return as is.
        """
        if "-" in season_str:
            return season_str
        year_int = int(season_str)
        return f"{season_str}-{str(year_int + 1)[-2:]}"

    def get_scraper_stats(self):
        """
        Return fields for the final SCRAPER_STATS line.
        e.g., # of players from rowSet, plus season from self.opts.
        """
        records_found = 0
        try:
            first_rs = self.decoded_data["resultSets"][0]
            rowset = first_rs.get("rowSet", [])
            records_found = len(rowset)
        except (IndexError, KeyError, TypeError):
            pass

        season = self.opts.get("season", "unknown")
        return {
            "records_found": records_found,
            "season": season,
        }


##############################################################################
# Cloud Function Entry Point
##############################################################################
def gcf_entry(request):
    """
    Google Cloud Function (HTTP) entry point for NBA.com PlayerList.
    Example usage:
      GET .../NbaComPlayerList?season=2022&group=prod
      or if season is absent, 'nba_season_today' from additional_opts sets it
    """
    # parse query params
    season = request.args.get("season", "")  # might be blank, uses "nba_season_today"
    group = request.args.get("group", "prod")

    opts = {
        "season": season,
        "group": group
    }

    scraper = GetNbaComPlayerList()
    result = scraper.run(opts)

    return f"PlayerList run complete. Found result: {result}", 200


##############################################################################
# Local CLI Usage
##############################################################################
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run NBA.com PlayerList locally")
    parser.add_argument("--season", default="2011", help="e.g., 2022 (will auto-add dash => 2022-23). If omitted, uses 'nba_season_today'.")
    parser.add_argument("--group", default="test", help="Which exporter group to run (dev/test/prod)")
    args = parser.parse_args()

    opts = vars(args)
    scraper = GetNbaComPlayerList()
    scraper.run(opts)

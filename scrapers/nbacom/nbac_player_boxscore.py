# scrapers/nba_com_player_boxscore.py

import os
import logging
from datetime import datetime

from ..scraper_base import ScraperBase, ExportMode
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaComPlayerBoxscore(ScraperBase):
    """
    Scraper for the leaguegamelog endpoint on stats.nba.com, focusing on player boxscores.

    Usage example (local CLI):
      python nba_com_player_boxscore.py --gamedate=2022-01-01
    """

    # Required & optional opts
    required_opts = ["gamedate"]
    additional_opts = ["nba_season_from_gamedate", "nba_seasontype_from_gamedate"]
    header_profile = "stats"
    # Proxy usage if we need to avoid blocked IPs
    proxy_enabled = True

    # Exporters using the new export_mode approach
    # Currently all default to "RAW" to mimic the old 'use_raw=True'
    exporters = [
        {
            "type": "gcs",
            "key": "nbacom/player-boxscore/%(season)s/%(gamedate)s/%(time)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomplayerboxscore2.json",
            "export_mode": ExportMode.RAW,
            "groups": ["test", "file"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomplayerboxscore3.json",
            "export_mode": ExportMode.RAW,
            "groups": ["test", "file2"],
        }
    ]

    def set_url(self):
        """
        Construct the leaguegamelog URL using self.opts:
         - self.opts["gamedate"]
         - self.opts["season"]
         - self.opts["season_type"]

        e.g.:
          https://stats.nba.com/stats/leaguegamelog?
            Counter=1000&DateFrom=2022-01-01&DateTo=2022-01-01&
            Direction=DESC&LeagueID=00&PlayerOrTeam=P&Season=2021-22&
            SeasonType=Regular+Season&Sorter=DATE
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

    def validate_download_data(self):
        """
        Ensure 'resultSets' with 'rowSet' exist and are non-empty.
        Raise DownloadDataException if invalid.
        """
        if "resultSets" not in self.decoded_data:
            logger.error("Missing 'resultSets' in decoded data.")
            raise DownloadDataException("[resultSets] not found in decoded data.")

        if not self.decoded_data["resultSets"]:
            logger.error("'resultSets' is empty.")
            raise DownloadDataException("[resultSets] is empty.")

        if "rowSet" not in self.decoded_data["resultSets"][0]:
            logger.error("Missing 'rowSet' in [resultSets][0].")
            raise DownloadDataException("[rowSet] not found in [resultSets][0].")

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
        logger.info("Should we save data? Found %d players => %s", players_found, (players_found > 0))
        return players_found > 0

    @staticmethod
    def add_dash_to_season(season_str):
        """
        If '2022' -> '2022-23'. If there's already a dash, return as-is.
        """
        if "-" in season_str:
            return season_str
        year_int = int(season_str)
        return f"{season_str}-{str(year_int + 1)[-2:]}"

    def get_scraper_stats(self):
        """
        Return fields for the final SCRAPER_STATS line: number of players found,
        plus gamedate, season, and season_type if available.
        """
        rowset = []
        try:
            rowset = self.decoded_data["resultSets"][0]["rowSet"]
        except (KeyError, IndexError, TypeError):
            pass

        records_found = len(rowset)
        gamedate = self.opts.get("gamedate", "unknown")
        season = self.opts.get("season", "unknown")
        season_type = self.opts.get("season_type", "unknown")

        return {
            "records_found": records_found,
            "gamedate": gamedate,
            "season": season,
            "season_type": season_type
        }


##############################################################################
# Cloud Function Entry Point
##############################################################################
def gcf_entry(request):
    """
    Google Cloud Function (HTTP) entry point.

    Example request:
      GET .../NbaComPlayerBoxscore?gamedate=2022-01-01&group=prod
    """
    gamedate = request.args.get("gamedate", "2022-01-01")
    group = request.args.get("group", "prod")

    opts = {
        "gamedate": gamedate,
        "group": group
    }

    scraper = GetNbaComPlayerBoxscore()
    result = scraper.run(opts)

    return f"PlayerBoxscore run complete. Found result: {result}", 200


##############################################################################
# Local CLI Usage
##############################################################################
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run NBA Player Boxscore locally")
    parser.add_argument("--gamedate", required=True, help="YYYY-MM-DD")
    parser.add_argument("--group", default="test", help="Which exporter group to run (e.g. dev/test/prod)")
    args = parser.parse_args()

    opts = vars(args)
    scraper = GetNbaComPlayerBoxscore()
    scraper.run(opts)

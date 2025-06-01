# scrapers/nba_com_schedule.py

import os
import logging
from datetime import datetime

from .scraper_base import ScraperBase
from .utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")

###############################################################################
# Main Scraper Class
###############################################################################
class GetNbaComSchedule(ScraperBase):
    """
    Fetches NBA schedule data from cdn.nba.com, then slices it by date/team if desired.
    """

    url = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"
    use_proxy = True

    # If you have a local environment variable check
    # e.g. exporter_test = is_local() and True, you can keep that
    # but let's remove references to is_local() for simplicity if not needed
    exporter_test = False

    # Exporters referencing your registry-based approach
    exporters = [
        {
            "type": "s3",
            "check_should_save": True,
            "key": "nbacom/season-schedule/%(season)s/log/%(time)s.json",
            "use_raw": True,
            "groups": ["prod", "s3"],
        },
        {
            "type": "s3",
            "check_should_save": True,
            "key": "nbacom/season-schedule/%(season)s/current/current.json",
            "use_raw": True,
            "groups": ["prod", "s3"],
        },
        {
            "type": "s3",
            "check_should_save": True,
            "key": "nbacom/season-schedule/%(season)s/current/sliced-schedule.json",
            "data_key": "slice_date_small",
            "groups": ["prod", "s3"],
        },
        {
            "type": "s3",
            "check_should_save": True,
            "key": "nbacom/season-schedule/%(season)s/current/sliced-gamedate-schedule.json",
            "data_key": "slice_date_large",
            "groups": ["prod", "s3"],
        },
        {
            "type": "s3",
            "check_should_save": True,
            "key": "nbacom/season-schedule/%(season)s/current/sliced-team-schedule.json",
            "data_key": "slice_team_large",
            "groups": ["prod", "s3"],
        },
        {
            "active": True,
            "type": "file",
            "filename": "/tmp/getnbacomschedule",
            "use_source": True,
            "test": True,
            "groups": ["test", "file"],
        },
    ]
    
    def validate_download_data(self):
        """
        Validate the JSON structure: leagueSchedule -> seasonYear, gameDates.
        Raise DownloadDataException if something is missing or incomplete.
        """
        if "leagueSchedule" not in self.decoded_data:
            logger.error("Missing 'leagueSchedule' key in decoded data.")
            raise DownloadDataException("[leagueSchedule] not in source data")
        
        ls = self.decoded_data["leagueSchedule"]
        if "seasonYear" not in ls:
            logger.error("'seasonYear' not found in leagueSchedule.")
            raise DownloadDataException("[leagueSchedule][seasonYear] not in source data")
        
        if "gameDates" not in ls:
            logger.error("'gameDates' not found in leagueSchedule.")
            raise DownloadDataException("[leagueSchedule][gameDates] not in source data")
        
        if len(ls["gameDates"]) < 50:
            logger.warning("Only %d gameDates found, expected more.", len(ls["gameDates"]))
            raise DownloadDataException("[leagueSchedule][gameDates] does not have enough data")
        
        logger.info("Download data is valid. Found %d gameDates in season=%s",
                    len(ls["gameDates"]), ls["seasonYear"])

    def set_opts_from_data(self):
        """
        Extract 'seasonYear' from the JSON and set self.opts["season"] automatically.
        Ensures the 'season' used in exporters matches the actual JSON data.
        """
        json_season = self.decoded_data["leagueSchedule"]["seasonYear"]
        self.opts["season"] = json_season.split("-")[0]
        logger.info("Set self.opts['season'] to %s based on schedule data.", self.opts["season"])
        
    def slice_data(self):
        """
        Call the inlined slicing functions to create subsets of the schedule data.
        We'll store them in self.data[...] so the base class can export them via 'data_key'.
        """
        logger.info("Starting slice_data for NBA schedule.")
        self.data["slice_date_small"] = slice_nba_season_by_date_small(self.decoded_data, self.opts)
        self.data["slice_date_large"] = slice_nba_season_by_date_large(self.decoded_data, self.opts)
        self.data["slice_team_large"] = slice_nba_season_by_team_large(self.decoded_data, self.opts)
        logger.info("Finished slice_data. Created 3 slices for date/team usage.")
    
    def get_return_value(self):
        """
        Return a minimal object.
        E.g. integer season from 'seasonYear'.
        """
        year_str = self.decoded_data["leagueSchedule"]["seasonYear"].split("-")[0]
        logger.info("Returning year_str=%s from get_return_value()", year_str)
        return {
            "season": year_str
        }

    def should_save_data(self):
        """
        Optionally ensure the user-supplied 'season' (if any) matches the JSON.
        If there's no mismatch, return True to proceed with exports.
        """
        if "season" not in self.opts:
            logger.error("'season' not set in opts, cannot save data.")
            raise DownloadDataException("No 'season' set in opts, cannot save.")
        
        json_season = self.decoded_data["leagueSchedule"]["seasonYear"]
        if not json_season.startswith(self.opts["season"]):
            logger.error("Mismatch: JSON season [%s] vs. opts season [%s].",
                         json_season, self.opts["season"])
            raise DownloadDataException(
                f"Mismatch: JSON season [{json_season}] vs. opts season [{self.opts['season']}]"
            )
        
        logger.info("Schedule data matches season=%s, proceeding to export.", self.opts["season"])
        return True
    
    ##################################################################
    # Override get_scraper_stats() to track # of gameDates and final season
    ##################################################################
    def get_scraper_stats(self):
        """
        Return fields for the final SCRAPER_STATS line: # of gameDates from the schedule, plus the season.
        """
        league_schedule = self.decoded_data.get("leagueSchedule", {})
        game_dates = league_schedule.get("gameDates", [])
        game_dates_count = len(game_dates)

        # The final season set by set_opts_from_data()
        season = self.opts.get("season", "unknown")

        return {
            "records_found": game_dates_count,  # e.g. how many gameDates
            "season": season
        }


###############################################################################
# Inline Slicer Logic at the Bottom
###############################################################################
PRE_SEASON = "001"
REGULAR_SEASON = "002"
ALL_STAR_GAME = "003"
PLAY_IN = "005"
PLAYOFFS = "004"


def get_seasontype_from_game_id(game_id):
    if game_id.startswith(PRE_SEASON):
        seasontype = "pre"
    elif game_id.startswith(REGULAR_SEASON):
        seasontype = "regular"
    elif game_id.startswith(ALL_STAR_GAME):
        seasontype = "allstar"
    elif game_id.startswith(PLAY_IN):
        seasontype = "playin"
    elif game_id.startswith(PLAYOFFS):
        seasontype = "playoffs"
    else:
        seasontype = ""
    return seasontype


def slice_nba_season_seasontype_by_date(data, opts):
    sliced_data = {
        "last_updated": data["meta"]["time"],
        "season": opts["season"],
        "dates": {}
    }
    
    for date_data in data["leagueSchedule"]["gameDates"]:
        date = date_data["gameDate"].split(" ")[0]
        date_string = datetime.strptime(date, "%m/%d/%Y").strftime("%Y-%m-%d")
        game_id = date_data["games"][0]["gameId"]
        sliced_data["dates"][date_string] = get_seasontype_from_game_id(game_id)

    return sliced_data


def slice_nba_season_game_count_by_date(data, opts):
    sliced_data = {
        "last_updated": data["meta"]["time"],
        "season": opts["season"],
        "dates": {},
    }

    for date_data in data["leagueSchedule"]["gameDates"]:
        date = date_data["gameDate"].split(" ")[0]
        date_string = datetime.strptime(date, "%m/%d/%Y").strftime("%Y-%m-%d")

        game_count = 0
        for game in date_data["games"]:
            game_id = game["gameId"]
            # skip pre-season and all-star
            if game_id.startswith(PRE_SEASON) or game_id.startswith(ALL_STAR_GAME):
                continue
            game_count += 1
        
        if game_count > 0:
            sliced_data["dates"][date_string] = game_count

    return sliced_data


def slice_nba_season_by_date_small(data, opts):
    sliced_data = {
        "meta": data["meta"],
        "season": opts["season"],
        "dates": {},
        "games_by_date": {},
        "first_gamedate": "",
        "last_gamedate": ""
    }

    for date_data in data["leagueSchedule"]["gameDates"]:
        date = date_data["gameDate"].split(" ")[0]
        date_string = datetime.strptime(date, "%m/%d/%Y").strftime("%Y-%m-%d")

        games_data = []
        game_count = 0
        for game in date_data["games"]:
            game_id = game["gameId"]
            if game_id.startswith(PRE_SEASON) or game_id.startswith(ALL_STAR_GAME):
                continue
            
            game_count += 1
            game_data = {
                "game_code": game["gameCode"],
            }
            games_data.append(game_data)
            sliced_data["dates"][date_string] = games_data
        
        if game_count > 0:
            sliced_data["games_by_date"][date_string] = game_count

    dates_with_games = list(sliced_data["games_by_date"].keys())
    if dates_with_games:
        sliced_data["first_gamedate"] = dates_with_games[0]
        sliced_data["last_gamedate"] = dates_with_games[-1]

    return sliced_data


def slice_nba_season_by_date_large(data, opts):
    sliced_data = {
        "meta": data["meta"],
        "season": opts["season"],
        "dates": {},
    }

    for date_data in data["leagueSchedule"]["gameDates"]:
        date = date_data["gameDate"].split(" ")[0]
        date_string = datetime.strptime(date, "%m/%d/%Y").strftime("%Y-%m-%d")

        games_data = []
        for game in date_data["games"]:
            game_id = game["gameId"]
            if game_id.startswith(PRE_SEASON) or game_id.startswith(ALL_STAR_GAME):
                continue

            game_data = {
                "id": game["gameId"],
                "signature": game["gameCode"],
                "home": game["homeTeam"]["teamTricode"],
                "away": game["awayTeam"]["teamTricode"],
                "week": game["weekNumber"],
                "date": date_string,
                "datetime_utc": game["gameDateTimeUTC"],
                "game_status": game["gameStatus"],
                "postponed_status": game["postponedStatus"],
                "if_necessary": game["ifNecessary"],
            }
            games_data.append(game_data)
            sliced_data["dates"][date_string] = games_data

    return sliced_data


def slice_nba_season_by_team_large(data, opts):
    sliced_data = {
        "meta": data["meta"],
        "season": opts["season"],
        "teams": {},
    }

    for date_data in data["leagueSchedule"]["gameDates"]:
        date = date_data["gameDate"].split(" ")[0]
        date_string = datetime.strptime(date, "%m/%d/%Y").strftime("%Y-%m-%d")

        for game in date_data["games"]:
            game_id = game["gameId"]
            if game_id.startswith(PRE_SEASON) or game_id.startswith(ALL_STAR_GAME):
                continue

            hometeam = game["homeTeam"]["teamTricode"]
            awayteam = game["awayTeam"]["teamTricode"]

            game_data = {
                "id": game["gameId"],
                "signature": game["gameCode"],
                "home": hometeam,
                "away": awayteam,
                "week": game["weekNumber"],
                "date": date_string,
                "datetime_utc": game["gameDateTimeUTC"],
                "game_status": game["gameStatus"],
                "postponed_status": game["postponedStatus"],
                "if_necessary": game["ifNecessary"],
            }
            if hometeam not in sliced_data["teams"]:
                sliced_data["teams"][hometeam] = [game_data]
            else:
                sliced_data["teams"][hometeam].append(game_data)
            
            if awayteam not in sliced_data["teams"]:
                sliced_data["teams"][awayteam] = [game_data]
            else:
                sliced_data["teams"][awayteam].append(game_data)

    return sliced_data


def slice_nba_season_games_by_date(source_data):
    games_by_date = {}
    for date_str in source_data["dates"]:
        games_by_date[date_str] = len(source_data["dates"][date_str])
    
    return games_by_date

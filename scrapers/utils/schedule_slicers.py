# analytics/schedule_slicers.py
"""
Reusable schedule‑slicer helpers
--------------------------------
All five slice shapes that once lived inside nbac_schedule.py.

Usage example
-------------
from analytics.schedule_slicers import (
    slice_nba_season_by_date_small,
    slice_nba_season_by_date_large,
    slice_nba_season_by_team_large,
)
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Dict, List


class NbaGameType(str, enum.Enum):
    PRE_SEASON = "001"
    REGULAR_SEASON = "002"
    ALL_STAR_GAME = "003"
    PLAY_IN = "005"
    PLAYOFFS = "004"


# --------------------------- helpers --------------------------- #
def _date_iso(date_str_mmddyyyy: str) -> str:
    return datetime.strptime(date_str_mmddyyyy, "%m/%d/%Y").strftime("%Y-%m-%d")


def get_seasontype_from_game_id(game_id: str) -> str:
    if game_id.startswith(NbaGameType.PRE_SEASON):
        return "pre"
    if game_id.startswith(NbaGameType.REGULAR_SEASON):
        return "regular"
    if game_id.startswith(NbaGameType.ALL_STAR_GAME):
        return "allstar"
    if game_id.startswith(NbaGameType.PLAY_IN):
        return "playin"
    if game_id.startswith(NbaGameType.PLAYOFFS):
        return "playoffs"
    return ""


# ------------------------- slicers ----------------------------- #
def slice_nba_season_seasontype_by_date(data: dict, opts: dict) -> dict:
    out: Dict = {"last_updated": data["meta"]["time"], "season": opts["season"], "dates": {}}
    for d in data["leagueSchedule"]["gameDates"]:
        iso = _date_iso(d["gameDate"].split(" ")[0])
        gid = d["games"][0]["gameId"]
        out["dates"][iso] = get_seasontype_from_game_id(gid)
    return out


def slice_nba_season_game_count_by_date(data: dict, opts: dict) -> dict:
    out: Dict = {"last_updated": data["meta"]["time"], "season": opts["season"], "dates": {}}
    for d in data["leagueSchedule"]["gameDates"]:
        iso = _date_iso(d["gameDate"].split(" ")[0])
        count = sum(
            1
            for g in d["games"]
            if not g["gameId"].startswith((NbaGameType.PRE_SEASON, NbaGameType.ALL_STAR_GAME))
        )
        if count:
            out["dates"][iso] = count
    return out


def slice_nba_season_by_date_small(data: dict, opts: dict) -> dict:
    out: Dict = {
        "meta": data["meta"],
        "season": opts["season"],
        "dates": {},
        "games_by_date": {},
        "first_gamedate": "",
        "last_gamedate": "",
    }
    for d in data["leagueSchedule"]["gameDates"]:
        iso = _date_iso(d["gameDate"].split(" ")[0])
        games: List[Dict] = []
        for g in d["games"]:
            gid = g["gameId"]
            if gid.startswith((NbaGameType.PRE_SEASON, NbaGameType.ALL_STAR_GAME)):
                continue
            games.append({"game_code": g["gameCode"]})
        if games:
            out["dates"][iso] = games
            out["games_by_date"][iso] = len(games)
    if out["games_by_date"]:
        dates = list(out["games_by_date"].keys())
        out["first_gamedate"], out["last_gamedate"] = dates[0], dates[-1]
    return out


def slice_nba_season_by_date_large(data: dict, opts: dict) -> dict:
    out: Dict = {"meta": data["meta"], "season": opts["season"], "dates": {}}
    for d in data["leagueSchedule"]["gameDates"]:
        iso = _date_iso(d["gameDate"].split(" ")[0])
        games: List[Dict] = []
        for g in d["games"]:
            gid = g["gameId"]
            if gid.startswith((NbaGameType.PRE_SEASON, NbaGameType.ALL_STAR_GAME)):
                continue
            games.append(
                {
                    "id": gid,
                    "signature": g["gameCode"],
                    "home": g["homeTeam"]["teamTricode"],
                    "away": g["awayTeam"]["teamTricode"],
                    "week": g["weekNumber"],
                    "date": iso,
                    "datetime_utc": g["gameDateTimeUTC"],
                    "game_status": g["gameStatus"],
                    "postponed_status": g["postponedStatus"],
                    "if_necessary": g["ifNecessary"],
                }
            )
        if games:
            out["dates"][iso] = games
    return out


def slice_nba_season_by_team_large(data: dict, opts: dict) -> dict:
    out: Dict = {"meta": data["meta"], "season": opts["season"], "teams": {}}
    for d in data["leagueSchedule"]["gameDates"]:
        iso = _date_iso(d["gameDate"].split(" ")[0])
        for g in d["games"]:
            gid = g["gameId"]
            if gid.startswith((NbaGameType.PRE_SEASON, NbaGameType.ALL_STAR_GAME)):
                continue
            rec = {
                "id": gid,
                "signature": g["gameCode"],
                "home": g["homeTeam"]["teamTricode"],
                "away": g["awayTeam"]["teamTricode"],
                "week": g["weekNumber"],
                "date": iso,
                "datetime_utc": g["gameDateTimeUTC"],
                "game_status": g["gameStatus"],
                "postponed_status": g["postponedStatus"],
                "if_necessary": g["ifNecessary"],
            }
            out["teams"].setdefault(rec["home"], []).append(rec)
            out["teams"].setdefault(rec["away"], []).append(rec)
    return out

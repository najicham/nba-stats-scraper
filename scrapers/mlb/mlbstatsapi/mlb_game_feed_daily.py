"""
File: scrapers/mlb/mlbstatsapi/mlb_game_feed_daily.py

MLB Stats API - Game Feed Daily Batch (per-pitch)                v1.0 - 2026-04-13
--------------------------------------------------------------------------------
Daily batch scraper that fetches per-pitch data for ALL Final games on a given
date, using the MLB Stats API /game/{pk}/feed/live endpoint.

Unlike mlb_game_feed.py (single game_pk, summary output), this scraper:
  1. Fetches the schedule for the target date
  2. Filters to games with detailedState in ('Final', 'Completed Early', 'Game Over')
  3. For each game, fetches the feed/live endpoint
  4. Emits one row per pitch with full physics + result classification

Output shape (single JSON file per date):
{
  "date": "2026-04-12",
  "timestamp": "2026-04-13T03:05:12Z",
  "games_processed": 15,
  "games_skipped": 0,
  "total_pitches": 4328,
  "pitches": [
    { "game_pk": 745263, "game_date": "2026-04-12", "pitcher_id": 543037, ... },
    ...
  ]
}

Why MLB Stats API (not Baseball Savant / pybaseball):
  - Available immediately after games end (Baseball Savant has a 4-12h index lag)
  - Richer play-event classification (details.code is canonical)
  - No cloud-IP blocking
  - No external dependency (pybaseball)

Usage:
  python scrapers/mlb/mlbstatsapi/mlb_game_feed_daily.py --debug
  python scrapers/mlb/mlbstatsapi/mlb_game_feed_daily.py --date 2026-04-12 --debug
"""

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

try:
    from ...scraper_base import DownloadType, ExportMode, ScraperBase
    from ...scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper

logger = logging.getLogger(__name__)

_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

# MLB Stats API `details.code` classification.
# See: https://statsapi.mlb.com (no public enum reference; codes observed in production feeds)
_BALL_CODES = frozenset({"B", "*B", "I", "V", "P", "H"})       # includes intent ball, auto ball, pitchout, HBP
_CALLED_STRIKE_CODES = frozenset({"C"})
_SWINGING_STRIKE_CODES = frozenset({"S", "W", "Q"})             # S, blocked-S (W), swing-and-miss (Q variant)
_FOUL_CODES = frozenset({"F", "T", "L", "R"})                   # foul, foul-tip, foul-bunt, foul (rare variant)
_IN_PLAY_CODES = frozenset({"X", "D", "E"})                     # out, no-out, run(s)
_MISSED_BUNT_CODES = frozenset({"M"})                           # treat as swinging strike

# Game states that indicate the game is complete enough to pull pitch data
_TERMINAL_STATES = frozenset({
    "Final",
    "Completed Early",
    "Game Over",
    "Final: Tied",       # rare — suspended/tied games
})


def _norm_lookup(name: str) -> str:
    """Normalize pitcher name to lookup key matching statcast_pitcher_daily format
    (lowercase alphanumeric, no spaces/punctuation). 'Sean Manaea' → 'seanmanaea'."""
    if not name:
        return ""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _classify_pitch(details_code: Optional[str]) -> Dict[str, bool]:
    """Classify a pitch by its MLB Stats API details.code."""
    code = details_code or ""
    is_swinging_strike = code in _SWINGING_STRIKE_CODES or code in _MISSED_BUNT_CODES
    is_called_strike = code in _CALLED_STRIKE_CODES
    is_foul = code in _FOUL_CODES
    is_ball = code in _BALL_CODES
    is_in_play = code in _IN_PLAY_CODES
    is_swing = is_swinging_strike or is_foul or is_in_play
    return {
        "is_swinging_strike": is_swinging_strike,
        "is_called_strike": is_called_strike,
        "is_foul": is_foul,
        "is_ball": is_ball,
        "is_in_play": is_in_play,
        "is_swing": is_swing,
        "is_whiff": is_swinging_strike,
    }


class MlbGameFeedDailyScraper(ScraperBase, ScraperFlaskMixin):
    """Daily per-pitch scraper: fetches schedule + all game feeds for a date."""

    scraper_name = "mlb_game_feed_daily"
    required_params: List[str] = []
    optional_params = {"date": None}
    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled = False

    exporters = [
        {
            "type": "gcs",
            "key": "mlb-stats-api/game-feed-daily/%(date)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_game_feed_daily_%(date)s_%(timestamp)s.json",
            "pretty_print": False,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        if not self.opts.get("date"):
            self.opts["date"] = datetime.now(timezone.utc).date().isoformat()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    def set_url(self) -> None:
        # Not used — we override download_and_decode. Set a placeholder for the
        # base class's URL logging.
        self.url = f"{_SCHEDULE_URL}?sportId=1&date={self.opts['date']}"

    def set_headers(self) -> None:
        self.headers = {
            "User-Agent": "mlb-game-feed-daily-scraper/1.0",
            "Accept": "application/json",
        }

    def download_and_decode(self) -> None:
        """Fetch schedule + each Final game's feed, extract per-pitch rows."""
        target_date = self.opts["date"]
        logger.info("Fetching game feeds for %s", target_date)

        game_pks = self._fetch_final_game_pks(target_date)
        logger.info("Found %d Final games for %s", len(game_pks), target_date)

        all_pitches: List[Dict[str, Any]] = []
        processed = 0
        skipped = 0

        for game_pk in game_pks:
            try:
                pitches = self._fetch_and_extract_pitches(game_pk, target_date)
                all_pitches.extend(pitches)
                processed += 1
                logger.info("Game %s: %d pitches extracted", game_pk, len(pitches))
            except Exception as exc:
                logger.error("Game %s failed: %s", game_pk, exc)
                skipped += 1

        self.decoded_data = {
            "date": target_date,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "games_processed": processed,
            "games_skipped": skipped,
            "total_pitches": len(all_pitches),
            "pitches": all_pitches,
        }

    # ------------------------------------------------------------------ #
    # Schedule + feed helpers
    # ------------------------------------------------------------------ #

    def _fetch_final_game_pks(self, target_date: str) -> List[int]:
        """Fetch schedule and return game_pks whose detailedState is terminal."""
        params = {
            "sportId": 1,
            "date": target_date,
            "gameTypes": "R,P",
        }
        resp = requests.get(_SCHEDULE_URL, params=params, headers=self.headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        pks: List[int] = []
        for date_block in data.get("dates", []):
            for game in date_block.get("games", []):
                status = game.get("status", {}).get("detailedState", "")
                pk = game.get("gamePk")
                if pk and status in _TERMINAL_STATES:
                    pks.append(int(pk))
        return pks

    def _fetch_and_extract_pitches(self, game_pk: int, game_date: str) -> List[Dict[str, Any]]:
        """Fetch one game's feed/live and extract all pitch events."""
        url = _FEED_URL.format(game_pk=game_pk)
        resp = requests.get(url, headers=self.headers, timeout=45)
        resp.raise_for_status()
        feed = resp.json()

        live = feed.get("liveData", {})
        all_plays = live.get("plays", {}).get("allPlays", [])

        pitches: List[Dict[str, Any]] = []
        for play in all_plays:
            matchup = play.get("matchup", {})
            about = play.get("about", {})
            result = play.get("result", {})
            play_events = play.get("playEvents", [])

            pitcher = matchup.get("pitcher", {}) or {}
            batter = matchup.get("batter", {}) or {}
            pitcher_id = pitcher.get("id")
            pitcher_name = pitcher.get("fullName", "")
            batter_id = batter.get("id")
            batter_name = batter.get("fullName", "")
            batter_side = (matchup.get("batSide", {}) or {}).get("code")

            at_bat_index = about.get("atBatIndex")
            inning = about.get("inning")
            half_inning = about.get("halfInning")
            at_bat_event = result.get("event")

            # Find terminal pitch index (last isPitch event in the playEvents)
            pitch_event_indices = [
                i for i, pe in enumerate(play_events) if pe.get("isPitch")
            ]
            terminal_idx = pitch_event_indices[-1] if pitch_event_indices else None

            for i, pe in enumerate(play_events):
                if not pe.get("isPitch"):
                    continue

                details = pe.get("details", {}) or {}
                pitch_data = pe.get("pitchData", {}) or {}
                count = pe.get("count", {}) or {}
                pitch_type = details.get("type", {}) or {}

                code = details.get("code")
                classification = _classify_pitch(code)

                zone = pitch_data.get("zone")
                is_in_zone = isinstance(zone, int) and 1 <= zone <= 9
                is_chase = classification["is_swing"] and zone is not None and not is_in_zone

                pitches.append({
                    "game_date": game_date,
                    "game_pk": int(game_pk),
                    "pitcher_id": int(pitcher_id) if pitcher_id is not None else None,
                    "pitcher_name": pitcher_name,
                    "pitcher_lookup": _norm_lookup(pitcher_name),
                    "batter_id": int(batter_id) if batter_id is not None else None,
                    "batter_name": batter_name,
                    "batter_side": batter_side,
                    "pitch_type_code": pitch_type.get("code"),
                    "pitch_type_desc": pitch_type.get("description"),
                    "velocity": pitch_data.get("startSpeed"),
                    "spin_rate": (pitch_data.get("breaks", {}) or {}).get("spinRate")
                                  or pitch_data.get("spinRate"),
                    "extension": pitch_data.get("extension"),
                    "zone": zone if isinstance(zone, int) else None,
                    "result_description": details.get("description"),
                    "is_swinging_strike": classification["is_swinging_strike"],
                    "is_called_strike": classification["is_called_strike"],
                    "is_foul": classification["is_foul"],
                    "is_ball": classification["is_ball"],
                    "is_in_play": classification["is_in_play"],
                    "is_swing": classification["is_swing"],
                    "is_in_zone": is_in_zone,
                    "is_chase": is_chase,
                    "is_whiff": classification["is_whiff"],
                    "count_balls": count.get("balls"),
                    "count_strikes": count.get("strikes"),
                    "inning": inning,
                    "half_inning": half_inning,
                    "at_bat_index": at_bat_index,
                    "pitch_number": pe.get("pitchNumber"),
                    "at_bat_event": at_bat_event if i == terminal_idx else None,
                    "is_at_bat_end": i == terminal_idx,
                })

        return pitches

    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict):
            raise ValueError("Game feed daily response malformed")
        if "pitches" not in self.decoded_data:
            raise ValueError("Missing 'pitches' in output")

    def transform_data(self) -> None:
        self.data = self.decoded_data

    def get_scraper_stats(self) -> dict:
        return {
            "date": self.opts.get("date"),
            "games_processed": self.data.get("games_processed", 0),
            "games_skipped": self.data.get("games_skipped", 0),
            "total_pitches": self.data.get("total_pitches", 0),
        }


create_app = convert_existing_flask_scraper(MlbGameFeedDailyScraper)

if __name__ == "__main__":
    main = MlbGameFeedDailyScraper.create_cli_and_flask_main()
    main()

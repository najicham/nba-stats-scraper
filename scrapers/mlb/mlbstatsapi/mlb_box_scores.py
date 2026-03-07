"""
File: scrapers/mlb/mlbstatsapi/mlb_box_scores.py

MLB Stats API - Post-Game Box Scores (Pitcher + Batter Stats)       v1.0 - 2026-03-06
--------------------------------------------------------------------------------
Batch scraper that fetches completed games for a date and extracts pitcher and
batter stats from each game's box score.

Two-step process:
1. Query the schedule endpoint to find all completed ("Final") games for a date
2. For each final game, fetch the live feed and extract box score stats

API Endpoints:
- Schedule: https://statsapi.mlb.com/api/v1/schedule?date={date}&sportId=1&hydrate=linescore
- Game Feed: https://statsapi.mlb.com/api/v1.1/game/{gamePk}/feed/live

No authentication required. Free API, cloud-friendly.

Output:
- pitcher_stats: strikeouts, IP, pitches, hits, walks, ER, W/L/S per pitcher
- batter_stats: strikeouts, at-bats, hits, walks, HR, RBI per batter

Usage:
  python scrapers/mlb/mlbstatsapi/mlb_box_scores.py --date 2025-06-15 --debug
  python scrapers/mlb/mlbstatsapi/mlb_box_scores.py --debug  # defaults to yesterday PT
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from ...scraper_base import DownloadType, ExportMode, ScraperBase
    from ...scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper

logger = logging.getLogger(__name__)

# Positions that are NOT batters (exclude pitchers from batter stats)
# DH (10) is included as a batter; P (1) is excluded
PITCHER_POSITION_CODE = "1"


class MlbBoxScoresScraper(ScraperBase, ScraperFlaskMixin):
    """
    Batch scraper for MLB post-game box scores from the official MLB Stats API.

    Fetches all completed games for a given date and extracts:
    - Pitcher stats (K, IP, pitches, hits, walks, ER, W/L/S)
    - Batter stats (K, AB, H, BB, HR, RBI, R)

    This replaces BDL for post-game stat collection.
    """

    # Flask Mixin Configuration
    scraper_name = "mlb_box_scores"
    required_params = ["date"]
    optional_params = {}

    # Scraper config
    required_opts: List[str] = ["date"]
    download_type = DownloadType.JSON
    decode_download_data = False  # We make multiple API calls, build self.data manually
    proxy_enabled: bool = False  # MLB API is cloud-friendly

    # Polite delay between game feed requests (seconds)
    _REQUEST_DELAY = 0.5

    exporters = [
        {
            "type": "gcs",
            "key": "mlb-stats-api/box-scores/%(date)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_box_scores_%(date)s_%(timestamp)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    _SCHEDULE_API = "https://statsapi.mlb.com/api/v1/schedule"
    _GAME_FEED_API = "https://statsapi.mlb.com/api/v1.1/game"

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        # Default to yesterday Pacific time if no date specified
        if not self.opts.get("date"):
            from scrapers.utils.date_utils import get_yesterday_pacific
            self.opts["date"] = get_yesterday_pacific()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    def set_url(self) -> None:
        # Not used directly -- we build URLs in download_and_decode
        self.url = f"{self._SCHEDULE_API}?date={self.opts['date']}&sportId=1&hydrate=linescore"

    def set_headers(self) -> None:
        self.headers = {
            "User-Agent": "mlb-box-scores-scraper/1.0",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------ #
    # Download + Build (overrides the HTTP download pipeline)
    # ------------------------------------------------------------------ #
    def download_and_decode(self) -> None:
        """Fetch schedule + per-game box scores, build self.data directly."""
        import requests

        session = requests.Session()
        session.headers.update(self.headers)

        target_date = self.opts["date"]

        # -------------------------------------------------------------- #
        # Step 1: Fetch schedule to find completed games
        # -------------------------------------------------------------- #
        schedule_url = (
            f"{self._SCHEDULE_API}?date={target_date}&sportId=1"
            f"&hydrate=linescore&gameTypes=R,P"
        )
        logger.info("Fetching MLB schedule for %s: %s", target_date, schedule_url)

        resp = session.get(schedule_url, timeout=30)
        resp.raise_for_status()
        schedule_data = resp.json()

        # Collect all games, identify finals
        all_games: List[Dict[str, Any]] = []
        for date_entry in schedule_data.get("dates", []):
            all_games.extend(date_entry.get("games", []))

        final_games = [
            g for g in all_games
            if g.get("status", {}).get("detailedState") == "Final"
        ]

        games_found = len(all_games)
        games_final = len(final_games)
        logger.info(
            "Schedule: %d games found, %d final for %s",
            games_found, games_final, target_date,
        )

        if games_final == 0:
            logger.warning("No completed games for %s", target_date)
            self.data = {
                "date": target_date,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "games_found": games_found,
                "games_final": 0,
                "pitcher_stats": [],
                "batter_stats": [],
            }
            return

        # -------------------------------------------------------------- #
        # Step 2: Fetch box score for each completed game
        # -------------------------------------------------------------- #
        all_pitcher_stats: List[Dict[str, Any]] = []
        all_batter_stats: List[Dict[str, Any]] = []

        for i, game in enumerate(final_games):
            game_pk = game.get("gamePk")
            if not game_pk:
                continue

            if i > 0:
                time.sleep(self._REQUEST_DELAY)

            feed_url = f"{self._GAME_FEED_API}/{game_pk}/feed/live"
            logger.debug("Fetching game feed: %s", feed_url)

            try:
                feed_resp = session.get(feed_url, timeout=30)
                feed_resp.raise_for_status()
                feed_data = feed_resp.json()
            except Exception as e:
                logger.error("Failed to fetch game %s: %s", game_pk, e)
                continue

            game_data = feed_data.get("gameData", {})
            live_data = feed_data.get("liveData", {})

            # Extract team abbreviations
            teams_info = game_data.get("teams", {})
            home_abbr = teams_info.get("home", {}).get("abbreviation", "")
            away_abbr = teams_info.get("away", {}).get("abbreviation", "")
            game_date = game_data.get("datetime", {}).get("officialDate", target_date)

            boxscore = live_data.get("boxscore", {})

            # Process both sides
            for side in ["home", "away"]:
                team_abbr = home_abbr if side == "home" else away_abbr
                opponent_abbr = away_abbr if side == "home" else home_abbr

                team_box = boxscore.get("teams", {}).get(side, {})
                players = team_box.get("players", {})
                pitchers_order = team_box.get("pitchers", [])
                batters_order = team_box.get("battingOrder", [])

                # ---- Pitcher stats ---- #
                pitcher_records = self._extract_pitcher_stats(
                    game_pk=game_pk,
                    game_date=game_date,
                    team_abbr=team_abbr,
                    opponent_abbr=opponent_abbr,
                    home_away=side,
                    players=players,
                    pitchers_order=pitchers_order,
                )
                all_pitcher_stats.extend(pitcher_records)

                # ---- Batter stats ---- #
                batter_records = self._extract_batter_stats(
                    game_pk=game_pk,
                    game_date=game_date,
                    team_abbr=team_abbr,
                    opponent_abbr=opponent_abbr,
                    home_away=side,
                    players=players,
                    batters_order=batters_order,
                )
                all_batter_stats.extend(batter_records)

            logger.debug(
                "Game %s (%s @ %s): %d pitchers, %d batters",
                game_pk, away_abbr, home_abbr,
                sum(1 for p in all_pitcher_stats if p["game_pk"] == game_pk),
                sum(1 for b in all_batter_stats if b["game_pk"] == game_pk),
            )

        logger.info(
            "Extracted %d pitcher records and %d batter records from %d games",
            len(all_pitcher_stats), len(all_batter_stats), games_final,
        )

        self.data = {
            "date": target_date,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "games_found": games_found,
            "games_final": games_final,
            "pitcher_stats": all_pitcher_stats,
            "batter_stats": all_batter_stats,
        }

    # ------------------------------------------------------------------ #
    # Extraction helpers
    # ------------------------------------------------------------------ #
    def _extract_pitcher_stats(
        self,
        game_pk: int,
        game_date: str,
        team_abbr: str,
        opponent_abbr: str,
        home_away: str,
        players: Dict[str, Any],
        pitchers_order: List[int],
    ) -> List[Dict[str, Any]]:
        """Extract pitcher stats from box score players dict."""
        records = []

        for idx, pitcher_id in enumerate(pitchers_order):
            player_key = f"ID{pitcher_id}"
            player_data = players.get(player_key, {})
            stats = player_data.get("stats", {}).get("pitching", {})

            if not stats:
                continue

            person = player_data.get("person", {})

            records.append({
                "game_pk": game_pk,
                "game_date": game_date,
                "player_id": pitcher_id,
                "player_name": person.get("fullName", ""),
                "team_abbr": team_abbr,
                "opponent_abbr": opponent_abbr,
                "home_away": home_away,
                "is_starter": idx == 0,
                "strikeouts": stats.get("strikeOuts", 0),
                "innings_pitched": stats.get("inningsPitched", "0.0"),
                "pitches_thrown": stats.get("numberOfPitches", 0),
                "strikes": stats.get("strikes", 0),
                "balls": stats.get("balls", 0),
                "hits_allowed": stats.get("hits", 0),
                "walks": stats.get("baseOnBalls", 0),
                "earned_runs": stats.get("earnedRuns", 0),
                "runs": stats.get("runs", 0),
                "home_runs_allowed": stats.get("homeRuns", 0),
                "batters_faced": stats.get("battersFaced", 0),
                "win": stats.get("wins", 0) > 0 if isinstance(stats.get("wins"), int) else False,
                "loss": stats.get("losses", 0) > 0 if isinstance(stats.get("losses"), int) else False,
                "save": stats.get("saves", 0) > 0 if isinstance(stats.get("saves"), int) else False,
            })

        return records

    def _extract_batter_stats(
        self,
        game_pk: int,
        game_date: str,
        team_abbr: str,
        opponent_abbr: str,
        home_away: str,
        players: Dict[str, Any],
        batters_order: List[int],
    ) -> List[Dict[str, Any]]:
        """Extract batter stats from box score players dict.

        Skips pitchers (position code "1") unless they are the DH.
        Only includes batters who appeared in the batting order.
        """
        records = []

        for order_idx, batter_id in enumerate(batters_order):
            player_key = f"ID{batter_id}"
            player_data = players.get(player_key, {})
            stats = player_data.get("stats", {}).get("batting", {})

            if not stats:
                continue

            person = player_data.get("person", {})
            position = player_data.get("position", {})
            position_code = position.get("code", "")

            # Skip pitchers (position code "1") but keep DHs (position code "10")
            if position_code == PITCHER_POSITION_CODE:
                continue

            # batting_order is 1-indexed (100, 200, ..., 900 in MLB API)
            # but we want simple 1-9
            batting_order_raw = player_data.get("battingOrder")
            if batting_order_raw:
                # MLB API uses 100, 200, ..., 900 for starters
                # and 101, 201, etc. for substitutes
                batting_order = (int(str(batting_order_raw)[0])
                                 if batting_order_raw else order_idx + 1)
            else:
                batting_order = order_idx + 1

            records.append({
                "game_pk": game_pk,
                "game_date": game_date,
                "player_id": batter_id,
                "player_name": person.get("fullName", ""),
                "team_abbr": team_abbr,
                "opponent_abbr": opponent_abbr,
                "home_away": home_away,
                "batting_order": batting_order,
                "strikeouts": stats.get("strikeOuts", 0),
                "at_bats": stats.get("atBats", 0),
                "hits": stats.get("hits", 0),
                "walks": stats.get("baseOnBalls", 0),
                "home_runs": stats.get("homeRuns", 0),
                "rbis": stats.get("rbi", 0),
                "runs": stats.get("runs", 0),
            })

        return records

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        if not self.data:
            return {}
        return {
            "date": self.opts.get("date"),
            "games_found": self.data.get("games_found", 0),
            "games_final": self.data.get("games_final", 0),
            "pitcher_records": len(self.data.get("pitcher_stats", [])),
            "batter_records": len(self.data.get("batter_stats", [])),
        }


# --------------------------------------------------------------------------- #
# Flask and CLI entry points
# --------------------------------------------------------------------------- #
create_app = convert_existing_flask_scraper(MlbBoxScoresScraper)

if __name__ == "__main__":
    main = MlbBoxScoresScraper.create_cli_and_flask_main()
    main()

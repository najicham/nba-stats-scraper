"""
File: scrapers/mlb/mlbstatsapi/mlb_game_feed.py

MLB Stats API - Game Feed (Play-by-Play)                          v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Detailed play-by-play data for MLB games from the official MLB Stats API.

API Endpoint: https://statsapi.mlb.com/api/v1.1/game/{gamePk}/feed/live

Key Data:
- Every pitch of the game
- Pitch sequences per at-bat
- Count progressions (0-0, 0-1, 1-1, etc.)
- Pitch results (ball, called_strike, swinging_strike, foul, in_play)
- At-bat outcomes (strikeout, walk, single, etc.)

Important for strikeout analysis:
- Pitch sequences leading to strikeouts
- Count-specific K rates (2-strike efficiency)
- Pitch type effectiveness by count

Usage:
  python scrapers/mlb/mlbstatsapi/mlb_game_feed.py --game_pk 745263 --debug

Note: This returns A LOT of data. Consider using for specific analysis
rather than bulk collection.
"""

from __future__ import annotations

import logging
import os
import sys
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


class MlbGameFeedScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for MLB game feed (play-by-play) from the official MLB Stats API.

    Provides pitch-by-pitch data including:
    - Every pitch thrown
    - Pitch results and at-bat outcomes
    - Count progressions
    - Strikeout details (looking vs swinging)
    """

    scraper_name = "mlb_game_feed"
    required_params = ["game_pk"]
    optional_params = {}

    required_opts: List[str] = ["game_pk"]
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False  # MLB API is cloud-friendly

    exporters = [
        {
            "type": "gcs",
            "key": "mlb-stats-api/game-feed/%(date)s/game_%(game_pk)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_game_feed_%(game_pk)s_%(timestamp)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts["date"] = datetime.now(timezone.utc).date().isoformat()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    _API_ROOT = "https://statsapi.mlb.com/api/v1.1/game"

    def set_url(self) -> None:
        game_pk = self.opts["game_pk"]
        self.url = f"{self._API_ROOT}/{game_pk}/feed/live"
        logger.debug("MLB Game Feed URL: %s", self.url)

    def set_headers(self) -> None:
        self.headers = {
            "User-Agent": "mlb-game-feed-scraper/1.0",
            "Accept": "application/json",
        }

    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict):
            raise ValueError("MLB game feed response malformed")

    def transform_data(self) -> None:
        game_data = self.decoded_data.get("gameData", {})
        live_data = self.decoded_data.get("liveData", {})

        # Extract game info
        game_info = {
            "game_pk": game_data.get("game", {}).get("pk"),
            "game_date": game_data.get("datetime", {}).get("officialDate"),
            "status": game_data.get("status", {}).get("detailedState"),
            "home_team": game_data.get("teams", {}).get("home", {}).get("abbreviation"),
            "away_team": game_data.get("teams", {}).get("away", {}).get("abbreviation"),
            "venue": game_data.get("venue", {}).get("name"),
        }

        # Extract all plays
        all_plays = live_data.get("plays", {}).get("allPlays", [])

        # Extract strikeout-specific data
        strikeout_plays = self._extract_strikeouts(all_plays)

        # Extract pitcher summaries
        pitcher_summaries = self._extract_pitcher_summaries(live_data)

        self.data = {
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gameInfo": game_info,
            "totalPlays": len(all_plays),
            "strikeoutCount": len(strikeout_plays),
            "strikeouts": strikeout_plays,
            "pitcherSummaries": pitcher_summaries,
            # Raw data for deep analysis (optional - can be large)
            # "allPlays": all_plays,
        }

        logger.info("Processed game feed for %s: %d plays, %d strikeouts",
                   self.opts["game_pk"], len(all_plays), len(strikeout_plays))

    def _extract_strikeouts(self, plays: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract all strikeout plays with pitch sequence details."""
        strikeouts = []

        for play in plays:
            result = play.get("result", {})
            event = result.get("event", "")

            if "Strikeout" in event:
                about = play.get("about", {})
                matchup = play.get("matchup", {})
                play_events = play.get("playEvents", [])

                # Get pitch sequence
                pitch_sequence = []
                for pe in play_events:
                    if pe.get("isPitch"):
                        pitch_sequence.append({
                            "pitch_number": pe.get("pitchNumber"),
                            "pitch_type": pe.get("details", {}).get("type", {}).get("description"),
                            "pitch_code": pe.get("details", {}).get("type", {}).get("code"),
                            "result": pe.get("details", {}).get("description"),
                            "velocity": pe.get("pitchData", {}).get("startSpeed"),
                            "spin_rate": pe.get("pitchData", {}).get("spinRate"),
                            "count": f"{pe.get('count', {}).get('balls', 0)}-{pe.get('count', {}).get('strikes', 0)}",
                        })

                strikeouts.append({
                    "inning": about.get("inning"),
                    "half_inning": about.get("halfInning"),
                    "batter_id": matchup.get("batter", {}).get("id"),
                    "batter_name": matchup.get("batter", {}).get("fullName"),
                    "pitcher_id": matchup.get("pitcher", {}).get("id"),
                    "pitcher_name": matchup.get("pitcher", {}).get("fullName"),
                    "event": event,
                    "is_swinging": "Swinging" in event,
                    "is_looking": "Looking" in event or "Called" in event,
                    "pitch_count": len(pitch_sequence),
                    "final_pitch": pitch_sequence[-1] if pitch_sequence else None,
                    "pitch_sequence": pitch_sequence,
                })

        return strikeouts

    def _extract_pitcher_summaries(self, live_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract pitcher performance summaries from box score."""
        summaries = []
        boxscore = live_data.get("boxscore", {})

        for team_key in ["home", "away"]:
            team_data = boxscore.get("teams", {}).get(team_key, {})
            pitchers = team_data.get("pitchers", [])
            players = team_data.get("players", {})

            for pitcher_id in pitchers:
                player_key = f"ID{pitcher_id}"
                player_data = players.get(player_key, {})
                stats = player_data.get("stats", {}).get("pitching", {})

                if stats:
                    summaries.append({
                        "player_id": pitcher_id,
                        "name": player_data.get("person", {}).get("fullName"),
                        "team": team_key,
                        "strikeouts": stats.get("strikeOuts", 0),
                        "innings_pitched": stats.get("inningsPitched", "0"),
                        "pitches": stats.get("numberOfPitches", 0),
                        "strikes": stats.get("strikes", 0),
                        "balls": stats.get("balls", 0),
                        "hits": stats.get("hits", 0),
                        "walks": stats.get("baseOnBalls", 0),
                        "earned_runs": stats.get("earnedRuns", 0),
                    })

        return summaries

    def get_scraper_stats(self) -> dict:
        return {
            "game_pk": self.opts.get("game_pk"),
            "totalPlays": self.data.get("totalPlays", 0),
            "strikeoutCount": self.data.get("strikeoutCount", 0),
        }


create_app = convert_existing_flask_scraper(MlbGameFeedScraper)

if __name__ == "__main__":
    main = MlbGameFeedScraper.create_cli_and_flask_main()
    main()

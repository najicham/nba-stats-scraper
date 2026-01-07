"""
File: scrapers/mlb/mlbstatsapi/mlb_lineups.py

MLB Stats API - Game Lineups                                     v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Starting lineups for MLB games from the official MLB Stats API.
CRITICAL for bottom-up model - tells us which 9 batters face the pitcher.

API Endpoint: https://statsapi.mlb.com/api/v1/game/{gamePk}/boxscore
- Free, no authentication required
- Lineups typically available 1-2 hours before game time
- Includes batting order (1-9) and positions

Key Data for Bottom-Up Model:
- battingOrder: Position in lineup (1-9)
- player.id: Player ID for joining to batter stats
- player.fullName: Player name
- position: Fielding position

Usage examples:
  # Fetch lineups for a specific game:
  python scrapers/mlb/mlbstatsapi/mlb_lineups.py --game-pk 745263 --debug

  # Fetch lineups for all games on a date:
  python scrapers/mlb/mlbstatsapi/mlb_lineups.py --date 2025-06-15 --debug

  # Flask web service:
  python scrapers/mlb/mlbstatsapi/mlb_lineups.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# Support both module execution and direct execution
try:
    from ...scraper_base import DownloadType, ExportMode, ScraperBase
    from ...scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from ...utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

# Notification system imports
try:
    from shared.utils.notification_system import notify_error, notify_warning, notify_info
except ImportError:
    def notify_error(*args, **kwargs): pass
    def notify_warning(*args, **kwargs): pass
    def notify_info(*args, **kwargs): pass

logger = logging.getLogger(__name__)


class MlbLineupsScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for MLB game lineups from the official MLB Stats API.

    CRITICAL for bottom-up strikeout model:
    - Gets the 9 batters in the starting lineup
    - We sum their individual K rates to predict pitcher Ks
    - Lineups typically available 1-2 hours before game

    The MLB Stats API is free and doesn't require authentication.
    """

    # Flask Mixin Configuration
    scraper_name = "mlb_lineups"
    required_params = []
    optional_params = {
        "game_pk": None,        # Single game ID
        "game_pks": None,       # Multiple game IDs (comma-separated)
        "date": None,           # Fetch lineups for all games on date
    }

    # Scraper config
    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False  # MLB API is cloud-friendly!

    # GCS Export Configuration
    GCS_PATH_KEY = "mlb_lineups"
    exporters = [
        # GCS for production
        {
            "type": "gcs",
            "key": "mlb-stats-api/lineups/%(date)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # Local file for development
        {
            "type": "file",
            "filename": "/tmp/mlb_lineups_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    # MLB Stats API endpoints
    _SCHEDULE_API = "https://statsapi.mlb.com/api/v1/schedule"
    _BOXSCORE_API = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

    # ------------------------------------------------------------------ #
    # Additional opts
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        # Default to today if no date/game specified
        if not self.opts.get("game_pk") and not self.opts.get("game_pks") and not self.opts.get("date"):
            today = datetime.now(timezone.utc).date()
            self.opts["date"] = today.isoformat()

    # ------------------------------------------------------------------ #
    # URL & headers (we'll fetch schedule first, then boxscores)
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        # If fetching by date, start with schedule
        if self.opts.get("date") and not self.opts.get("game_pk"):
            self.url = f"{self._SCHEDULE_API}?sportId=1&date={self.opts['date']}&gameTypes=R,P"
        elif self.opts.get("game_pk"):
            # Single game boxscore
            self.url = self._BOXSCORE_API.format(game_pk=self.opts["game_pk"])
        else:
            # Default to today's schedule
            today = datetime.now(timezone.utc).date().isoformat()
            self.url = f"{self._SCHEDULE_API}?sportId=1&date={today}&gameTypes=R,P"

        logger.debug("MLB Lineups URL: %s", self.url)

    def set_headers(self) -> None:
        self.headers = {
            "User-Agent": "mlb-lineups-scraper/1.0",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        # Can be schedule response or boxscore response
        if not isinstance(self.decoded_data, dict):
            raise ValueError("MLB API response is not a dict")

    # ------------------------------------------------------------------ #
    # Transform - fetch lineups for each game
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        try:
            all_lineups: List[Dict[str, Any]] = []

            # Check if this is a schedule response (has 'dates') or boxscore
            if "dates" in self.decoded_data:
                # Schedule response - need to fetch boxscores for each game
                game_pks = self._extract_game_pks_from_schedule()
                logger.info(f"Found {len(game_pks)} games, fetching lineups...")

                for game_pk in game_pks:
                    lineup_data = self._fetch_game_lineup(game_pk)
                    if lineup_data:
                        all_lineups.append(lineup_data)

            elif "gameData" in self.decoded_data:
                # Single boxscore response
                lineup_data = self._transform_boxscore(self.decoded_data)
                if lineup_data:
                    all_lineups.append(lineup_data)

            elif self.opts.get("game_pks"):
                # Multiple specific games
                for game_pk in str(self.opts["game_pks"]).split(","):
                    lineup_data = self._fetch_game_lineup(game_pk.strip())
                    if lineup_data:
                        all_lineups.append(lineup_data)

            # Count lineups that are available
            lineups_available = sum(
                1 for g in all_lineups
                if g.get("away_lineup") and len(g.get("away_lineup", [])) > 0
            )

            self.data = {
                "scrape_date": self.opts.get("date", datetime.now(timezone.utc).date().isoformat()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_games": len(all_lineups),
                "lineups_available": lineups_available,
                "games": all_lineups,
            }

            logger.info(
                "Fetched lineups for %d games (%d with lineups available) for %s",
                len(all_lineups), lineups_available, self.opts.get("date", "query")
            )

            # Notifications
            if lineups_available == 0 and len(all_lineups) > 0:
                notify_warning(
                    title="MLB Lineups - No Lineups Posted",
                    message=f"Found {len(all_lineups)} games but no lineups posted yet",
                    details={
                        'scraper': 'mlb_lineups',
                        'date': self.opts.get('date'),
                        'games': len(all_lineups),
                    }
                )
            elif lineups_available > 0:
                notify_info(
                    title="MLB Lineups - Success",
                    message=f"Scraped {lineups_available} lineups from {len(all_lineups)} games",
                    details={
                        'scraper': 'mlb_lineups',
                        'date': self.opts.get('date'),
                        'total_games': len(all_lineups),
                        'lineups_available': lineups_available,
                    }
                )

        except Exception as e:
            notify_error(
                title="MLB Lineups - Transform Failed",
                message=f"Data transformation failed: {str(e)}",
                details={
                    'scraper': 'mlb_lineups',
                    'date': self.opts.get('date'),
                    'error_type': type(e).__name__,
                },
                processor_name="MLB Lineups"
            )
            raise

    def _extract_game_pks_from_schedule(self) -> List[int]:
        """Extract game IDs from schedule response."""
        game_pks = []
        for date_entry in self.decoded_data.get("dates", []):
            for game in date_entry.get("games", []):
                game_pk = game.get("gamePk")
                if game_pk:
                    game_pks.append(game_pk)
        return game_pks

    def _fetch_game_lineup(self, game_pk: int) -> Optional[Dict]:
        """Fetch and transform lineup for a single game."""
        try:
            url = self._BOXSCORE_API.format(game_pk=game_pk)
            resp = self.http_downloader.get(url, headers=self.headers, timeout=30)
            resp.raise_for_status()
            boxscore_data = resp.json()
            return self._transform_boxscore(boxscore_data)
        except Exception as e:
            logger.warning(f"Error fetching lineup for game {game_pk}: {e}")
            return None

    def _transform_boxscore(self, boxscore: Dict) -> Optional[Dict]:
        """Transform boxscore response into lineup data."""
        try:
            game_data = boxscore.get("gameData", {})
            live_data = boxscore.get("liveData", {})
            boxscore_data = live_data.get("boxscore", {})

            game_pk = game_data.get("game", {}).get("pk")
            if not game_pk:
                return None

            # Get game info
            game_info = game_data.get("game", {})
            datetime_info = game_data.get("datetime", {})
            venue = game_data.get("venue", {})
            status = game_data.get("status", {})

            # Teams
            teams = boxscore_data.get("teams", {})
            away_team = teams.get("away", {})
            home_team = teams.get("home", {})

            # Extract lineups (batting order)
            away_lineup = self._extract_lineup(away_team)
            home_lineup = self._extract_lineup(home_team)

            # Get pitchers
            away_pitchers = self._extract_pitchers(away_team)
            home_pitchers = self._extract_pitchers(home_team)

            return {
                # Game identifiers
                "game_pk": game_pk,
                "game_date": datetime_info.get("originalDate"),
                "game_time_utc": datetime_info.get("dateTime"),
                "game_type": game_info.get("type"),

                # Teams
                "away_team_id": away_team.get("team", {}).get("id"),
                "away_team_name": away_team.get("team", {}).get("name"),
                "away_team_abbr": away_team.get("team", {}).get("abbreviation"),
                "home_team_id": home_team.get("team", {}).get("id"),
                "home_team_name": home_team.get("team", {}).get("name"),
                "home_team_abbr": home_team.get("team", {}).get("abbreviation"),

                # Venue
                "venue_name": venue.get("name"),

                # Status
                "status_code": status.get("statusCode"),
                "lineups_available": len(away_lineup) > 0 or len(home_lineup) > 0,

                # LINEUPS (THE KEY DATA FOR BOTTOM-UP MODEL!)
                "away_lineup": away_lineup,  # List of 9 batters in order
                "home_lineup": home_lineup,  # List of 9 batters in order

                # Pitchers
                "away_pitchers": away_pitchers,
                "home_pitchers": home_pitchers,
            }

        except Exception as e:
            logger.warning(f"Error transforming boxscore: {e}")
            return None

    def _extract_lineup(self, team_data: Dict) -> List[Dict]:
        """Extract batting lineup from team boxscore data."""
        lineup = []
        batters = team_data.get("batters", [])
        players = team_data.get("players", {})

        for player_id in batters:
            player_key = f"ID{player_id}"
            player_data = players.get(player_key, {})
            person = player_data.get("person", {})
            position = player_data.get("position", {})
            batting_order = player_data.get("battingOrder")

            # Only include players with a batting order (in the lineup)
            if batting_order:
                # Convert batting order to position (100 = 1, 200 = 2, etc.)
                order_position = int(batting_order) // 100 if batting_order else None

                lineup.append({
                    "player_id": person.get("id"),
                    "player_name": person.get("fullName"),
                    "batting_order": order_position,
                    "batting_order_raw": batting_order,
                    "position": position.get("abbreviation"),
                    "position_name": position.get("name"),
                })

        # Sort by batting order
        lineup.sort(key=lambda x: x.get("batting_order", 99))

        return lineup

    def _extract_pitchers(self, team_data: Dict) -> List[Dict]:
        """Extract pitchers from team boxscore data."""
        pitchers_list = []
        pitchers = team_data.get("pitchers", [])
        players = team_data.get("players", {})

        for i, player_id in enumerate(pitchers):
            player_key = f"ID{player_id}"
            player_data = players.get(player_key, {})
            person = player_data.get("person", {})
            stats = player_data.get("stats", {}).get("pitching", {})

            pitchers_list.append({
                "player_id": person.get("id"),
                "player_name": person.get("fullName"),
                "is_starter": i == 0,  # First pitcher is starter
                "innings_pitched": stats.get("inningsPitched"),
                "strikeouts": stats.get("strikeOuts"),
                "hits": stats.get("hits"),
                "runs": stats.get("runs"),
                "earned_runs": stats.get("earnedRuns"),
            })

        return pitchers_list

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "total_games": self.data.get("total_games", 0),
            "lineups_available": self.data.get("lineups_available", 0),
            "date": self.opts.get("date", "multiple"),
        }


# --------------------------------------------------------------------------- #
# Flask and CLI entry points
# --------------------------------------------------------------------------- #
create_app = convert_existing_flask_scraper(MlbLineupsScraper)

if __name__ == "__main__":
    main = MlbLineupsScraper.create_cli_and_flask_main()
    main()

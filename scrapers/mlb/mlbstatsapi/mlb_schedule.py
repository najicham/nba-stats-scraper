"""
File: scrapers/mlb/mlbstatsapi/mlb_schedule.py

MLB Stats API - Schedule with Probable Pitchers                  v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Daily game schedule from the official MLB Stats API.
CRITICAL for predictions - tells us WHO is pitching.

API Endpoint: https://statsapi.mlb.com/api/v1/schedule
- Free, no authentication required
- Cloud-friendly (no IP blocking)
- Includes probable pitchers (announced 1-2 days before game)

Key Data:
- gamePk: Authoritative MLB game ID
- gameDate: Game date/time (UTC)
- teams.away/home.probablePitcher: Starting pitcher info
- venue: Stadium name
- status: Game status (Scheduled, In Progress, Final)

Usage examples:
  # Fetch schedule for a specific date:
  python scrapers/mlb/mlbstatsapi/mlb_schedule.py --date 2025-06-15 --debug

  # Fetch schedule for date range:
  python scrapers/mlb/mlbstatsapi/mlb_schedule.py --start-date 2025-06-01 --end-date 2025-06-07

  # Flask web service:
  python scrapers/mlb/mlbstatsapi/mlb_schedule.py --serve --debug
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


class MlbScheduleScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for MLB schedule from the official MLB Stats API.

    This is the FOUNDATION for MLB predictions:
    - Tells us which games are happening
    - Provides probable pitchers (who we're predicting Ks for)
    - Gives game context (venue, time, home/away)

    The MLB Stats API is free and doesn't require authentication.
    """

    # Flask Mixin Configuration
    scraper_name = "mlb_schedule"
    required_params = []
    optional_params = {
        "date": None,           # Single date (YYYY-MM-DD)
        "start_date": None,     # Start of date range
        "end_date": None,       # End of date range
        "team_id": None,        # Filter by team ID
        "include_completed": "true",  # Include completed games
    }

    # Scraper config
    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False  # MLB API is cloud-friendly!

    # GCS Export Configuration
    GCS_PATH_KEY = "mlb_schedule"
    exporters = [
        # GCS for production
        {
            "type": "gcs",
            "key": "mlb-stats-api/schedule/%(date)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # Local file for development
        {
            "type": "file",
            "filename": "/tmp/mlb_schedule_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    # MLB Stats API base URL
    _API_ROOT = "https://statsapi.mlb.com/api/v1/schedule"

    # Hydration parameters for additional data
    # probablePitcher: Get starting pitcher info
    # team: Get full team info
    # venue: Get stadium details
    # linescore: Get score by inning (for completed games)
    _HYDRATE = "probablePitcher,team,venue,linescore"

    # ------------------------------------------------------------------ #
    # Additional opts
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        # Default to today if no date specified
        if not self.opts.get("date") and not self.opts.get("start_date"):
            today = datetime.now(timezone.utc).date()
            self.opts["date"] = today.isoformat()

    # ------------------------------------------------------------------ #
    # URL & headers
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        params = [
            "sportId=1",  # 1 = MLB
            f"hydrate={self._HYDRATE}",
        ]

        # Date handling
        if self.opts.get("date"):
            params.append(f"date={self.opts['date']}")
        elif self.opts.get("start_date") and self.opts.get("end_date"):
            params.append(f"startDate={self.opts['start_date']}")
            params.append(f"endDate={self.opts['end_date']}")
        else:
            # Default to today
            today = datetime.now(timezone.utc).date().isoformat()
            params.append(f"date={today}")

        # Optional team filter
        if self.opts.get("team_id"):
            params.append(f"teamId={self.opts['team_id']}")

        # Game types (R=Regular, P=Postseason, S=Spring Training)
        params.append("gameTypes=R,P")

        self.url = f"{self._API_ROOT}?{'&'.join(params)}"
        logger.debug("MLB Schedule URL: %s", self.url)

    def set_headers(self) -> None:
        # MLB Stats API doesn't require auth
        self.headers = {
            "User-Agent": "mlb-schedule-scraper/1.0",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        try:
            if not isinstance(self.decoded_data, dict):
                raise ValueError("MLB schedule response is not a dict")
            if "dates" not in self.decoded_data:
                raise ValueError("MLB schedule response missing 'dates' key")
        except Exception as e:
            notify_error(
                title="MLB Schedule - Validation Failed",
                message=f"Data validation failed: {str(e)}",
                details={
                    'scraper': 'mlb_schedule',
                    'date': self.opts.get('date'),
                    'error_type': type(e).__name__,
                },
                processor_name="MLB Schedule"
            )
            raise

    # ------------------------------------------------------------------ #
    # Transform
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        try:
            dates_data = self.decoded_data.get("dates", [])
            all_games: List[Dict[str, Any]] = []

            for date_entry in dates_data:
                date_str = date_entry.get("date")
                games = date_entry.get("games", [])

                for game in games:
                    transformed_game = self._transform_game(game, date_str)
                    if transformed_game:
                        all_games.append(transformed_game)

            # Sort by game date and time
            all_games.sort(key=lambda g: (g.get("game_date", ""), g.get("game_time_utc", "")))

            # Count games with probable pitchers
            games_with_starters = sum(
                1 for g in all_games
                if g.get("away_probable_pitcher_id") or g.get("home_probable_pitcher_id")
            )

            self.data = {
                "scrape_date": self.opts.get("date", "multiple"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_games": len(all_games),
                "games_with_probable_pitchers": games_with_starters,
                "games": all_games,
            }

            logger.info(
                "Fetched %d games (%d with probable pitchers) for %s",
                len(all_games), games_with_starters, self.opts.get("date", "range")
            )

            # Notifications
            if len(all_games) == 0:
                notify_warning(
                    title="MLB Schedule - No Games",
                    message=f"No games found for {self.opts.get('date', 'query')}",
                    details={'scraper': 'mlb_schedule', 'date': self.opts.get('date')}
                )
            else:
                notify_info(
                    title="MLB Schedule - Success",
                    message=f"Scraped {len(all_games)} games ({games_with_starters} with starters)",
                    details={
                        'scraper': 'mlb_schedule',
                        'date': self.opts.get('date'),
                        'total_games': len(all_games),
                        'games_with_starters': games_with_starters,
                    }
                )

        except Exception as e:
            notify_error(
                title="MLB Schedule - Transform Failed",
                message=f"Data transformation failed: {str(e)}",
                details={
                    'scraper': 'mlb_schedule',
                    'date': self.opts.get('date'),
                    'error_type': type(e).__name__,
                },
                processor_name="MLB Schedule"
            )
            raise

    def _transform_game(self, game: Dict, date_str: str) -> Optional[Dict]:
        """Transform a single game record."""
        try:
            game_pk = game.get("gamePk")
            if not game_pk:
                return None

            # Teams
            teams = game.get("teams", {})
            away = teams.get("away", {})
            home = teams.get("home", {})

            away_team = away.get("team", {})
            home_team = home.get("team", {})

            # Probable pitchers (CRITICAL!)
            away_pitcher = away.get("probablePitcher", {})
            home_pitcher = home.get("probablePitcher", {})

            # Venue
            venue = game.get("venue", {})

            # Status
            status = game.get("status", {})

            # Game time
            game_date_str = game.get("gameDate", "")  # ISO format with time

            # Linescore for final scores
            linescore = game.get("linescore", {})
            teams_linescore = linescore.get("teams", {})

            return {
                # Core identifiers
                "game_pk": game_pk,
                "game_date": date_str,
                "game_time_utc": game_date_str,
                "season": game.get("season"),
                "game_type": game.get("gameType"),  # R=Regular, P=Postseason

                # Teams
                "away_team_id": away_team.get("id"),
                "away_team_name": away_team.get("name"),
                "away_team_abbr": away_team.get("abbreviation"),
                "home_team_id": home_team.get("id"),
                "home_team_name": home_team.get("name"),
                "home_team_abbr": home_team.get("abbreviation"),

                # Probable Pitchers (THE KEY DATA!)
                "away_probable_pitcher_id": away_pitcher.get("id"),
                "away_probable_pitcher_name": away_pitcher.get("fullName"),
                "away_probable_pitcher_number": away_pitcher.get("primaryNumber"),
                "home_probable_pitcher_id": home_pitcher.get("id"),
                "home_probable_pitcher_name": home_pitcher.get("fullName"),
                "home_probable_pitcher_number": home_pitcher.get("primaryNumber"),

                # Venue
                "venue_id": venue.get("id"),
                "venue_name": venue.get("name"),

                # Status
                "status_code": status.get("statusCode"),
                "status_detailed": status.get("detailedState"),
                "is_final": status.get("statusCode") == "F",

                # Scores (for completed games)
                "away_score": teams_linescore.get("away", {}).get("runs"),
                "home_score": teams_linescore.get("home", {}).get("runs"),
                "away_hits": teams_linescore.get("away", {}).get("hits"),
                "home_hits": teams_linescore.get("home", {}).get("hits"),

                # Additional context
                "day_night": game.get("dayNight"),
                "series_description": game.get("seriesDescription"),
                "games_in_series": game.get("gamesInSeries"),
                "series_game_number": game.get("seriesGameNumber"),
            }

        except Exception as e:
            logger.warning(f"Error transforming game: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "total_games": self.data.get("total_games", 0),
            "games_with_starters": self.data.get("games_with_probable_pitchers", 0),
            "date": self.opts.get("date", "multiple"),
        }


# --------------------------------------------------------------------------- #
# Flask and CLI entry points
# --------------------------------------------------------------------------- #
create_app = convert_existing_flask_scraper(MlbScheduleScraper)

if __name__ == "__main__":
    main = MlbScheduleScraper.create_cli_and_flask_main()
    main()

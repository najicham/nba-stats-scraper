# File: scrapers/projections/espn_projections.py
"""
ESPN Fantasy NBA Player Projections Scraper                   v1.0 - 2026-03-07
--------------------------------------------------------------------------------
Scrapes season-average player projections from ESPN Fantasy Basketball API.

ESPN's Fantasy API provides season-level stat projections for ~500 players.
We convert these to per-game projections by dividing by projected_games (stat[42]).

Data: Projected points, minutes, rebounds, assists per player (per-game average).
Source: Public ESPN Fantasy API (no authentication required).

Usage:
  python scrapers/projections/espn_projections.py --date 2026-03-07 --debug
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

from shared.utils.notification_system import notify_error, notify_warning, notify_info

logger = logging.getLogger("scraper_base")

# ESPN Fantasy Basketball API endpoint
ESPN_FANTASY_API_URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{year}"
    "/segments/0/leaguedefaults/3?view=kona_player_info"
)

# ESPN proTeamId -> NBA standard tricode
# Inversion of ESPN_TEAM_IDS from scrapers/espn/espn_roster_api.py
ESPN_PRO_TEAM_ID_TO_ABBR = {
    1: "ATL", 2: "BOS", 3: "NOP", 4: "CHI", 5: "CLE",
    6: "DAL", 7: "DEN", 8: "DET", 9: "GSW", 10: "HOU",
    11: "IND", 12: "LAC", 13: "LAL", 14: "MIA", 15: "MIL",
    16: "MIN", 17: "BKN", 18: "NYK", 19: "ORL", 20: "PHI",
    21: "PHX", 22: "POR", 23: "SAC", 24: "SAS", 25: "OKC",
    26: "UTA", 27: "WAS", 28: "TOR", 29: "MEM", 30: "CHA",
}

# ESPN stat index -> stat name
# statSourceId=1 means projections, seasonId=2026 means current season
STAT_INDICES = {
    0: 'points',
    3: 'assists',
    6: 'rebounds',
    28: 'minutes',
    42: 'projected_games',
}

# ESPN position IDs
ESPN_POSITION_MAP = {
    1: "PG", 2: "SG", 3: "SF", 4: "PF", 5: "C",
}


def normalize_player_name(name: str) -> str:
    """Convert player name to player_lookup format (lowercase, no spaces)."""
    if not name:
        return ""
    for suffix in [" Jr.", " Sr.", " Jr", " Sr", " III", " II", " IV"]:
        name = name.replace(suffix, "")
    normalized = name.lower().strip()
    normalized = re.sub(r'[^a-z\s-]', '', normalized)
    normalized = re.sub(r'[\s-]+', '', normalized)
    return normalized


class ESPNProjectionsScraper(ScraperBase, ScraperFlaskMixin):
    """Scrape daily NBA player projections from ESPN Fantasy Basketball API."""

    # Flask Mixin Configuration
    scraper_name = "espn_projections"
    required_params = ["date"]
    optional_params = {}

    # Scraper config — JSON download type since we're hitting a REST API
    required_opts: List[str] = ["date"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = None
    proxy_enabled: bool = False  # Public API, no proxy needed

    CRAWL_DELAY_SECONDS = 2.0

    GCS_PATH_KEY = "espn_projections"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/espn_projections_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
    ]

    def set_url(self) -> None:
        """Set ESPN Fantasy API URL."""
        # Derive season year from date (NBA season spans two calendar years)
        date_str = self.opts.get("date", "")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            # NBA season year: if month >= October, season = year+1, else season = year
            year = dt.year + 1 if dt.month >= 10 else dt.year
        except (ValueError, AttributeError):
            year = 2026

        self.url = ESPN_FANTASY_API_URL.format(year=year)
        logger.info("ESPN Fantasy API URL: %s", self.url)

    def download_and_decode(self):
        """Fetch projections via ESPN Fantasy Basketball API.

        Single GET request with x-fantasy-filter header for pagination and
        projection data filtering.
        """
        import requests

        time.sleep(self.CRAWL_DELAY_SECONDS)

        # Derive season year from date
        date_str = self.opts.get("date", "")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            year = dt.year + 1 if dt.month >= 10 else dt.year
        except (ValueError, AttributeError):
            year = 2026

        url = ESPN_FANTASY_API_URL.format(year=year)

        # x-fantasy-filter header for player projections
        fantasy_filter = {
            "players": {
                "limit": 500,
                "sortPercOwned": {"sortAsc": False, "sortPriority": 1},
                "filterStatsForExternalIds": {"value": [year]},
                "filterSlotIds": {"value": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]},
                "filterStatsForSourceIds": {"value": [1]},
                "sortAppliedStatTotal": None,
                "sortAppliedStatTotalForScoringPeriodId": None,
            }
        }

        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'x-fantasy-filter': json.dumps(fantasy_filter),
        }

        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("ESPN Fantasy API request failed: %s", e)
            raise

        players = data.get("players", [])
        logger.info("ESPN Fantasy API returned %d player entries", len(players))

        self.decoded_data = {"players": players, "season_year": year}

    def validate_download_data(self) -> None:
        """Validate we received valid projections data."""
        if not isinstance(self.decoded_data, dict):
            raise ValueError("Expected dict from ESPN Fantasy API response")

    def transform_data(self) -> None:
        """Transform ESPN Fantasy API projections into our standard format."""
        raw_players = self.decoded_data.get("players", [])

        players = []
        skipped_free_agents = 0
        skipped_no_projections = 0

        for entry in raw_players:
            if not isinstance(entry, dict):
                continue

            player_info = entry.get("player") or {}
            full_name = player_info.get("fullName", "")
            if not full_name:
                continue

            # Filter out free agents (proTeamId=0)
            pro_team_id = player_info.get("proTeamId", 0)
            if pro_team_id == 0:
                skipped_free_agents += 1
                continue

            team_abbr = ESPN_PRO_TEAM_ID_TO_ABBR.get(pro_team_id, "")
            if not team_abbr:
                continue

            # Get player position
            default_position_id = player_info.get("defaultPositionId", 0)
            position = ESPN_POSITION_MAP.get(default_position_id, "")

            # Get ESPN player ID
            espn_player_id = player_info.get("id")

            # Extract projection stats from statSourceId=1
            stats = player_info.get("stats", [])
            proj_stats = None
            for stat_set in stats:
                if not isinstance(stat_set, dict):
                    continue
                # statSourceId=1 = projections
                if stat_set.get("statSourceId") == 1:
                    proj_stats = stat_set.get("stats", {})
                    break

            if not proj_stats:
                skipped_no_projections += 1
                continue

            # Get season total points and projected games
            season_total_points = _safe_float(proj_stats.get("0"))
            projected_games = _safe_float(proj_stats.get("42"))

            if not season_total_points or not projected_games or projected_games <= 0:
                skipped_no_projections += 1
                continue

            # Compute per-game projections
            projected_points = round(season_total_points / projected_games, 1)
            if projected_points <= 0:
                continue

            season_total_minutes = _safe_float(proj_stats.get("28"))
            season_total_rebounds = _safe_float(proj_stats.get("6"))
            season_total_assists = _safe_float(proj_stats.get("3"))

            projected_minutes = round(season_total_minutes / projected_games, 1) if season_total_minutes else None
            projected_rebounds = round(season_total_rebounds / projected_games, 1) if season_total_rebounds else None
            projected_assists = round(season_total_assists / projected_games, 1) if season_total_assists else None

            players.append({
                "player_name": full_name,
                "player_lookup": normalize_player_name(full_name),
                "team": team_abbr,
                "position": position,
                "projected_points": projected_points,
                "projected_minutes": projected_minutes,
                "projected_rebounds": projected_rebounds,
                "projected_assists": projected_assists,
                "espn_player_id": espn_player_id,
            })

        self.data = {
            "source": "espn",
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "player_count": len(players),
            "players": players,
        }

        logger.info(
            "Parsed %d player projections from ESPN Fantasy API "
            "(skipped %d free agents, %d without projections)",
            len(players), skipped_free_agents, skipped_no_projections
        )

        if players:
            try:
                notify_info(
                    title="ESPN Projections Scraped",
                    message=f"Scraped {len(players)} player projections for {self.opts['date']}",
                    details={'player_count': len(players), 'date': self.opts['date']},
                    processor_name=self.__class__.__name__
                )
            except Exception:
                pass
        else:
            try:
                notify_warning(
                    title="ESPN Projections: No Projections",
                    message=f"0 projections returned for {self.opts['date']}",
                    details={'date': self.opts['date']},
                    processor_name=self.__class__.__name__
                )
            except Exception:
                pass

    def get_scraper_stats(self) -> dict:
        return {
            "date": self.opts.get("date"),
            "player_count": self.data.get("player_count", 0),
        }


def _safe_float(val: Any) -> Optional[float]:
    """Safely convert value to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# Flask and CLI entry points
create_app = convert_existing_flask_scraper(ESPNProjectionsScraper)

if __name__ == "__main__":
    main = ESPNProjectionsScraper.create_cli_and_flask_main()
    main()

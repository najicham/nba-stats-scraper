# File: scrapers/projections/numberfire_projections.py
"""
NumberFire/FanDuel NBA Player Projections Scraper              v2.0 - 2026-03-04
---------------------------------------------------------------------------------
Scrapes daily fantasy basketball projections from FanDuel Research GraphQL API.

NumberFire was acquired by FanDuel — the domain now redirects to a React SPA.
Instead of HTML parsing or Playwright, we hit the public GraphQL API directly:
  1. GET slates via getSlates(sport: NBA) to find today's main slate ID
  2. GET projections via getProjections(slateId) for all player projections

Data: Projected points, minutes, rebounds, assists per player.
Timing: Updates by ~10 AM ET.

Usage:
  python scrapers/projections/numberfire_projections.py --date 2026-03-04 --debug
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

# FanDuel Research GraphQL endpoint (public, no auth)
FANDUEL_GRAPHQL_URL = "https://fdresearch-api.fanduel.com/graphql"

# Team abbreviation normalization
TEAM_ABBR_MAP = {
    "ATL": "ATL", "BOS": "BOS", "BKN": "BKN", "CHA": "CHA", "CHI": "CHI",
    "CLE": "CLE", "DAL": "DAL", "DEN": "DEN", "DET": "DET", "GS": "GSW",
    "GSW": "GSW", "HOU": "HOU", "IND": "IND", "LAC": "LAC", "LAL": "LAL",
    "MEM": "MEM", "MIA": "MIA", "MIL": "MIL", "MIN": "MIN", "NO": "NOP",
    "NOP": "NOP", "NY": "NYK", "NYK": "NYK", "OKC": "OKC", "ORL": "ORL",
    "PHI": "PHI", "PHX": "PHX", "PHO": "PHX", "POR": "POR", "SAC": "SAC",
    "SA": "SAS", "SAS": "SAS", "TOR": "TOR", "UTA": "UTA", "WAS": "WAS",
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


class NumberFireProjectionsScraper(ScraperBase, ScraperFlaskMixin):
    """Scrape daily NBA player projections from FanDuel Research GraphQL API."""

    # Flask Mixin Configuration
    scraper_name = "numberfire_projections"
    required_params = ["date"]
    optional_params = {}

    # Scraper config — JSON download type since we're hitting a GraphQL API
    required_opts: List[str] = ["date"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = None
    proxy_enabled: bool = False  # Public API, no proxy needed

    CRAWL_DELAY_SECONDS = 2.0

    GCS_PATH_KEY = "numberfire_projections"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/numberfire_projections_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
    ]

    def set_url(self) -> None:
        """Set FanDuel GraphQL URL."""
        self.url = FANDUEL_GRAPHQL_URL
        logger.info("FanDuel GraphQL URL: %s", self.url)

    def download_and_decode(self):
        """Fetch projections via FanDuel GraphQL API.

        Two-step process:
        1. Query getSlates to find today's main NBA slate ID
        2. Query getProjections with that slate ID for all player projections
        """
        import requests

        time.sleep(self.CRAWL_DELAY_SECONDS)

        session = requests.Session()
        session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Origin': 'https://www.fanduel.com',
            'Referer': 'https://www.fanduel.com/',
        })

        # Step 1: Get slate ID
        slate_id = self._get_main_slate_id(session)
        if not slate_id:
            logger.warning("No NBA slates found — off-day or API changed")
            self.decoded_data = {"players": [], "slate_id": None}
            return

        logger.info("Found main NBA slate ID: %s", slate_id)

        # Step 2: Get projections for this slate
        projections_query = {
            "query": """
            query {
                getProjections(input: {type: DAILY, sport: NBA, position: NBA_PLAYER, slateId: "%s"}) {
                    ... on NbaPlayer {
                        player { name position numberFireId }
                        team { abbreviation }
                        gameInfo { homeTeam { abbreviation } awayTeam { abbreviation } gameTime }
                        minutes points rebounds assists steals blocks turnovers fantasy
                    }
                }
            }
            """ % slate_id
        }

        try:
            resp = session.post(FANDUEL_GRAPHQL_URL, json=projections_query, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("FanDuel GraphQL projections request failed: %s", e)
            raise

        projections = data.get("data", {}).get("getProjections", [])
        logger.info("FanDuel GraphQL returned %d player projections", len(projections))

        self.decoded_data = {"players": projections, "slate_id": slate_id}

    def _get_main_slate_id(self, session) -> Optional[str]:
        """Query getSlates to find today's main NBA slate."""
        slates_query = {
            "query": """
            query {
                getSlates(input: {sport: NBA}) {
                    slateId
                    name
                    gameCount
                }
            }
            """
        }

        try:
            resp = session.post(FANDUEL_GRAPHQL_URL, json=slates_query, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("FanDuel GraphQL slates request failed: %s", e)
            return None

        slates = data.get("data", {}).get("getSlates", [])
        if not slates:
            return None

        # Find the "Main" slate (covers all games), or fallback to largest
        for slate in slates:
            name = (slate.get("name") or "").lower()
            if "main" in name:
                return slate["slateId"]

        # Fallback: use the slate with the most games
        slates.sort(key=lambda s: s.get("gameCount", 0), reverse=True)
        return slates[0]["slateId"]

    def validate_download_data(self) -> None:
        """Validate we received valid projections data."""
        if not isinstance(self.decoded_data, dict):
            raise ValueError("Expected dict from FanDuel GraphQL response")

    def transform_data(self) -> None:
        """Transform FanDuel GraphQL projections into our standard format."""
        raw_players = self.decoded_data.get("players", [])

        players = []
        for p in raw_players:
            if not isinstance(p, dict):
                continue

            player_info = p.get("player") or {}
            team_info = p.get("team") or {}
            game_info = p.get("gameInfo") or {}

            name = player_info.get("name", "")
            if not name:
                continue

            team_abbr = team_info.get("abbreviation", "")
            team_abbr = TEAM_ABBR_MAP.get(team_abbr, team_abbr)

            # Determine opponent
            home_team = (game_info.get("homeTeam") or {}).get("abbreviation", "")
            away_team = (game_info.get("awayTeam") or {}).get("abbreviation", "")
            opponent = away_team if team_abbr == TEAM_ABBR_MAP.get(home_team, home_team) else home_team
            opponent = TEAM_ABBR_MAP.get(opponent, opponent)

            projected_points = _safe_float(p.get("points"))
            if projected_points is None or projected_points <= 0:
                continue

            players.append({
                "player_name": name,
                "player_lookup": normalize_player_name(name),
                "team": team_abbr,
                "position": player_info.get("position", ""),
                "opponent": opponent,
                "projected_points": projected_points,
                "projected_minutes": _safe_float(p.get("minutes")),
                "projected_rebounds": _safe_float(p.get("rebounds")),
                "projected_assists": _safe_float(p.get("assists")),
                "projected_steals": _safe_float(p.get("steals")),
                "projected_blocks": _safe_float(p.get("blocks")),
                "projected_turnovers": _safe_float(p.get("turnovers")),
                "projected_fantasy": _safe_float(p.get("fantasy")),
            })

        self.data = {
            "source": "numberfire",
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "player_count": len(players),
            "players": players,
        }

        logger.info("Parsed %d player projections from FanDuel GraphQL", len(players))

        if players:
            try:
                notify_info(
                    title="NumberFire Projections Scraped",
                    message=f"Scraped {len(players)} player projections for {self.opts['date']}",
                    details={'player_count': len(players), 'date': self.opts['date']},
                    processor_name=self.__class__.__name__
                )
            except Exception:
                pass
        else:
            try:
                notify_warning(
                    title="NumberFire: No Projections",
                    message=f"0 projections returned for {self.opts['date']}",
                    details={'date': self.opts['date'], 'slate_id': self.decoded_data.get('slate_id')},
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
        return round(float(val), 1)
    except (ValueError, TypeError):
        return None


# Flask and CLI entry points
create_app = convert_existing_flask_scraper(NumberFireProjectionsScraper)

if __name__ == "__main__":
    main = NumberFireProjectionsScraper.create_cli_and_flask_main()
    main()

# File: scrapers/external/rotowire_lineups.py
"""
RotoWire NBA Lineups & Projected Minutes Scraper                v1.0 - 2026-03-04
----------------------------------------------------------------------------------
Scrapes projected starting lineups and minutes estimates from RotoWire.

URL: https://www.rotowire.com/basketball/nba-lineups.php
Data: Projected starting lineups, injury designations, minutes estimates.
Access: Free lineup page. May require browser rendering for full content.
Timing: Updates ~4 PM ET on game days.

Creates minutes_projection signal: projected minutes 3+ above season average.
Creates dnp_risk filter: player projected for reduced/DNP minutes.

Usage:
  python scrapers/external/rotowire_lineups.py --date 2026-03-04 --debug
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

try:
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

from shared.utils.notification_system import notify_warning, notify_info

logger = logging.getLogger("scraper_base")

# Position abbreviations
VALID_POSITIONS = {"PG", "SG", "SF", "PF", "C", "G", "F", "G/F", "F/C"}

# Injury status values
INJURY_STATUSES = {
    "GTD": "game-time-decision",
    "O": "out",
    "OUT": "out",
    "D": "doubtful",
    "Q": "questionable",
    "P": "probable",
}


def normalize_player_name(name: str) -> str:
    """Convert player name to player_lookup format."""
    if not name:
        return ""
    for suffix in [" Jr.", " Sr.", " Jr", " Sr", " III", " II", " IV"]:
        name = name.replace(suffix, "")
    normalized = name.lower().strip()
    normalized = re.sub(r'[^a-z\s-]', '', normalized)
    normalized = re.sub(r'\s+', '-', normalized)
    return normalized


class RotoWireLineupsScraper(ScraperBase, ScraperFlaskMixin):
    """Scrape projected lineups and minutes from RotoWire."""

    scraper_name = "rotowire_lineups"
    required_params = ["date"]
    optional_params = {}

    required_opts: List[str] = ["date"]
    download_type: DownloadType = DownloadType.HTML
    decode_download_data: bool = True
    header_profile: str | None = None
    proxy_enabled: bool = True
    # Try plain HTTP first — Playwright not installed in production Docker image
    browser_enabled: bool = False

    CRAWL_DELAY_SECONDS = 2.5

    GCS_PATH_KEY = "rotowire_lineups"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/rotowire_lineups_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_rotowire_%(date)s.html",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    def set_url(self) -> None:
        self.url = "https://www.rotowire.com/basketball/nba-lineups.php"
        logger.info("RotoWire lineups URL: %s", self.url)

    def set_headers(self) -> None:
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
            "Referer": "https://www.rotowire.com/basketball/",
        }

    def download_data(self):
        logger.info("Waiting %.1f seconds for rate limiting...", self.CRAWL_DELAY_SECONDS)
        time.sleep(self.CRAWL_DELAY_SECONDS)
        super().download_data()

    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, str):
            raise ValueError("Expected HTML string")
        html_lower = self.decoded_data.lower()
        if "<html" not in html_lower:
            raise ValueError("Response doesn't appear to be HTML")

    def transform_data(self) -> None:
        """Parse RotoWire lineups page and extract game + player data."""
        soup = BeautifulSoup(self.decoded_data, "html.parser")

        games = []

        # RotoWire uses lineup cards with class "lineup" or "lineup__main"
        lineup_cards = soup.find_all("div", class_=re.compile(r"lineup(?!-)|lineups-card"))
        if not lineup_cards:
            # Fallback: look for game containers
            lineup_cards = soup.find_all("div", class_=re.compile(r"game-card|matchup"))

        if not lineup_cards:
            # Try to parse from any structured content
            games = self._try_parse_flat_layout(soup)
        else:
            for card in lineup_cards:
                game_data = self._parse_lineup_card(card)
                if game_data:
                    games.append(game_data)

        total_players = sum(len(g.get("away_players", [])) + len(g.get("home_players", [])) for g in games)

        self.data = {
            "source": "rotowire",
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "game_count": len(games),
            "total_players": total_players,
            "games": games,
        }

        logger.info("Parsed %d games with %d total players from RotoWire", len(games), total_players)

        if games:
            try:
                notify_info(
                    title="RotoWire Lineups Scraped",
                    message=f"Scraped {len(games)} game lineups with {total_players} players",
                    details={'game_count': len(games), 'total_players': total_players},
                    processor_name=self.__class__.__name__
                )
            except Exception:
                pass

    def _parse_lineup_card(self, card) -> Optional[Dict]:
        """Parse a single game lineup card."""
        try:
            # Extract team names
            team_elements = card.find_all(class_=re.compile(r"team-name|lineup__team"))
            teams = []
            for elem in team_elements:
                text = elem.get_text(strip=True)
                if text:
                    teams.append(text)

            # Also check for abbrev elements
            if len(teams) < 2:
                abbr_elements = card.find_all(class_=re.compile(r"team-abbr|lineup__abbr"))
                for elem in abbr_elements:
                    text = elem.get_text(strip=True).upper()
                    if text and len(text) <= 4:
                        teams.append(text)

            away_team = teams[0] if len(teams) > 0 else ""
            home_team = teams[1] if len(teams) > 1 else ""

            # Extract player lists — typically two columns (away/home)
            player_sections = card.find_all("ul", class_=re.compile(r"lineup__list|players"))
            if len(player_sections) < 2:
                player_sections = card.find_all("div", class_=re.compile(r"lineup__players"))

            away_players = []
            home_players = []

            if len(player_sections) >= 2:
                away_players = self._parse_player_list(player_sections[0])
                home_players = self._parse_player_list(player_sections[1])
            elif len(player_sections) == 1:
                # All players in one section
                all_players = self._parse_player_list(player_sections[0])
                mid = len(all_players) // 2
                away_players = all_players[:mid]
                home_players = all_players[mid:]

            # Extract game time
            time_elem = card.find(class_=re.compile(r"game-time|lineup__time|time"))
            game_time = time_elem.get_text(strip=True) if time_elem else ""

            return {
                "away_team": away_team,
                "home_team": home_team,
                "game_time": game_time,
                "away_players": away_players,
                "home_players": home_players,
            }
        except Exception as e:
            logger.debug("Error parsing lineup card: %s", e)
            return None

    def _parse_player_list(self, container) -> List[Dict]:
        """Parse a player list element into structured player data."""
        players = []
        items = container.find_all("li") or container.find_all("div", class_=re.compile(r"player"))

        for i, item in enumerate(items):
            player = self._parse_player_item(item, lineup_position=i + 1)
            if player:
                players.append(player)

        return players

    def _parse_player_item(self, item, lineup_position: int = 0) -> Optional[Dict]:
        """Parse a single player item."""
        try:
            # Get player name
            link = item.find("a")
            name = link.get_text(strip=True) if link else item.get_text(strip=True)
            if not name or len(name) < 3:
                return None

            # Check for injury indicator
            injury_elem = item.find(class_=re.compile(r"injury|status|tag"))
            injury_status = ""
            if injury_elem:
                status_text = injury_elem.get_text(strip=True).upper()
                injury_status = INJURY_STATUSES.get(status_text, status_text.lower())

            # Check for position
            pos_elem = item.find(class_=re.compile(r"position|pos"))
            position = pos_elem.get_text(strip=True).upper() if pos_elem else ""

            # Check for projected minutes (if shown)
            mins_elem = item.find(class_=re.compile(r"minutes|mins|min"))
            projected_minutes = None
            if mins_elem:
                try:
                    projected_minutes = float(mins_elem.get_text(strip=True))
                except (ValueError, TypeError):
                    pass

            # Extract play probability from CSS class (e.g., is-pct-play-100)
            play_probability = None
            item_classes = item.get("class", [])
            for cls in item_classes:
                pct_match = re.search(r'is-pct-play-(\d+)', cls)
                if pct_match:
                    play_probability = int(pct_match.group(1))
                    break

            is_starter = lineup_position <= 5

            return {
                "player_name": name,
                "player_lookup": normalize_player_name(name),
                "position": position,
                "lineup_position": lineup_position,
                "is_starter": is_starter,
                "injury_status": injury_status,
                "projected_minutes": projected_minutes,
                "play_probability": play_probability,
            }
        except Exception as e:
            logger.debug("Error parsing player item: %s", e)
            return None

    def _try_parse_flat_layout(self, soup) -> List[Dict]:
        """Try to parse lineups from a flat/non-card layout."""
        games = []
        # Look for tables with player names
        tables = soup.find_all("table")
        for table in tables:
            text = table.get_text().lower()
            if "lineup" in text or "starter" in text:
                # Try to extract players from table
                rows = table.find_all("tr")
                players = []
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    for cell in cells:
                        link = cell.find("a")
                        if link:
                            name = link.get_text(strip=True)
                            if name and " " in name:
                                players.append({
                                    "player_name": name,
                                    "player_lookup": normalize_player_name(name),
                                    "position": "",
                                    "lineup_position": len(players) + 1,
                                    "is_starter": len(players) < 5,
                                    "injury_status": "",
                                    "projected_minutes": None,
                                })
                if players:
                    games.append({
                        "away_team": "",
                        "home_team": "",
                        "game_time": "",
                        "away_players": players[:len(players)//2],
                        "home_players": players[len(players)//2:],
                    })
        return games

    def get_scraper_stats(self) -> dict:
        return {
            "date": self.opts.get("date"),
            "game_count": self.data.get("game_count", 0),
            "total_players": self.data.get("total_players", 0),
        }


create_app = convert_existing_flask_scraper(RotoWireLineupsScraper)

if __name__ == "__main__":
    main = RotoWireLineupsScraper.create_cli_and_flask_main()
    main()

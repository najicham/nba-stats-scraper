# File: scrapers/projections/numberfire_projections.py
"""
NumberFire NBA Player Projections Scraper                       v1.0 - 2026-03-04
---------------------------------------------------------------------------------
Scrapes daily fantasy basketball projections from NumberFire for consensus signal.

URL: https://www.numberfire.com/nba/daily-fantasy/daily-basketball-projections
Data: Projected points, minutes, usage for every player daily.
Access: Free, clean HTML tables, no auth.
Timing: Updates by ~10 AM ET.

The projected points are compared against our model's predicted_points and the
prop line to create a projection_consensus signal. When 2+ external projections
agree with our model direction, the signal fires (expected HR 65-70%).

Usage:
  python scrapers/projections/numberfire_projections.py --date 2026-03-04 --debug
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

from shared.utils.notification_system import notify_error, notify_warning, notify_info

logger = logging.getLogger("scraper_base")

# Player name normalization for matching against our player_lookup format
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
    """Convert player name to player_lookup format (lowercase, hyphenated)."""
    if not name:
        return ""
    # Remove suffixes
    for suffix in [" Jr.", " Sr.", " Jr", " Sr", " III", " II", " IV"]:
        name = name.replace(suffix, "")
    # Lowercase, replace spaces with hyphens, remove non-alphanumeric except hyphens
    normalized = name.lower().strip()
    normalized = re.sub(r'[^a-z\s-]', '', normalized)
    normalized = re.sub(r'\s+', '-', normalized)
    return normalized


class NumberFireProjectionsScraper(ScraperBase, ScraperFlaskMixin):
    """Scrape daily NBA player projections from NumberFire."""

    # Flask Mixin Configuration
    scraper_name = "numberfire_projections"
    required_params = ["date"]
    optional_params = {}

    # Scraper config
    required_opts: List[str] = ["date"]
    download_type: DownloadType = DownloadType.HTML
    decode_download_data: bool = True
    header_profile: str | None = None
    proxy_enabled: bool = True

    # Rate limiting
    CRAWL_DELAY_SECONDS = 2.0

    # GCS export configuration
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
        {
            "type": "file",
            "filename": "/tmp/raw_numberfire_%(date)s.html",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    def set_url(self) -> None:
        """Build NumberFire projections URL."""
        self.url = "https://www.numberfire.com/nba/daily-fantasy/daily-basketball-projections"
        logger.info("NumberFire projections URL: %s", self.url)

    def set_headers(self) -> None:
        """Set browser-like headers for NumberFire."""
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    def download_data(self):
        """Override to add rate limiting delay."""
        logger.info("Waiting %.1f seconds for rate limiting...", self.CRAWL_DELAY_SECONDS)
        time.sleep(self.CRAWL_DELAY_SECONDS)
        super().download_data()

    def validate_download_data(self) -> None:
        """Validate that we received a proper NumberFire page."""
        if not isinstance(self.decoded_data, str):
            raise ValueError("Expected HTML string")
        html_lower = self.decoded_data.lower()
        if "<html" not in html_lower:
            raise ValueError("Response doesn't appear to be HTML")
        if "numberfire" not in html_lower:
            raise ValueError("Response doesn't appear to be from NumberFire")

    def transform_data(self) -> None:
        """Parse NumberFire projections page and extract player projection data."""
        soup = BeautifulSoup(self.decoded_data, "html.parser")

        players = []

        # NumberFire uses a projection table with class "projection-table"
        # Structure: table rows with player name, team, position, projected stats
        projection_table = soup.find("table", class_=re.compile(r"projection"))
        if not projection_table:
            # Fallback: look for any table with player data
            all_tables = soup.find_all("table")
            for table in all_tables:
                text = table.get_text().lower()
                if "pts" in text and ("player" in text or "name" in text):
                    projection_table = table
                    break

        if not projection_table:
            # Try parsing from script/JSON data embedded in page
            players = self._try_parse_embedded_data(soup)
            if not players:
                logger.warning("Could not find projection table on NumberFire page")
                try:
                    notify_warning(
                        title="NumberFire No Projection Table",
                        message="Could not find projection table on NumberFire page",
                        details={'url': self.url, 'date': self.opts.get('date')},
                        processor_name=self.__class__.__name__
                    )
                except Exception:
                    pass
                self.data = self._create_empty_result()
                return
        else:
            players = self._parse_projection_table(projection_table)

        # Build final data structure
        self.data = {
            "source": "numberfire",
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "player_count": len(players),
            "players": players,
        }

        logger.info("Parsed %d player projections from NumberFire", len(players))

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

    def _parse_projection_table(self, table) -> List[Dict]:
        """Parse the projection HTML table into structured player data."""
        players = []
        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

        # Detect column headers
        header_row = table.find("thead")
        headers = []
        if header_row:
            for th in header_row.find_all(["th", "td"]):
                headers.append(th.get_text(strip=True).lower())

        # Map column indices
        pts_col = self._find_column_index(headers, ["pts", "points", "fp", "fpts"])
        min_col = self._find_column_index(headers, ["min", "minutes"])
        reb_col = self._find_column_index(headers, ["reb", "rebounds"])
        ast_col = self._find_column_index(headers, ["ast", "assists"])

        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue

            player_data = self._extract_player_from_row(cells, pts_col, min_col, reb_col, ast_col)
            if player_data and player_data.get("player_name"):
                players.append(player_data)

        return players

    def _extract_player_from_row(self, cells, pts_col, min_col, reb_col, ast_col) -> Optional[Dict]:
        """Extract player projection from a single table row."""
        try:
            # Find player name — look for links first, then text
            player_name = ""
            team = ""
            position = ""

            for cell in cells[:3]:
                link = cell.find("a")
                if link:
                    name_text = link.get_text(strip=True)
                    if len(name_text) > 3 and " " in name_text:
                        player_name = name_text
                        break

            if not player_name:
                # Fallback: first cell with a multi-word text
                for cell in cells[:3]:
                    text = cell.get_text(strip=True)
                    if len(text) > 3 and " " in text and not re.match(r'^[\d.]+$', text):
                        player_name = text
                        break

            if not player_name:
                return None

            # Extract team/position from nearby cells or spans
            for cell in cells[:3]:
                spans = cell.find_all("span")
                for span in spans:
                    text = span.get_text(strip=True).upper()
                    if text in TEAM_ABBR_MAP:
                        team = TEAM_ABBR_MAP.get(text, text)
                    elif text in ("PG", "SG", "SF", "PF", "C", "G", "F"):
                        position = text

            # Extract numeric projections
            cell_texts = [c.get_text(strip=True) for c in cells]
            projected_points = self._extract_numeric(cell_texts, pts_col)
            projected_minutes = self._extract_numeric(cell_texts, min_col)
            projected_rebounds = self._extract_numeric(cell_texts, reb_col)
            projected_assists = self._extract_numeric(cell_texts, ast_col)

            # If we couldn't find pts via header, try to find the first float-like value
            if projected_points is None:
                for text in cell_texts[1:]:
                    val = self._try_parse_float(text)
                    if val is not None and 5.0 <= val <= 60.0:
                        projected_points = val
                        break

            player_lookup = normalize_player_name(player_name)

            return {
                "player_name": player_name,
                "player_lookup": player_lookup,
                "team": team,
                "position": position,
                "projected_points": projected_points,
                "projected_minutes": projected_minutes,
                "projected_rebounds": projected_rebounds,
                "projected_assists": projected_assists,
            }

        except Exception as e:
            logger.debug("Error parsing NumberFire row: %s", e)
            return None

    def _try_parse_embedded_data(self, soup) -> List[Dict]:
        """Try to extract projection data from embedded JSON/script tags."""
        players = []
        for script in soup.find_all("script"):
            script_text = script.string or ""
            if "projections" in script_text.lower() and "player" in script_text.lower():
                # Try to extract JSON data from script tag
                import json
                json_match = re.search(r'(?:projections|players)\s*[=:]\s*(\[.*?\]);', script_text, re.DOTALL)
                if json_match:
                    try:
                        data = json.loads(json_match.group(1))
                        for item in data:
                            if isinstance(item, dict):
                                name = item.get("name") or item.get("player_name") or item.get("display_name", "")
                                pts = item.get("pts") or item.get("points") or item.get("projected_points")
                                if name and pts:
                                    players.append({
                                        "player_name": name,
                                        "player_lookup": normalize_player_name(name),
                                        "team": item.get("team", ""),
                                        "position": item.get("position", ""),
                                        "projected_points": float(pts) if pts else None,
                                        "projected_minutes": self._safe_float(item.get("min") or item.get("minutes")),
                                        "projected_rebounds": self._safe_float(item.get("reb") or item.get("rebounds")),
                                        "projected_assists": self._safe_float(item.get("ast") or item.get("assists")),
                                    })
                    except (json.JSONDecodeError, ValueError):
                        continue
        return players

    def _find_column_index(self, headers: List[str], candidates: List[str]) -> Optional[int]:
        """Find column index matching any candidate header name."""
        for i, header in enumerate(headers):
            if any(c in header for c in candidates):
                return i
        return None

    def _extract_numeric(self, cell_texts: List[str], col_index: Optional[int]) -> Optional[float]:
        """Extract numeric value from cell at given column index."""
        if col_index is None or col_index >= len(cell_texts):
            return None
        return self._try_parse_float(cell_texts[col_index])

    def _try_parse_float(self, text: str) -> Optional[float]:
        """Try to parse a float from text."""
        if not text:
            return None
        try:
            cleaned = re.sub(r'[,$%]', '', text.strip())
            return float(cleaned)
        except (ValueError, TypeError):
            return None

    def _safe_float(self, val) -> Optional[float]:
        """Safely convert value to float."""
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _create_empty_result(self) -> Dict:
        """Create empty result when no data found."""
        return {
            "source": "numberfire",
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "player_count": 0,
            "players": [],
            "error": "No projection data found",
        }

    def get_scraper_stats(self) -> dict:
        """Return stats for logging."""
        return {
            "date": self.opts.get("date"),
            "player_count": self.data.get("player_count", 0),
        }


# Flask and CLI entry points
create_app = convert_existing_flask_scraper(NumberFireProjectionsScraper)

if __name__ == "__main__":
    main = NumberFireProjectionsScraper.create_cli_and_flask_main()
    main()

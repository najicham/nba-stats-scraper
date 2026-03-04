# File: scrapers/projections/dimers_projections.py
"""
Dimers NBA Player Projections Scraper                          v1.0 - 2026-03-04
---------------------------------------------------------------------------------
Scrapes player projections from Dimers.com for consensus signal generation.

URL: https://www.dimers.com/nba/player-projections
Data: Projected points, minutes for every player daily.
Access: Free, HTML tables, no auth.
Timing: Updates morning of game day.

Used alongside NumberFire, FantasyPros, and DailyFantasyFuel projections to
create a projection consensus signal. When 2+ independent projection sources
agree with our model direction, the signal fires (expected HR 65-70%).

Usage:
  python scrapers/projections/dimers_projections.py --date 2026-03-04 --debug
"""

from __future__ import annotations

import json
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

# Reuse canonical team abbreviation map from numberfire
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
    for suffix in [" Jr.", " Sr.", " Jr", " Sr", " III", " II", " IV"]:
        name = name.replace(suffix, "")
    normalized = name.lower().strip()
    normalized = re.sub(r'[^a-z\s-]', '', normalized)
    normalized = re.sub(r'\s+', '-', normalized)
    return normalized


class DimersProjectionsScraper(ScraperBase, ScraperFlaskMixin):
    """Scrape daily NBA player projections from Dimers."""

    # Flask Mixin Configuration
    scraper_name = "dimers_projections"
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
    GCS_PATH_KEY = "dimers_projections"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/dimers_projections_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_dimers_%(date)s.html",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    def set_url(self) -> None:
        """Build Dimers projections URL."""
        self.url = "https://www.dimers.com/nba/player-projections"
        logger.info("Dimers projections URL: %s", self.url)

    def set_headers(self) -> None:
        """Set browser-like headers for Dimers."""
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
        """Validate that we received a proper Dimers page."""
        if not isinstance(self.decoded_data, str):
            raise ValueError("Expected HTML string")
        html_lower = self.decoded_data.lower()
        if "<html" not in html_lower:
            raise ValueError("Response doesn't appear to be HTML")
        if "dimers" not in html_lower:
            raise ValueError("Response doesn't appear to be from Dimers")

    def transform_data(self) -> None:
        """Parse Dimers projections page and extract player data."""
        soup = BeautifulSoup(self.decoded_data, "html.parser")

        players = []

        # Dimers may use various table structures for player projections
        # Try id-based selectors first, then class-based, then generic
        projection_table = (
            soup.find("table", {"id": "projections"})
            or soup.find("table", {"id": "player-projections"})
            or soup.find("table", class_=re.compile(r"projection|player.*table"))
        )

        if not projection_table:
            # Broader search: any table with projection-related headers
            all_tables = soup.find_all("table")
            for table in all_tables:
                text = table.get_text().lower()
                if ("pts" in text or "points" in text or "proj" in text) and (
                    "player" in text or "name" in text
                ):
                    if len(table.find_all("tr")) > 5:
                        projection_table = table
                        break

        if not projection_table:
            # Last resort: any sizable table
            for table in soup.find_all("table"):
                rows = table.find_all("tr")
                if len(rows) > 10:
                    projection_table = table
                    break

        if not projection_table:
            # Try embedded JSON data (Dimers may use React/Next.js hydration)
            players = self._try_parse_embedded_data(soup)
            if not players:
                logger.warning("Could not find projection table on Dimers page")
                try:
                    notify_warning(
                        title="Dimers No Projection Table",
                        message="Could not find projection table on Dimers page",
                        details={'url': self.url, 'date': self.opts.get('date')},
                        processor_name=self.__class__.__name__
                    )
                except Exception:
                    pass
                self.data = self._create_empty_result()
                return
        else:
            players = self._parse_projection_table(projection_table)

        self.data = {
            "source": "dimers",
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "player_count": len(players),
            "players": players,
        }

        logger.info("Parsed %d player projections from Dimers", len(players))

        if players:
            try:
                notify_info(
                    title="Dimers Projections Scraped",
                    message=f"Scraped {len(players)} player projections for {self.opts['date']}",
                    details={'player_count': len(players), 'date': self.opts['date']},
                    processor_name=self.__class__.__name__
                )
            except Exception:
                pass

    def _parse_projection_table(self, table) -> List[Dict]:
        """Parse the projection HTML table into structured player data."""
        players = []
        header_row = table.find("thead")
        headers = []
        if header_row:
            for th in header_row.find_all(["th", "td"]):
                headers.append(th.get_text(strip=True).lower())

        # Map column indices for Dimers columns
        pts_col = self._find_column_index(headers, ["pts", "proj", "points", "fp", "fpts", "projection"])
        min_col = self._find_column_index(headers, ["min", "minutes"])
        salary_col = self._find_column_index(headers, ["salary", "sal", "$"])
        pos_col = self._find_column_index(headers, ["pos", "position"])
        team_col = self._find_column_index(headers, ["team", "tm"])

        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue

            player_data = self._extract_player_from_row(
                cells, pts_col, min_col, salary_col, pos_col, team_col
            )
            if player_data and player_data.get("player_name"):
                players.append(player_data)

        return players

    def _extract_player_from_row(
        self, cells, pts_col, min_col, salary_col, pos_col, team_col
    ) -> Optional[Dict]:
        """Extract player projection from a single table row."""
        try:
            player_name = ""
            team = ""
            position = ""

            # Look for player name as a link first
            first_cell = cells[0]
            link = first_cell.find("a")
            if link:
                player_name = link.get_text(strip=True)
            else:
                text = first_cell.get_text(strip=True)
                if len(text) > 3 and " " in text:
                    player_name = text

            if not player_name:
                # Try second cell in case first is a rank column
                if len(cells) > 1:
                    second_cell = cells[1]
                    link = second_cell.find("a")
                    if link:
                        player_name = link.get_text(strip=True)
                    else:
                        text = second_cell.get_text(strip=True)
                        if len(text) > 3 and " " in text and not re.match(r'^[\d.]+$', text):
                            player_name = text

            if not player_name:
                return None

            # Extract team/position from dedicated columns
            cell_texts = [c.get_text(strip=True) for c in cells]

            if team_col is not None and team_col < len(cell_texts):
                raw_team = cell_texts[team_col].upper().strip()
                team = TEAM_ABBR_MAP.get(raw_team, raw_team)

            if pos_col is not None and pos_col < len(cell_texts):
                position = cell_texts[pos_col].upper().strip()

            # Fallback: look for team/position in small tags or spans
            if not team or not position:
                for cell in cells[:3]:
                    small_tags = cell.find_all(["small", "span", "em"])
                    for tag in small_tags:
                        text = tag.get_text(strip=True).upper()
                        parts = re.split(r'[\s\-/]+', text)
                        for part in parts:
                            if not team and part in TEAM_ABBR_MAP:
                                team = TEAM_ABBR_MAP[part]
                            elif not position and part in ("PG", "SG", "SF", "PF", "C", "G", "F"):
                                position = part

            # Extract numeric projections
            projected_points = self._extract_numeric(cell_texts, pts_col)
            projected_minutes = self._extract_numeric(cell_texts, min_col)

            # Salary if available
            salary = None
            if salary_col is not None and salary_col < len(cell_texts):
                salary = self._try_parse_salary(cell_texts[salary_col])

            # Fallback: find first reasonable points value if pts_col missed
            if projected_points is None:
                for text in cell_texts[1:]:
                    val = self._try_parse_float(text)
                    if val is not None and 5.0 <= val <= 60.0:
                        projected_points = val
                        break

            return {
                "player_name": player_name,
                "player_lookup": normalize_player_name(player_name),
                "team": team,
                "position": position,
                "projected_points": projected_points,
                "projected_minutes": projected_minutes,
                "salary": salary,
            }
        except Exception as e:
            logger.debug("Error parsing Dimers row: %s", e)
            return None

    def _try_parse_embedded_data(self, soup) -> List[Dict]:
        """Try to extract projection data from embedded JSON/script tags.

        Dimers uses Next.js / React hydration, so projection data may be in
        __NEXT_DATA__ or similar script payloads.
        """
        players = []

        # Try __NEXT_DATA__ (Next.js hydration payload)
        next_data_script = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_data_script and next_data_script.string:
            try:
                next_data = json.loads(next_data_script.string)
                players = self._extract_from_next_data(next_data)
                if players:
                    return players
            except (json.JSONDecodeError, ValueError):
                pass

        # Generic script tag search
        for script in soup.find_all("script"):
            script_text = script.string or ""
            if "projections" in script_text.lower() and "player" in script_text.lower():
                # Try array format
                json_match = re.search(
                    r'(?:projections|players)\s*[=:]\s*(\[.*?\]);',
                    script_text, re.DOTALL
                )
                if json_match:
                    try:
                        data = json.loads(json_match.group(1))
                        for item in data:
                            if isinstance(item, dict):
                                name = (
                                    item.get("name")
                                    or item.get("player_name")
                                    or item.get("display_name", "")
                                )
                                pts = (
                                    item.get("pts")
                                    or item.get("points")
                                    or item.get("projected_points")
                                    or item.get("projection")
                                )
                                if name and pts:
                                    raw_team = str(item.get("team", "")).upper()
                                    players.append({
                                        "player_name": name,
                                        "player_lookup": normalize_player_name(name),
                                        "team": TEAM_ABBR_MAP.get(raw_team, raw_team),
                                        "position": item.get("position", ""),
                                        "projected_points": float(pts),
                                        "projected_minutes": self._safe_float(
                                            item.get("min") or item.get("minutes")
                                        ),
                                        "salary": self._safe_int(
                                            item.get("salary") or item.get("sal")
                                        ),
                                    })
                    except (json.JSONDecodeError, ValueError):
                        continue
                # Try object format
                json_match = re.search(
                    r'(?:projections|playerData)\s*[=:]\s*(\{.*?\});',
                    script_text, re.DOTALL
                )
                if json_match and not players:
                    try:
                        data = json.loads(json_match.group(1))
                        player_list = data.get("players", data.get("projections", []))
                        if isinstance(player_list, list):
                            for item in player_list:
                                if isinstance(item, dict):
                                    name = (
                                        item.get("player_name")
                                        or item.get("name", "")
                                    )
                                    pts = item.get("pts") or item.get("points")
                                    if name and pts:
                                        raw_team = str(item.get("team", "")).upper()
                                        players.append({
                                            "player_name": name,
                                            "player_lookup": normalize_player_name(name),
                                            "team": TEAM_ABBR_MAP.get(raw_team, raw_team),
                                            "position": item.get("position", ""),
                                            "projected_points": float(pts),
                                            "projected_minutes": self._safe_float(
                                                item.get("min")
                                            ),
                                            "salary": self._safe_int(
                                                item.get("salary")
                                            ),
                                        })
                    except (json.JSONDecodeError, ValueError):
                        continue
        return players

    def _extract_from_next_data(self, next_data: dict) -> List[Dict]:
        """Extract player projections from Next.js __NEXT_DATA__ payload."""
        players = []

        # Recursively search for projection arrays in the nested JSON
        def _search(obj, depth=0):
            if depth > 10:
                return
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict):
                        name = (
                            item.get("playerName")
                            or item.get("player_name")
                            or item.get("name", "")
                        )
                        pts = (
                            item.get("projectedPoints")
                            or item.get("projected_points")
                            or item.get("pts")
                            or item.get("points")
                        )
                        if name and pts:
                            raw_team = str(
                                item.get("team")
                                or item.get("teamAbbr")
                                or ""
                            ).upper()
                            players.append({
                                "player_name": name,
                                "player_lookup": normalize_player_name(name),
                                "team": TEAM_ABBR_MAP.get(raw_team, raw_team),
                                "position": item.get("position", ""),
                                "projected_points": float(pts),
                                "projected_minutes": self._safe_float(
                                    item.get("minutes") or item.get("min")
                                ),
                                "salary": self._safe_int(item.get("salary")),
                            })
                    _search(item, depth + 1)
            elif isinstance(obj, dict):
                for value in obj.values():
                    _search(value, depth + 1)

        _search(next_data)
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

    def _try_parse_salary(self, text: str) -> Optional[int]:
        """Parse DFS salary value like '$10,200' -> 10200."""
        if not text:
            return None
        try:
            cleaned = re.sub(r'[$,\s]', '', text.strip())
            return int(float(cleaned))
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

    def _safe_int(self, val) -> Optional[int]:
        """Safely convert value to int."""
        if val is None:
            return None
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return None

    def _create_empty_result(self) -> Dict:
        """Create empty result when no data found."""
        return {
            "source": "dimers",
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
create_app = convert_existing_flask_scraper(DimersProjectionsScraper)

if __name__ == "__main__":
    main = DimersProjectionsScraper.create_cli_and_flask_main()
    main()

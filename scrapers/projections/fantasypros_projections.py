# File: scrapers/projections/fantasypros_projections.py
"""
FantasyPros NBA Consensus Projections Scraper                   v1.0 - 2026-03-04
----------------------------------------------------------------------------------
Scrapes consensus player projections aggregated from multiple DFS sites.

URL: https://www.fantasypros.com/nba/projections/
Data: Consensus projected points, rebounds, assists, etc.
Access: Free tier, structured HTML tables.
Timing: Updates early morning.

Used alongside NumberFire projections to create a projection consensus signal.
When 2+ independent projection sources agree with our model direction, the
signal fires with expected HR of 65-70%.

Usage:
  python scrapers/projections/fantasypros_projections.py --date 2026-03-04 --debug
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


class FantasyProsProjectionsScraper(ScraperBase, ScraperFlaskMixin):
    """Scrape daily NBA consensus projections from FantasyPros."""

    # Flask Mixin Configuration
    scraper_name = "fantasypros_projections"
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
    GCS_PATH_KEY = "fantasypros_projections"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/fantasypros_projections_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_fantasypros_%(date)s.html",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    def set_url(self) -> None:
        """Build FantasyPros projections URL."""
        self.url = "https://www.fantasypros.com/nba/projections/tot.php"
        logger.info("FantasyPros projections URL: %s", self.url)

    def set_headers(self) -> None:
        """Set browser-like headers for FantasyPros."""
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
        """Validate that we received a proper FantasyPros page."""
        if not isinstance(self.decoded_data, str):
            raise ValueError("Expected HTML string")
        html_lower = self.decoded_data.lower()
        if "<html" not in html_lower:
            raise ValueError("Response doesn't appear to be HTML")
        if "fantasypros" not in html_lower:
            raise ValueError("Response doesn't appear to be from FantasyPros")

    def transform_data(self) -> None:
        """Parse FantasyPros projections page and extract player data."""
        soup = BeautifulSoup(self.decoded_data, "html.parser")

        players = []

        # FantasyPros uses an #data table or data-table class
        projection_table = (
            soup.find("table", {"id": "data"})
            or soup.find("table", {"id": "projections"})
            or soup.find("table", class_=re.compile(r"table.*projections|projections.*table"))
        )

        if not projection_table:
            # Broader search
            all_tables = soup.find_all("table")
            for table in all_tables:
                text = table.get_text().lower()
                if "pts" in text and len(table.find_all("tr")) > 5:
                    projection_table = table
                    break

        if not projection_table:
            players = self._try_parse_embedded_data(soup)
            if not players:
                logger.warning("Could not find projection table on FantasyPros page")
                try:
                    notify_warning(
                        title="FantasyPros No Projection Table",
                        message="Could not find projection table on FantasyPros page",
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
            "source": "fantasypros",
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "player_count": len(players),
            "players": players,
        }

        logger.info("Parsed %d player projections from FantasyPros", len(players))

        if players:
            try:
                notify_info(
                    title="FantasyPros Projections Scraped",
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

        pts_col = self._find_column_index(headers, ["pts", "points"])
        min_col = self._find_column_index(headers, ["min", "minutes"])
        reb_col = self._find_column_index(headers, ["reb", "rebounds"])
        ast_col = self._find_column_index(headers, ["ast", "assists"])

        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

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
            player_name = ""
            team = ""
            position = ""

            # FantasyPros typically has player name as a link in the first cell
            first_cell = cells[0]
            link = first_cell.find("a")
            if link:
                player_name = link.get_text(strip=True)
            else:
                text = first_cell.get_text(strip=True)
                if len(text) > 3 and " " in text:
                    player_name = text

            if not player_name:
                return None

            # FantasyPros often has team/position in small text or spans
            small_tags = first_cell.find_all(["small", "span", "em"])
            for tag in small_tags:
                text = tag.get_text(strip=True).upper()
                # Check for "DAL - PG" or "LAL PG" patterns
                parts = re.split(r'[\s\-]+', text)
                for part in parts:
                    if part in ("PG", "SG", "SF", "PF", "C", "G", "F"):
                        position = part
                    elif len(part) in (2, 3) and part.isalpha():
                        from scrapers.projections.numberfire_projections import TEAM_ABBR_MAP
                        if part in TEAM_ABBR_MAP:
                            team = TEAM_ABBR_MAP[part]

            cell_texts = [c.get_text(strip=True) for c in cells]
            projected_points = self._extract_numeric(cell_texts, pts_col)
            projected_minutes = self._extract_numeric(cell_texts, min_col)
            projected_rebounds = self._extract_numeric(cell_texts, reb_col)
            projected_assists = self._extract_numeric(cell_texts, ast_col)

            # Fallback: find first reasonable points value
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
                "projected_rebounds": projected_rebounds,
                "projected_assists": projected_assists,
            }
        except Exception as e:
            logger.debug("Error parsing FantasyPros row: %s", e)
            return None

    def _try_parse_embedded_data(self, soup) -> List[Dict]:
        """Try to extract projection data from embedded JSON/script tags."""
        import json
        players = []
        for script in soup.find_all("script"):
            script_text = script.string or ""
            if "ecrData" in script_text or "projections" in script_text.lower():
                json_match = re.search(r'(?:ecrData|projections)\s*[=:]\s*(\{.*?\});', script_text, re.DOTALL)
                if json_match:
                    try:
                        data = json.loads(json_match.group(1))
                        player_list = data.get("players", data.get("projections", []))
                        if isinstance(player_list, list):
                            for item in player_list:
                                if isinstance(item, dict):
                                    name = item.get("player_name") or item.get("name", "")
                                    pts = item.get("pts") or item.get("points")
                                    if name and pts:
                                        players.append({
                                            "player_name": name,
                                            "player_lookup": normalize_player_name(name),
                                            "team": item.get("team", ""),
                                            "position": item.get("position", ""),
                                            "projected_points": float(pts),
                                            "projected_minutes": self._safe_float(item.get("min")),
                                            "projected_rebounds": self._safe_float(item.get("reb")),
                                            "projected_assists": self._safe_float(item.get("ast")),
                                        })
                    except (json.JSONDecodeError, ValueError):
                        continue
        return players

    def _find_column_index(self, headers: List[str], candidates: List[str]) -> Optional[int]:
        for i, header in enumerate(headers):
            if any(c in header for c in candidates):
                return i
        return None

    def _extract_numeric(self, cell_texts: List[str], col_index: Optional[int]) -> Optional[float]:
        if col_index is None or col_index >= len(cell_texts):
            return None
        return self._try_parse_float(cell_texts[col_index])

    def _try_parse_float(self, text: str) -> Optional[float]:
        if not text:
            return None
        try:
            cleaned = re.sub(r'[,$%]', '', text.strip())
            return float(cleaned)
        except (ValueError, TypeError):
            return None

    def _safe_float(self, val) -> Optional[float]:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _create_empty_result(self) -> Dict:
        return {
            "source": "fantasypros",
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "player_count": 0,
            "players": [],
            "error": "No projection data found",
        }

    def get_scraper_stats(self) -> dict:
        return {
            "date": self.opts.get("date"),
            "player_count": self.data.get("player_count", 0),
        }


# Flask and CLI entry points
create_app = convert_existing_flask_scraper(FantasyProsProjectionsScraper)

if __name__ == "__main__":
    main = FantasyProsProjectionsScraper.create_cli_and_flask_main()
    main()

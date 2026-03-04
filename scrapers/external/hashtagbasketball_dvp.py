# File: scrapers/external/hashtagbasketball_dvp.py
"""
Hashtag Basketball Defense vs Position Scraper                  v1.0 - 2026-03-04
----------------------------------------------------------------------------------
Scrapes per-team, per-position points/rebounds/assists allowed.

URL: https://hashtagbasketball.com/nba-defense-vs-position
Data: Per-team, per-position DvP rankings (points allowed to PG/SG/SF/PF/C).
Access: Free, clean HTML tables.
Timing: Updates daily.

Creates a dvp_favorable_over signal: when opponent is bottom-5 at defending
player's position AND model says OVER → expected HR 60-65%.

Usage:
  python scrapers/external/hashtagbasketball_dvp.py --date 2026-03-04 --debug
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

# Positions tracked in DvP data
DVP_POSITIONS = ["PG", "SG", "SF", "PF", "C"]

# Team name mapping (Hashtag Basketball uses various formats)
HASHTAG_TEAM_MAP = {
    "atl": "ATL", "bos": "BOS", "bkn": "BKN", "brk": "BKN", "cha": "CHA",
    "chi": "CHI", "cle": "CLE", "dal": "DAL", "den": "DEN", "det": "DET",
    "gs": "GSW", "gsw": "GSW", "hou": "HOU", "ind": "IND", "lac": "LAC",
    "lal": "LAL", "mem": "MEM", "mia": "MIA", "mil": "MIL", "min": "MIN",
    "no": "NOP", "nop": "NOP", "ny": "NYK", "nyk": "NYK", "okc": "OKC",
    "orl": "ORL", "phi": "PHI", "phx": "PHX", "pho": "PHX", "por": "POR",
    "sac": "SAC", "sa": "SAS", "sas": "SAS", "tor": "TOR", "uta": "UTA",
    "was": "WAS",
    # Full names
    "atlanta": "ATL", "boston": "BOS", "brooklyn": "BKN", "charlotte": "CHA",
    "chicago": "CHI", "cleveland": "CLE", "dallas": "DAL", "denver": "DEN",
    "detroit": "DET", "golden state": "GSW", "houston": "HOU", "indiana": "IND",
    "la clippers": "LAC", "la lakers": "LAL", "memphis": "MEM", "miami": "MIA",
    "milwaukee": "MIL", "minnesota": "MIN", "new orleans": "NOP",
    "new york": "NYK", "oklahoma city": "OKC", "orlando": "ORL",
    "philadelphia": "PHI", "phoenix": "PHX", "portland": "POR",
    "sacramento": "SAC", "san antonio": "SAS", "toronto": "TOR",
    "utah": "UTA", "washington": "WAS",
}


def resolve_team(name: str) -> str:
    """Resolve team name to NBA tricode."""
    if not name:
        return ""
    lower = name.lower().strip()
    if lower in HASHTAG_TEAM_MAP:
        return HASHTAG_TEAM_MAP[lower]
    for key, tricode in HASHTAG_TEAM_MAP.items():
        if key in lower or lower in key:
            return tricode
    return name.upper()[:3]


class HashtagBasketballDvpScraper(ScraperBase, ScraperFlaskMixin):
    """Scrape defense vs position data from Hashtag Basketball."""

    scraper_name = "hashtagbasketball_dvp"
    required_params = ["date"]
    optional_params = {}

    required_opts: List[str] = ["date"]
    download_type: DownloadType = DownloadType.HTML
    decode_download_data: bool = True
    header_profile: str | None = None
    proxy_enabled: bool = True

    CRAWL_DELAY_SECONDS = 2.0

    GCS_PATH_KEY = "hashtagbasketball_dvp"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/hashtagbasketball_dvp_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
    ]

    def set_url(self) -> None:
        """Build Hashtag Basketball DvP URL."""
        self.url = "https://hashtagbasketball.com/nba-defense-vs-position"
        logger.info("Hashtag Basketball DvP URL: %s", self.url)

    def set_headers(self) -> None:
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
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
        """Parse DvP page and extract per-team, per-position defense data."""
        soup = BeautifulSoup(self.decoded_data, "html.parser")

        teams_dvp = {}

        # Hashtag Basketball renders multiple tables — one per position or one combined
        # Try combined table first
        tables = soup.find_all("table")

        for table in tables:
            headers = []
            header_row = table.find("thead") or table.find("tr")
            if header_row:
                for th in header_row.find_all(["th", "td"]):
                    headers.append(th.get_text(strip=True).lower())

            # Need at least team + some stats
            if len(headers) < 3:
                continue

            # Check if this looks like a DvP table
            has_pts = any("pts" in h or "points" in h for h in headers)
            has_team = any("team" in h or "name" in h for h in headers)
            if not has_pts:
                continue

            # Detect position from headers or table context
            position = self._detect_position_from_context(table, headers)

            tbody = table.find("tbody")
            rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) < 3:
                    continue

                team_data = self._extract_team_dvp(cells, headers, position)
                if team_data and team_data.get("team"):
                    team = team_data["team"]
                    if team not in teams_dvp:
                        teams_dvp[team] = {"team": team, "positions": {}}
                    pos_key = team_data.get("position", "ALL")
                    teams_dvp[team]["positions"][pos_key] = {
                        "points_allowed": team_data.get("points_allowed"),
                        "rebounds_allowed": team_data.get("rebounds_allowed"),
                        "assists_allowed": team_data.get("assists_allowed"),
                        "rank": team_data.get("rank"),
                    }

        team_list = sorted(teams_dvp.values(), key=lambda t: t.get("team", ""))

        self.data = {
            "source": "hashtagbasketball",
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "team_count": len(team_list),
            "teams": team_list,
        }

        logger.info("Parsed DvP data for %d teams from Hashtag Basketball", len(team_list))

    def _detect_position_from_context(self, table, headers: List[str]) -> str:
        """Detect which position this table covers."""
        # Check headers
        for pos in DVP_POSITIONS:
            if any(pos.lower() in h for h in headers):
                return pos

        # Check table caption/title
        parent = table.parent
        if parent:
            prev = parent.find_previous(["h2", "h3", "h4", "strong"])
            if prev:
                text = prev.get_text(strip=True).upper()
                for pos in DVP_POSITIONS:
                    if pos in text:
                        return pos

        return "ALL"

    def _extract_team_dvp(self, cells, headers: List[str], position: str) -> Optional[Dict]:
        """Extract team DvP data from a row."""
        try:
            team_name = ""
            for cell in cells[:2]:
                link = cell.find("a")
                text = link.get_text(strip=True) if link else cell.get_text(strip=True)
                if len(text) > 1 and not text.isdigit():
                    team_name = text
                    break

            if not team_name:
                return None

            tricode = resolve_team(team_name)
            cell_texts = [c.get_text(strip=True) for c in cells]

            pts_col = None
            reb_col = None
            ast_col = None
            rank_col = None

            for i, h in enumerate(headers):
                if "pts" in h or "points" in h:
                    pts_col = i
                elif "reb" in h:
                    reb_col = i
                elif "ast" in h:
                    ast_col = i
                elif "rank" in h:
                    rank_col = i

            return {
                "team": tricode,
                "position": position,
                "points_allowed": self._safe_float(cell_texts, pts_col),
                "rebounds_allowed": self._safe_float(cell_texts, reb_col),
                "assists_allowed": self._safe_float(cell_texts, ast_col),
                "rank": self._safe_int(cell_texts, rank_col),
            }
        except Exception as e:
            logger.debug("Error parsing DvP row: %s", e)
            return None

    def _safe_float(self, texts: List[str], col: Optional[int]) -> Optional[float]:
        if col is None or col >= len(texts):
            return None
        try:
            return float(texts[col].replace(",", ""))
        except (ValueError, TypeError):
            return None

    def _safe_int(self, texts: List[str], col: Optional[int]) -> Optional[int]:
        if col is None or col >= len(texts):
            return None
        try:
            return int(texts[col])
        except (ValueError, TypeError):
            return None

    def get_scraper_stats(self) -> dict:
        return {
            "date": self.opts.get("date"),
            "team_count": self.data.get("team_count", 0),
        }


create_app = convert_existing_flask_scraper(HashtagBasketballDvpScraper)

if __name__ == "__main__":
    main = HashtagBasketballDvpScraper.create_cli_and_flask_main()
    main()

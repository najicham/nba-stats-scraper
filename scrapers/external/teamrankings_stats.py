# File: scrapers/external/teamrankings_stats.py
"""
TeamRankings NBA Team Stats Scraper                             v1.0 - 2026-03-04
----------------------------------------------------------------------------------
Scrapes predicted pace, offensive efficiency, and defensive efficiency per team.

URLs:
  - https://www.teamrankings.com/nba/stat/possessions-per-game
  - https://www.teamrankings.com/nba/stat/offensive-efficiency
  - https://www.teamrankings.com/nba/stat/defensive-efficiency

Data: Predicted pace, offensive/defensive ratings per team.
Access: Free, clean HTML tables, no auth.
Timing: Updates after each game day (~3 AM ET).

Upgrades the fast_pace_over signal with predicted game pace for tonight's
specific matchup instead of trailing averages.

Usage:
  python scrapers/external/teamrankings_stats.py --date 2026-03-04 --debug
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

# TeamRankings uses full team names — map to NBA tricodes
TEAMRANKINGS_TO_TRICODE = {
    "atlanta": "ATL", "boston": "BOS", "brooklyn": "BKN", "charlotte": "CHA",
    "chicago": "CHI", "cleveland": "CLE", "dallas": "DAL", "denver": "DEN",
    "detroit": "DET", "golden state": "GSW", "golden st": "GSW",
    "houston": "HOU", "indiana": "IND", "la clippers": "LAC",
    "los angeles clippers": "LAC", "la lakers": "LAL",
    "los angeles lakers": "LAL", "memphis": "MEM", "miami": "MIA",
    "milwaukee": "MIL", "minnesota": "MIN", "new orleans": "NOP",
    "new york": "NYK", "oklahoma city": "OKC", "okla city": "OKC",
    "orlando": "ORL", "philadelphia": "PHI", "phoenix": "PHX",
    "portland": "POR", "sacramento": "SAC", "san antonio": "SAS",
    "san ant": "SAS", "toronto": "TOR", "utah": "UTA", "washington": "WAS",
    # Common abbreviations
    "hawks": "ATL", "celtics": "BOS", "nets": "BKN", "hornets": "CHA",
    "bulls": "CHI", "cavaliers": "CLE", "cavs": "CLE", "mavericks": "DAL",
    "mavs": "DAL", "nuggets": "DEN", "pistons": "DET", "warriors": "GSW",
    "rockets": "HOU", "pacers": "IND", "clippers": "LAC", "lakers": "LAL",
    "grizzlies": "MEM", "heat": "MIA", "bucks": "MIL", "timberwolves": "MIN",
    "wolves": "MIN", "pelicans": "NOP", "knicks": "NYK", "thunder": "OKC",
    "magic": "ORL", "76ers": "PHI", "sixers": "PHI", "suns": "PHX",
    "trail blazers": "POR", "blazers": "POR", "kings": "SAC", "spurs": "SAS",
    "raptors": "TOR", "jazz": "UTA", "wizards": "WAS",
}

# Stats to scrape
STAT_URLS = {
    "pace": "https://www.teamrankings.com/nba/stat/possessions-per-game",
    "offensive_efficiency": "https://www.teamrankings.com/nba/stat/offensive-efficiency",
    "defensive_efficiency": "https://www.teamrankings.com/nba/stat/defensive-efficiency",
}


def resolve_team(name: str) -> str:
    """Convert TeamRankings team name to NBA tricode."""
    if not name:
        return ""
    lower = name.lower().strip()
    # Try exact match
    if lower in TEAMRANKINGS_TO_TRICODE:
        return TEAMRANKINGS_TO_TRICODE[lower]
    # Try partial match
    for key, tricode in TEAMRANKINGS_TO_TRICODE.items():
        if key in lower or lower in key:
            return tricode
    return name.upper()[:3]


class TeamRankingsStatsScraper(ScraperBase, ScraperFlaskMixin):
    """Scrape team pace, offensive and defensive efficiency from TeamRankings."""

    scraper_name = "teamrankings_stats"
    required_params = ["date"]
    optional_params = {}

    required_opts: List[str] = ["date"]
    download_type: DownloadType = DownloadType.HTML
    decode_download_data: bool = True
    header_profile: str | None = None
    proxy_enabled: bool = True

    CRAWL_DELAY_SECONDS = 3.0  # Respectful rate limiting

    GCS_PATH_KEY = "teamrankings_team_stats"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/teamrankings_stats_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
    ]

    def set_url(self) -> None:
        """Set initial URL (pace page). We'll fetch all 3 pages in download_and_decode."""
        self.url = STAT_URLS["pace"]
        logger.info("TeamRankings stats URL (pace): %s", self.url)

    def set_headers(self) -> None:
        """Set browser-like headers."""
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
        }

    def download_and_decode(self):
        """Download all 3 stat pages sequentially with rate limiting."""
        pages_data = {}

        for stat_name, stat_url in STAT_URLS.items():
            logger.info("Fetching TeamRankings %s from %s", stat_name, stat_url)
            self.url = stat_url
            time.sleep(self.CRAWL_DELAY_SECONDS)

            try:
                super().download_and_decode()
                pages_data[stat_name] = self.decoded_data
            except Exception as e:
                logger.warning("Failed to fetch %s: %s", stat_name, e)
                pages_data[stat_name] = None

        # Store all pages in decoded_data for transform
        self.decoded_data = pages_data

    def validate_download_data(self) -> None:
        """Validate we got at least the pace page."""
        if not isinstance(self.decoded_data, dict):
            raise ValueError("Expected dict of page data")
        if not self.decoded_data.get("pace"):
            raise ValueError("Failed to download pace data from TeamRankings")

    def transform_data(self) -> None:
        """Parse all TeamRankings stat pages into structured team data."""
        teams: Dict[str, Dict] = {}

        for stat_name, html in self.decoded_data.items():
            if not html or not isinstance(html, str):
                continue
            stat_data = self._parse_stat_table(html, stat_name)
            for team_tricode, value in stat_data.items():
                if team_tricode not in teams:
                    teams[team_tricode] = {"team": team_tricode}
                teams[team_tricode][stat_name] = value

        team_list = sorted(teams.values(), key=lambda t: t.get("team", ""))

        self.data = {
            "source": "teamrankings",
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "team_count": len(team_list),
            "teams": team_list,
        }

        logger.info("Parsed stats for %d teams from TeamRankings", len(team_list))

    def _parse_stat_table(self, html: str, stat_name: str) -> Dict[str, float]:
        """Parse a single TeamRankings stat table into {tricode: value}."""
        soup = BeautifulSoup(html, "html.parser")
        result = {}

        # TeamRankings uses a table with class "tr-table datatable"
        table = (
            soup.find("table", class_=re.compile(r"datatable|tr-table"))
            or soup.find("table", {"id": re.compile(r"DataTables|datatable")})
        )
        if not table:
            all_tables = soup.find_all("table")
            for t in all_tables:
                if len(t.find_all("tr")) > 10:
                    table = t
                    break

        if not table:
            logger.warning("No stat table found for %s", stat_name)
            return result

        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            # First cell is usually rank, second is team name
            team_name = ""
            for cell in cells[:3]:
                link = cell.find("a")
                text = link.get_text(strip=True) if link else cell.get_text(strip=True)
                if len(text) > 3 and not text.isdigit():
                    team_name = text
                    break

            if not team_name:
                continue

            tricode = resolve_team(team_name)
            if not tricode:
                continue

            # Find the "This Season" or first numeric value (column 2 typically)
            for cell in cells[1:]:
                text = cell.get_text(strip=True)
                try:
                    val = float(text.replace(",", ""))
                    if stat_name == "pace" and 90 <= val <= 115:
                        result[tricode] = val
                        break
                    elif "efficiency" in stat_name and 90 <= val <= 130:
                        result[tricode] = val
                        break
                except (ValueError, TypeError):
                    continue

        return result

    def get_scraper_stats(self) -> dict:
        return {
            "date": self.opts.get("date"),
            "team_count": self.data.get("team_count", 0),
        }


create_app = convert_existing_flask_scraper(TeamRankingsStatsScraper)

if __name__ == "__main__":
    main = TeamRankingsStatsScraper.create_cli_and_flask_main()
    main()

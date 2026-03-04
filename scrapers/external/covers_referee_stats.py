# File: scrapers/external/covers_referee_stats.py
"""
Covers.com NBA Referee Statistics Scraper                       v1.0 - 2026-03-04
----------------------------------------------------------------------------------
Scrapes referee O/U tendency statistics from Covers.com.

URL: https://www.covers.com/sport/basketball/nba/referees/statistics/{season}
Data: Per-referee O/U tendency, total games officiated, O/U record.
Access: Free, clean HTML tables.
Timing: Updates after each game day.

Combined with the NBA.com referee assignments scraper (which provides tonight's
assigned crew), this creates a ref_crew_over_tendency signal: crew with 58%+
OVER rate + model says OVER.

Usage:
  python scrapers/external/covers_referee_stats.py --season 2025-2026 --date 2026-03-04 --debug
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


class CoversRefereeStatsScraper(ScraperBase, ScraperFlaskMixin):
    """Scrape referee O/U statistics from Covers.com."""

    scraper_name = "covers_referee_stats"
    required_params = ["date"]
    optional_params = {"season": None}

    required_opts: List[str] = ["date"]
    download_type: DownloadType = DownloadType.HTML
    decode_download_data: bool = True
    header_profile: str | None = None
    proxy_enabled: bool = True

    CRAWL_DELAY_SECONDS = 3.0

    GCS_PATH_KEY = "covers_referee_stats"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/covers_referee_stats_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        # Derive season if not provided (e.g., 2025-2026)
        if not self.opts.get("season"):
            try:
                date_obj = datetime.strptime(self.opts["date"], "%Y-%m-%d")
                if date_obj.month >= 10:
                    season_start = date_obj.year
                else:
                    season_start = date_obj.year - 1
                self.opts["season"] = f"{season_start}-{season_start + 1}"
            except ValueError:
                self.opts["season"] = "2025-2026"

    def set_url(self) -> None:
        season = self.opts.get("season", "2025-2026")
        self.url = f"https://www.covers.com/sport/basketball/nba/referees/statistics/{season}"
        logger.info("Covers.com referee stats URL: %s", self.url)

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
        if "<html" not in self.decoded_data.lower():
            raise ValueError("Response doesn't appear to be HTML")

    def transform_data(self) -> None:
        """Parse Covers.com referee stats page."""
        soup = BeautifulSoup(self.decoded_data, "html.parser")

        referees = []

        # Covers.com uses tables for referee statistics
        tables = soup.find_all("table")
        for table in tables:
            headers = []
            header_row = table.find("thead")
            if header_row:
                for th in header_row.find_all(["th", "td"]):
                    headers.append(th.get_text(strip=True).lower())

            # Look for table with referee names and O/U data
            has_referee = any("referee" in h or "name" in h or "official" in h for h in headers)
            has_ou = any("o/u" in h or "over" in h or "under" in h for h in headers)
            if not (has_referee or has_ou) and len(headers) < 3:
                continue

            tbody = table.find("tbody")
            rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) < 3:
                    continue

                ref_data = self._extract_referee_data(cells, headers)
                if ref_data and ref_data.get("referee_name"):
                    referees.append(ref_data)

        self.data = {
            "source": "covers",
            "season": self.opts.get("season"),
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "referee_count": len(referees),
            "referees": referees,
        }

        logger.info("Parsed stats for %d referees from Covers.com", len(referees))

    def _extract_referee_data(self, cells, headers: List[str]) -> Optional[Dict]:
        """Extract referee statistics from a table row."""
        try:
            cell_texts = [c.get_text(strip=True) for c in cells]

            # Find referee name (first non-numeric text)
            referee_name = ""
            for text in cell_texts:
                if text and not text.replace(".", "").replace("-", "").isdigit() and len(text) > 3:
                    referee_name = text
                    break

            if not referee_name:
                return None

            # Find O/U stats by column headers
            games = None
            over_record = None
            under_record = None
            over_pct = None

            for i, h in enumerate(headers):
                if i >= len(cell_texts):
                    break
                if "game" in h or "gp" in h:
                    games = self._try_int(cell_texts[i])
                elif "over" in h and "pct" not in h and "%" not in h:
                    over_record = cell_texts[i]
                elif "under" in h and "pct" not in h and "%" not in h:
                    under_record = cell_texts[i]
                elif "o/u" in h or ("over" in h and ("pct" in h or "%" in h)):
                    over_pct = self._try_float(cell_texts[i])

            # If no header match, try positional extraction
            if games is None and over_pct is None:
                for text in cell_texts[1:]:
                    val = self._try_float(text)
                    if val is not None:
                        if games is None and 10 <= (self._try_int(text) or 0) <= 100:
                            games = self._try_int(text)
                        elif over_pct is None and 30 <= (val or 0) <= 70:
                            over_pct = val

            return {
                "referee_name": referee_name,
                "games_officiated": games,
                "over_record": over_record,
                "under_record": under_record,
                "over_percentage": over_pct,
            }
        except Exception as e:
            logger.debug("Error parsing referee row: %s", e)
            return None

    def _try_float(self, text: str) -> Optional[float]:
        if not text:
            return None
        try:
            return float(text.replace("%", "").replace(",", "").strip())
        except (ValueError, TypeError):
            return None

    def _try_int(self, text: str) -> Optional[int]:
        if not text:
            return None
        try:
            return int(text.replace(",", "").strip())
        except (ValueError, TypeError):
            return None

    def get_scraper_stats(self) -> dict:
        return {
            "date": self.opts.get("date"),
            "season": self.opts.get("season"),
            "referee_count": self.data.get("referee_count", 0),
        }


create_app = convert_existing_flask_scraper(CoversRefereeStatsScraper)

if __name__ == "__main__":
    main = CoversRefereeStatsScraper.create_cli_and_flask_main()
    main()

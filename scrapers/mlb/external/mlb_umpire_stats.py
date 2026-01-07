"""
File: scrapers/mlb/external/mlb_umpire_stats.py

MLB Umpire Stats - UmpScorecards                                  v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Umpire accuracy and strike zone tendency data from UmpScorecards.

Data Source: https://umpscorecards.com/
- Historical data: 2015-present
- Per-umpire accuracy ratings
- Strike zone tendencies
- Run favor metrics

Key Metrics for K Predictions:
- accuracy: Overall call accuracy (higher = more consistent K zone)
- favor_home/away: Run favor by home plate position
- k_zone_size: Estimated strike zone size (larger = more Ks)
- consistency: How consistent the umpire's zone is

Usage:
  python scrapers/mlb/external/mlb_umpire_stats.py --debug
  python scrapers/mlb/external/mlb_umpire_stats.py --umpire_name "Angel Hernandez"

Note: This scraper fetches data from UmpScorecards website. Be respectful of
their servers and cache results where possible.
"""

from __future__ import annotations

import logging
import os
import sys
import re
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from ...scraper_base import DownloadType, ExportMode, ScraperBase
    from ...scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper

# Try to import BeautifulSoup for HTML parsing
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

logger = logging.getLogger(__name__)


class MlbUmpireStatsScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for MLB umpire statistics from UmpScorecards.

    Provides umpire-specific data that can affect K rates:
    - Some umpires have larger/smaller strike zones
    - Consistency affects pitcher confidence
    - Historical patterns can predict game K totals
    """

    scraper_name = "mlb_umpire_stats"
    required_params = []
    optional_params = {
        "season": None,        # Filter by season (e.g., 2025)
        "umpire_name": None,   # Filter by specific umpire
    }

    required_opts: List[str] = []
    download_type = DownloadType.HTML
    decode_download_data = True
    proxy_enabled: bool = False

    exporters = [
        {
            "type": "gcs",
            "key": "mlb-external/umpire-stats/%(season)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_umpire_stats_%(season)s_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts["date"] = datetime.now(timezone.utc).date().isoformat()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Default to current season
        if not self.opts.get("season"):
            now = datetime.now(timezone.utc)
            if now.month < 4:
                self.opts["season"] = str(now.year - 1)
            else:
                self.opts["season"] = str(now.year)

    _BASE_URL = "https://umpscorecards.com"

    def set_url(self) -> None:
        # Umpires list page
        self.url = f"{self._BASE_URL}/data/umpires"
        logger.debug("MLB Umpire Stats URL: %s", self.url)

    def set_headers(self) -> None:
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

    def validate_download_data(self) -> None:
        if not BS4_AVAILABLE:
            raise ImportError(
                "BeautifulSoup4 is required for UmpScorecards scraping. "
                "Install with: pip install beautifulsoup4"
            )
        if not self.download_data:
            raise ValueError("No data received from UmpScorecards")

    def transform_data(self) -> None:
        """Parse umpire stats from the HTML page."""
        soup = BeautifulSoup(self.download_data, "html.parser")

        umpires = []

        # Find the umpire data table
        # Note: UmpScorecards structure may change - this is a best-effort parse
        try:
            # Look for umpire entries
            umpire_cards = soup.find_all("div", class_=re.compile(r"umpire|card"))

            if not umpire_cards:
                # Try finding table rows
                rows = soup.find_all("tr")
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 3:
                        umpire_data = self._parse_table_row(cells)
                        if umpire_data:
                            umpires.append(umpire_data)
            else:
                for card in umpire_cards:
                    umpire_data = self._parse_umpire_card(card)
                    if umpire_data:
                        umpires.append(umpire_data)

        except Exception as e:
            logger.warning("Error parsing UmpScorecards HTML: %s", e)
            # Return empty but valid data structure
            umpires = []

        # Filter by umpire name if specified
        if self.opts.get("umpire_name"):
            name_filter = self.opts["umpire_name"].lower()
            umpires = [u for u in umpires if name_filter in u.get("name", "").lower()]

        # Calculate K-relevant metrics
        for ump in umpires:
            ump["k_zone_tendency"] = self._calculate_k_tendency(ump)

        # Sort by games (most experienced first)
        umpires_sorted = sorted(umpires, key=lambda x: x.get("games", 0), reverse=True)

        self.data = {
            "season": self.opts.get("season"),
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "umpscorecards.com",
            "umpireCount": len(umpires),
            "umpires": umpires_sorted,
            "highKUmpires": [u for u in umpires if u.get("k_zone_tendency") == "large"],
            "lowKUmpires": [u for u in umpires if u.get("k_zone_tendency") == "small"],
        }

        logger.info("Parsed %d umpires from UmpScorecards", len(umpires))

    def _parse_table_row(self, cells: List) -> Optional[Dict[str, Any]]:
        """Parse umpire data from a table row."""
        try:
            if len(cells) < 3:
                return None

            name = cells[0].get_text(strip=True)
            if not name or name.lower() in ["umpire", "name", ""]:
                return None

            return {
                "name": name,
                "games": self._safe_int(cells[1].get_text(strip=True)) if len(cells) > 1 else 0,
                "accuracy": self._safe_float(cells[2].get_text(strip=True)) if len(cells) > 2 else None,
                "consistency": self._safe_float(cells[3].get_text(strip=True)) if len(cells) > 3 else None,
                "favor": self._safe_float(cells[4].get_text(strip=True)) if len(cells) > 4 else None,
            }
        except Exception:
            return None

    def _parse_umpire_card(self, card) -> Optional[Dict[str, Any]]:
        """Parse umpire data from a card element."""
        try:
            name_elem = card.find(class_=re.compile(r"name|title"))
            name = name_elem.get_text(strip=True) if name_elem else None

            if not name:
                return None

            # Try to find stats
            stats = {}
            stat_elems = card.find_all(class_=re.compile(r"stat|value|number"))
            for elem in stat_elems:
                text = elem.get_text(strip=True)
                if "%" in text:
                    stats["accuracy"] = self._safe_float(text.replace("%", ""))

            return {
                "name": name,
                "games": stats.get("games", 0),
                "accuracy": stats.get("accuracy"),
                "consistency": stats.get("consistency"),
                "favor": stats.get("favor"),
            }
        except Exception:
            return None

    def _safe_int(self, value: str) -> int:
        """Safely convert string to int."""
        try:
            return int(re.sub(r"[^\d]", "", value))
        except (ValueError, TypeError):
            return 0

    def _safe_float(self, value: str) -> Optional[float]:
        """Safely convert string to float."""
        try:
            # Remove % and other non-numeric chars except . and -
            cleaned = re.sub(r"[^\d.\-]", "", value)
            return round(float(cleaned), 2)
        except (ValueError, TypeError):
            return None

    def _calculate_k_tendency(self, ump: Dict[str, Any]) -> str:
        """
        Calculate umpire's K zone tendency.

        Higher accuracy + larger zone = more Ks
        Lower accuracy + tight zone = fewer Ks
        """
        accuracy = ump.get("accuracy", 92)  # League average ~93%

        if accuracy is None:
            return "average"

        if accuracy >= 94:
            return "large"  # Consistent, larger zone = more Ks
        elif accuracy <= 91:
            return "small"  # Inconsistent, smaller zone = fewer Ks
        else:
            return "average"

    def get_scraper_stats(self) -> dict:
        return {
            "umpireCount": self.data.get("umpireCount", 0),
            "season": self.data.get("season"),
        }


create_app = convert_existing_flask_scraper(MlbUmpireStatsScraper)

if __name__ == "__main__":
    main = MlbUmpireStatsScraper.create_cli_and_flask_main()
    main()

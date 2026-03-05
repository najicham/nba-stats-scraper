# File: scrapers/external/vsin_betting_splits.py
"""
VSiN NBA Public Betting Splits Scraper                          v2.0 - 2026-03-04
----------------------------------------------------------------------------------
Scrapes public betting percentage data from VSiN (DraftKings-sourced).

URL: https://data.vsin.com/nba/betting-splits/
Data: Percentage of bets (tickets) and money (handle) on each side of game totals.
Access: Free, updates every 5 minutes, DraftKings-sourced data.
Timing: Available throughout the day, scrape ~2 PM ET for pre-game data.

v2.0: Data is server-side rendered at data.vsin.com — no Playwright needed.
      Rewrote parser to match actual freezetable HTML structure.

Usage:
  python scrapers/external/vsin_betting_splits.py --date 2026-03-04 --debug
"""

from __future__ import annotations

import logging
import os
import re
import sys
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

# Team name → tricode mapping
TEAM_MAP = {
    "atlanta": "ATL", "hawks": "ATL",
    "boston": "BOS", "celtics": "BOS",
    "brooklyn": "BKN", "nets": "BKN",
    "charlotte": "CHA", "hornets": "CHA",
    "chicago": "CHI", "bulls": "CHI",
    "cleveland": "CLE", "cavaliers": "CLE", "cavs": "CLE",
    "dallas": "DAL", "mavericks": "DAL", "mavs": "DAL",
    "denver": "DEN", "nuggets": "DEN",
    "detroit": "DET", "pistons": "DET",
    "golden state": "GSW", "warriors": "GSW",
    "houston": "HOU", "rockets": "HOU",
    "indiana": "IND", "pacers": "IND",
    "la clippers": "LAC", "clippers": "LAC",
    "la lakers": "LAL", "lakers": "LAL",
    "memphis": "MEM", "grizzlies": "MEM",
    "miami": "MIA", "heat": "MIA",
    "milwaukee": "MIL", "bucks": "MIL",
    "minnesota": "MIN", "timberwolves": "MIN", "wolves": "MIN",
    "new orleans": "NOP", "pelicans": "NOP",
    "new york": "NYK", "knicks": "NYK",
    "oklahoma city": "OKC", "thunder": "OKC",
    "orlando": "ORL", "magic": "ORL",
    "philadelphia": "PHI", "76ers": "PHI", "sixers": "PHI",
    "phoenix": "PHX", "suns": "PHX",
    "portland": "POR", "trail blazers": "POR", "blazers": "POR", "trailblazers": "POR",
    "sacramento": "SAC", "kings": "SAC",
    "san antonio": "SAS", "spurs": "SAS",
    "toronto": "TOR", "raptors": "TOR",
    "utah": "UTA", "jazz": "UTA",
    "washington": "WAS", "wizards": "WAS",
}


def resolve_team(name: str) -> str:
    """Convert team name variants to NBA tricode.

    Uses word-boundary matching to avoid false positives like
    'nets' matching inside 'hornets'.
    """
    lower = name.lower().strip()
    if lower in TEAM_MAP:
        return TEAM_MAP[lower]
    # Split into words and check each word individually
    words = lower.split()
    for word in words:
        if word in TEAM_MAP:
            return TEAM_MAP[word]
    # Check multi-word keys (e.g., "golden state", "la clippers")
    for key, tricode in TEAM_MAP.items():
        if ' ' in key and key in lower:
            return tricode
    return name.upper()[:3]


GCS_PATH_KEY = "vsin_betting_splits"


class VSiNBettingSplitsScraper(ScraperBase, ScraperFlaskMixin):
    """Scrape NBA public betting splits from VSiN (DraftKings-sourced)."""

    scraper_name = "vsin_betting_splits"
    required_params = ["date"]
    optional_params = {}
    required_opts: List[str] = ["date"]
    download_type = DownloadType.HTML
    decode_download_data: bool = True
    header_profile: str | None = None
    proxy_enabled: bool = True
    CRAWL_DELAY_SECONDS = 2.0

    VSIN_URL = "https://data.vsin.com/nba/betting-splits/"

    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/vsin_betting_splits_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_vsin_betting_splits_%(date)s.html",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    def set_url(self) -> None:
        """Set VSiN betting splits URL."""
        self.url = self.VSIN_URL
        logger.info("VSiN betting splits URL: %s", self.url)

    def transform_data(self) -> None:
        """Parse VSiN data.vsin.com server-rendered HTML for betting splits.

        HTML structure (freezetable layout):
        - Row 0: Title banner ("NBA Betting Splits")
        - Row 1: Column headers (Spread / Handle / Bets / Total / Handle / Bets / ML)
        - Row 2+: Data rows, each with cells:
            [0] Teams (txt-color-vsinred links: away, home)
            [1] Spread lines (DraftKings links: away, home)
            [2] Spread handle % (divs: away, home)
            [3] Spread bets % (divs: away, home)
            [4] Total line (divs/links: over, under — same number)
            [5] Total handle % (divs: over, under)
            [6] Total bets % (divs: over, under)
            [7] Moneyline (DraftKings links: away, home)
        """
        soup = BeautifulSoup(self.decoded_data, "html.parser")
        game_date = self.opts["date"]
        games = []

        table = soup.find("table")
        if not table:
            logger.warning("No table found on VSiN page")
            self.data = self._empty_result(game_date)
            return

        rows = table.find_all("tr")

        for row in rows[2:]:  # Skip header rows
            # Use recursive=False to get direct TD children only.
            # The freezetable layout has nested elements that inflate
            # find_all("td") from 10 real cells to 150+ nested elements.
            cells = row.find_all("td", recursive=False)
            if len(cells) < 8:
                continue

            game = self._parse_game_row(cells, game_date)
            if game:
                games.append(game)

        self.data = {
            "source": "vsin",
            "date": game_date,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "game_count": len(games),
            "games": games,
        }

        logger.info("VSiN: Scraped %d games with betting splits for %s", len(games), game_date)

        if games:
            try:
                notify_info(
                    title="VSiN Betting Splits Scraped",
                    message=f"Scraped {len(games)} games for {game_date}",
                    details={"game_count": len(games), "date": game_date},
                    processor_name=self.__class__.__name__
                )
            except Exception:
                pass
        else:
            try:
                notify_warning(
                    title="VSiN Betting Splits: No Data",
                    message=f"0 games found for {game_date}",
                    details={"date": game_date},
                    processor_name=self.__class__.__name__
                )
            except Exception:
                pass

    def _parse_game_row(self, cells, game_date: str) -> Optional[Dict]:
        """Parse a single data row into a game dict."""
        try:
            # Cell 0: Teams from txt-color-vsinred links (away first, home second)
            team_links = cells[0].find_all("a", class_="txt-color-vsinred")
            team_names = [a.get_text(strip=True) for a in team_links]
            if len(team_names) < 2:
                return None

            away_team = resolve_team(team_names[0])
            home_team = resolve_team(team_names[1])

            # Cell 1: Spread lines
            spread_links = cells[1].find_all("a")
            spreads = [a.get_text(strip=True) for a in spread_links]
            away_spread = _parse_number(spreads[0]) if len(spreads) > 0 else None
            home_spread = _parse_number(spreads[1]) if len(spreads) > 1 else None

            # Cell 2-3: Spread handle % and bets %
            spread_handle = _extract_pcts(cells[2])
            spread_bets = _extract_pcts(cells[3])

            # Cell 4: Total line
            total_line = None
            total_divs = cells[4].find_all("div", class_=re.compile(r"text-center"))
            for div in total_divs:
                val = _parse_number(div.get_text(strip=True))
                if val and val > 100:  # NBA totals are 200+
                    total_line = val
                    break
            if total_line is None:
                total_links = cells[4].find_all("a")
                for link in total_links:
                    val = _parse_number(link.get_text(strip=True))
                    if val and val > 100:
                        total_line = val
                        break

            # Cell 5-6: Total handle % and bets %
            total_handle = _extract_pcts(cells[5])
            total_bets = _extract_pcts(cells[6])

            # Cell 7: Moneyline
            ml_links = cells[7].find_all("a")
            moneylines = [a.get_text(strip=True) for a in ml_links]
            away_ml = _parse_number(moneylines[0]) if len(moneylines) > 0 else None
            home_ml = _parse_number(moneylines[1]) if len(moneylines) > 1 else None

            return {
                "away_team": away_team,
                "home_team": home_team,
                "game_date": game_date,
                # Spread
                "spread": away_spread,
                "away_spread_pct": spread_bets[0] if len(spread_bets) > 0 else None,
                "home_spread_pct": spread_bets[1] if len(spread_bets) > 1 else None,
                # Total — ticket_pct = bets %, money_pct = handle %
                # (matches Phase 2 processor field names)
                "total_line": total_line,
                "over_ticket_pct": total_bets[0] if len(total_bets) > 0 else None,
                "under_ticket_pct": total_bets[1] if len(total_bets) > 1 else None,
                "over_money_pct": total_handle[0] if len(total_handle) > 0 else None,
                "under_money_pct": total_handle[1] if len(total_handle) > 1 else None,
                # Moneyline (extra data, not in BQ yet)
                "away_moneyline": away_ml,
                "home_moneyline": home_ml,
            }

        except Exception as e:
            logger.debug("Error parsing VSiN row: %s", e)
            return None

    def _empty_result(self, game_date: str) -> Dict:
        return {
            "source": "vsin",
            "date": game_date,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "game_count": 0,
            "games": [],
        }


def _extract_pcts(cell) -> List[Optional[float]]:
    """Extract percentage values from div elements in a cell.

    Returns list of floats (e.g., [44.0, 56.0]) for away/over and home/under.
    """
    divs = cell.find_all("div", class_=re.compile(r"text-center"))
    values = []
    for div in divs:
        text = div.get_text(strip=True)
        if "%" in text:
            val = _parse_number(text.replace("%", ""))
            if val is not None:
                values.append(val)
    return values


def _parse_number(text: str) -> Optional[float]:
    """Parse a number from text, handling +/- signs and commas."""
    if not text:
        return None
    try:
        cleaned = text.strip().replace(",", "").replace("%", "")
        return float(cleaned)
    except (ValueError, TypeError):
        return None


# Flask integration
app = convert_existing_flask_scraper(VSiNBettingSplitsScraper)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="VSiN Betting Splits Scraper")
    parser.add_argument("--date", required=True, help="Game date (YYYY-MM-DD)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--local", action="store_true", help="Run locally with file export only")
    parser.add_argument("--serve", action="store_true", help="Start Flask server")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.serve:
        app.run(host="0.0.0.0", port=8080, debug=True)
    else:
        scraper = VSiNBettingSplitsScraper()
        groups = ["dev", "test"] if args.local else ["prod", "gcs"]
        scraper.run(
            opts={"date": args.date},
            groups=groups,
        )

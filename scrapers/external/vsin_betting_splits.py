# File: scrapers/external/vsin_betting_splits.py
"""
VSiN NBA Public Betting Splits Scraper                          v1.0 - 2026-03-04
----------------------------------------------------------------------------------
Scrapes public betting percentage data from VSiN (DraftKings-sourced).

URL: https://data.vsin.com/nba/betting-splits/
Data: Percentage of bets (tickets) and money (handle) on each side of game totals.
Access: Free, updates every 5 minutes, DraftKings-sourced data.
Timing: Available throughout the day, scrape ~2 PM ET for pre-game data.

When 80%+ of public bets are on OVER for a game total but the line hasn't moved up,
sharp money is likely on UNDER. This creates a sharp_money signal for player props.

Usage:
  python scrapers/external/vsin_betting_splits.py --date 2026-03-04 --debug
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

# Team name mappings for resolving VSiN team names to standard tricodes
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
    "portland": "POR", "trail blazers": "POR", "blazers": "POR",
    "sacramento": "SAC", "kings": "SAC",
    "san antonio": "SAS", "spurs": "SAS",
    "toronto": "TOR", "raptors": "TOR",
    "utah": "UTA", "jazz": "UTA",
    "washington": "WAS", "wizards": "WAS",
}


def resolve_team(name: str) -> str:
    """Convert team name variants to NBA tricode."""
    lower = name.lower().strip()
    if lower in TEAM_MAP:
        return TEAM_MAP[lower]
    for key, tricode in TEAM_MAP.items():
        if key in lower or lower in key:
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

    def download_and_decode(self):
        """Use Playwright to render VSiN WordPress page with AJAX-loaded data.

        VSiN loads betting splits via WordPress AJAX after page load — static
        HTML has empty container divs. We use headless Chromium to wait for
        the data to render, then extract the full DOM.
        """
        from scrapers.scraper_base import _PLAYWRIGHT_AVAILABLE, _STEALTH_FN

        if not _PLAYWRIGHT_AVAILABLE:
            raise ValueError(
                "Playwright not available — install with: playwright install chromium --with-deps"
            )

        from playwright.sync_api import sync_playwright

        logger.info("Launching Playwright for VSiN AJAX rendering...")
        time.sleep(self.CRAWL_DELAY_SECONDS)

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                page = browser.new_page()
                if callable(_STEALTH_FN):
                    _STEALTH_FN(page)

                page.goto(self.VSIN_URL, wait_until="networkidle", timeout=60_000)

                # Wait for AJAX data to populate tables/cards
                try:
                    page.wait_for_selector(
                        "table, [class*='split'], [class*='game'], [class*='matchup']",
                        timeout=15_000,
                    )
                    # Extra wait for AJAX data to fully populate
                    page.wait_for_timeout(3_000)
                except Exception:
                    logger.warning("No betting splits selector found, waiting extra time...")
                    page.wait_for_timeout(8_000)

                html = page.content()
                logger.info("Playwright rendered %d bytes of HTML from VSiN", len(html))
            finally:
                browser.close()

        self.decoded_data = html

    def transform_data(self) -> None:
        """Parse VSiN betting splits page and extract game-level public betting data."""
        soup = BeautifulSoup(self.decoded_data, "html.parser")

        games = []
        game_date = self.opts["date"]

        # Try to find the main data container
        # VSiN typically uses structured tables or card layouts
        tables = soup.find_all("table")

        # Also try to find embedded JSON data (common pattern on data sites)
        scripts = soup.find_all("script")
        embedded_data = None
        for script in scripts:
            script_text = script.get_text()
            if "bettingSplits" in script_text or "publicBetting" in script_text:
                # Try to extract JSON from script tag
                json_match = re.search(r'(?:bettingSplits|publicBetting|gameData)\s*[=:]\s*(\[.*?\]);',
                                       script_text, re.DOTALL)
                if json_match:
                    try:
                        embedded_data = json.loads(json_match.group(1))
                    except json.JSONDecodeError:
                        pass

        if embedded_data:
            games = self._parse_embedded_data(embedded_data, game_date)
        elif tables:
            games = self._parse_tables(tables, game_date)
        else:
            # Try card-based layouts
            cards = soup.find_all("div", class_=re.compile(r"game|matchup|split"))
            if cards:
                games = self._parse_cards(cards, game_date)

        if not games:
            logger.warning(f"No betting splits data found for {game_date}")
            try:
                notify_warning(
                    title="VSiN Betting Splits: No Data",
                    message=f"Could not find betting splits data for {game_date}",
                    details={"date": game_date, "tables_found": len(tables)},
                    processor_name=self.__class__.__name__
                )
            except Exception:
                pass

        self.data = {
            "source": "vsin",
            "date": game_date,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "game_count": len(games),
            "games": games,
        }

        logger.info(f"VSiN: Scraped {len(games)} games with betting splits for {game_date}")

    def _parse_embedded_data(self, data: list, game_date: str) -> List[Dict]:
        """Parse embedded JSON data from VSiN page."""
        games = []
        for item in data:
            away_team = resolve_team(item.get("awayTeam", item.get("away", "")))
            home_team = resolve_team(item.get("homeTeam", item.get("home", "")))

            game = {
                "away_team": away_team,
                "home_team": home_team,
                "game_date": game_date,
                "total_line": self._safe_float(item.get("total", item.get("totalLine"))),
                "over_ticket_pct": self._safe_float(item.get("overTicketPct", item.get("overPct"))),
                "under_ticket_pct": self._safe_float(item.get("underTicketPct", item.get("underPct"))),
                "over_money_pct": self._safe_float(item.get("overMoneyPct", item.get("overHandlePct"))),
                "under_money_pct": self._safe_float(item.get("underMoneyPct", item.get("underHandlePct"))),
                "spread": self._safe_float(item.get("spread")),
                "home_spread_pct": self._safe_float(item.get("homeSpreadPct")),
                "away_spread_pct": self._safe_float(item.get("awaySpreadPct")),
            }
            games.append(game)
        return games

    def _parse_tables(self, tables: list, game_date: str) -> List[Dict]:
        """Parse HTML tables for betting splits data."""
        games = []
        for table in tables:
            headers = []
            for th in table.find_all("th"):
                h = th.get_text(strip=True).lower()
                headers.append(h)

            # Skip tables that don't look like betting splits
            has_team = any(h in ("team", "matchup", "game") for h in headers)
            has_pct = any("%" in h or "pct" in h or "public" in h or "ticket" in h for h in headers)
            if not (has_team or has_pct) and len(headers) < 3:
                continue

            # Identify column positions
            over_pct_col = None
            under_pct_col = None
            total_col = None
            team_col = None
            over_money_col = None
            under_money_col = None

            for i, h in enumerate(headers):
                if "over" in h and ("%" in h or "pct" in h or "ticket" in h):
                    over_pct_col = i
                elif "under" in h and ("%" in h or "pct" in h or "ticket" in h):
                    under_pct_col = i
                elif "over" in h and ("money" in h or "handle" in h):
                    over_money_col = i
                elif "under" in h and ("money" in h or "handle" in h):
                    under_money_col = i
                elif h in ("total", "o/u", "game total"):
                    total_col = i
                elif h in ("team", "matchup", "game", "teams"):
                    team_col = i

            rows = table.find_all("tr")
            for row in rows[1:]:  # Skip header
                cells = row.find_all(["td", "th"])
                cell_texts = [c.get_text(strip=True) for c in cells]
                if len(cell_texts) < 3:
                    continue

                # Extract teams
                away_team = ""
                home_team = ""
                if team_col is not None and team_col < len(cell_texts):
                    team_text = cell_texts[team_col]
                    # Try to split teams: "LAL @ BOS" or "LAL vs BOS"
                    parts = re.split(r'\s*[@vs]+\s*', team_text, maxsplit=1)
                    if len(parts) == 2:
                        away_team = resolve_team(parts[0])
                        home_team = resolve_team(parts[1])

                game = {
                    "away_team": away_team,
                    "home_team": home_team,
                    "game_date": game_date,
                    "total_line": self._safe_float_from_cells(cell_texts, total_col),
                    "over_ticket_pct": self._safe_float_from_cells(cell_texts, over_pct_col),
                    "under_ticket_pct": self._safe_float_from_cells(cell_texts, under_pct_col),
                    "over_money_pct": self._safe_float_from_cells(cell_texts, over_money_col),
                    "under_money_pct": self._safe_float_from_cells(cell_texts, under_money_col),
                }

                if away_team or home_team:
                    games.append(game)

        return games

    def _parse_cards(self, cards: list, game_date: str) -> List[Dict]:
        """Parse card-style layout for betting splits."""
        games = []
        for card in cards:
            text = card.get_text(" ", strip=True)

            # Try to extract teams
            team_els = card.find_all(class_=re.compile(r"team|name"))
            teams = [resolve_team(el.get_text(strip=True)) for el in team_els]

            # Try to extract percentages
            pct_els = card.find_all(class_=re.compile(r"pct|percent|split"))
            pcts = []
            for el in pct_els:
                val = re.search(r'(\d+(?:\.\d+)?)\s*%?', el.get_text())
                if val:
                    pcts.append(float(val.group(1)))

            if len(teams) >= 2:
                game = {
                    "away_team": teams[0],
                    "home_team": teams[1],
                    "game_date": game_date,
                    "over_ticket_pct": pcts[0] if len(pcts) > 0 else None,
                    "under_ticket_pct": pcts[1] if len(pcts) > 1 else None,
                    "over_money_pct": pcts[2] if len(pcts) > 2 else None,
                    "under_money_pct": pcts[3] if len(pcts) > 3 else None,
                }
                games.append(game)

        return games

    def _safe_float(self, val) -> Optional[float]:
        """Safely convert value to float."""
        if val is None:
            return None
        try:
            if isinstance(val, str):
                val = val.replace("%", "").replace(",", "").strip()
            return float(val)
        except (ValueError, TypeError):
            return None

    def _safe_float_from_cells(self, cells: list, col: Optional[int]) -> Optional[float]:
        """Safely extract float from cell list by column index."""
        if col is None or col >= len(cells):
            return None
        return self._safe_float(cells[col])


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

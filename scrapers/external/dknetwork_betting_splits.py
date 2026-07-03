# File: scrapers/external/dknetwork_betting_splits.py
"""
DraftKings Network NBA Public Betting Splits Scraper           v1.0 - 2026-07-02
----------------------------------------------------------------------------------
Scrapes public betting percentage data from DraftKings Network — a free,
server-rendered replacement for the now-paywalled VSiN source.

URL: https://dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/
     ?tb_eg=42648&tb_edate=today&tb_emt=Total
Data: % of bets (tickets) and % of money (handle) on each side of game totals.
Access: FREE, no auth, no bot protection, DraftKings-sourced data.
Timing: Available throughout the day; scrape ~2 PM ET for pre-game data.

Query params (reverse-engineered 2026-07-02):
  tb_eg    Event group ID. NBA = 42648. (MLB 84240, WNBA 94682, NFL 88808, ...)
  tb_edate Date range: today | tomorrow | n7days | n30days
  tb_emt   Market type: Total | Spread | Moneyline | 0 (All, defaults to Moneyline)
           We use Total — game O/U splits are what the sharp_money signals consume.

HTML structure (fully server-rendered — no Playwright / no AJAX):
  div.tb-se                     one per game ("sportsbook event")
    .tb-se-title h5 a           matchup text ("DET Tigers @ TEX Rangers")
    .tb-se-title span           tip time ("7/2, 08:05PM")
    .tb-market-wrap             per-market block
      .tb-se-head div[0]        market name ("Total")
      .tb-sodd                  one per outcome (Over row, Under row)
        .tb-slipline            "Over 7.5" / "Under 7.5"
        .tb-odd-s               american odds ("+100" / "−120", Unicode minus)
        div (1st %)             % Handle (money)
        div (2nd %)             % Bets (tickets)

Output schema matches nba_raw.vsin_betting_splits so this is a drop-in source for
the same Phase 2 processor / signal wiring (sharp_money_over/under, public_fade_filter).

Usage:
  python scrapers/external/dknetwork_betting_splits.py --date 2026-07-02 --debug
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

# NBA event group ID in the DK Network betting-splits widget.
NBA_EVENT_GROUP = "42648"

# Team name → tricode mapping. DK Network prefixes matchups with a short code
# ("DET Tigers @ TEX Rangers" for MLB; NBA is expected to read like
# "LAL Lakers @ BOS Celtics"), so nickname matching is the reliable signal.
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
    """Convert a team name/matchup-half to an NBA tricode.

    Uses word matching so 'nets' does not match inside 'hornets'. Falls back to
    the uppercased first token (often already a tricode like 'LAL').
    """
    lower = name.lower().strip()
    if lower in TEAM_MAP:
        return TEAM_MAP[lower]
    words = lower.split()
    for word in words:
        if word in TEAM_MAP:
            return TEAM_MAP[word]
    for key, tricode in TEAM_MAP.items():
        if ' ' in key and key in lower:
            return tricode
    # DK prefixes a code as the first token — use it if it looks like a tricode.
    if words and words[0].isalpha() and len(words[0]) <= 3:
        return words[0].upper()
    return name.upper()[:3]


GCS_PATH_KEY = "dknetwork_betting_splits"


class DKNetworkBettingSplitsScraper(ScraperBase, ScraperFlaskMixin):
    """Scrape NBA public betting splits from DraftKings Network (free, DK-sourced)."""

    scraper_name = "dknetwork_betting_splits"
    required_params = ["date"]
    optional_params = {}
    required_opts: List[str] = ["date"]
    download_type = DownloadType.HTML
    decode_download_data: bool = True
    header_profile: str | None = None
    # DK Network is a public WordPress site with no bot protection — verified
    # working from a plain IP (1.5s fetch, no proxy). Kept False to save proxy
    # cost. FALLBACK: if the season-open smoke test returns 0 games or HTTP
    # errors (GCP egress IPs blocked), flip this to True.
    proxy_enabled: bool = False
    CRAWL_DELAY_SECONDS = 2.0

    BASE_URL = "https://dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/"

    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/dknetwork_betting_splits_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_dknetwork_betting_splits_%(date)s.html",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    def set_url(self) -> None:
        """Build the NBA Totals betting-splits URL for today's games."""
        self.url = (
            f"{self.BASE_URL}?tb_eg={NBA_EVENT_GROUP}"
            f"&tb_edate=today&tb_emt=Total"
        )
        logger.info("DK Network betting splits URL: %s", self.url)

    def transform_data(self) -> None:
        """Parse DK Network server-rendered HTML into per-game total splits."""
        soup = BeautifulSoup(self.decoded_data, "html.parser")
        game_date = self.opts["date"]

        events = soup.select("div.tb-se")
        games = []
        for ev in events:
            game = self._parse_event(ev, game_date)
            if game:
                games.append(game)

        self.data = {
            "source": "dknetwork",
            "date": game_date,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "game_count": len(games),
            "games": games,
        }

        logger.info(
            "DK Network: Scraped %d games with betting splits for %s",
            len(games), game_date,
        )

        try:
            if games:
                notify_info(
                    title="DK Network Betting Splits Scraped",
                    message=f"Scraped {len(games)} games for {game_date}",
                    details={"game_count": len(games), "date": game_date},
                    processor_name=self.__class__.__name__,
                )
            else:
                notify_warning(
                    title="DK Network Betting Splits: No Data",
                    message=f"0 games found for {game_date} (expected during off-season)",
                    details={"date": game_date},
                    processor_name=self.__class__.__name__,
                )
        except Exception:
            pass

    def _parse_event(self, ev, game_date: str) -> Optional[Dict]:
        """Parse a single tb-se event block into a game dict (total splits)."""
        try:
            title_el = ev.select_one(".tb-se-title h5 a")
            if not title_el:
                return None
            matchup = title_el.get_text(strip=True)
            if "@" not in matchup:
                return None
            away_raw, home_raw = matchup.split("@", 1)
            away_team = resolve_team(away_raw)
            home_team = resolve_team(home_raw)

            # DraftKings event id (stable game identifier, useful for dedup)
            dk_event_id = None
            href = title_el.get("href", "")
            m = re.search(r"/event/(\d+)", href)
            if m:
                dk_event_id = m.group(1)

            # Find the Total market block within this event.
            over_row = under_row = None
            for mw in ev.select(".tb-market-wrap"):
                head = mw.select_one(".tb-se-head div")
                if not head or head.get_text(strip=True).lower() != "total":
                    continue
                for sodd in mw.select(".tb-sodd"):
                    line_el = sodd.select_one(".tb-slipline")
                    label = line_el.get_text(strip=True).lower() if line_el else ""
                    if label.startswith("over"):
                        over_row = self._parse_outcome(sodd)
                    elif label.startswith("under"):
                        under_row = self._parse_outcome(sodd)
                break

            if not over_row and not under_row:
                return None

            total_line = (over_row or under_row or {}).get("line")

            return {
                "away_team": away_team,
                "home_team": home_team,
                "game_date": game_date,
                "dk_event_id": dk_event_id,
                "total_line": total_line,
                # ticket_pct = % Bets, money_pct = % Handle (VSiN-compatible names)
                "over_ticket_pct": (over_row or {}).get("bets_pct"),
                "under_ticket_pct": (under_row or {}).get("bets_pct"),
                "over_money_pct": (over_row or {}).get("handle_pct"),
                "under_money_pct": (under_row or {}).get("handle_pct"),
                "over_odds": (over_row or {}).get("odds"),
                "under_odds": (under_row or {}).get("odds"),
            }

        except Exception as e:
            logger.debug("Error parsing DK Network event: %s", e)
            return None

    @staticmethod
    def _parse_outcome(sodd) -> Dict:
        """Parse one Over/Under outcome row: line, odds, handle%, bets%."""
        line_el = sodd.select_one(".tb-slipline")
        odd_el = sodd.select_one(".tb-odd-s")

        line = None
        if line_el:
            m = re.search(r"([-+]?\d+(?:\.\d+)?)", line_el.get_text(strip=True))
            if m:
                line = float(m.group(1))

        odds = _parse_number(odd_el.get_text(strip=True)) if odd_el else None

        # The two direct-child percentage divs are ordered: Handle %, then Bets %.
        pcts = []
        for d in sodd.find_all("div", recursive=False):
            text = d.get_text(strip=True)
            m = re.match(r"(\d+(?:\.\d+)?)\s*%", text)
            if m:
                pcts.append(float(m.group(1)))
        return {
            "line": line,
            "odds": odds,
            "handle_pct": pcts[0] if len(pcts) > 0 else None,
            "bets_pct": pcts[1] if len(pcts) > 1 else None,
        }


def _parse_number(text: str) -> Optional[float]:
    """Parse a number from text, handling +/- signs, commas, and Unicode minus."""
    if not text:
        return None
    try:
        cleaned = (
            text.strip()
            .replace(",", "")
            .replace("%", "")
            .replace("−", "-")  # Unicode minus → ASCII hyphen
        )
        return float(cleaned)
    except (ValueError, TypeError):
        return None


# Flask integration
app = convert_existing_flask_scraper(DKNetworkBettingSplitsScraper)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="DK Network Betting Splits Scraper")
    parser.add_argument("--date", required=True, help="Game date (YYYY-MM-DD)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--local", action="store_true", help="Run locally with file export only")
    parser.add_argument("--serve", action="store_true", help="Start Flask server")

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    if args.serve:
        app.run(host="0.0.0.0", port=8080, debug=True)
    else:
        scraper = DKNetworkBettingSplitsScraper()
        opts = {"date": args.date}
        if args.local:
            opts["group"] = "dev"
        scraper.run(opts=opts)

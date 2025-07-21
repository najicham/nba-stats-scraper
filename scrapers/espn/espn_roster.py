"""
ESPN NBA Roster (HTML) scraper                         v2 - 2025-06-16
----------------------------------------------------------------------
Scrapes the public roster page, e.g.

    https://www.espn.com/nba/team/roster/_/name/bos/boston-celtics

Key upgrades
------------
- header_profile = "espn"  - UA managed in ScraperBase
- Strict ISO-8601 UTC timestamp
- Exporter groups now include prod
- Selector constants moved top-of-file for quick hot-patching
- Jersey number extraction falls back to regex if ESPN tweaks classnames
- Sentry warning only when *all three* of [name, slug, playerId] missing

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py espn_roster \
      --teamSlug boston-celtics --teamAbbr bos \
      --debug

  # Direct CLI execution:
  python scrapers/espn/espn_roster.py --teamSlug boston-celtics --teamAbbr bos --debug

  # Flask web service:
  python scrapers/espn/espn_roster.py --serve --debug
"""

from __future__ import annotations

import logging
import re
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List

import sentry_sdk
from bs4 import BeautifulSoup

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.espn.espn_roster
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
except ImportError:
    # Direct execution: python scrapers/espn/espn_roster.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper

logger = logging.getLogger("scraper_base")

# ------------------------------------------------------------------ #
# Tweak-point constants (ESPN sometimes A/B tests these class names)
# ------------------------------------------------------------------ #
ROW_SELECTOR = "tr.Table__TR"          # main roster rows
NAME_CELL_ANCHOR = "a[href*='/player/_/id/']"


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class GetEspnTeamRoster(ScraperBase, ScraperFlaskMixin):
    """
    Scrape roster from ESPN's HTML team page.
    """

    # Flask Mixin Configuration
    scraper_name = "espn_roster"
    required_params = ["teamSlug", "teamAbbr"]  # Both parameters are required
    optional_params = {}

    # Original scraper config
    required_opts: List[str] = ["teamSlug", "teamAbbr"]
    download_type: DownloadType = DownloadType.HTML
    decode_download_data: bool = True
    header_profile: str | None = "espn"

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": "espn/roster/%(teamAbbr)s_%(date)s_%(run_id)s.raw.html",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/espn_roster_%(teamAbbr)s_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        # ---------- raw HTML fixture (offline tests) ----------
        {
            "type": "file",
            # capture.py expects filenames that start with raw_
            "filename": "/tmp/raw_%(teamAbbr)s.html",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },

        # ---------- golden snapshot (parsed DATA) ----------
        {
            "type": "file",
            # capture.py expects filenames that start with exp_
            "filename": "/tmp/exp_%(teamAbbr)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts (date / season) helpers
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        now = datetime.now(timezone.utc)
        self.opts["date"] = now.strftime("%Y-%m-%d")
        self.opts["time"] = now.strftime("%H-%M-%S")
        season_start = now.year
        self.opts.setdefault("season", f"{season_start}-{(season_start+1)%100:02d}")

    # ------------------------------------------------------------------ #
    # URL
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        self.url = (
            f"https://www.espn.com/nba/team/roster/_/name/{self.opts['teamAbbr']}"
            f"/{self.opts['teamSlug']}"
        )
        logger.info("Resolved ESPN roster URL: %s", self.url)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, str) or "<html" not in self.decoded_data.lower():
            raise ValueError("Roster page did not return HTML.")

    # ------------------------------------------------------------------ #
    # Transform
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        soup = BeautifulSoup(self.decoded_data, "html.parser")
        rows = soup.select(ROW_SELECTOR)

        players: List[Dict[str, str]] = []
        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue

            anchor = tds[1].select_one(NAME_CELL_ANCHOR)
            if not anchor:
                continue

            full_href = anchor["href"]  # /nba/player/_/id/4397424/neemias-queta
            name = anchor.get_text(strip=True)

            # PlayerId & slug
            m = re.search(r"/id/(\d+)/(.*)$", full_href)
            player_id = m.group(1) if m else ""
            slug = m.group(2) if m else ""

            # Jersey number - class has changed before, so fallback to regex
            jersey_span = tds[1].find("span", class_=re.compile("pl"))
            jersey = (
                re.sub(r"[^\d]", "", jersey_span.get_text()) if jersey_span else ""
            )
            if not jersey:
                jersey = re.sub(r".*\s(\d+)$", r"\1", tds[1].get_text()).strip()

            position = tds[2].get_text(strip=True)
            age = tds[3].get_text(strip=True)
            height = tds[4].get_text(strip=True)
            weight = tds[5].get_text(strip=True)

            players.append(
                {
                    "number": jersey,
                    "name": name,
                    "playerId": player_id,
                    "slug": slug,
                    "fullUrl": (
                        f"https://www.espn.com{full_href}"
                        if full_href.startswith("/")
                        else full_href
                    ),
                    "position": position,
                    "age": age,
                    "height": height,
                    "weight": weight,
                }
            )

        # Basic schema-sanity warning
        for p in players:
            missing = [k for k in ("name", "slug", "playerId") if not p.get(k)]
            if len(missing) == 3:  # all missing -> definitely broken row
                logger.warning("ESPN roster: missing all ids for row %s", p)
                sentry_sdk.capture_message(f"[ESPN Roster] Unparsed row: {p}", level="warning")

        self.data = {
            "teamAbbr": self.opts["teamAbbr"],
            "teamSlug": self.opts["teamSlug"],
            "season": self.opts["season"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "playerCount": len(players),
            "players": players,
        }
        logger.info("Parsed %d players for %s", len(players), self.opts["teamAbbr"])

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "teamAbbr": self.opts["teamAbbr"],
            "playerCount": self.data.get("playerCount", 0),
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetEspnTeamRoster)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetEspnTeamRoster.create_cli_and_flask_main()
    main()
    
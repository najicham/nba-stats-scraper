"""
FILE: scrapers/espn/espn_roster.py
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
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/espn/espn_roster.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

# Notification system imports
try:
    from shared.utils.notification_system import (
        notify_error,
        notify_warning,
        notify_info
    )
except ImportError:
    # Fallback if notification system not available
    def notify_error(*args, **kwargs):
        pass
    def notify_warning(*args, **kwargs): pass  #
    ):
        pass
    def notify_info(*args, **kwargs): pass  #
    ):
        pass

# Pub/Sub imports for publishing completion messages (added after Jan 23 incident)
try:
    from google.cloud import pubsub_v1
    import json
    PUBSUB_AVAILABLE = True
except ImportError:
    PUBSUB_AVAILABLE = False
    pubsub_v1 = None

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
    GCS_PATH_KEY = "espn_team_roster"
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
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
        super().set_additional_opts()
        now = datetime.now(timezone.utc)
        self.opts["date"] = now.strftime("%Y-%m-%d")
        self.opts["time"] = now.strftime("%H-%M-%S")
        season_start = now.year
        self.opts.setdefault("season", f"{season_start}-{(season_start+1)%100:02d}")

        # Add snake_case versions for GCS path template compatibility
        self.opts["team_abbr"] = self.opts["teamAbbr"]
        self.opts["team_slug"] = self.opts["teamSlug"]

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
            error_msg = "Roster page did not return HTML."
            
            # Send error notification
            try:
                notify_error(
                    title="ESPN Roster: Invalid Response",
                    message=f"Roster page for {self.opts['teamAbbr']} did not return valid HTML",
                    details={
                        'scraper': 'espn_roster',
                        'team_abbr': self.opts['teamAbbr'],
                        'team_slug': self.opts['teamSlug'],
                        'error': error_msg,
                        'response_type': type(self.decoded_data).__name__ if self.decoded_data else 'None',
                        'response_length': len(self.decoded_data) if isinstance(self.decoded_data, str) else 0
                    },
                    processor_name="ESPN Roster Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise ValueError(error_msg)

    # ------------------------------------------------------------------ #
    # Transform
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        soup = BeautifulSoup(self.decoded_data, "html.parser")
        rows = soup.select(ROW_SELECTOR)

        # Warn if no roster rows found
        if not rows:
            try:
                notify_warning(
                    title="ESPN Roster: No Rows Found",
                    message=f"No roster rows found for {self.opts['teamAbbr']} using selector '{ROW_SELECTOR}'",
                    details={
                        'scraper': 'espn_roster',
                        'team_abbr': self.opts['teamAbbr'],
                        'team_slug': self.opts['teamSlug'],
                        'selector': ROW_SELECTOR,
                        'html_length': len(self.decoded_data)
                    },
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

        players: List[Dict[str, str]] = []
        unparsed_rows = []  # Track rows with all IDs missing
        
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

            player_data = {
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
            
            players.append(player_data)
            
            # Track completely unparsed rows
            missing = [k for k in ("name", "slug", "playerId") if not player_data.get(k)]
            if len(missing) == 3:  # all missing -> definitely broken row
                unparsed_rows.append(player_data)

        # Send notification about unparsed rows if any found
        if unparsed_rows:
            logger.warning("ESPN roster: %d rows missing all IDs", len(unparsed_rows))
            for p in unparsed_rows:
                sentry_sdk.capture_message(f"[ESPN Roster] Unparsed row: {p}", level="warning")
            
            try:
                notify_warning(
                    title="ESPN Roster: Unparsed Rows",
                    message=f"Found {len(unparsed_rows)} rows with missing player IDs for {self.opts['teamAbbr']}",
                    details={
                        'scraper': 'espn_roster',
                        'team_abbr': self.opts['teamAbbr'],
                        'team_slug': self.opts['teamSlug'],
                        'unparsed_count': len(unparsed_rows),
                        'total_rows': len(players),
                        'unparsed_rows': unparsed_rows[:5]  # Include first 5 for inspection
                    },
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

        self.data = {
            "teamAbbr": self.opts["teamAbbr"],
            "teamSlug": self.opts["teamSlug"],
            "season": self.opts["season"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "playerCount": len(players),
            "players": players,
        }
        logger.info("Parsed %d players for %s", len(players), self.opts["teamAbbr"])

        # Send success notification
        try:
            notify_info(
                title="ESPN Roster Scraped Successfully",
                message=f"Successfully scraped {len(players)} players for {self.opts['teamAbbr']}",
                details={
                    'scraper': 'espn_roster',
                    'team_abbr': self.opts['teamAbbr'],
                    'team_slug': self.opts['teamSlug'],
                    'season': self.opts['season'],
                    'player_count': len(players),
                    'unparsed_count': len(unparsed_rows)
                },
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "teamAbbr": self.opts["teamAbbr"],
            "playerCount": self.data.get("playerCount", 0),
        }

    # ------------------------------------------------------------------ #
    # Post-Export Hook - Publish to Pub/Sub (added after Jan 23 incident)
    # ------------------------------------------------------------------ #
    def post_export(self) -> None:
        """
        Called after successful export. Publishes completion message to Pub/Sub
        so Phase 2 processor can be triggered automatically.

        This was added after the Jan 23, 2026 incident where ESPN rosters were
        being scraped to GCS but the Phase 2 processor wasn't triggered,
        causing stale roster data in BigQuery.
        """
        # Call parent's post_export first
        super().post_export()

        # Publish completion message to Pub/Sub
        if not PUBSUB_AVAILABLE:
            logger.warning("Pub/Sub not available - skipping completion message")
            return

        try:
            project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
            topic_name = 'nba-phase1-scrapers-complete'

            publisher = pubsub_v1.PublisherClient()
            topic_path = publisher.topic_path(project_id, topic_name)

            message_data = {
                'scraper': 'espn_roster',
                'scraper_type': 'espn_team_roster',
                'team_abbr': self.opts.get('teamAbbr'),
                'team_slug': self.opts.get('teamSlug'),
                'date': self.opts.get('date'),
                'player_count': self.data.get('playerCount', 0),
                'gcs_path': f"espn/rosters/{self.opts.get('date')}/team_{self.opts.get('teamAbbr')}/",
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'run_id': self.run_id
            }

            future = publisher.publish(
                topic_path,
                json.dumps(message_data).encode('utf-8'),
                scraper='espn_roster',
                team_abbr=self.opts.get('teamAbbr', 'unknown')
            )
            message_id = future.result(timeout=10)
            logger.info(f"📤 Published completion message to {topic_name}: {message_id}")

        except Exception as e:
            # Log but don't fail the scraper - completion message is nice-to-have
            logger.warning(f"Failed to publish completion message: {e}")


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetEspnTeamRoster)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetEspnTeamRoster.create_cli_and_flask_main()
    main()
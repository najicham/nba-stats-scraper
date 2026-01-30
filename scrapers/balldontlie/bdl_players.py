"""
File: scrapers/balldontlie/bdl_players.py

BALLDONTLIE - Players endpoint                                 v2.0 2025-06-25
------------------------------------------------------------------------------
Fetch player rows from

    https://api.balldontlie.io/v1/players           (default)
    https://api.balldontlie.io/v1/players/active    (--active flag)

Supports every documented query parameter:

    cursor, per_page, search, first_name, last_name,
    team_ids[], player_ids[]

Examples
--------
# Entire catalogue (~4,500 rows)
python -m scrapers.balldontlie.bdl_players

# Active Celtics players, 50 per page
python -m scrapers.balldontlie.bdl_players --active \
       --teamIds 2 --perPage 50

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_players \
      --debug

  # Active Thunder players
  python tools/fixtures/capture.py bdl_players \
      --debug --active --teamIds 21

  # Name search
  python tools/fixtures/capture.py bdl_players \
      --debug --search james --perPage 50

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_players.py --active --teamIds 2 --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_players.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlencode

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_players
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_players.py
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
    # Graceful fallback if notification system not available
    def notify_warning(*args, **kwargs): pass  #
    def notify_info(*args, **kwargs): pass  #

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class BdlPlayersScraper(ScraperBase, ScraperFlaskMixin):
    """Scraper for /players and /players/active with full filter support."""

    # Flask Mixin Configuration
    scraper_name = "bdl_players"
    required_params = []  # No required parameters
    optional_params = {
        "active": None,       # boolean flag for /players/active
        "cursor": None,       # pagination cursor
        "perPage": 100,       # items per page (1-100, default 100)
        "search": None,       # free-text search
        "firstName": None,    # exact match on first name
        "lastName": None,     # exact match on last name
        "teamIds": None,      # comma list of team IDs
        "playerIds": None,    # comma list of player IDs
        "api_key": None,       # Falls back to env var
    }

    # Original scraper config
    download_type = DownloadType.JSON
    decode_download_data = True
    required_opts: List[str] = []
    proxy_enabled: bool = False

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "bdl_players"
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
            "filename": "/tmp/bdl_players_%(ident)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
        # capture artefacts
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "export_mode": ExportMode.DECODED,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Helpers for query params                                           #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _split(raw: str | None) -> List[str]:
        return [s.strip() for s in str(raw).split(",") if s.strip()] if raw else []

    @staticmethod
    def _qs(d: Dict[str, object]) -> str:
        """urlencode but keep [] for array parameters."""
        return urlencode(d, doseq=True, safe="[]")

    # ------------------------------------------------------------------ #
    # set_additional_opts                                                #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        # Default perPage = 100, cap at 100
        per_page = int(self.opts.get("perPage") or 100)
        self.opts["perPage"] = min(max(per_page, 1), 100)

        # Build ident for filenames / logs
        parts: List[str] = []
        if self.opts.get("active"):
            parts.append("active")
        if self.opts.get("playerIds"):
            parts.append(f"pids_{len(self._split(self.opts['playerIds']))}")
        if self.opts.get("teamIds"):
            parts.append(f"tids_{len(self._split(self.opts['teamIds']))}")
        if self.opts.get("search"):
            parts.append(f"search_{self.opts['search']}")
        if not parts:
            parts.append(datetime.now(timezone.utc).date().isoformat())

        self.opts["ident"] = "_".join(parts)

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/players"
    _API_ACTIVE = "https://api.balldontlie.io/v1/players/active"

    def _build_params(self, extra: Dict[str, object] | None = None) -> Dict[str, object]:
        q: Dict[str, object] = {"per_page": self.opts["perPage"]}

        simple_map = {
            "cursor": "cursor",
            "search": "search",
            "firstName": "first_name",
            "lastName": "last_name",
        }
        for opt_key, api_key in simple_map.items():
            if self.opts.get(opt_key):
                q[api_key] = self.opts[opt_key]

        # array params
        array_map = {
            "teamIds": "team_ids[]",
            "playerIds": "player_ids[]",
        }
        for opt_key, api_key in array_map.items():
            for val in self._split(self.opts.get(opt_key)):
                q.setdefault(api_key, []).append(val)

        if extra:
            q.update(extra)
        return q

    def set_url(self) -> None:
        self.base_url = self._API_ACTIVE if self.opts.get("active") else self._API_ROOT
        self.url = f"{self.base_url}?{self._qs(self._build_params())}"
        logger.debug("Players URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-players/2.0 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        try:
            if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
                raise ValueError("Players response malformed: missing 'data' key")
        except Exception as e:
            # Send error notification for validation failure
            try:
                notify_error(
                    title="BDL Players - Validation Failed",
                    message=f"Data validation failed for {self.opts.get('ident', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_players',
                        'ident': self.opts.get('ident'),
                        'active_only': bool(self.opts.get('active')),
                        'error_type': type(e).__name__,
                        'url': self.url,
                        'has_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Players"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send validation error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Transform (cursor walk)                                            #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        try:
            players: List[Dict[str, object]] = list(self.decoded_data["data"])
            cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")
            pages_fetched = 1

            # Paginate through all results
            while cursor:
                try:
                    resp = self.http_downloader.get(
                        self.base_url,
                        headers=self.headers,
                        params=self._build_params({"cursor": cursor}),
                        timeout=self.timeout_http,
                    )
                    resp.raise_for_status()
                    js = resp.json()
                    players.extend(js.get("data", []))
                    cursor = js.get("meta", {}).get("next_cursor")
                    pages_fetched += 1
                except Exception as e:
                    # Pagination failure
                    try:
                        notify_error(
                            title="BDL Players - Pagination Failed",
                            message=f"Failed to fetch page {pages_fetched + 1} for {self.opts.get('ident', 'unknown')}: {str(e)}",
                            details={
                                'scraper': 'bdl_players',
                                'ident': self.opts.get('ident'),
                                'active_only': bool(self.opts.get('active')),
                                'pages_fetched': pages_fetched,
                                'players_so_far': len(players),
                                'error_type': type(e).__name__,
                                'cursor': cursor
                            },
                            processor_name="Ball Don't Lie Players"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send pagination error notification: {notify_ex}")
                    raise

            players.sort(key=lambda p: p.get("id", 0))

            self.data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "playerCount": len(players),
                "players": players,
            }
            
            logger.info("Fetched %d players (%s) across %d pages", 
                       len(players), self.opts["ident"], pages_fetched)

            # Success notification
            try:
                notify_info(
                    title="BDL Players - Success",
                    message=f"Successfully scraped {len(players)} players ({self.opts.get('ident', 'unknown')})",
                    details={
                        'scraper': 'bdl_players',
                        'ident': self.opts.get('ident'),
                        'active_only': bool(self.opts.get('active')),
                        'player_count': len(players),
                        'pages_fetched': pages_fetched
                    },
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send success notification: {notify_ex}")

        except Exception as e:
            # General transformation error
            try:
                notify_error(
                    title="BDL Players - Transform Failed",
                    message=f"Data transformation failed for {self.opts.get('ident', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_players',
                        'ident': self.opts.get('ident'),
                        'active_only': bool(self.opts.get('active')),
                        'error_type': type(e).__name__,
                        'has_decoded_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Players"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send transform error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> Dict[str, object]:
        return {"playerCount": self.data.get("playerCount", 0), "ident": self.opts["ident"]}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlPlayersScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlPlayersScraper.create_cli_and_flask_main()
    main()
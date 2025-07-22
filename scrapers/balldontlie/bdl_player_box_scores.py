"""
BALLDONTLIE - Player Box Scores (stats endpoint)           v1.3 (2025-06-24)
------------------------------------------------------------------------------
Collect per-player box-score rows from

    https://api.balldontlie.io/v1/stats

Supported query parameters (full parity with BDL docs)
------------------------------------------------------
--startDate / --endDate    inclusive YYYY-MM-DD window
--gameIds                  comma list   e.g. 486435,486436
--playerIds                comma list
--teamIds                  comma list
--seasons                  comma list (season start years)
--postSeason               flag (playoff games only)
--perPage                  1-100 (default 100)

If any ID/season filter is supplied we make a single request.
Otherwise we iterate date-by-date across the window.

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_player_box_scores \
      --startDate 2025-01-15 --endDate 2025-01-16 \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_player_box_scores.py --playerIds 237,115 --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_player_box_scores.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_player_box_scores
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_player_box_scores.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

logger = logging.getLogger("scraper_base")

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _coerce_date(val: str | date | None, default: date) -> date:
    if val is None:
        return default
    if isinstance(val, date):
        return val
    return datetime.strptime(str(val), "%Y-%m-%d").date()


def _split(raw: str | None) -> List[str]:
    return [p.strip() for p in str(raw).split(",") if p.strip()] if raw else []


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class BdlPlayerBoxScoresScraper(ScraperBase, ScraperFlaskMixin):
    """Cursor scraper for /stats, returns player box-score rows."""

    # Flask Mixin Configuration
    scraper_name = "bdl_player_box_scores"
    required_params = []  # No required parameters
    optional_params = {
        "startDate": None,   # Defaults to yesterday
        "endDate": None,     # Defaults to tomorrow
        "gameIds": None,     # comma list
        "playerIds": None,   # comma list
        "teamIds": None,     # comma list
        "seasons": None,     # comma list (season start years)
        "postSeason": None,  # boolean flag
        "perPage": 100,      # 1-100 (default 100)
        "apiKey": None,      # Falls back to env var
    }

    # Original scraper config
    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "bdl_player_box_scores"
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/bdl_player_box_scores_%(startDate)s_%(endDate)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
        # capture artefacts (raw + decoded) keyed by run_id
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
    # Additional opts                                                    #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        today = datetime.now(timezone.utc).date()
        self.opts["startDate"] = _coerce_date(
            self.opts.get("startDate"), today - timedelta(days=1)
        ).isoformat()
        self.opts["endDate"] = _coerce_date(
            self.opts.get("endDate"), today + timedelta(days=1)
        ).isoformat()

        for key in ("gameIds", "playerIds", "teamIds", "seasons"):
            self.opts[key] = self.opts.get(key, "")

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/stats"

    def _build_query(self, extra: dict | None = None) -> Dict[str, Any]:
        q: Dict[str, Any] = {"per_page": int(self.opts.get("perPage") or 100)}

        mapping = {
            "gameIds": "game_ids[]",
            "playerIds": "player_ids[]",
            "teamIds": "team_ids[]",
            "seasons": "seasons[]",
        }
        for opt_key, api_key in mapping.items():
            for val in _split(self.opts.get(opt_key)):
                q.setdefault(api_key, []).append(val)

        if self.opts.get("postSeason"):
            q["postseason"] = "true"

        if extra:
            q.update(extra)
        return q

    @staticmethod
    def _qs(params: Dict[str, Any]) -> str:
        """urlencode but keep [] unescaped (doseq handles lists)."""
        return urlencode(params, doseq=True, safe="[]")

    def set_url(self) -> None:
        filter_fields = (
            "gameIds",
            "playerIds",
            "teamIds",
            "seasons",
            "postSeason",
        )
        self.base_url = self._API_ROOT

        # Filter mode
        if any(self.opts.get(f) for f in filter_fields):
            self.url = f"{self.base_url}?{self._qs(self._build_query())}"
            self._date_iter = iter([])  # skip date loop
            logger.info("Player box-scores URL with filters: %s", self.url)
            return

        # Date-window mode
        self._date_iter = self._build_date_iter()
        first_date = next(self._date_iter)
        self.url = f"{self.base_url}?{self._qs(self._build_query({'dates[]': first_date}))}"
        logger.info("Player box-scores URL (date mode first page): %s", self.url)

    def _build_date_iter(self):
        start = datetime.strptime(self.opts["startDate"], "%Y-%m-%d").date()
        end = datetime.strptime(self.opts["endDate"], "%Y-%m-%d").date()
        d = start
        while d <= end:
            yield d.isoformat()
            d += timedelta(days=1)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-player-box-scores/1.3",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Stats response malformed: missing 'data' key")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        rows: List[Dict[str, Any]] = []
        dates_done: List[str] = []

        def add_page(js: Dict[str, Any]) -> Optional[str]:
            rows.extend(js.get("data", []))
            return js.get("meta", {}).get("next_cursor")

        # first response
        next_cursor = add_page(self.decoded_data)
        date_param = (
            self.decoded_data.get("meta", {}).get("request_params", {}).get("dates[]")
        )
        if date_param:
            dates_done.append(date_param)

        while next_cursor:
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params=self._build_query({"cursor": next_cursor}),
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            next_cursor = add_page(resp.json())

        for dt in self._date_iter:
            dates_done.append(dt)
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params=self._build_query({"dates[]": dt}),
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            next_cursor = add_page(resp.json())

            while next_cursor:
                resp = self.http_downloader.get(
                    self.base_url,
                    headers=self.headers,
                    params=self._build_query({"cursor": next_cursor}),
                    timeout=self.timeout_http,
                )
                resp.raise_for_status()
                next_cursor = add_page(resp.json())

        rows.sort(key=lambda r: (r.get("game", {}).get("id"), r.get("player_id")))

        self.data = {
            "startDate": self.opts["startDate"],
            "endDate": self.opts["endDate"],
            "datesProcessed": dates_done,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rowCount": len(rows),
            "stats": rows,
        }
        logger.info(
            "Fetched %d player box-score rows across %d dates (%s -> %s)",
            len(rows),
            len(dates_done),
            self.opts["startDate"],
            self.opts["endDate"],
        )

    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0),
            "startDate": self.opts["startDate"],
            "endDate": self.opts["endDate"],
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlPlayerBoxScoresScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlPlayerBoxScoresScraper.create_cli_and_flask_main()
    main()
    
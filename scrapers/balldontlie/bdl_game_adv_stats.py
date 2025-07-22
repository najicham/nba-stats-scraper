"""
BALLDONTLIE - Game Advanced Stats endpoint                 v2.0 (2025-06-25)
------------------------------------------------------------------------------
Per-player advanced box-score rows from

    https://api.balldontlie.io/v1/stats/advanced

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_game_adv_stats \
      --startDate 2025-06-22 --endDate 2025-06-22 \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_game_adv_stats.py --startDate 2025-06-22 --endDate 2025-06-22 --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_game_adv_stats.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
import json
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import urlencode

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_game_adv_stats
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import (
        NoHttpStatusCodeException,
        InvalidHttpStatusCodeException,
    )
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_game_adv_stats.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import (
        NoHttpStatusCodeException,
        InvalidHttpStatusCodeException,
    )
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helper                                                                      #
# --------------------------------------------------------------------------- #
def _split(raw: str | None) -> List[str]:
    return [s.strip() for s in str(raw).split(",") if s.strip()] if raw else []


def _coerce_date(val: str | date | None, default: date) -> date:
    if val is None:
        return default
    if isinstance(val, date):
        return val
    return datetime.strptime(str(val), "%Y-%m-%d").date()


def _qs(d: Dict[str, object]) -> str:
    """urlencode but preserve [] for array params."""
    return urlencode(d, doseq=True, safe="[]")


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class BdlGameAdvStatsScraper(ScraperBase, ScraperFlaskMixin):
    """Scraper for /stats/advanced with full filter support."""

    # Flask Mixin Configuration
    scraper_name = "bdl_game_adv_stats"
    required_params = []  # No required parameters
    optional_params = {
        "cursor": None,
        "perPage": 100,
        "playerIds": None,  # comma separated
        "gameIds": None,    # comma separated
        "dates": None,      # comma separated
        "seasons": None,    # comma separated
        "postSeason": None, # boolean flag
        "startDate": None,  # defaults to yesterday
        "endDate": None,    # defaults to tomorrow
        "apiKey": None,     # Falls back to env var
    }

    # Original scraper config
    download_type = DownloadType.JSON
    decode_download_data = True
    required_opts: List[str] = []

    # HTTP retry / error handling --------------------------------------
    no_retry_status_codes = ScraperBase.no_retry_status_codes + [401, 403, 429, 503]

    def get_retry_strategy(self):
        from urllib3.util.retry import Retry

        return Retry(
            total=self.max_retries_http,
            status_forcelist=[429, 500, 502, 504],  # 503 excluded
            allowed_methods=["GET"],
            backoff_factor=3,
        )

    def check_download_status(self):
        code = getattr(self.raw_response, "status_code", None)
        if code is None:
            raise NoHttpStatusCodeException("No status_code on response")

        if code in {400, 401, 403, 429, 503}:
            detail = ""
            if self.raw_response.content:
                try:
                    detail = self.raw_response.json().get("message", "")
                except (ValueError, json.JSONDecodeError):
                    detail = self.raw_response.text[:200].strip()
            raise InvalidHttpStatusCodeException(
                f"{code} {self.raw_response.reason} - {detail or 'see docs'}"
            )
        super().check_download_status()

    # ------------------------------------------------------------------ #
    # Exporters                                                          #
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "bdl_game_adv_stats"
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
            "filename": "/tmp/bdl_game_adv_stats_%(ident)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
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

        # perPage default / clamp
        per_page = int(self.opts.get("perPage") or 100)
        self.opts["perPage"] = min(max(per_page, 1), 100)

        # ident for filenames
        parts: List[str] = []
        if self.opts.get("playerIds"):
            parts.append(f"p{len(_split(self.opts['playerIds']))}")
        if self.opts.get("gameIds"):
            parts.append(f"g{len(_split(self.opts['gameIds']))}")
        if self.opts.get("dates"):
            parts.append(f"d{len(_split(self.opts['dates']))}")
        if self.opts.get("seasons"):
            parts.append(f"s{len(_split(self.opts['seasons']))}")
        if self.opts.get("postSeason"):
            parts.append("post")
        if not parts:
            parts.append(f"{self.opts['startDate']}_{self.opts['endDate']}")
        self.opts["ident"] = "_".join(parts)

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/stats/advanced"

    def _build_params(self, extra: Dict[str, object] | None = None) -> Dict[str, object]:
        q: Dict[str, object] = {"per_page": self.opts["perPage"]}

        simple_map = {
            "cursor": "cursor",
            "startDate": "start_date",
            "endDate": "end_date",
        }
        for opt_key, api_key in simple_map.items():
            if self.opts.get(opt_key):
                q[api_key] = self.opts[opt_key]

        array_map = {
            "playerIds": "player_ids[]",
            "gameIds": "game_ids[]",
            "dates": "dates[]",
            "seasons": "seasons[]",
        }
        for opt_key, api_key in array_map.items():
            for val in _split(self.opts.get(opt_key)):
                q.setdefault(api_key, []).append(val)

        if self.opts.get("postSeason"):
            q["postseason"] = "true"

        if extra:
            q.update(extra)
        return q

    def set_url(self) -> None:
        filter_flags = (
            "playerIds",
            "gameIds",
            "dates",
            "seasons",
            "postSeason",
            "cursor",
            "startDate",
            "endDate",
        )

        self.base_url = self._API_ROOT

        # If any explicit filter is given (other than the default start/end)
        # we issue a single request and rely on cursor pagination.
        has_explicit_filter = any(
            self.opts.get(f) for f in filter_flags if f not in {"startDate", "endDate"}
        )

        if has_explicit_filter:
            self._date_iter = iter([])  # no date loop
            self.url = f"{self.base_url}?{_qs(self._build_params())}"
            logger.debug("Adv-stats URL (filters): %s", self.url)
            return

        # Window mode: iterate startDate -> endDate day by day
        self._date_iter = self._gen_dates()
        first_date = next(self._date_iter)
        self.url = f"{self.base_url}?{_qs(self._build_params({'dates[]': first_date}))}"
        logger.debug("Adv-stats URL (date mode first page): %s", self.url)

    def _gen_dates(self):
        start = datetime.strptime(self.opts["startDate"], "%Y-%m-%d").date()
        end = datetime.strptime(self.opts["endDate"], "%Y-%m-%d").date()
        d = start
        while d <= end:
            yield d.isoformat()
            d += timedelta(days=1)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-game-adv-stats/2.0",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Advanced-stats response malformed: missing 'data' key")

    # ------------------------------------------------------------------ #
    # Transform (cursor walk, optional date loop)                        #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        rows: List[Dict[str, object]] = []
        seen_dates: List[str] = []

        def add_page(js: Dict[str, object]) -> Optional[str]:
            rows.extend(js.get("data", []))
            return js.get("meta", {}).get("next_cursor")

        # first response
        next_cursor = add_page(self.decoded_data)
        date_in_meta = (
            self.decoded_data.get("meta", {}).get("request_params", {}).get("dates[]")
        )
        if isinstance(date_in_meta, str):
            seen_dates.append(date_in_meta)

        # cursor pagination
        while next_cursor:
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params=self._build_params({"cursor": next_cursor}),
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            next_cursor = add_page(resp.json())

        # additional dates (window mode only)
        for dt in self._date_iter:
            seen_dates.append(dt)
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params=self._build_params({"dates[]": dt}),
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            next_cursor = add_page(resp.json())

            while next_cursor:
                resp = self.http_downloader.get(
                    self.base_url,
                    headers=self.headers,
                    params=self._build_params({"cursor": next_cursor}),
                    timeout=self.timeout_http,
                )
                resp.raise_for_status()
                next_cursor = add_page(resp.json())

        rows.sort(key=lambda r: (r.get("game", {}).get("id"), r.get("player_id")))

        self.data = {
            "ident": self.opts["ident"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rowCount": len(rows),
            "advancedStats": rows,
        }
        logger.info("Fetched %d advanced-stat rows (%s)", len(rows), self.opts["ident"])

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> Dict[str, object]:
        return {"rowCount": self.data.get("rowCount", 0), "ident": self.opts["ident"]}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlGameAdvStatsScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlGameAdvStatsScraper.create_cli_and_flask_main()
    main()
    
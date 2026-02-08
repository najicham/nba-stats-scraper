"""
File: scrapers/balldontlie/bdl_player_box_scores.py

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

# BDL availability logging (for tracking per-game data availability)
try:
    from shared.utils.bdl_availability_logger import log_bdl_game_availability
    BDL_AVAILABILITY_LOGGING_ENABLED = True
except ImportError:
    BDL_AVAILABILITY_LOGGING_ENABLED = False

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
        "api_key": None,      # Falls back to env var
    }

    # Original scraper config
    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "bdl_player_box_scores"
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
        first_date = next(self._date_iter, None)
        if first_date is None:
            raise ValueError("No dates available for box scores date range")
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
        api_key = self.opts.get("api_key") or os.getenv("BDL_API_KEY")
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
        try:
            if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
                raise ValueError("Stats response malformed: missing 'data' key")
        except Exception as e:
            # Send error notification for validation failure
            try:
                notify_error(
                    title="BDL Player Box Scores - Validation Failed",
                    message=f"Data validation failed for {self.opts.get('startDate')} to {self.opts.get('endDate')}: {str(e)}",
                    details={
                        'scraper': 'bdl_player_box_scores',
                        'start_date': self.opts.get('startDate'),
                        'end_date': self.opts.get('endDate'),
                        'error_type': type(e).__name__,
                        'url': self.url,
                        'has_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Player Box Scores"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send validation error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        try:
            rows: List[Dict[str, Any]] = []
            dates_done: List[str] = []
            pages_fetched = 1

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

            # cursor pagination
            while next_cursor:
                try:
                    resp = self.http_downloader.get(
                        self.base_url,
                        headers=self.headers,
                        params=self._build_query({"cursor": next_cursor}),
                        timeout=self.timeout_http,
                    )
                    resp.raise_for_status()
                    next_cursor = add_page(resp.json())
                    pages_fetched += 1
                except Exception as e:
                    # Pagination failure
                    try:
                        notify_error(
                            title="BDL Player Box Scores - Pagination Failed",
                            message=f"Failed to fetch page {pages_fetched + 1}: {str(e)}",
                            details={
                                'scraper': 'bdl_player_box_scores',
                                'start_date': self.opts.get('startDate'),
                                'end_date': self.opts.get('endDate'),
                                'pages_fetched': pages_fetched,
                                'rows_so_far': len(rows),
                                'error_type': type(e).__name__
                            },
                            processor_name="Ball Don't Lie Player Box Scores"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send pagination error notification: {notify_ex}")
                    raise

            # additional dates (window mode only)
            for dt in self._date_iter:
                dates_done.append(dt)
                try:
                    resp = self.http_downloader.get(
                        self.base_url,
                        headers=self.headers,
                        params=self._build_query({"dates[]": dt}),
                        timeout=self.timeout_http,
                    )
                    resp.raise_for_status()
                    next_cursor = add_page(resp.json())
                    pages_fetched += 1
                except Exception as e:
                    # Date fetch failure
                    try:
                        notify_error(
                            title="BDL Player Box Scores - Date Fetch Failed",
                            message=f"Failed to fetch data for date {dt}: {str(e)}",
                            details={
                                'scraper': 'bdl_player_box_scores',
                                'date': dt,
                                'dates_fetched': len(dates_done) - 1,
                                'rows_so_far': len(rows),
                                'error_type': type(e).__name__
                            },
                            processor_name="Ball Don't Lie Player Box Scores"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send date fetch error notification: {notify_ex}")
                    raise

                while next_cursor:
                    try:
                        resp = self.http_downloader.get(
                            self.base_url,
                            headers=self.headers,
                            params=self._build_query({"cursor": next_cursor}),
                            timeout=self.timeout_http,
                        )
                        resp.raise_for_status()
                        next_cursor = add_page(resp.json())
                        pages_fetched += 1
                    except Exception as e:
                        # Date pagination failure
                        try:
                            notify_error(
                                title="BDL Player Box Scores - Date Pagination Failed",
                                message=f"Failed to fetch page for date {dt}: {str(e)}",
                                details={
                                    'scraper': 'bdl_player_box_scores',
                                    'date': dt,
                                    'pages_fetched': pages_fetched,
                                    'rows_so_far': len(rows),
                                    'error_type': type(e).__name__
                                },
                                processor_name="Ball Don't Lie Player Box Scores"
                            )
                        except Exception as notify_ex:
                            logger.warning(f"Failed to send date pagination error notification: {notify_ex}")
                        raise

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
                "Fetched %d player box-score rows across %d dates (%s -> %s, %d pages)",
                len(rows),
                len(dates_done),
                self.opts["startDate"],
                self.opts["endDate"],
                pages_fetched
            )

            # Success notification
            try:
                notify_info(
                    title="BDL Player Box Scores - Success",
                    message=f"Successfully scraped {len(rows)} player box score rows ({self.opts.get('startDate')} to {self.opts.get('endDate')})",
                    details={
                        'scraper': 'bdl_player_box_scores',
                        'start_date': self.opts.get('startDate'),
                        'end_date': self.opts.get('endDate'),
                        'row_count': len(rows),
                        'dates_processed': len(dates_done),
                        'pages_fetched': pages_fetched
                    },
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send success notification: {notify_ex}")

            # Log BDL game availability for tracking per-game data availability
            # This enables answering: "When did BDL first return data for game X?"
            if BDL_AVAILABILITY_LOGGING_ENABLED:
                for game_date in dates_done:
                    try:
                        availability_records = log_bdl_game_availability(
                            game_date=game_date,
                            execution_id=self.run_id,
                            box_scores=rows,
                            workflow=self.opts.get("workflow")
                        )
                        # Log missing games as warnings
                        missing_games = [r for r in availability_records if not r.was_available]
                        if missing_games:
                            missing_str = ", ".join([f"{r.away_team}@{r.home_team}" for r in missing_games])
                            logger.warning(f"BDL API missing {len(missing_games)} games for {game_date}: {missing_str}")
                    except Exception as avail_ex:
                        logger.warning(f"Failed to log BDL availability for {game_date}: {avail_ex}")

        except Exception as e:
            # General transformation error
            try:
                notify_error(
                    title="BDL Player Box Scores - Transform Failed",
                    message=f"Data transformation failed for {self.opts.get('startDate')} to {self.opts.get('endDate')}: {str(e)}",
                    details={
                        'scraper': 'bdl_player_box_scores',
                        'start_date': self.opts.get('startDate'),
                        'end_date': self.opts.get('endDate'),
                        'error_type': type(e).__name__,
                        'has_decoded_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Player Box Scores"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send transform error notification: {notify_ex}")
            raise

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
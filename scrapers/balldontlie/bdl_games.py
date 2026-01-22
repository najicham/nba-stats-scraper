"""
File: scrapers/balldontlie/bdl_games.py

BALLDONTLIE - Games endpoint                                  v1.2 - 2025-06-24
-------------------------------------------------------------------------------
Fetches every NBA game between **startDate** and **endDate** (inclusive).

    /games?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD

The endpoint is cursor-paginated.  We grab the first page through
ScraperBase's normal downloader, then—inside **transform_data()**—walk any
`next_cursor` links with the **same requests.Session** (self.http_downloader)
so we inherit proxy / retry / header behaviour.

Typical page size is <= 15 games, so extra pages are rare today but the loop is
future-proof.

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_games \
      --startDate 2025-01-15 --endDate 2025-01-16 \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_games.py --startDate 2025-01-15 --endDate 2025-01-16 --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_games.py --serve --debug
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import sys
from typing import Any, Dict, List, Optional

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_games
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_games.py
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
    def notify_error(*args, **kwargs): pass
    def notify_warning(*args, **kwargs): pass
    def notify_info(*args, **kwargs): pass

# Rate limit handler import
try:
    from shared.utils.rate_limit_handler import get_rate_limit_handler
except ImportError:
    # Fallback if rate limit handler not available
    get_rate_limit_handler = None

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Small helper - date coercion                                                #
# --------------------------------------------------------------------------- #
def _coerce_date(val: str | _dt.date | None, default: _dt.date) -> _dt.date:
    if val is None:
        return default
    if isinstance(val, _dt.date):
        return val
    return _dt.datetime.strptime(str(val), "%Y-%m-%d").date()


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class BdlGamesScraper(ScraperBase, ScraperFlaskMixin):
    """Fetch game rows, follow cursor pagination, merge pages."""

    # Flask Mixin Configuration
    scraper_name = "bdl_games"
    required_params = []  # No required parameters
    optional_params = {
        "startDate": None,  # Defaults to yesterday
        "endDate": None,    # Defaults to tomorrow
        "api_key": None,     # Falls back to env var
    }

    # Original scraper config
    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "bdl_games"
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # Normal artifact (pretty JSON after full transform)
        {
            "type": "file",
            "filename": "/tmp/bdl_games_%(startDate)s_%(endDate)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        # Capture RAW + EXP
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
    # Option derivation                                                  #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        today_utc = _dt.datetime.now(_dt.timezone.utc).date()
        self.opts["startDate"] = _coerce_date(
            self.opts.get("startDate"), default=today_utc - _dt.timedelta(days=1)
        ).isoformat()
        self.opts["endDate"] = _coerce_date(
            self.opts.get("endDate"), default=today_utc + _dt.timedelta(days=1)
        ).isoformat()

    # ------------------------------------------------------------------ #
    # HTTP setup                                                         #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/games"

    def set_url(self) -> None:
        params = {
            "start_date": self.opts["startDate"],
            "end_date": self.opts["endDate"],
            "per_page": 100,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}?{query}"
        logger.debug("Games URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-games/1.1 (+github.com/your-org)",
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
                raise ValueError("Games response malformed: no 'data' key")
        except Exception as e:
            # Send error notification for validation failure
            try:
                notify_error(
                    title="BDL Games - Validation Failed",
                    message=f"Data validation failed for {self.opts.get('startDate')} to {self.opts.get('endDate')}: {str(e)}",
                    details={
                        'scraper': 'bdl_games',
                        'start_date': self.opts.get('startDate'),
                        'end_date': self.opts.get('endDate'),
                        'error_type': type(e).__name__,
                        'url': self.url,
                        'has_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Games"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send validation error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Transform (cursor walk + packaging)                                #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        try:
            games: List[Dict[str, Any]] = list(self.decoded_data["data"])
            cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")
            pages_fetched = 1

            base_params = {
                "start_date": self.opts["startDate"],
                "end_date": self.opts["endDate"],
                "per_page": 100,
            }

            # Get rate limit handler (if available)
            rate_limiter = get_rate_limit_handler() if get_rate_limit_handler is not None else None
            domain = "api.balldontlie.io"

            # Paginate through all results (with rate limit awareness)
            while cursor:
                # Check circuit breaker before fetching page
                if rate_limiter and rate_limiter.is_circuit_open(domain):
                    error_msg = f"Circuit breaker open for {domain}, aborting pagination"
                    logger.error(error_msg)
                    try:
                        notify_error(
                            title="BDL Games - Circuit Breaker Open",
                            message=error_msg,
                            details={
                                'scraper': 'bdl_games',
                                'start_date': self.opts.get('startDate'),
                                'end_date': self.opts.get('endDate'),
                                'pages_fetched': pages_fetched,
                                'games_so_far': len(games),
                                'action': 'Wait for circuit breaker cooldown or reduce API call frequency'
                            },
                            processor_name="Ball Don't Lie Games"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send circuit breaker notification: {notify_ex}")
                    raise RuntimeError(error_msg)

                try:
                    base_params["cursor"] = cursor
                    r = self.http_downloader.get(
                        self.base_url,
                        headers=self.headers,
                        params=base_params,
                        timeout=self.timeout_http,
                    )

                    # Handle rate limiting specifically
                    if r.status_code == 429:
                        if rate_limiter:
                            should_retry, wait_time = rate_limiter.should_retry(
                                r, pages_fetched, domain
                            )

                            if not should_retry:
                                error_msg = f"Rate limit exceeded during pagination (page {pages_fetched + 1})"
                                logger.error(error_msg)
                                try:
                                    notify_error(
                                        title="BDL Games - Rate Limit Exceeded",
                                        message=error_msg,
                                        details={
                                            'scraper': 'bdl_games',
                                            'start_date': self.opts.get('startDate'),
                                            'end_date': self.opts.get('endDate'),
                                            'pages_fetched': pages_fetched,
                                            'games_so_far': len(games),
                                            'cursor': cursor
                                        },
                                        processor_name="Ball Don't Lie Games"
                                    )
                                except Exception as notify_ex:
                                    logger.warning(f"Failed to send rate limit notification: {notify_ex}")
                                raise RuntimeError(error_msg)

                            # Wait before retrying
                            logger.info(f"Rate limited on page {pages_fetched + 1}, waiting {wait_time:.2f}s")
                            import time
                            time.sleep(wait_time)
                            continue  # Retry same page
                        else:
                            # No rate limiter, use simple backoff
                            import time
                            time.sleep(2.0)
                            continue

                    r.raise_for_status()

                    # Success - record it for circuit breaker
                    if rate_limiter:
                        rate_limiter.record_success(domain)

                    j = r.json()
                    games.extend(j.get("data", []))
                    cursor = j.get("meta", {}).get("next_cursor")
                    pages_fetched += 1

                except Exception as e:
                    # Pagination failure (non-429)
                    try:
                        notify_error(
                            title="BDL Games - Pagination Failed",
                            message=f"Failed to fetch page {pages_fetched + 1} for {self.opts.get('startDate')} to {self.opts.get('endDate')}: {str(e)}",
                            details={
                                'scraper': 'bdl_games',
                                'start_date': self.opts.get('startDate'),
                                'end_date': self.opts.get('endDate'),
                                'pages_fetched': pages_fetched,
                                'games_so_far': len(games),
                                'error_type': type(e).__name__,
                                'cursor': cursor
                            },
                            processor_name="Ball Don't Lie Games"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send pagination error notification: {notify_ex}")
                    raise

            games.sort(key=lambda g: g.get("id", 0))

            self.data = {
                "startDate": self.opts["startDate"],
                "endDate": self.opts["endDate"],
                "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "gameCount": len(games),
                "games": games,
            }
            
            logger.info(
                "Fetched %d games (%s -> %s) across %d pages",
                len(games),
                self.opts["startDate"],
                self.opts["endDate"],
                pages_fetched
            )

            # Success notification
            try:
                notify_info(
                    title="BDL Games - Success",
                    message=f"Successfully scraped {len(games)} games ({self.opts.get('startDate')} to {self.opts.get('endDate')})",
                    details={
                        'scraper': 'bdl_games',
                        'start_date': self.opts.get('startDate'),
                        'end_date': self.opts.get('endDate'),
                        'game_count': len(games),
                        'pages_fetched': pages_fetched
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send success notification: {notify_ex}")

        except Exception as e:
            # General transformation error
            try:
                notify_error(
                    title="BDL Games - Transform Failed",
                    message=f"Data transformation failed for {self.opts.get('startDate')} to {self.opts.get('endDate')}: {str(e)}",
                    details={
                        'scraper': 'bdl_games',
                        'start_date': self.opts.get('startDate'),
                        'end_date': self.opts.get('endDate'),
                        'error_type': type(e).__name__,
                        'has_decoded_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Games"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send transform error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:  # noqa: D401
        return {
            "startDate": self.opts["startDate"],
            "endDate": self.opts["endDate"],
            "gameCount": self.data.get("gameCount", 0),
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlGamesScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlGamesScraper.create_cli_and_flask_main()
    main()
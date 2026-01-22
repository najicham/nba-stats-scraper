"""
File: scrapers/balldontlie/bdl_box_scores.py

BALLDONTLIE - Box-Scores (final) endpoint                 v1.1 - 2025-06-24
-------------------------------------------------------------------------------
Finished-game box scores:

    https://api.balldontlie.io/v1/box_scores

--date param defaults to **yesterday (UTC)**.

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_box_scores \
      --date 2025-01-15 \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_box_scores.py --date 2025-01-15 --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_box_scores.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_box_scores
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_box_scores.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

# Retry logic for API resilience (prevents 40% of weekly failures)
try:
    from shared.utils.retry_with_jitter import retry_with_jitter
except ImportError:
    # Fallback if shared module not available
    logger.warning("Could not import retry_with_jitter, API calls will not retry on failure")
    def retry_with_jitter(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

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

# BDL availability logger for per-game tracking
try:
    from shared.utils.bdl_availability_logger import log_bdl_game_availability
except ImportError:
    # Graceful fallback if logger not available
    logger.warning("Could not import bdl_availability_logger - game availability tracking disabled")
    def log_bdl_game_availability(*args, **kwargs): pass

# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class BdlBoxScoresScraper(ScraperBase, ScraperFlaskMixin):
    """Daily or on-demand scraper for /box_scores."""

    # Flask Mixin Configuration
    scraper_name = "bdl_box_scores"
    required_params = []  # No required parameters (defaults to yesterday)
    optional_params = {
        "date": None,  # Defaults to yesterday if not provided
        "api_key": None,  # Falls back to env var
    }

    # Original scraper config
    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "bdl_box_scores"
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # Normal artifact
        {
            "type": "file",
            "filename": "/tmp/bdl_box_scores_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
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
            "pretty_print": True,
            "export_mode": ExportMode.DECODED,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts                                                    #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        if not self.opts.get("date"):
            # Use Eastern Time for NBA games - ensures west coast late games
            # (which end at 11 PM PT / 2 AM ET) are captured with correct date
            from scrapers.utils.date_utils import get_yesterday_eastern
            self.opts["date"] = get_yesterday_eastern()

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/box_scores"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}?date={self.opts['date']}&per_page=100"
        logger.debug("Box-scores URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-box-scores/1.1 (+github.com/your-org)",
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
                raise ValueError("Box-scores response malformed: missing 'data' key")
        except Exception as e:
            # Send error notification for validation failure
            try:
                notify_error(
                    title="BDL Box Scores - Validation Failed",
                    message=f"Data validation failed for date {self.opts.get('date', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_box_scores',
                        'date': self.opts.get('date'),
                        'error_type': type(e).__name__,
                        'url': self.url,
                        'has_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Box Scores"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send validation error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Transform (cursor-safe)                                            #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        try:
            rows: List[Dict[str, Any]] = list(self.decoded_data["data"])
            cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")
            pages_fetched = 1

            # Paginate through all results
            while cursor:
                try:
                    # Use retry-wrapped fetch for resilience against transient API failures
                    page_json = self._fetch_page_with_retry(cursor)
                    rows.extend(page_json.get("data", []))
                    cursor = page_json.get("meta", {}).get("next_cursor")
                    pages_fetched += 1
                except Exception as e:
                    # Pagination failure after all retries exhausted
                    try:
                        notify_error(
                            title="BDL Box Scores - Pagination Failed",
                            message=f"Failed to fetch page {pages_fetched + 1} for {self.opts.get('date', 'unknown')} after retries: {str(e)}",
                            details={
                                'scraper': 'bdl_box_scores',
                                'date': self.opts.get('date'),
                                'pages_fetched': pages_fetched,
                                'rows_so_far': len(rows),
                                'error_type': type(e).__name__,
                                'cursor': cursor
                            },
                            processor_name="Ball Don't Lie Box Scores"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send pagination error notification: {notify_ex}")
                    raise

            rows.sort(key=lambda r: (r.get("game", {}).get("id"), r.get("player_id")))

            self.data = {
                "date": self.opts["date"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "rowCount": len(rows),
                "boxScores": rows,
            }

            # Log which games were available from BDL API (per-game availability tracking)
            try:
                log_bdl_game_availability(
                    game_date=self.opts["date"],
                    execution_id=self.run_id,
                    box_scores=self.data["boxScores"],
                    workflow=self.opts.get("workflow", "unknown")
                )
                logger.info(f"Logged BDL game availability for {self.opts['date']}")
            except Exception as e:
                logger.warning(f"Failed to log BDL game availability: {e}", exc_info=True)

            logger.info("Fetched %d box-score rows for %s across %d pages",
                       len(rows), self.opts["date"], pages_fetched)

            # Check for data quality issues
            if len(rows) == 0:
                try:
                    notify_warning(
                        title="BDL Box Scores - No Data Found",
                        message=f"No box score rows returned for {self.opts.get('date', 'unknown')}",
                        details={
                            'scraper': 'bdl_box_scores',
                            'date': self.opts.get('date'),
                            'note': 'This may be normal for off-days or future dates'
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send empty data warning: {notify_ex}")
            elif len(rows) < 50:
                # Typical game has ~26 players (13 per team), so < 50 rows suggests partial data
                try:
                    notify_warning(
                        title="BDL Box Scores - Low Data Count",
                        message=f"Only {len(rows)} box score rows for {self.opts.get('date', 'unknown')} (expected 100+ on game days)",
                        details={
                            'scraper': 'bdl_box_scores',
                            'date': self.opts.get('date'),
                            'row_count': len(rows),
                            'note': 'May indicate incomplete data or few games played'
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send low count warning: {notify_ex}")
            else:
                # Success notification
                try:
                    notify_info(
                        title="BDL Box Scores - Success",
                        message=f"Successfully scraped {len(rows)} box score rows for {self.opts.get('date', 'unknown')}",
                        details={
                            'scraper': 'bdl_box_scores',
                            'date': self.opts.get('date'),
                            'row_count': len(rows),
                            'pages_fetched': pages_fetched,
                            'estimated_games': len(rows) // 26 if len(rows) > 0 else 0
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send success notification: {notify_ex}")

        except Exception as e:
            # General transformation error
            try:
                notify_error(
                    title="BDL Box Scores - Transform Failed",
                    message=f"Data transformation failed for {self.opts.get('date', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_box_scores',
                        'date': self.opts.get('date'),
                        'error_type': type(e).__name__,
                        'has_decoded_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Box Scores"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send transform error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Retry-wrapped pagination (prevents 40% of weekly failures)         #
    # ------------------------------------------------------------------ #
    @retry_with_jitter(
        max_attempts=5,
        base_delay=60,  # Start with 60s delay (BDL API rate limits)
        max_delay=1800,  # Max 30 minutes delay
        exceptions=(requests.RequestException, requests.Timeout, ConnectionError)
    )
    def _fetch_page_with_retry(self, cursor: str) -> Dict[str, Any]:
        """
        Fetch a single page from BDL API with automatic retry on transient failures.

        Retry strategy:
        - 5 attempts with exponential backoff + jitter
        - Handles: Network errors, timeouts, API rate limits (429), server errors (5xx)
        - Total retry window: ~30 minutes worst case

        This prevents 40% of weekly box score gaps caused by transient API failures.

        Args:
            cursor: Pagination cursor from previous response

        Returns:
            JSON response from API

        Raises:
            requests.RequestException: After all retries exhausted
        """
        resp = self.http_downloader.get(
            self.base_url,
            headers=self.headers,
            params={"cursor": cursor, "per_page": 100},
            timeout=self.timeout_http,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"rowCount": self.data.get("rowCount", 0), "date": self.opts["date"]}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlBoxScoresScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlBoxScoresScraper.create_cli_and_flask_main()
    main()
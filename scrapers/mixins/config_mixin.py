"""
config_mixin.py

Mixin for managing scraper configuration, options, headers, and URLs.
"""

import logging
import os
from datetime import datetime
from typing import Dict, Any

from scrapers.utils.env_utils import is_local
from scrapers.utils.exceptions import DownloadDataException, DownloadDecodeMaxRetryException
from scrapers.utils.nba_header_utils import (
    stats_nba_headers,
    data_nba_headers,
    core_api_headers,
    _ua,
    cdn_nba_headers,
    stats_api_headers,
    bettingpros_headers,
)
from shared.utils.notification_system import notify_error, notify_warning

logger = logging.getLogger(__name__)


class ConfigMixin:
    """
    Mixin for scraper configuration management.

    Handles:
    - Setting and validating options
    - Managing URLs and headers
    - Time tracking
    - Hook methods for data transformation
    """

    def set_opts(self, opts: Dict[str, Any]) -> None:
        """
        Set and process scraper options from the provided configuration.

        Copies options to self.opts, extracts proxy URL if provided, and
        optionally locks the run_id if specified in opts.

        Args:
            opts: Configuration dictionary containing scraper options.
                  Common keys include:
                  - gamedate: Date for game-specific scrapers (YYYYMMDD format)
                  - group: Export group ('dev' or 'prod')
                  - proxyUrl: Optional proxy URL for requests
                  - run_id: Optional run ID to lock for correlation

        Example:
            scraper.set_opts({'gamedate': '20260115', 'group': 'prod'})
        """
        self.opts = opts
        self.proxy_url = opts.get("proxyUrl") or os.getenv("NBA_SCRAPER_PROXY")

        # ── NEW: allow caller to lock the run_id up‑front ───────────────────
        if opts.get("run_id"):
            self.run_id = str(opts["run_id"])

        self.opts["run_id"] = self.run_id

    def validate_opts(self) -> None:
        """
        Validate that all required options are present in self.opts.

        Checks self.required_opts (defined by subclasses) and raises
        DownloadDataException if any required option is missing.
        Also sends an error notification for monitoring.

        Raises:
            DownloadDataException: If any required option is missing.

        Example:
            # Subclass defines required options
            class GameScraper(ScraperBase):
                required_opts = ['gamedate', 'season']

            # Validation happens automatically in run()
        """
        for required_opt in self.required_opts:
            if required_opt not in self.opts:
                error_msg = f"Missing required option [{required_opt}]."

                try:
                    notify_error(
                        title=f"Scraper Configuration Error: {self.__class__.__name__}",
                        message=f"Missing required option: {required_opt}",
                        details={
                            'scraper': self.__class__.__name__,
                            'run_id': self.run_id,
                            'missing_option': required_opt,
                            'required_opts': self.required_opts,
                            'provided_opts': list(self.opts.keys())
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")

                raise DownloadDataException(error_msg)

    def set_exporter_group_to_opts(self):
        """
        If opts doesn't contain 'group', set default:
          'dev' if local, else 'prod'.
        """
        if "group" not in self.opts:
            self.opts["group"] = "dev" if is_local() else "prod"

    def set_additional_opts(self):
        """
        Add standard variables needed for GCS export paths and derived options.

        This method adds computed options that scrapers commonly need:
        - timestamp: UTC timestamp for unique filenames (YYYYMMDD_HHMMSS)
        - date: Game date in YYYY-MM-DD format (derived from gamedate if present)

        Subclasses should override and call super().set_additional_opts() first,
        then add their own derived options (e.g., season year from date).

        Example:
            class SeasonScraper(ScraperBase):
                def set_additional_opts(self):
                    super().set_additional_opts()
                    # Add season year: 2025-10-15 -> 2025
                    date = self.opts.get('date')
                    if date:
                        month = int(date[5:7])
                        year = int(date[:4])
                        self.opts['season'] = year if month >= 10 else year - 1
        """
        # Add UTC timestamp for unique filenames
        if "timestamp" not in self.opts:
            self.opts["timestamp"] = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        # Add Eastern date if not provided as parameter
        if "date" not in self.opts:
            # Derive from existing parameters first
            if "gamedate" in self.opts:
                gamedate = self.opts["gamedate"]
                if len(gamedate) == 8 and gamedate.isdigit():
                    # Convert YYYYMMDD to YYYY-MM-DD for consistent paths
                    self.opts["date"] = f"{gamedate[:4]}-{gamedate[4:6]}-{gamedate[6:8]}"
                else:
                    self.opts["date"] = gamedate  # Already has dashes
            elif "game_date" in self.opts:
                game_date = self.opts["game_date"]
                if len(game_date) == 8 and game_date.isdigit():
                    # Convert YYYYMMDD to YYYY-MM-DD for consistent paths
                    self.opts["date"] = f"{game_date[:4]}-{game_date[4:6]}-{game_date[6:8]}"
                else:
                    self.opts["date"] = game_date  # Already has dashes
            else:
                # Use current Eastern date
                try:
                    import pytz
                    eastern = pytz.timezone('US/Eastern')
                    eastern_now = datetime.now(eastern)
                    self.opts["date"] = eastern_now.strftime("%Y-%m-%d")
                except (ImportError, KeyError):
                    # ImportError: pytz not installed; KeyError: invalid timezone name
                    # Fallback to UTC date if timezone fails
                    self.opts["date"] = datetime.utcnow().strftime("%Y-%m-%d")

        logger.debug("Added standard path variables: timestamp=%s, date=%s",
                self.opts.get("timestamp"), self.opts.get("date"))

    def validate_additional_opts(self):
        """
        Hook: child scrapers can validate newly-added opts.
        By default, we ensure 'group' is present.
        """
        if "group" not in self.opts:
            raise DownloadDataException("Missing 'group' after set_exporter_group_to_opts.")

    def set_url(self):
        """
        Build the target URL for this scraper using self.opts.

        Subclasses must override this method to set self.url.
        Use options from self.opts to construct the URL.

        Example:
            def set_url(self):
                date = self.opts['date']
                self.url = f"https://stats.nba.com/stats/scoreboard?GameDate={date}"
        """
        pass

    def set_headers(self):
        """
        Set HTTP headers for API requests based on header_profile.

        Uses self.header_profile to select pre-configured header sets:
        - 'stats': stats.nba.com headers
        - 'data': data.nba.com headers
        - 'core': NBA Core API headers
        - 'espn': ESPN user-agent only
        - 'nbacdn': NBA CDN headers
        - 'statsapi': Stats API headers
        - 'bettingpros': BettingPros headers

        Falls back to a simple user-agent if profile not found.
        """
        profile_map = {
            "stats": stats_nba_headers,
            "data":  data_nba_headers,
            "core":  core_api_headers,
            "espn":  lambda: {"User-Agent": _ua()},
            "nbacdn": cdn_nba_headers,
            "statsapi": stats_api_headers,
            "bettingpros": bettingpros_headers,
        }
        if self.header_profile in profile_map:
            fn = profile_map[self.header_profile]
            self.headers = fn() if callable(fn) else fn
        else:
            self.headers = {"User-Agent": _ua()}

    def should_retry_on_http_status_code(self, status_code):
        """
        Return True unless status_code is in no_retry_status_codes (e.g. 404).
        """
        return status_code not in self.no_retry_status_codes

    def increment_retry_count(self):
        """
        Enhanced: Check for "no data" success cases before raising max retry exception.
        """
        if self.download_retry_count < self.max_retries_decode:
            self.download_retry_count += 1
        else:
            # BEFORE raising exception, check if this should be "no data" success
            if (hasattr(self, 'treat_max_retries_as_success') and
                hasattr(self, 'raw_response') and
                self.raw_response and
                self.raw_response.status_code in getattr(self, 'treat_max_retries_as_success', [])):

                logger.info("✅ Treating max retries (status %d) as 'no data available' success",
                        self.raw_response.status_code)

                # Raise a special exception that the download loop can catch
                from scrapers.utils.exceptions import NoDataAvailableSuccess
                raise NoDataAvailableSuccess(
                    f"No data available (HTTP {self.raw_response.status_code}) - treating as success"
                )
            else:
                # Normal max retry behavior
                raise DownloadDecodeMaxRetryException(
                    f"Max decode/download retries reached: {self.max_retries_decode}"
                )

    def sleep_before_retry(self):
        """
        Exponential backoff. 4 * 2^(retry_count-1), capped at 15 seconds.
        """
        import time
        backoff_factor = 4
        backoff_max = 15
        sleep_seconds = min(backoff_factor * (2 ** (self.download_retry_count - 1)), backoff_max)
        logger.warning("Sleeping %.1f seconds before retry...", sleep_seconds)
        time.sleep(sleep_seconds)

    def extract_opts_from_data(self):
        """
        If we discover new context from decoded_data (like a seasonYear)
        that becomes part of self.opts, child scrapers override here.
        """
        pass

    def validate_extracted_opts(self):
        """
        If we changed self.opts in extract_opts_from_data, we can do final checks here.
        """
        pass

    def transform_data(self):
        """
        Transform decoded API response into the format for export.

        Subclasses must override this method to restructure self.decoded_data
        into self.data. The transformed data in self.data will be exported
        to GCS/BigQuery.

        This is where you:
        - Extract relevant fields from the API response
        - Rename fields to match your schema
        - Add computed fields (timestamps, derived values)
        - Flatten nested structures

        Example:
            def transform_data(self):
                games = self.decoded_data.get('scoreboard', {}).get('games', [])
                self.data['games'] = [
                    {
                        'game_id': g['gameId'],
                        'home_team': g['homeTeam']['teamTricode'],
                        'away_team': g['awayTeam']['teamTricode'],
                        'game_date': self.opts['date']
                    }
                    for g in games
                ]
        """
        pass

    def should_save_data(self):
        """
        Return False to skip exporting under certain conditions.
        Child scrapers can override if needed.
        """
        return True

    def get_no_data_response(self) -> dict | list:
        """
        Return the data structure to use when no data is available
        (e.g., after max retries with treat_max_retries_as_success).

        Child scrapers can override this to return a proper structured
        response with metadata instead of an empty list.

        Returns:
            Default: [] (empty list)
            Child classes can return {"metadata": {...}, "records": []} etc.
        """
        return []

    def mark_time(self, label):
        """
        If label is new, store 'start'=now, 'last'=now, return "0.0" sec.
        If label exists, measure time delta from last_time to now,
        update 'last'=now, return string e.g. "3.4" sec.
        """
        now = datetime.now()
        if label not in self.time_markers:
            self.time_markers[label] = {
                "start": now,
                "last": now
            }
            return "0.0"
        else:
            last_time = self.time_markers[label]["last"]
            delta = (now - last_time).total_seconds()
            self.time_markers[label]["last"] = now
            return f"{delta:.1f}"

    def get_elapsed_seconds(self, label):
        """
        Return total seconds from when we first called mark_time(label)
        to 'now'.
        """
        if label not in self.time_markers:
            return 0.0
        start_time = self.time_markers[label]["start"]
        now_time = datetime.now()
        return (now_time - start_time).total_seconds()

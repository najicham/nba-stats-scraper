"""
File: scrapers/balldontlie/bdl_teams.py

BallDontLie - Teams endpoint                                    v1.1 - 2025-06-23
-------------------------------------------------------------------------------
Grabs the full list of NBA franchises from

    https://api.balldontlie.io/v1/teams            (no auth required for free tier)

If pagination ever appears (meta.next_page > current_page) we'll loop until done.

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_teams \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_teams.py --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_teams.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_teams
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_teams.py
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
    def notify_warning(*args, **kwargs,
    processor_name=self.__class__.__name__
    ): pass
    def notify_info(*args, **kwargs,
    processor_name=self.__class__.__name__
    ): pass

logger = logging.getLogger(__name__)  # module-specific logger


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class BdlTeams(ScraperBase, ScraperFlaskMixin):
    """Static reference table - typically run once per season."""

    # Flask Mixin Configuration
    scraper_name = "bdl_teams"
    required_params = []  # No required parameters
    optional_params = {
        "api_key": None,  # Falls back to env var (optional for free tier)
    }

    # Original scraper config
    download_type = DownloadType.JSON
    decode_download_data = True
    required_opts: List[str] = []  # no CLI options required
    proxy_enabled: bool = False

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "bdl_teams"
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # Normal dev / prod artifact
        {
            "type": "file",
            "filename": "/tmp/bdl_teams.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
        # Capture RAW
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        # Capture decoded EXP
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DECODED,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # URL & headers
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/teams"

    def set_url(self) -> None:
        self.url = self._API_ROOT  # no query params today
        logger.debug("Teams URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_API_KEY")
        hdrs = {
            "User-Agent": "scrape-bdl-teams/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:  # paid tier or future lockdown
            hdrs["Authorization"] = f"Bearer {api_key}"
        self.headers = hdrs

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        try:
            if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
                raise ValueError("Unexpected teams JSON structure")
        except Exception as e:
            # Send error notification for validation failure
            try:
                notify_error(
                    title="BDL Teams - Validation Failed",
                    message=f"Data validation failed: {str(e)}",
                    details={
                        'scraper': 'bdl_teams',
                        'error_type': type(e).__name__,
                        'url': self.url,
                        'has_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Teams"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send validation error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Transform (handles future pagination)
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        # Import max pages from centralized constants
        from shared.constants.resilience import BDL_MAX_PAGES

        try:
            teams: List[Dict[str, Any]] = []
            page_json: Dict[str, Any] = self.decoded_data
            pages_fetched = 1

            while True:
                # Safety guard: prevent infinite loops
                if pages_fetched > BDL_MAX_PAGES:
                    logger.warning(
                        f"Reached maximum page limit ({BDL_MAX_PAGES}), "
                        f"stopping pagination with {len(teams)} teams"
                    )
                    break

                teams.extend(page_json.get("data", []))

                # BDL v1 paginates with meta.next_page (int) or next_page_url (str)
                meta = page_json.get("meta", {})
                next_page = meta.get("next_page") or meta.get("next_page_url")
                if not next_page:
                    break

                logger.debug("Following pagination to %s", next_page)
                try:
                    page_json = self.http_downloader.get(
                        next_page if isinstance(next_page, str) else self._API_ROOT,
                        headers=self.headers,
                        params={"page": next_page} if isinstance(next_page, int) else None,
                        timeout=self.timeout_http,
                    ).json()
                    pages_fetched += 1
                except Exception as e:
                    # Pagination failure
                    try:
                        notify_error(
                            title="BDL Teams - Pagination Failed",
                            message=f"Failed to fetch page {pages_fetched + 1}: {str(e)}",
                            details={
                                'scraper': 'bdl_teams',
                                'pages_fetched': pages_fetched,
                                'teams_so_far': len(teams),
                                'error_type': type(e).__name__,
                                'next_page': str(next_page)
                            },
                            processor_name="Ball Don't Lie Teams"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send pagination error notification: {notify_ex}")
                    raise

            teams.sort(key=lambda t: t["id"])  # deterministic order

            self.data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "teamCount": len(teams),
                "teams": teams,
            }
            
            logger.info("Fetched %d NBA franchises across %d pages", len(teams), pages_fetched)

            # Data quality check - NBA should have exactly 30 teams
            if len(teams) == 0:
                try:
                    notify_error(
                        title="BDL Teams - No Data",
                        message="No teams returned from API",
                        details={
                            'scraper': 'bdl_teams',
                            'team_count': 0,
                            'note': 'This is unusual - teams endpoint should always return 30 teams'
                        },
                        processor_name="Ball Don't Lie Teams"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send empty data error: {notify_ex}")
            elif len(teams) != 30:
                # NBA has exactly 30 teams, so any other count indicates a data issue
                try:
                    notify_warning(
                        title="BDL Teams - Incorrect Team Count",
                        message=f"Teams endpoint returned {len(teams)} teams (expected 30)",
                        details={
                            'scraper': 'bdl_teams',
                            'team_count': len(teams),
                            'expected_count': 30,
                            'note': 'May indicate incomplete data or API issue'
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send incorrect count warning: {notify_ex}")
            else:
                # Success notification - correct team count
                try:
                    notify_info(
                        title="BDL Teams - Success",
                        message=f"Successfully scraped all 30 NBA teams",
                        details={
                            'scraper': 'bdl_teams',
                            'team_count': len(teams),
                            'pages_fetched': pages_fetched
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send success notification: {notify_ex}")

        except Exception as e:
            # General transformation error
            try:
                notify_error(
                    title="BDL Teams - Transform Failed",
                    message=f"Data transformation failed: {str(e)}",
                    details={
                        'scraper': 'bdl_teams',
                        'error_type': type(e).__name__,
                        'has_decoded_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Teams"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send transform error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Stats for SCRAPER_STATS
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"teamCount": self.data.get("teamCount", 0)}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlTeams)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlTeams.create_cli_and_flask_main()
    main()
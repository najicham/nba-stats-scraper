"""
File: scrapers/balldontlie/bdl_player_leaders.py

BALLDONTLIE - Player Leaders endpoint                   v1.2  2025-06-24
-----------------------------------------------------------------------
Top-N league leaders for a single statistic:

    https://api.balldontlie.io/v1/leaders

Defaults:  statType = "pts",  season = current NBA season

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_player_leaders \
      --statType pts --season 2024 \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_player_leaders.py --statType ast --season 2024 --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_player_leaders.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_player_leaders
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_player_leaders.py
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

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _current_nba_season() -> int:
    today = datetime.now(timezone.utc)
    return today.year if today.month >= 9 else today.year - 1


_VALID_STATS = {
    "pts", "ast", "reb", "stl", "blk", "tov",
    "fg_pct", "fg3_pct", "ft_pct",
    "plus_minus", "off_rtg", "def_rtg",
    "ts_pct", "efg_pct", "usg_pct",
}

# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class BdlPlayerLeadersScraper(ScraperBase, ScraperFlaskMixin):
    """Scraper for /leaders (top-N players for one stat)."""

    # Flask Mixin Configuration
    scraper_name = "bdl_player_leaders"
    required_params = []  # No required parameters
    optional_params = {
        "statType": "pts",    # Default to points
        "season": None,       # Defaults to current NBA season
        "api_key": None,       # Falls back to env var
    }

    # Original scraper config
    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    # ------------------------------------------------------------------ #
    # Exporters
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "bdl_player_leaders"
    exporters = [
        # GCS RAW for production
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # Normal artefact
        {
            "type": "file",
            "filename": "/tmp/bdl_player_leaders_%(ident)s.json",
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
        
        try:
            stat_type = (self.opts.get("statType") or "pts").lower()
            if stat_type not in _VALID_STATS:
                raise ValueError(
                    f"Invalid statType '{stat_type}'. Allowed: {', '.join(sorted(_VALID_STATS))}"
                )
            self.opts["statType"] = stat_type
            self.opts["season"] = int(self.opts.get("season") or _current_nba_season())
            self.opts["ident"] = f"{self.opts['season']}_{stat_type}"
        
        except Exception as e:
            # Send error notification for parameter validation failure
            try:
                notify_error(
                    title="BDL Player Leaders - Parameter Validation Failed",
                    message=f"Invalid parameters: {str(e)}",
                    details={
                        'scraper': 'bdl_player_leaders',
                        'error_type': type(e).__name__,
                        'stat_type': self.opts.get('statType'),
                        'season': self.opts.get('season'),
                        'valid_stats': ', '.join(sorted(_VALID_STATS))
                    },
                    processor_name="Ball Don't Lie Player Leaders"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send parameter validation error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/leaders"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT
        self.url = (
            f"{self.base_url}?season={self.opts['season']}"
            f"&stat_type={self.opts['statType']}&per_page=100"
        )
        logger.debug("Leaders URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-player-leaders/1.2 (+github.com/your-org)",
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
                raise ValueError("Leaders response malformed: missing 'data' key")
        except Exception as e:
            # Send error notification for validation failure
            try:
                notify_error(
                    title="BDL Player Leaders - Validation Failed",
                    message=f"Data validation failed for {self.opts.get('ident', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_player_leaders',
                        'ident': self.opts.get('ident'),
                        'stat_type': self.opts.get('statType'),
                        'season': self.opts.get('season'),
                        'error_type': type(e).__name__,
                        'url': self.url,
                        'has_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Player Leaders"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send validation error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Transform (cursor-aware)                                           #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        try:
            leaders: List[Dict[str, Any]] = list(self.decoded_data["data"])
            cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")
            pages_fetched = 1

            # Paginate through all results
            while cursor:
                try:
                    resp = self.http_downloader.get(
                        self.base_url,
                        headers=self.headers,
                        params={
                            "cursor": cursor,
                            "per_page": 100,
                            "season": self.opts["season"],
                            "stat_type": self.opts["statType"],
                        },
                        timeout=self.timeout_http,
                    )
                    resp.raise_for_status()
                    page_json: Dict[str, Any] = resp.json()
                    leaders.extend(page_json.get("data", []))
                    cursor = page_json.get("meta", {}).get("next_cursor")
                    pages_fetched += 1
                except Exception as e:
                    # Pagination failure
                    try:
                        notify_error(
                            title="BDL Player Leaders - Pagination Failed",
                            message=f"Failed to fetch page {pages_fetched + 1} for {self.opts.get('ident', 'unknown')}: {str(e)}",
                            details={
                                'scraper': 'bdl_player_leaders',
                                'ident': self.opts.get('ident'),
                                'stat_type': self.opts.get('statType'),
                                'season': self.opts.get('season'),
                                'pages_fetched': pages_fetched,
                                'leaders_so_far': len(leaders),
                                'error_type': type(e).__name__,
                                'cursor': cursor
                            },
                            processor_name="Ball Don't Lie Player Leaders"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send pagination error notification: {notify_ex}")
                    raise

            leaders.sort(key=lambda r: r.get("rank", 999))

            self.data = {
                "ident": self.opts["ident"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "rowCount": len(leaders),
                "leaders": leaders,
            }
            
            logger.info("Fetched %d leader rows for %s across %d pages", 
                       len(leaders), self.opts["ident"], pages_fetched)

            # Success notification
            try:
                notify_info(
                    title="BDL Player Leaders - Success",
                    message=f"Successfully scraped {len(leaders)} leader rows ({self.opts.get('ident', 'unknown')})",
                    details={
                        'scraper': 'bdl_player_leaders',
                        'ident': self.opts.get('ident'),
                        'stat_type': self.opts.get('statType'),
                        'season': self.opts.get('season'),
                        'leader_count': len(leaders),
                        'pages_fetched': pages_fetched
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send success notification: {notify_ex}")

        except Exception as e:
            # General transformation error
            try:
                notify_error(
                    title="BDL Player Leaders - Transform Failed",
                    message=f"Data transformation failed for {self.opts.get('ident', 'unknown')}: {str(e)}",
                    details={
                        'scraper': 'bdl_player_leaders',
                        'ident': self.opts.get('ident'),
                        'stat_type': self.opts.get('statType'),
                        'season': self.opts.get('season'),
                        'error_type': type(e).__name__,
                        'has_decoded_data': self.decoded_data is not None
                    },
                    processor_name="Ball Don't Lie Player Leaders"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send transform error notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"rowCount": self.data.get("rowCount", 0), "ident": self.opts["ident"]}


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlPlayerLeadersScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlPlayerLeadersScraper.create_cli_and_flask_main()
    main()
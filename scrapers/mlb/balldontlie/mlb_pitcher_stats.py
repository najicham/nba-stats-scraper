"""
File: scrapers/mlb/balldontlie/mlb_pitcher_stats.py

MLB Ball Don't Lie - Pitcher Game Statistics                    v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Per-game pitching statistics from the Ball Don't Lie MLB API.

API Endpoint: https://api.balldontlie.io/mlb/v1/stats

Key Fields for Strikeout Predictions:
- P_K: Strikeouts (our TARGET variable)
- IP: Innings Pitched
- PITCH_COUNT: Total pitches thrown
- STRIKES: Strike count
- P_BB: Walks allowed
- P_HITS: Hits allowed
- ERA: Earned Run Average (calculated)

Usage examples:
  # Fetch pitcher stats for a specific date:
  python scrapers/mlb/balldontlie/mlb_pitcher_stats.py --date 2025-06-15 --debug

  # Fetch stats for specific games:
  python scrapers/mlb/balldontlie/mlb_pitcher_stats.py --game_ids 12345,12346

  # Flask web service:
  python scrapers/mlb/balldontlie/mlb_pitcher_stats.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# Support both module execution and direct execution
try:
    from ...scraper_base import DownloadType, ExportMode, ScraperBase
    from ...scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from ...utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

# Notification system imports
try:
    from shared.utils.notification_system import notify_error, notify_warning, notify_info
except ImportError:
    def notify_error(*args, **kwargs): pass
    def notify_warning(*args, **kwargs): pass
    def notify_info(*args, **kwargs): pass

logger = logging.getLogger(__name__)


class MlbPitcherStatsScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for MLB pitcher game statistics from Ball Don't Lie API.

    This scraper fetches per-game pitching stats, which include the P_K (strikeouts)
    field that is our primary target variable for prediction models.
    """

    # Flask Mixin Configuration
    scraper_name = "mlb_pitcher_stats"
    required_params = []
    optional_params = {
        "date": None,           # Filter by game date
        "dates": None,          # Multiple dates (comma-separated)
        "game_ids": None,       # Filter by specific game IDs
        "player_ids": None,     # Filter by specific player IDs
        "seasons": None,        # Filter by season(s)
        "api_key": None,        # Falls back to env var
    }

    # Scraper config
    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True
    proxy_enabled: bool = False

    # GCS Export Configuration
    GCS_PATH_KEY = "mlb_pitcher_stats"
    exporters = [
        # GCS for production
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        # Local file for development
        {
            "type": "file",
            "filename": "/tmp/mlb_pitcher_stats_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
        # Capture modes
        {
            "type": "file",
            "filename": "/tmp/mlb_pitcher_stats_raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_pitcher_stats_exp_%(run_id)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DECODED,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        # Default to yesterday if no date specified
        # Use Pacific Time for MLB - ensures west coast late games are captured
        if not self.opts.get("date") and not self.opts.get("dates") and not self.opts.get("game_ids"):
            from scrapers.utils.date_utils import get_yesterday_pacific
            self.opts["date"] = get_yesterday_pacific()

    # ------------------------------------------------------------------ #
    # URL & headers
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/mlb/v1/stats"

    def set_url(self) -> None:
        self.base_url = self._API_ROOT

        # Build query parameters
        params = ["per_page=100"]

        if self.opts.get("date"):
            # Single date - use dates parameter
            params.append(f"dates[]={self.opts['date']}")
        elif self.opts.get("dates"):
            # Multiple dates
            for d in self.opts["dates"].split(","):
                params.append(f"dates[]={d.strip()}")

        if self.opts.get("game_ids"):
            for gid in str(self.opts["game_ids"]).split(","):
                params.append(f"game_ids[]={gid.strip()}")

        if self.opts.get("player_ids"):
            for pid in str(self.opts["player_ids"]).split(","):
                params.append(f"player_ids[]={pid.strip()}")

        if self.opts.get("seasons"):
            for s in str(self.opts["seasons"]).split(","):
                params.append(f"seasons[]={s.strip()}")

        self.url = f"{self.base_url}?{'&'.join(params)}"
        logger.debug("MLB Pitcher Stats URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_MLB_API_KEY") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "mlb-pitcher-stats-scraper/1.0",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = api_key

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        try:
            if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
                raise ValueError("MLB stats response malformed: missing 'data' key")
        except Exception as e:
            notify_error(
                title="MLB Pitcher Stats - Validation Failed",
                message=f"Data validation failed: {str(e)}",
                details={
                    'scraper': 'mlb_pitcher_stats',
                    'date': self.opts.get('date'),
                    'error_type': type(e).__name__,
                },
                processor_name="MLB Pitcher Stats"
            )
            raise

    # ------------------------------------------------------------------ #
    # Transform (with pagination)
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        try:
            all_stats: List[Dict[str, Any]] = list(self.decoded_data["data"])
            cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")
            pages_fetched = 1

            # Paginate through all results
            while cursor:
                try:
                    resp = self.http_downloader.get(
                        self.base_url,
                        headers=self.headers,
                        params={"cursor": cursor, "per_page": 100},
                        timeout=self.timeout_http,
                    )
                    resp.raise_for_status()
                    page_json: Dict[str, Any] = resp.json()
                    all_stats.extend(page_json.get("data", []))
                    cursor = page_json.get("meta", {}).get("next_cursor")
                    pages_fetched += 1
                except Exception as e:
                    notify_error(
                        title="MLB Pitcher Stats - Pagination Failed",
                        message=f"Failed to fetch page {pages_fetched + 1}: {str(e)}",
                        details={
                            'scraper': 'mlb_pitcher_stats',
                            'pages_fetched': pages_fetched,
                            'rows_so_far': len(all_stats),
                        },
                        processor_name="MLB Pitcher Stats"
                    )
                    raise

            # Filter to only pitcher stats (have pitching fields)
            pitcher_stats = [
                stat for stat in all_stats
                if self._is_pitcher_stat(stat)
            ]

            # Sort by game_id, then player_id
            pitcher_stats.sort(key=lambda r: (
                r.get("game", {}).get("id", 0),
                r.get("player", {}).get("id", 0)
            ))

            # Extract key strikeout data for easy access
            for stat in pitcher_stats:
                stat["_strikeouts"] = stat.get("p_k", 0) or stat.get("strikeouts", 0) or 0
                stat["_innings_pitched"] = stat.get("ip", 0) or stat.get("innings_pitched", 0) or 0

            self.data = {
                "date": self.opts.get("date", "multiple"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "rowCount": len(pitcher_stats),
                "totalStatsReturned": len(all_stats),
                "pitcherStats": pitcher_stats,
            }

            logger.info(
                "Fetched %d pitcher stat rows (from %d total) for %s across %d pages",
                len(pitcher_stats), len(all_stats), self.opts.get("date", "multiple"), pages_fetched
            )

            # Data quality checks
            if len(pitcher_stats) == 0:
                notify_warning(
                    title="MLB Pitcher Stats - No Data Found",
                    message=f"No pitcher stats returned for {self.opts.get('date', 'query')}",
                    details={
                        'scraper': 'mlb_pitcher_stats',
                        'date': self.opts.get('date'),
                        'total_stats': len(all_stats),
                    }
                )
            else:
                # Calculate some summary stats
                total_ks = sum(s.get("_strikeouts", 0) for s in pitcher_stats)
                avg_ks = total_ks / len(pitcher_stats) if pitcher_stats else 0

                notify_info(
                    title="MLB Pitcher Stats - Success",
                    message=f"Scraped {len(pitcher_stats)} pitcher stat rows",
                    details={
                        'scraper': 'mlb_pitcher_stats',
                        'date': self.opts.get('date'),
                        'pitcher_count': len(pitcher_stats),
                        'total_strikeouts': total_ks,
                        'avg_strikeouts': round(avg_ks, 2),
                    }
                )

        except Exception as e:
            notify_error(
                title="MLB Pitcher Stats - Transform Failed",
                message=f"Data transformation failed: {str(e)}",
                details={
                    'scraper': 'mlb_pitcher_stats',
                    'date': self.opts.get('date'),
                    'error_type': type(e).__name__,
                },
                processor_name="MLB Pitcher Stats"
            )
            raise

    def _is_pitcher_stat(self, stat: Dict[str, Any]) -> bool:
        """
        Check if a stat record is for a pitcher (has pitching-specific fields).

        Pitching fields include: p_k (strikeouts), ip (innings pitched),
        p_bb (walks), p_hits, er (earned runs), etc.
        """
        # Check for pitching-specific fields
        pitching_fields = ['p_k', 'ip', 'er', 'p_bb', 'p_hits', 'pitch_count', 'strikes']

        for field in pitching_fields:
            value = stat.get(field)
            if value is not None and value != 0:
                return True

        # Also check player position if available
        player = stat.get("player", {})
        position = player.get("position", "").lower()
        if "pitcher" in position or position in ["sp", "rp", "cp", "p"]:
            return True

        return False

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0),
            "date": self.opts.get("date", "multiple"),
        }


# --------------------------------------------------------------------------- #
# Flask and CLI entry points
# --------------------------------------------------------------------------- #
create_app = convert_existing_flask_scraper(MlbPitcherStatsScraper)

if __name__ == "__main__":
    main = MlbPitcherStatsScraper.create_cli_and_flask_main()
    main()

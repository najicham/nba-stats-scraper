"""
File: scrapers/mlb/balldontlie/mlb_batter_stats.py

MLB Ball Don't Lie - Batter Game Statistics                      v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Per-game batting statistics from the Ball Don't Lie MLB API.

API Endpoint: https://api.balldontlie.io/mlb/v1/stats

Key Fields for Bottom-Up Strikeout Model:
- K / strikeouts: Batter strikeouts (CRITICAL for bottom-up model)
- AB: At bats
- H: Hits
- BB: Walks
- HR: Home runs
- RBI: Runs batted in

Bottom-Up Model Insight:
  Pitcher K's ≈ Sum of individual batter K probabilities
  If batter K lines don't sum to pitcher K line → market inefficiency → edge

Usage examples:
  # Fetch batter stats for a specific date:
  python scrapers/mlb/balldontlie/mlb_batter_stats.py --date 2025-06-15 --debug

  # Fetch stats for specific games:
  python scrapers/mlb/balldontlie/mlb_batter_stats.py --game_ids 12345,12346

  # Flask web service:
  python scrapers/mlb/balldontlie/mlb_batter_stats.py --serve --debug
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


class MlbBatterStatsScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for MLB batter game statistics from Ball Don't Lie API.

    This scraper fetches per-game batting stats, which include the K (strikeouts)
    field that is critical for the bottom-up strikeout prediction model.

    Bottom-Up Model:
    - Each batter has a K probability
    - Sum of batter K probabilities ≈ Pitcher's expected Ks
    - Compare to pitcher K line for edge detection
    """

    # Flask Mixin Configuration
    scraper_name = "mlb_batter_stats"
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
    GCS_PATH_KEY = "mlb_batter_stats"
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
            "filename": "/tmp/mlb_batter_stats_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
        # Capture modes
        {
            "type": "file",
            "filename": "/tmp/mlb_batter_stats_raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_batter_stats_exp_%(run_id)s.json",
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
        if not self.opts.get("date") and not self.opts.get("dates") and not self.opts.get("game_ids"):
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
            self.opts["date"] = yesterday.isoformat()

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
        logger.debug("MLB Batter Stats URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_MLB_API_KEY") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "mlb-batter-stats-scraper/1.0",
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
                title="MLB Batter Stats - Validation Failed",
                message=f"Data validation failed: {str(e)}",
                details={
                    'scraper': 'mlb_batter_stats',
                    'date': self.opts.get('date'),
                    'error_type': type(e).__name__,
                },
                processor_name="MLB Batter Stats"
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
                        title="MLB Batter Stats - Pagination Failed",
                        message=f"Failed to fetch page {pages_fetched + 1}: {str(e)}",
                        details={
                            'scraper': 'mlb_batter_stats',
                            'pages_fetched': pages_fetched,
                            'rows_so_far': len(all_stats),
                        },
                        processor_name="MLB Batter Stats"
                    )
                    raise

            # Filter to only batter stats (have batting fields, NOT pitching fields)
            batter_stats = [
                stat for stat in all_stats
                if self._is_batter_stat(stat)
            ]

            # Sort by game_id, then player_id
            batter_stats.sort(key=lambda r: (
                r.get("game", {}).get("id", 0),
                r.get("player", {}).get("id", 0)
            ))

            # Extract key strikeout data for easy access (critical for bottom-up model)
            for stat in batter_stats:
                stat["_strikeouts"] = stat.get("k", 0) or stat.get("strikeouts", 0) or stat.get("so", 0) or 0
                stat["_at_bats"] = stat.get("ab", 0) or stat.get("at_bats", 0) or 0
                stat["_hits"] = stat.get("h", 0) or stat.get("hits", 0) or 0

            self.data = {
                "date": self.opts.get("date", "multiple"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "rowCount": len(batter_stats),
                "totalStatsReturned": len(all_stats),
                "batterStats": batter_stats,
            }

            logger.info(
                "Fetched %d batter stat rows (from %d total) for %s across %d pages",
                len(batter_stats), len(all_stats), self.opts.get("date", "multiple"), pages_fetched
            )

            # Data quality checks
            if len(batter_stats) == 0:
                notify_warning(
                    title="MLB Batter Stats - No Data Found",
                    message=f"No batter stats returned for {self.opts.get('date', 'query')}",
                    details={
                        'scraper': 'mlb_batter_stats',
                        'date': self.opts.get('date'),
                        'total_stats': len(all_stats),
                    }
                )
            else:
                # Calculate summary stats (useful for bottom-up model validation)
                total_ks = sum(s.get("_strikeouts", 0) for s in batter_stats)
                total_abs = sum(s.get("_at_bats", 0) for s in batter_stats)
                k_rate = total_ks / total_abs if total_abs > 0 else 0

                notify_info(
                    title="MLB Batter Stats - Success",
                    message=f"Scraped {len(batter_stats)} batter stat rows",
                    details={
                        'scraper': 'mlb_batter_stats',
                        'date': self.opts.get('date'),
                        'batter_count': len(batter_stats),
                        'total_strikeouts': total_ks,
                        'total_at_bats': total_abs,
                        'k_rate': round(k_rate, 3),
                    }
                )

        except Exception as e:
            notify_error(
                title="MLB Batter Stats - Transform Failed",
                message=f"Data transformation failed: {str(e)}",
                details={
                    'scraper': 'mlb_batter_stats',
                    'date': self.opts.get('date'),
                    'error_type': type(e).__name__,
                },
                processor_name="MLB Batter Stats"
            )
            raise

    def _is_batter_stat(self, stat: Dict[str, Any]) -> bool:
        """
        Check if a stat record is for a batter (has batting fields, NOT pitching fields).

        Batting fields include: ab (at bats), h (hits), k/so (strikeouts),
        bb (walks), hr (home runs), rbi, r (runs), etc.

        We exclude records that have significant pitching fields (ip, er, pitch_count).
        """
        # First check for pitching-specific fields that indicate this is a pitcher stat
        # If these have meaningful values, exclude this record
        pitching_fields = ['ip', 'er', 'pitch_count']
        for field in pitching_fields:
            value = stat.get(field)
            if value is not None and value != 0:
                return False

        # Check for batting-specific fields
        batting_fields = ['ab', 'h', 'rbi', 'r', 'hr', '2b', '3b', 'sb']

        for field in batting_fields:
            value = stat.get(field)
            if value is not None and value != 0:
                return True

        # Also check at_bats (alternate field name)
        if stat.get('at_bats') and stat.get('at_bats') != 0:
            return True

        # Check player position if available (exclude pitchers)
        player = stat.get("player", {})
        position = player.get("position", "").lower()

        # Exclude pitcher positions
        if "pitcher" in position or position in ["sp", "rp", "cp", "p"]:
            return False

        # Include common batting positions
        batting_positions = ['c', 'catcher', '1b', '2b', '3b', 'ss', 'lf', 'cf', 'rf',
                            'of', 'dh', 'inf', 'if', 'outfield', 'infield', 'designated']
        for bp in batting_positions:
            if bp in position:
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
create_app = convert_existing_flask_scraper(MlbBatterStatsScraper)

if __name__ == "__main__":
    main = MlbBatterStatsScraper.create_cli_and_flask_main()
    main()

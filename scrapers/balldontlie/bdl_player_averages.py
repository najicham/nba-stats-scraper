"""
BALLDONTLIE - Player Averages endpoint                       v2.1 (2025-06-25)
------------------------------------------------------------------------------
Per-player season averages from:

    https://api.balldontlie.io/v1/season_averages/<category>

All route/query parameters from the public docs are supported.

Usage examples:
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py bdl_player_averages \
      --playerIds 237,115,140 --season 2024 \
      --debug

  # Direct CLI execution:
  python scrapers/balldontlie/bdl_player_averages.py --playerIds 237,115,140 --season 2024 --debug

  # Flask web service:
  python scrapers/balldontlie/bdl_player_averages.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlencode

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.balldontlie.bdl_player_averages
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import (
        NoHttpStatusCodeException,
        InvalidHttpStatusCodeException,
    )
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/balldontlie/bdl_player_averages.py
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
# Constants / helpers                                                         #
# --------------------------------------------------------------------------- #
_VALID_CATEGORIES = {"general", "clutch", "defense", "shooting"}
_VALID_SEASON_TYPES = {"regular", "playoffs", "ist", "playin"}
_VALID_TYPES = {
    "advanced",
    "base",
    "misc",
    "scoring",
    "usage",
    "2_pointers",
    "3_pointers",
    "greater_than_15ft",
    "less_than_10ft",
    "less_than_6ft",
    "overall",
    "by_zone",
    "5ft_range",
}
_CHUNK_SIZE = 100  # BallDontLie hard limit per request


def _current_nba_season() -> int:
    today = datetime.now(timezone.utc)
    return today.year if today.month >= 9 else today.year - 1


def _split(raw: Optional[str]) -> List[str]:
    """Return a list, handling None and empty strings gracefully."""
    if not raw:
        return []
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def _qs(d: Dict[str, object]) -> str:
    """urlencode helper that keeps [] in array params."""
    return urlencode(d, doseq=True, safe="[]")


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class BdlPlayerAveragesScraper(ScraperBase, ScraperFlaskMixin):
    """Scraper for /season_averages/<category> with full filter support."""

    # Flask Mixin Configuration
    scraper_name = "bdl_player_averages"
    required_params = []  # All parameters are optional
    optional_params = {
        "playerIds": None,      # comma separated
        "gameIds": None,        # comma separated
        "dates": None,          # comma separated
        "seasons": None,        # comma separated
        "postseason": None,     # boolean flag
        "startDate": None,      # YYYY-MM-DD
        "endDate": None,        # YYYY-MM-DD
        "season": None,         # single int (defaults to current)
        "category": "general",  # general|clutch|defense|shooting
        "seasonType": "regular", # regular|playoffs|ist|playin
        "type": "base",         # stat grouping type
        "api_key": None,         # Falls back to env var
    }

    # Original scraper config
    required_opts: List[str] = []  # all parameters optional
    download_type = DownloadType.JSON
    decode_download_data = True
    no_retry_status_codes = ScraperBase.no_retry_status_codes + [503]
    proxy_enabled: bool = False

    # ------------------------------------------------------------------ #
    # Retry: exclude 503 so we fail fast with context                    #
    # ------------------------------------------------------------------ #
    def get_retry_strategy(self):
        from urllib3.util.retry import Retry

        return Retry(
            total=self.max_retries_http,
            status_forcelist=[429, 500, 502, 504],
            allowed_methods=["GET"],
            backoff_factor=3,
        )

    def check_download_status(self):
        sc = getattr(self.raw_response, "status_code", None)
        if sc is None:
            raise NoHttpStatusCodeException("No status_code on response")

        if sc == 503:
            msg = ""
            if self.raw_response.headers.get("Content-Type", "").startswith(
                "application/json"
            ):
                try:
                    msg = self.raw_response.json().get("message", "")
                except ValueError:
                    pass
            raise InvalidHttpStatusCodeException(
                f"503 Service Unavailable - {msg or 'see BallDontLie docs'}"
            )

        super().check_download_status()

    # ------------------------------------------------------------------ #
    # Exporters                                                          #
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "bdl_player_averages"
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
            "filename": "/tmp/bdl_player_averages_%(ident)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "capture"],
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
    # Option derivation                                                  #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        # 1. required route & query params with defaults
        self.opts["category"] = (self.opts.get("category") or "general").lower()
        if self.opts["category"] not in _VALID_CATEGORIES:
            raise ValueError(f"Invalid category '{self.opts['category']}'")

        self.opts["seasonType"] = (
            self.opts.get("seasonType") or "regular"
        ).lower()
        if self.opts["seasonType"] not in _VALID_SEASON_TYPES:
            raise ValueError(f"Invalid season_type '{self.opts['seasonType']}'")

        self.opts["statType"] = (self.opts.get("type") or "base").lower()
        if self.opts["statType"] not in _VALID_TYPES:
            raise ValueError(f"Invalid type '{self.opts['statType']}'")

        # 2. season / arrays
        if self.opts.get("season"):
            self.opts["season"] = int(self.opts["season"])
        else:
            self.opts["season"] = _current_nba_season()

        self._player_ids = [int(x) for x in _split(self.opts.get("playerIds"))]
        # do NOT raise if empty; league-wide queries are allowed

        # treat comma lists for other array params
        self._game_ids = [int(x) for x in _split(self.opts.get("gameIds"))]
        self._dates = _split(self.opts.get("dates"))
        self._seasons_multi = [int(x) for x in _split(self.opts.get("seasons"))]

        # 3. chunk player IDs <=100 each
        if self._player_ids:
            self._id_chunks: List[List[int]] = [
                self._player_ids[i : i + _CHUNK_SIZE]
                for i in range(0, len(self._player_ids), _CHUNK_SIZE)
            ]
        else:
            self._id_chunks = [[]]  # single request, no IDs

        self._chunk_iter = iter(self._id_chunks)

        # 4. identify run
        sample_ids = ",".join(map(str, self._player_ids[:3])) or "league"
        suffix = "etc" if len(self._player_ids) > 3 else ""
        self.opts["ident"] = (
            f"{self.opts['season']}_{self.opts['category']}_"
            f"{self.opts['seasonType']}_{self.opts['statType']}_"
            f"{len(self._player_ids)}p_{sample_ids}{suffix}"
        )

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_BASE = "https://api.balldontlie.io/v1/season_averages"

    def _build_url(self, player_ids: List[int]) -> str:
        qs: Dict[str, object] = {
            "season_type": self.opts["seasonType"],
            "type": self.opts["statType"],
        }

        # season (single) or seasons[] (array)
        if self.opts.get("season") is not None:
            qs["season"] = self.opts["season"]
        for s in self._seasons_multi:
            qs.setdefault("seasons[]", []).append(s)

        # arrays from opts
        for gid in self._game_ids:
            qs.setdefault("game_ids[]", []).append(gid)
        for dt in self._dates:
            qs.setdefault("dates[]", []).append(dt)

        # start / end dates
        if self.opts.get("startDate"):
            qs["start_date"] = self.opts["startDate"]
        if self.opts.get("endDate"):
            qs["end_date"] = self.opts["endDate"]

        # postseason flag
        if self.opts.get("postseason") is not None:
            qs["postseason"] = str(self.opts["postseason"]).lower()

        # player IDs for this chunk
        for pid in player_ids:
            qs.setdefault("player_ids[]", []).append(pid)

        return f"{self._API_BASE}/{self.opts['category']}?{_qs(qs)}"

    def set_url(self) -> None:
        first_chunk = next(self._chunk_iter)
        self.base_url = f"{self._API_BASE}/{self.opts['category']}"
        self.url = self._build_url(first_chunk)
        logger.debug(
            "Player-averages URL (chunk 1/%d): %s",
            len(self._id_chunks),
            self.url,
        )

    def set_headers(self) -> None:
        api_key = self.opts.get("api_key") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-player-avg/2.1",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Player-averages response missing 'data' key")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        rows: List[Dict[str, object]] = list(self.decoded_data["data"])

        chunk_idx = 1
        for ids in self._chunk_iter:
            chunk_idx += 1
            resp = self.http_downloader.get(
                self._build_url(ids), headers=self.headers, timeout=self.timeout_http
            )
            resp.raise_for_status()
            rows.extend(resp.json().get("data", []))
            logger.debug(
                "Fetched chunk %d/%d (%d IDs)", chunk_idx, len(self._id_chunks), len(ids)
            )

        rows.sort(key=lambda r: r.get("player_id", 0))

        self.data = {
            "ident": self.opts["ident"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "season": self.opts["season"],
            "category": self.opts["category"],
            "seasonType": self.opts["seasonType"],
            "statType": self.opts["statType"],
            "playerCountRequested": len(self._player_ids),
            "rowCount": len(rows),
            "playerAverages": rows,
        }
        logger.info(
            "Fetched %d rows (%s/%s/%s season %s)",
            len(rows),
            self.opts["category"],
            self.opts["seasonType"],
            self.opts["statType"],
            self.opts["season"],
        )

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> Dict[str, object]:
        return {
            "rowCount": self.data.get("rowCount", 0),
            "ident": self.opts["ident"],
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points (MUCH CLEANER!)
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BdlPlayerAveragesScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BdlPlayerAveragesScraper.create_cli_and_flask_main()
    main()
    
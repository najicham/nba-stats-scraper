"""
BALLDONTLIE - Player Leaders endpoint                   v1.2  2025-06-24
-----------------------------------------------------------------------
Top-N league leaders for a single statistic:

    https://api.balldontlie.io/v1/leaders

Defaults:  statType = "pts",  season = current NBA season
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.cli_utils import add_common_args

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
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class BdlPlayerLeadersScraper(ScraperBase):
    """Scraper for /leaders (top-N players for one stat)."""

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True

    exporters = [
        # Normal artefact
        {
            "type": "file",
            "filename": "/tmp/bdl_player_leaders_%(ident)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
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
        stat_type = (self.opts.get("statType") or "pts").lower()
        if stat_type not in _VALID_STATS:
            raise ValueError(
                f"Invalid statType '{stat_type}'. Allowed: {', '.join(sorted(_VALID_STATS))}"
            )
        self.opts["statType"] = stat_type
        self.opts["season"] = int(self.opts.get("season") or _current_nba_season())
        self.opts["ident"] = f"{self.opts['season']}_{stat_type}"

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
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-player-leaders/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Leaders response malformed: missing 'data' key")

    # ------------------------------------------------------------------ #
    # Transform (cursor-aware)                                           #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        leaders: List[Dict[str, Any]] = list(self.decoded_data["data"])
        cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")

        while cursor:
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

        leaders.sort(key=lambda r: r.get("rank", 999))

        self.data = {
            "ident": self.opts["ident"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rowCount": len(leaders),
            "leaders": leaders,
        }
        logger.info("Fetched %d leader rows for %s", len(leaders), self.opts["ident"])

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {"rowCount": self.data.get("rowCount", 0), "ident": self.opts["ident"]}


# --------------------------------------------------------------------------- #
# Google Cloud Function entry                                                #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    opts = {
        "statType": request.args.get("statType"),
        "season": request.args.get("season"),
        "group": request.args.get("group", "prod"),
        "apiKey": request.args.get("apiKey"),
        "runId": request.args.get("runId"),
    }
    BdlPlayerLeadersScraper().run(opts)
    ident = f"{opts.get('season') or _current_nba_season()}_{opts.get('statType') or 'pts'}"
    return f"BallDontLie player leaders scrape complete ({ident})", 200


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scrape BallDontLie /leaders")
    parser.add_argument("--statType", help="pts, ast, reb, etc. (default pts)")
    parser.add_argument("--season", type=int, help="Season start year, e.g. 2024")
    add_common_args(parser)  # --group --apiKey --runId --debug
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    BdlPlayerLeadersScraper().run(vars(args))

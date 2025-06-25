"""
BALLDONTLIE - Players endpoint                                 v2.0 2025-06-25
------------------------------------------------------------------------------
Fetch player rows from

    https://api.balldontlie.io/v1/players           (default)
    https://api.balldontlie.io/v1/players/active    (--active flag)

Supports every documented query parameter:

    cursor, per_page, search, first_name, last_name,
    team_ids[], player_ids[]

Examples
--------
# Entire catalogue (≈4,500 rows)
python -m scrapers.balldontlie.bdl_players

# Active Celtics players, 50 per page
python -m scrapers.balldontlie.bdl_players --active \
       --teamIds 2 --perPage 50

# 1) Entire catalogue (default /players)
python tools/fixtures/capture.py bdl_players --debug

# 2) Active Thunder players
python tools/fixtures/capture.py bdl_players --debug --active --teamIds 21

# 3) Name search
python tools/fixtures/capture.py bdl_players --debug --search james --perPage 50

"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlencode

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.cli_utils import add_common_args

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class BdlPlayersScraper(ScraperBase):
    """Scraper for /players and /players/active with full filter support."""

    download_type = DownloadType.JSON
    decode_download_data = True
    required_opts: List[str] = []

    # ---------------- exporters ------------------
    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_players_%(ident)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        # capture artefacts
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
    # Helpers for query params                                           #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _split(raw: str | None) -> List[str]:
        return [s.strip() for s in str(raw).split(",") if s.strip()] if raw else []

    @staticmethod
    def _qs(d: Dict[str, object]) -> str:
        """urlencode but keep [] for array parameters."""
        return urlencode(d, doseq=True, safe="[]")

    # ------------------------------------------------------------------ #
    # set_additional_opts                                                #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        # Default perPage = 100, cap at 100
        per_page = int(self.opts.get("perPage") or 100)
        self.opts["perPage"] = min(max(per_page, 1), 100)

        # Build ident for filenames / logs
        parts: List[str] = []
        if self.opts.get("active"):
            parts.append("active")
        if self.opts.get("playerIds"):
            parts.append(f"pids_{len(self._split(self.opts['playerIds']))}")
        if self.opts.get("teamIds"):
            parts.append(f"tids_{len(self._split(self.opts['teamIds']))}")
        if self.opts.get("search"):
            parts.append(f"search_{self.opts['search']}")
        if not parts:
            parts.append(datetime.now(timezone.utc).date().isoformat())

        self.opts["ident"] = "_".join(parts)

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/players"
    _API_ACTIVE = "https://api.balldontlie.io/v1/players/active"

    def _build_params(self, extra: Dict[str, object] | None = None) -> Dict[str, object]:
        q: Dict[str, object] = {"per_page": self.opts["perPage"]}

        simple_map = {
            "cursor": "cursor",
            "search": "search",
            "firstName": "first_name",
            "lastName": "last_name",
        }
        for opt_key, api_key in simple_map.items():
            if self.opts.get(opt_key):
                q[api_key] = self.opts[opt_key]

        # array params
        array_map = {
            "teamIds": "team_ids[]",
            "playerIds": "player_ids[]",
        }
        for opt_key, api_key in array_map.items():
            for val in self._split(self.opts.get(opt_key)):
                q.setdefault(api_key, []).append(val)

        if extra:
            q.update(extra)
        return q

    def set_url(self) -> None:
        self.base_url = self._API_ACTIVE if self.opts.get("active") else self._API_ROOT
        self.url = f"{self.base_url}?{self._qs(self._build_params())}"
        logger.debug("Players URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-players/2.0 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Players response malformed: missing 'data' key")

    # ------------------------------------------------------------------ #
    # Transform (cursor walk)                                            #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        players: List[Dict[str, object]] = list(self.decoded_data["data"])
        cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")

        while cursor:
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params=self._build_params({"cursor": cursor}),
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            js = resp.json()
            players.extend(js.get("data", []))
            cursor = js.get("meta", {}).get("next_cursor")

        players.sort(key=lambda p: p.get("id", 0))

        self.data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "playerCount": len(players),
            "players": players,
        }
        logger.info("Fetched %d players (%s)", len(players), self.opts["ident"])

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> Dict[str, object]:
        return {"playerCount": self.data.get("playerCount", 0), "ident": self.opts["ident"]}


# --------------------------------------------------------------------------- #
# Google Cloud Function entry                                                #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    opts = {
        "cursor": request.args.get("cursor"),
        "perPage": request.args.get("perPage"),
        "search": request.args.get("search"),
        "firstName": request.args.get("first_name"),
        "lastName": request.args.get("last_name"),
        "teamIds": request.args.get("team_ids"),
        "playerIds": request.args.get("player_ids"),
        "active": request.args.get("active"),  # truthy string triggers /active
        "group": request.args.get("group", "prod"),
        "apiKey": request.args.get("apiKey"),
        "runId": request.args.get("runId"),
    }
    BdlPlayersScraper().run(opts)
    return "BallDontLie players scrape complete", 200


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scrape BallDontLie /players")
    parser.add_argument("--active", action="store_true", help="Use /players/active")
    parser.add_argument("--cursor", help="Cursor for pagination")
    parser.add_argument("--perPage", type=int, help="Items per page (1-100, default 100)")
    parser.add_argument("--search", help="Free-text search across first & last name")
    parser.add_argument("--firstName", help="Exact match on first name")
    parser.add_argument("--lastName", help="Exact match on last name")
    parser.add_argument("--teamIds", help="Comma list of team IDs")
    parser.add_argument("--playerIds", help="Comma list of player IDs")
    add_common_args(parser)  # --group --apiKey --runId --debug
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    BdlPlayersScraper().run(vars(args))

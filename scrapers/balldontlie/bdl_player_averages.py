"""
BALLDONTLIE - Player Averages endpoint                       v2.1 (2025-06-25)
------------------------------------------------------------------------------
Per-player season averages from:

    https://api.balldontlie.io/v1/season_averages/<category>

All route/query parameters from the public docs are supported.

python tools/fixtures/capture.py bdl_player_averages --group capture --debug \
       --playerIds 237,115,140 --season 2024

"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlencode

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import (
    NoHttpStatusCodeException,
    InvalidHttpStatusCodeException,
)

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
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class BdlPlayerAveragesScraper(ScraperBase):
    """Scraper for /season_averages/<category> with full filter support."""

    required_opts: List[str] = []  # all parameters optional
    download_type = DownloadType.JSON
    decode_download_data = True
    no_retry_status_codes = ScraperBase.no_retry_status_codes + [503]

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
                f"503 Service Unavailable – {msg or 'see BallDontLie docs'}"
            )

        super().check_download_status()

    # ------------------------------------------------------------------ #
    # Exporters                                                          #
    # ------------------------------------------------------------------ #
    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_player_averages_%(ident)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod", "capture"],
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
        # do NOT raise if empty; league‑wide queries are allowed

        # treat comma lists for other array params
        self._game_ids = [int(x) for x in _split(self.opts.get("gameIds"))]
        self._dates = _split(self.opts.get("dates"))
        self._seasons_multi = [int(x) for x in _split(self.opts.get("seasons"))]

        # 3. chunk player IDs ≤100 each
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
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
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
# Google Cloud Function entry                                                #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    opts = {
        "playerIds": request.args.get("playerIds"),
        "gameIds": request.args.get("gameIds"),
        "dates": request.args.get("dates"),
        "seasons": request.args.get("seasons"),
        "postseason": request.args.get("postseason"),
        "startDate": request.args.get("start_date"),
        "endDate": request.args.get("end_date"),
        "season": request.args.get("season"),
        "category": request.args.get("category"),
        "seasonType": request.args.get("season_type"),
        "type": request.args.get("type"),
        "apiKey": request.args.get("apiKey"),
        "group": request.args.get("group", "prod"),
        "runId": request.args.get("runId"),
    }
    BdlPlayerAveragesScraper().run(opts)
    return "BallDontLie player-averages scrape complete", 200


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from scrapers.utils.cli_utils import add_common_args

    cli = argparse.ArgumentParser(
        description="Scrape BallDontLie /season_averages/<category>"
    )
    cli.add_argument("--playerIds", help="Comma list of player IDs")
    cli.add_argument("--gameIds", help="Comma list of game IDs")
    cli.add_argument("--dates", help="Comma list of YYYY-MM-DD values")
    cli.add_argument("--seasons", help="Comma list of season start years")
    cli.add_argument("--postseason", choices=["true", "false"])
    cli.add_argument("--startDate", help="YYYY-MM-DD (on/after)")
    cli.add_argument("--endDate", help="YYYY-MM-DD (on/before)")
    cli.add_argument("--season", type=int, help="Season start year (default current)")
    cli.add_argument(
        "--category",
        choices=sorted(_VALID_CATEGORIES),
        default="general",
        help="general|clutch|defense|shooting",
    )
    cli.add_argument(
        "--seasonType",
        choices=sorted(_VALID_SEASON_TYPES),
        default="regular",
        help="regular|playoffs|ist|playin",
    )
    cli.add_argument(
        "--type",
        choices=sorted(_VALID_TYPES),
        default="base",
        help="Stat grouping - see docs",
    )
    add_common_args(cli)  # --group --apiKey --runId --debug
    args = cli.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    BdlPlayerAveragesScraper().run(vars(args))

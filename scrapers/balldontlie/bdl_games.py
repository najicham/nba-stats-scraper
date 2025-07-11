"""
BALLDONTLIE – Games endpoint                                  v1.2 • 2025‑06‑24
-------------------------------------------------------------------------------
Fetches every NBA game between **startDate** and **endDate** (inclusive).

    /games?start_date=YYYY‑MM‑DD&end_date=YYYY‑MM‑DD

The endpoint is cursor‑paginated.  We grab the first page through
ScraperBase’s normal downloader, then—inside **transform_data()**—walk any
`next_cursor` links with the **same requests.Session** (self.http_downloader)
so we inherit proxy / retry / header behaviour.

Typical page size is ≤ 15 games, so extra pages are rare today but the loop is
future‑proof.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.cli_utils import add_common_args

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Small helper – date coercion                                                #
# --------------------------------------------------------------------------- #
def _coerce_date(val: str | _dt.date | None, default: _dt.date) -> _dt.date:
    if val is None:
        return default
    if isinstance(val, _dt.date):
        return val
    return _dt.datetime.strptime(str(val), "%Y-%m-%d").date()


# --------------------------------------------------------------------------- #
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class BdlGamesScraper(ScraperBase):
    """Fetch game rows, follow cursor pagination, merge pages."""

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True

    exporters = [
        # Normal artifact (pretty JSON after full transform)
        {
            "type": "file",
            "filename": "/tmp/bdl_games_%(startDate)s_%(endDate)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
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
    # Option derivation                                                  #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        today_utc = _dt.datetime.now(_dt.timezone.utc).date()
        self.opts["startDate"] = _coerce_date(
            self.opts.get("startDate"), default=today_utc - _dt.timedelta(days=1)
        ).isoformat()
        self.opts["endDate"] = _coerce_date(
            self.opts.get("endDate"), default=today_utc + _dt.timedelta(days=1)
        ).isoformat()

    # ------------------------------------------------------------------ #
    # HTTP setup                                                         #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/games"

    def set_url(self) -> None:
        params = {
            "start_date": self.opts["startDate"],
            "end_date": self.opts["endDate"],
            "per_page": 100,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        self.base_url = self._API_ROOT
        self.url = f"{self.base_url}?{query}"
        logger.debug("Games URL: %s", self.url)

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-games/1.1 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Games response malformed: no 'data' key")

    # ------------------------------------------------------------------ #
    # Transform (cursor walk + packaging)                                #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        games: List[Dict[str, Any]] = list(self.decoded_data["data"])
        cursor: Optional[str] = self.decoded_data.get("meta", {}).get("next_cursor")

        base_params = {
            "start_date": self.opts["startDate"],
            "end_date": self.opts["endDate"],
            "per_page": 100,
        }

        while cursor:
            base_params["cursor"] = cursor
            r = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params=base_params,
                timeout=self.timeout_http,
            )
            r.raise_for_status()
            j = r.json()
            games.extend(j.get("data", []))
            cursor = j.get("meta", {}).get("next_cursor")

        games.sort(key=lambda g: g.get("id", 0))

        self.data = {
            "startDate": self.opts["startDate"],
            "endDate": self.opts["endDate"],
            "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "gameCount": len(games),
            "games": games,
        }
        logger.info(
            "Fetched %d games (%s → %s)",
            len(games),
            self.opts["startDate"],
            self.opts["endDate"],
        )

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:  # noqa: D401
        return {
            "startDate": self.opts["startDate"],
            "endDate": self.opts["endDate"],
            "gameCount": self.data.get("gameCount", 0),
        }


# --------------------------------------------------------------------------- #
# Google Cloud Function entry                                                #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    opts = {
        "startDate": request.args.get("startDate"),
        "endDate": request.args.get("endDate"),
        "apiKey": request.args.get("apiKey"),
        "group": request.args.get("group", "prod"),
        "runId": request.args.get("runId"),
    }
    BdlGamesScraper().run(opts)
    return (
        f"BallDontLie games scrape complete ({opts.get('startDate')} → {opts.get('endDate')})",
        200,
    )


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scrape BallDontLie /games")
    parser.add_argument("--startDate", help="YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--endDate", help="YYYY-MM-DD (default: tomorrow)")
    add_common_args(parser)  # --group --apiKey --runId --debug
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    BdlGamesScraper().run(vars(args))

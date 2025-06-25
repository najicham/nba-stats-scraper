"""
BALLDONTLIE - Player Box Scores (stats endpoint)           v1.3 (2025-06-24)
------------------------------------------------------------------------------
Collect per-player box‑score rows from

    https://api.balldontlie.io/v1/stats

Supported query parameters (full parity with BDL docs)
------------------------------------------------------
--startDate / --endDate    inclusive YYYY-MM-DD window
--gameIds                  comma list   e.g. 486435,486436
--playerIds                comma list
--teamIds                  comma list
--seasons                  comma list (season start years)
--postSeason               flag (playoff games only)
--perPage                  1-100 (default 100)

If any ID/season filter is supplied we make a single request.
Otherwise we iterate date-by-date across the window.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.cli_utils import add_common_args

logger = logging.getLogger("scraper_base")

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _coerce_date(val: str | date | None, default: date) -> date:
    if val is None:
        return default
    if isinstance(val, date):
        return val
    return datetime.strptime(str(val), "%Y-%m-%d").date()


def _split(raw: str | None) -> List[str]:
    return [p.strip() for p in str(raw).split(",") if p.strip()] if raw else []


# --------------------------------------------------------------------------- #
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class BdlPlayerBoxScoresScraper(ScraperBase):
    """Cursor scraper for /stats, returns player box‑score rows."""

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_player_box_scores_%(startDate)s_%(endDate)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        # capture artefacts (raw + decoded) keyed by run_id
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
        today = datetime.now(timezone.utc).date()
        self.opts["startDate"] = _coerce_date(
            self.opts.get("startDate"), today - timedelta(days=1)
        ).isoformat()
        self.opts["endDate"] = _coerce_date(
            self.opts.get("endDate"), today + timedelta(days=1)
        ).isoformat()

        for key in ("gameIds", "playerIds", "teamIds", "seasons"):
            self.opts[key] = self.opts.get(key, "")

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/stats"

    def _build_query(self, extra: dict | None = None) -> Dict[str, Any]:
        q: Dict[str, Any] = {"per_page": int(self.opts.get("perPage") or 100)}

        mapping = {
            "gameIds": "game_ids[]",
            "playerIds": "player_ids[]",
            "teamIds": "team_ids[]",
            "seasons": "seasons[]",
        }
        for opt_key, api_key in mapping.items():
            for val in _split(self.opts.get(opt_key)):
                q.setdefault(api_key, []).append(val)

        if self.opts.get("postSeason"):
            q["postseason"] = "true"

        if extra:
            q.update(extra)
        return q

    @staticmethod
    def _qs(params: Dict[str, Any]) -> str:
        """urlencode but keep [] unescaped (doseq handles lists)."""
        return urlencode(params, doseq=True, safe="[]")

    def set_url(self) -> None:
        filter_fields = (
            "gameIds",
            "playerIds",
            "teamIds",
            "seasons",
            "postSeason",
        )
        self.base_url = self._API_ROOT

        # Filter mode
        if any(self.opts.get(f) for f in filter_fields):
            self.url = f"{self.base_url}?{self._qs(self._build_query())}"
            self._date_iter = iter([])  # skip date loop
            logger.info("Player box-scores URL with filters: %s", self.url)
            return

        # Date-window mode
        self._date_iter = self._build_date_iter()
        first_date = next(self._date_iter)
        self.url = f"{self.base_url}?{self._qs(self._build_query({'dates[]': first_date}))}"
        logger.info("Player box-scores URL (date mode first page): %s", self.url)

    def _build_date_iter(self):
        start = datetime.strptime(self.opts["startDate"], "%Y-%m-%d").date()
        end = datetime.strptime(self.opts["endDate"], "%Y-%m-%d").date()
        d = start
        while d <= end:
            yield d.isoformat()
            d += timedelta(days=1)

    def set_headers(self) -> None:
        api_key = os.getenv("BDL_API_KEY")
        if not api_key:
            raise RuntimeError("Environment variable BDL_API_KEY not set")
        self.headers = {
            "Authorization": api_key,
            "User-Agent": "scrape-bdl-player-box-scores/1.0",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Stats response malformed: missing 'data' key")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        rows: List[Dict[str, Any]] = []
        dates_done: List[str] = []

        def add_page(js: Dict[str, Any]) -> Optional[str]:
            rows.extend(js.get("data", []))
            return js.get("meta", {}).get("next_cursor")

        # first response
        next_cursor = add_page(self.decoded_data)
        date_param = (
            self.decoded_data.get("meta", {}).get("request_params", {}).get("dates[]")
        )
        if date_param:
            dates_done.append(date_param)

        while next_cursor:
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params=self._build_query({"cursor": next_cursor}),
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            next_cursor = add_page(resp.json())

        for dt in self._date_iter:
            dates_done.append(dt)
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params=self._build_query({"dates[]": dt}),
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            next_cursor = add_page(resp.json())

            while next_cursor:
                resp = self.http_downloader.get(
                    self.base_url,
                    headers=self.headers,
                    params=self._build_query({"cursor": next_cursor}),
                    timeout=self.timeout_http,
                )
                resp.raise_for_status()
                next_cursor = add_page(resp.json())

        rows.sort(key=lambda r: (r.get("game", {}).get("id"), r.get("player_id")))

        self.data = {
            "startDate": self.opts["startDate"],
            "endDate": self.opts["endDate"],
            "datesProcessed": dates_done,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rowCount": len(rows),
            "stats": rows,
        }
        logger.info(
            "Fetched %d player box-score rows across %d dates (%s -> %s)",
            len(rows),
            len(dates_done),
            self.opts["startDate"],
            self.opts["endDate"],
        )

    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0),
            "startDate": self.opts["startDate"],
            "endDate": self.opts["endDate"],
        }


# --------------------------------------------------------------------------- #
# Google Cloud Function entry                                                #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    opts = {
        "startDate": request.args.get("startDate"),
        "endDate": request.args.get("endDate"),
        "gameIds": request.args.get("gameIds"),
        "playerIds": request.args.get("playerIds"),
        "teamIds": request.args.get("teamIds"),
        "seasons": request.args.get("seasons"),
        "postSeason": request.args.get("postSeason"),
        "perPage": request.args.get("perPage"),
        "group": request.args.get("group", "prod"),
    }
    BdlPlayerBoxScoresScraper().run(opts)
    return (
        f"BallDontLie player box-scores scrape complete "
        f"({opts.get('startDate')} -> {opts.get('endDate')})",
        200,
    )


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Scrape BallDontLie /stats (player box-scores)"
    )
    parser.add_argument("--startDate", help="YYYY-MM-DD")
    parser.add_argument("--endDate", help="YYYY-MM-DD")
    parser.add_argument("--gameIds", help="comma list")
    parser.add_argument("--playerIds", help="comma list")
    parser.add_argument("--teamIds", help="comma list")
    parser.add_argument("--seasons", help="comma list of season start years")
    parser.add_argument(
        "--postSeason", action="store_true", help="playoff games only"
    )
    parser.add_argument("--perPage", type=int, help="1-100 (default 100)")
    add_common_args(parser)  # --group --apiKey --runId --debug
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    BdlPlayerBoxScoresScraper().run(vars(args))

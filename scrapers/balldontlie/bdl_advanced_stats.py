"""
BALLDONTLIE ‑ Advanced‑Stats endpoint                    v1 – 2025‑06‑22
-----------------------------------------------------------------------------
Per‑player advanced box scores from

    https://api.balldontlie.io/v1/stats/advanced

This endpoint mirrors `/stats` but includes additional fields such as
`ts_pct`, `usg_pct`, `off_rtg`, etc.

### Parameters
* `startDate` / `endDate` – inclusive YYYY‑MM‑DD window  
  (defaults: yesterday → tomorrow).

Implementation details are identical to **BdlGameStatsScraper**: we iterate
one calendar day at a time and walk the cursor for each day so memory remains
flat even if the query spans multiple days.

CLI
---
    python -m scrapers.bdl.bdl_advanced_stats_scraper \
        --startDate 2025-06-20 --endDate 2025-06-22
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")

# --------------------------------------------------------------------------- #
# Helper – date coercion                                                      #
# --------------------------------------------------------------------------- #
def _coerce_date(val: str | date | None, default: date) -> date:
    if val is None:
        return default
    if isinstance(val, date):
        return val
    return datetime.strptime(str(val), "%Y-%m-%d").date()


class BdlAdvancedStatsScraper(ScraperBase):
    """
    Cursor‑based scraper for /stats/advanced.
    """

    # ------------------------------------------------------------------ #
    # Config                                                             #
    # ------------------------------------------------------------------ #
    required_opts: List[str] = []
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_adv_stats_%(startDate)s_%(endDate)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_adv_stats_%(startDate)s_%(endDate)s.json",
            "export_mode": ExportMode.RAW,
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

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/stats/advanced"

    def set_url(self) -> None:
        # We prime the first request with the first date in window
        self.base_url = self._API_ROOT
        self._date_iter = self._gen_dates()
        first_date = next(self._date_iter)
        self.url = f"{self.base_url}?per_page=100&dates[]={first_date}"
        logger.info("Resolved BALLDONTLIE advanced‑stats URL (first page): %s", self.url)

    def _gen_dates(self):
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
            "User-Agent": "Mozilla/5.0 (compatible; scrape-bdl/1.0)",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict):
            raise ValueError("Advanced‑stats response is not JSON object")
        if "data" not in self.decoded_data:
            raise ValueError("'data' field missing in advanced‑stats JSON")

    # ------------------------------------------------------------------ #
    # Transform (multi‑date loop + cursor walk)                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        rows: List[Dict[str, Any]] = []
        dates_done: List[str] = []

        def _add_page(js: Dict[str, Any]) -> Optional[str]:
            rows.extend(js.get("data", []))
            return js.get("meta", {}).get("next_cursor")

        # ---------- first response already downloaded ----------
        next_cursor = _add_page(self.decoded_data)
        current_date_param = self.decoded_data.get("meta", {}).get("request_params", {}).get("dates[]")
        if current_date_param:
            dates_done.append(current_date_param)

        while next_cursor:
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params={"cursor": next_cursor, "per_page": 100},
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            next_cursor = _add_page(resp.json())

        # ---------- remaining dates in window ------------------
        for dt in self._date_iter:
            dates_done.append(dt)
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params={"per_page": 100, "dates[]": dt},
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            next_cursor = _add_page(resp.json())

            while next_cursor:
                resp = self.http_downloader.get(
                    self.base_url,
                    headers=self.headers,
                    params={"cursor": next_cursor, "per_page": 100},
                    timeout=self.timeout_http,
                )
                resp.raise_for_status()
                next_cursor = _add_page(resp.json())

        # Deterministic order: gameId then playerId
        rows.sort(key=lambda r: (r.get("game", {}).get("id"), r.get("player_id")))

        self.data = {
            "startDate": self.opts["startDate"],
            "endDate": self.opts["endDate"],
            "datesProcessed": dates_done,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rowCount": len(rows),
            "advancedStats": rows,
        }
        logger.info(
            "Fetched %d advanced‑stat rows across %d dates (%s → %s)",
            len(rows),
            len(dates_done),
            self.opts["startDate"],
            self.opts["endDate"],
        )

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0),
            "startDate": self.opts["startDate"],
            "endDate": self.opts["endDate"],
        }


# ---------------------------------------------------------------------- #
# Google Cloud Function entry point                                      #
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    start_date = request.args.get("startDate")
    end_date = request.args.get("endDate")
    group = request.args.get("group", "prod")
    opts = {"startDate": start_date, "endDate": end_date, "group": group}
    BdlAdvancedStatsScraper().run(opts)
    return (
        f"BALLDONTLIE advanced‑stats scrape complete ({start_date} → {end_date})",
        200,
    )


# ---------------------------------------------------------------------- #
# CLI usage                                                              #
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--startDate", help="YYYY‑MM‑DD")
    cli.add_argument("--endDate", help="YYYY‑MM‑DD")
    cli.add_argument("--group", default="test")
    BdlAdvancedStatsScraper().run(vars(cli.parse_args()))

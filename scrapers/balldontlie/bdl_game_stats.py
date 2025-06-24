"""
BALLDONTLIE ‑ Stats endpoint (player box‑scores)         v1 – 2025‑06‑22
-----------------------------------------------------------------------------
Collects *per‑player* box‑score rows from

    https://api.balldontlie.io/v1/stats

### Parameters handled
* `startDate` / `endDate` – inclusive YYYY‑MM‑DD window  
  (default: yesterday → tomorrow).
* Internally loops one day at a time so memory stays flat even if you hit
  a multi‑day range such as All‑Star break + catch‑ups.

Typical volume:
    • Regular‑season day  → ~300 rows
    • Busy playoff day    → ~450 rows

CLI
---
    python -m scrapers.bdl.bdl_game_stats_scraper \
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
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _coerce_date(val: str | date | None, default: date) -> date:
    if val is None:
        return default
    if isinstance(val, date):
        return val
    return datetime.strptime(str(val), "%Y-%m-%d").date()


class BdlGameStatsScraper(ScraperBase):
    """
    High‑volume cursor scraper for /stats.
    """

    # ------------------------------------------------------------------ #
    # Class‑level config                                                 #
    # ------------------------------------------------------------------ #
    required_opts: List[str] = []
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_stats_%(startDate)s_%(endDate)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_stats_%(startDate)s_%(endDate)s.json",
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
    _API_ROOT = "https://api.balldontlie.io/v1/stats"

    def set_url(self) -> None:
        # First request = first date of the window
        self.base_url = self._API_ROOT
        self._date_iter = self._build_date_iter()          # save for transform()
        first_date = next(self._date_iter)                 # prime iterator
        self.url = f"{self.base_url}?per_page=100&dates[]={first_date}"
        logger.info("Resolved BALLDONTLIE stats URL (first page): %s", self.url)

    def _build_date_iter(self):
        """Generator over every date in the (inclusive) window."""
        start = datetime.strptime(self.opts["startDate"], "%Y-%m-%d").date()
        end = datetime.strptime(self.opts["endDate"], "%Y-%m-%d").date()
        curr = start
        while curr <= end:
            yield curr.isoformat()
            curr += timedelta(days=1)

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
            raise ValueError("Stats response is not JSON object")
        if "data" not in self.decoded_data:
            raise ValueError("'data' field missing in stats JSON")

    # ------------------------------------------------------------------ #
    # Transform (multi‑date loop + cursor walk)                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        all_stats: List[Dict[str, Any]] = []
        dates_processed: List[str] = []

        def _grab_page(json_obj: Dict[str, Any]) -> Optional[str]:
            """Extend all_stats and return next_cursor (if any)."""
            all_stats.extend(json_obj.get("data", []))
            return json_obj.get("meta", {}).get("next_cursor")

        # ----------- process the first request already downloaded -------
        next_cursor = _grab_page(self.decoded_data)
        current_date_param = self.decoded_data.get("meta", {}).get("request_params", {}).get("dates[]")
        if current_date_param:
            dates_processed.append(current_date_param)

        # ----------- finish cursor loop for the *same* date ------------
        while next_cursor:
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params={"cursor": next_cursor, "per_page": 100},
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            next_cursor = _grab_page(resp.json())

        # ----------- move to any *additional* dates in window ----------
        for dt in self._date_iter:
            dates_processed.append(dt)
            next_cursor = None
            params = {"per_page": 100, "dates[]": dt}
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params=params,
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            next_cursor = _grab_page(resp.json())

            while next_cursor:
                resp = self.http_downloader.get(
                    self.base_url,
                    headers=self.headers,
                    params={"cursor": next_cursor, "per_page": 100},
                    timeout=self.timeout_http,
                )
                resp.raise_for_status()
                next_cursor = _grab_page(resp.json())

        # Sort deterministically
        all_stats.sort(key=lambda s: (s.get("game", {}).get("id"), s.get("player_id")))

        self.data = {
            "startDate": self.opts["startDate"],
            "endDate": self.opts["endDate"],
            "datesProcessed": dates_processed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rowCount": len(all_stats),
            "stats": all_stats,
        }
        logger.info(
            "Fetched %d stat rows across %d dates (%s → %s)",
            len(all_stats),
            len(dates_processed),
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
    BdlGameStatsScraper().run(opts)
    return (
        f"BALLDONTLIE stats scrape complete ({start_date} → {end_date})",
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
    BdlGameStatsScraper().run(vars(cli.parse_args()))

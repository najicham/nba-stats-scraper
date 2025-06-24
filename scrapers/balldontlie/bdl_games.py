"""
BALLDONTLIE ‑ Games endpoint                                   v1 – 2025‑06‑22
-------------------------------------------------------------------------------
Fetches all NBA games in an arbitrary date window from

    https://api.balldontlie.io/v1/games

The endpoint is cursor‑paginated.  We grab the first page via the standard
ScraperBase download flow, then—*inside `transform_data()`*—loop over any
follow‑up cursors **using the same `requests.Session` that ScraperBase already
created** (`self.http_downloader`).  This keeps proxy, retry, and header logic
centralised.

Typical payload size:
    • Regular‑season day  → ≈ 10‑15 games  → fits in one page (≤ 100)
    • Busy playoff day    → max 15 games  → also one page
So the cursor loop is future‑proof but rarely needed in practice.

CLI
---
    python -m scrapers.bdl.bdl_games_scraper --startDate 2025-06-21 --endDate 2025-06-22
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")

# --------------------------------------------------------------------------- #
# Small helper – date coercion                                                #
# --------------------------------------------------------------------------- #
def _coerce_date(val: str | date | None, default: date) -> date:
    if val is None:
        return default
    if isinstance(val, date):
        return val
    return datetime.strptime(str(val), "%Y-%m-%d").date()


class BdlGamesScraper(ScraperBase):
    """
    Scraper for /games (with optional date filter).
    """

    # ------------------------------------------------------------------ #
    # Class‑level config                                                 #
    # ------------------------------------------------------------------ #
    required_opts: List[str] = []        # dates default automatically
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    # Each child scraper overrides this list as needed.
    exporters = [
        {
            "type": "file",
            "filename": (
                "/tmp/bdl_games_%(startDate)s_%(endDate)s.json"
            ),
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        # Raw API response snapshot — useful for capture tests / fixtures
        {
            "type": "file",
            "filename": "/tmp/raw_games_%(startDate)s_%(endDate)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional option derivation & validation                          #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        """
        Populate default 'startDate' and 'endDate' (YYYY‑MM‑DD) if caller
        did not supply them.
        """
        today_utc = datetime.now(timezone.utc).date()
        self.opts["startDate"] = _coerce_date(
            self.opts.get("startDate"), default=today_utc - timedelta(days=1)
        ).isoformat()
        self.opts["endDate"] = _coerce_date(
            self.opts.get("endDate"), default=today_utc + timedelta(days=1)
        ).isoformat()

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/games"

    def set_url(self) -> None:
        """
        Store the *first‑page* URL in self.url; keep a base_url for the
        cursor loop later.
        """
        params = {
            "start_date": self.opts["startDate"],
            "end_date": self.opts["endDate"],
            "per_page": 100,
        }
        # Save as string; ScraperBase doesn’t expose a helper for this
        query = "&".join(f"{k}={v}" for k, v in params.items())
        self.base_url = self._API_ROOT            # keep for cursor loop
        self.url = f"{self.base_url}?{query}"

        logger.info("Resolved BALLDONTLIE games URL: %s", self.url)

    def set_headers(self) -> None:
        """
        BALLDONTLIE requires an `Authorization` bearer token sent via header.
        """
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
            raise ValueError("Games response is not a JSON object")
        if "data" not in self.decoded_data:
            raise ValueError("'data' field missing in games JSON")

    # ------------------------------------------------------------------ #
    # Transform (cursor walk + packaging)                                #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        """
        Consolidate *all* pages (if any) into one list then attach
        metadata. Uses the already‑configured `self.http_downloader`
        (requests.Session) so we inherit proxy / retry behaviour.
        """
        all_games: List[Dict[str, Any]] = list(self.decoded_data["data"])
        meta: Dict[str, Any] = self.decoded_data.get("meta", {})
        cursor: Optional[str] = meta.get("next_cursor")

        # Preserve original query params for subsequent pages
        base_params = {
            "start_date": self.opts["startDate"],
            "end_date": self.opts["endDate"],
            "per_page": 100,
        }

        while cursor:
            base_params["cursor"] = cursor
            resp = self.http_downloader.get(
                self.base_url,
                headers=self.headers,
                params=base_params,
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            page_json: Dict[str, Any] = resp.json()
            all_games.extend(page_json.get("data", []))
            cursor = page_json.get("meta", {}).get("next_cursor")

        # Optional: sort deterministically by gameId
        all_games.sort(key=lambda g: g.get("id"))

        self.data = {
            "startDate": self.opts["startDate"],
            "endDate": self.opts["endDate"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gameCount": len(all_games),
            "games": all_games,
        }
        logger.info(
            "Fetched %d games (%s → %s)",
            len(all_games),
            self.opts["startDate"],
            self.opts["endDate"],
        )

    # ------------------------------------------------------------------ #
    # Stats for SCRAPER_STATS line                                       #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "startDate": self.opts["startDate"],
            "endDate": self.opts["endDate"],
            "gameCount": self.data.get("gameCount", 0),
        }


# ---------------------------------------------------------------------- #
# Google Cloud Functions entry point (optional)                          #
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    start_date = request.args.get("startDate")     # YYYY‑MM‑DD
    end_date = request.args.get("endDate")         # YYYY‑MM‑DD
    group = request.args.get("group", "prod")

    opts = {"startDate": start_date, "endDate": end_date, "group": group}
    BdlGamesScraper().run(opts)
    return (
        f"BALLDONTLIE games scrape OK ({start_date} → {end_date})",
        200,
    )


# ---------------------------------------------------------------------- #
# CLI usage                                                              #
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--startDate", help="YYYY‑MM‑DD (default: yesterday)")
    cli.add_argument("--endDate", help="YYYY‑MM‑DD (default: tomorrow)")
    cli.add_argument("--group", default="test")
    args = cli.parse_args()

    BdlGamesScraper().run(vars(args))

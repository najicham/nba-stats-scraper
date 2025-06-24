# scrapers/pbpstats/pbpstats_schedule.py
"""
PBPStats season‑schedule scraper                         v2.5 – 2025‑06‑22
--------------------------------------------------------------------------
Runs on:
  • pbpstats 1.3.x  (legacy)
  • pbpstats 2.0‑RC variants that lack DataNbaWebLoader.load_data()

Local test:
    python -m scrapers.pbpstats.pbpstats_schedule --season 2024 --group test --debug 1
"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaSchedulePBPStats(ScraperBase):
    required_opts: List[str] = ["season"]            # four‑digit start year
    download_type: DownloadType = DownloadType.BINARY
    decode_download_data: bool = False
    header_profile: str | None = "data"

    RAW_KEY = "raw_json"
    GAMES_KEY = "games"

    exporters = [
        # raw JSON
        {
            "type": "file",
            "filename": "/tmp/schedule_%(season)s_raw.json",
            "export_mode": ExportMode.DATA,
            "data_key": RAW_KEY,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
        # games list
        {
            "type": "file",
            "filename": "/tmp/schedule_%(season)s_games.json",
            "export_mode": ExportMode.DATA,
            "data_key": GAMES_KEY,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
    ]

    # ------------------------------------------------ URL helper
    def set_url(self) -> None:
        self.url = (
            "https://cdn.nba.com/static/json/staticData/"
            f"scheduleLeagueV2_{self.opts['season']}.json"
        )
        logger.info("Resolved NBA schedule URL: %s", self.url)

    # ------------------------------------------------ validation
    def validate_download_data(self) -> None:
        if not isinstance(self.raw_json, dict) or "lscd" not in self.raw_json:
            raise ValueError("Unexpected schedule JSON schema.")

    # ------------------------------------------------ download
    def download_and_decode(self) -> None:
        start_year_int = int(self.opts["season"])
        start_year_str = f"{start_year_int}-{(start_year_int + 1) % 100:02d}"
        self.set_url()

        from pbpstats.data_loader import DataNbaScheduleLoader  # type: ignore

        sig = inspect.signature(DataNbaScheduleLoader)
        modern_api = {"league", "season_type"}.issubset(sig.parameters)

        # -------------------- shim for broken RC ------------------------ #
                # -------------------- shim for broken RC ------------------------ #
        class _ShimScheduleSourceLoader:
            """Fallback for pbpstats 2.0‑RC variants without a working loader."""

            file_path: str | None = None

            _HEADERS = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
                    "Gecko/20100101 Firefox/124.0"
                ),
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.nba.com/",
                "Origin": "https://www.nba.com",
            }

            def _get(self, url: str):
                resp = requests.get(url, headers=self._HEADERS, timeout=30)
                if resp.status_code == 403:
                    raise PermissionError("403")
                resp.raise_for_status()
                return resp.json()

            def load_data(self, league: str, season: str):
                start_year = season.split("-")[0]
                # 1) preferred CDN
                cdn_url = (
                    "https://cdn.nba.com/static/json/staticData/"
                    f"scheduleLeagueV2_{start_year}.json"
                )
                try:
                    data = self._get(cdn_url)
                    self.file_path = f"/tmp/pbp_cache/schedule_{start_year}_cdn.json"
                    return data
                except PermissionError:
                    # 2) fall back to data.nba.com (unprotected)
                    data_url = (
                        "https://data.nba.com/data/v2015/json/mobile_teams/"
                        f"nba/{start_year}/league/00_full_schedule.json"
                    )
                    logger.debug("CDN blocked; falling back to %s", data_url)
                    data = self._get(data_url)
                    self.file_path = f"/tmp/pbp_cache/schedule_{start_year}_data.json"
                    return data


        try:
            if modern_api:
                kw: Dict[str, Any] = {
                    "league": "nba",
                    "season": start_year_str,
                    "season_type": "Regular Season",
                }
                if "source_loader" in sig.parameters:
                    # Try native loader first
                    try:
                        from pbpstats.data_loader.data_nba.web_loader import (  # type: ignore
                            DataNbaWebLoader,
                        )

                        if hasattr(DataNbaWebLoader, "load_data"):
                            kw["source_loader"] = DataNbaWebLoader()
                        else:
                            kw["source_loader"] = _ShimScheduleSourceLoader()
                    except ImportError:
                        kw["source_loader"] = _ShimScheduleSourceLoader()

                loader = DataNbaScheduleLoader(**kw)  # type: ignore[arg-type]
            else:
                loader = DataNbaScheduleLoader(season=start_year_int)  # type: ignore[arg-type]

            # -------------------------------------------------------------
            self.raw_json: Dict[str, Any] = loader.get_data()
            self.validate_download_data()
            self.games: List[Dict[str, Any]] = [g.__dict__ for g in loader.get_games()]

        except Exception as exc:  # noqa: BLE001
            raise DownloadDataException(
                f"PBPStats schedule error for season {start_year_int}: {exc}"
            ) from exc

        if str(self.opts.get("debug", "0")).lower() in {"1", "true", "yes"}:
            logger.info("Schedule cache path: %s", getattr(loader, "file_path", "n/a"))

    # ------------------------------------------------ transform
    def transform_data(self) -> None:
        self.data = {
            "metadata": {
                "season": self.opts["season"],
                "generated": datetime.now(timezone.utc).isoformat(),
                "gameCount": len(self.games),
            },
            self.RAW_KEY: self.raw_json,
            self.GAMES_KEY: self.games,
        }
        logger.info(
            "Parsed %d games for season=%s", len(self.games), self.opts["season"]
        )

    # ------------------------------------------------ exporter helper / stats
    def get_export_data_for_exporter(self, exporter):
        return self.data.get(exporter.get("data_key", ""), {})

    def get_scraper_stats(self) -> dict:
        return {"season": self.opts["season"], "games": len(self.games)}


# ---------------------------------------------------------------------- #
# CLI
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description="Run PBPStats schedule scraper")
    cli.add_argument("--season", required=True, help="Start year, e.g. 2024 for 2024‑25")
    cli.add_argument("--group", default="test", help="dev / test / prod")
    cli.add_argument("--debug", default="0", help="1/true to print cache path")
    GetNbaSchedulePBPStats().run(vars(cli.parse_args()))

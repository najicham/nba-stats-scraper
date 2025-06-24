"""
BALLDONTLIE ‑ Season Averages endpoint                    v1 – 2025‑06‑22
-----------------------------------------------------------------------------
Per‑player season averages from

    https://api.balldontlie.io/v1/season_averages

### Required options
* `playerIds` – a comma‑separated string or Python list of player IDs.
               The API accepts up to **100 IDs per call**; this scraper
               automatically chunks larger lists.
### Optional
* `season`    – season start year, e.g. 2024.  
                Defaults to the “active” season (same rule as standings).

CLI
---
    python -m scrapers.bdl.bdl_season_averages_scraper \
        --playerIds 237,115,140 --season 2024
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..scraper_base import DownloadType, ExportMode, ScraperBase

logger = logging.getLogger("scraper_base")


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _current_nba_season() -> int:
    today = datetime.now(timezone.utc)
    return today.year if today.month >= 9 else today.year - 1


def _parse_player_ids(raw: str | List[str | int]) -> List[int]:
    """
    Accepts:
        * "1,2,3"
        * ["1", "2", "3"]
        * ["1", 2, 3]
    Returns: list[int]
    """
    if isinstance(raw, str):
        ids = [s.strip() for s in raw.split(",") if s.strip()]
    elif isinstance(raw, list):
        ids = raw
    else:
        raise ValueError("playerIds must be comma string or list")

    try:
        return [int(x) for x in ids]
    except ValueError as exc:
        raise ValueError("playerIds must be integers") from exc


_CHUNK_SIZE = 100                     # BALLDONTLIE hard limit per request


class BdlSeasonAveragesScraper(ScraperBase):
    """
    Batch scraper for /season_averages (handles >100 players via chunking).
    """

    # ------------------------------------------------------------------ #
    # Config                                                             #
    # ------------------------------------------------------------------ #
    required_opts: List[str] = ["playerIds"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_season_avg_%(ident)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_season_avg_%(ident)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts                                                    #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        # season default
        self.opts["season"] = int(self.opts.get("season") or _current_nba_season())

        # playerIds parsing + chunking list ready for later
        self._all_player_ids: List[int] = _parse_player_ids(self.opts["playerIds"])
        if not self._all_player_ids:
            raise ValueError("playerIds list is empty")

        # Build chunks (<=100 each) and keep iterator pointer
        self._id_chunks: List[List[int]] = [
            self._all_player_ids[i : i + _CHUNK_SIZE]
            for i in range(0, len(self._all_player_ids), _CHUNK_SIZE)
        ]
        self._chunk_iter = iter(self._id_chunks)

        # ident for filenames/logs
        first_n = ",".join(str(pid) for pid in self._all_player_ids[:3])
        suffix = "etc" if len(self._all_player_ids) > 3 else ""
        self.opts["ident"] = f"{self.opts['season']}_{len(self._all_player_ids)}p_{first_n}{suffix}"

    # ------------------------------------------------------------------ #
    # URL & headers (first chunk only)                                   #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/season_averages"

    def set_url(self) -> None:
        first_chunk = next(self._chunk_iter)      # consume first chunk
        self.base_url = self._API_ROOT
        self.url = self._build_url(first_chunk)
        logger.info("Resolved BALLDONTLIE season‑averages URL (chunk 1/%d): %s",
                    len(self._id_chunks), self.url)

    def _build_url(self, player_ids: List[int]) -> str:
        query = f"season={self.opts['season']}"
        for pid in player_ids:
            query += f"&player_ids[]={pid}"
        return f"{self.base_url}?{query}"

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
            raise ValueError("Season‑averages response is not JSON object")
        if "data" not in self.decoded_data:
            raise ValueError("'data' field missing in season‑averages JSON")

    # ------------------------------------------------------------------ #
    # Transform (iterate remaining chunks)                               #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        rows: List[Dict[str, Any]] = list(self.decoded_data["data"])

        # Iterate remaining chunks
        chunk_num = 1
        for ids in self._chunk_iter:
            chunk_num += 1
            url = self._build_url(ids)
            resp = self.http_downloader.get(
                url,
                headers=self.headers,
                timeout=self.timeout_http,
            )
            resp.raise_for_status()
            rows.extend(resp.json().get("data", []))
            logger.info("Fetched chunk %d/%d (%d IDs)", chunk_num, len(self._id_chunks), len(ids))

        # Deterministic order: playerId ASC
        rows.sort(key=lambda r: r.get("player_id"))

        self.data = {
            "ident": self.opts["ident"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "season": self.opts["season"],
            "playerCountRequested": len(self._all_player_ids),
            "rowCount": len(rows),
            "seasonAverages": rows,
        }
        logger.info(
            "Retrieved season averages for %d of %d requested players (season %s)",
            len(rows),
            len(self._all_player_ids),
            self.opts["season"],
        )

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0),
            "playerReq": self.data.get("playerCountRequested", 0),
            "season": self.opts["season"],
        }


# ---------------------------------------------------------------------- #
# Google Cloud Function entry point                                      #
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    player_ids = request.args.get("playerIds")
    season = request.args.get("season")
    group = request.args.get("group", "prod")

    opts = {"playerIds": player_ids, "season": season, "group": group}
    BdlSeasonAveragesScraper().run(opts)
    ident = opts.get("season") or _current_nba_season()
    return f"BALLDONTLIE season‑averages scrape complete ({ident})", 200


# ---------------------------------------------------------------------- #
# CLI usage                                                              #
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse, textwrap

    cli = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(
            """\
            Example:
                python -m scrapers.bdl.bdl_season_averages_scraper \\
                    --playerIds 237,115,140 --season 2024
            """
        ),
    )
    cli.add_argument("--playerIds", required=True, help="Comma list of player IDs (max 5000 recommended)")
    cli.add_argument("--season", type=int, help="Season start year, e.g. 2024")
    cli.add_argument("--group", default="test")
    BdlSeasonAveragesScraper().run(vars(cli.parse_args()))

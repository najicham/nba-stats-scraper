"""
BALLDONTLIE - Player Averages endpoint                     v1.3 (2025-06-24)
------------------------------------------------------------------------------
Per-player season averages from

    https://api.balldontlie.io/v1/season_averages
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import (
    NoHttpStatusCodeException,
    InvalidHttpStatusCodeException,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _current_nba_season() -> int:
    today = datetime.now(timezone.utc)
    return today.year if today.month >= 9 else today.year - 1


def _parse_player_ids(raw: str | List[str | int]) -> List[int]:
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


_CHUNK_SIZE = 100  # BallDontLie hard limit per request

# --------------------------------------------------------------------------- #
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class BdlPlayerAveragesScraper(ScraperBase):
    """Batch scraper for /season_averages (handles >100 IDs via chunking)."""

    required_opts: List[str] = ["playerIds"]
    download_type = DownloadType.JSON
    decode_download_data = True
    no_retry_status_codes = ScraperBase.no_retry_status_codes + [503]

    # -- retry strategy --------------------------------------------------
    def get_retry_strategy(self):
        from urllib3.util.retry import Retry

        return Retry(
            total=self.max_retries_http,
            status_forcelist=[429, 500, 502, 504],  # 503 excluded
            allowed_methods=["GET"],
            backoff_factor=3,
        )

    def check_download_status(self):
        if not hasattr(self.raw_response, "status_code"):
            raise NoHttpStatusCodeException("No status_code on download response.")

        if self.raw_response.status_code == 503:
            detail = ""
            if self.raw_response.headers.get("Content-Type", "").startswith(
                "application/json"
            ):
                try:
                    detail = self.raw_response.json().get("message", "")
                except ValueError:
                    pass
            raise InvalidHttpStatusCodeException(
                f"503 Service Unavailable - {detail or 'data not available yet'}"
            )

        super().check_download_status()

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/bdl_player_averages_%(ident)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
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
        self.opts["season"] = int(self.opts.get("season") or _current_nba_season())

        self._all_player_ids = _parse_player_ids(self.opts["playerIds"])
        if not self._all_player_ids:
            raise ValueError("playerIds list is empty")

        self._id_chunks: List[List[int]] = [
            self._all_player_ids[i : i + _CHUNK_SIZE]
            for i in range(0, len(self._all_player_ids), _CHUNK_SIZE)
        ]
        self._chunk_iter = iter(self._id_chunks)

        first_n = ",".join(str(pid) for pid in self._all_player_ids[:3])
        suffix = "etc" if len(self._all_player_ids) > 3 else ""
        self.opts["ident"] = (
            f"{self.opts['season']}_{len(self._all_player_ids)}p_{first_n}{suffix}"
        )

    # ------------------------------------------------------------------ #
    # HTTP setup                                                         #
    # ------------------------------------------------------------------ #
    _API_ROOT = "https://api.balldontlie.io/v1/season_averages"

    def _build_url(self, player_ids: List[int]) -> str:
        ids_qs = "&".join(f"player_ids[]={pid}" for pid in player_ids)
        return f"{self._API_ROOT}?season={self.opts['season']}&{ids_qs}"

    def set_url(self) -> None:
        first_chunk = next(self._chunk_iter)  # consume first chunk
        self.base_url = self._API_ROOT
        self.url = self._build_url(first_chunk)
        logger.debug(
            "Player-averages URL (chunk 1/%d): %s", len(self._id_chunks), self.url
        )

    def set_headers(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("BDL_API_KEY")
        self.headers = {
            "User-Agent": "scrape-bdl-player-avg/1.2 (+github.com/your-org)",
            "Accept": "application/json",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        if not isinstance(self.decoded_data, dict) or "data" not in self.decoded_data:
            raise ValueError("Player-averages response malformed: missing 'data' key")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        rows: List[Dict[str, Any]] = list(self.decoded_data["data"])

        chunk_num = 1
        for ids in self._chunk_iter:
            chunk_num += 1
            url = self._build_url(ids)
            resp = self.http_downloader.get(
                url, headers=self.headers, timeout=self.timeout_http
            )
            resp.raise_for_status()
            rows.extend(resp.json().get("data", []))
            logger.debug(
                "Fetched chunk %d/%d (%d IDs)", chunk_num, len(self._id_chunks), len(ids)
            )

        rows.sort(key=lambda r: r.get("player_id", 0))

        self.data = {
            "ident": self.opts["ident"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "season": self.opts["season"],
            "playerCountRequested": len(self._all_player_ids),
            "rowCount": len(rows),
            "playerAverages": rows,
        }
        logger.info(
            "Retrieved player averages for %d of %d requested players (season %s)",
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


# --------------------------------------------------------------------------- #
# Google Cloud Function entry                                                #
# --------------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    opts = {
        "playerIds": request.args.get("playerIds"),
        "season": request.args.get("season"),
        "apiKey": request.args.get("apiKey"),
        "group": request.args.get("group", "prod"),
        "runId": request.args.get("runId"),
    }
    BdlPlayerAveragesScraper().run(opts)
    return (
        f"BallDontLie player-averages scrape complete "
        f"({opts.get('season') or _current_nba_season()})",
        200,
    )


# --------------------------------------------------------------------------- #
# CLI usage                                                                  #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    import textwrap
    from scrapers.utils.cli_utils import add_common_args

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(
            """\
            Scrape BallDontLie /season_averages (player averages)

            Examples
            --------
            * Single player, default season:
              python -m scrapers.balldontlie.bdl_player_averages --playerIds 237

            * Three players, explicit season:
              python -m scrapers.balldontlie.bdl_player_averages \\
                     --playerIds 237,115,140 --season 2024
            """
        ),
    )
    parser.add_argument(
        "--playerIds",
        required=True,
        help="Comma list of player IDs (auto-chunked to 100 per call)",
    )
    parser.add_argument("--season", type=int, help="Season start year, e.g. 2024")
    add_common_args(parser)  # --group --apiKey --runId --debug
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    BdlPlayerAveragesScraper().run(vars(args))

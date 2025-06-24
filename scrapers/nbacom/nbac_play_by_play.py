# scrapers/nbacom/nbac_pbp_raw_backup.py
"""
Raw play-by-play JSON backup scraper                     v2 - 2025-06-16
------------------------------------------------------------------------
Downloads the unprocessed PBP feed from data.nba.com for a given gameId.
Useful when the cleaned PBPStats feed fails or you need to rehydrate
historical data.

CLI example
-----------
    python -m scrapers.nbacom.nbac_pbp_raw_backup --gameId 0022400987
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaPlayByPlayRawBackup(ScraperBase):
    """Downloads raw PBP JSON from the public CDN."""

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #
    required_opts = ["gameId"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = "data"

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/pbp_raw_%(gameId)s.json",
            "export_mode": ExportMode.DECODED,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
        {
            "type": "gcs",
            "key": "nba/pbp/raw_backup/%(season)s/%(gameId)s.json",
            "export_mode": ExportMode.DECODED,
            "groups": ["prod", "gcs"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts helper (derive season)
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        gid = self.opts["gameId"]
        try:
            yr_prefix = 2000 + int(gid[3:5])
            self.opts["season"] = f"{yr_prefix}-{(yr_prefix + 1) % 100:02d}"
        except (ValueError, IndexError):
            raise DownloadDataException("Invalid gameId format for season derivation")

    # ------------------------------------------------------------------ #
    # URL builder
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        gid = self.opts["gameId"]
        self.url = (
            f"https://cdn.nba.com/static/json/liveData/playbyplay/"
            f"playbyplay_{gid}.json"
        )
        logger.info("PBP URL: %s", self.url)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        game = self.decoded_data.get("game")
        if game is None or "actions" not in game:
            raise DownloadDataException("PBP JSON missing game.actions array")
        if not isinstance(game["actions"], list) or not game["actions"]:
            raise DownloadDataException("game.actions is empty")

    # ------------------------------------------------------------------ #
    # Transform (wrap with metadata)
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        actions = self.decoded_data["game"]["actions"]

        self.data: Dict[str, Any] = {
            "metadata": {
                "gameId": self.opts["gameId"],
                "season": self.opts["season"],
                "fetchedUtc": ts,
                "eventCount": len(actions),
            },
            "playByPlay": self.decoded_data,
        }

    # ------------------------------------------------------------------ #
    # Tell exporters what to save (just the playByPlay section for GCS/file)
    # ------------------------------------------------------------------ #
    def get_export_data_for_exporter(self, _exporter_cfg):  # noqa: D401
        return self.data["playByPlay"]

    # ------------------------------------------------------------------ #
    # Stats line
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "gameId": self.opts["gameId"],
            "events": self.data["metadata"]["eventCount"],
        }


# ---------------------------------------------------------------------- #
# Cloud Function / Cloud Run HTTP entry
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    game_id = request.args.get("gameId")
    if not game_id:
        return ("Missing query param 'gameId'", 400)

    ok = GetNbaPlayByPlayRawBackup().run(
        {"gameId": game_id, "group": request.args.get("group", "prod")}
    )
    return (("PBP scrape failed", 500) if ok is False else ("Scrape ok", 200))


# ---------------------------------------------------------------------- #
# CLI helper
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--gameId", required=True, help="e.g. 0022400987")
    cli.add_argument("--group", default="test")
    GetNbaPlayByPlayRawBackup().run(vars(cli.parse_args()))

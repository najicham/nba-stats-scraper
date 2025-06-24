# scrapers/nbacom/nbac_player_movement.py
"""
NBA Player-Movement / Transaction feed                    v2 - 2025-06-16
------------------------------------------------------------------------
CLI quick-start:
    python -m scrapers.nbacom.nbac_player_movement --year 2025 --group test
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaComPlayerMovement(ScraperBase):
    """
    Downloads the static JSON blob at
    https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json
    """

    # ------------------------------------------------------------------ #
    # Configuration mirrors v1
    # ------------------------------------------------------------------ #
    additional_opts = ["current_year"]        # auto‑fill `year` if omitted
    header_profile: str | None = "stats"
    proxy_enabled: bool = False               # unchanged
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True

    # Fixed URL (same as before)
    url = "https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json"

    exporters = [
        {
            "type": "gcs",
            "key": "nbacom/player-movement/%(year)s/log/%(time)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "s3", "gcs"],
        },
        {
            "type": "gcs",
            "key": "nbacom/player-movement/%(year)s/current/current.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "s3", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacomplayermovement2.json",
            "export_mode": ExportMode.RAW,
            "groups": ["dev", "file"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Option helpers
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        if not self.opts.get("year"):
            self.opts["year"] = str(datetime.now(timezone.utc).year)
        # exporter timestamp
        self.opts["time"] = datetime.now(timezone.utc).strftime("%H-%M-%S")

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        root = self.decoded_data.get("NBA_Player_Movement")
        rows: List = (root or {}).get("rows", [])
        if not rows:
            raise DownloadDataException("NBA_Player_Movement.rows missing or empty")
        logger.info("Found %d movement rows for year=%s", len(rows), self.opts["year"])

    # ------------------------------------------------------------------ #
    # Transform (pass-through but add meta)
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        self.data: Dict[str, any] = {
            "year": self.opts["year"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rows": self.decoded_data["NBA_Player_Movement"]["rows"],
        }

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "year": self.opts["year"],
            "records_found": len(self.data["rows"]),
        }


# ---------------------------------------------------------------------- #
# Google Cloud Function / Cloud Run entry
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    year = request.args.get("year", "")  # blank triggers auto‑fill
    group = request.args.get("group", "prod")

    ok = GetNbaComPlayerMovement().run({"year": year, "group": group})
    return (("Player‑movement scrape failed", 500) if ok is False else ("Scrape ok", 200))


# ---------------------------------------------------------------------- #
# Local CLI usage
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description="Run NBA Player Movement locally")
    cli.add_argument("--year", default="", help="e.g. 2025 (blank for current)")
    cli.add_argument("--group", default="test")
    GetNbaComPlayerMovement().run(vars(cli.parse_args()))

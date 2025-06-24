# scrapers/nbacom/nba_game_ids_content.py
from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Dict, Any
import logging

from ...scraper_base import ScraperBase, DownloadType, ExportMode
from ...utils.exceptions import DownloadDataException

log = logging.getLogger("scraper_base")

class GetNbaGameIdsContent(ScraperBase):
    required_opts = ["scoreDate"]              # YYYYMMDD or YYYY‑MM‑DD
    header_profile = "data"                    # simple UA only
    download_type = DownloadType.JSON
    browser_enabled = True                     # harvest Akamai cookies
    browser_url = "https://www.nba.com/games"  # page that sets them
    proxy_enabled = False

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/nba_game_ids_content_%(scoreDate)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "prod"],
        }
    ]

    def set_url(self):
        raw = self.opts["scoreDate"].replace("-", "")
        if len(raw) != 8 or not raw.isdigit():
            raise DownloadDataException("scoreDate must be YYYYMMDD or YYYY‑MM‑DD")
        yyyy, mm, dd = raw[0:4], raw[4:6], raw[6:8]
        iso_date = f"{yyyy}-{mm}-{dd}"

        base = (
            "https://content-api-prod.nba.com/public/1/leagues/nba/"
            "content/event"
        )
        self.url = (
            f"{base}?eventDate={iso_date}"
            "&sort=eventDate"
            "&countryCode=US"
            "&region=international"
        )
        log.info("Resolved Content‑API URL: %s", self.url)
        self.opts["scoreDate"] = raw

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self):
        if not self.decoded_data:
            raise DownloadDataException("Content‑API returned empty JSON.")

        if "results" not in self.decoded_data:
            raise DownloadDataException("Missing 'results' key in Content‑API.")

        if not isinstance(self.decoded_data["results"], dict):
            raise DownloadDataException("'results' is not an object.")

        if "items" not in self.decoded_data["results"]:
            raise DownloadDataException("Missing 'results.items' list.")

    # ------------------------------------------------------------------ #
    # Transform
    # ------------------------------------------------------------------ #
    def transform_data(self):
        rows = self.decoded_data["results"]["items"]  # guaranteed by validate
        parsed = []

        for rec in rows:
            # Sometimes it's a plain dict, sometimes under 'payload'
            payload = rec.get("payload", rec)

            gid = payload.get("gameId") or payload.get("eventId")
            if not gid:
                continue  # skip non‑game promos

            parsed.append(
                {
                    "gameId": gid,
                    "home": payload.get("homeTeam", {}).get("profile", {}).get("abbr"),
                    "away": payload.get("awayTeam", {}).get("profile", {}).get("abbr"),
                    "state": payload.get("eventStatus")
                             or payload.get("gameStatusText", ""),
                    "startTimeUTC": payload.get("dateUtc") or payload.get("datetimeUtc"),
                }
            )

        self.data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scoreDate": self.opts["scoreDate"],
            "gameCount": len(parsed),
            "games": parsed,
        }


    def get_scraper_stats(self):
        return {
            "scoreDate": self.opts["scoreDate"],
            "gameCount": self.data.get("gameCount", 0),
        }

# CLI helper
if __name__ == "__main__":
    import argparse, pathlib, sys
    cli = argparse.ArgumentParser()
    cli.add_argument("--scoreDate", required=True, help="20250621 or 2025‑06‑21")
    cli.add_argument("--group", default="dev")
    sys.exit(GetNbaGameIdsContent().run(vars(cli.parse_args())))

# nba_game_ids_core.py
#
# Pulls NBA GameIDs for a single date via:
#   https://core-api.nba.com/cp/api/v1.9/feeds/gamecardfeed
# and writes a tidy JSON file for downstream jobs.
#
# CLI usage:
#   python -m scrapers.nba_game_ids_core --scoreDate 20250316
# GCF usage:
#   Deploy the 'gcf_entry' function (HTTP trigger) and call:
#   https://…/nbaGameIds?scoreDate=20250316
#   or ...?scoreDate=2025-03-16

import logging
import json
import pytz
from datetime import datetime

from ..scraper_base import ScraperBase, DownloadType, ExportMode
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaGameIdsCore(ScraperBase):
    """
    Collects NBA GameIDs for a given date using the public Core‑API feed.
    """

    required_opts = ["scoreDate"]           # YYYYMMDD

    download_type = DownloadType.JSON
    decode_download_data = True

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/nba_game_ids_core_%(scoreDate)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"]
        },
        {
            "type": "gcs",
            "key": "nba/game_ids/%(scoreDate)s/game_ids_core.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"]
        }
    ]

    # ------------------------------------------------------------------ URL / headers
    def set_url(self):
        """
        Build the core‑api endpoint.
        API wants MM/DD/YYYY (zero‑padded) in US format.
        """
        raw = self.opts["scoreDate"]        # YYYYMMDD
        if len(raw) != 8:
            raise DownloadDataException("scoreDate must be YYYYMMDD")

        yyyy, mm, dd = raw[0:4], raw[4:6], raw[6:8]
        mmddyyyy = f"{mm}/{dd}/{yyyy}"

        base = "https://core-api.nba.com/cp/api/v1.9/feeds/gamecardfeed"
        self.url = f"{base}?gamedate={mmddyyyy}&platform=web"
        logger.info("Resolved Core‑API URL: %s", self.url)

    def set_headers(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            ),
            "Origin": "https://www.nba.com",
            "Referer": "https://www.nba.com/"
        }

    # ------------------------------------------------------------------ validation
    def validate_download_data(self):
        if "games" not in self.decoded_data:
            raise DownloadDataException("No 'games' key in core‑api response")

    # ------------------------------------------------------------------ transform
    def transform_data(self):
        """
        Reduce the raw JSON to a concise list of games.
        """
        self.step_info("transform", "Parsing core‑api gamecardfeed JSON")

        games_raw = self.decoded_data.get("games", [])
        logger.info("Found %d games for date=%s", len(games_raw), self.opts["scoreDate"])

        parsed_games = [
            {
                "gameId": g.get("gameId"),
                "home":   g.get("homeTeam", {}).get("teamTricode"),
                "away":   g.get("awayTeam", {}).get("teamTricode"),
                "gameStatus": g.get("gameStatus"),          # 1 pre, 2 live, 3 final
                "startTimeUTC": g.get("gameEt")             # ET ISO string
            }
            for g in games_raw
        ]

        now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat()
        self.data = {
            "timestamp": now_utc,
            "scoreDate": self.opts["scoreDate"],
            "games": parsed_games
        }

    # ------------------------------------------------------------------ stats
    def get_scraper_stats(self):
        return {
            "scoreDate": self.opts["scoreDate"],
            "gameCount": len(self.data.get("games", [])),
        }


# ------------------------------------------------------------------ Google Cloud Function entry
def gcf_entry(request):
    """
    HTTP entry point for Cloud Functions / Cloud Run.

    Query parameters:
        scoreDate  – required – YYYYMMDD  (20250316)  OR YYYY-MM-DD (2025-03-16)
        group      – optional – defaults to 'prod'
    """
    score_date = request.args.get("scoreDate")
    group      = request.args.get("group", "prod")

    if not score_date:
        return ("Missing required parameter: scoreDate", 400)

    # Allow YYYY-MM-DD convenience
    if "-" in score_date and len(score_date) == 10:
        score_date = score_date.replace("-", "")

    opts = {"scoreDate": score_date, "group": group}
    scraper = GetNbaGameIdsCore()
    result  = scraper.run(opts)

    if result is False:
        return (f"Game‑ID scraper failed for {score_date}", 500)
    return (f"Game‑ID scraper completed for {score_date}. Result={result}", 200)


# ------------------------------------------------------------------ Local CLI helper
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--scoreDate", required=True, help="e.g. 20250316")
    parser.add_argument("--group", default="test", help="dev, test, prod, etc.")
    args = parser.parse_args()

    scraper = GetNbaGameIdsCore()
    scraper.run(vars(args))

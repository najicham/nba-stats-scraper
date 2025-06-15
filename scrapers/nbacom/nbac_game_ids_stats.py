# nba_game_ids_stats.py
#
# Fallback Game‑ID scraper for a single calendar date.
# Hits the classic stats.nba.com ScoreboardV3 feed, which has been stable
# since 2019 but requires custom headers and is more likely to rate‑limit
# cloud‑provider IP blocks.
#
# CLI:
#   python -m scrapers.nba_game_ids_stats --scoreDate 20250316
#
# GCF:
#   Deploy 'gcf_entry' and call
#     .../nbaGameIdsStats?scoreDate=2025-03-16
#     or ...?scoreDate=20250316
#
# Output: identical shape to nba_game_ids_core.py so downstream jobs
#         don’t care which source produced the file.

import logging
import pytz
from datetime import datetime

from ..scraper_base import ScraperBase, DownloadType, ExportMode
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaGameIdsStats(ScraperBase):
    """
    Fallback collector using stats.nba.com/stats/scoreboardv3.
    """

    required_opts = ["scoreDate"]           # YYYYMMDD
    download_type = DownloadType.JSON
    decode_download_data = True
    header_profile = "stats"

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/nba_game_ids_stats_%(scoreDate)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"]
        },
        {
            "type": "gcs",
            "key": "nba/game_ids/%(scoreDate)s/game_ids_stats.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"]
        }
    ]

    # ------------------------------------------------------------ URL / headers
    def set_url(self):
        """
        Build the ScoreboardV3 endpoint.
        Only GameDate and LeagueID are required; DayOffset=0 keeps it simple.
        """
        raw = self.opts["scoreDate"]        # YYYYMMDD
        if len(raw) != 8:
            raise DownloadDataException("scoreDate must be YYYYMMDD")

        yyyy, mm, dd = raw[0:4], raw[4:6], raw[6:8]
        mmddyyyy = f"{mm}/{dd}/{yyyy}"

        base = "https://stats.nba.com/stats/scoreboardv3"
        self.url = (
            f"{base}?GameDate={mmddyyyy}"
            f"&LeagueID=00"
            f"&DayOffset=0"
        )
        logger.info("Resolved ScoreboardV3 URL: %s", self.url)

    def set_headers(self):
        """
        Stats site blocks 'curl' UAs & requires 2 custom headers.
        """
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            ),
            "x-nba-stats-origin": "stats",
            "x-nba-stats-token": "true",
            "Referer": "https://www.nba.com/",
            "Origin": "https://www.nba.com"
        }

    # ------------------------------------------------------------ validation
    def validate_download_data(self):
        """
        Expect top‑level 'scoreboard' with 'games' array.
        """
        data = self.decoded_data
        if not isinstance(data, dict):
            raise DownloadDataException("Decoded response is not a dict.")
        if "scoreboard" not in data or "games" not in data["scoreboard"]:
            raise DownloadDataException("Missing 'scoreboard.games' in JSON.")

    # ------------------------------------------------------------ transform
    def transform_data(self):
        """
        Reduce to the same shape as the core‑api scraper.
        """
        games_raw = self.decoded_data["scoreboard"]["games"]
        logger.info("Found %d games for %s via ScoreboardV3",
                    len(games_raw), self.opts["scoreDate"])

        parsed = [
            {
                "gameId": g.get("gameId"),
                "home":   g.get("homeTeam", {}).get("teamTricode"),
                "away":   g.get("awayTeam", {}).get("teamTricode"),
                "gameStatus": g.get("gameStatus"),           # 1/2/3
                "startTimeUTC": g.get("gameEt")              # ET ISO string
            }
            for g in games_raw
        ]

        now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat()
        self.data = {
            "timestamp": now_utc,
            "scoreDate": self.opts["scoreDate"],
            "games": parsed
        }

    # ------------------------------------------------------------ stats
    def get_scraper_stats(self):
        return {
            "scoreDate": self.opts["scoreDate"],
            "gameCount": len(self.data.get("games", []))
        }


# ------------------------------------------------------------ GCF entry
def gcf_entry(request):
    """
    HTTP entry point (Cloud Function / Cloud Run):

      ?scoreDate=YYYYMMDD  or  YYYY-MM-DD
      ?group=dev|test|prod   (optional, default 'prod')
    """
    score_date = request.args.get("scoreDate")
    group      = request.args.get("group", "prod")

    if not score_date:
        return ("Missing required parameter: scoreDate", 400)

    # Allow YYYY-MM-DD convenience
    if "-" in score_date and len(score_date) == 10:
        score_date = score_date.replace("-", "")

    opts = {"scoreDate": score_date, "group": group}
    scraper = GetNbaGameIdsStats()
    result  = scraper.run(opts)

    if result is False:
        return (f"Stats scoreboard scrape failed for {score_date}", 500)
    return (f"Stats scoreboard scrape completed for {score_date}. Result={result}", 200)


# ------------------------------------------------------------ Local CLI helper
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--scoreDate", required=True, help="e.g. 20250316")
    parser.add_argument("--group", default="test", help="dev, test, prod, etc.")
    args = parser.parse_args()

    scraper = GetNbaGameIdsStats()
    scraper.run(vars(args))

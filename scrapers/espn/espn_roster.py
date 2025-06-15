# scrapers/espn_roster.py
# python -m scrapers.espn_roster --teamSlug boston-celtics --teamAbbr bos

import os
import logging
import json
from datetime import datetime
import pytz
import re

import sentry_sdk
from bs4 import BeautifulSoup

from ..scraper_base import ScraperBase, DownloadType, ExportMode
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger("scraper_base")


class GetEspnTeamRoster(ScraperBase):
    """
    Scraper for ESPN rosters, e.g.:
      https://www.espn.com/nba/team/roster/_/name/bos/boston-celtics
    Requires:
      --teamSlug (e.g. 'boston-celtics')
      --teamAbbr (e.g. 'bos')
    """

    required_opts = ["teamSlug", "teamAbbr"]
    decode_download_data = True
    download_type = DownloadType.BINARY  # We'll parse raw HTML ourselves

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/espn_roster_%(teamAbbr)s_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"]
        },
        # Add GCS or other exporters here if desired
        # {
        #     "type": "gcs",
        #     "key": "nba/espn/rosters/%(season)s/%(date)s/%(teamAbbr)s_%(time)s.json",
        #     "export_mode": ExportMode.DATA,
        #     "groups": ["prod", "gcs"]
        # }
    ]

    def set_additional_opts(self):
        """
        Fill in default date, time, season if not provided.
        """
        now_utc = datetime.utcnow()
        now_pst = now_utc.astimezone(pytz.timezone("America/Los_Angeles"))

        self.opts["date"] = now_pst.strftime("%Y-%m-%d")
        self.opts["time"] = now_pst.strftime("%H-%M-%S")
        # Example season = "2025-26"
        season_year = now_pst.year
        next_year_2dig = f"{(season_year + 1) % 100:02d}"
        self.opts["season"] = self.opts.get("season", f"{season_year}-{next_year_2dig}")

    def set_url(self):
        """
        Build ESPN URL, e.g.:
          https://www.espn.com/nba/team/roster/_/name/bos/boston-celtics
        """
        teamSlug = self.opts["teamSlug"]
        teamAbbr = self.opts["teamAbbr"]
        self.url = (
            f"https://www.espn.com/nba/team/roster/_/name/{teamAbbr}/{teamSlug}"
        )
        logger.info(f"Resolved ESPN roster URL: {self.url}")

    def set_headers(self):
        """Use a 'real browser' style user-agent."""
        self.headers = {"User-Agent": "Mozilla/5.0"}

    def decode_download_content(self):
        """
        We'll store the raw HTML text ourselves in self.html_content.
        """
        self.html_content = self.raw_response.text

    def validate_download_data(self):
        """
        Confirm we have HTML content.
        """
        if not getattr(self, "html_content", ""):
            raise DownloadDataException("No HTML content retrieved from ESPN roster page.")

    def transform_data(self):
        """
        1) Parse HTML with BeautifulSoup
        2) Extract table rows for roster
        3) Build a list of players with fields:
            number, name, playerId, slug, fullUrl, position, age, height, weight
        4) Perform light validation (Sentry alert if name/slug/playerId missing)
        """
        self.step_info("transform", "Starting ESPN roster transformation via table")

        # Optionally, store the raw HTML to a debug file
        self._debug_write_raw_html()

        soup = BeautifulSoup(self.html_content, "html.parser")
        table_rows = soup.select("tr.Table__TR")

        players = []
        for tr in table_rows:
            # ESPN's pattern:
            #  1st <td> = headshot
            #  2nd <td> = name + jersey
            #  3rd <td> = position
            #  4th <td> = age
            #  5th <td> = height
            #  6th <td> = weight
            # (And possibly more columns for college, salary, etc.)

            tds = tr.find_all("td")
            if len(tds) < 6:
                # Not a valid roster row
                continue

            # The 2nd td (index 1) typically has:
            #   <a href=".../id/4397424/neemias-queta">Neemias Queta</a><span>88</span>
            anchor = tds[1].find("a", href=True)
            if not anchor:
                continue
            name = anchor.get_text(strip=True)
            full_href = anchor["href"]  # e.g. 'https://www.espn.com/nba/player/_/id/4397424/neemias-queta'

            # Attempt to find <span> (the jersey number) inside the same TD
            jersey_span = tds[1].find("span", {"class": "pl2"})
            jersey_number = jersey_span.get_text(strip=True) if jersey_span else ""

            # Player ID is usually after '/id/'
            # Slug is after that ID, e.g. ".../id/4397424/neemias-queta"
            # A quick approach:
            #   pattern = /id/(\d+)/(.*)$
            # We'll store the entire absolute URL as well
            full_url = f"https://www.espn.com{full_href}" if full_href.startswith("/") else full_href
            player_id = ""
            slug = ""

            pattern = re.compile(r"/id/(\d+)/(.*)$")
            match = pattern.search(full_href)
            if match:
                player_id = match.group(1)  # "4397424"
                slug = match.group(2)      # "neemias-queta"

            position = tds[2].get_text(strip=True) or ""
            age = tds[3].get_text(strip=True) or ""
            height = tds[4].get_text(strip=True) or ""
            weight = tds[5].get_text(strip=True) or ""

            players.append({
                "number": jersey_number,
                "name": name,
                "playerId": player_id,
                "slug": slug,
                "fullUrl": full_url,
                "position": position,
                "age": age,
                "height": height,
                "weight": weight,
            })

        # Light schema validation: If name, slug, or playerId is empty => log + Sentry
        validated_players = []
        for p in players:
            missing = []
            for key in ("name", "slug", "playerId"):
                if not p.get(key):
                    missing.append(key)

            if missing:
                # Log a warning
                logger.warning(
                    f"ESPN Roster: Missing {missing} for player record: {p}"
                )
                # Send Sentry notification
                sentry_sdk.capture_message(
                    f"[ESPN Roster Alert] Missing {', '.join(missing)} for player: {p}",
                    level="warning",
                )
            validated_players.append(p)

        # Build final data
        now_utc = datetime.utcnow()
        self.data = {
            "teamAbbr": self.opts["teamAbbr"],
            "teamSlug": self.opts["teamSlug"],
            "timestamp": now_utc.isoformat(),
            "players": validated_players,
            "season": self.opts["season"],
            "date": self.opts["date"],
            "time": self.opts["time"],
        }

        logger.info(f"Found {len(validated_players)} players for ESPN team {self.opts['teamAbbr']}!")

    def get_scraper_stats(self):
        """
        Add custom stats to the final log line (SCRAPER_STATS).
        """
        return {
            "teamAbbr": self.opts["teamAbbr"],
            "playerCount": len(self.data.get("players", [])),
        }

    # -------------------------------------------------------------------------
    # Debug utility: write raw HTML to a file.
    # -------------------------------------------------------------------------
    def _debug_write_raw_html(self):
        debug_file = f"/tmp/debug_raw_{self.run_id}.html"
        try:
            with open(debug_file, "w", encoding="utf-8") as f:
                f.write(self.html_content)
            logger.info(f"Saved raw HTML to {debug_file} for debugging")
        except Exception as e:
            logger.warning(f"Failed to write {debug_file}: {e}")


# -------------------------------------------------------------------------
# CLI or GCF entry point
# -------------------------------------------------------------------------
def gcf_entry(request):
    """
    Google Cloud Function entry point
    """
    teamSlug = request.args.get("teamSlug")
    teamAbbr = request.args.get("teamAbbr")
    group = request.args.get("group", "prod")

    if not teamSlug or not teamAbbr:
        return ("Missing required parameters: teamSlug, teamAbbr", 400)

    opts = {"teamSlug": teamSlug, "teamAbbr": teamAbbr, "group": group}
    scraper = GetEspnTeamRoster()
    result = scraper.run(opts)
    return f"ESPN Roster run complete for {teamSlug}. Result: {result}", 200


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--teamSlug", required=True, help="e.g. 'boston-celtics'")
    parser.add_argument("--teamAbbr", required=True, help="e.g. 'bos'")
    parser.add_argument("--group", default="test", help="dev, test, prod, etc.")
    args = parser.parse_args()

    scraper = GetEspnTeamRoster()
    scraper.run(vars(args))

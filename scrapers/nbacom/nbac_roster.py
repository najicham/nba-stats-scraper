# nbac_team_roster.py

import os
import logging
import json
from datetime import datetime
from bs4 import BeautifulSoup
import pytz

# Pydantic for JSON structure validation
from pydantic import BaseModel, Field, ValidationError
from typing import List

from ..scraper_base import ScraperBase, DownloadType, ExportMode
from ..utils.exceptions import DownloadDataException
from config.nba_teams import NBA_TEAMS

logger = logging.getLogger("scraper_base")

##############################################################################
# 1) Define Pydantic models to describe the JSON structure you expect.
#    Customize as your actual structure changes. 
##############################################################################

class PlayerItem(BaseModel):
    PLAYER: str = Field(..., description="Full name of the player (e.g. 'Stephen Curry')")
    PLAYER_SLUG: str = Field(..., description="Slug (e.g. 'stephen-curry')")
    PLAYER_ID: int = Field(..., description="Numeric ID (e.g. 201939)")
    NUM: str = Field(..., description="Jersey number (e.g. '30')")
    POSITION: str = Field(..., description="Position label (e.g. 'G')")

class Roster(BaseModel):
    roster: List[PlayerItem]

class TeamProps(BaseModel):
    team: Roster

class PageProps(BaseModel):
    pageProps: TeamProps

class NextData(BaseModel):
    props: PageProps


##############################################################################
# 2) Scraper Class
##############################################################################
class GetNbaTeamRoster(ScraperBase):
    """
    Scraper to download an NBA team's official roster page from nba.com and
    parse the JSON structure within <script id="__NEXT_DATA__"> to build a
    structured player list.

    - Provides data validation via Pydantic
    - Attempts fallback data storage if the JSON doesn't match the schema
    """
    required_opts = ["teamAbbr"]
    decode_download_data = True        # We'll let ScraperBase call validate_download_data
    download_type = DownloadType.BINARY  # We'll decode HTML ourselves
    # Use the shared data‑site headers (UA + Referer) from ScraperBase
    header_profile = "data"

    exporters = [
        {
            "type": "gcs",
            "key": "nba/rosters/%(season)s/%(date)s/%(teamAbbr)s_%(time)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"]
        },
        {
            "type": "file",
            "filename": "/tmp/roster_%(teamAbbr)s_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"]
        }
    ]

    def resolve_team_config(self):
        """
        Finds the matching team config (ID, slug) for the user-supplied abbreviation.
        """
        teamAbbr = self.opts["teamAbbr"]
        for team in NBA_TEAMS:
            if team["abbr"].lower() == teamAbbr.lower():
                return team
        raise DownloadDataException(f"Team config not found for abbreviation: {teamAbbr}")

    def set_additional_opts(self):
        """
        Fill in default date, time, season if not already present.
        """
        now_utc = datetime.utcnow()  
        now_pst = now_utc.astimezone(pytz.timezone("America/Los_Angeles"))

        self.opts["date"] = now_pst.strftime("%Y-%m-%d")
        self.opts["time"] = now_pst.strftime("%H-%M-%S")

        # Example: '2024-25' for the current year
        season_year = now_pst.year
        default_season = f"{season_year}-{(season_year + 1) % 100:02d}"
        self.opts["season"] = self.opts.get("season", default_season)

    def set_url(self):
        """
        Build the official NBA team roster URL, e.g.:
        https://www.nba.com/team/1610612744/warriors/roster
        """
        team = self.resolve_team_config()
        self.opts["teamId"] = team["teamId"]
        self.opts["slug"] = team["slug"]
        self.url = f"https://www.nba.com/team/{team['teamId']}/{team['slug']}/roster"
        logger.info(f"Resolved roster URL: {self.url}")

    # -------------------------------------------------------------------------
    # Overriding decode_download_content so we can store the raw HTML ourselves.
    # -------------------------------------------------------------------------
    def decode_download_content(self):
        # The base class won't attempt JSON decode because we set download_type=BINARY.
        # We'll just store raw HTML as 'self.html_content'.
        self.html_content = self.raw_response.text

    def validate_download_data(self):
        """
        Confirm we have non-empty HTML from the response.
        """
        if not getattr(self, "html_content", ""):
            raise DownloadDataException("No HTML content retrieved for roster page.")

    def transform_data(self):
        """
        1) Parse the HTML
        2) Find the <script id="__NEXT_DATA__">
        3) Parse JSON from that script
        4) Run Pydantic validation
        5) Build final list of players
        """
        self.step_info("transform", "Starting the transformation step")

        soup = BeautifulSoup(self.html_content, "html.parser")

        # Debug: write entire page for reference
        self._debug_write_html()

        # Debug: write out each <script> in /tmp/debug_scripts/
        self._debug_write_all_scripts(soup)

        # Find the special <script id="__NEXT_DATA__">
        next_data_script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not next_data_script:
            logger.warning("No <script id='__NEXT_DATA__'> found on page.")
            raise DownloadDataException("Could not find __NEXT_DATA__ script on roster page.")

        script_content = next_data_script.string or ""
        if not script_content.strip():
            raise DownloadDataException("__NEXT_DATA__ script was empty. No JSON to parse.")

        # Attempt to parse the raw JSON
        embedded_json = self._parse_json_from_script(script_content)
        # For debugging, write the entire JSON structure
        self._debug_write_embedded_json(embedded_json)

        # Attempt to validate with Pydantic
        # If it fails, we store fallback data but continue or raise.
        validated_data = None
        try:
            validated_data = NextData(**embedded_json)
        except ValidationError as exc:
            logger.error(f"JSON structure did not match expected schema: {exc}")
            # Optionally store the raw JSON in a fallback location
            self._store_fallback_json(embedded_json, reason="ValidationError")
            # You can decide whether to raise or proceed with partial data
            # For now, let's raise an exception so we’re alerted via Sentry
            raise DownloadDataException("JSON schema mismatch, see logs for details.")

        # If we got here, the JSON matches our schema.
        roster_items = validated_data.props.pageProps.team.roster

        # Convert the Pydantic objects into final data dicts
        players = []
        for item in roster_items:
            players.append({
                "name": item.PLAYER,
                "slug": item.PLAYER_SLUG,
                "playerId": item.PLAYER_ID,
                "number": item.NUM,
                "position": item.POSITION,
            })

        # Build final data object
        now_utc = datetime.utcnow()
        self.data = {
            "teamAbbr": self.opts["teamAbbr"],
            "teamId": self.opts["teamId"],
            "timestamp": now_utc.isoformat(),
            "players": players,
            "season": self.opts["season"],
            "date": self.opts["date"],
            "time": self.opts["time"],
        }

        logger.info(f"Found {len(players)} players for {self.opts['teamAbbr']}!")

    def get_scraper_stats(self):
        """
        Additional fields in the final SCRAPER_STATS log line.
        """
        return {
            "teamAbbr": self.opts["teamAbbr"],
            "playerCount": len(self.data.get("players", [])),
        }

    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------
    def _parse_json_from_script(self, script_content):
        """
        If there's a preamble, strip until the first '{', then parse as JSON.
        """
        try:
            idx = script_content.find("{")
            if idx >= 0:
                script_content = script_content[idx:]
            return json.loads(script_content)
        except Exception as e:
            raise DownloadDataException(f"Failed parsing JSON: {e}")

    def _debug_write_html(self):
        """
        Write the entire HTML to /tmp/roster_page.html for debugging.
        """
        try:
            with open("/tmp/roster_page.html", "w", encoding="utf-8") as f:
                f.write(self.html_content)
        except Exception as e:
            logger.warning(f"Failed to write /tmp/roster_page.html: {e}")

    def _debug_write_all_scripts(self, soup):
        """
        Write each <script> tag to /tmp/debug_scripts/script_{idx}.txt
        for debugging or offline inspection.
        """
        debug_dir = "/tmp/debug_scripts"
        os.makedirs(debug_dir, exist_ok=True)

        script_tags = soup.find_all("script")
        logger.info(f"Found {len(script_tags)} <script> tags on the page.")

        for idx, tag in enumerate(script_tags):
            content = tag.string or ""
            file_path = os.path.join(debug_dir, f"script_{idx}.txt")
            try:
                with open(file_path, "w", encoding="utf-8") as sf:
                    sf.write(content)
            except Exception as e:
                logger.warning(f"Failed writing {file_path}: {e}")

    def _debug_write_embedded_json(self, data):
        """
        Write the extracted JSON to /tmp/debug_embedded.json
        to confirm structure and debugging.
        """
        try:
            with open("/tmp/debug_embedded.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info("Wrote debug JSON to /tmp/debug_embedded.json")
        except Exception as e:
            logger.warning(f"Failed writing /tmp/debug_embedded.json: {e}")

    def _store_fallback_json(self, data, reason="unknown"):
        """
        If validation fails or something is off, we can store the entire JSON
        so we have it for offline inspection. 
        """
        fallback_dir = "/tmp/fallback_json"
        os.makedirs(fallback_dir, exist_ok=True)

        fallback_filename = (
            f"roster_fallback_{self.opts.get('teamAbbr','NA')}_"
            f"{self.opts.get('date','NA')}_{self.opts.get('time','NA')}_"
            f"{reason}.json"
        )
        fallback_path = os.path.join(fallback_dir, fallback_filename)

        try:
            with open(fallback_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.warning(f"Stored fallback JSON at {fallback_path}")
        except Exception as e:
            logger.warning(f"Failed writing fallback JSON to {fallback_path}: {e}")


##############################################################################
# Optional: GCF Entrypoint
##############################################################################
def gcf_entry(request):
    """
    Example Google Cloud Function entrypoint 
    (if you deploy the scraper as a cloud function).
    """
    teamAbbr = request.args.get("teamAbbr")
    group = request.args.get("group", "prod")

    if not teamAbbr:
        return ("Missing required parameter: teamAbbr", 400)

    opts = {"teamAbbr": teamAbbr, "group": group}
    scraper = GetNbaTeamRoster()
    result = scraper.run(opts)
    return f"TeamRoster run complete for {teamAbbr}. Result: {result}", 200


##############################################################################
# Local CLI usage
##############################################################################
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--teamAbbr", required=True, help="e.g. GSW")
    parser.add_argument("--group", default="test", help="dev, test, prod, etc.")
    args = parser.parse_args()

    scraper = GetNbaTeamRoster()
    scraper.run(vars(args))

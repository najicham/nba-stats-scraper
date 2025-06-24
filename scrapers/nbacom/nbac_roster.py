# scrapers/nbacom/nbac_team_roster.py
"""
NBA.com team roster scraper                               v2.1 - 2025-06-17
--------------------------------------------------------------------------
CLI quick‑start (debug OFF):
    python -m scrapers.nbacom.nbac_team_roster --teamAbbr GSW

Enable debug dumps:
    python -m scrapers.nbacom.nbac_team_roster --teamAbbr GSW --debug 1
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import List, Dict

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ValidationError

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import DownloadDataException
from config.nba_teams import NBA_TEAMS

logger = logging.getLogger("scraper_base")

# ------------------------------------------------------------------ #
# Pydantic models
# ------------------------------------------------------------------ #
class PlayerItem(BaseModel):
    PLAYER: str = Field(...)
    PLAYER_SLUG: str = Field(...)
    PLAYER_ID: int = Field(...)
    NUM: str = Field(...)
    POSITION: str = Field(...)


class Roster(BaseModel):
    roster: List[PlayerItem]


class TeamProps(BaseModel):
    team: Roster


class PageProps(BaseModel):
    pageProps: TeamProps


class NextData(BaseModel):
    props: PageProps


# ------------------------------------------------------------------ #
class GetNbaTeamRoster(ScraperBase):
    """Parses roster JSON embedded in nba.com team pages."""

    required_opts = ["teamAbbr"]
    header_profile: str | None = "data"
    download_type: DownloadType = DownloadType.HTML
    decode_download_data: bool = True

    # master debug flag (can be overridden by opts['debug'])
    debug_enabled: bool = False

    exporters = [
        {
            "type": "file",
            "filename": "/tmp/roster_%(teamAbbr)s_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "gcs",
            "key": "nba/rosters/%(season)s/%(date)s/%(teamAbbr)s_%(time)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
    ]

    # ------------------------------------------------------------ helpers
    def set_additional_opts(self) -> None:
        now = datetime.now(timezone.utc)
        self.opts["date"] = now.strftime("%Y-%m-%d")
        self.opts["time"] = now.strftime("%H-%M-%S")
        self.opts.setdefault("season", f"{now.year}-{(now.year + 1) % 100:02d}")

        # interpret --debug flag (truthy → enable debug helpers)
        dbg = str(self.opts.get("debug", "0")).lower()
        self.debug_enabled = dbg in {"1", "true", "yes"}

    def _team_cfg(self) -> dict:
        for t in NBA_TEAMS:
            if t["abbr"].lower() == self.opts["teamAbbr"].lower():
                return t
        raise DownloadDataException(f"Unknown teamAbbr: {self.opts['teamAbbr']}")

    # ------------------------------------------------------------ URL
    def set_url(self) -> None:
        cfg = self._team_cfg()
        self.opts["teamId"] = cfg["teamId"]
        self.url = f"https://www.nba.com/team/{cfg['teamId']}/{cfg['slug']}/roster"
        logger.info("Roster URL: %s", self.url)

    # ------------------------------------------------------------ validation
    def validate_download_data(self) -> None:
        if not self.decoded_data or "<html" not in self.decoded_data.lower():
            raise DownloadDataException("Roster page HTML missing or empty.")

    # ------------------------------------------------------------ transform
    def transform_data(self) -> None:
        soup = BeautifulSoup(self.decoded_data, "html.parser")

        # Conditional debug dumps
        if self.debug_enabled:
            self._debug_write_html()
            self._debug_write_all_scripts(soup)

        tag = soup.find("script", id="__NEXT_DATA__")
        if not tag or not tag.string:
            raise DownloadDataException("__NEXT_DATA__ script not found.")

        try:
            json_text = tag.string[tag.string.find("{") :]
            raw_json = json.loads(json_text)
            parsed = NextData(**raw_json)
        except (json.JSONDecodeError, ValidationError) as exc:
            if self.debug_enabled:
                self._debug_write_embedded_json(tag.string)
                self._store_fallback_json(tag.string, reason="ValidationError")
            raise DownloadDataException(f"Roster JSON invalid: {exc}")

        roster_items = parsed.props.pageProps.team.roster

        players = [
            {
                "name": p.PLAYER,
                "slug": p.PLAYER_SLUG,
                "playerId": p.PLAYER_ID,
                "number": p.NUM,
                "position": p.POSITION,
            }
            for p in roster_items
        ]

        self.data = {
            "teamAbbr": self.opts["teamAbbr"],
            "teamId": self.opts["teamId"],
            "season": self.opts["season"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "playerCount": len(players),
            "players": players,
        }

        logger.info("Found %d players for %s", len(players), self.opts["teamAbbr"])

    # ------------------------------------------------------------ stats
    def get_scraper_stats(self) -> dict:
        return {"teamAbbr": self.opts["teamAbbr"], "playerCount": self.data["playerCount"]}

    # ------------------------------------------------------------ debug helpers
    def _debug_write_html(self) -> None:
        try:
            with open("/tmp/roster_page.html", "w", encoding="utf-8") as fh:
                fh.write(self.decoded_data)
        except Exception as exc:
            logger.warning("Failed to dump HTML: %s", exc)

    def _debug_write_all_scripts(self, soup: BeautifulSoup) -> None:
        debug_dir = "/tmp/debug_scripts"
        os.makedirs(debug_dir, exist_ok=True)
        for idx, tag in enumerate(soup.find_all("script")):
            path = os.path.join(debug_dir, f"script_{idx}.txt")
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(tag.string or "")
            except Exception as exc:
                logger.warning("Failed to write %s: %s", path, exc)

    def _debug_write_embedded_json(self, text: str) -> None:
        try:
            with open("/tmp/debug_embedded.json", "w", encoding="utf-8") as fh:
                fh.write(text)
        except Exception as exc:
            logger.warning("Failed to write embedded JSON: %s", exc)

    def _store_fallback_json(self, text: str, reason: str = "unknown") -> None:
        fb_dir = "/tmp/fallback_json"
        os.makedirs(fb_dir, exist_ok=True)
        filename = (
            f"roster_fallback_{self.opts.get('teamAbbr','NA')}_"
            f"{self.opts.get('date','NA')}_{self.opts.get('time','NA')}_{reason}.json"
        )
        path = os.path.join(fb_dir, filename)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            logger.warning("Stored fallback JSON at %s", path)
        except Exception as exc:
            logger.warning("Failed to write fallback JSON: %s", exc)


# ---------------------------------------------------------------------- #
# Google Cloud Function entry
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    team = request.args.get("teamAbbr")
    if not team:
        return ("Missing teamAbbr", 400)

    ok = GetNbaTeamRoster().run(
        {
            "teamAbbr": team,
            "group": request.args.get("group", "prod"),
            "debug": request.args.get("debug", "0"),
        }
    )
    return (("Roster scrape failed", 500) if ok is False else ("Scrape ok", 200))


# ---------------------------------------------------------------------- #
# Local CLI usage
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description="Run NBA.com team roster locally")
    cli.add_argument("--teamAbbr", required=True, help="e.g. GSW")
    cli.add_argument("--group", default="test")
    cli.add_argument("--debug", default="0", help="1/true to enable debug dumps")
    GetNbaTeamRoster().run(vars(cli.parse_args()))

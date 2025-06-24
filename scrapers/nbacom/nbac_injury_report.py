# scrapers/nbacom/nbac_injury_report.py
"""
NBA.com Injury Report PDF scraper                       v2 - 2025-06-16
-----------------------------------------------------------------------
Downloads and parses the official Injury Report PDF.  Outputs a list of
records like:

    {
        "date": "03/16/2025",
        "gametime": "7:30 PM ET",
        "matchup": "LAL@BOS",
        "team": "LOS ANGELES LAKERS",
        "player": "James, LeBron",
        "status": "Questionable",
        "reason": "Left ankle soreness"
    }
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import List

from pdfreader import SimplePDFViewer
from pdfreader.viewer.pdfviewer import PageDoesNotExist

from ..scraper_base import DownloadType, ExportMode, ScraperBase
from ..utils.exceptions import DownloadDataException, InvalidRegionDecodeException

logger = logging.getLogger("scraper_base")


class GetNbaComInjuryReport(ScraperBase):
    """Scrapes and parses the daily NBA Injury Report PDF."""

    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #
    required_opts = ["gamedate", "hour"]            # hour must be 1, 5, or 8
    header_profile: str | None = "data"
    download_type: DownloadType = DownloadType.BINARY
    proxy_enabled: bool = True
    no_retry_status_codes = [403]

    exporters = [
        {
            "type": "gcs",
            "key": "nbacom/injury-report/%(season)s/%(gamedate)s/0%(hour)sPM/%(time)s.pdf",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/nbacom_injury_report_%(gamedate)s_%(hour)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts helper
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        now = datetime.now(timezone.utc)
        self.opts["time"] = now.strftime("%H-%M-%S")
        year = int(self.opts["gamedate"][0:4])
        self.opts["season"] = f"{year}-{(year + 1) % 100:02d}"

    # ------------------------------------------------------------------ #
    # Option validation
    # ------------------------------------------------------------------ #
    def validate_opts(self) -> None:
        super().validate_opts()
        if self.opts["hour"] not in {"1", "5", "8"}:
            raise DownloadDataException("hour must be 1, 5, or 8")

    # ------------------------------------------------------------------ #
    # URL builder
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        gd = self.opts["gamedate"]
        hour = self.opts["hour"]
        self.url = (
            f"https://ak-static.cms.nba.com/referee/injury/"
            f"Injury-Report_{gd}_0{hour}PM.pdf"
        )
        logger.info("Injury Report URL: %s", self.url)

    # ------------------------------------------------------------------ #
    # Only save if we parsed at least 1 record
    # ------------------------------------------------------------------ #
    def should_save_data(self) -> bool:
        return isinstance(self.data, list) and len(self.data) > 0

    # ------------------------------------------------------------------ #
    # Decode PDF -> self.data
    # ------------------------------------------------------------------ #
    def decode_download_content(self) -> None:
        content = self.raw_response.content

        if b"not accessible in this region" in content.lower():
            raise InvalidRegionDecodeException("PDF blocked in this region.")
        if b"%PDF" not in content[:1024]:
            raise InvalidRegionDecodeException("Response is not a PDF.")

        records: List[dict] = []
        temp = {
            "date": "",
            "gametime": "",
            "matchup": "",
            "team": "",
            "player": "",
            "status": "",
            "next_state": "",
        }

        viewer = SimplePDFViewer(content)
        page_num = 0
        try:
            while True:
                viewer.render()
                self._parse_strings(viewer.canvas.strings, temp, records)
                viewer.next()
                page_num += 1
        except PageDoesNotExist:
            logger.info(
                "Finished PDF after %d pages, parsed %d records.", page_num, len(records)
            )

        if not records:
            raise DownloadDataException("Parsed 0 records from PDF.")
        self.data = records

    # ------------------------------------------------------------------ #
    # String parser with full state machine
    # ------------------------------------------------------------------ #
    def _parse_strings(self, strings: List[str], temp: dict, out_list: List[dict]) -> None:
        for s in strings:
            # ---------------- Continued-field states ------------------
            if temp["next_state"] == "team":
                # Accumulate multi-token team names until we hit a new logical token
                if "@" not in s and "," not in s and not re.match(r"\d{1,2}:\d{2}", s):
                    temp["team"] = (temp["team"] + " " + s).strip()
                    continue
                # Fall through to evaluate the new token as fresh input

            if temp["next_state"] == "player":
                if re.match(r".*, .*", s):
                    temp["player"] = s
                    temp["next_state"] = "status"
                    continue

            if temp["next_state"] == "status":
                temp["status"] = s
                temp["next_state"] = "reason"
                continue

            if temp["next_state"] == "reason":
                out_list.append(
                    {
                        "date": temp["date"],
                        "gametime": temp["gametime"],
                        "matchup": temp["matchup"],
                        "team": temp["team"],
                        "player": temp["player"],
                        "status": temp["status"],
                        "reason": s,
                    }
                )
                temp["next_state"] = ""
                continue

            # ---------------- Fresh-record pattern matches -------------
            if re.match(r"\d{2}/\d{2}/\d{4}", s):           # Date
                temp.update(date=s, next_state="gametime")
            elif re.match(r"\d{1,2}:\d{2}", s):             # Game time
                temp.update(gametime=s, next_state="matchup")
            elif "@" in s:                                  # Matchup
                temp.update(matchup=s, next_state="team", team="")
            elif re.match(r".*, .*", s):                    # Player
                temp.update(player=s, next_state="status")
            # If we are in 'team' state but token didn't match earlier,
            # it might be the first chunk of a multi-word team name.
            elif temp["next_state"] == "team":
                temp["team"] = s

    # ------------------------------------------------------------------ #
    # Stats line
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "gamedate": self.opts["gamedate"],
            "hour": self.opts["hour"],
            "records": len(self.data) if isinstance(self.data, list) else 0,
        }


# ---------------------------------------------------------------------- #
# Cloud Function entry
# ---------------------------------------------------------------------- #
def gcf_entry(request):  # type: ignore[valid-type]
    gd = request.args.get("gamedate")
    hr = request.args.get("hour")
    if not gd or not hr:
        return ("Missing 'gamedate' or 'hour'", 400)

    ok = GetNbaComInjuryReport().run(
        {"gamedate": gd, "hour": hr, "group": request.args.get("group", "prod")}
    )
    return (("Injury PDF scrape failed", 500) if ok is False else ("Scrape ok", 200))


# ---------------------------------------------------------------------- #
# CLI helper
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("--gamedate", required=True, help="YYYY-MM-DD")
    cli.add_argument("--hour", required=True, choices=["1", "5", "8"])
    cli.add_argument("--group", default="test")
    GetNbaComInjuryReport().run(vars(cli.parse_args()))

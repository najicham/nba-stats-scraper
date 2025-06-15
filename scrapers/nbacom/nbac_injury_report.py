# scrapers/nba_com_injury_report.py

import os
import re
import sys
import logging
from pdfreader import SimplePDFViewer
from pdfreader.viewer.pdfviewer import PageDoesNotExist

from .scraper_base import ScraperBase, DownloadType, ExportMode
from .utils.exceptions import InvalidRegionDecodeException, DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaComInjuryReport(ScraperBase):
    """
    Scraper for the NBA.com Injury Report PDF.

    Usage example (local CLI):
      python nba_com_injury_report.py --gamedate=2022-01-03 --hour=8
    """

    # Required options
    required_opts = ["gamedate", "hour"]
    # Additional (auto-set 'season' if you want it derived from gamedate)
    additional_opts = ["nba_season_from_gamedate"]

    # We'll parse a PDF manually, so treat raw response as BINARY
    download_type = DownloadType.BINARY

    # If we want a proxy, set proxy_enabled = True
    proxy_enabled = True

    # Skip retry on 403
    no_retry_status_codes = [403]

    # Define exporters:
    # 1) GCS: store the raw PDF
    # 2) File: store the *parsed* data from self.data
    exporters = [
        {
            "type": "gcs",
            "key": "nbacom/injury-report/%(season)s/%(gamedate)s/0%(hour)sPM/%(time)s.pdf",
            "export_mode": ExportMode.RAW,  # raw PDF content
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacominjuryreport.json",
            "export_mode": ExportMode.DATA,  # final parsed data from self.data
            "pretty_print": True,
            "groups": ["dev", "file"],
        },
    ]

    def validate_opts(self):
        """
        Ensure required options. 
        hour must be '1', '5', or '8', for example.
        """
        super().validate_opts()
        valid_hours = ["1", "5", "8"]
        if self.opts["hour"] not in valid_hours:
            logger.error("Invalid hour %s. Must be one of %s", self.opts["hour"], valid_hours)
            raise DownloadDataException("[hour] must be 1, 5, or 8")

    def set_url(self):
        """
        Build the final PDF URL from 'gamedate' and 'hour'.
        Example: 
          https://ak-static.cms.nba.com/referee/injury/Injury-Report_2023-01-10_01PM.pdf
        """
        gamedate = self.opts["gamedate"]
        hour_str = self.opts["hour"]  # '1', '5', or '8'
        self.url = (
            f"https://ak-static.cms.nba.com/referee/injury/Injury-Report_{gamedate}_0{hour_str}PM.pdf"
        )
        logger.info("Injury Report PDF URL set to: %s", self.url)

    def should_save_data(self):
        """
        We only export if we have parsed at least 1 record in self.data.
        """
        record_count = len(self.data) if isinstance(self.data, list) else 0
        logger.info("should_save_data? Found %d records.", record_count)
        return record_count > 0

    def decode_download_content(self):
        """
        Parse the PDF from self.raw_response.content.
        Store the resulting list of records in self.data.
        """
        try:
            # Check if the content indicates a region block
            if b"not accessible in this region" in self.raw_response.content:
                logger.error("Region block detected in PDF content.")
                raise InvalidRegionDecodeException("PDF blocked in this region.")

            # Quick check if the response is recognized as PDF
            if b"PDF" not in self.raw_response.content[:1024]:
                logger.error("Download content does not appear to be PDF.")
                raise InvalidRegionDecodeException("Content is not recognized as PDF.")

            data = []
            current_record = {
                "date": "",
                "gametime": "",
                "matchup": "",
                "team": "",
                "status": "",
                "player": "",
                "next_is": ""
            }

            logger.debug("Starting PDF parse for Injury Report.")
            viewer = SimplePDFViewer(self.raw_response.content)
            page_count = 0

            while True:
                viewer.render()
                page_strings = viewer.canvas.strings
                self.parse_strings(page_strings, current_record, data)
                viewer.next()
                page_count += 1

        except PageDoesNotExist:
            # End of PDF
            logger.info("Reached end of PDF after %d pages.", page_count)
            if data:
                self.data = data  # store final parsed data
                logger.info("Parsed a total of %d injury records.", len(data))
            else:
                logger.error("Parsed 0 records. PDF parse error.")
                raise DownloadDataException("PDF parse error: no data found.")

        except Exception as ex:
            logger.exception("Unexpected error parsing PDF.")
            raise DownloadDataException(f"PDF parse unexpected error: {ex}")

    def parse_strings(self, page_strings, current_record, data):
        """
        Process each string on the PDF page. 
        We build up a record and append to 'data' once we have all fields.
        """
        for string in page_strings:
            if current_record["next_is"] == "player":
                # e.g. "LastName, FirstName"
                if re.match(r".*, .*", string):
                    current_record["player"] = string
                    current_record["next_is"] = "status"
                else:
                    current_record["next_is"] = "newline"

            elif current_record["next_is"] == "gametime":
                current_record["gametime"] = string
                current_record["next_is"] = "matchup"

            elif current_record["next_is"] == "matchup":
                current_record["matchup"] = string
                current_record["next_is"] = "team"

            elif current_record["next_is"] == "team":
                current_record["team"] = string
                current_record["next_is"] = "player"

            elif current_record["next_is"] == "status":
                current_record["status"] = string
                current_record["next_is"] = "reason"

            elif current_record["next_is"] == "reason":
                # finalize a record
                data.append({
                    "date": current_record["date"],
                    "gametime": current_record["gametime"],
                    "matchup": current_record["matchup"],
                    "team": current_record["team"],
                    "player": current_record["player"],
                    "status": current_record["status"],
                    "reason": string
                })
                current_record["next_is"] = "newline"

            # If we detect a date like "MM/DD/YYYY"
            elif re.match(r"[\d]{2}/[\d]{2}/[\d]{4}", string):
                current_record["date"] = string
                current_record["next_is"] = "gametime"

            # If the string looks like "LastName, FirstName"
            elif re.match(r".*, .*", string):
                current_record["player"] = string
                current_record["next_is"] = "status"

            # If it looks like "TEAM@TEAM"
            elif re.match(r".*@.*", string):
                current_record["matchup"] = string
                current_record["next_is"] = "team"

            # "HH:MM (ET)" or similar
            elif current_record["next_is"] == "newline" and re.match(r"[\d]+:[\d]+[\s].+", string):
                current_record["gametime"] = string
                current_record["next_is"] = "matchup"

            # Possibly a multi-word team name: "Los Angeles Lakers"
            elif current_record["next_is"] == "newline" and re.match(r"[\w]+\s+[\w]+", string):
                current_record["team"] = string
                current_record["next_is"] = ""

    def get_scraper_stats(self):
        """
        Return # of parsed records, plus gamedate/hour used.
        """
        records_found = len(self.data) if isinstance(self.data, list) else 0
        return {
            "records_found": records_found,
            "gamedate": self.opts.get("gamedate", "unknown"),
            "hour": self.opts.get("hour", "unknown"),
        }


##############################################################################
# Cloud Function Entry Point
##############################################################################
def gcf_entry(request):
    """
    Google Cloud Function (HTTP) entry point.
    Example request: 
      GET .../NbaComInjuryReport?gamedate=2023-01-03&hour=8&group=prod
    """
    gamedate = request.args.get("gamedate", "2023-01-01")
    hour = request.args.get("hour", "8")
    group = request.args.get("group", "prod")

    opts = {
        "gamedate": gamedate,
        "hour": hour,
        "group": group
    }

    scraper = GetNbaComInjuryReport()
    result = scraper.run(opts)

    return f"InjuryReport run complete. Found result: {result}", 200


##############################################################################
# Local CLI Usage
##############################################################################
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run NBA.com Injury Report locally")
    parser.add_argument("--gamedate", required=True, help="e.g. 2023-01-03")
    parser.add_argument("--hour", default="8", help="Possible values: 1, 5, or 8")
    parser.add_argument("--group", default="test", help="Which group exporters to run, e.g. dev/test/prod")
    args = parser.parse_args()

    opts = vars(args)

    scraper = GetNbaComInjuryReport()
    scraper.run(opts)

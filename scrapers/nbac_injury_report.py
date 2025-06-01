# scrapers/nba_com_injury_report.py

import re
import sys
import logging

from pdfreader import SimplePDFViewer
from pdfreader.viewer.pdfviewer import PageDoesNotExist

from .scraper_base import ScraperBase
from .utils.exceptions import InvalidRegionDecodeException, DownloadDataException

logger = logging.getLogger("scraper_base")


class GetNbaComInjuryReport(ScraperBase):
    """
    Scraper for the NBA.com Injury Report PDF.

    Usage example:
      get_nbacominjuryreport --gamedate=2022-01-03 --hour=8
    """

    required_opts = ["gamedate", "hour"]
    additional_opts = ["nba_season_from_gamedate"]

    # PDF URL template, formatted with %(gamedate)s and %(hour)s
    url_template = (
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_%(gamedate)s_0%(hour)sPM.pdf"
    )

    use_proxy = True
    no_retry_error_codes = [403]

    exporters = [
        {
            "type": "gcs", 
            "key": "nbacom/injury-report/%(season)s/%(gamedate)s/0%(hour)sPM/%(time)s.json",
            "groups": ["prod", "s3", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/getnbacominjuryreport",
            "test": True,
            "groups": ["dev", "file1"],
        },
    ]

    def validate_opts(self):
        """
        Validate required options. For instance, hour must be '1', '5', or '8'.
        If the NBA changes their times, you might store valid hours in a config or ENV variable.
        """
        super().validate_opts()
        valid_hours = ["1", "5", "8"]
        if self.opts["hour"] not in valid_hours:
            logger.error("Invalid hour %s. Must be one of %s", self.opts["hour"], valid_hours)
            raise DownloadDataException("[hour] must be 1, 5, or 8")

    def set_url(self):
        """Build the final PDF URL from the opts using the template."""
        self.url = self.url_template % self.opts
        logger.info("Injury Report PDF URL set to: %s", self.url)

    def should_save_data(self):
        """
        We only export if self.data is non-empty (i.e. at least 1 record).
        """
        to_save = bool(self.data)
        logger.info("should_save_data? %s. Found %d records.", to_save, len(self.data) if self.data else 0)
        return to_save

    def decode_download_data(self):
        """
        Parse the PDF content. Raise exceptions if region is blocked or PDF is invalid.
        """
        try:
            if b"not accessible in this region" in self.download.content:
                logger.error("Region block detected in PDF content.")
                raise InvalidRegionDecodeException("PDF blocked in this region.")
            
            # Quick check if the response is not recognized as PDF
            if b"PDF" not in self.download.content[:1024]:
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
            viewer = SimplePDFViewer(self.download.content)
            page_count = 0
            while True:
                viewer.render()
                page_strings = viewer.canvas.strings
                self.parse_strings(page_strings, current_record, data)
                viewer.next()
                page_count += 1

        except PageDoesNotExist:
            logger.info("Reached end of PDF after %d pages.", page_count)
            self.stats["pdf_pages"] = page_count  # store page_count in self.stats for final logging

            if data:
                self.data = data
                logger.info("Parsed a total of %d injury records.", len(data))
            else:
                logger.error("Parsed 0 records. PDF parse error.")
                raise DownloadDataException("PDF parse error: no data found.")

        except Exception as ex:
            logger.exception("Unexpected error parsing PDF.")
            raise DownloadDataException(f"PDF parse unexpected error: {ex}")

    def parse_strings(self, page_strings, current_record, data):
        """
        Iterate over each string on the page. Decide which field to populate
        based on current_record["next_is"] or pattern matching.
        """
        for string in page_strings:
            if current_record["next_is"] == "player":
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

            # If the string looks like "TEAM@TEAM"
            elif re.match(r".*@.*", string):
                current_record["matchup"] = string
                current_record["next_is"] = "team"

            # "HH:MM (ET)" or similar
            elif current_record["next_is"] == "newline" and re.match(r"[\d]+:[\d]+[\s].+", string):
                current_record["gametime"] = string
                current_record["next_is"] = "matchup"

            # Possibly a team name: "Los Angeles Lakers"
            elif current_record["next_is"] == "newline" and re.match(r"[\w]+\s+[\w]+", string):
                current_record["team"] = string
                current_record["next_is"] = ""

    ##################################################################
    # Override get_scraper_stats() to include # of PDF pages & record count
    ##################################################################
    def get_scraper_stats(self):
        """
        Return fields for the final SCRAPER_STATS line. We'll log how many records we found,
        how many pages we parsed, plus the gamedate/hour.
        """
        # The data we store is a list of dicts (each representing an injury record)
        record_count = len(self.data) if isinstance(self.data, list) else 0
        pdf_pages = self.stats.get("pdf_pages", 0)

        return {
            "records_found": record_count,
            "pdf_pages": pdf_pages,
            "gamedate": self.opts.get("gamedate", "unknown"),
            "hour": self.opts.get("hour", "unknown"),
        }

"""
File: scrapers/nbacom/nbac_injury_report.py

NBA.com Injury Report PDF scraper - FIXED v16 - 2025-10-15
----------------------------------------------------------------
Two-file approach using validated parser module for 99-100% accuracy.
NOW HANDLES EMPTY PDFS GRACEFULLY (All-Star weekend, off-days, etc.)

This scraper handles PDF extraction and exports, while delegating
the parsing logic to the injury_parser module that contains the
validated multi-line detection logic.

FIXED: Empty PDFs (0 records) are now treated as valid and saved,
not as errors. This is expected during All-Star weekend and off-days.

Usage examples:
  python tools/fixtures/capture.py nbac_injury_report \
      --gamedate 20220517 --hour 4 --period PM --debug
"""

from __future__ import annotations

import logging
import re
import os
import sys
import time
import tempfile
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Set
import json

import pdfplumber
from collections import Counter

# Support both module execution (python -m) and direct execution
try:
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException, InvalidRegionDecodeException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException, InvalidRegionDecodeException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

# Import the validated parser module
try:
    from .injury_parser import InjuryReportParser
except ImportError:
    # Fallback for development - assume injury_parser.py is in same directory
    sys.path.insert(0, os.path.dirname(__file__))
    from injury_parser import InjuryReportParser

# Notification system imports
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger("scraper_base")


class GetNbaComInjuryReport(ScraperBase, ScraperFlaskMixin):
    """Simplified NBA Injury Report PDF scraper using validated parser module."""

    # Flask Mixin Configuration
    scraper_name = "nbac_injury_report"
    required_params = ["gamedate", "hour", "period"]
    optional_params = {"minute": "00"}  # Default to :00 for new URL format

    # Original scraper config
    required_opts = ["gamedate", "hour", "period"]
    header_profile: str | None = "data"
    download_type: DownloadType = DownloadType.BINARY
    proxy_enabled: bool = True
    max_retries_decode = 2
    no_retry_status_codes = [404, 422]
    treat_max_retries_as_success = [403]

    # Exporters
    # NOTE: Order matters! First GCS exporter's path is published to Pub/Sub for Phase 2.
    # JSON exporter must be first so Phase 2 processors receive the correct file path.
    exporters = [
        {"type": "gcs", "key": GCSPathBuilder.get_path("nba_com_injury_report_data"),
         "export_mode": ExportMode.DATA, "groups": ["prod", "gcs"]},  # PRIMARY: JSON for Phase 2
        {"type": "gcs", "key": GCSPathBuilder.get_path("nba_com_injury_report_pdf_raw"),
         "export_mode": ExportMode.RAW, "groups": ["prod", "gcs"]},  # SECONDARY: PDF archive
        {"type": "file", "filename": "/tmp/nbacom_injury_report_%(gamedate)s_%(hour)s.json",
         "export_mode": ExportMode.DATA, "pretty_print": True, "groups": ["dev", "test"]},
        {"type": "file", "filename": "/tmp/raw_%(run_id)s.pdf",
         "export_mode": ExportMode.RAW, "groups": ["capture"]},
        {"type": "file", "filename": "/tmp/exp_%(run_id)s.json",
         "export_mode": ExportMode.DATA, "pretty_print": True, "groups": ["capture"]},
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialize the validated parser
        self.injury_parser = InjuryReportParser(logger=logger)

    def get_no_data_response(self) -> dict:
        """
        Override base class to return proper structured response when
        PDF is unavailable (403/404). This ensures GCS files have
        metadata even when no injury data is available.
        """
        # Ensure opts are set (may be called before full initialization)
        gamedate = self.opts.get("gamedate", "unknown")
        hour = self.opts.get("hour", "0")
        period = self.opts.get("period", "PM")
        hour24 = self.opts.get("hour24", "00")
        season = self.opts.get("season", "unknown")
        scrape_time = self.opts.get("time", "00-00-00")

        return {
            "metadata": {
                "gamedate": gamedate,
                "hour": hour,
                "period": period,
                "hour24": hour24,
                "season": season,
                "scrape_time": scrape_time,
                "run_id": self.run_id,
                "is_empty_report": True,
                "no_data_reason": "pdf_unavailable"  # Distinguishes from genuinely empty PDFs
            },
            "parsing_stats": {
                "total_records": 0,
                "overall_confidence": 1.0,
                "status_counts": {},
                "confidence_distribution": {},
                "parsing_stats": {
                    "total_lines": 0,
                    "player_lines": 0,
                    "merged_multiline": 0,
                    "unparsed_count": 0
                },
                "unparsed_lines_sample": []
            },
            "records": []
        }

    def sleep_before_retry(self):
        """Fast retry strategy - only 2 seconds between attempts."""
        sleep_seconds = 2
        logger.warning("Quick retry in %.1f seconds...", sleep_seconds)
        time.sleep(sleep_seconds)

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        now = datetime.now(timezone.utc)
        self.opts["time"] = now.strftime("%H-%M-%S")
        year = int(self.opts["gamedate"][0:4])
        self.opts["season"] = f"{year}-{(year + 1) % 100:02d}"

        # Set default minute if not provided (for new URL format)
        if "minute" not in self.opts or self.opts["minute"] is None:
            self.opts["minute"] = "00"

        # Calculate hour24
        hour_12 = int(self.opts["hour"])
        period = self.opts["period"].upper()

        if period == "AM":
            hour_24 = 0 if hour_12 == 12 else hour_12
        else:
            hour_24 = 12 if hour_12 == 12 else hour_12 + 12

        self.opts["hour24"] = f"{hour_24:02d}"

    def validate_opts(self) -> None:
        super().validate_opts()
        try:
            hour = int(self.opts["hour"])
            if not (1 <= hour <= 12):
                raise DownloadDataException("hour must be between 1 and 12")
        except ValueError:
            raise DownloadDataException("hour must be a valid number")

        if str(self.opts["period"]).upper() not in {"AM", "PM"}:
            raise DownloadDataException("period must be AM or PM")

        # Validate minute if provided (optional parameter)
        if "minute" in self.opts and self.opts["minute"] is not None:
            try:
                minute = int(self.opts["minute"])
                if not (0 <= minute <= 59):
                    raise DownloadDataException("minute must be between 0 and 59")
            except ValueError:
                raise DownloadDataException("minute must be a valid number")

    def set_url(self) -> None:
        gd = self.opts["gamedate"]
        if "-" not in gd:
            formatted_date = f"{gd[0:4]}-{gd[4:6]}-{gd[6:8]}"
        else:
            formatted_date = gd

        hour = str(self.opts["hour"]).zfill(2)
        period = str(self.opts["period"]).upper()
        minute = str(self.opts.get("minute", "00")).zfill(2)

        # Determine URL format based on date
        # NBA.com changed URL format around Dec 23, 2025 to include minutes
        # Old format: Injury-Report_2025-12-22_06PM.pdf
        # New format: Injury-Report_2025-12-31_06_00PM.pdf
        try:
            # Parse gamedate to determine which format to use
            if "-" in formatted_date:
                date_obj = datetime.strptime(formatted_date, "%Y-%m-%d").date()
            else:
                date_obj = datetime.strptime(formatted_date, "%Y%m%d").date()

            # Cutoff date: Dec 23, 2025 (when NBA.com changed format)
            cutoff_date = datetime(2025, 12, 23).date()

            if date_obj >= cutoff_date:
                # New format with minutes (post-Dec 22, 2025)
                self.url = (
                    f"https://ak-static.cms.nba.com/referee/injury/"
                    f"Injury-Report_{formatted_date}_{hour}_{minute}{period}.pdf"
                )
            else:
                # Old format without minutes (pre-Dec 23, 2025)
                self.url = (
                    f"https://ak-static.cms.nba.com/referee/injury/"
                    f"Injury-Report_{formatted_date}_{hour}{period}.pdf"
                )
        except Exception as e:
            # Fallback to new format if date parsing fails
            logger.warning(f"Failed to parse date {formatted_date}, using new URL format: {e}")
            self.url = (
                f"https://ak-static.cms.nba.com/referee/injury/"
                f"Injury-Report_{formatted_date}_{hour}_{minute}{period}.pdf"
            )

        logger.info("Injury Report URL: %s", self.url)

    def should_save_data(self) -> bool:
        """
        FIXED: Allow saving empty reports.
        Empty PDFs are valid during All-Star weekend, off-days, etc.
        """
        return (isinstance(self.data, dict) and 
                isinstance(self.data.get('records'), list))
        # OLD CODE REMOVED: len(self.data.get('records', [])) > 0

    def decode_download_content(self) -> None:
        """Simplified PDF parsing using validated parser module."""
        content = self.raw_response.content

        # Basic PDF validation
        if b"not accessible in this region" in content.lower():
            logger.error("PDF blocked in region for gamedate %s", self.opts["gamedate"])
            try:
                notify_error(
                    title="NBA.com Injury Report Region Blocked",
                    message=f"Injury report PDF not accessible in this region for {self.opts['gamedate']}",
                    details={
                        'gamedate': self.opts['gamedate'],
                        'hour': self.opts['hour'],
                        'period': self.opts['period'],
                        'url': self.url
                    },
                    processor_name="NBA.com Injury Report Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise InvalidRegionDecodeException("PDF blocked in this region.")
            
        if b"%PDF" not in content[:1024]:
            logger.error("Response is not a PDF for gamedate %s", self.opts["gamedate"])
            try:
                notify_error(
                    title="NBA.com Injury Report Invalid PDF",
                    message=f"Response is not a valid PDF for {self.opts['gamedate']}",
                    details={
                        'gamedate': self.opts['gamedate'],
                        'hour': self.opts['hour'],
                        'period': self.opts['period'],
                        'url': self.url,
                        'content_size': len(content),
                        'content_preview': content[:200].decode('utf-8', errors='ignore')
                    },
                    processor_name="NBA.com Injury Report Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise InvalidRegionDecodeException("Response is not a PDF.")

        logger.info("PDF Content size: %d bytes", len(content))

        # Save content to temp file for pdfplumber
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            with pdfplumber.open(temp_file_path) as pdf:
                # Extract all text from all pages
                full_text = ""
                for page_num, page in enumerate(pdf.pages):
                    page_text = page.extract_text(
                        x_tolerance=2, y_tolerance=2, layout=False,
                        x_density=7.25, y_density=13
                    )
                    if page_text:
                        full_text += page_text + "\n"
                
                logger.info(f"Extracted text: {len(full_text)} characters")
                
                # Use the validated parser module
                records = self.injury_parser.parse_text_content(full_text)
                logger.info("Parsing complete: %d records found", len(records))

        except Exception as e:
            logger.error("Failed to extract text from PDF for gamedate %s: %s", self.opts["gamedate"], e)
            try:
                notify_error(
                    title="NBA.com Injury Report PDF Extraction Failed",
                    message=f"pdfplumber failed to extract text for {self.opts['gamedate']}: {str(e)}",
                    details={
                        'gamedate': self.opts['gamedate'],
                        'hour': self.opts['hour'],
                        'period': self.opts['period'],
                        'pdf_size_bytes': len(content),
                        'error': str(e),
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Injury Report Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"PDF text extraction failed: {e}") from e
        finally:
            os.unlink(temp_file_path)

        # Enhanced debug output with parser statistics
        debug_file = f"/tmp/debug_injury_report_text_{self.run_id}.txt"
        try:
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(full_text)
                
                # Add parser statistics
                parser_stats = self.injury_parser.get_parsing_stats()
                f.write(f"\n\n=== PARSING STATISTICS ===\n")
                f.write(f"Total lines processed: {parser_stats['parsing_stats']['total_lines']}\n")
                f.write(f"Player lines found: {parser_stats['parsing_stats']['player_lines']}\n") 
                f.write(f"Multi-line injuries merged: {parser_stats['parsing_stats']['merged_multiline']}\n")
                f.write(f"Unparsed lines: {parser_stats['parsing_stats']['unparsed_count']}\n")
                
                f.write(f"\n=== PARSED RECORDS ({len(records)}) ===\n")
                for i, record in enumerate(records):
                    confidence = record.get('confidence', 'N/A')
                    f.write(f"{i+1}. {record['player']} ({record['team']}) {record['matchup']} - {record['reason']} (conf: {confidence})\n")
                
                # Show unparsed lines for monitoring
                if parser_stats.get('unparsed_lines_sample'):
                    f.write(f"\n=== UNPARSED LINES SAMPLE ===\n")
                    for i, line in enumerate(parser_stats['unparsed_lines_sample']):
                        f.write(f"{i+1}. {line}\n")
                        
            logger.info("Enhanced debug output saved to: %s", debug_file)
        except Exception as e:
            logger.warning("Failed to save debug text: %s", e)

        # FIXED: Handle empty PDFs gracefully
        if not records:
            logger.warning("Parsed 0 records from PDF for gamedate %s - PDF may be empty (All-Star weekend, off-day, or no injuries)", 
                          self.opts["gamedate"])
            
            # Create valid empty report structure
            enhanced_output = {
                "metadata": {
                    "gamedate": self.opts["gamedate"],
                    "hour": self.opts["hour"],
                    "period": self.opts["period"],
                    "hour24": self.opts["hour24"],
                    "season": self.opts["season"],
                    "scrape_time": self.opts["time"],
                    "run_id": self.run_id,
                    "is_empty_report": True  # Flag for empty reports
                },
                "parsing_stats": {
                    "total_records": 0,
                    "overall_confidence": 1.0,  # High confidence that it's genuinely empty
                    "status_counts": {},
                    "confidence_distribution": {},
                    **self.injury_parser.get_parsing_stats()
                },
                "records": []
            }
            
            self.data = enhanced_output
            self.decoded_data = enhanced_output
            
            # INFO level logging instead of ERROR - this is expected
            logger.info("Successfully processed empty injury report (no players listed) - valid for All-Star weekend or off-days")
            
            # Don't send critical error notification for empty PDFs
            # This is expected behavior during All-Star weekend, off-days, etc.
            return  # Don't raise exception - empty reports are valid
        
        # Calculate additional useful stats from records (non-empty reports)
        status_counts = {
            status: sum(1 for r in records if r.get('status') == status)
            for status in ['Out', 'Questionable', 'Doubtful', 'Probable', 'Available']
        }
        
        confidence_distribution = {}
        for record in records:
            conf = record.get('confidence', 0.0)
            bucket = f"{int(conf * 10) * 10}%"
            confidence_distribution[bucket] = confidence_distribution.get(bucket, 0) + 1
        
        # Create enhanced output with metadata and parsing stats
        enhanced_output = {
            "metadata": {
                "gamedate": self.opts["gamedate"],
                "hour": self.opts["hour"],
                "period": self.opts["period"],
                "hour24": self.opts["hour24"],
                "season": self.opts["season"],
                "scrape_time": self.opts["time"],
                "run_id": self.run_id,
                "is_empty_report": False  # Flag for non-empty reports
            },
            "parsing_stats": {
                "total_records": len(records),
                "overall_confidence": self._calculate_overall_confidence_for_records(records),
                "status_counts": status_counts,
                "confidence_distribution": confidence_distribution,
                **self.injury_parser.get_parsing_stats()
            },
            "records": records
        }
        
        self.data = enhanced_output
        self.decoded_data = enhanced_output
        
        # Check parsing quality and send notifications if needed
        overall_confidence = enhanced_output['parsing_stats']['overall_confidence']
        parser_stats = self.injury_parser.get_parsing_stats()
        
        # Warning for low overall confidence
        confidence_threshold = float(os.environ.get('INJURY_REPORT_CONFIDENCE_THRESHOLD', '0.6'))
        if overall_confidence < confidence_threshold:
            logger.warning("Low overall confidence (%.3f) for gamedate %s", overall_confidence, self.opts["gamedate"])
            try:
                notify_warning(
                    title="NBA.com Injury Report Low Confidence",
                    message=f"Low parsing confidence ({overall_confidence:.3f}) for {self.opts['gamedate']}",
                    details={
                        'gamedate': self.opts['gamedate'],
                        'hour': self.opts['hour'],
                        'period': self.opts['period'],
                        'overall_confidence': overall_confidence,
                        'threshold': confidence_threshold,
                        'total_records': len(records),
                        'unparsed_count': parser_stats['parsing_stats']['unparsed_count'],
                        'confidence_distribution': confidence_distribution
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        
        # Warning for high unparsed line count
        unparsed_threshold = int(os.environ.get('INJURY_REPORT_UNPARSED_THRESHOLD', '20'))
        unparsed_count = parser_stats['parsing_stats']['unparsed_count']
        if unparsed_count > unparsed_threshold:
            logger.warning("High unparsed line count (%d) for gamedate %s", unparsed_count, self.opts["gamedate"])
            try:
                notify_warning(
                    title="NBA.com Injury Report High Unparsed Lines",
                    message=f"High unparsed line count ({unparsed_count}) for {self.opts['gamedate']}",
                    details={
                        'gamedate': self.opts['gamedate'],
                        'hour': self.opts['hour'],
                        'period': self.opts['period'],
                        'unparsed_count': unparsed_count,
                        'threshold': unparsed_threshold,
                        'total_lines': parser_stats['parsing_stats']['total_lines'],
                        'total_records': len(records),
                        'unparsed_sample': parser_stats.get('unparsed_lines_sample', [])[:5]
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        
        logger.info("Successfully parsed %d injury records with enhanced metadata", len(records))

    def _calculate_overall_confidence_for_records(self, records: List[Dict]) -> float:
        """Calculate overall confidence for a list of records (used during parsing)."""
        if not records:
            return 1.0  # FIXED: Empty reports have high confidence (genuinely empty)
        
        # Start with average individual confidence
        avg_confidence = sum(r.get('confidence', 0.0) for r in records) / len(records)
        
        # Get parser statistics
        parser_stats = self.injury_parser.get_parsing_stats()
        parsing_stats = parser_stats['parsing_stats']
        
        # Apply penalties and bonuses
        overall = avg_confidence
        
        # Penalize high unparsed count (potential missed players)
        if parsing_stats['player_lines'] > 0:
            unparsed_ratio = parsing_stats['unparsed_count'] / parsing_stats['player_lines']
            penalty = min(0.3, unparsed_ratio * 0.5)
            overall -= penalty
        
        # Penalize high percentage of low-confidence records
        low_conf_count = sum(1 for r in records if r.get('confidence', 1.0) < 0.7)
        if len(records) > 0:
            low_conf_ratio = low_conf_count / len(records)
            penalty = min(0.2, low_conf_ratio * 0.3)
            overall -= penalty
        
        # Small bonus for successful multi-line merges
        if parsing_stats['merged_multiline'] > 0:
            bonus = min(0.1, parsing_stats['merged_multiline'] * 0.02)
            overall += bonus
        
        # Penalize if too many empty reasons
        empty_reasons = sum(1 for r in records if not r.get('reason', '').strip())
        if len(records) > 0:
            empty_ratio = empty_reasons / len(records)
            penalty = min(0.4, empty_ratio * 0.6)
            overall -= penalty
        
        final_confidence = max(0.0, min(1.0, overall))
        return round(final_confidence, 3)

    def get_scraper_stats(self) -> dict:
        """Enhanced statistics with parsing and confidence metrics."""
        if isinstance(self.data, dict) and 'metadata' in self.data:
            # New structure - extract from existing data
            records = self.data.get('records', [])
            base_stats = self.data['metadata'].copy()
            base_stats.update(self.data['parsing_stats'])
        else:
            # Fallback for old structure
            records = self.data if isinstance(self.data, list) else []
            base_stats = {
                "gamedate": self.opts.get("gamedate", ""),
                "hour": self.opts.get("hour", ""),
                "period": self.opts.get("period", ""),
                "records": len(records),
            }
        
        if records:
            empty_reasons = [r for r in records if not r.get('reason')]
            low_confidence = [r for r in records if r.get('confidence', 1.0) < 0.7]
            high_confidence = [r for r in records if r.get('confidence', 1.0) >= 0.9]
            
            # Calculate confidence distribution
            confidence_distribution = {}
            for record in records:
                conf = record.get('confidence', 0.0)
                bucket = f"{int(conf * 10) * 10}%"
                confidence_distribution[bucket] = confidence_distribution.get(bucket, 0) + 1
            
            base_stats.update({
                "unique_teams": len(set(r.get('team', '') for r in records)),
                "unique_matchups": len(set(r.get('matchup', '') for r in records)),
                "status_counts": {
                    status: sum(1 for r in records if r.get('status') == status)
                    for status in ['Out', 'Questionable', 'Doubtful', 'Probable', 'Available']
                },
                "empty_reasons_count": len(empty_reasons),
                "players_with_empty_reasons": [r['player'] for r in empty_reasons],
                "low_confidence_count": len(low_confidence),
                "high_confidence_count": len(high_confidence),
                "average_confidence": sum(r.get('confidence', 1.0) for r in records) / len(records),
                "players_with_low_confidence": [f"{r['player']} ({r.get('confidence', 0):.3f})" for r in low_confidence],
                "confidence_distribution": confidence_distribution
            })
        
        return base_stats

    def validate_injury_data(self) -> None:
        """
        Enhanced validation with parsing quality checks.
        FIXED: Empty reports are now valid (no exception raised).
        """
        if isinstance(self.data, dict):
            records = self.data.get('records', [])
            is_empty_report = self.data.get('metadata', {}).get('is_empty_report', False)
        else:
            records = self.data if isinstance(self.data, list) else []
            is_empty_report = False
        
        if not isinstance(records, list):
            error_msg = "Records should be a list of injury records"
            logger.error(error_msg)
            try:
                notify_error(
                    title="NBA.com Injury Report Validation Failed",
                    message=f"Invalid data structure for {self.opts['gamedate']}: {error_msg}",
                    details={
                        'gamedate': self.opts['gamedate'],
                        'hour': self.opts['hour'],
                        'period': self.opts['period'],
                        'data_type': type(self.data).__name__
                    },
                    processor_name="NBA.com Injury Report Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(error_msg)
        
        # FIXED: Allow empty reports - they're valid for All-Star weekend, off-days
        if len(records) == 0:
            if is_empty_report:
                logger.info("Validation passed: Empty injury report (valid for All-Star weekend or off-days)")
                return  # Empty reports are valid - don't raise exception
            else:
                # This shouldn't happen - if we have 0 records, is_empty_report should be True
                logger.warning("Empty report without is_empty_report flag - treating as valid")
                return
        
        record_count = len(records)
        if record_count > 1000:
            error_msg = f"Suspiciously high record count: {record_count}"
            logger.error(error_msg)
            try:
                notify_error(
                    title="NBA.com Injury Report High Record Count",
                    message=f"Suspiciously high record count ({record_count}) for {self.opts['gamedate']}",
                    details={
                        'gamedate': self.opts['gamedate'],
                        'hour': self.opts['hour'],
                        'period': self.opts['period'],
                        'record_count': record_count
                    },
                    processor_name="NBA.com Injury Report Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(error_msg)
        
        # Validate key fields
        valid_records = []
        for i, record in enumerate(records):
            required_fields = ['date', 'gametime', 'matchup', 'team', 'player', 'status', 'reason', 'confidence']
            
            if all(field in record for field in required_fields):
                if len(record['player']) >= 3:
                    valid_records.append(record)
                else:
                    logger.warning("Skipping record %d with suspicious player name: %s", 
                                 i, record.get('player'))
        
        # Update records in data structure
        if isinstance(self.data, dict):
            self.data['records'] = valid_records
            self.data['parsing_stats']['total_records'] = len(valid_records)
        else:
            self.data = valid_records
        
        # Enhanced validation logging
        stats = self.get_scraper_stats()
        overall_confidence = stats.get('overall_confidence', 0.0)
        
        logger.info("Enhanced validation passed: %d valid records", len(valid_records))
        logger.info(f"Overall session confidence: {overall_confidence:.3f}")
        logger.info(f"Average individual confidence: {stats.get('average_confidence', 0):.3f}")
        
        # Check if we have parsing stats
        if 'parsing_stats' in stats:
            logger.info(f"Multi-line injuries merged: {stats['parsing_stats'].get('merged_multiline', 0)}")
            logger.info(f"Unparsed lines detected: {stats['parsing_stats'].get('unparsed_count', 0)}")
        
        # Alert-level logging based on overall confidence
        if overall_confidence < 0.4:
            logger.error(f"CRITICAL: Overall confidence extremely low ({overall_confidence:.3f}) - parsing may have failed")
        elif overall_confidence < 0.6:
            logger.warning(f"WARNING: Overall confidence low ({overall_confidence:.3f}) - check parsing quality")
        elif overall_confidence < 0.8:
            logger.info(f"NOTICE: Overall confidence moderate ({overall_confidence:.3f}) - minor parsing issues detected")
        
        if stats.get('empty_reasons_count', 0) > 0:
            logger.warning("%d players have empty reasons", stats['empty_reasons_count'])
        
        if stats.get('low_confidence_count', 0) > 0:
            logger.warning("%d players have low confidence scores", stats['low_confidence_count'])
        
        # Log confidence distribution
        conf_dist = stats.get('confidence_distribution', {})
        if conf_dist:
            logger.info(f"Confidence distribution: {conf_dist}")


# Flask and CLI entry points
create_app = convert_existing_flask_scraper(GetNbaComInjuryReport)

if __name__ == "__main__":
    main = GetNbaComInjuryReport.create_cli_and_flask_main()
    main()
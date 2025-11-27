"""
File: scrapers/nbacom/nbac_gamebook_pdf.py

NBA.com Gamebook PDF scraper - Enhanced with GCS source support        v1.2 - 2025-08-23
---------------------------------------------------------------------------
* Downloads and parses NBA gamebook PDFs from NBA.com OR reads from GCS
* AUTO-DERIVES date and teams from game_code (single source of truth!)
* Extracts box scores AND DNP reasons (critical for prop betting)
* PRODUCTION-READY with comprehensive issue tracking and monitoring
* NEW: Supports reading existing PDFs from GCS for fast re-parsing

Usage examples
--------------
  # Download from NBA.com (default behavior - unchanged):
  python scrapers/nbacom/nbac_gamebook_pdf.py --game_code "20240410/MEMCLE" --debug

  # Read existing PDF from GCS (new capability):
  python scrapers/nbacom/nbac_gamebook_pdf.py --game_code "20240410/MEMCLE" --pdf_source "gcs" --debug

  # Via capture tool:
  python tools/fixtures/capture.py nbac_gamebook_pdf \
      --game_code "20240410/MEMCLE" --pdf_source "gcs" --debug
"""

import logging
import os
import sys
import re
import tempfile
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import pdfplumber
# from google.cloud import storage  # Import moved to lazy initialization

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.nbacom.nbac_gamebook_pdf
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException, InvalidRegionDecodeException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_gamebook_pdf.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException, InvalidRegionDecodeException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

# Notification system imports
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Schedule service for season type detection
from shared.utils.schedule import NBAScheduleService

logger = logging.getLogger("scraper_base")


class GetNbaComGamebookPdf(ScraperBase, ScraperFlaskMixin):
    """Downloads and parses NBA gamebook PDF - AUTO-DERIVES everything from game_code."""

    # Flask Mixin Configuration - ENHANCED with pdf_source parameter
    scraper_name = "nbac_gamebook_pdf"
    required_params = ["game_code"]
    optional_params = {
        "version": "short",
        "pdf_source": "download",  # NEW: "download" (from NBA.com) or "gcs" (from GCS)
        "bucket_name": "nba-scraped-data", # NEW: GCS bucket name when pdf_source="gcs"
        "date": None,
        "away_team": None,
        "home_team": None,
    }

    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #
    required_opts = ["game_code"]  # Just 1! Everything else auto-derived
    header_profile: str | None = "data"
    download_type: DownloadType = DownloadType.BINARY
    proxy_enabled: bool = True
    timeout_http = 60
    
    # ------------------------------------------------------------------ #
    # Exporters - Save BOTH PDF and parsed data
    # ------------------------------------------------------------------ #
    exporters = [
        # Save original PDF to GCS (skip when pdf_source="gcs" since PDF already exists)
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path("nba_com_gamebooks_pdf_raw"),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "s3", "gcs", "reparse_from_nba"],  # NEW: reparse_from_nba group
            "condition": "pdf_source_download",  # NEW: conditional export
        },
        # Always save parsed data to GCS
        {
            "type": "gcs", 
            "key": GCSPathBuilder.get_path("nba_com_gamebooks_pdf_data"),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "s3", "gcs", "reparse_from_gcs"],  # NEW: reparse_from_gcs group
        },
        # Development exports
        {
            "type": "file",
            "filename": "/tmp/nba_gamebook_%(clean_game_code)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        # Capture group exports
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.pdf",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
            "condition": "pdf_source_download",  # NEW: only export raw PDF when downloading
        },
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # Class-level schedule service (lazy initialization)
    _schedule_service: Optional[NBAScheduleService] = None

    @classmethod
    def _get_schedule_service(cls) -> NBAScheduleService:
        """Get or create the schedule service instance."""
        if cls._schedule_service is None:
            cls._schedule_service = NBAScheduleService()
        return cls._schedule_service

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialize parsing issues tracker
        self.parsing_issues = {
            "malformed_inactive_players": [],
            "unbalanced_parentheses": [],
            "failed_stat_lines": [],
            "unknown_player_categories": [],
            "parsing_failure": [],
            "warnings": []
        }

        # NEW: GCS client for reading PDFs from storage
        self.gcs_client = None

    # ------------------------------------------------------------------ #
    # AUTO-DERIVE everything from game_code
    # ------------------------------------------------------------------ #
    def _detect_season_type(self, game_date: str) -> str:
        """
        Auto-detect season type from schedule database.

        Args:
            game_date: Date string in YYYY-MM-DD format

        Returns:
            Season type string (e.g., "Regular Season", "Playoffs", "All Star")
        """
        try:
            schedule = self._get_schedule_service()
            season_type = schedule.get_season_type_for_date(game_date)
            return season_type
        except Exception as e:
            logger.warning("Failed to detect season type from schedule for %s: %s. "
                          "Falling back to Regular Season.", game_date, e)
            return "Regular Season"

    def set_additional_opts(self) -> None:
        # Parse game_code BEFORE calling super() to extract the correct date
        game_code = self.opts["game_code"]
        if "/" not in game_code:
            raise DownloadDataException("game_code must be in format YYYYMMDD/TEAMTEAM")
        
        date_part, teams_part = game_code.split("/")
        
        # FORCE the game date (override parent class default)
        year = date_part[:4]    # "2024"
        month = date_part[4:6]  # "04" 
        day = date_part[6:8]    # "10"
        self.opts["date"] = f"{year}-{month}-{day}"  # "2024-04-10" - GAME DATE
        
        # Now call super() - it won't override our date since it's already set
        super().set_additional_opts()
        
        # AUTO-DERIVE TEAMS from game_code (unless overridden)
        if len(teams_part) != 6:
            raise DownloadDataException("Teams part must be 6 characters (3+3)")
        
        if not self.opts.get("away_team"):
            self.opts["away_team"] = teams_part[:3]  # "MEM"
        if not self.opts.get("home_team"):
            self.opts["home_team"] = teams_part[3:]  # "CLE"
        
        # Set derived values
        self.opts["date_part"] = date_part
        self.opts["teams_part"] = teams_part
        self.opts["matchup"] = f"{self.opts['away_team']}@{self.opts['home_team']}"
        self.opts["clean_game_code"] = game_code.replace("/", "_")  # For filenames
        self.opts["clean_game_code_dashes"] = game_code.replace("/", "-")  # "20211003-BKNLAL"
        
        # Set defaults for NEW parameters
        self.opts["pdf_source"] = self.opts.get("pdf_source", "download")
        self.opts["bucket_name"] = self.opts.get("bucket_name", "nba-scraped-data")
        self.opts["version"] = self.opts.get("version", "short")

        # Auto-detect season type and skip All-Star games
        season_type = self._detect_season_type(self.opts["date"])
        self.opts["season_type"] = season_type
        logger.info(f"Auto-detected season_type: {season_type} for date {self.opts['date']}")

        # Skip All-Star games - they use non-NBA teams (e.g., "Team LeBron", "Team Durant")
        # and have non-standard team codes that break PDF URL construction
        if season_type == "All Star":
            raise DownloadDataException(
                f"Skipping All-Star game on {self.opts['date']} - "
                f"exhibition games use non-standard team codes (game_code: {game_code})"
            )

        if self.opts["pdf_source"] == "gcs":
            # Enable GCS download instead of HTTP
            self.gcs_enabled = True
            self.proxy_enabled = False  # Disable proxy for GCS
            self.gcs_bucket = self.opts["bucket_name"]
            self.gcs_path = self._construct_gcs_path()
            logger.info("Configured for GCS: bucket=%s, path=%s", 
                    self.gcs_bucket, self.gcs_path)
        else:
            # Use existing HTTP download
            self.gcs_enabled = False
            self.proxy_enabled = True
            logger.info("Configured for HTTP download")
        
        # GCS client will be initialized lazily when needed
        self.gcs_client = None
        
        # Log to verify correct configuration
        logger.info("Using game date: %s, pdf_source: %s (game_code: %s)", 
                   self.opts["date"], self.opts["pdf_source"], game_code)
        
    def _construct_gcs_path(self) -> str:
        """
        Construct GCS path based on actual structure.
        Returns a pattern that can be used to find the PDF.
        """
        date = self.opts["date"]  # "2021-10-03"
        clean_game_code_dashes = self.opts["clean_game_code_dashes"]  # "20211003-BKNLAL"
        
        # Pattern: nba-com/gamebooks-pdf/2021-10-03/20211003-BKNLAL/
        return f"nba-com/gamebooks-pdf/{date}/{clean_game_code_dashes}/"

    # ------------------------------------------------------------------ #
    # URL construction
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        """Construct PDF URL from game_code - only needed when pdf_source='download'."""
        if self.opts["pdf_source"] == "gcs":
            # Don't need a URL when reading from GCS
            self.url = None
            logger.info("PDF source is GCS - skipping URL construction")
            return
            
        date_part = self.opts["date_part"]
        teams_part = self.opts["teams_part"]
        version = self.opts["version"]
        
        # CORRECTED URL format
        if version == "short":
            # Short version - basic box score (NO _book suffix)
            self.url = f"https://statsdmz.nba.com/pdfs/{date_part}/{date_part}_{teams_part}.pdf"
        elif version == "full":
            # Full version - detailed game book (HAS _book suffix)
            self.url = f"https://statsdmz.nba.com/pdfs/{date_part}/{date_part}_{teams_part}_book.pdf"
        else:
            raise DownloadDataException("version must be 'short' or 'full'")
        
        logger.info("NBA Gamebook PDF URL (%s): %s", version, self.url)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_opts(self) -> None:
        super().validate_opts()
        
        # Validate game_code format
        game_code = self.opts["game_code"]
        if not re.match(r'^\d{8}/[A-Z]{6}$', game_code):
            raise DownloadDataException("game_code must be in format YYYYMMDD/TEAMTEAM")
        
        # Validate pdf_source
        pdf_source = self.opts.get("pdf_source", "download")
        if pdf_source not in ["download", "gcs"]:
            raise DownloadDataException("pdf_source must be 'download' or 'gcs'")
        
    # ------------------------------------------------------------------ #
    # ENHANCED Download Methods - Support GCS source
    # ------------------------------------------------------------------ #
    def download_and_decode(self):
        """
        Enhanced download method that supports both NBA.com and GCS sources.
        Routing logic based on pdf_source parameter.
        """
        try:
            if self.opts["pdf_source"] == "gcs":
                # NEW: Read PDF from GCS instead of downloading
                self._download_pdf_from_gcs()
            else:
                # EXISTING: Download from NBA.com (unchanged behavior)
                super().download_and_decode()
        except InvalidRegionDecodeException as e:
            # Region-blocked PDFs
            logger.error("PDF blocked in region for game %s: %s", self.opts["game_code"], e)
            try:
                notify_error(
                    title="NBA.com Gamebook PDF Region Blocked",
                    message=f"PDF not accessible in this region for game {self.opts['game_code']}",
                    details={
                        'game_code': self.opts['game_code'],
                        'matchup': self.opts['matchup'],
                        'pdf_source': self.opts['pdf_source'],
                        'error': str(e)
                    },
                    processor_name="NBA.com Gamebook PDF Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
        except DownloadDataException as e:
            # Download/GCS failures
            logger.error("Failed to get PDF for game %s: %s", self.opts["game_code"], e)
            try:
                notify_error(
                    title="NBA.com Gamebook PDF Download Failed",
                    message=f"Failed to retrieve PDF for game {self.opts['game_code']}: {str(e)}",
                    details={
                        'game_code': self.opts['game_code'],
                        'matchup': self.opts['matchup'],
                        'pdf_source': self.opts['pdf_source'],
                        'url': self.url if self.opts['pdf_source'] == 'download' else None,
                        'gcs_path': self.gcs_path if self.opts['pdf_source'] == 'gcs' else None,
                        'error_type': type(e).__name__,
                        'error': str(e)
                    },
                    processor_name="NBA.com Gamebook PDF Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
        except Exception as e:
            # Unexpected failures
            logger.error("Unexpected error downloading/parsing PDF for game %s: %s", self.opts["game_code"], e)
            try:
                notify_error(
                    title="NBA.com Gamebook PDF Unexpected Error",
                    message=f"Unexpected error processing game {self.opts['game_code']}: {str(e)}",
                    details={
                        'game_code': self.opts['game_code'],
                        'matchup': self.opts['matchup'],
                        'pdf_source': self.opts['pdf_source'],
                        'error_type': type(e).__name__,
                        'error': str(e)
                    },
                    processor_name="NBA.com Gamebook PDF Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
    
    def _download_pdf_from_gcs(self) -> None:
        """
        NEW METHOD: Read PDF from GCS bucket instead of downloading from NBA.com.
        Simulates the HTTP download by populating self.raw_response.content.
        """
        try:
            logger.info("Reading PDF from GCS bucket: %s", self.opts["bucket_name"])
            
            # Lazy initialization of GCS client with error handling
            if not self.gcs_client:
                try:
                    from google.cloud import storage
                    self.gcs_client = storage.Client()
                    logger.info("✅ GCS client initialized successfully")
                except ImportError as e:
                    error_msg = "google-cloud-storage not available in scraper service"
                    logger.error(error_msg)
                    try:
                        notify_error(
                            title="GCS Client Initialization Failed",
                            message=f"Cannot initialize GCS client for game {self.opts['game_code']}",
                            details={
                                'game_code': self.opts['game_code'],
                                'error': error_msg,
                                'bucket': self.opts['bucket_name']
                            },
                            processor_name="NBA.com Gamebook PDF Scraper"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                    raise DownloadDataException(error_msg) from e
                except Exception as e:
                    error_msg = f"Failed to initialize GCS client: {e}"
                    logger.error(error_msg)
                    try:
                        notify_error(
                            title="GCS Client Initialization Failed",
                            message=f"GCS client initialization error for game {self.opts['game_code']}",
                            details={
                                'game_code': self.opts['game_code'],
                                'error': str(e),
                                'error_type': type(e).__name__,
                                'bucket': self.opts['bucket_name']
                            },
                            processor_name="NBA.com Gamebook PDF Scraper"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                    raise DownloadDataException(error_msg) from e
            
            # Construct GCS path based on expected structure from original scraper
            gcs_pdf_path = self._construct_gcs_pdf_path()
            logger.info("Looking for PDF in GCS path: %s", gcs_pdf_path)
            
            # Find the PDF in GCS
            pdf_blob = self._find_pdf_blob(gcs_pdf_path)
            if not pdf_blob:
                error_msg = f"PDF not found in GCS path: {gcs_pdf_path}"
                logger.error(error_msg)
                try:
                    notify_warning(
                        title="NBA.com Gamebook PDF Not Found in GCS",
                        message=f"PDF not found in GCS for game {self.opts['game_code']}",
                        details={
                            'game_code': self.opts['game_code'],
                            'matchup': self.opts['matchup'],
                            'gcs_path': gcs_pdf_path,
                            'bucket': self.opts['bucket_name']
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(error_msg)
            
            # Download PDF content from GCS
            pdf_content = pdf_blob.download_as_bytes()
            logger.info("Successfully read PDF from GCS: %s (%d bytes)", pdf_blob.name, len(pdf_content))
            
            # Create a mock response object that mimics requests.Response
            # This allows existing parsing logic to work unchanged
            class MockResponse:
                def __init__(self, content):
                    self.content = content
                    self.status_code = 200
                    self.text = "PDF from GCS"
                    
            self.raw_response = MockResponse(pdf_content)
            
            # Call the existing decode logic (this is where all the battle-tested parsing happens)
            if self.decode_download_data:
                self.decode_download_content()
            
            logger.info("✅ Successfully processed PDF from GCS")
            
        except DownloadDataException:
            # Already handled above, just re-raise
            raise
        except Exception as e:
            error_msg = f"GCS PDF reading failed: {e}"
            logger.error("Failed to read PDF from GCS: %s", e)
            try:
                notify_error(
                    title="GCS PDF Read Failed",
                    message=f"Error reading PDF from GCS for game {self.opts['game_code']}",
                    details={
                        'game_code': self.opts['game_code'],
                        'matchup': self.opts['matchup'],
                        'gcs_path': self._construct_gcs_pdf_path(),
                        'bucket': self.opts['bucket_name'],
                        'error': str(e),
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Gamebook PDF Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(error_msg) from e

    def _construct_gcs_pdf_path(self) -> str:
        """
        Construct the expected GCS path where the PDF should be stored.
        Based on actual structure: nba-com/gamebooks-pdf/2021-10-19/20211019-BKNMIL/
        """
        date = self.opts["date"]  # "2024-04-10"
        clean_game_code_dashes = self.opts["clean_game_code_dashes"]  # "20240410-MEMCLE"
        
        # Expected path: nba-com/gamebooks-pdf/2024-04-10/20240410-MEMCLE/
        return f"nba-com/gamebooks-pdf/{date}/{clean_game_code_dashes}/"

    def _find_pdf_blob(self, gcs_path_prefix: str) -> Optional[Any]:
        """
        Find the PDF blob in GCS that matches our game_code.
        Handles timestamped filenames from the original scraper.
        """
        bucket = self.gcs_client.bucket(self.opts["bucket_name"])
        
        # List all blobs with the path prefix  
        blobs = bucket.list_blobs(prefix=gcs_path_prefix)
        
        # Primary matching - use the dash format since that's what we found in GCS
        clean_game_code_dashes = self.opts["clean_game_code_dashes"]  # "20240410-MEMCLE"
        
        # Find PDF that matches our game code (should be in the directory already)
        for blob in blobs:
            if blob.name.endswith('.pdf'):
                logger.debug("Found PDF in path: %s", blob.name)
                return blob  # Since we're looking in the specific game directory, any PDF should work
        
        logger.debug("No PDFs found in path: %s", gcs_path_prefix)
        return None

    # ------------------------------------------------------------------ #
    # ENHANCED Export Control - Skip PDF export when reading from GCS
    # ------------------------------------------------------------------ #
    def export_data(self):
        """
        Enhanced export method that respects conditional exports.
        Filters exporters based on conditions when pdf_source="gcs".
        """
        # Filter exporters based on conditions
        effective_exporters = []
        
        for config in self.exporters:
            # Check condition
            condition = config.get("condition")
            
            if condition == "pdf_source_download" and self.opts["pdf_source"] != "download":
                # Skip PDF export when reading from GCS (since PDF already exists there)
                logger.debug("Skipping PDF export (condition: %s, pdf_source: %s)", 
                           condition, self.opts["pdf_source"])
                continue
            
            effective_exporters.append(config)
        
        # Temporarily replace exporters for this run
        original_exporters = self.exporters
        self.exporters = effective_exporters
        
        try:
            # Call original export logic
            super().export_data()
        finally:
            # Restore original exporters
            self.exporters = original_exporters

    # ------------------------------------------------------------------ #
    # Issue Tracking Utilities
    # ------------------------------------------------------------------ #
    def _log_parsing_issue(self, issue_type: str, **issue_data):
        """Log a parsing issue for later review."""
        issue = {
            "type": issue_type,
            "game_code": self.opts["game_code"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **issue_data
        }
        self.parsing_issues[issue_type].append(issue)
        logger.warning("Parsing issue (%s): %s", issue_type, issue_data)

    # ------------------------------------------------------------------ #
    # PDF Parsing
    # ------------------------------------------------------------------ #
    def decode_download_content(self) -> None:
        """Parse PDF content using pdfplumber - UNCHANGED from v1.1"""
        content = self.raw_response.content

        # Basic PDF validation
        if b"not accessible in this region" in content.lower():
            raise InvalidRegionDecodeException("PDF blocked in this region.")
        if b"%PDF" not in content[:1024]:
            raise InvalidRegionDecodeException("Response is not a PDF.")

        logger.info("PDF Content size: %d bytes (source: %s)", len(content), self.opts["pdf_source"])

        # Initialize data structures with corrected categories
        active_players = []
        dnp_players = []  # Did Not Play (NWT/DNP) - game-specific
        inactive_players = []  # Truly inactive (longer-term unavailable)
        
        game_info = {
            "game_code": self.opts["game_code"],
            "date": self.opts["date"],
            "matchup": self.opts["matchup"],
            "away_team": self.opts["away_team"],
            "home_team": self.opts["home_team"],
            "pdf_version": self.opts["version"],
            "pdf_source": self.opts["pdf_source"],  # NEW: track source
            "pdf_url": self.url if self.opts["pdf_source"] == "download" else None,
        }

        # Extract text using pdfplumber
        logger.info("Extracting text with pdfplumber")
        
        # Save content to temp file for pdfplumber
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        try:
            # Extract text using pdfplumber
            with pdfplumber.open(temp_file_path) as pdf:
                full_text = ""
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        full_text += page_text + "\n"
            
            logger.debug("pdfplumber extracted %d characters", len(full_text))
            logger.debug("Text sample (first 500 chars):\n%s", full_text[:500])
            
        except Exception as e:
            logger.error("pdfplumber failed to extract text: %s", e)
            try:
                notify_error(
                    title="NBA.com Gamebook PDF Parsing Failed",
                    message=f"pdfplumber failed to extract text for game {self.opts['game_code']}",
                    details={
                        'game_code': self.opts['game_code'],
                        'matchup': self.opts['matchup'],
                        'pdf_source': self.opts['pdf_source'],
                        'pdf_size_bytes': len(content),
                        'error': str(e),
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Gamebook PDF Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"pdfplumber failed: {e}") from e
        finally:
            # Clean up temp file
            os.unlink(temp_file_path)
        
        if not full_text:
            logger.error("pdfplumber extracted no text from PDF")
            try:
                notify_error(
                    title="NBA.com Gamebook PDF Empty",
                    message=f"No text extracted from PDF for game {self.opts['game_code']}",
                    details={
                        'game_code': self.opts['game_code'],
                        'matchup': self.opts['matchup'],
                        'pdf_source': self.opts['pdf_source'],
                        'pdf_size_bytes': len(content)
                    },
                    processor_name="NBA.com Gamebook PDF Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException("pdfplumber failed to extract any text from PDF")

        # Save debug text
        debug_file = f"/tmp/debug_pdfplumber_text_{self.run_id}.txt"
        try:
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(full_text)
            logger.debug("Debug text saved to: %s", debug_file)
        except Exception as e:
            logger.warning("Failed to save debug text: %s", e)

        # Parse the clean text with corrected categories
        try:
            self._parse_clean_text(full_text, active_players, dnp_players, inactive_players, game_info)
        except Exception as e:
            logger.error("Failed to parse PDF text for game %s: %s", self.opts["game_code"], e)
            try:
                notify_error(
                    title="NBA.com Gamebook PDF Parse Error",
                    message=f"Error parsing PDF text for game {self.opts['game_code']}: {str(e)}",
                    details={
                        'game_code': self.opts['game_code'],
                        'matchup': self.opts['matchup'],
                        'pdf_source': self.opts['pdf_source'],
                        'text_length': len(full_text),
                        'error': str(e),
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Gamebook PDF Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

        # Calculate issue summary for monitoring
        total_issues = sum(len(issues) for issues in self.parsing_issues.values())
        
        # Set final data structure with proper categories
        self.data = {
            **game_info,  # This now includes arena, officials, attendance, etc.
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "active_players": active_players,
            "dnp_players": dnp_players,  # Did Not Play this game
            "inactive_players": inactive_players,  # Truly inactive/unavailable
            "total_players": len(active_players) + len(dnp_players) + len(inactive_players),
            "active_count": len(active_players),
            "dnp_count": len(dnp_players),
            "inactive_count": len(inactive_players),
            "source": "nba_gamebook_pdf",
            "debug_info": {
                "text_length": len(full_text),
                "parser_used": "pdfplumber", 
                "debug_file": debug_file,
                "parsing_issues": self.parsing_issues,
                "total_issues": total_issues
            }
        }
        
        self.decoded_data = self.data
        
        # CRITICAL: Check for no active players - major data quality issue
        if len(active_players) == 0:
            logger.warning("No active players found in game %s", self.opts["game_code"])
            try:
                notify_warning(
                    title="NBA.com Gamebook PDF - No Active Players",
                    message=f"No active players found for game {self.opts['game_code']}",
                    details={
                        'game_code': self.opts['game_code'],
                        'matchup': self.opts['matchup'],
                        'pdf_source': self.opts['pdf_source'],
                        'dnp_count': len(dnp_players),
                        'inactive_count': len(inactive_players),
                        'parsing_issues': total_issues,
                        'arena': game_info.get('arena', 'unknown')
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        
        # Warning for high parsing issues
        parsing_issue_threshold = int(os.environ.get('PDF_PARSING_ISSUE_THRESHOLD', '10'))
        if total_issues > parsing_issue_threshold:
            logger.warning("High parsing issue count (%d) for game %s", total_issues, self.opts["game_code"])
            try:
                notify_warning(
                    title="NBA.com Gamebook PDF - High Parsing Issues",
                    message=f"Game {self.opts['game_code']} had {total_issues} parsing issues",
                    details={
                        'game_code': self.opts['game_code'],
                        'matchup': self.opts['matchup'],
                        'pdf_source': self.opts['pdf_source'],
                        'total_issues': total_issues,
                        'issue_breakdown': {k: len(v) for k, v in self.parsing_issues.items()},
                        'active_count': len(active_players),
                        'dnp_count': len(dnp_players),
                        'inactive_count': len(inactive_players)
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        
        # Log summary with issue count for monitoring
        if total_issues > 0:
            logger.warning("Parsed PDF with %d parsing issues: %d active, %d DNP, %d inactive players (source: %s)", 
                          total_issues, len(active_players), len(dnp_players), len(inactive_players), self.opts["pdf_source"])
        else:
            logger.info("Parsed PDF successfully: %d active, %d DNP, %d inactive players (source: %s)", 
                       len(active_players), len(dnp_players), len(inactive_players), self.opts["pdf_source"])

    def _normalize_team_name(self, team_name: str) -> str:
        """Normalize team name from inactive line to full team name."""
        
        # Clean up the input
        team_name = team_name.strip()
        
        # Map common team abbreviations/names to full names
        team_mappings = {
            # Use the away/home teams from the game as primary mapping
            self.opts.get("away_team", "").upper(): f"{self.opts.get('away_team', '')} (Away)",
            self.opts.get("home_team", "").upper(): f"{self.opts.get('home_team', '')} (Home)",
            
            # Common team name variations seen in PDFs
            "PELICANS": "New Orleans Pelicans",
            "SUNS": "Phoenix Suns", 
            "GRIZZLIES": "Memphis Grizzlies",
            "CAVALIERS": "Cleveland Cavaliers",
            "CAVS": "Cleveland Cavaliers",
            "WARRIORS": "Golden State Warriors",
            "LAKERS": "Los Angeles Lakers",
            "CLIPPERS": "Los Angeles Clippers",
            "CELTICS": "Boston Celtics",
            "HEAT": "Miami Heat",
            "BULLS": "Chicago Bulls",
            "KNICKS": "New York Knicks",
            "NETS": "Brooklyn Nets",
            "SIXERS": "Philadelphia 76ers",
            "76ERS": "Philadelphia 76ers",
            "RAPTORS": "Toronto Raptors",
            "PACERS": "Indiana Pacers",
            "PISTONS": "Detroit Pistons",
            "BUCKS": "Milwaukee Bucks",
            "HAWKS": "Atlanta Hawks",
            "HORNETS": "Charlotte Hornets",
            "MAGIC": "Orlando Magic",
            "WIZARDS": "Washington Wizards",
            "NUGGETS": "Denver Nuggets", 
            "JAZZ": "Utah Jazz",
            "THUNDER": "Oklahoma City Thunder",
            "TRAIL BLAZERS": "Portland Trail Blazers",
            "BLAZERS": "Portland Trail Blazers",
            "KINGS": "Sacramento Kings",
            "SPURS": "San Antonio Spurs",
            "MAVERICKS": "Dallas Mavericks",
            "MAVS": "Dallas Mavericks",
            "ROCKETS": "Houston Rockets",
            "TIMBERWOLVES": "Minnesota Timberwolves",
            "WOLVES": "Minnesota Timberwolves",
        }
        
        # Try exact match first
        team_upper = team_name.upper()
        if team_upper in team_mappings:
            return team_mappings[team_upper]
        
        # Try partial matches for team names
        for key, full_name in team_mappings.items():
            if key in team_upper or team_upper in key:
                return full_name
        
        # If no mapping found, return the original team name
        # This ensures the function doesn't fail even for unknown teams
        logger.debug("No team mapping found for '%s', using as-is", team_name)
        return team_name
        
    def _extract_dnd_from_clean_line(self, line: str, team: str) -> Optional[Dict]:
        """Extract DND (Did Not Dress) player from clean line like '23 Mitchell Robinson DND - Injury/Illness - Back; Sore lower'"""
        try:
            parts = line.split(' DND - ', 1)
            if len(parts) != 2:
                return None
            
            name_part = parts[0].strip()
            reason_part = parts[1].strip()
            
            # Remove jersey number from start - FIXED to include hyphens
            name = re.sub(r'^\d+\s+', '', name_part).strip()
            
            if name and len(name) > 1:
                return {
                    "name": name,
                    "team": team,
                    "status": "did_not_play",
                    "dnp_reason": f"DND - {reason_part}",
                    "category": "DND"
                }
        except AttributeError as e:
            logger.error("CRITICAL CODE BUG extracting DND from line '%s': %s", line, e)
            self._log_parsing_issue("unknown_player_categories", 
                                   text=line, team=team, error=str(e), category="DND")
            raise
        except (ValueError, TypeError) as e:
            logger.error("PARSING ERROR extracting DND from line '%s': %s", line, e)
            self._log_parsing_issue("unknown_player_categories", 
                                   text=line, team=team, error=str(e), category="DND")
            raise
        
        return None

    def _extract_game_metadata(self, text: str, game_info: Dict) -> None:
        """Extract additional game metadata from PDF header."""
        
        lines = text.split('\n')[:20]  # Look at first 20 lines for metadata
        
        try:
            for line in lines:
                line = line.strip()
                
                # Extract arena and location
                # Pattern: "Wednesday, April 10, 2024 Rocket Mortgage FieldHouse, Cleveland, OH"
                arena_match = re.search(r'\d{4}\s+(.+?),\s+([A-Za-z\s]+),\s+([A-Z]{2})', line)
                if arena_match:
                    arena = arena_match.group(1).strip()
                    city = arena_match.group(2).strip()
                    state = arena_match.group(3).strip()
                    
                    game_info["arena"] = arena
                    game_info["city"] = city
                    game_info["state"] = state
                    game_info["location"] = f"{city}, {state}"
                    
                    logger.debug("Found game location: %s at %s", game_info["location"], arena)
                
                # Extract officials
                # Pattern: "Officials: #24 Kevin Scott, #36 Brent Barnaky, #41 Nate Green"
                elif line.startswith('Officials:'):
                    officials = self._parse_officials(line)
                    if officials:
                        game_info["officials"] = officials
                        logger.debug("Found officials: %s", [f["name"] for f in officials])
                
                # Extract game duration
                # Pattern: "Game Duration: 2:10"
                elif line.startswith('Game Duration:'):
                    duration_match = re.search(r'Game Duration:\s*(\d+:\d+)', line)
                    if duration_match:
                        game_info["game_duration"] = duration_match.group(1)
                        logger.debug("Found game duration: %s", game_info["game_duration"])
                
                # Extract attendance
                # Pattern: "Attendance: 19432 (Sellout)" or "Attendance: 19432"
                elif line.startswith('Attendance:'):
                    attendance_match = re.search(r'Attendance:\s*(\d+)(?:\s*\(([^)]+)\))?', line)
                    if attendance_match:
                        game_info["attendance"] = int(attendance_match.group(1))
                        if attendance_match.group(2):
                            game_info["attendance_note"] = attendance_match.group(2)
                        logger.debug("Found attendance: %s", game_info["attendance"])
        
        except AttributeError as e:
            logger.error("CRITICAL CODE BUG extracting game metadata: %s", e)
            self._log_parsing_issue("warnings", error=str(e), context="game_metadata_extraction")
            raise
        except (ValueError, TypeError) as e:
            logger.error("PARSING ERROR extracting game metadata: %s", e)
            self._log_parsing_issue("warnings", error=str(e), context="game_metadata_extraction")
            raise

    def _parse_officials(self, officials_line: str) -> List[Dict[str, Any]]:
        """Parse officials from line like 'Officials: #24 Kevin Scott, #36 Brent Barnaky, #41 Nate Green'"""
        officials = []
        
        try:
            # Remove "Officials:" prefix
            officials_text = officials_line.replace('Officials:', '').strip()
            
            # Split by commas
            official_parts = [part.strip() for part in officials_text.split(',')]
            
            for part in official_parts:
                # Extract number and name
                # Pattern: "#24 Kevin Scott"
                match = re.match(r'#(\d+)\s+(.+)', part)
                if match:
                    number = int(match.group(1))
                    name = match.group(2).strip()
                    
                    officials.append({
                        "number": number,
                        "name": name
                    })
                else:
                    logger.debug("Could not parse official: '%s'", part)
                    self._log_parsing_issue("warnings", 
                                           context="official_parsing", 
                                           unparsed_text=part)
        
        except AttributeError as e:
            logger.error("CRITICAL CODE BUG parsing officials from '%s': %s", officials_line, e)
            self._log_parsing_issue("warnings", error=str(e), context="officials_parsing")
            raise
        except (ValueError, TypeError) as e:
            logger.error("PARSING ERROR parsing officials from '%s': %s", officials_line, e)
            self._log_parsing_issue("warnings", error=str(e), context="officials_parsing")
            raise
        
        return officials

    def _extract_inactive_players_from_line(self, line: str, all_lines: List[str], line_idx: int) -> List[Dict]:
        """Extract truly inactive players from 'Inactive:' sections."""
        inactive_list = []
        
        try:
            logger.debug("Processing inactive line: %s", line)
            
            # Generic team extraction from "Inactive: [TEAM] - [PLAYERS]" format
            team_match = re.search(r'Inactive:\s*([^-]+?)\s*-', line)
            if not team_match:
                logger.warning("Could not extract team from inactive line: %s", line)
                self._log_parsing_issue("warnings", 
                                       context="inactive_team_extraction", 
                                       text=line)
                return inactive_list
                
            team_name = team_match.group(1).strip()
            
            # Map team abbreviations/names to full names if needed
            team = self._normalize_team_name(team_name)
            
            if not team:
                logger.warning("Could not determine team from inactive line: %s", line)
                self._log_parsing_issue("warnings", 
                                       context="team_name_normalization", 
                                       text=line, team_name=team_name)
                return inactive_list
            
            # Remove "Inactive: Grizzlies - " or similar prefix
            team_prefix = f"Inactive: {team_name.strip()} - "
            content = line.replace(team_prefix, '')
            
            # Check if inactive list continues on next lines (common in PDFs)
            full_content = content
            next_line_idx = line_idx + 1
            while next_line_idx < len(all_lines):
                next_line = all_lines[next_line_idx].strip()
                # FIXED: Stop if next line starts with another "Inactive:" section
                if (next_line and 
                    not next_line.startswith(('Points in the Paint', 'SCORE BY', 'Technical fouls', 'MEMO', 'Copyright', 'Inactive:')) and
                    not re.match(r'^\d+\s+[A-Za-z]', next_line)):  # Not a new player stat line
                    full_content += " " + next_line
                    next_line_idx += 1
                else:
                    logger.debug("Stopping line continuation at: %s", next_line[:50])
                    break
            
            logger.debug("Full inactive content for %s: %s", team, full_content)
            
            # Split by commas to get individual players - parentheses-aware splitting
            raw_parts = self._smart_comma_split(full_content)
            
            player_parts = []
            for part in raw_parts:
                part = part.strip()
                if part:
                    # Additional cleanup: Remove any remaining "Inactive:" contamination 
                    part_cleaned = re.sub(r'\s*\)\s*Inactive:.*$', ')', part)
                    part_cleaned = part_cleaned.strip()
                    
                    if part_cleaned:
                        player_parts.append(part_cleaned)
            
            logger.debug("Player parts after splitting: %s", player_parts)
            
            for part in player_parts:
                player = self._parse_individual_inactive_player(part, team)
                if player:
                    inactive_list.append(player)
                else:
                    logger.debug("Could not parse player part: '%s'", part)
        
        except AttributeError as e:
            # Code bugs (missing methods, wrong object types)
            logger.error("CRITICAL CODE BUG in inactive player extraction: %s", e)
            self._log_parsing_issue("warnings", error=str(e), context="inactive_player_extraction")
            raise  # Crash loudly - this is a missing method or similar
        except (ValueError, KeyError, TypeError) as e:
            # Data structure issues (unexpected formats, missing keys)
            logger.error("PARSING ERROR in inactive player extraction from '%s': %s", line, e)
            self._log_parsing_issue("warnings", error=str(e), context="inactive_player_extraction", text=line)
            raise  # Crash loudly - data structure unexpected
        
        return inactive_list
    
    def _smart_comma_split(self, text: str) -> List[str]:
        """Split by commas but respect parentheses - don't split commas inside ()."""
        parts = []
        current_part = ""
        paren_depth = 0
        
        for char in text:
            if char == '(':
                paren_depth += 1
                current_part += char
            elif char == ')':
                paren_depth -= 1
                current_part += char
            elif char == ',' and paren_depth == 0:
                if current_part.strip():
                    parts.append(current_part.strip())
                current_part = ""
            else:
                current_part += char
        
        if current_part.strip():
            parts.append(current_part.strip())
        
        # SAFETY CHECK: Track unbalanced parentheses
        if paren_depth != 0:
            self._log_parsing_issue("unbalanced_parentheses", 
                                   text=text, paren_depth=paren_depth)
            logger.warning("Unbalanced parentheses detected: %s", text)
            return [p.strip() for p in text.split(',') if p.strip()]
        
        return parts

    def _parse_individual_inactive_player(self, player_text: str, team: str) -> Optional[Dict]:
        """Parse individual inactive player - handles 'Name (Reason)', 'Name ()', and 'Name' formats"""
        try:
            logger.debug("Parsing inactive player text: '%s' for team: '%s'", player_text, team)
            
            # Clean up the player text first
            player_text = player_text.strip()
            if not player_text:
                return None
            
            # Pattern 1: "PlayerName (Reason)" - player with injury/reason - FIXED to include hyphens
            match = re.match(r'^([A-Za-z\s\.\'\-Jr Sr]+?)\s*\((.+?)\s*\)\s*$', player_text)
            if match:
                name = match.group(1).strip()
                reason = match.group(2).strip()
                
                if match.group(2).strip():  # Make sure reason isn't empty
                    # Clean up name
                    name = re.sub(r'\s+', ' ', name)  # Multiple spaces to single
                    
                    if name and len(name) > 1:
                        return {
                            "name": name,
                            "team": team,
                            "status": "inactive",
                            "reason": reason
                        }
            
            # Pattern 2: "PlayerName ()" - player with empty parentheses - FIXED to include hyphens
            empty_parens_match = re.match(r'^([A-Za-z\s\.\'\-Jr Sr]+?)\s*\(\s*\)\s*$', player_text)
            if empty_parens_match:
                name = empty_parens_match.group(1).strip()
                
                # Clean up name
                name = re.sub(r'\s+', ' ', name)  # Multiple spaces to single
                
                if name and len(name) > 1:
                    return {
                        "name": name,
                        "team": team,
                        "status": "inactive",
                        "reason": "Not specified"
                    }
            
            # Pattern 3: "PlayerName" - player with no parentheses at all - FIXED to include hyphens
            name_only_match = re.match(r'^([A-Za-z\s\.\'\-Jr Sr]+)$', player_text)
            if name_only_match:
                name = name_only_match.group(1).strip()
                
                # Clean up name
                name = re.sub(r'\s+', ' ', name)  # Multiple spaces to single
                
                # Make sure it's a reasonable name (not just single letter, etc.)
                if name and len(name) > 1 and not name.isdigit():
                    return {
                        "name": name,
                        "team": team,
                        "status": "inactive",
                        "reason": "Not specified"
                    }
            
            # If we get here, we couldn't parse the player
            self._log_parsing_issue("malformed_inactive_players", 
                                   text=player_text, team=team)
            logger.debug("Could not parse inactive player text: '%s'", player_text)
                
        except AttributeError as e:
            # Code bugs (regex issues, wrong method calls)
            logger.error("CRITICAL CODE BUG parsing individual inactive player '%s': %s", player_text, e)
            self._log_parsing_issue("malformed_inactive_players", 
                                   text=player_text, team=team, error=str(e))
            raise
        except (ValueError, TypeError) as e:
            # Data issues (unexpected string format)
            logger.error("PARSING ERROR for individual inactive player '%s': %s", player_text, e)
            self._log_parsing_issue("malformed_inactive_players", 
                                   text=player_text, team=team, error=str(e))
            raise
        
        return None

    # Keep existing methods but update for new structure
    def _extract_nwt_from_clean_line(self, line: str, team: str) -> Optional[Dict]:
        """Extract NWT player from clean line like '7 Santi Aldama NWT - Injury/Illness - Right Foot; Strain'"""
        try:
            parts = line.split(' NWT - ', 1)
            if len(parts) != 2:
                return None
            
            name_part = parts[0].strip()
            reason_part = parts[1].strip()
            
            # Remove jersey number from start - FIXED to include hyphens  
            name = re.sub(r'^\d+\s+', '', name_part).strip()
            
            if name and len(name) > 1:
                return {
                    "name": name,
                    "team": team,
                    "status": "did_not_play",
                    "dnp_reason": f"NWT - {reason_part}",
                    "category": "NWT"
                }
        except AttributeError as e:
            logger.error("CRITICAL CODE BUG extracting NWT from line '%s': %s", line, e)
            self._log_parsing_issue("unknown_player_categories", 
                                   text=line, team=team, error=str(e), category="NWT")
            raise
        except (ValueError, TypeError) as e:
            logger.error("PARSING ERROR extracting NWT from line '%s': %s", line, e)
            self._log_parsing_issue("unknown_player_categories", 
                                   text=line, team=team, error=str(e), category="NWT")
            raise
        
        return None

    def _extract_dnp_from_clean_line(self, line: str, team: str) -> Optional[Dict]:
        """Extract DNP player from clean line like '24 Marcus Morris Sr. DNP - Coach's Decision'"""
        try:
            parts = line.split(' DNP - ', 1)
            if len(parts) != 2:
                return None
            
            name_part = parts[0].strip()
            reason_part = parts[1].strip()
            
            # Remove jersey number from start - FIXED to include hyphens
            name = re.sub(r'^\d+\s+', '', name_part).strip()
            
            if name and len(name) > 1:
                return {
                    "name": name,
                    "team": team,
                    "status": "did_not_play",
                    "dnp_reason": f"DNP - {reason_part}",
                    "category": "DNP"
                }
        except AttributeError as e:
            logger.error("CRITICAL CODE BUG extracting DNP from line '%s': %s", line, e)
            self._log_parsing_issue("unknown_player_categories", 
                                   text=line, team=team, error=str(e), category="DNP")
            raise
        except (ValueError, TypeError) as e:
            logger.error("PARSING ERROR extracting DNP from line '%s': %s", line, e)
            self._log_parsing_issue("unknown_player_categories", 
                                   text=line, team=team, error=str(e), category="DNP")
            raise
        
        return None

    def _extract_active_from_clean_line(self, line: str, team: str) -> Optional[Dict]:
        """Extract active player with full stats from line like '45 GG Jackson F 35:42 7 21 2 10 6 6 0 2 2 2 2 2 1 1 -13 22'"""
        try:
            # Find minutes pattern
            minutes_match = re.search(r'(\d{1,2}:\d{2})', line)
            if not minutes_match:
                return None
            minutes = minutes_match.group(1)
            
            # Split on minutes to get parts before and after
            before_minutes = line.split(minutes)[0].strip()
            after_minutes = line.split(minutes)[1].strip() if minutes in line else ""
            
            # Extract name from before minutes - FIXED to include hyphens
            # Typical pattern: "32 Karl-Anthony Towns C" -> want "Karl-Anthony Towns"
            name_match = re.search(r'^\d+\s+([A-Za-z\s\.\'\-Jr Sr]+?)\s+[FGC]?\s*$', before_minutes)
            if not name_match:
                # Try simpler pattern without position
                name_match = re.search(r'^\d+\s+([A-Za-z\s\.\'\-Jr Sr]+)', before_minutes)
            
            if not name_match:
                self._log_parsing_issue("failed_stat_lines", 
                                       text=line, team=team, reason="no_name_match")
                return None
            
            name = name_match.group(1).strip()
            
            # Parse full stat line from after minutes
            # Expected order: FG FGA 3P 3PA FT FTA OR DR TOT A PF ST TO BS +/- PTS
            stats = self._parse_stat_line(after_minutes, line)
            
            # Add minutes to stats
            stats["minutes"] = minutes
            
            # Sanity check
            if name and len(name) > 2 and not name.isdigit():
                return {
                    "name": name,
                    "team": team,
                    "status": "active",
                    "stats": stats
                }
            else:
                self._log_parsing_issue("failed_stat_lines", 
                                       text=line, team=team, reason="invalid_name", name=name)
                
        except AttributeError as e:
            logger.error("CRITICAL CODE BUG extracting active player from line '%s': %s", line, e)
            self._log_parsing_issue("failed_stat_lines", 
                                   text=line, team=team, error=str(e))
            raise
        except (ValueError, TypeError) as e:
            logger.error("PARSING ERROR extracting active player from line '%s': %s", line, e)
            self._log_parsing_issue("failed_stat_lines", 
                                   text=line, team=team, error=str(e))
            raise
        
        return None

    def _parse_stat_line(self, stat_text: str, full_line: str = "") -> Dict[str, Any]:
        """Parse NBA stat line into structured data."""
        # Split stats by spaces and clean
        stat_parts = [s.strip() for s in stat_text.split() if s.strip()]
        
        # Initialize with defaults
        stats = {
            "minutes": "0:00",
            "field_goals_made": 0,
            "field_goals_attempted": 0,
            "three_pointers_made": 0,
            "three_pointers_attempted": 0,
            "free_throws_made": 0,
            "free_throws_attempted": 0,
            "offensive_rebounds": 0,
            "defensive_rebounds": 0,
            "total_rebounds": 0,
            "assists": 0,
            "personal_fouls": 0,
            "steals": 0,
            "turnovers": 0,
            "blocks": 0,
            "plus_minus": 0,
            "points": 0,
            # Calculated fields
            "field_goal_percentage": 0.0,
            "three_point_percentage": 0.0,
            "free_throw_percentage": 0.0,
        }
        
        try:
            # Expected order after minutes: FG FGA 3P 3PA FT FTA OR DR TOT A PF ST TO BS +/- PTS
            if len(stat_parts) >= 16:  # Minimum expected for full stat line
                stats["field_goals_made"] = self._safe_int(stat_parts[0])
                stats["field_goals_attempted"] = self._safe_int(stat_parts[1])
                stats["three_pointers_made"] = self._safe_int(stat_parts[2])
                stats["three_pointers_attempted"] = self._safe_int(stat_parts[3])
                stats["free_throws_made"] = self._safe_int(stat_parts[4])
                stats["free_throws_attempted"] = self._safe_int(stat_parts[5])
                stats["offensive_rebounds"] = self._safe_int(stat_parts[6])
                stats["defensive_rebounds"] = self._safe_int(stat_parts[7])
                stats["total_rebounds"] = self._safe_int(stat_parts[8])
                stats["assists"] = self._safe_int(stat_parts[9])
                stats["personal_fouls"] = self._safe_int(stat_parts[10])
                stats["steals"] = self._safe_int(stat_parts[11])
                stats["turnovers"] = self._safe_int(stat_parts[12])
                stats["blocks"] = self._safe_int(stat_parts[13])
                
                # Plus/minus can be negative, handle carefully
                plus_minus_str = stat_parts[14]
                if plus_minus_str.startswith('-'):
                    stats["plus_minus"] = -self._safe_int(plus_minus_str[1:])
                else:
                    stats["plus_minus"] = self._safe_int(plus_minus_str)
                
                # Points is typically the last number
                stats["points"] = self._safe_int(stat_parts[15])
                
                # Calculate percentages
                stats["field_goal_percentage"] = self._safe_percentage(
                    stats["field_goals_made"], stats["field_goals_attempted"]
                )
                stats["three_point_percentage"] = self._safe_percentage(
                    stats["three_pointers_made"], stats["three_pointers_attempted"]
                )
                stats["free_throw_percentage"] = self._safe_percentage(
                    stats["free_throws_made"], stats["free_throws_attempted"]
                )
                
            else:
                # Log the short stat line issue
                self._log_parsing_issue("failed_stat_lines", 
                                       text=full_line, 
                                       reason="insufficient_stats", 
                                       stat_parts_count=len(stat_parts),
                                       stat_parts=stat_parts[:10])  # Only log first 10 to avoid huge logs
                
                # Fallback: try to at least get points (last number)
                if stat_parts:
                    # Look for points at the end
                    for part in reversed(stat_parts):
                        if part.isdigit():
                            stats["points"] = int(part)
                            break
                            
                logger.debug("Stat line too short (%d parts), using fallback: %s", len(stat_parts), stat_parts)
        
        except AttributeError as e:
            logger.error("CRITICAL CODE BUG parsing stat line '%s': %s", stat_text, e)
            self._log_parsing_issue("failed_stat_lines", 
                                   text=full_line, error=str(e), context="stat_parsing")
            raise
        except (ValueError, TypeError, IndexError) as e:
            logger.error("PARSING ERROR in stat line '%s': %s", stat_text, e)
            self._log_parsing_issue("failed_stat_lines", 
                                   text=full_line, error=str(e), context="stat_parsing")
            raise
        
        return stats

    def _safe_int(self, value: str) -> int:
        """Safely convert string to int, return 0 if invalid."""
        try:
            return int(value) if value.isdigit() else 0
        except (ValueError, AttributeError):
            return 0

    def _safe_percentage(self, made: int, attempted: int) -> float:
        """Safely calculate percentage, return 0.0 if attempted is 0."""
        try:
            return round(made / attempted, 3) if attempted > 0 else 0.0
        except (ZeroDivisionError, TypeError):
            return 0.0
        
    def _detect_special_venue_game(self, text: str, game_info: Dict) -> Dict[str, bool]:
        """
        Detect if this is a special venue game and what type.
        Returns flags for different types of special games.
        """
        arena = game_info.get("arena", "").lower()
        city = game_info.get("city", "").lower() 
        
        # Neutral site venues (neither team's home court)
        neutral_venues = [
            "t-mobile arena",  # Las Vegas
            "accor arena",     # Paris  
            "o2 arena",        # London
            "arena cdmx",      # Mexico City
            "saitama super arena",  # Tokyo
            "etihad arena",    # Abu Dhabi
        ]
        
        # Relocated home games (team playing at alternate venue)
        relocated_patterns = [
            ("moody center", "austin"),  # San Antonio games in Austin
            ("honda center", "anaheim"), # Potential LA team relocations
        ]
        
        is_neutral_site = any(venue in arena for venue in neutral_venues)
        is_relocated_home = any(venue in arena and location in city 
                            for venue, location in relocated_patterns)
        is_international = city in ["paris", "london", "tokyo", "mexico city", "abu dhabi"]
        
        # Check if standard parsing labels exist
        has_standard_labels = "HOME:" in text and "VISITOR:" in text
        
        return {
            "is_special_venue": is_neutral_site or is_relocated_home or is_international,
            "is_neutral_site": is_neutral_site,
            "is_relocated_home": is_relocated_home, 
            "is_international": is_international,
            "has_standard_labels": has_standard_labels,
            "needs_fallback_parsing": not has_standard_labels
        }

    def _parse_clean_text(self, text: str, active_players: List[Dict], 
                        dnp_players: List[Dict], inactive_players: List[Dict], game_info: Dict) -> None:
        """Enhanced parsing with neutral site support."""
        
        logger.info("Parsing clean text (%d chars)", len(text))
        
        # Extract game metadata from the top of the PDF
        self._extract_game_metadata(text, game_info)
        
        # ENHANCED: Detect special venue games and set flags
        venue_flags = self._detect_special_venue_game(text, game_info)
        game_info.update(venue_flags)
        
        # ENHANCED: Choose parsing strategy based on venue type
        if venue_flags["needs_fallback_parsing"]:
            logger.warning("Standard HOME/VISITOR labels missing - using fallback parsing for %s", 
                        self.opts["game_code"])
            self._parse_special_venue_format(text, active_players, dnp_players, inactive_players, game_info)
        else:
            logger.info("Using standard parsing format for %s", self.opts["game_code"])
            self._parse_standard_format(text, active_players, dnp_players, inactive_players, game_info)

    def _parse_standard_format(self, text: str, active_players: List[Dict], 
                            dnp_players: List[Dict], inactive_players: List[Dict], game_info: Dict) -> None:
        """Original parsing logic for standard games."""
        lines = text.split('\n')
        current_team = None
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            # Standard team detection
            if 'VISITOR:' in line:
                team_match = re.search(r'VISITOR:\s*(.+?)\s*\(', line)
                if team_match:
                    current_team = team_match.group(1)
                    logger.debug("Found visitor team: %s", current_team)
                continue
            elif 'HOME:' in line:
                team_match = re.search(r'HOME:\s*(.+?)\s*\(', line)
                if team_match:
                    current_team = team_match.group(1)
                    logger.debug("Found home team: %s", current_team)
                continue
            
            # Continue with existing parsing logic...
            self._parse_player_line(line, current_team, active_players, dnp_players, inactive_players, lines, i)

    def _parse_special_venue_format(self, text: str, active_players: List[Dict], 
                               dnp_players: List[Dict], inactive_players: List[Dict], game_info: Dict) -> None:
        """Fallback parsing for neutral site/international games without HOME/VISITOR labels."""
        
        lines = text.split('\n')
        
        away_team_abbr = self.opts["away_team"]  # "ATL"
        home_team_abbr = self.opts["home_team"]   # "MIL"
        
        current_team = None
        current_team_abbr = None
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
                
            # Detect team sections by team name with record
            team_section = self._detect_team_section_fallback(line, {}, away_team_abbr, home_team_abbr)
            if team_section:
                current_team = team_section["team_name"]
                current_team_abbr = team_section["abbr"] 
                logger.debug("Found %s team section: %s (%s)", team_section["type"], current_team, current_team_abbr)
                continue
            
            # Parse player lines with team context
            if current_team:
                self._parse_player_line(line, current_team, active_players, dnp_players, inactive_players, lines, i)
        
        # Log results
        logger.info("Special venue parsing complete: %d active, %d DNP, %d inactive players", 
                len(active_players), len(dnp_players), len(inactive_players))
        
        # Warning (not error) if no active players found
        if len(active_players) == 0:
            logger.warning("No active players found in special venue game %s - may need manual review", 
                        self.opts["game_code"])
            # Don't crash - just log the issue
            if hasattr(self, 'parsing_issues') and 'parsing_failure' in self.parsing_issues:
                self._log_parsing_issue("parsing_failure", 
                                    game_code=self.opts["game_code"],
                                    venue_type="special_venue", 
                                    arena=game_info.get("arena"),
                                    total_dnp=len(dnp_players),
                                    total_inactive=len(inactive_players))

    def _detect_team_sections_by_order(self, text: str, away_abbr: str, home_abbr: str) -> Dict:
        """
        Detect team sections in special venue games.
        Look for patterns that indicate team sections without HOME/VISITOR labels.
        """
        # Look for team full names or abbreviations in specific patterns
        team_patterns = [
            # Pattern: Team name followed by record in parentheses
            rf"({away_abbr}|{home_abbr})\s*\(\d+-\d+\)",
            # Pattern: Full team names 
            r"(Hawks|Bucks|Suns|Pacers|Warriors|Lakers)",  # Add more as needed
        ]
        
        sections = {"away": None, "home": None}
        
        # This is a simplified version - you'd want to make this more robust
        # by actually parsing the team names and positions in the PDF
        
        return sections

    def _detect_team_section_fallback(self, line: str, team_sections: Dict, 
                                    away_abbr: str, home_abbr: str) -> Optional[Dict]:
        """
        Detect team sections without HOME/VISITOR labels.
        Look for team names with records like "Atlanta Hawks (14-13)"
        """
        
        # Pattern: Team name followed by record in parentheses
        team_record_pattern = r'^([A-Z][A-Za-z\s]+)\s+\((\d+-\d+)\)$'
        match = re.match(team_record_pattern, line.strip())
        
        if match:
            team_full_name = match.group(1).strip()
            normalized_pdf_name = self._normalize_team_name_for_comparison(team_full_name)
            
            # Clean team name lookup (only one version of each)
            team_name_to_abbr = {
                # Eastern Conference
                "Atlanta Hawks": "ATL",
                "Boston Celtics": "BOS", 
                "Brooklyn Nets": "BKN",
                "Charlotte Hornets": "CHA",
                "Chicago Bulls": "CHI",
                "Cleveland Cavaliers": "CLE",
                "Detroit Pistons": "DET",
                "Indiana Pacers": "IND", 
                "Miami Heat": "MIA",
                "Milwaukee Bucks": "MIL",
                "New York Knicks": "NYK",
                "Orlando Magic": "ORL",
                "Philadelphia 76ers": "PHI",
                "Toronto Raptors": "TOR",
                "Washington Wizards": "WAS",
                
                # Western Conference  
                "Dallas Mavericks": "DAL",
                "Denver Nuggets": "DEN",
                "Golden State Warriors": "GSW",
                "Houston Rockets": "HOU",
                "Los Angeles Clippers": "LAC", 
                "Los Angeles Lakers": "LAL",
                "Memphis Grizzlies": "MEM",
                "Minnesota Timberwolves": "MIN",
                "New Orleans Pelicans": "NOP", 
                "Oklahoma City Thunder": "OKC",
                "Phoenix Suns": "PHX",
                "Portland Trail Blazers": "POR",
                "Sacramento Kings": "SAC",
                "San Antonio Spurs": "SAS",
                "Utah Jazz": "UTA"
            }
            
            # Find matching team by normalized comparison
            team_abbr = None
            matched_team_name = None
            
            for lookup_name, abbr in team_name_to_abbr.items():
                normalized_lookup = self._normalize_team_name_for_comparison(lookup_name)
                if normalized_pdf_name == normalized_lookup:
                    team_abbr = abbr
                    matched_team_name = lookup_name
                    break
            
            if team_abbr:
                # Determine if this is away or home team based on game_code
                if team_abbr == away_abbr:
                    return {"type": "away", "team_name": matched_team_name, "abbr": team_abbr}
                elif team_abbr == home_abbr:
                    return {"type": "home", "team_name": matched_team_name, "abbr": team_abbr}
                else:
                    logger.debug("Found team %s (%s) but doesn't match game teams %s vs %s", 
                            matched_team_name, team_abbr, away_abbr, home_abbr)
            else:
                logger.debug("Unknown team name: %s (normalized: %s)", team_full_name, normalized_pdf_name)
        
        return None

    def _normalize_team_name_for_comparison(self, team_name: str) -> str:
        """Normalize team name for comparison by removing spaces, lowercasing, and removing punctuation."""
        return re.sub(r'[^a-z]', '', team_name.lower())

    def _parse_player_line(self, line: str, current_team: str, active_players: List[Dict], 
                        dnp_players: List[Dict], inactive_players: List[Dict], 
                        all_lines: List[str], line_idx: int) -> None:
        """Consolidated player line parsing logic."""
        
        # NWT players
        if ' NWT - ' in line:
            player = self._extract_nwt_from_clean_line(line, current_team)
            if player:
                dnp_players.append(player)
                logger.debug("Found NWT player: %s - %s", player['name'], player['dnp_reason'])
        
        # DNP players
        elif ' DNP - ' in line:
            player = self._extract_dnp_from_clean_line(line, current_team)
            if player:
                dnp_players.append(player)
                logger.debug("Found DNP player: %s - %s", player['name'], player['dnp_reason'])
        
        # DND players
        elif ' DND - ' in line:
            player = self._extract_dnd_from_clean_line(line, current_team)
            if player:
                dnp_players.append(player)
                logger.debug("Found DND player: %s - %s", player['name'], player['dnp_reason'])
        
        # Active players (lines with minutes like "35:42")
        elif re.search(r'\d{1,2}:\d{2}', line) and current_team:
            player = self._extract_active_from_clean_line(line, current_team)
            if player:
                active_players.append(player)
                logger.debug("Found active player: %s (%s pts, %s min)",
                        player['name'], player.get('stats', {}).get('points', 0), 
                        player.get('stats', {}).get('minutes', '0:00'))
        
        # Inactive player sections
        elif line.startswith('Inactive:'):
            inactive_list = self._extract_inactive_players_from_line(line, all_lines, line_idx)
            inactive_players.extend(inactive_list)
            for player in inactive_list:
                logger.debug("Found inactive player: %s - %s (%s)",
                        player['name'], player['reason'], player['team'])

    
    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #    
    def get_scraper_stats(self) -> dict:
        """Return scraper statistics for SCRAPER_STATS log (summary only, not full data)."""
        total_issues = sum(len(issues) for issues in self.parsing_issues.values())
        
        return {
            "game_code": self.opts["game_code"],
            "matchup": self.opts["matchup"],
            "pdf_version": self.opts["version"],
            "pdf_source": self.opts["pdf_source"],  # NEW: track source
            "arena": self.data.get("arena", "unknown"),
            "attendance": self.data.get("attendance", 0),
            "total_players": self.data.get("total_players", 0),
            "active_count": self.data.get("active_count", 0),
            "dnp_count": self.data.get("dnp_count", 0),
            "inactive_count": self.data.get("inactive_count", 0),
            "officials_count": len(self.data.get("officials", [])),
            "text_length": self.data.get("debug_info", {}).get("text_length", 0),
            "parser_used": self.data.get("debug_info", {}).get("parser_used", "unknown"),
            "parsing_issues_count": total_issues,
            "has_parsing_issues": total_issues > 0,
        }


# --------------------------------------------------------------------------- #
# Flask and CLI entry points
# --------------------------------------------------------------------------- #
create_app = convert_existing_flask_scraper(GetNbaComGamebookPdf)

if __name__ == "__main__":
    main = GetNbaComGamebookPdf.create_cli_and_flask_main()
    main()
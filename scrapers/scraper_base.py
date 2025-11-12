"""
scraper_base.py

A base class 'ScraperBase' that handles:
 - Option validation
 - HTTP downloading (with optional proxy & retries)
 - Decoding JSON (if requested)
 - Validating & transforming data
 - Exporting data (via a registry-based approach)
 - Logging structured steps & final stats
 - Capturing a short run ID for correlation
 - Providing hooks for child classes to override
 - Enhanced Sentry integration for monitoring
 - Multi-channel notifications (Email + Slack) for critical errors
 - Phase 1 orchestration logging to BigQuery
"""

import sentry_sdk
from .utils.env_utils import is_local
import os

# Initialize Sentry with environment-specific configuration
ENV = "development" if is_local() else "production"
sentry_dsn = os.getenv("SENTRY_DSN", "https://96f5d7efbb7105ef2c05aa551fa5f4e0@o102085.ingest.us.sentry.io/4509460047790080")

sentry_sdk.init(
    dsn=sentry_dsn,
    environment=ENV,
    traces_sample_rate=1.0 if ENV == "development" else 0.1,
    profiles_sample_rate=1.0 if ENV == "development" else 0.01,
    send_default_pii=False,
)

import enum
from typing import Callable
import requests

try:                                         # Playwright core
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ModuleNotFoundError:
    _PLAYWRIGHT_AVAILABLE = False

# ---- optional stealth plug‑in (v1.x or v2.x) ---------------------------
_STEALTH_FN: Callable | None = None
try:
    from playwright_stealth import stealth_sync as _STEALTH_FN          # ≤ v1.1
except ImportError:
    try:
        import playwright_stealth as _ps                                # ≥ v2.0
        _STEALTH_FN = getattr(_ps, "stealth", None)
    except ImportError:
        _STEALTH_FN = None
_STEALTH_AVAILABLE = callable(_STEALTH_FN)

import logging, urllib.parse
import time
import sys
import traceback
import pprint
import json
import random
import uuid
from datetime import datetime, timezone

from requests.exceptions import ProxyError, ConnectTimeout, ConnectionError, ReadTimeout
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .utils.exceptions import (
    DownloadDataException,
    DownloadDecodeMaxRetryException,
    NoHttpStatusCodeException,
    InvalidHttpStatusCodeException,
    RetryInvalidHttpStatusCodeException,
    InvalidRegionDecodeException
)
from .exporters import EXPORTER_REGISTRY
from .utils.proxy_utils import get_proxy_urls
from .utils.nba_header_utils import (
    stats_nba_headers,
    data_nba_headers,
    core_api_headers,
    _ua,
    cdn_nba_headers,
    stats_api_headers,
    bettingpros_headers,
)

# Import notification system
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

##############################################################################
# Configure a default logger so INFO messages appear in the console.
##############################################################################
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger("scraper_base")
logger.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
# Enumerations to prevent magic strings for download types and export modes.
# --------------------------------------------------------------------------- #
class DownloadType(str, enum.Enum):
    """
    Defines how the HTTP response is interpreted:
      - JSON: parse as JSON (store in self.decoded_data)
      - BINARY: do not parse, store raw bytes only
      - HTML: store the response text in self.decoded_data
    """
    JSON = "json"
    BINARY = "binary"
    HTML = "html"


class ExportMode(str, enum.Enum):
    """
    Defines which data we export in export_data():
      - RAW: self.raw_response.content (raw bytes)
      - DECODED: self.decoded_data (Python dict/list if JSON)
      - DATA: self.data (the result of transformations or slicing)
    """
    RAW = "raw"
    DECODED = "decoded"
    DATA = "data"


class ScraperBase:
    """
    A base class orchestrating a typical scraper lifecycle:
      1) Parse/validate options
      2) Set up URL & headers
      3) Download (with optional proxy, retries, backoff)
      4) Decode if configured (e.g., JSON or HTML text)
      5) Validate downloaded data
      6) Optionally extract opts from data & transform data
      7) Export results to GCS/File/etc.
      8) Log final stats & run ID
      9) Log execution to Phase 1 orchestration (BigQuery)

    Child classes typically override:
      - set_url(), set_headers()
      - validate_download_data()
      - extract_opts_from_data(), transform_data()
      - get_scraper_stats() (for final stats line)
      - run-specific settings (download_type, decode_download_data, etc.)
    """

    ##########################################################################
    # Class-level Configs: required_opts, additional_opts, exporters, etc.
    ##########################################################################
    required_opts = []        # child scrapers define e.g. ["gamedate"]
    additional_opts = []      # child scrapers define if they auto-set "season", etc.
    exporters = []            # array of dicts describing export configs

    # Download / decode settings
    proxy_enabled = False
    # If you pass opts["proxyUrl"]="https://user:pass@1.2.3.4:3128"
    # it will be copied into self.proxy_url during set_opts().
    proxy_url: str | None = None
    test_proxies = False
    decode_download_data = True
    download_type = DownloadType.JSON

    # ---- NEW default flags for headless browser support -----------------
    browser_enabled = False          # subclasses set True if needed
    browser_url: str | None = None   # page that sets the Akamai cookies
    
    max_retries_http = 3
    timeout_http = 20
    no_retry_status_codes: list[int] = [404, 422]
    max_retries_decode = 8

    # NEW: Add this single property
    treat_max_retries_as_success: list[int] = []  # Status codes to treat as success after max retries
    
    # Header/profile defaults
    header_profile: str | None = None          # "stats" | "data" | "core" | "espn"
    headers: dict[str, str] = {}

    # Data placeholders (typed so attr always exist)
    raw_response: requests.Response | None = None
    decoded_data: dict | list | str | bytes = {}
    data: dict = {}
    stats = {}

    # Time tracking
    time_markers = {}
    pp = pprint.PrettyPrinter(indent=4)

    # If set True, will store partial data on exception
    save_data_on_error = True

    # ---- NEW: GCS support flags -----------------
    gcs_enabled = False          # subclasses set True if needed
    gcs_bucket: str | None = None
    gcs_path: str | None = None

    def __init__(self):
        """
        Initialize instance variables. 
        We also generate a short run_id for correlation across logs.
        """
        self.opts = {}
        self.http_downloader = None
        self.raw_response = None
        self.decoded_data = {}
        self.data = {}
        self.stats = {}
        self.time_markers = {}
        self.download_retry_count = 0

        # Generate a short run ID (first 8 chars of a UUID).
        self.run_id = str(uuid.uuid4())[:8]
        self.stats["run_id"] = self.run_id

    ##########################################################################
    # Main Entrypoint for the Lifecycle (Enhanced with Sentry + Notifications)
    ##########################################################################
    def run(self, opts=None):
        """
        Enhanced run method with comprehensive Sentry tracking, error handling,
        multi-channel notifications, and Phase 1 orchestration logging.
        """
        if opts is None:
            opts = {}

        # Add scraper context to Sentry
        sentry_sdk.set_tag("scraper.name", self.__class__.__name__)
        sentry_sdk.set_tag("scraper.run_id", self.run_id)
        sentry_sdk.set_context("scraper_opts", {
            "sport": opts.get("sport"),
            "date": opts.get("date"),
            "group": opts.get("group"),
            "debug": opts.get("debug", False)
        })

        # Track the entire scraper run as a transaction
        with sentry_sdk.start_transaction(
            op="scraper.run",
            name=f"{self.__class__.__name__}.run"
        ) as transaction:
            
            transaction.set_tag("scraper.sport", opts.get("sport", "unknown"))
            transaction.set_tag("scraper.group", opts.get("group", "unknown"))
            
            try:
                # Re-init, but preserve the run_id
                self._reinit_except_run_id()

                self.mark_time("total")
                # Track start time for orchestration logging
                self.stats["start_time"] = datetime.now(timezone.utc)
                
                self.step_info("start", "Scraper run starting", extra={"opts": opts})

                self.set_opts(opts)
                self.validate_opts()
                self.set_exporter_group_to_opts()
                self.set_additional_opts()
                self.validate_additional_opts()

                self.set_url()
                self.set_headers()

                self.mark_time("download")
                self.download_and_decode()
                download_seconds = self.get_elapsed_seconds("download")
                self.stats["download_time"] = download_seconds
                self.step_info("download_complete", "Download+Decode completed",
                            extra={"elapsed": download_seconds})

                if self.decode_download_data:
                    self.validate_download_data()
                    self.extract_opts_from_data()
                    self.validate_extracted_opts()
                    self.transform_data()

                self.mark_time("export")
                self.export_data()
                export_seconds = self.get_elapsed_seconds("export")
                self.stats["export_time"] = export_seconds
                self.step_info("export_complete", "Export completed", extra={"elapsed": export_seconds})

                self.post_export()

                total_seconds = self.get_elapsed_seconds("total")
                self.stats["total_runtime"] = total_seconds
                self.step_info("finish", "Scraper run completed",
                            extra={"total_seconds": total_seconds})

                # Track success metrics in Sentry
                transaction.set_tag("scraper.status", "success")
                transaction.set_data("scraper.row_count", self.get_scraper_stats().get("rowCount", 0))
                transaction.set_data("scraper.runtime_seconds", total_seconds)
                
                # ✅ NEW: Log execution to Phase 1 orchestration
                self._log_execution_to_bigquery()
                
                if self.decode_download_data:
                    return self.get_return_value()
                else:
                    return True
                
            except Exception as e:
                logger.error("ScraperBase Error: %s", e, exc_info=True)            
                traceback.print_exc()

                # Enhanced Sentry error tracking
                sentry_sdk.set_tag("scraper.status", "error")
                sentry_sdk.set_context("scraper_error", {
                    "error_type": type(e).__name__,
                    "url": getattr(self, 'url', 'unknown'),
                    "retry_count": getattr(self, 'download_retry_count', 0),
                    "opts": opts,
                    "step": self._get_current_step()
                })
                
                # Capture exception in Sentry
                sentry_sdk.capture_exception(e)

                # Send notification for scraper failure
                try:
                    notify_error(
                        title=f"Scraper Failed: {self.__class__.__name__}",
                        message=f"Scraper run failed at {self._get_current_step()} step: {str(e)}",
                        details={
                            'scraper': self.__class__.__name__,
                            'run_id': self.run_id,
                            'error_type': type(e).__name__,
                            'url': getattr(self, 'url', 'unknown'),
                            'retry_count': self.download_retry_count,
                            'step': self._get_current_step(),
                            'opts': {
                                'date': opts.get('date'),
                                'group': opts.get('group'),
                                'sport': opts.get('sport')
                            }
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")

                # ✅ NEW: Log failed execution to Phase 1 orchestration
                try:
                    self._log_failed_execution_to_bigquery(e)
                except Exception as log_ex:
                    logger.warning(f"Failed to log failed execution: {log_ex}")

                # If we want to save partial data or raw data on error
                if self.save_data_on_error:
                    self._debug_save_data_on_error(e)

                self.report_error(e)  # Sentry/email/Slack, etc.
                return False

    def _get_current_step(self):
        """Helper to determine current processing step for error context."""
        if not hasattr(self, 'url') or not self.url:
            return "initialization"
        elif not self.raw_response:
            return "download"
        elif not self.decoded_data:
            return "decode"
        elif not self.data:
            return "transform"
        else:
            return "export"

    def _reinit_except_run_id(self):
        """
        Re-initialize instance variables while preserving the same run_id.
        This ensures partial re-runs still share the same correlation ID.
        """
        saved_run_id = self.run_id
        self.__init__()
        self.run_id = saved_run_id
        self.stats["run_id"] = saved_run_id

    ##########################################################################
    # Phase 1 Orchestration Logging (NEW)
    ##########################################################################
    
    def _get_scraper_name(self) -> str:
        """
        Extract clean scraper name from class name for orchestration logging.
        
        Converts class names like:
          - GetNBAComInjuryReport → nbac_injury_report
          - GetOddsAPIEvents → oddsa_events
          - GetBallDontLieBoxscores → bdl_boxscores
        
        Returns:
            str: Snake-case scraper name with source prefix
        """
        import re
        
        class_name = self.__class__.__name__
        
        # Remove 'Get' prefix if present
        if class_name.startswith('Get'):
            class_name = class_name[3:]
        
        # Convert CamelCase to snake_case
        name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', class_name)
        name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()
        
        # Apply standard source prefixes
        name = name.replace('nba_com_', 'nbac_')
        name = name.replace('odds_api_', 'oddsa_')
        name = name.replace('ball_dont_lie_', 'bdl_')
        name = name.replace('big_data_ball_', 'bdb_')
        name = name.replace('espn_', 'espn_')
        
        return name
    
    def _determine_execution_source(self) -> tuple[str, str, str]:
        """
        Determine execution source, environment, and triggered_by for logging.
        
        Source values:
          - CONTROLLER: Called by master workflow controller
          - MANUAL: Direct API call (testing)
          - LOCAL: Running on dev laptop
          - CLOUD_RUN: Direct endpoint call to Cloud Run service
          - SCHEDULER: Triggered by Cloud Scheduler job
          - RECOVERY: Republished by cleanup processor (self-healing)
        
        Returns:
            tuple: (source, environment, triggered_by)
        """
        import getpass
        
        # Check explicit source in opts (workflow controller sets this)
        if 'source' in self.opts:
            source = self.opts['source']
        # Check if running in Cloud Run
        elif os.getenv('K_SERVICE'):
            if self.opts.get('workflow') and self.opts['workflow'] != 'MANUAL':
                source = 'CONTROLLER'  # Called by master controller
            else:
                source = 'CLOUD_RUN'  # Direct endpoint call
        # Check if running locally
        elif is_local():
            source = 'LOCAL'
        else:
            source = 'MANUAL'
        
        # Determine environment (reuse existing ENV detection)
        environment = 'local' if is_local() else self.opts.get('group', 'prod')
        
        # Determine triggered_by based on source
        if source == 'CONTROLLER':
            triggered_by = 'master-controller'
        elif source == 'SCHEDULER':
            triggered_by = 'cloud-scheduler'
        elif source == 'RECOVERY':
            triggered_by = 'cleanup-processor'
        elif source == 'LOCAL':
            try:
                triggered_by = f"{getpass.getuser()}@local"
            except:
                triggered_by = 'unknown@local'
        else:
            triggered_by = os.getenv('K_SERVICE', 'manual')
        
        return source, environment, triggered_by
    
    def _determine_execution_status(self) -> tuple[str, int]:
        """
        Determine execution status using 3-status system for orchestration.
        
        Status values:
          - 'success': Got data (record_count > 0)
          - 'no_data': Tried but empty (record_count = 0)
          - 'failed': Error occurred (handled in _log_failed_execution_to_bigquery)
        
        This enables discovery mode: controller stops trying after 'success',
        keeps trying after 'no_data'.
        
        Returns:
            tuple: (status, record_count)
        """
        # Count records in self.data
        if isinstance(self.data, dict):
            # Standard pattern: {'records': [...], 'metadata': {...}}
            record_count = len(self.data.get('records', []))
            # Check if scraper marked this as intentionally empty
            is_empty = self.data.get('metadata', {}).get('is_empty_report', False)
        elif isinstance(self.data, list):
            # Simple list of records
            record_count = len(self.data)
            is_empty = False
        else:
            # Empty or unexpected format
            record_count = 0
            is_empty = False
        
        # Determine status based on record count
        if record_count > 0:
            status = 'success'
        elif is_empty or record_count == 0:
            status = 'no_data'
        else:
            # Fallback (shouldn't reach here)
            status = 'success'
        
        return status, record_count
    
    def _log_execution_to_bigquery(self):
        """
        Log successful execution to nba_orchestration.scraper_execution_log.
        
        Uses 3-status system (success/no_data) based on record_count.
        Never fails the scraper - logs errors but continues.
        """
        try:
            from shared.utils.bigquery_utils import insert_bigquery_rows
            
            source, environment, triggered_by = self._determine_execution_source()
            status, record_count = self._determine_execution_status()
            
            now = datetime.now(timezone.utc)
            
            # Get start_time, ensure it's a datetime, then convert to ISO
            start_time = self.stats.get('start_time', now)
            if isinstance(start_time, datetime):
                triggered_at_iso = start_time.isoformat()
            else:
                triggered_at_iso = now.isoformat()
            
            record = {
                'execution_id': self.run_id,
                'scraper_name': self._get_scraper_name(),
                'workflow': self.opts.get('workflow', 'MANUAL'),
                'status': status,
                'triggered_at': triggered_at_iso,  # ✅ FIXED: ISO string
                'completed_at': now.isoformat(),   # ✅ FIXED: ISO string
                'duration_seconds': self.stats.get('total_runtime', 0),
                'source': source,
                'environment': environment,
                'triggered_by': triggered_by,
                'gcs_path': self.opts.get('gcs_output_path'),
                'data_summary': json.dumps({
                    'record_count': record_count,
                    'scraper_stats': self.get_scraper_stats(),
                    'is_empty_report': status == 'no_data'
                }),
                'error_type': None,
                'error_message': None,
                'retry_count': self.download_retry_count,
                'recovery': self.opts.get('recovery', False),
                'run_id': self.run_id,
                'opts': json.dumps({k: v for k, v in self.opts.items() 
                        if k not in ['password', 'api_key', 'token', 'proxyUrl']}),
                'created_at': now.isoformat()      # ✅ FIXED: ISO string
            }
            
            insert_bigquery_rows('nba_orchestration.scraper_execution_log', [record])
            logger.info(f"✅ Orchestration logged: {status} ({record_count} records) from {source}")
            
        except Exception as e:
            # Don't fail the scraper if logging fails
            logger.error(f"Failed to log execution to orchestration: {e}")
            # Still capture in Sentry for alerting
            try:
                sentry_sdk.capture_exception(e)
            except:
                pass

    def _log_failed_execution_to_bigquery(self, error: Exception):
        """
        Log failed execution to nba_orchestration.scraper_execution_log.
        
        Status is always 'failed' with error details captured.
        Never fails the scraper - logs errors but continues.
        
        Args:
            error: The exception that caused the failure
        """
        try:
            from shared.utils.bigquery_utils import insert_bigquery_rows
            
            source, environment, triggered_by = self._determine_execution_source()
            now = datetime.now(timezone.utc)
            
            # Get start_time, ensure it's a datetime, then convert to ISO
            start_time = self.stats.get('start_time', now)
            if isinstance(start_time, datetime):
                triggered_at_iso = start_time.isoformat()
            else:
                triggered_at_iso = now.isoformat()
            
            record = {
                'execution_id': self.run_id,
                'scraper_name': self._get_scraper_name(),
                'workflow': self.opts.get('workflow', 'MANUAL'),
                'status': 'failed',
                'triggered_at': triggered_at_iso,  # ✅ FIXED: ISO string
                'completed_at': None,
                'duration_seconds': None,
                'source': source,
                'environment': environment,
                'triggered_by': triggered_by,
                'gcs_path': None,
                'data_summary': None,
                'error_type': error.__class__.__name__,
                'error_message': str(error)[:1000],  # Truncate very long errors
                'retry_count': self.download_retry_count,
                'recovery': self.opts.get('recovery', False),
                'run_id': self.run_id,
                'opts': {k: v for k, v in self.opts.items() 
                        if k not in ['password', 'api_key', 'token', 'proxyUrl']},
                'created_at': now.isoformat()      # ✅ FIXED: ISO string
            }
            
            insert_bigquery_rows('nba_orchestration.scraper_execution_log', [record])
            logger.info(f"✅ Orchestration logged failure from {source}: {error.__class__.__name__}")
            
        except Exception as e:
            # Don't fail the scraper if logging fails
            logger.error(f"Failed to log failed execution to orchestration: {e}")
            # Still capture in Sentry
            try:
                sentry_sdk.capture_exception(e)
            except:
                pass

    ##########################################################################
    # Enhanced Error Handling
    ##########################################################################
    def report_error(self, exc):
        """
        Hook to integrate Slack, Sentry, or email for error reporting.
        We'll send the exception to Sentry here.
        """
        import sentry_sdk
        sentry_sdk.capture_exception(exc)

    def _debug_save_data_on_error(self, exc):
        """
        Optionally save partial data or raw response if we hit an exception.
        Customize as needed to store to GCS, S3, or just local disk for debugging.
        """
        try:
            # Example: store raw response content (if any) to /tmp
            if self.raw_response is not None and self.raw_response.content:
                debug_html = f"/tmp/debug_raw_{self.run_id}.html"
                with open(debug_html, "wb") as f:
                    f.write(self.raw_response.content)
                logger.info("Saved raw HTML to %s for debugging", debug_html)

            # If we had decoded JSON or HTML text in self.decoded_data:
            if self.decoded_data:
                debug_json = f"/tmp/debug_decoded_{self.run_id}.json"
                # If it's a string (HTML), just wrap in a dict so we can json.dump
                if isinstance(self.decoded_data, str):
                    out_data = {"html": self.decoded_data}
                else:
                    out_data = self.decoded_data

                with open(debug_json, "w", encoding="utf-8") as f:
                    json.dump(out_data, f, indent=2, ensure_ascii=False)
                logger.info("Saved partial decoded data to %s for debugging", debug_json)

        except Exception as save_ex:
            logger.warning("Failed to save debug data on error: %s", save_ex)

    ##########################################################################
    # Step Logging (SCRAPER_STEP) for Structured Logs
    ##########################################################################
    def step_info(self, step_name, message, extra=None):
        """
        Logs a structured "SCRAPER_STEP {message}" line with run_id & step name.
        Helps parse logs by step or correlate across runs.
        """
        if extra is None:
            extra = {}
        extra.update({
            "run_id": self.run_id,
            "step": step_name,
        })
        logger.info(f"SCRAPER_STEP {message}", extra=extra)

    ##########################################################################
    # Option & Exporter Group Management
    ##########################################################################
    def set_opts(self, opts):
        self.opts = opts
        self.proxy_url = opts.get("proxyUrl") or os.getenv("NBA_SCRAPER_PROXY")

        # ── NEW: allow caller to lock the run_id up‑front ───────────────────
        if opts.get("run_id"):
            self.run_id = str(opts["run_id"])

        self.opts["run_id"] = self.run_id 

    def validate_opts(self):
        """
        Ensure all required_opts are present. 
        Raise if missing.
        """
        for required_opt in self.required_opts:
            if required_opt not in self.opts:
                error_msg = f"Missing required option [{required_opt}]."
                
                try:
                    notify_error(
                        title=f"Scraper Configuration Error: {self.__class__.__name__}",
                        message=f"Missing required option: {required_opt}",
                        details={
                            'scraper': self.__class__.__name__,
                            'run_id': self.run_id,
                            'missing_option': required_opt,
                            'required_opts': self.required_opts,
                            'provided_opts': list(self.opts.keys())
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                raise DownloadDataException(error_msg)

    def set_exporter_group_to_opts(self):
        """
        If opts doesn't contain 'group', set default:
          'dev' if local, else 'prod'.
        """
        if "group" not in self.opts:
            self.opts["group"] = "dev" if is_local() else "prod"

    def set_additional_opts(self):
        """
        Add standard variables needed for GCS export paths.
        Child scrapers override this and call super().set_additional_opts() first.
        """
        # Add UTC timestamp for unique filenames
        if "timestamp" not in self.opts:
            self.opts["timestamp"] = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        # Add Eastern date if not provided as parameter
        if "date" not in self.opts:
            # Derive from existing parameters first
            if "gamedate" in self.opts:
                gamedate = self.opts["gamedate"]
                if len(gamedate) == 8 and gamedate.isdigit():
                    # Convert YYYYMMDD to YYYY-MM-DD for consistent paths
                    self.opts["date"] = f"{gamedate[:4]}-{gamedate[4:6]}-{gamedate[6:8]}"
                else:
                    self.opts["date"] = gamedate  # Already has dashes
            elif "game_date" in self.opts:
                game_date = self.opts["game_date"]
                if len(game_date) == 8 and game_date.isdigit():
                    # Convert YYYYMMDD to YYYY-MM-DD for consistent paths
                    self.opts["date"] = f"{game_date[:4]}-{game_date[4:6]}-{game_date[6:8]}"
                else:
                    self.opts["date"] = game_date  # Already has dashes
            else:
                # Use current Eastern date
                try:
                    import pytz
                    eastern = pytz.timezone('US/Eastern')
                    eastern_now = datetime.now(eastern)
                    self.opts["date"] = eastern_now.strftime("%Y-%m-%d")
                except Exception:
                    # Fallback to UTC date if timezone fails
                    self.opts["date"] = datetime.utcnow().strftime("%Y-%m-%d")

        logger.debug("Added standard path variables: timestamp=%s, date=%s", 
                self.opts.get("timestamp"), self.opts.get("date"))

    def validate_additional_opts(self):
        """
        Hook: child scrapers can validate newly-added opts. 
        By default, we ensure 'group' is present.
        """
        if "group" not in self.opts:
            raise DownloadDataException("Missing 'group' after set_exporter_group_to_opts.")

    ##########################################################################
    # URL & Headers Setup
    ##########################################################################
    def set_url(self):
        """
        Child classes override. E.g. self.url = f"https://x.com?date={self.opts['date']}"
        """
        pass

    def set_headers(self):
        """
        Provide sensible defaults or map well‑known header profiles to helpers.
        Added support for ``header_profile = "espn"`` (UA only).
        """
        profile_map = {
            "stats": stats_nba_headers,
            "data":  data_nba_headers,
            "core":  core_api_headers,
            "espn":  lambda: {"User-Agent": _ua()},
            "nbacdn": cdn_nba_headers,
            "statsapi": stats_api_headers,
            "bettingpros": bettingpros_headers,
        }
        if self.header_profile in profile_map:
            fn = profile_map[self.header_profile]
            self.headers = fn() if callable(fn) else fn
        else:
            self.headers = {"User-Agent": _ua()}

    ##########################################################################
    # Download & Decode (Enhanced with Sentry + Notifications)
    ##########################################################################
    def download_and_decode(self):
        """
        Download with loop-based retry (avoids recursive stack growth).
        Enhanced with Sentry span tracking and "no data success" support.
        """
        with sentry_sdk.start_span(op="http.request", description="Scraper API call") as span:
            span.set_tag("http.url", getattr(self, 'url', 'unknown'))
            span.set_tag("scraper.retry_count", self.download_retry_count)
            
            try:
                # Wrap the retry loop to catch max retries exception
                try:
                    while True:
                        try:
                            self.set_http_downloader()
                            self.start_download()
                            self.check_download_status()
                            if self.decode_download_data:
                                self.decode_download_content()
                            break  # success
                            
                        except (
                            ValueError,
                            InvalidRegionDecodeException,
                            NoHttpStatusCodeException,
                            RetryInvalidHttpStatusCodeException,
                            ReadTimeout,
                        ) as err:
                            self.increment_retry_count()
                            self.sleep_before_retry()
                            logger.warning("[Retry %s] after %s: %s", self.download_retry_count, type(err).__name__, err)

                        except InvalidHttpStatusCodeException as e:
                            # Send notification for invalid HTTP status
                            try:
                                notify_error(
                                    title=f"Scraper HTTP Error: {self.__class__.__name__}",
                                    message=f"Invalid HTTP status code: {getattr(self.raw_response, 'status_code', 'unknown')}",
                                    details={
                                        'scraper': self.__class__.__name__,
                                        'run_id': self.run_id,
                                        'url': getattr(self, 'url', 'unknown'),
                                        'status_code': getattr(self.raw_response, 'status_code', 'unknown'),
                                        'retry_count': self.download_retry_count,
                                        'error': str(e)
                                    },
                                    processor_name=self.__class__.__name__
                                )
                            except Exception as notify_ex:
                                logger.warning(f"Failed to send notification: {notify_ex}")
                            raise

                except DownloadDecodeMaxRetryException as e:
                    # SIMPLE FIX: If scraper has the property, treat as success
                    if hasattr(self, 'treat_max_retries_as_success') and getattr(self, 'treat_max_retries_as_success', []):
                        logger.info("✅ Treating max retries as 'no data available' success")
                        
                        # Set up successful "no data" response
                        self.data = []
                        self.decoded_data = []
                        
                        # ADD THIS FLAG to skip validation:
                        self._no_data_success = True
                        
                        # Enhanced Sentry tracking for "no data" success
                        span.set_tag("http.status_code", 403)
                        span.set_tag("scraper.result", "no_data_available")
                        span.set_data("response.size", 0)
                        
                        return  # Success exit with no data
                    else:
                        # Send notification for max retry failure
                        try:
                            notify_error(
                                title=f"Scraper Max Retries Failed: {self.__class__.__name__}",
                                message=f"Reached maximum retry attempts ({self.max_retries_decode})",
                                details={
                                    'scraper': self.__class__.__name__,
                                    'run_id': self.run_id,
                                    'url': getattr(self, 'url', 'unknown'),
                                    'retry_count': self.download_retry_count,
                                    'max_retries': self.max_retries_decode,
                                    'last_error': str(e)
                                },
                                processor_name=self.__class__.__name__
                            )
                        except Exception as notify_ex:
                            logger.warning(f"Failed to send notification: {notify_ex}")
                        # Re-raise for normal max retry failures
                        raise

                # Track successful request
                span.set_tag("http.status_code", self.raw_response.status_code)
                span.set_tag("scraper.result", "data_found")
                span.set_data("response.size", len(self.raw_response.content))
                
            except Exception as e:
                # Track failed requests
                span.set_tag("http.status_code", getattr(self.raw_response, 'status_code', 'unknown'))
                span.set_tag("error.type", type(e).__name__)
                
                # Add result classification for better monitoring
                if isinstance(e, DownloadDecodeMaxRetryException):
                    span.set_tag("scraper.result", "max_retries_failed")
                else:
                    span.set_tag("scraper.result", "error")
                
                raise

    def set_http_downloader(self):
        """
        Create a requests.Session with a custom retry strategy & adapter.
        """
        self.http_downloader = requests.Session()
        # If a single proxy_url was supplied, use it for all schemes
        if self.proxy_url:
            self.http_downloader.proxies.update({"http": self.proxy_url, "https": self.proxy_url})

        retry_strategy = self.get_retry_strategy()
        adapter = self.get_http_adapter(retry_strategy)
        self.http_downloader.mount("https://", adapter)
        self.http_downloader.mount("http://", adapter)

    def get_retry_strategy(self):
        """
        Return a configured urllib3.util.retry.Retry object for HTTP retries.
        """
        return Retry(
            total=self.max_retries_http,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            backoff_factor=3
        )

    def get_http_adapter(self, retry_strategy):
        """
        Return an HTTPAdapter with the given retry_strategy.
        """
        return HTTPAdapter(max_retries=retry_strategy)

    def start_download(self):
        """
        Enhanced download path chooser with GCS support:
          • gcs_enabled      → Read from GCS bucket
          • browser_enabled  → Playwright cookie harvest + requests
          • proxy_enabled    → rotate proxies
          • otherwise        → plain requests
        """
        if self.gcs_enabled:
            self.download_from_gcs()
        elif self.browser_enabled:
            self.download_via_browser()
        elif self.proxy_enabled:
            self.download_data_with_proxy()
        else:
            self.download_data()

    def download_from_gcs(self) -> None:
        """
        GCS download path - reads file from GCS bucket instead of HTTP.
        Creates a mock response that works with existing decode logic.
        """
        try:
            # Lazy import to avoid dependency issues
            from google.cloud import storage
        except ImportError as e:
            try:
                notify_error(
                    title=f"Scraper Dependency Missing: {self.__class__.__name__}",
                    message="google-cloud-storage library not available",
                    details={
                        'scraper': self.__class__.__name__,
                        'run_id': self.run_id,
                        'missing_dependency': 'google-cloud-storage',
                        'install_command': 'pip install google-cloud-storage'
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException("google-cloud-storage not available - install with pip install google-cloud-storage") from e
        
        self.step_info("gcs_download", "Reading from GCS bucket", 
                       extra={"bucket": self.gcs_bucket, "path": self.gcs_path})
        
        try:
            # Initialize GCS client
            client = storage.Client()
            bucket = client.bucket(self.gcs_bucket)
            
            # Find the blob (either exact path or search pattern)
            blob = self._find_gcs_blob(bucket, self.gcs_path)
            if not blob:
                try:
                    notify_error(
                        title=f"Scraper GCS File Not Found: {self.__class__.__name__}",
                        message=f"File not found in GCS bucket",
                        details={
                            'scraper': self.__class__.__name__,
                            'run_id': self.run_id,
                            'bucket': self.gcs_bucket,
                            'path': self.gcs_path,
                            'action': 'Check if file exists and path is correct'
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(f"File not found in GCS: {self.gcs_bucket}/{self.gcs_path}")
            
            # Download content
            content = blob.download_as_bytes()
            self.step_info("gcs_download", "Successfully read from GCS", 
                          extra={"blob_name": blob.name, "size_bytes": len(content)})
            
            # Create mock response object that works with existing decode logic
            class MockResponse:
                def __init__(self, content, download_type):
                    self.content = content
                    self.status_code = 200
                    self.text = content.decode('utf-8', errors='ignore') if download_type == DownloadType.HTML else "Binary content from GCS"
                    
            self.raw_response = MockResponse(content, self.download_type)
            
        except Exception as e:
            if not isinstance(e, DownloadDataException):
                try:
                    notify_error(
                        title=f"Scraper GCS Download Failed: {self.__class__.__name__}",
                        message=f"Failed to download from GCS: {str(e)}",
                        details={
                            'scraper': self.__class__.__name__,
                            'run_id': self.run_id,
                            'bucket': self.gcs_bucket,
                            'path': self.gcs_path,
                            'error_type': type(e).__name__,
                            'error': str(e)
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException(f"GCS download failed: {e}") from e
        
    def _find_gcs_blob(self, bucket, path_pattern):
        """
        Find GCS blob - supports exact paths or pattern matching.
        Subclasses can override for custom blob finding logic.
        """
        # Try exact path first
        blob = bucket.blob(path_pattern)
        if blob.exists():
            return blob
        
        # Try pattern matching (for cases like finding latest timestamp)
        if '*' in path_pattern or '{' in path_pattern:
            # This is a pattern, list blobs and find match
            prefix = path_pattern.split('*')[0].split('{')[0]  # Get prefix before wildcards
            blobs = bucket.list_blobs(prefix=prefix)
            
            for blob in blobs:
                if self._blob_matches_pattern(blob.name, path_pattern):
                    return blob
        
        return None
    
    def _blob_matches_pattern(self, blob_name, pattern):
        """
        Basic pattern matching for GCS blobs.
        Subclasses can override for more sophisticated matching.
        """
        # Simple wildcard support
        if '*' in pattern:
            import fnmatch
            return fnmatch.fnmatch(blob_name, pattern)
        
        # Simple substring match
        return pattern in blob_name

    def download_via_browser(self) -> None:
        """
        Headless Playwright path used *only* when a scraper sets
        ``browser_enabled = True``.  We visit one page (``browser_url`` or
        ``self.url``), let Akamai set cookies, copy those cookies into the
        current ``requests.Session`` and immediately fall back to the normal
        requests-based download.  No UI is ever shown.
        """
        if not _PLAYWRIGHT_AVAILABLE:
            try:
                notify_error(
                    title=f"Scraper Dependency Missing: {self.__class__.__name__}",
                    message="Playwright package not installed",
                    details={
                        'scraper': self.__class__.__name__,
                        'run_id': self.run_id,
                        'missing_dependency': 'playwright',
                        'install_command': 'pip install playwright && playwright install chromium'
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException("Playwright package not installed")

        harvest_url = self.browser_url or self.url
        self.step_info("browser", "Headless cookie harvest",
                       extra={"harvest_url": harvest_url})

        # ------------------------------------------------------- launch
        launch_args = ["--disable-blink-features=AutomationControlled"]

        pw_proxy = None
        if self.proxy_url:
            parsed = urllib.parse.urlparse(self.proxy_url)
            pw_proxy = {
                "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                "username": parsed.username,
                "password": parsed.password,
            }

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=launch_args,
                                        proxy=pw_proxy)
            page = browser.new_page()
            if _STEALTH_AVAILABLE:
                _STEALTH_FN(page)

            # ── single hop ───────────────────────────────────────────
            page.route("**/*.{png,jpg,jpeg,gif,svg,woff,css}", lambda r: r.abort())
            page.goto(harvest_url, wait_until="networkidle", timeout=90_000)

            # OneTrust → Accept cookies if shown (non-blocking)
            try:
                btn = page.locator("button#onetrust-accept-btn-handler")
                if btn.is_visible(timeout=3_000):
                    btn.click()
            except Exception:
                pass

            # short pause so Akamai JS can finish
            page.wait_for_timeout(1_500)

            cookie_map = {c["name"]: c["value"] for c in page.context.cookies()}
            browser.close()

        # sanity
        if not cookie_map:
            try:
                notify_warning(
                    title=f"Scraper Browser Warning: {self.__class__.__name__}",
                    message="Playwright did not return any cookies",
                    details={
                        'scraper': self.__class__.__name__,
                        'run_id': self.run_id,
                        'harvest_url': harvest_url,
                        'warning': 'No cookies harvested from browser'
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException("Playwright did not return any cookies")

        # inject into requests.Session
        for name, val in cookie_map.items():
            self.http_downloader.cookies.set(name, val, domain=".nba.com")

        self.step_info("browser", "Cookie harvest complete",
                       extra={"cookies": list(cookie_map)[:5]})

        # -------------------- proceed with *normal* requests path -----------
        self.raw_response = self.http_downloader.get(
            self.url,
            timeout=self.timeout_http,
            **self._common_requests_kwargs(),
        )

    def get_requests_kwargs(self) -> dict:
        """Child scrapers override to inject extra requests.get kwargs."""
        return {}

    def _common_requests_kwargs(self) -> dict:
        kw = {"headers": self.headers, **self.get_requests_kwargs()}
        if self.proxy_url:
            kw["proxies"] = {"https": self.proxy_url, "http": self.proxy_url}
        return kw
    
    def download_data(self):
        """Direct (non-proxy) download."""
        self.step_info("download", "Starting download (no proxy)", extra={"url": self.url})
        logger.debug("Effective headers: %s", self.headers)
        self.raw_response = self.http_downloader.get(
            self.url,
            timeout=self.timeout_http,
            **self._common_requests_kwargs(),
        )

    def download_data_with_proxy(self):
        """
        Shuffle or iterate proxies from get_proxy_urls(),
        attempt each until success or exhausted.
        """
        proxy_pool = get_proxy_urls()
        if not self.test_proxies:
            random.shuffle(proxy_pool)

        self.mark_time("proxy")
        proxy_errors = []
        
        for proxy in proxy_pool:
            try:
                self.step_info("download_proxy", f"Attempting proxy {proxy}")
                self.raw_response = self.http_downloader.get(
                    self.url,
                    proxies={"https": proxy},
                    timeout=self.timeout_http,
                    **self._common_requests_kwargs(),
                )
                elapsed = self.mark_time("proxy")

                if self.raw_response.status_code == 200 and not self.test_proxies:
                    logger.info("Proxy success: %s, took=%ss", proxy, elapsed)
                    break
                else:
                    logger.warning("Proxy failed: %s, status=%s, took=%ss",
                                   proxy, self.raw_response.status_code, elapsed)
                    proxy_errors.append({'proxy': proxy, 'status': self.raw_response.status_code})

            except (ProxyError, ConnectTimeout, ConnectionError) as ex:
                elapsed = self.mark_time("proxy")
                logger.warning("Proxy error with %s, %s, took=%ss",
                               proxy, type(ex).__name__, elapsed)
                proxy_errors.append({'proxy': proxy, 'error': type(ex).__name__})
        
        # If all proxies failed, send notification
        if proxy_errors and len(proxy_errors) == len(proxy_pool):
            try:
                notify_warning(
                    title=f"Scraper Proxy Exhaustion: {self.__class__.__name__}",
                    message=f"All {len(proxy_pool)} proxies failed",
                    details={
                        'scraper': self.__class__.__name__,
                        'run_id': self.run_id,
                        'url': getattr(self, 'url', 'unknown'),
                        'proxy_count': len(proxy_pool),
                        'failures': proxy_errors
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

    def check_download_status(self):
        """
        Ensure we got a valid status_code == 200, else raise an exception 
        to trigger retry or error out.
        """
        if not hasattr(self.raw_response, "status_code"):
            raise NoHttpStatusCodeException("No status_code on download response.")

        if self.raw_response.status_code != 200:
            if self.should_retry_on_http_status_code(self.raw_response.status_code):
                raise RetryInvalidHttpStatusCodeException(
                    f"Invalid HTTP status code (retry): {self.raw_response.status_code}"
                )
            else:
                raise InvalidHttpStatusCodeException(
                    f"Invalid HTTP status code (no retry): {self.raw_response.status_code}"
                )

    def decode_download_content(self):
        """
        If we're expecting JSON, parse self.raw_response.content as JSON.
        If DownloadType.HTML, store text in self.decoded_data.
        If BINARY, do nothing special.
        """
        logger.debug("Decoding raw response as '%s'", self.download_type)
        if self.download_type == DownloadType.JSON:
            try:
                self.decoded_data = json.loads(self.raw_response.content)
            except json.JSONDecodeError as ex:
                try:
                    notify_warning(
                        title=f"Scraper JSON Decode Failed: {self.__class__.__name__}",
                        message="Failed to parse JSON response",
                        details={
                            'scraper': self.__class__.__name__,
                            'run_id': self.run_id,
                            'url': getattr(self, 'url', 'unknown'),
                            'retry_count': self.download_retry_count,
                            'content_preview': self.raw_response.content[:200].decode('utf-8', errors='ignore')
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                # eligible for retry
                raise DownloadDataException(f"JSON decode failed: {ex}") from ex
        elif self.download_type == DownloadType.HTML:
            self.decoded_data = self.raw_response.text
        elif self.download_type == DownloadType.BINARY:
            # Still place the bytes in decoded_data so ExportMode.DECODED works
            self.decoded_data = self.raw_response.content
        else:
            pass

    def should_retry_on_http_status_code(self, status_code):
        """
        Return True unless status_code is in no_retry_status_codes (e.g. 404).
        """
        return status_code not in self.no_retry_status_codes

    ##########################################################################
    # Download/Decode Retry Helpers
    ##########################################################################
    def increment_retry_count(self):
        """
        Enhanced: Check for "no data" success cases before raising max retry exception.
        """
        if self.download_retry_count < self.max_retries_decode:
            self.download_retry_count += 1
        else:
            # BEFORE raising exception, check if this should be "no data" success
            if (hasattr(self, 'treat_max_retries_as_success') and
                hasattr(self, 'raw_response') and 
                self.raw_response and 
                self.raw_response.status_code in getattr(self, 'treat_max_retries_as_success', [])):
                
                logger.info("✅ Treating max retries (status %d) as 'no data available' success", 
                        self.raw_response.status_code)
                
                # Raise a special exception that the download loop can catch
                from .utils.exceptions import NoDataAvailableSuccess
                raise NoDataAvailableSuccess(
                    f"No data available (HTTP {self.raw_response.status_code}) - treating as success"
                )
            else:
                # Normal max retry behavior
                raise DownloadDecodeMaxRetryException(
                    f"Max decode/download retries reached: {self.max_retries_decode}"
                )

    def sleep_before_retry(self):
        """
        Exponential backoff. 4 * 2^(retry_count-1), capped at 15 seconds.
        """
        backoff_factor = 4
        backoff_max = 15
        sleep_seconds = min(backoff_factor * (2 ** (self.download_retry_count - 1)), backoff_max)
        logger.warning("Sleeping %.1f seconds before retry...", sleep_seconds)
        time.sleep(sleep_seconds)

    ##########################################################################
    # Validation & Transformation Hooks
    ##########################################################################
    def validate_download_data(self):
        """
        Enhanced to skip validation for "no data" success cases.
        Child classes override. E.g., check if 'scoreboard' in self.decoded_data, etc.
        """
        # NEW: Skip validation if this is a "no data" success case
        if hasattr(self, '_no_data_success') and self._no_data_success:
            logger.info("✅ Skipping validation for 'no data' success case")
            return
        
        # EXISTING validation logic:
        if not self.decoded_data:
            try:
                notify_warning(
                    title=f"Scraper Validation Warning: {self.__class__.__name__}",
                    message="Downloaded data is empty",
                    details={
                        'scraper': self.__class__.__name__,
                        'run_id': self.run_id,
                        'url': getattr(self, 'url', 'unknown'),
                        'decoded_data': str(self.decoded_data)[:200]
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException("Downloaded data is empty or None.")

    def extract_opts_from_data(self):
        """
        If we discover new context from decoded_data (like a seasonYear) 
        that becomes part of self.opts, child scrapers override here.
        """
        pass

    def validate_extracted_opts(self):
        """
        If we changed self.opts in extract_opts_from_data, we can do final checks here.
        """
        pass

    def transform_data(self):
        """
        Child classes override to slice or restructure self.decoded_data into self.data.
        E.g. self.data["some_key"] = ...
        """
        pass

    ##########################################################################
    # Export (Enhanced with Sentry + Notifications)
    ##########################################################################
    def should_save_data(self):
        """
        Return False to skip exporting under certain conditions. 
        Child scrapers can override if needed.
        """
        return True

    def export_data(self):
        """
        Evaluate each exporter config in self.exporters.
        Enhanced with Sentry span tracking and notifications.
        """
        with sentry_sdk.start_span(op="data.export", description="Export scraper data") as span:
            span.set_tag("export.group", self.opts.get("group", "unknown"))
            span.set_data("export.data_size", len(str(self.data)))
            
            try:
                # Track whether we actually used any exporter
                ran_exporter = False

                for config in self.exporters:
                    groups = config.get("groups", [])
                    if self.opts["group"] not in groups:
                        # group mismatch => skip
                        continue

                    if config.get("check_should_save"):
                        if not self.should_save_data():
                            logger.info("Skipping export for config %s (should_save_data=False)", config)
                            continue

                    # read export_mode, default ExportMode.DATA if missing
                    export_mode = config.get("export_mode", ExportMode.DATA)
                    if isinstance(export_mode, str):
                        export_mode = ExportMode(export_mode)  # convert from string if needed

                    if export_mode == ExportMode.RAW:
                        data_to_export = self.raw_response.content
                    elif export_mode == ExportMode.DECODED:
                        data_to_export = self.decoded_data
                    else:  # ExportMode.DATA
                        data_key = config.get("data_key")
                        if data_key:
                            data_to_export = self.data.get(data_key, {})
                        else:
                            data_to_export = self.data

                    exporter_type = config["type"]
                    exporter_cls = EXPORTER_REGISTRY.get(exporter_type)
                    if not exporter_cls:
                        raise DownloadDataException(f"Exporter type not found: {exporter_type}")

                    self.step_info("export", f"Exporting with {exporter_type}",
                                extra={"export_mode": str(export_mode), "config": config})
                    exporter = exporter_cls()
                    exporter_result = exporter.run(data_to_export, config, self.opts)
                    
                    # ✅ NEW: Capture GCS output path if exporter returned it
                    if isinstance(exporter_result, dict) and 'gcs_path' in exporter_result:
                        self.opts['gcs_output_path'] = exporter_result['gcs_path']

                    # Mark that at least one exporter was triggered
                    ran_exporter = True

                # If we never ran an exporter, log a warning
                if not ran_exporter:
                    logger.warning(
                        "No exporters matched group=%r. No data was exported.",
                        self.opts.get("group")
                    )
                
                span.set_tag("export.status", "success")
                span.set_data("export.count", len([c for c in self.exporters if self.opts["group"] in c.get("groups", [])]))
                
            except Exception as e:
                span.set_tag("export.status", "error")
                span.set_tag("error.type", type(e).__name__)
                
                # Send notification for export failure
                try:
                    notify_error(
                        title=f"Scraper Export Failed: {self.__class__.__name__}",
                        message=f"Failed to export data: {str(e)}",
                        details={
                            'scraper': self.__class__.__name__,
                            'run_id': self.run_id,
                            'export_group': self.opts.get('group'),
                            'exporters_count': len(self.exporters),
                            'error_type': type(e).__name__,
                            'error': str(e)
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                raise

    def post_export(self):
        """
        Called after exporting. By default logs final stats + run_id as SCRAPER_STATS.
        Child scrapers can override or add fields by returning a dict in get_scraper_stats().
        """
        summary = {
            "run_id": self.run_id,
            "scraper": self.__class__.__name__,
            "function": os.getenv("K_SERVICE", "unknown"),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "total_runtime": self.stats.get("total_runtime", 0),
        }

        # Merge child stats
        child_stats = self.get_scraper_stats()
        if isinstance(child_stats, dict):
            summary.update(child_stats)

        logger.info("SCRAPER_STATS %s", json.dumps(summary))

    def get_return_value(self):
        """
        By default, if decode_download_data is True, we return self.decoded_data 
        (if it exists), else True. Child classes can override for custom returns.
        """
        return self.decoded_data if self.decoded_data else True

    def get_scraper_stats(self):
        """
        Child scrapers override to provide additional fields in the final SCRAPER_STATS log line.
        E.g., {"records_found": 123, "gamedate": "2023-01-01"}.
        """
        return {}

    ##########################################################################
    # Time Measurement Helpers
    ##########################################################################
    def mark_time(self, label):
        """
        If label is new, store 'start'=now, 'last'=now, return "0.0" sec.
        If label exists, measure time delta from last_time to now,
        update 'last'=now, return string e.g. "3.4" sec.
        """
        now = datetime.now()
        if label not in self.time_markers:
            self.time_markers[label] = {
                "start": now,
                "last": now
            }
            return "0.0"
        else:
            last_time = self.time_markers[label]["last"]
            delta = (now - last_time).total_seconds()
            self.time_markers[label]["last"] = now
            return f"{delta:.1f}"

    def get_elapsed_seconds(self, label):
        """
        Return total seconds from when we first called mark_time(label) 
        to 'now'.
        """
        if label not in self.time_markers:
            return 0.0
        start_time = self.time_markers[label]["start"]
        now_time = datetime.now()
        return (now_time - start_time).total_seconds()
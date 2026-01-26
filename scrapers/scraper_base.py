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

import logging
import os
import sentry_sdk
from .utils.env_utils import is_local

# Initialize logger for this module
logger = logging.getLogger(__name__)

# Initialize Sentry with environment-specific configuration
ENV = "development" if is_local() else "production"
sentry_dsn = os.getenv("SENTRY_DSN", "")

if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        environment=ENV,
        traces_sample_rate=1.0 if ENV == "development" else 0.1,
        profiles_sample_rate=1.0 if ENV == "development" else 0.01,
        send_default_pii=False,
    )
    logger.info(f"Sentry initialized for {ENV} environment")
else:
    logger.info("Sentry DSN not configured - error monitoring disabled")

import enum
from typing import Callable, Dict, Any, Optional, List
import requests
from shared.clients.http_pool import get_http_session

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

import urllib.parse
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
from .utils.proxy_utils import (
    get_proxy_urls,
    get_proxy_urls_with_circuit_breaker,
    ProxyCircuitBreaker,
    extract_provider_from_url,
    get_healthy_proxy_urls_for_target,
    record_proxy_success,
    record_proxy_failure,
    get_proxy_health_summary,
)
from shared.utils.proxy_health_logger import log_proxy_result, extract_host_from_url, classify_error
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

# Import sport configuration for multi-sport support
from shared.config.sport_config import (
    get_orchestration_dataset,
    get_project_id,
    get_current_sport,
)

# Import pipeline logger for event tracking and auto-retry queue (Jan 2026 resilience)
try:
    from shared.utils.pipeline_logger import (
        log_processor_start,
        log_processor_complete,
        log_processor_error,
        mark_retry_succeeded,
        classify_error as classify_error_for_retry
    )
    _PIPELINE_LOGGER_AVAILABLE = True
except ImportError:
    _PIPELINE_LOGGER_AVAILABLE = False
    log_processor_start = None
    log_processor_complete = None
    log_processor_error = None
    mark_retry_succeeded = None
    classify_error_for_retry = None
    logger.warning("Could not import pipeline_logger - auto-retry queue disabled")

# Import mixins for composable functionality
from .mixins import (
    CostTrackingMixin,
    ExecutionLoggingMixin,
    ValidationMixin,
    HttpHandlerMixin,
    EventPublisherMixin,
    ConfigMixin
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


class ScraperBase(CostTrackingMixin, ExecutionLoggingMixin, ValidationMixin, HttpHandlerMixin, EventPublisherMixin, ConfigMixin):
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

        # Cost tracking integration
        self._cost_tracker = None
        self._bytes_downloaded = 0
        self._bytes_exported = 0

        # Rate limiter instance (lazily initialized)
        self._rate_limiter = None

    ##########################################################################
    # Main Entrypoint for the Lifecycle (Enhanced with Sentry + Notifications)
    ##########################################################################
    def run(self, opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Enhanced run method with comprehensive Sentry tracking, error handling,
        multi-channel notifications, and Phase 1 orchestration logging.

        Args:
            opts: Configuration options for the scraper run

        Returns:
            Dictionary containing run statistics and status
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

                # Initialize cost tracking
                self._init_cost_tracking()

                # Log processor start event for pipeline tracking (Jan 2026 resilience)
                self._pipeline_event_id = None
                if _PIPELINE_LOGGER_AVAILABLE and log_processor_start:
                    try:
                        game_date = opts.get('date') or opts.get('gamedate', '')
                        if game_date and len(game_date) == 8:  # YYYYMMDD format
                            game_date = f"{game_date[:4]}-{game_date[4:6]}-{game_date[6:8]}"
                        self._pipeline_event_id = log_processor_start(
                            phase='phase_2',
                            processor_name=self._get_scraper_name(),
                            game_date=game_date if game_date else None,
                            correlation_id=self.run_id,
                            trigger_source=opts.get('triggered_by', 'scheduled')
                        )
                    except Exception as e:
                        logger.debug(f"Pipeline start logging failed (non-critical): {e}")

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

                # ✅ LAYER 1: Validate scraper output (detects gaps at source)
                self._validate_scraper_output()

                # ✅ Phase 1→2 Boundary Validation (lightweight sanity checks)
                self._validate_phase1_boundary()

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

                # Log processor completion event for pipeline tracking (Jan 2026 resilience)
                if _PIPELINE_LOGGER_AVAILABLE and log_processor_complete:
                    try:
                        game_date = self._extract_game_date()
                        log_processor_complete(
                            phase='phase_2',
                            processor_name=self._get_scraper_name(),
                            game_date=game_date if game_date else None,
                            duration_seconds=self.stats.get('total_runtime', 0),
                            records_processed=self.get_scraper_stats().get('rowCount', 0),
                            correlation_id=self.run_id,
                            parent_event_id=getattr(self, '_pipeline_event_id', None)
                        )
                        # Clear any pending retry entries for this processor/date
                        if mark_retry_succeeded and game_date:
                            mark_retry_succeeded(
                                phase='phase_2',
                                processor_name=self._get_scraper_name(),
                                game_date=game_date
                            )
                    except Exception as e:
                        logger.debug(f"Pipeline complete logging failed (non-critical): {e}")

                # ✅ NEW: Finalize and save cost tracking metrics
                self._finalize_cost_tracking(success=True)

                # ✅ NEW: Publish Pub/Sub event for Phase 2 processors
                # (unless skip_pubsub flag is set for batch processing)
                if not self.opts.get('skip_pubsub', False):
                    self._publish_completion_event_to_pubsub()
                else:
                    logger.info("Skipping Pub/Sub publish (skip_pubsub=True, batch mode)")

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

                # ✅ NEW: Log failure for automatic backfill recovery
                try:
                    self._log_scraper_failure_for_backfill(e)
                except Exception as backfill_log_ex:
                    logger.warning(f"Failed to log failure for backfill: {backfill_log_ex}")

                # ✅ NEW (Jan 2026): Log to pipeline_event_log and queue for auto-retry
                if _PIPELINE_LOGGER_AVAILABLE and log_processor_error:
                    try:
                        game_date = self._extract_game_date()
                        # Classify error as transient (network, rate limit) or permanent (code bug)
                        error_type = classify_error_for_retry(e) if classify_error_for_retry else 'transient'
                        log_processor_error(
                            phase='phase_2',
                            processor_name=self._get_scraper_name(),
                            game_date=game_date if game_date else None,
                            error_message=str(e)[:1000],
                            error_type=error_type,
                            stack_trace=traceback.format_exc()[:4000],
                            correlation_id=self.run_id,
                            parent_event_id=getattr(self, '_pipeline_event_id', None),
                            metadata={
                                'url': getattr(self, 'url', 'unknown'),
                                'retry_count': self.download_retry_count,
                                'step': self._get_current_step()
                            }
                        )
                        # Note: log_processor_error automatically queues transient errors for retry
                    except Exception as pipeline_log_ex:
                        logger.warning(f"Pipeline error logging failed (non-critical): {pipeline_log_ex}")

                # ✅ NEW: Publish failed event to Pub/Sub
                try:
                    self._publish_failed_event_to_pubsub(e)
                except Exception as pub_ex:
                    logger.warning(f"Failed to publish failed event: {pub_ex}")

                # ✅ NEW: Finalize and save cost tracking metrics (for failures)
                try:
                    self._finalize_cost_tracking(success=False, error=e)
                except Exception as cost_ex:
                    logger.warning(f"Failed to save cost tracking metrics: {cost_ex}")

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
        logger.info("SCRAPER_STEP %s: %s", step_name, json.dumps(extra))

    ##########################################################################
    # Export & Post-Processing
    ##########################################################################
    def export_data(self):
        """
        Export transformed data using configured exporters.

        Iterates through self.exporters and executes each one that matches
        the current group setting. Exporters can write to GCS, BigQuery,
        or other destinations.

        Each exporter config should specify:
        - groups: List of groups to run for (e.g., ['dev', 'prod'])
        - exporter_class: The exporter class to use (e.g., GCSExporter)
        - path_template: GCS path with placeholders for opts
        - export_mode: What to export (DATA, RAW_RESPONSE, BOTH)

        Sends notifications on export failures for monitoring.
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

                    # ✅ Capture GCS output path if exporter returned it
                    # Only capture the FIRST gcs_path (primary data exporter)
                    # Secondary exporters (metadata, etc.) should not overwrite
                    if isinstance(exporter_result, dict) and 'gcs_path' in exporter_result:
                        if 'gcs_output_path' not in self.opts:
                            self.opts['gcs_output_path'] = exporter_result['gcs_path']
                            logger.info(f"Captured gcs_output_path: {self.opts['gcs_output_path']}")
                        else:
                            logger.debug(f"Skipping secondary gcs_path: {exporter_result['gcs_path']}")
                    else:
                        logger.debug(f"Exporter {exporter_type} returned: {type(exporter_result).__name__}")

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

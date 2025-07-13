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
      8) Log final stats & run ID.

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
    no_retry_status_codes: list[int] = [404]
    max_retries_decode = 8
    
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
    # Main Entrypoint for the Lifecycle (Enhanced with Sentry)
    ##########################################################################
    def run(self, opts=None):
        """
        Enhanced run method with comprehensive Sentry tracking and error handling.
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
        logger.info(f"SCRAPER_STEP {message}", extra=extra)

    ##########################################################################
    # Option & Exporter Group Management
    ##########################################################################
    def set_opts(self, opts):
        self.opts = opts
        self.proxy_url = opts.get("proxyUrl") or os.getenv("NBA_SCRAPER_PROXY")

        # ── NEW: allow caller to lock the run_id up‑front ───────────────────
        if opts.get("runId"):
            self.run_id = str(opts["runId"])

        self.opts["run_id"] = self.run_id 

    def validate_opts(self):
        """
        Ensure all required_opts are present. 
        Raise if missing.
        """
        for required_opt in self.required_opts:
            if required_opt not in self.opts:
                raise DownloadDataException(f"Missing required option [{required_opt}].")

    def set_exporter_group_to_opts(self):
        """
        If opts doesn't contain 'group', set default:
          'dev' if local, else 'prod'.
        """
        if "group" not in self.opts:
            self.opts["group"] = "dev" if is_local() else "prod"

    def set_additional_opts(self):
        """
        Hook: child scrapers that auto-derive e.g. 'season' from 'gamedate'
        can do so here. By default, does nothing.
        """
        pass

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
        }
        if self.header_profile in profile_map:
            fn = profile_map[self.header_profile]
            self.headers = fn() if callable(fn) else fn
        else:
            self.headers = {"User-Agent": _ua()}

    ##########################################################################
    # Download & Decode (Enhanced with Sentry)
    ##########################################################################
    def download_and_decode(self):
        """
        Download with loop‑based retry (avoids recursive stack growth).
        Enhanced with Sentry span tracking.
        """
        with sentry_sdk.start_span(op="http.request", description="Scraper API call") as span:
            span.set_tag("http.url", getattr(self, 'url', 'unknown'))
            span.set_tag("scraper.retry_count", self.download_retry_count)
            
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

                    except InvalidHttpStatusCodeException:
                        raise

                    # Failsafe: stop if we somehow fell out of the retry bucket
                    if self.download_retry_count >= self.max_retries_decode:
                        raise DownloadDecodeMaxRetryException(
                            f"Reached max retries ({self.max_retries_decode}) without success."
                        )

                # Track successful request
                span.set_tag("http.status_code", self.raw_response.status_code)
                span.set_data("response.size", len(self.raw_response.content))
                
            except Exception as e:
                # Track failed requests
                span.set_tag("http.status_code", getattr(self.raw_response, 'status_code', 'unknown'))
                span.set_tag("error.type", type(e).__name__)
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
        Choose download path:
          • browser_enabled  → Playwright cookie harvest + requests
          • proxy_enabled    → rotate proxies
          • otherwise        → plain requests
        """
        if self.browser_enabled:
            self.download_via_browser()
        elif self.proxy_enabled:
            self.download_data_with_proxy()
        else:
            self.download_data()

# ------------------------------------------------------------------ #
    # Playwright helper – runs **headless only** when browser_enabled == True
    # ------------------------------------------------------------------ #
    def download_via_browser(self) -> None:
        """
        Headless Playwright path used *only* when a scraper sets
        ``browser_enabled = True``.  We visit one page (``browser_url`` or
        ``self.url``), let Akamai set cookies, copy those cookies into the
        current ``requests.Session`` and immediately fall back to the normal
        requests-based download.  No UI is ever shown.
        """
        if not _PLAYWRIGHT_AVAILABLE:
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

    # ------------------------------------------------------------------ #
    # requests.get kwargs helpers
    # ------------------------------------------------------------------ #
    def get_requests_kwargs(self) -> dict:
        """Child scrapers override to inject extra requests.get kwargs."""
        return {}

    def _common_requests_kwargs(self) -> dict:  # noqa: D401 (private)
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

            except (ProxyError, ConnectTimeout, ConnectionError) as ex:
                elapsed = self.mark_time("proxy")
                logger.warning("Proxy error with %s, %s, took=%ss",
                               proxy, type(ex).__name__, elapsed)

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
        Increments self.download_retry_count; raise if we exceed max_retries_decode.
        """
        if self.download_retry_count < self.max_retries_decode:
            self.download_retry_count += 1
        else:
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
        Child classes override. 
        E.g., check if 'scoreboard' in self.decoded_data, etc.
        """
        if not self.decoded_data:
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
    # Export (Enhanced with Sentry)
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
        Enhanced with Sentry span tracking.
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
                    exporter.run(data_to_export, config, self.opts)

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
    
"""
http_handler_mixin.py

HttpHandlerMixin - Handles HTTP operations, downloads, retries, and proxies.

This mixin provides comprehensive HTTP downloading capabilities including:
 - Direct HTTP downloads with requests
 - Proxy-based downloads with health-based rotation and circuit breaker pattern
 - Browser-based downloads using Playwright for cookie harvesting
 - GCS (Google Cloud Storage) downloads as an alternative to HTTP
 - Retry strategies with exponential backoff
 - WAF/Cloudflare detection
 - Content decoding (JSON, HTML, binary)
 - Enhanced error handling and monitoring

The mixin supports multiple download paths:
 - GCS: Read from Google Cloud Storage bucket
 - Browser: Playwright cookie harvest + requests
 - Proxy: Rotate proxies with health tracking
 - Direct: Plain requests without proxy

Configuration is controlled via properties on the scraper class.
"""

import logging
import os
import json
import random
import urllib.parse
import sentry_sdk
from typing import Optional

import requests
from requests.exceptions import ProxyError, ConnectTimeout, ConnectionError, ReadTimeout
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from shared.clients.http_pool import get_http_session
from shared.utils.proxy_health_logger import log_proxy_result, extract_host_from_url, classify_error
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
)

from ..utils.exceptions import (
    DownloadDataException,
    DownloadDecodeMaxRetryException,
    NoHttpStatusCodeException,
    InvalidHttpStatusCodeException,
    RetryInvalidHttpStatusCodeException,
    InvalidRegionDecodeException
)
from ..utils.proxy_utils import (
    extract_provider_from_url,
    get_healthy_proxy_urls_for_target,
    record_proxy_success,
    record_proxy_failure,
    get_proxy_health_summary,
    ProxyCircuitBreaker,
)

# Note: DownloadType enum is expected to be available via the scraper class
# that uses this mixin. It's defined in scraper_base.py and accessed via self.download_type

# Initialize logger for this module
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Playwright availability checks
# --------------------------------------------------------------------------- #
try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ModuleNotFoundError:
    _PLAYWRIGHT_AVAILABLE = False

# ---- optional stealth plug‑in (v1.x or v2.x) ---------------------------
_STEALTH_FN = None
try:
    from playwright_stealth import stealth_sync as _STEALTH_FN  # ≤ v1.1
except ImportError:
    try:
        import playwright_stealth as _ps  # ≥ v2.0
        _STEALTH_FN = getattr(_ps, "stealth", None)
    except ImportError:
        _STEALTH_FN = None
_STEALTH_AVAILABLE = callable(_STEALTH_FN)


class HttpHandlerMixin:
    """
    Mixin providing HTTP download capabilities for scrapers.

    Handles all HTTP-related operations including:
    - HTTP session management with retry strategies
    - Multiple download paths (direct, proxy, browser, GCS)
    - Error handling and retry logic
    - Content decoding (JSON, HTML, binary)
    - WAF/Cloudflare detection
    - Proxy rotation with health tracking

    Expected properties on the scraper class:
    - url: Target URL to download
    - proxy_url: Optional proxy URL
    - gcs_enabled: Enable GCS download path
    - browser_enabled: Enable browser-based download
    - proxy_enabled: Enable proxy rotation
    - download_type: DownloadType enum (JSON, HTML, BINARY)
    - max_retries_http: Max HTTP-level retries
    - max_retries_decode: Max download/decode retries
    - timeout_http: HTTP timeout in seconds
    - headers: HTTP headers dict
    - download_retry_count: Current retry count
    - raw_response: Response object from requests
    - decoded_data: Decoded response content
    - data: Final data after validation
    - run_id: Unique run identifier
    """

    def download_and_decode(self):
        """
        Download data from self.url and decode the response.

        Implements a loop-based retry strategy with exponential backoff for
        transient failures. Automatically retries on network errors, rate
        limiting (429), and server errors (5xx).

        The method handles several scenarios:
        - Success: Sets self.raw_response and self.decoded_data
        - Max retries with treat_max_retries_as_success: Returns empty data
        - Max retries without success flag: Raises DownloadDecodeMaxRetryException

        Tracked with Sentry spans for performance monitoring.

        Raises:
            DownloadDecodeMaxRetryException: When max retries exceeded
            InvalidHttpStatusCodeException: For non-retryable HTTP errors
        """
        with sentry_sdk.start_span(op="http.request", description="Scraper API call") as span:
            span.set_tag("http.url", getattr(self, 'url', 'unknown'))
            span.set_tag("scraper.retry_count", self.download_retry_count)

            try:
                # Wrap the retry loop to catch max retries exception
                try:
                    # Safety guard: prevent infinite retry loops
                    max_loop_iterations = 100  # Should never need more than max_retries_decode
                    loop_iteration = 0
                    while True:
                        loop_iteration += 1
                        if loop_iteration > max_loop_iterations:
                            logger.warning(
                                f"download_and_decode exceeded {max_loop_iterations} iterations, breaking to prevent infinite loop"
                            )
                            raise DownloadDecodeMaxRetryException(
                                f"Loop guard triggered after {max_loop_iterations} iterations"
                            )
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
                        # Use get_no_data_response() so child scrapers can provide proper structure
                        no_data_response = self.get_no_data_response()
                        self.data = no_data_response
                        self.decoded_data = no_data_response

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
        self.http_downloader = get_http_session()
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

        Exponential backoff: {backoff_factor} * (2 ** (retry_number - 1))
        With backoff_factor=3 and max_retries=3:
          - 1st retry: 3s delay
          - 2nd retry: 6s delay
          - 3rd retry: 12s delay
        Max backoff capped at 60s to prevent excessive delays.

        Status codes that trigger retry:
          - 429: Too Many Requests (rate limiting)
          - 500: Internal Server Error
          - 502: Bad Gateway
          - 503: Service Unavailable
          - 504: Gateway Timeout

        Configuration:
          - SCRAPER_BACKOFF_FACTOR: Override default backoff factor (default: 3.0)
        """
        # Get backoff_factor from environment variable with default
        backoff_factor = float(os.getenv('SCRAPER_BACKOFF_FACTOR', '3.0'))

        return Retry(
            total=self.max_retries_http,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            backoff_factor=backoff_factor,
            backoff_max=60,  # Cap exponential backoff at 60 seconds
            respect_retry_after_header=True  # Honor Retry-After headers from APIs
        )

    def get_http_adapter(self, retry_strategy, pool_connections: int = 10, pool_maxsize: int = 20):
        """
        Return an HTTPAdapter with the given retry_strategy and connection pooling.

        Args:
            retry_strategy: urllib3 Retry object
            pool_connections: Number of connection pools to cache (default 10)
            pool_maxsize: Max connections per pool (default 20)

        Returns:
            HTTPAdapter configured with retries and connection pooling
        """
        return HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize
        )

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
                    # Check if download_type is HTML (supports both enum and string)
                    is_html = str(download_type).lower() in ('html', 'downloadtype.html')
                    self.text = content.decode('utf-8', errors='ignore') if is_html else "Binary content from GCS"

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
            try:
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
                except (TimeoutError, Exception) as e:
                    # TimeoutError: button not visible in time; other playwright errors
                    # This is optional UI interaction, safe to continue without it
                    logger.debug("Cookie consent button not clicked: %s", type(e).__name__)

                # short pause so Akamai JS can finish
                page.wait_for_timeout(1_500)

                cookie_map = {c["name"]: c["value"] for c in page.context.cookies()}
            finally:
                # Ensure browser is always closed to prevent resource leaks
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

    def _get_proxy_provider(self, proxy_url: str) -> str:
        """Extract proxy provider name from proxy URL for logging."""
        return extract_provider_from_url(proxy_url)

    def download_data_with_proxy(self):
        """
        Download data using proxies with intelligent health-based rotation.

        Implements:
        - Health-based proxy selection (preferring healthy proxies)
        - Per-proxy retry with exponential backoff for retryable errors
        - Cooldown periods for failing proxies
        - Circuit breaker pattern for persistent state across instances

        Uses:
        - ProxyManager for health-based rotation (in-memory health tracking)
        - Circuit breaker pattern for persistent state (BigQuery-backed)
        """
        import time as time_module

        # Extract target host for health tracking
        target_host = extract_host_from_url(self.url)

        # Initialize circuit breaker (uses BigQuery for persistent state)
        circuit_breaker = ProxyCircuitBreaker(use_bigquery=True)

        # Get proxy pool ordered by health and filtered by circuit breaker
        # This uses ProxyManager for health scoring + circuit breaker for persistent state
        proxy_pool = get_healthy_proxy_urls_for_target(
            target_host,
            circuit_breaker=circuit_breaker,
            shuffle=not self.test_proxies
        )

        # Log proxy health status at start
        health_status = get_proxy_health_summary()
        if health_status:
            logger.info(f"Proxy pool status: {health_status}")

        self.mark_time("proxy")
        proxy_errors = []

        # Retry configuration
        MAX_RETRIES_PER_PROXY = 3
        BASE_DELAY = 2.0  # seconds
        MAX_DELAY = 15.0  # seconds
        RETRYABLE_STATUS_CODES = {429, 503, 504}  # Rate limit, service unavailable, gateway timeout
        PERMANENT_FAILURE_CODES = {401, 403}  # Unauthorized, forbidden - don't retry

        for proxy in proxy_pool:
            provider = self._get_proxy_provider(proxy)
            proxy_success = False

            for attempt in range(MAX_RETRIES_PER_PROXY):
                try:
                    self.step_info("download_proxy", f"Attempting proxy {proxy} (attempt {attempt + 1})")
                    self.raw_response = self.http_downloader.get(
                        self.url,
                        proxies={"https": proxy},
                        timeout=self.timeout_http,
                        **self._common_requests_kwargs(),
                    )
                    elapsed = self.mark_time("proxy")

                    if self.raw_response.status_code == 200 and not self.test_proxies:
                        response_time_ms = int(float(elapsed) * 1000) if elapsed else None
                        logger.info("Proxy success: %s, took=%ss, attempt=%d", provider, elapsed, attempt + 1)

                        # Record success to health manager and circuit breaker
                        record_proxy_success(
                            proxy, target_host,
                            response_time_ms=response_time_ms,
                            circuit_breaker=circuit_breaker
                        )

                        # Also log to BigQuery for monitoring
                        log_proxy_result(
                            scraper_name=self.__class__.__name__,
                            target_host=target_host,
                            http_status_code=200,
                            response_time_ms=response_time_ms,
                            success=True,
                            proxy_provider=provider
                        )
                        proxy_success = True
                        break  # Success, exit retry loop

                    # Check if we should retry this proxy or move to next
                    status_code = self.raw_response.status_code

                    if status_code in PERMANENT_FAILURE_CODES:
                        # Permanent failure - don't retry this proxy
                        error_type = classify_error(status_code=status_code)
                        response_time_ms = int(float(elapsed) * 1000) if elapsed else None
                        logger.warning("Proxy permanent failure: %s, status=%s (not retrying)",
                                       provider, status_code)
                        proxy_errors.append({'proxy': provider, 'status': status_code, 'permanent': True})

                        # Record failure to health manager and circuit breaker
                        record_proxy_failure(
                            proxy, target_host,
                            error_type=error_type,
                            http_status_code=status_code,
                            circuit_breaker=circuit_breaker
                        )

                        # Also log to BigQuery for monitoring
                        log_proxy_result(
                            scraper_name=self.__class__.__name__,
                            target_host=target_host,
                            http_status_code=status_code,
                            response_time_ms=response_time_ms,
                            success=False,
                            error_type=error_type,
                            proxy_provider=provider
                        )
                        break  # Move to next proxy

                    elif status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES_PER_PROXY - 1:
                        # Retryable error - backoff and retry same proxy
                        delay = min(BASE_DELAY * (2 ** attempt) + random.uniform(0, 1), MAX_DELAY)
                        logger.warning("Proxy retryable error: %s, status=%s, retrying in %.1fs (attempt %d/%d)",
                                       provider, status_code, delay, attempt + 1, MAX_RETRIES_PER_PROXY)
                        time_module.sleep(delay)
                        continue  # Retry same proxy

                    else:
                        # Non-retryable or final attempt - move to next proxy
                        error_type = classify_error(status_code=status_code)
                        response_time_ms = int(float(elapsed) * 1000) if elapsed else None
                        logger.warning("Proxy failed: %s, status=%s, took=%ss",
                                       provider, status_code, elapsed)
                        proxy_errors.append({'proxy': provider, 'status': status_code})

                        # Record failure to health manager and circuit breaker
                        record_proxy_failure(
                            proxy, target_host,
                            error_type=error_type,
                            http_status_code=status_code,
                            circuit_breaker=circuit_breaker
                        )

                        # Also log to BigQuery for monitoring
                        log_proxy_result(
                            scraper_name=self.__class__.__name__,
                            target_host=target_host,
                            http_status_code=status_code,
                            response_time_ms=response_time_ms,
                            success=False,
                            error_type=error_type,
                            proxy_provider=provider
                        )
                        break  # Move to next proxy

                except (ProxyError, ConnectTimeout, ConnectionError) as ex:
                    elapsed = self.mark_time("proxy")

                    # Connection errors may be transient - retry with backoff
                    if attempt < MAX_RETRIES_PER_PROXY - 1:
                        delay = min(BASE_DELAY * (2 ** attempt) + random.uniform(0, 1), MAX_DELAY)
                        logger.warning("Proxy connection error: %s, %s, retrying in %.1fs (attempt %d/%d)",
                                       provider, type(ex).__name__, delay, attempt + 1, MAX_RETRIES_PER_PROXY)
                        time_module.sleep(delay)
                        continue  # Retry same proxy
                    else:
                        error_type = classify_error(exception=ex)
                        response_time_ms = int(float(elapsed) * 1000) if elapsed else None
                        logger.warning("Proxy error with %s, %s, took=%ss (exhausted retries)",
                                       provider, type(ex).__name__, elapsed)
                        proxy_errors.append({'proxy': provider, 'error': type(ex).__name__})

                        # Record failure to health manager and circuit breaker
                        record_proxy_failure(
                            proxy, target_host,
                            error_type=error_type,
                            error_message=str(ex),
                            circuit_breaker=circuit_breaker
                        )

                        # Also log to BigQuery for monitoring
                        log_proxy_result(
                            scraper_name=self.__class__.__name__,
                            target_host=target_host,
                            response_time_ms=response_time_ms,
                            success=False,
                            error_type=error_type,
                            error_message=str(ex),
                            proxy_provider=provider
                        )
                        break  # Move to next proxy

            if proxy_success:
                # Update rate limiter with response headers on success
                # NOTE: This method (_update_rate_limit_from_response) is expected to be
                # provided by another mixin or the base class. It's called here but
                # defined elsewhere (likely in RateLimiterMixin).
                if hasattr(self, '_update_rate_limit_from_response'):
                    self._update_rate_limit_from_response()
                break  # Got a successful response, exit proxy loop

            # Add delay before trying next proxy to avoid hammering
            if proxy != proxy_pool[-1]:  # Not the last proxy
                inter_proxy_delay = 2.0 + random.uniform(0, 1)
                logger.debug("Waiting %.1fs before trying next proxy", inter_proxy_delay)
                time_module.sleep(inter_proxy_delay)

        # If all proxies failed, send notification with health info
        if proxy_errors and len(proxy_errors) >= len(proxy_pool):
            health_summary = get_proxy_health_summary()
            try:
                notify_warning(
                    title=f"Scraper Proxy Exhaustion: {self.__class__.__name__}",
                    message=f"All {len(proxy_pool)} proxies failed after retries",
                    details={
                        'scraper': self.__class__.__name__,
                        'run_id': self.run_id,
                        'url': getattr(self, 'url', 'unknown'),
                        'proxy_count': len(proxy_pool),
                        'max_retries_per_proxy': MAX_RETRIES_PER_PROXY,
                        'failures': proxy_errors,
                        'proxy_health': health_summary
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

        # Check for WAF/Cloudflare blocks that return 200 with challenge page
        self._check_for_waf_block()

    def _check_for_waf_block(self):
        """
        Detect Cloudflare/WAF challenge pages that return HTTP 200.

        Challenge pages return 200 status but contain HTML with JavaScript
        challenges instead of the expected JSON/data content.
        """
        if not hasattr(self.raw_response, 'headers'):
            return

        headers = self.raw_response.headers

        # Check for Cloudflare-specific headers
        is_cloudflare = (
            headers.get('Server', '').lower() in ('cloudflare', 'cloudflare-nginx') or
            'cf-ray' in headers
        )

        # Check Content-Type mismatch (expecting JSON but got HTML)
        content_type = headers.get('Content-Type', '').lower()
        # Check if download_type is JSON (supports both enum and string)
        expecting_json = str(self.download_type).lower() in ('json', 'downloadtype.json')
        got_html = 'text/html' in content_type

        if expecting_json and got_html:
            # Peek at response content for challenge patterns
            try:
                content_preview = self.raw_response.content[:2000].decode('utf-8', errors='ignore').lower()
            except Exception:
                content_preview = ''

            # Common WAF/challenge page indicators
            waf_patterns = [
                'checking your browser',
                'please enable javascript',
                'please enable cookies',
                'access denied',
                'ray id:',
                '__cf_chl',
                'challenge-form',
                'captcha',
                'security check',
                'blocked',
                'ddos protection',
            ]

            detected_patterns = [p for p in waf_patterns if p in content_preview]

            if detected_patterns:
                waf_source = 'Cloudflare' if is_cloudflare else 'WAF'
                cf_ray = headers.get('cf-ray', 'none')

                logger.warning(
                    f"{waf_source} challenge/block detected! "
                    f"Patterns: {detected_patterns[:3]}, cf-ray: {cf_ray}, "
                    f"URL: {getattr(self.raw_response, 'url', 'unknown')}"
                )

                # Raise retryable exception - might work with different proxy/timing
                raise RetryInvalidHttpStatusCodeException(
                    f"{waf_source} challenge page detected (patterns: {detected_patterns[:2]}). "
                    f"Consider using browser mode or different proxy."
                )

    def decode_download_content(self):
        """
        If we're expecting JSON, parse self.raw_response.content as JSON.
        If download_type is HTML, store text in self.decoded_data.
        If BINARY, do nothing special.

        Handles encoding issues by falling back to latin-1 if UTF-8 fails.
        Also handles gzip and brotli compressed responses that weren't auto-decompressed.
        """
        logger.debug("Decoding raw response as '%s'", self.download_type)
        # Check download type (supports both enum and string values)
        download_type_str = str(self.download_type).lower()
        is_json = 'json' in download_type_str
        is_html = 'html' in download_type_str
        is_binary = 'binary' in download_type_str

        if is_json:
            content = self.raw_response.content

            # Check if response is gzip-compressed but wasn't auto-decompressed
            # (can happen when proxy doesn't pass Content-Encoding header correctly)
            if content[:2] == b'\x1f\x8b':  # gzip magic number
                import gzip
                try:
                    content = gzip.decompress(content)
                    logger.info("Manually decompressed gzip response")
                except Exception as e:
                    logger.warning("Failed to decompress gzip response: %s", e)

            # Check if response is brotli-compressed but wasn't auto-decompressed
            # (can happen when server ignores Accept-Encoding or CDN sends cached brotli)
            # Brotli doesn't have a magic number, but we can detect it by:
            # 1. Content starts with non-UTF8 bytes and
            # 2. Doesn't start with { or [ (valid JSON start)
            # 3. Is not gzip (already handled above)
            elif content and content[0:1] not in (b'{', b'[', b'"', b' ', b'\n', b'\t'):
                try:
                    import brotli
                    decompressed = brotli.decompress(content)
                    content = decompressed
                    logger.info("Manually decompressed brotli response (%d -> %d bytes)",
                               len(self.raw_response.content), len(content))
                except ImportError:
                    logger.warning("Brotli package not installed - cannot decompress brotli response")
                except Exception as e:
                    # Not brotli or decompression failed - continue with original content
                    logger.debug("Brotli decompression not applicable: %s", e)

            try:
                self.decoded_data = json.loads(content)
            except UnicodeDecodeError as e:
                # UTF-8 decode failed, try latin-1 fallback
                logger.warning("UTF-8 decode failed for %s, trying latin-1: %s",
                             self.__class__.__name__, e)
                try:
                    content_str = content.decode('latin-1')
                    self.decoded_data = json.loads(content_str)
                    logger.info("Successfully decoded with latin-1 fallback")
                except (UnicodeDecodeError, json.JSONDecodeError) as e2:
                    logger.error("All encoding attempts failed for %s: %s",
                               self.__class__.__name__, e2)
                    try:
                        notify_warning(
                            title=f"Scraper Encoding Failed: {self.__class__.__name__}",
                            message="Could not decode response with UTF-8 or latin-1",
                            details={
                                'scraper': self.__class__.__name__,
                                'run_id': self.run_id,
                                'url': getattr(self, 'url', 'unknown'),
                                'error': str(e2),
                                'content_preview': content[:200].decode('utf-8', errors='replace')
                            }
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                    raise DownloadDataException(f"Response encoding failed: {e2}") from e2
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
                            'content_preview': content[:200].decode('utf-8', errors='ignore')
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                # eligible for retry
                raise DownloadDataException(f"JSON decode failed: {ex}") from ex
        elif is_html:
            try:
                self.decoded_data = self.raw_response.text
            except UnicodeDecodeError:
                # Fallback for HTML content with non-UTF-8 encoding
                logger.warning("UTF-8 decode failed for HTML, using latin-1 fallback")
                self.decoded_data = self.raw_response.content.decode('latin-1')
        elif is_binary:
            # Still place the bytes in decoded_data so ExportMode.DECODED works
            self.decoded_data = self.raw_response.content
        else:
            pass

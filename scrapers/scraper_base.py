# scrapers/scraper_base.py

import requests
import logging
import time
import os
import sys
import traceback
import pprint
import json
import random
from datetime import datetime

from requests.exceptions import ProxyError, ConnectTimeout, ConnectionError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .utils.env_utils import is_local
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


logger = logging.getLogger("scraper_base")
logger.setLevel(logging.INFO)

class ScraperBase:
    """
    A base class for scrapers that handles:
      - HTTP GET, optional proxies
      - Automatic retries on certain exceptions
      - Decode JSON data (optional)
      - Validate data structure (child class override)
      - Export the data (GCS, file, print)
      - post_export hook that logs a structured summary
    """

    required_opts = []
    additional_opts = []
    exporters = []
    url = None
    headers = None

    download_retry_count = 0
    max_retries_http_downloader = 3
    timeout_secs_http_downloader = 20
    use_proxy = False
    test_proxies = False
    should_decode_download_data = True
    download_type = "json"
    max_retries_download_decode = 8
    no_retry_error_codes = [404]

    decoded_data = {}
    data = {}
    stats = {}
    time_markers = {}

    def __init__(self):
        self.opts = {}
        self.http_downloader = None
        self.download = {}
        self.decoded_data = {}
        self.data = {}
        self.stats = {}
        self.time_markers = {}
        self.download_retry_count = 0

    def run(self, opts=None):
        if opts is None:
            opts = {}

        try:
            self.__init__()  # re-init in case run is called multiple times
            self.mark_time("all")

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
            logger.info("Download+Decode completed in %.2f seconds", download_seconds)

            if self.should_decode():
                self.validate_download_data()
                self.set_opts_from_data()
                self.validate_opts_from_data()
                self.slice_data()

            self.mark_time("export")
            self.export_data()
            export_seconds = self.get_elapsed_seconds("export")
            self.stats["export_time"] = export_seconds
            logger.info("Export completed in %.2f seconds", export_seconds)

            self.post_export()

            total_seconds = self.get_elapsed_seconds("all")
            self.stats["total_runtime"] = total_seconds
            logger.info("Scraper run completed in %.2f seconds total", total_seconds)

            if self.should_decode():
                return self.get_return_value()
            else:
                return True

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            logger.error("ScraperBase Error: %s %s", exc_type, e, exc_info=True)
            traceback.print_exc()
            return False

    # ------------------ OVERRIDABLE HOOKS ------------------
    def set_url(self):
        pass

    def set_headers(self):
        pass

    def validate_download_data(self):
        pass

    def set_opts_from_data(self):
        pass

    def validate_opts_from_data(self):
        pass

    def slice_data(self):
        pass

    def should_save_data(self):
        return True

    def get_return_value(self):
        return True

    ###########################################################################
    # post_export() -> We now add a structured log that can be parsed daily.
    ###########################################################################
    def post_export(self):
        """
        Runs after all exports are completed. 
        Here, we emit a SCRAPER_STATS line with JSON summary, so a daily aggregator can parse it.
        """
        summary = {
            "scraper_name": self.__class__.__name__,
            "function_name": os.getenv("K_SERVICE", "unknown"),  # e.g. GCF name
            "timestamp_utc": datetime.utcnow().isoformat(),
            "total_runtime": self.stats.get("total_runtime", 0),
        }
        # Let child scrapers add record counts, etc.
        child_stats = self.get_scraper_stats()
        if child_stats and isinstance(child_stats, dict):
            summary.update(child_stats)

        logger.info("SCRAPER_STATS %s", json.dumps(summary))

    def get_scraper_stats(self):
        """
        Child classes can override to provide extra fields for daily summary logs.
        E.g. number of records processed, main date, etc.
        By default, returns empty dict.
        """
        return {}

    # ------------------ OPTION VALIDATION ------------------
    def validate_opts(self):
        for required_opt in self.required_opts:
            if required_opt not in self.opts:
                raise DownloadDataException(f"Missing required option [{required_opt}].")

    def set_exporter_group_to_opts(self):
        if "group" not in self.opts:
            from .utils.env_utils import is_local
            self.opts["group"] = "dev" if is_local() else "prod"

    def set_additional_opts(self):
        pass

    def validate_additional_opts(self):
        if "group" not in self.opts:
            raise DownloadDataException("Missing 'group' after set_exporter_group_to_opts.")

    def set_opts(self, opts):
        self.opts = opts

    # ------------------ DOWNLOAD & DECODE ------------------
    def download_and_decode(self):
        try:
            self.set_http_downloader()
            self.start_download()
            self.check_download_status()

            if self.should_decode():
                self.decode_download_data()

        except (ValueError,
                InvalidRegionDecodeException,
                NoHttpStatusCodeException,
                RetryInvalidHttpStatusCodeException) as err:
            self.increment_retry_count()
            self.sleep_before_retry()

            logger.warning(
                "[Retry %s] after %s: %s",
                self.download_retry_count, type(err).__name__, err
            )
            self.download_and_decode()

        except InvalidHttpStatusCodeException as err:
            raise

    def set_http_downloader(self):
        self.http_downloader = requests.Session()
        retry_strategy = self.get_retry_strategy()
        adapter = self.get_http_adapter(retry_strategy)

        self.http_downloader.mount("https://", adapter)
        self.http_downloader.mount("http://", adapter)

    def get_retry_strategy(self):
        return Retry(
            total=self.max_retries_http_downloader,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            backoff_factor=3
        )

    def get_http_adapter(self, retry_strategy):
        return HTTPAdapter(max_retries=retry_strategy)

    def start_download(self):
        if self.should_use_proxy():
            self.download_data_with_proxy()
        else:
            self.download_data()

    def download_data(self):
        logger.info("Starting download without proxy: %s", self.url)
        self.download = self.http_downloader.get(
            self.url,
            headers=self.headers,
            timeout=self.timeout_secs_http_downloader
        )

    def download_data_with_proxy(self):
        proxy_pool = get_proxy_urls()
        if not self.test_proxies:
            random.shuffle(proxy_pool)

        self.mark_time("proxy")
        for proxy in proxy_pool:
            try:
                logger.info("Attempting proxy: %s", proxy)
                self.download = self.http_downloader.get(
                    self.url,
                    headers=self.headers,
                    proxies={"https": proxy},
                    timeout=self.timeout_secs_http_downloader
                )
                seconds = self.mark_time("proxy")

                if self.download.status_code == 200 and not self.test_proxies:
                    logger.info(
                        "Proxy success: %s, status=%d, took=%ss",
                        proxy, self.download.status_code, seconds
                    )
                    break
                else:
                    logger.warning(
                        "Proxy failed: %s, status=%d, took=%ss",
                        proxy, self.download.status_code, seconds
                    )

            except (ProxyError, ConnectTimeout, ConnectionError) as ex:
                seconds = self.mark_time("proxy")
                logger.warning(
                    "Proxy error with %s, %s, took=%ss",
                    proxy, type(ex).__name__, seconds
                )

    def check_download_status(self):
        if not hasattr(self.download, "status_code"):
            raise NoHttpStatusCodeException("No status_code on download response.")

        if self.download.status_code != 200:
            if self.should_retry_on_http_status_code(self.download.status_code):
                raise RetryInvalidHttpStatusCodeException(
                    f"Invalid HTTP status code (retry): {self.download.status_code}"
                )
            else:
                raise InvalidHttpStatusCodeException(
                    f"Invalid HTTP status code (no retry): {self.download.status_code}"
                )

    def decode_download_data(self):
        logger.debug("Decoding download data as '%s'", self.download_type)
        if self.download_type == "json":
            self.decoded_data = json.loads(self.download.content)
        else:
            raise DownloadDataException(f"Unknown download_type: {self.download_type}")

    def should_decode(self):
        return self.should_decode_download_data

    def should_retry_on_http_status_code(self, status_code):
        return False if status_code in self.no_retry_error_codes else True

    # ------------------ RETRY HELPERS ------------------
    def increment_retry_count(self):
        if self.download_retry_count < self.max_retries_download_decode:
            self.download_retry_count += 1
        else:
            raise DownloadDecodeMaxRetryException(
                f"Max decode/download retries reached: {self.max_retries_download_decode}"
            )

    def sleep_before_retry(self):
        backoff_factor = 4
        backoff_max = 15
        sleep_seconds = min(backoff_factor * (2 ** (self.download_retry_count - 1)), backoff_max)
        logger.warning("Sleeping %.1f seconds before retry...", sleep_seconds)
        time.sleep(sleep_seconds)

    def should_use_proxy(self):
        return self.use_proxy

    # ------------------ EXPORTS ------------------
    def export_data(self):
        for config in self.exporters:
            if "groups" in config:
                if self.opts["group"] not in config["groups"]:
                    continue

            if "check_should_save" in config and config["check_should_save"]:
                if not self.should_save_data():
                    logger.info("Skipping export for config: %s (should_save_data=False)", config)
                    continue

            if config.get("use_raw"):
                data_to_export = self.download.content
            elif config.get("use_decoded_data"):
                data_to_export = self.decoded_data
            elif "data_key" in config:
                data_to_export = self.data.get(config["data_key"], {})
            else:
                data_to_export = self.data

            exporter_type = config["type"]
            exporter_cls = EXPORTER_REGISTRY.get(exporter_type)
            if exporter_cls is None:
                raise DownloadDataException(f"Exporter type not found: {exporter_type}")

            exporter = exporter_cls()
            logger.info("Exporting with %s (config=%s)", exporter_type, config)
            exporter.run(data_to_export, config, self.opts)

    # ------------------ TIME MEASUREMENTS ------------------
    def mark_time(self, label):
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
            return str(round(delta, 1))

    def get_elapsed_seconds(self, label):
        if label not in self.time_markers:
            return 0.0
        start_time = self.time_markers[label]["start"]
        now_time = datetime.now()
        return (now_time - start_time).total_seconds()

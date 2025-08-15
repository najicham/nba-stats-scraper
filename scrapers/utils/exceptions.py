# scrapers/utils/exceptions.py

class InvalidRegionDecodeException(Exception):
    """
    Sometimes raised if a region-based decode fails
    (Used in ScraperBase retry logic)
    """
    pass


class UsageError(Exception):
    """
    For command-line usage errors (possibly unused now).
    """


class DownloadDecodeMaxRetryException(Exception):
    """
    Raised when download/decode attempts exceed max_retries_download_decode
    (Used in ScraperBase)
    """
    pass


class GetFileDecodeMaxRetryException(Exception):
    """
    Potentially unused now. If you do not call it anywhere,
    you can remove it.
    """
    pass


class NoHttpStatusCodeException(Exception):
    """
    Raised when there's no status_code in HTTP response
    (Used in ScraperBase)
    """
    pass


class InvalidHttpStatusCodeException(Exception):
    """
    Raised for non-200 status codes that are not retryable
    (Used in ScraperBase)
    """
    pass


class InvalidSourceTypeException(Exception):
    """
    Potentially unused. Remove if not called anywhere in new code.
    """
    pass


class RetryInvalidHttpStatusCodeException(Exception):
    """
    Raised for invalid HTTP status codes that should be retried
    (Used in ScraperBase)
    """
    pass


class InvalidArgumentException(Exception):
    """
    Generic invalid argument. Possibly unused.
    """


class ProcessCheckException(Exception):
    """
    Possibly unused. Remove if no references in your code.
    """


class CheckTypeException(Exception):
    """
    Possibly unused. Remove if no references in your code.
    """


class FileSlicerException(Exception):
    """
    Possibly unused. Remove if no references in your code.
    """


class DownloadDataException(Exception):
    """
    Typically raised when downloaded JSON structure is invalid
    (Used in ScraperBase and child scrapers)
    """
    pass


class DatesToProcessException(Exception):
    """
    Possibly unused. 
    """


class KeyDateException(Exception):
    """
    Possibly unused.
    """


class ReporterException(Exception):
    """
    Possibly unused.
    """

class NoDataAvailableSuccess(Exception):
    """Special exception indicating "no data available" should be treated as success."""
    pass

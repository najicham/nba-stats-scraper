"""
Common Type Definitions
=======================
Shared type aliases and type hints used across the platform.

Provides consistent typing for common patterns like:
- BigQuery query results
- API responses
- Processor outputs
- Scraper results

Usage:
    from shared.utils.type_defs import BigQueryResult, ProcessorOutput

    def get_player_stats(player_id: str) -> BigQueryResult:
        ...

    def process_games(date: str) -> ProcessorOutput:
        ...

Version: 1.0
Created: 2026-01-24
"""

from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    TypedDict,
    Union,
)
from datetime import date, datetime


# =============================================================================
# BigQuery Types
# =============================================================================

# Generic BigQuery result (list of row dicts)
BigQueryResult = List[Dict[str, Any]]

# Single BigQuery row
BigQueryRow = Dict[str, Any]

# Query parameters
QueryParam = Union[str, int, float, bool, date, datetime, None]
QueryParams = Dict[str, QueryParam]


# =============================================================================
# Processor Types
# =============================================================================

# Standard processor output
ProcessorOutput = List[Dict[str, Any]]

# Processor run result
class ProcessorRunResult(TypedDict, total=False):
    """Result from a processor run."""
    status: str  # 'success', 'failed', 'skipped'
    records_processed: int
    records_failed: int
    duration_seconds: float
    error_message: Optional[str]
    skip_reason: Optional[str]


# Dependency check result
class DependencyCheckResult(TypedDict, total=False):
    """Result from dependency checking."""
    should_proceed: bool
    degraded: bool
    coverage: Dict[str, float]
    warnings: List[str]
    errors: List[str]


# =============================================================================
# Scraper Types
# =============================================================================

# Scraper result
ScraperResult = Dict[str, Any]

# Scraped data records
ScrapedRecords = List[Dict[str, Any]]

# HTTP response-like result
class HttpResult(TypedDict, total=False):
    """HTTP request result."""
    status_code: int
    content: bytes
    text: str
    json: Dict[str, Any]
    headers: Dict[str, str]
    elapsed_ms: float


# =============================================================================
# API/Cloud Function Types
# =============================================================================

# Cloud Function response
CloudFunctionResponse = Dict[str, Any]

# Standard API response
class ApiResponse(TypedDict, total=False):
    """Standard API response format."""
    status: str
    message: str
    data: Any
    error: Optional[str]
    timestamp: str


# Pub/Sub message
class PubSubMessage(TypedDict, total=False):
    """Pub/Sub message structure."""
    data: str  # Base64 encoded
    attributes: Dict[str, str]
    message_id: str
    publish_time: str


# =============================================================================
# Configuration Types
# =============================================================================

# Generic config dict
ConfigDict = Dict[str, Any]

# Environment-based config
EnvConfig = Dict[str, str]


# =============================================================================
# Date/Time Types
# =============================================================================

# Date string in YYYY-MM-DD format
DateString = str

# Datetime string in ISO format
DateTimeString = str

# Date range tuple
DateRange = Tuple[date, date]


# =============================================================================
# Callback/Handler Types
# =============================================================================

# Generic callback function
Callback = Callable[..., Any]

# Error handler
ErrorHandler = Callable[[Exception], None]

# Result transformer
ResultTransformer = Callable[[Any], Any]


# =============================================================================
# Entity Types
# =============================================================================

# Player identifier
PlayerId = str

# Game identifier
GameId = str

# Team abbreviation (e.g., 'LAL', 'BOS')
TeamAbbr = str

# Prop type (e.g., 'points', 'rebounds', 'assists')
PropType = str


# =============================================================================
# Validation Types
# =============================================================================

class ValidationResult(TypedDict, total=False):
    """Result from data validation."""
    valid: bool
    errors: List[str]
    warnings: List[str]
    records_checked: int
    records_invalid: int


# =============================================================================
# Alert Types
# =============================================================================

class AlertPayload(TypedDict, total=False):
    """Alert message payload."""
    severity: str  # 'info', 'warning', 'error', 'critical'
    title: str
    message: str
    category: str
    context: Dict[str, Any]
    timestamp: str

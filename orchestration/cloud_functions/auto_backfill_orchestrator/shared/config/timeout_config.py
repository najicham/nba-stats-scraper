"""
Week 1: Centralized Timeout Configuration

Single source of truth for all timeout values across the codebase.

Previously: 1,070+ hardcoded timeout values scattered across files
Now: All timeouts defined here with clear documentation

Usage:
    from shared.config.timeout_config import TimeoutConfig

    timeouts = TimeoutConfig()
    requests.get(url, timeout=timeouts.HTTP_REQUEST)

Environment Variable Overrides:
    All timeouts can be overridden via environment variables:
    - TIMEOUT_HTTP_REQUEST=30
    - TIMEOUT_BIGQUERY_QUERY=120
    etc.

Created: 2026-01-20 (Week 1, Day 4)
"""

import os
from dataclasses import dataclass


@dataclass
class TimeoutConfig:
    """
    Centralized timeout configuration.

    All values in seconds unless otherwise noted.
    """

    # ============================================================================
    # HTTP/API Timeouts
    # ============================================================================

    # Standard HTTP requests (scraping, API calls)
    HTTP_REQUEST: int = 30

    # Scraper HTTP calls in workflow executor
    SCRAPER_HTTP: int = 180  # 3 minutes (scrapers can be slow)

    # Scraper future timeout (parallel execution)
    SCRAPER_FUTURE: int = 190  # 10s overhead over HTTP timeout

    # Cloud Run health checks
    HEALTH_CHECK: int = 10

    # Slack webhook notifications
    SLACK_WEBHOOK: int = 10

    # Basketball-Reference.com (can be slow)
    BR_SCRAPER: int = 45

    # NBA.com API (can be slow)
    NBAC_API: int = 60

    # BigDataBall API
    BDB_API: int = 30

    # OddsAPI
    ODDS_API: int = 30

    # BallDontLie API
    BDL_API: int = 30

    # ============================================================================
    # BigQuery Timeouts
    # ============================================================================

    # Standard BigQuery query
    BIGQUERY_QUERY: int = 60  # 1 minute

    # Large BigQuery query (batch operations)
    BIGQUERY_LARGE_QUERY: int = 300  # 5 minutes

    # BigQuery load job
    BIGQUERY_LOAD: int = 60

    # BigQuery streaming insert
    BIGQUERY_STREAMING: int = 30

    # ============================================================================
    # Firestore Timeouts
    # ============================================================================

    # Standard Firestore read
    FIRESTORE_READ: int = 10

    # Firestore write
    FIRESTORE_WRITE: int = 10

    # Firestore transaction
    FIRESTORE_TRANSACTION: int = 30

    # Firestore batch write
    FIRESTORE_BATCH: int = 60

    # ============================================================================
    # Pub/Sub Timeouts
    # ============================================================================

    # Pub/Sub publish
    PUBSUB_PUBLISH: int = 60

    # Pub/Sub batch publish
    PUBSUB_BATCH_PUBLISH: int = 120

    # ============================================================================
    # Workflow/Orchestration Timeouts
    # ============================================================================

    # Workflow execution timeout
    WORKFLOW_EXECUTION: int = 600  # 10 minutes

    # Phase 2 processor timeout
    PHASE2_PROCESSOR: int = 600  # 10 minutes

    # Week 1: Phase 2 completion deadline (minutes)
    PHASE2_COMPLETION_DEADLINE: int = 30  # minutes

    # Phase 3 processor timeout
    PHASE3_PROCESSOR: int = 600

    # Phase 4 processor timeout
    PHASE4_PROCESSOR: int = 600

    # Phase 5 prediction worker timeout
    PHASE5_WORKER: int = 300  # 5 minutes

    # Cloud Scheduler job timeout
    SCHEDULER_JOB: int = 600  # 10 minutes (default for all scheduler jobs)

    # ============================================================================
    # Machine Learning Timeouts
    # ============================================================================

    # Model inference
    ML_INFERENCE: int = 30

    # Model training
    ML_TRAINING: int = 3600  # 1 hour

    # Feature computation
    ML_FEATURES: int = 120  # 2 minutes

    # ============================================================================
    # Database Connection Timeouts
    # ============================================================================

    # Database connection timeout
    DB_CONNECT: int = 30

    # Database query timeout
    DB_QUERY: int = 60

    # Connection pool checkout
    DB_POOL_CHECKOUT: int = 30

    # ============================================================================
    # Retry/Backoff Timeouts
    # ============================================================================

    # Circuit breaker timeout (seconds)
    CIRCUIT_BREAKER: int = 300  # 5 minutes

    # Retry backoff base (seconds)
    RETRY_BACKOFF_BASE: float = 1.0

    # Retry backoff max (seconds)
    RETRY_BACKOFF_MAX: float = 30.0

    # ============================================================================
    # Application-Specific Timeouts
    # ============================================================================

    # Batch consolidation timeout
    BATCH_CONSOLIDATION: int = 300  # 5 minutes

    # Data loader batch operation
    DATA_LOADER_BATCH: int = 120  # 2 minutes (increased from 30s for 300-400 players)

    # Stall detection (seconds)
    STALL_DETECTION: int = 600  # 10 minutes

    # Session timeout
    SESSION_TIMEOUT: int = 3600  # 1 hour

    # ============================================================================
    # Environment Variable Overrides
    # ============================================================================

    def __post_init__(self):
        """Apply environment variable overrides."""
        # HTTP/API
        self.HTTP_REQUEST = int(os.getenv('TIMEOUT_HTTP_REQUEST', self.HTTP_REQUEST))
        self.SCRAPER_HTTP = int(os.getenv('TIMEOUT_SCRAPER_HTTP', self.SCRAPER_HTTP))
        self.HEALTH_CHECK = int(os.getenv('TIMEOUT_HEALTH_CHECK', self.HEALTH_CHECK))
        self.SLACK_WEBHOOK = int(os.getenv('TIMEOUT_SLACK_WEBHOOK', self.SLACK_WEBHOOK))

        # BigQuery
        self.BIGQUERY_QUERY = int(os.getenv('TIMEOUT_BIGQUERY_QUERY', self.BIGQUERY_QUERY))
        self.BIGQUERY_LARGE_QUERY = int(os.getenv('TIMEOUT_BIGQUERY_LARGE_QUERY', self.BIGQUERY_LARGE_QUERY))
        self.BIGQUERY_LOAD = int(os.getenv('TIMEOUT_BIGQUERY_LOAD', self.BIGQUERY_LOAD))

        # Firestore
        self.FIRESTORE_READ = int(os.getenv('TIMEOUT_FIRESTORE_READ', self.FIRESTORE_READ))
        self.FIRESTORE_WRITE = int(os.getenv('TIMEOUT_FIRESTORE_WRITE', self.FIRESTORE_WRITE))
        self.FIRESTORE_TRANSACTION = int(os.getenv('TIMEOUT_FIRESTORE_TRANSACTION', self.FIRESTORE_TRANSACTION))

        # Pub/Sub
        self.PUBSUB_PUBLISH = int(os.getenv('TIMEOUT_PUBSUB_PUBLISH', self.PUBSUB_PUBLISH))

        # Workflow
        self.WORKFLOW_EXECUTION = int(os.getenv('TIMEOUT_WORKFLOW_EXECUTION', self.WORKFLOW_EXECUTION))
        self.SCHEDULER_JOB = int(os.getenv('TIMEOUT_SCHEDULER_JOB', self.SCHEDULER_JOB))

        # ML
        self.ML_INFERENCE = int(os.getenv('TIMEOUT_ML_INFERENCE', self.ML_INFERENCE))
        self.ML_TRAINING = int(os.getenv('TIMEOUT_ML_TRAINING', self.ML_TRAINING))

        # Application
        self.BATCH_CONSOLIDATION = int(os.getenv('TIMEOUT_BATCH_CONSOLIDATION', self.BATCH_CONSOLIDATION))
        self.DATA_LOADER_BATCH = int(os.getenv('TIMEOUT_DATA_LOADER_BATCH', self.DATA_LOADER_BATCH))
        self.STALL_DETECTION = int(os.getenv('TIMEOUT_STALL_DETECTION', self.STALL_DETECTION))


# Singleton instance
_timeouts: TimeoutConfig = None


def get_timeout_config() -> TimeoutConfig:
    """Get the singleton timeout configuration."""
    global _timeouts
    if _timeouts is None:
        _timeouts = TimeoutConfig()
    return _timeouts


# Convenience exports for common timeouts
def get_http_timeout() -> int:
    """Get standard HTTP request timeout."""
    return get_timeout_config().HTTP_REQUEST


def get_bigquery_timeout() -> int:
    """Get standard BigQuery query timeout."""
    return get_timeout_config().BIGQUERY_QUERY


def get_scraper_timeout() -> int:
    """Get scraper HTTP timeout."""
    return get_timeout_config().SCRAPER_HTTP


def get_workflow_timeout() -> int:
    """Get workflow execution timeout."""
    return get_timeout_config().WORKFLOW_EXECUTION

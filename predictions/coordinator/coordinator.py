# predictions/coordinator/coordinator.py

"""
Phase 5 Prediction Coordinator

Cloud Run service that orchestrates daily prediction generation for all NBA players.

Flow:
1. Triggered by Cloud Scheduler (or HTTP request)
2. Query players with games today (~450 players)
3. Publish prediction request for each player to Pub/Sub
4. Monitor completion events from workers
5. Track progress (450/450)
6. Publish summary when complete

Architecture:
- /start endpoint: Initiates prediction batch
- /status endpoint: Check progress
- /complete endpoint: Receives completion events from workers
"""

from flask import Flask, request, jsonify
from functools import wraps
import json
import logging
import os
import secrets
import threading
import uuid
from typing import Dict, List, Optional, TYPE_CHECKING
from datetime import datetime, date, timedelta
import base64
import time

# Startup verification - MUST be early to detect wrong code deployment
try:
    from shared.utils.startup_verification import verify_startup
    verify_startup(
        expected_module="prediction-coordinator",
        service_name="prediction-coordinator"
    )
except ImportError:
    # Shared module not available (local dev without full setup)
    logging.warning("startup_verification not available - running without verification")

# Critical imports verification - catch missing modules at startup, not at runtime
# This prevents silent failures where the service starts but crashes on first request
_CRITICAL_IMPORTS = [
    'predictions.worker.data_loaders',  # Used in start_prediction_batch for batch loading
]
for _module in _CRITICAL_IMPORTS:
    try:
        __import__(_module)
        logging.info(f"Critical import verified: {_module}")
    except ImportError as e:
        logging.error(f"CRITICAL: Missing import {_module}: {e}")
        logging.error("This is likely a Dockerfile issue - check that all required directories are copied")
        raise SystemExit(1)

# Defer google.cloud imports to lazy loading functions to avoid cold start hang
if TYPE_CHECKING:
    from google.cloud import bigquery, pubsub_v1

from predictions.coordinator.player_loader import PlayerLoader
from predictions.coordinator.progress_tracker import ProgressTracker
from predictions.coordinator.run_history import CoordinatorRunHistory
from predictions.coordinator.coverage_monitor import PredictionCoverageMonitor
from predictions.coordinator.batch_state_manager import get_batch_state_manager, BatchStateManager, BatchState
from predictions.coordinator.instance_manager import (
    CoordinatorInstanceManager,
    get_instance_manager,
    LockAcquisitionError
)

# Import batch consolidator for staging table merging
from predictions.shared.batch_staging_writer import BatchConsolidator

# Import unified publishing (lazy import to avoid cold start)
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from shared.publishers.unified_pubsub_publisher import UnifiedPubSubPublisher
from shared.config.orchestration_config import get_orchestration_config
from shared.utils.env_validation import validate_required_env_vars
from shared.utils.bigquery_retry import retry_on_transient
from shared.utils.firestore_retry import retry_on_firestore_error, retry_firestore_transaction
from shared.utils.auth_utils import get_api_key
from shared.endpoints.health import create_health_blueprint, HealthChecker

# Postponement detection (Jan 2026)
from shared.utils.postponement_detector import PostponementDetector
from predictions.coordinator.signal_calculator import calculate_daily_signals

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HeartbeatLogger:
    """
    Periodic heartbeat logger for long-running operations.

    Logs a heartbeat message every N seconds to prove the process is still alive.
    Helps debugging hung processes by showing where they got stuck.

    Usage:
        with HeartbeatLogger("Loading historical games", interval=300):  # 5 min
            # Long-running operation
            data = load_historical_games_batch(...)
    """
    def __init__(self, operation_name: str, interval: int = 300):
        """
        Args:
            operation_name: Name of the operation for logging
            interval: Heartbeat interval in seconds (default 5 minutes)
        """
        self.operation_name = operation_name
        self.interval = interval
        self.start_time = None
        self.timer = None
        self._active = False

    def __enter__(self):
        """Start heartbeat logging when entering context"""
        self.start_time = time.time()
        self._active = True
        logger.info(f"HEARTBEAT START: {self.operation_name}")
        self._schedule_next_heartbeat()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop heartbeat logging when exiting context"""
        self._active = False
        if self.timer:
            self.timer.cancel()

        elapsed = time.time() - self.start_time
        elapsed_min = elapsed / 60

        if exc_type:
            logger.error(f"HEARTBEAT END (ERROR): {self.operation_name} failed after {elapsed_min:.1f} min", exc_info=True)
        else:
            logger.info(f"HEARTBEAT END: {self.operation_name} completed in {elapsed_min:.1f} min")

        return False  # Don't suppress exceptions

    def _schedule_next_heartbeat(self):
        """Schedule the next heartbeat log"""
        if not self._active:
            return

        # Log current heartbeat
        if self.start_time:
            elapsed = time.time() - self.start_time
            elapsed_min = elapsed / 60
            logger.info(f"HEARTBEAT: {self.operation_name} still running ({elapsed_min:.1f} min elapsed)")

        # Schedule next heartbeat
        self.timer = threading.Timer(self.interval, self._schedule_next_heartbeat)
        self.timer.daemon = True  # Don't prevent process exit
        self.timer.start()


# Validate required environment variables at startup
validate_required_env_vars(
    ['GCP_PROJECT_ID'],
    service_name='PredictionCoordinator'
)

# Flask app
app = Flask(__name__)

# Environment configuration
from shared.config.gcp_config import get_project_id
PROJECT_ID = get_project_id()
PREDICTION_REQUEST_TOPIC = os.environ.get('PREDICTION_REQUEST_TOPIC', 'prediction-request-prod')
PREDICTION_READY_TOPIC = os.environ.get('PREDICTION_READY_TOPIC', 'prediction-ready-prod')
BATCH_SUMMARY_TOPIC = os.environ.get('BATCH_SUMMARY_TOPIC', 'prediction-batch-complete')

# Week 1: Idempotency feature flags
ENABLE_IDEMPOTENCY_KEYS = os.environ.get('ENABLE_IDEMPOTENCY_KEYS', 'false').lower() == 'true'
DEDUP_TTL_DAYS = int(os.environ.get('DEDUP_TTL_DAYS', '7'))

# API Key authentication (required for /start and /complete endpoints)
# Try Secret Manager first, fallback to environment variable for local dev
COORDINATOR_API_KEY = get_api_key(
    secret_name='coordinator-api-key',
    default_env_var='COORDINATOR_API_KEY'
)
if not COORDINATOR_API_KEY:
    logger.warning("COORDINATOR_API_KEY not available from Secret Manager or environment - authenticated endpoints will reject all requests")

# Health check endpoints (Phase 1 - Task 1.1: Add Health Endpoints)
# See: docs/08-projects/current/pipeline-reliability-improvements/
health_checker = HealthChecker(
    service_name='prediction-coordinator',
    version='1.0'
)
app.register_blueprint(create_health_blueprint(
    service_name='prediction-coordinator',
    version='1.0',
    health_checker=health_checker
))
logger.info("Health check endpoints registered: /health, /ready, /health/deep")


# =============================================================================
# DATA COMPLETENESS GATE (Jan 2026 Resilience)
# Prevents predictions when historical data is incomplete
# =============================================================================

@retry_on_transient
def _check_data_completeness_for_predictions(
    game_date: date,
    dataset_prefix: str = '',
    lookback_days: int = 7,
    threshold_pct: float = 80.0
) -> dict:
    """
    Check if historical data is complete enough to make reliable predictions.

    Checks analytics coverage for the lookback period. If coverage is below
    threshold, predictions should be blocked to prevent using stale data.

    Args:
        game_date: Date we're making predictions for
        dataset_prefix: Optional dataset prefix for test isolation
        lookback_days: How many days of history to check
        threshold_pct: Minimum coverage percentage required

    Returns:
        dict with:
            - is_complete: bool - True if data meets threshold
            - analytics_coverage_pct: float - Actual coverage percentage
            - threshold: float - Required threshold
            - details: dict - Per-date breakdown
    """
    from google.cloud import bigquery

    client = bigquery.Client(project=PROJECT_ID)

    # Check analytics coverage for the lookback period
    query = f"""
    WITH schedule AS (
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as expected_games
        FROM `{PROJECT_ID}.nba_raw.v_nbac_schedule_latest`
        WHERE game_status = 3
            AND game_date >= DATE_SUB(@game_date, INTERVAL {lookback_days} DAY)
            AND game_date < @game_date
        GROUP BY 1
    ),
    analytics AS (
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as analytics_games
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
        WHERE game_date >= DATE_SUB(@game_date, INTERVAL {lookback_days} DAY)
            AND game_date < @game_date
        GROUP BY 1
    )
    SELECT
        COALESCE(SUM(s.expected_games), 0) as total_expected,
        COALESCE(SUM(a.analytics_games), 0) as total_with_analytics,
        SAFE_DIVIDE(SUM(a.analytics_games), SUM(s.expected_games)) * 100 as coverage_pct
    FROM schedule s
    LEFT JOIN analytics a ON s.game_date = a.game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    result = list(client.query(query, job_config=job_config).result())

    if not result or result[0]['total_expected'] == 0:
        # No games in lookback period - likely offseason
        return {
            'is_complete': True,
            'analytics_coverage_pct': 100.0,
            'threshold': threshold_pct,
            'details': {'note': 'No games in lookback period'}
        }

    row = result[0]
    coverage_pct = row['coverage_pct'] or 0.0

    return {
        'is_complete': coverage_pct >= threshold_pct,
        'analytics_coverage_pct': coverage_pct,
        'threshold': threshold_pct,
        'total_expected_games': row['total_expected'],
        'total_with_analytics': row['total_with_analytics'],
        'lookback_days': lookback_days,
        'details': {
            'expected_games': row['total_expected'],
            'games_with_analytics': row['total_with_analytics'],
            'missing_games': row['total_expected'] - row['total_with_analytics']
        }
    }


# =============================================================================
# POSTPONEMENT CHECK (Jan 2026 Resilience)
# Warns if games on the target date are known to be postponed
# =============================================================================

def _check_for_postponed_games(game_date: date) -> dict:
    """
    Check if any games on the target date are known to be postponed.

    Checks two sources:
    1. game_postponements table - known postponements already tracked
    2. PostponementDetector - detects games appearing on multiple dates (rescheduled)

    Args:
        game_date: Date we're making predictions for

    Returns:
        dict with:
            - has_postponements: bool - True if any postponed games found
            - tracked_postponements: list - Games in game_postponements table
            - detected_rescheduled: list - Games detected as rescheduled
            - total_count: int - Total number of postponed games
    """
    from google.cloud import bigquery

    client = bigquery.Client(project=PROJECT_ID)
    result = {
        'has_postponements': False,
        'tracked_postponements': [],
        'detected_rescheduled': [],
        'total_count': 0
    }

    # Check 1: Known postponements in tracking table
    query = """
    SELECT
        game_id,
        original_date,
        new_date,
        reason,
        status,
        detection_details
    FROM `nba_orchestration.game_postponements`
    WHERE original_date = @game_date
      AND status IN ('detected', 'confirmed')
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    )

    try:
        rows = list(client.query(query, job_config=job_config).result())
        for row in rows:
            details = row.detection_details
            if isinstance(details, str):
                import json
                try:
                    details = json.loads(details)
                except (json.JSONDecodeError, ValueError, TypeError):
                    details = {}

            result['tracked_postponements'].append({
                'game_id': row.game_id,
                'original_date': str(row.original_date),
                'new_date': str(row.new_date) if row.new_date else None,
                'reason': row.reason,
                'status': row.status,
                'matchup': details.get('matchup', 'Unknown')
            })
    except Exception as e:
        logger.warning(f"Failed to check game_postponements table: {e}")

    # Check 2: Detect rescheduled games (same game_id on multiple dates)
    try:
        detector = PostponementDetector(sport="NBA", bq_client=client)
        anomalies = detector.detect_all(game_date)

        for anomaly in anomalies:
            if anomaly['type'] == 'GAME_RESCHEDULED':
                # Check if this is the ORIGINAL date (we don't want to skip the NEW date)
                original_date = anomaly.get('original_date')
                if original_date and str(game_date) == original_date:
                    result['detected_rescheduled'].append({
                        'game_id': anomaly['game_id'],
                        'teams': anomaly['teams'],
                        'original_date': original_date,
                        'new_date': anomaly.get('new_date'),
                        'all_dates': anomaly.get('all_dates', [])
                    })
    except Exception as e:
        logger.warning(f"PostponementDetector check failed: {e}")

    # Combine results
    result['total_count'] = len(result['tracked_postponements']) + len(result['detected_rescheduled'])
    result['has_postponements'] = result['total_count'] > 0

    return result


# =============================================================================
# VEGAS LINE SOURCE COVERAGE CHECK (Session 152)
# Checks feature store to determine which scrapers provided vegas data.
# Alerts when coverage is degraded (>50% of players have no line source).
# =============================================================================

def _check_vegas_source_coverage(game_date: date, dataset_prefix: str = '') -> dict:
    """Check vegas line source distribution in feature store for a game date.

    Returns dict with source counts and coverage status.
    Status is 'degraded' when >50% of players have no vegas line source,
    indicating a scraper failure rather than normal bench player gaps.
    """
    try:
        client = get_bq_client()
        dataset = f"{dataset_prefix}nba_predictions" if dataset_prefix else "nba_predictions"

        query = f"""
        SELECT
            COUNTIF(vegas_line_source = 'odds_api') as odds_api_only,
            COUNTIF(vegas_line_source = 'bettingpros') as bettingpros_only,
            COUNTIF(vegas_line_source = 'both') as both_sources,
            COUNTIF(vegas_line_source = 'none' OR vegas_line_source IS NULL) as no_source,
            COUNT(*) as total
        FROM `{PROJECT_ID}.{dataset}.ml_feature_store_v2`
        WHERE game_date = '{game_date}'
        """

        result = client.query(query).result()
        row = list(result)[0] if result.total_rows > 0 else None

        if not row or row.total == 0:
            return {'status': 'no_data', 'total': 0}

        total = row.total
        no_source = row.no_source
        coverage_pct = (total - no_source) * 100.0 / total

        coverage = {
            'odds_api_only': row.odds_api_only,
            'bettingpros_only': row.bettingpros_only,
            'both_sources': row.both_sources,
            'no_source': no_source,
            'total': total,
            'coverage_pct': coverage_pct,
            'status': 'degraded' if no_source / total > 0.5 else 'healthy',
        }
        return coverage

    except Exception as e:
        logger.warning(f"Vegas source coverage check failed: {e}")
        return {'status': 'error', 'error': str(e), 'total': 0}


def require_api_key(f):
    """
    Decorator to require API key authentication for endpoints.

    Checks X-API-Key header or 'key' query parameter.
    Also allows GCP service account identity tokens (Bearer auth).
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Allow GCP identity tokens (for Cloud Scheduler and other GCP services)
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            # Trust GCP identity tokens (Cloud Run validates these)
            return f(*args, **kwargs)

        # Check API key
        if not COORDINATOR_API_KEY:
            logger.error("COORDINATOR_API_KEY not configured - rejecting request", exc_info=True)
            return jsonify({'error': 'Server misconfigured'}), 500

        provided_key = request.headers.get('X-API-Key') or request.args.get('key')
        if not provided_key or not secrets.compare_digest(provided_key, COORDINATOR_API_KEY):
            logger.warning(f"Unauthorized request to {request.path}")
            return jsonify({'error': 'Unauthorized'}), 401

        return f(*args, **kwargs)
    return decorated

# Lazy-loaded components (initialized on first request to avoid cold start timeout)
_player_loader: Optional[PlayerLoader] = None
_pubsub_publisher: Optional['pubsub_v1.PublisherClient'] = None
_run_history: Optional[CoordinatorRunHistory] = None
_bq_client: Optional['bigquery.Client'] = None
_batch_consolidator: Optional[BatchConsolidator] = None
_batch_state_manager: Optional[BatchStateManager] = None
_instance_manager: Optional[CoordinatorInstanceManager] = None

# Multi-instance mode feature flag
ENABLE_MULTI_INSTANCE = os.environ.get('ENABLE_MULTI_INSTANCE', 'false').lower() == 'true'

# Global state (DEPRECATED - use BatchStateManager for persistent state)
# These remain for backwards compatibility but should not be used for new code
current_tracker: Optional[ProgressTracker] = None
current_batch_id: Optional[str] = None
current_correlation_id: Optional[str] = None  # Track correlation_id for this batch
current_game_date: Optional[date] = None  # Track game_date for run history

def get_player_loader() -> PlayerLoader:
    """Lazy-load PlayerLoader on first use"""
    global _player_loader
    if _player_loader is None:
        logger.info("Initializing PlayerLoader...")
        _player_loader = PlayerLoader(PROJECT_ID)
        logger.info("PlayerLoader initialized successfully")
    return _player_loader

def get_pubsub_publisher() -> 'pubsub_v1.PublisherClient':
    """Lazy-load Pub/Sub publisher on first use via pool"""
    from shared.clients import get_pubsub_publisher as get_pooled_publisher
    global _pubsub_publisher
    if _pubsub_publisher is None:
        logger.info("Initializing Pub/Sub publisher via pool...")
        _pubsub_publisher = get_pooled_publisher()
        logger.info("Pub/Sub publisher initialized successfully")
    return _pubsub_publisher


def get_run_history() -> CoordinatorRunHistory:
    """Lazy-load run history logger on first use"""
    global _run_history
    if _run_history is None:
        logger.info("Initializing CoordinatorRunHistory...")
        _run_history = CoordinatorRunHistory(project_id=PROJECT_ID)
        logger.info("CoordinatorRunHistory initialized successfully")
    return _run_history


def get_bq_client() -> 'bigquery.Client':
    """Lazy-load BigQuery client on first use via pool"""
    from shared.clients import get_bigquery_client
    global _bq_client
    if _bq_client is None:
        logger.info("Initializing BigQuery client via pool...")
        _bq_client = get_bigquery_client(PROJECT_ID)
        logger.info("BigQuery client initialized")
    return _bq_client


def get_batch_consolidator() -> BatchConsolidator:
    """Lazy-load batch consolidator on first use"""
    global _batch_consolidator
    if _batch_consolidator is None:
        logger.info("Initializing BatchConsolidator...")
        _batch_consolidator = BatchConsolidator(get_bq_client(), PROJECT_ID)
        logger.info("BatchConsolidator initialized")
    return _batch_consolidator


def get_state_manager() -> BatchStateManager:
    """Lazy-load batch state manager on first use"""
    global _batch_state_manager
    if _batch_state_manager is None:
        logger.info("Initializing BatchStateManager...")
        _batch_state_manager = get_batch_state_manager(PROJECT_ID)
        logger.info("BatchStateManager initialized")
    return _batch_state_manager


def get_coordinator_instance_manager() -> CoordinatorInstanceManager:
    """
    Lazy-load instance manager for multi-instance coordination.

    Only used when ENABLE_MULTI_INSTANCE=true.
    """
    global _instance_manager
    if _instance_manager is None:
        logger.info("Initializing CoordinatorInstanceManager...")
        _instance_manager = get_instance_manager(PROJECT_ID)
        _instance_manager.start()  # Start heartbeat thread
        logger.info(f"CoordinatorInstanceManager initialized: instance_id={_instance_manager.instance_id}")
    return _instance_manager


def cleanup_instance_manager():
    """Clean up instance manager on shutdown."""
    global _instance_manager
    if _instance_manager is not None:
        logger.info("Stopping CoordinatorInstanceManager...")
        _instance_manager.stop()
        _instance_manager = None
        logger.info("CoordinatorInstanceManager stopped")


# Register cleanup on app teardown
import atexit
atexit.register(cleanup_instance_manager)

logger.info(
    f"Coordinator initialized successfully "
    f"(multi_instance={ENABLE_MULTI_INSTANCE}, heavy clients will lazy-load on first request)"
)


@app.route('/', methods=['GET'])
def index():
    """Health check and info endpoint"""
    response = {
        'service': 'Phase 5 Prediction Coordinator',
        'status': 'healthy',
        'project_id': PROJECT_ID,
        'current_batch': current_batch_id,
        'batch_active': current_tracker is not None and not current_tracker.is_complete,
        'multi_instance_enabled': ENABLE_MULTI_INSTANCE
    }

    # Add instance info if multi-instance mode is enabled
    if ENABLE_MULTI_INSTANCE and _instance_manager is not None:
        response['instance_id'] = _instance_manager.instance_id

    return jsonify(response), 200


@app.route('/health/deep', methods=['GET'])
def health_check_deep():
    """
    Deep health check - validates critical functionality.

    Checks:
    1. Critical module imports (player_loader, data loaders)
    2. BigQuery connectivity AND pandas conversion
    3. Firestore connectivity (for distributed locks)
    4. Pub/Sub connectivity (can publish messages)

    Returns 200 if all checks pass, 503 if any fail.
    """
    checks = {}
    all_healthy = True

    try:
        # Check 1: Critical imports
        try:
            from player_loader import PlayerLoader
            from data_freshness_validator import DataFreshnessValidator
            checks['imports'] = {
                'status': 'ok',
                'modules': ['player_loader', 'data_freshness_validator']
            }
        except ImportError as e:
            checks['imports'] = {
                'status': 'failed',
                'error': str(e)
            }
            all_healthy = False

        # Check 2: BigQuery connectivity AND pandas conversion
        try:
            from shared.clients.bigquery_pool import get_bigquery_client
            client = get_bigquery_client()
            # Test actual pandas conversion (catches db-dtypes issues)
            query_job = client.query("SELECT 1 as test")
            df = query_job.to_dataframe()
            if len(df) != 1:
                raise ValueError("Query returned wrong number of rows")
            checks['bigquery'] = {
                'status': 'ok',
                'operations': ['query', 'to_dataframe'],
                'connection': 'verified'
            }
        except ImportError as e:
            checks['bigquery'] = {
                'status': 'failed',
                'error': f'Import error: {str(e)} (missing db-dtypes?)'
            }
            all_healthy = False
        except Exception as e:
            checks['bigquery'] = {
                'status': 'failed',
                'error': str(e)
            }
            all_healthy = False

        # Check 3: Firestore connectivity (for distributed locks)
        try:
            from google.cloud import firestore
            db = firestore.Client()
            # Test actual write operation (catches permission issues)
            test_ref = db.collection('_health_checks').document('test')
            test_ref.set({'timestamp': datetime.utcnow().isoformat()})
            test_ref.delete()
            checks['firestore'] = {
                'status': 'ok',
                'operations': ['write', 'delete'],
                'connection': 'verified'
            }
        except Exception as e:
            checks['firestore'] = {
                'status': 'failed',
                'error': str(e)
            }
            all_healthy = False

        # Check 4: Pub/Sub connectivity (can get client)
        try:
            from google.cloud import pubsub_v1
            publisher = pubsub_v1.PublisherClient()
            checks['pubsub'] = {
                'status': 'ok',
                'connection': 'verified'
            }
        except Exception as e:
            checks['pubsub'] = {
                'status': 'failed',
                'error': str(e)
            }
            all_healthy = False

        # Overall status
        status_code = 200 if all_healthy else 503
        response = {
            "status": "healthy" if all_healthy else "unhealthy",
            "service": "prediction_coordinator",
            "timestamp": datetime.utcnow().isoformat(),
            "checks": checks
        }

        return jsonify(response), status_code

    except Exception as e:
        logger.error(f"Deep health check failed: {e}", exc_info=True)
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 503


@app.route('/instances', methods=['GET'])
@require_api_key
def get_instances():
    """
    Get information about all coordinator instances.

    Only available when ENABLE_MULTI_INSTANCE=true.

    Returns:
        JSON with instance information and statistics
    """
    if not ENABLE_MULTI_INSTANCE:
        return jsonify({
            'status': 'disabled',
            'message': 'Multi-instance mode is not enabled. Set ENABLE_MULTI_INSTANCE=true.'
        }), 200

    try:
        instance_manager = get_coordinator_instance_manager()

        # Get active instances
        active_instances = instance_manager.get_active_instances()

        # Get batch processing stats
        state_manager = get_state_manager()
        batch_stats = state_manager.get_batch_processing_stats()

        return jsonify({
            'status': 'success',
            'this_instance': instance_manager.instance_id,
            'active_instances': [
                {
                    'instance_id': inst.instance_id,
                    'hostname': inst.hostname,
                    'pod_name': inst.pod_name,
                    'status': inst.status,
                    'last_heartbeat': inst.last_heartbeat.isoformat() if inst.last_heartbeat else None,
                    'is_alive': inst.is_alive()
                }
                for inst in active_instances
            ],
            'batch_stats': batch_stats
        }), 200

    except Exception as e:
        logger.error(f"Error getting instance info: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/instances/cleanup', methods=['POST'])
@require_api_key
def cleanup_instances():
    """
    Clean up dead instances and release their locks.

    Only available when ENABLE_MULTI_INSTANCE=true.

    Returns:
        JSON with cleanup results
    """
    if not ENABLE_MULTI_INSTANCE:
        return jsonify({
            'status': 'disabled',
            'message': 'Multi-instance mode is not enabled.'
        }), 200

    try:
        instance_manager = get_coordinator_instance_manager()
        cleaned_count = instance_manager.cleanup_dead_instances()

        return jsonify({
            'status': 'success',
            'instances_cleaned': cleaned_count
        }), 200

    except Exception as e:
        logger.error(f"Error cleaning up instances: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# Health check endpoint removed - now provided by shared health blueprint (see lines 161-173)
# The blueprint provides: /health (liveness), /ready (readiness), /health/deep (deep checks)


@app.route('/start', methods=['POST'])
@require_api_key
def start_prediction_batch():
    """
    Start a new prediction batch

    Triggered by Cloud Scheduler or manual HTTP request (or Phase 4 completion)

    Request body (optional):
    {
        "game_date": "2025-11-08",     # defaults to today
        "min_minutes": 15,              # minimum projected minutes
        "use_multiple_lines": false,    # test multiple betting lines
        "correlation_id": "abc-123",    # optional - for pipeline tracing
        "parent_processor": "MLFeatureStore",  # optional
        "dataset_prefix": "test",       # optional - for test dataset isolation
        "skip_completeness_check": false,  # skip data completeness validation
        "skip_postponement_check": false,  # skip postponed game detection
        "require_real_lines": false     # only predict for players WITH real lines (Session 74)
    }

    Returns:
        202 Accepted with batch info
        503 Service Unavailable if data incomplete (unless skip_completeness_check=true)
    """
    global current_tracker, current_batch_id, current_correlation_id, current_game_date

    try:
        # Parse request
        request_data = request.get_json() or {}

        # Get game date (default to today)
        # Supports: specific date (YYYY-MM-DD), "TODAY", "TOMORROW"
        game_date_str = request_data.get('game_date')
        if game_date_str:
            if game_date_str == "TODAY":
                from zoneinfo import ZoneInfo
                game_date = datetime.now(ZoneInfo('America/New_York')).date()
                logger.info(f"TODAY game_date resolved to: {game_date}")
            elif game_date_str == "TOMORROW":
                from zoneinfo import ZoneInfo
                from datetime import timedelta
                game_date = datetime.now(ZoneInfo('America/New_York')).date() + timedelta(days=1)
                logger.info(f"TOMORROW game_date resolved to: {game_date}")
            else:
                game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
        else:
            game_date = date.today()

        min_minutes = request_data.get('min_minutes', 15)
        # Use orchestration config for default (Issue 4: enable multiple lines by default)
        orch_config = get_orchestration_config()
        use_multiple_lines = request_data.get(
            'use_multiple_lines',
            orch_config.prediction_mode.use_multiple_lines_default
        )
        force = request_data.get('force', False)

        # Session 74: Real lines only mode for early predictions
        # When True, only generate predictions for players WITH real betting lines
        require_real_lines = request_data.get('require_real_lines', False)

        # Session 76: Track run mode for analysis (EARLY, OVERNIGHT, SAME_DAY, BACKFILL)
        # This enables studying early vs morning prediction performance
        prediction_run_mode = request_data.get('prediction_run_mode', 'OVERNIGHT')
        if require_real_lines:
            prediction_run_mode = 'EARLY'  # Override if require_real_lines is set

        # Extract correlation tracking (for pipeline tracing Phase 1→5)
        correlation_id = request_data.get('correlation_id') or str(uuid.uuid4())[:8]
        parent_processor = request_data.get('parent_processor')
        dataset_prefix = request_data.get('dataset_prefix', '')  # Optional test dataset prefix
        current_correlation_id = correlation_id

        mode_desc = "REAL_LINES_ONLY" if require_real_lines else "ALL_PLAYERS"
        logger.info(
            f"Starting prediction batch for {game_date} "
            f"(correlation_id={correlation_id}, parent={parent_processor}, "
            f"mode={mode_desc}, run_mode={prediction_run_mode}, "
            f"dataset_prefix={dataset_prefix or 'production'})"
        )

        # =========================================================================
        # DATA COMPLETENESS GATE (Jan 2026 Resilience)
        # Refuse to make predictions if historical data is incomplete.
        # This prevents silent failures where predictions are made with stale data.
        # =========================================================================
        skip_completeness_check = request_data.get('skip_completeness_check', False)
        if not skip_completeness_check:
            try:
                completeness_result = _check_data_completeness_for_predictions(game_date, dataset_prefix)
                if not completeness_result['is_complete']:
                    logger.error(
                        f"🚨 DATA COMPLETENESS GATE: Refusing to make predictions! "
                        f"Analytics coverage: {completeness_result['analytics_coverage_pct']:.1f}% "
                        f"(threshold: {completeness_result['threshold']}%)"
                    )
                    return jsonify({
                        'status': 'error',
                        'error': 'DATA_INCOMPLETE',
                        'message': (
                            f"Cannot make predictions - historical data is incomplete. "
                            f"Analytics coverage: {completeness_result['analytics_coverage_pct']:.1f}% "
                            f"(requires {completeness_result['threshold']}%). "
                            f"Run backfill or set skip_completeness_check=true to override."
                        ),
                        'details': completeness_result,
                        'game_date': str(game_date)
                    }), 503  # Service Unavailable
                else:
                    logger.info(
                        f"✅ Data completeness check passed: "
                        f"{completeness_result['analytics_coverage_pct']:.1f}% coverage"
                    )
            except Exception as e:
                # Don't block predictions if check fails - log and continue
                logger.warning(f"Data completeness check failed (continuing anyway): {e}")

        # =========================================================================
        # POSTPONEMENT CHECK (Jan 2026 Resilience)
        # Warn if games on the target date are known to be postponed.
        # Currently non-blocking (warning only) - can be made blocking later.
        # =========================================================================
        skip_postponement_check = request_data.get('skip_postponement_check', False)
        if not skip_postponement_check:
            try:
                postponement_result = _check_for_postponed_games(game_date)
                if postponement_result['has_postponements']:
                    # Log details of each postponed game
                    for pp in postponement_result['tracked_postponements']:
                        logger.warning(
                            f"⚠️ POSTPONED GAME (tracked): {pp['matchup']} on {pp['original_date']} "
                            f"→ {pp['new_date'] or 'TBD'} ({pp['reason']})"
                        )
                    for pp in postponement_result['detected_rescheduled']:
                        logger.warning(
                            f"⚠️ RESCHEDULED GAME (detected): {pp['teams']} appears on dates: "
                            f"{', '.join(pp['all_dates'])}"
                        )

                    logger.warning(
                        f"⚠️ POSTPONEMENT CHECK: Found {postponement_result['total_count']} "
                        f"postponed/rescheduled game(s) on {game_date}. "
                        f"Predictions will still be generated but may need invalidation. "
                        f"Set skip_postponement_check=true to suppress this warning."
                    )
                else:
                    logger.info(f"✅ Postponement check passed: no postponed games found for {game_date}")
            except Exception as e:
                # Don't block predictions if check fails - log and continue
                logger.warning(f"Postponement check failed (continuing anyway): {e}")

        # Check if batch already running
        # Session 159: Reduced stall threshold from 600s (10min) to 300s (5min)
        # to detect stuck batches faster and allow new runs sooner
        if current_tracker and not current_tracker.is_complete:
            is_stalled = current_tracker.is_stalled(stall_threshold_seconds=300)
            if not force and not is_stalled:
                logger.warning("Batch already in progress")
                return jsonify({
                    'status': 'already_running',
                    'batch_id': current_batch_id,
                    'progress': current_tracker.get_progress()
                }), 409  # Conflict
            else:
                # Allow override if forced or stalled
                reason = "forced" if force else "stalled"
                logger.warning(f"Overriding existing batch ({reason}), starting new batch")
                current_tracker.reset()
        
        # Create batch ID
        batch_id = f"batch_{game_date.isoformat()}_{int(time.time())}"
        current_batch_id = batch_id
        current_game_date = game_date

        # Get summary stats first
        summary_stats = get_player_loader().get_summary_stats(game_date, dataset_prefix=dataset_prefix)
        logger.info(f"Game date summary: {summary_stats}")

        # Create prediction requests
        # Session 74: Pass require_real_lines for early prediction mode
        requests = get_player_loader().create_prediction_requests(
            game_date=game_date,
            min_minutes=min_minutes,
            use_multiple_lines=use_multiple_lines,
            dataset_prefix=dataset_prefix,
            require_real_lines=require_real_lines
        )

        if not requests:
            logger.error(f"No prediction requests created for {game_date}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': f'No players found for {game_date}',
                'summary': summary_stats
            }), 404

        # Log line source statistics for monitoring/alerting (v3.9)
        try:
            line_stats = get_player_loader().get_line_source_stats()
            odds_api = line_stats.get('odds_api', 0)
            bettingpros = line_stats.get('bettingpros_fallback', 0)
            no_line = line_stats.get('no_line_data', 0)
            total = odds_api + bettingpros + no_line
            if total > 0:
                logger.info(f"📊 LINE_SOURCE_STATS: odds_api={odds_api} ({100*odds_api//total}%), bettingpros_fallback={bettingpros} ({100*bettingpros//total}%), no_line={no_line}")
                if bettingpros > odds_api:
                    logger.warning(f"⚠️ ODDS_API_DEGRADED: More lines from bettingpros ({bettingpros}) than odds_api ({odds_api}). Check odds_api scraper health.")
                if no_line > 0:
                    logger.warning(f"⚠️ MISSING_LINES: {no_line} players had no line from either source")
        except Exception as e:
            logger.debug(f"Could not log line source stats: {e}")

        # Session 175: Batch-level OddsAPI coverage diagnostic
        try:
            player_lookups = [r.get('player_lookup') for r in prediction_requests if r.get('player_lookup')]
            get_player_loader().diagnose_odds_api_coverage(game_date, player_lookups)
        except Exception as e:
            logger.debug(f"Could not run OddsAPI coverage diagnostic: {e}")

        # BATCH OPTIMIZATION: Pre-load historical games for all players (331x speedup!)
        # Instead of workers querying individually (225s total for sequential queries),
        # coordinator loads once (0.68s) and passes to workers via Pub/Sub
        # VERIFIED: Dec 31, 2025 - 118 players loaded in 0.68s, all workers used batch data
        # FIXED: Session 102 - Increased timeout from 30s to 120s to support 300-400 players

        try:
            player_lookups = [r.get('player_lookup') for r in requests if r.get('player_lookup')]
            if player_lookups:
                batch_start = time.time()
                # Use heartbeat logger to track long-running data load (5-min intervals)
                with HeartbeatLogger(f"Loading historical games for {len(player_lookups)} players", interval=300):
                    # Import PredictionDataLoader to use batch loading method
                    from predictions.worker.data_loaders import PredictionDataLoader

                    data_loader = PredictionDataLoader(project_id=PROJECT_ID, dataset_prefix=dataset_prefix)
                    batch_historical_games = data_loader.load_historical_games_batch(
                        player_lookups=player_lookups,
                        game_date=game_date,
                        lookback_days=90,
                        max_games=30
                    )

                batch_elapsed = time.time() - batch_start
                total_games = sum(len(games) for games in batch_historical_games.values())
                logger.info(
                    f"Batch loaded {total_games} historical games for "
                    f"{len(batch_historical_games)} players in {batch_elapsed:.2f}s"
                )
                logger.info(
                    f"✅ Batch loaded {total_games} historical games for {len(batch_historical_games)} players in {batch_elapsed:.2f}s",
                    extra={
                        'batch_load_time': batch_elapsed,
                        'player_count': len(batch_historical_games),
                        'games_loaded': total_games,
                        'avg_time_per_player': batch_elapsed / len(batch_historical_games) if batch_historical_games else 0
                    }
                )
            else:
                batch_historical_games = None
        except Exception as e:
            # Non-fatal: workers can fall back to individual queries
            logger.warning(f"Batch historical load failed (workers will use individual queries): {e}")
            batch_historical_games = None

        # Initialize progress tracker (DEPRECATED - keeping for backward compatibility)
        current_tracker = ProgressTracker(expected_players=len(requests))

        # Create batch state in Firestore (PERSISTENT - survives container restarts!)
        try:
            state_manager = get_state_manager()

            # Multi-instance mode: Use transaction to prevent duplicate batch creation
            if ENABLE_MULTI_INSTANCE:
                instance_manager = get_coordinator_instance_manager()
                instance_id = instance_manager.instance_id

                # Use transaction-based creation for safety
                batch_state = state_manager.create_batch_with_transaction(
                    batch_id=batch_id,
                    game_date=game_date.isoformat(),
                    expected_players=len(requests),
                    correlation_id=correlation_id,
                    dataset_prefix=dataset_prefix,
                    instance_id=instance_id
                )

                if batch_state is None:
                    # Batch already exists - another instance created it
                    logger.warning(
                        f"Batch {batch_id} already exists (created by another instance)"
                    )
                    return jsonify({
                        'status': 'already_exists',
                        'batch_id': batch_id,
                        'message': 'Batch was created by another coordinator instance'
                    }), 409

                # Claim the batch for this instance
                claimed = state_manager.claim_batch_for_processing(
                    batch_id=batch_id,
                    instance_id=instance_id
                )
                if not claimed:
                    logger.warning(f"Could not claim batch {batch_id} - may be processed by another instance")

                logger.info(
                    f"✅ Batch state persisted to Firestore: {batch_id} "
                    f"(expected={len(requests)} players, instance={instance_id})"
                )
            else:
                # Single-instance mode: Use simple create
                batch_state = state_manager.create_batch(
                    batch_id=batch_id,
                    game_date=game_date.isoformat(),
                    expected_players=len(requests),
                    correlation_id=correlation_id,
                    dataset_prefix=dataset_prefix
                )
                logger.info(
                    f"✅ Batch state persisted to Firestore: {batch_id} "
                    f"(expected={len(requests)} players)"
                )
        except Exception as e:
            # This is critical - without persistent state, consolidation won't work after restart
            logger.error(f"❌ CRITICAL: Failed to persist batch state to Firestore: {e}", exc_info=True)
            raise

        # Log batch start to processor_run_history for unified monitoring
        try:
            get_run_history().start_batch(
                batch_id=batch_id,
                game_date=game_date,
                correlation_id=correlation_id,
                parent_processor=parent_processor,
                trigger_source='api' if request_data else 'scheduler',
                expected_players=len(requests)
            )
        except Exception as e:
            # Don't fail the batch if run history logging fails
            logger.warning(f"Failed to log batch start (non-fatal): {e}")

        # =========================================================================
        # ANALYTICS QUALITY CHECK (Session 96)
        # Check analytics data quality (usage_rate, minutes) before making predictions
        # This catches issues like Feb 2 where usage_rate was 0% for all games
        # =========================================================================
        try:
            from predictions.coordinator.quality_gate import AnalyticsQualityGate

            analytics_gate = AnalyticsQualityGate(project_id=PROJECT_ID, dataset_prefix=dataset_prefix)

            # Check yesterday's data quality (the data we're using to make predictions)
            yesterday = game_date - timedelta(days=1)
            analytics_quality = analytics_gate.check_analytics_quality(yesterday)

            if not analytics_quality.passes_threshold:
                # Log critical warning but don't block (alerting is separate)
                logger.warning(
                    f"ANALYTICS_QUALITY_GATE: Data quality issues detected for {yesterday}: "
                    f"{analytics_quality.issues}"
                )
            else:
                logger.info(
                    f"ANALYTICS_QUALITY_GATE: Data quality OK for {yesterday}: "
                    f"usage_rate={analytics_quality.usage_rate_coverage_pct}%, "
                    f"minutes={analytics_quality.minutes_coverage_pct}%"
                )
        except Exception as e:
            # Don't block predictions if quality check fails
            logger.warning(f"Failed to check analytics quality (non-fatal): {e}")

        # =========================================================================
        # QUALITY GATE: "Predict Once, Never Replace" (Session 95, overhauled Session 139)
        # - Check for existing predictions (skip if already predicted)
        # - HARD FLOOR: Never predict with red alerts or matchup_quality < 50%
        # - Apply mode-based quality thresholds (FIRST=85%, RETRY=85%, FINAL_RETRY=80%, LAST_CALL=70%)
        # - Self-heal via QualityHealer when processors are missing
        # - Send PREDICTIONS_SKIPPED alert for hard-blocked players
        # =========================================================================
        viable_requests = []
        quality_gate_results = {}  # Maps player_lookup to QualityGateResult

        try:
            from predictions.coordinator.quality_gate import QualityGate, parse_prediction_mode, PredictionMode
            from predictions.coordinator.quality_alerts import (
                check_and_send_quality_alerts, log_quality_metrics,
                send_predictions_skipped_alert
            )

            # Parse prediction mode
            mode = parse_prediction_mode(prediction_run_mode)
            logger.info(f"QUALITY_GATE: Applying mode={mode.value} for {game_date}")

            # Session 139: BACKFILL mode validation
            # Session 171: Changed >= to > to allow same-day BACKFILL
            # (games may be Final on same day; only block future dates)
            if mode == PredictionMode.BACKFILL:
                from datetime import date as date_type
                if game_date > date_type.today():
                    logger.warning(
                        f"QUALITY_GATE: BACKFILL mode requires game_date <= today, "
                        f"got {game_date}. Switching to RETRY mode."
                    )
                    mode = PredictionMode.RETRY

            # Initialize quality gate
            quality_gate = QualityGate(project_id=PROJECT_ID, dataset_prefix=dataset_prefix)

            # Get player lookups from requests
            player_lookups = [r.get('player_lookup') for r in requests if r.get('player_lookup')]

            if player_lookups:
                # Apply quality gate
                gate_results, summary = quality_gate.apply_quality_gate(
                    game_date=game_date,
                    player_lookups=player_lookups,
                    mode=mode
                )

                # Session 139: Self-heal if players are hard-blocked and mode >= RETRY
                heal_attempted = False
                heal_success = False
                if (summary.players_hard_blocked > 0
                        and summary.missing_processors
                        and mode in (PredictionMode.RETRY, PredictionMode.FINAL_RETRY,
                                     PredictionMode.LAST_CALL)):
                    try:
                        from predictions.coordinator.quality_healer import QualityHealer
                        healer = QualityHealer(project_id=PROJECT_ID)
                        heal_result = healer.attempt_heal(
                            game_date=game_date,
                            batch_id=batch_id,
                            missing_processors=summary.missing_processors,
                        )
                        heal_attempted = heal_result.attempted
                        heal_success = heal_result.success

                        if heal_result.success:
                            logger.info(
                                f"QUALITY_HEALER: Heal succeeded, re-running quality gate "
                                f"for {summary.players_hard_blocked} blocked players"
                            )
                            # Re-run quality gate for previously blocked players only
                            blocked_lookups = [
                                r.player_lookup for r in gate_results
                                if r.hard_floor_blocked
                            ]
                            if blocked_lookups:
                                retry_results, retry_summary = quality_gate.apply_quality_gate(
                                    game_date=game_date,
                                    player_lookups=blocked_lookups,
                                    mode=mode
                                )
                                # Merge newly viable players into results
                                retry_map = {r.player_lookup: r for r in retry_results}
                                gate_results = [
                                    retry_map.get(r.player_lookup, r)
                                    if r.hard_floor_blocked else r
                                    for r in gate_results
                                ]
                                # Update summary with merged results
                                newly_viable = sum(1 for r in retry_results if r.should_predict)
                                summary.players_hard_blocked -= newly_viable
                                summary.players_to_predict += newly_viable
                                summary.players_skipped_low_quality -= newly_viable
                                logger.info(
                                    f"QUALITY_HEALER: {newly_viable}/{len(blocked_lookups)} "
                                    f"players now pass quality gate after healing"
                                )
                    except Exception as e:
                        logger.error(f"QUALITY_HEALER: Self-heal failed: {e}", exc_info=True)

                # Build lookup for results
                quality_gate_results = {r.player_lookup: r for r in gate_results}

                # Filter requests and add quality flags
                for pred_request in requests:
                    player_lookup = pred_request.get('player_lookup')
                    gate_result = quality_gate_results.get(player_lookup)

                    if gate_result and gate_result.should_predict:
                        # Add quality flags to request
                        pred_request['feature_quality_score'] = gate_result.feature_quality_score
                        pred_request['low_quality_flag'] = gate_result.low_quality_flag
                        pred_request['forced_prediction'] = gate_result.forced_prediction
                        pred_request['prediction_attempt'] = gate_result.prediction_attempt
                        viable_requests.append(pred_request)
                    elif gate_result:
                        logger.debug(
                            f"QUALITY_GATE: Skipping {player_lookup} - {gate_result.reason}"
                        )

                # Log quality metrics for monitoring
                log_quality_metrics(
                    game_date=game_date,
                    mode=mode.value,
                    summary_dict={
                        'total_players': summary.total_players,
                        'players_to_predict': summary.players_to_predict,
                        'players_skipped_existing': summary.players_skipped_existing,
                        'players_skipped_low_quality': summary.players_skipped_low_quality,
                        'players_forced': summary.players_forced,
                        'avg_quality_score': summary.avg_quality_score,
                        'quality_distribution': summary.quality_distribution,
                    }
                )

                # Check for and send quality alerts
                check_and_send_quality_alerts(
                    game_date=game_date,
                    mode=mode.value,
                    total_players=summary.total_players,
                    players_to_predict=summary.players_to_predict,
                    players_skipped_existing=summary.players_skipped_existing,
                    players_skipped_low_quality=summary.players_skipped_low_quality,
                    players_forced=summary.players_forced,
                    avg_quality_score=summary.avg_quality_score,
                    quality_distribution=summary.quality_distribution
                )

                # Session 139: Send PREDICTIONS_SKIPPED alert for hard-blocked players
                if summary.players_hard_blocked > 0:
                    blocked_results = [r for r in gate_results if r.hard_floor_blocked]
                    send_predictions_skipped_alert(
                        game_date=game_date,
                        mode=mode.value,
                        blocked_results=blocked_results,
                        missing_processors=summary.missing_processors,
                        heal_attempted=heal_attempted,
                        heal_success=heal_success,
                    )

                logger.info(
                    f"QUALITY_GATE: {len(viable_requests)}/{len(requests)} players will get predictions "
                    f"(skipped_existing={summary.players_skipped_existing}, "
                    f"skipped_low_quality={summary.players_skipped_low_quality}, "
                    f"hard_blocked={summary.players_hard_blocked})"
                )
            else:
                viable_requests = requests
        except Exception as e:
            # Non-fatal: If quality gate fails, fall back to publishing all requests
            logger.error(f"QUALITY_GATE: Failed to apply quality gate (publishing all): {e}", exc_info=True)
            viable_requests = requests

        # =========================================================================
        # VEGAS LINE SOURCE COVERAGE CHECK (Session 152)
        # Check feature store vegas source distribution before publishing.
        # Alert when >50% of players have no line source (scraper failure).
        # =========================================================================
        try:
            vegas_coverage = _check_vegas_source_coverage(game_date, dataset_prefix)
            if vegas_coverage.get('status') == 'degraded':
                from predictions.coordinator.quality_alerts import send_vegas_coverage_alert
                send_vegas_coverage_alert(game_date, prediction_run_mode, vegas_coverage)
            elif vegas_coverage.get('total', 0) > 0:
                logger.info(
                    f"VEGAS_COVERAGE: {vegas_coverage.get('coverage_pct', 0):.0f}% "
                    f"(both={vegas_coverage.get('both_sources', 0)}, "
                    f"oa={vegas_coverage.get('odds_api_only', 0)}, "
                    f"bp={vegas_coverage.get('bettingpros_only', 0)}, "
                    f"none={vegas_coverage.get('no_source', 0)})"
                )
        except Exception as e:
            logger.warning(f"Vegas coverage check failed (non-fatal): {e}")

        # Publish viable requests to Pub/Sub (with batch historical data if available)
        # Session 76: Include prediction_run_mode for traceability
        published_count = publish_prediction_requests(
            viable_requests, batch_id, batch_historical_games, dataset_prefix, prediction_run_mode
        )

        # Update expected_players to match actual published count (quality gate may filter most)
        actual_expected = published_count
        if actual_expected != len(requests):
            current_tracker.expected_players = actual_expected
            try:
                state_manager = get_state_manager()
                state_manager.update_expected_players(batch_id, actual_expected)
            except Exception as e:
                logger.warning(f"Failed to update expected_players in Firestore (non-fatal): {e}")

        # If nothing was published, mark batch complete immediately
        if published_count == 0:
            current_tracker.is_complete = True
            try:
                state_manager = get_state_manager()
                state_manager.mark_batch_complete(batch_id)
                logger.info(f"Batch {batch_id} marked complete (0 publishable players after quality gate)")
            except Exception as e:
                logger.warning(f"Failed to mark empty batch complete (non-fatal): {e}")

        logger.info(f"Published {published_count}/{len(requests)} prediction requests")

        # Return batch info
        return jsonify({
            'status': 'started',
            'batch_id': batch_id,
            'game_date': game_date.isoformat(),
            'total_requests': len(requests),
            'published': published_count,
            'summary': summary_stats,
            'monitor_url': f'/status?batch_id={batch_id}'
        }), 202  # Accepted
        
    except Exception as e:
        logger.error(f"Error starting batch: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


def check_and_mark_message_processed(message_id: str) -> bool:
    """
    Week 1: Check if Pub/Sub message already processed (idempotency).

    Uses Firestore deduplication collection with TTL to prevent
    duplicate processing of Pub/Sub messages.

    Args:
        message_id: Pub/Sub message ID

    Returns:
        True if message already processed (duplicate), False if new
    """
    if not ENABLE_IDEMPOTENCY_KEYS:
        return False  # Idempotency disabled, treat as new

    try:
        return _check_and_mark_message_processed_impl(message_id)
    except Exception as e:
        logger.error(f"Idempotency check failed for {message_id}: {e}", exc_info=True)
        # On error, treat as new to avoid blocking legitimate messages
        return False


@retry_firestore_transaction
def _check_and_mark_message_processed_impl(message_id: str) -> bool:
    """
    Internal implementation of idempotency check with Firestore retry.

    Uses @retry_firestore_transaction decorator for aggressive retry
    on transaction conflicts (5 attempts, 0.5s base delay).

    Args:
        message_id: Pub/Sub message ID

    Returns:
        True if message already processed (duplicate), False if new
    """
    # Lazy load Firestore via pool
    from google.cloud import firestore
    from shared.clients import get_firestore_client

    db = get_firestore_client(PROJECT_ID)
    dedup_ref = db.collection('pubsub_deduplication').document(message_id)

    # Atomic transaction to check-and-set
    transaction = db.transaction()

    @firestore.transactional
    def check_and_mark(transaction):
        doc = dedup_ref.get(transaction=transaction)

        if doc.exists:
            # Already processed - duplicate message
            logger.info(f"Duplicate message detected: {message_id}")
            return True

        # Mark as processed with TTL
        from datetime import datetime, timedelta, timezone
        expiry = datetime.now(timezone.utc) + timedelta(days=DEDUP_TTL_DAYS)

        transaction.set(dedup_ref, {
            'message_id': message_id,
            'processed_at': firestore.SERVER_TIMESTAMP,
            'expires_at': expiry  # For manual cleanup (Firestore TTL not available)
        })

        return False  # New message

    return check_and_mark(transaction)


@app.route('/regenerate-pubsub', methods=['POST'])
def regenerate_pubsub():
    """
    Handle Pub/Sub push messages for prediction regeneration.

    This endpoint receives messages from the 'nba-prediction-trigger' topic
    published by the BDB retry processor when late data arrives.

    Expected message format:
    {
        "game_date": "2026-01-17",
        "reason": "bdb_upgrade",
        "mode": "regenerate_with_supersede",
        "metadata": {
            "upgrade_from": "nbac_fallback",
            "upgrade_to": "bigdataball",
            ...
        }
    }
    """
    try:
        # Parse Pub/Sub message
        envelope = request.get_json()
        if not envelope:
            logger.error("No Pub/Sub message received")
            return ('Bad Request: no Pub/Sub message received', 400)

        # Decode message
        pubsub_message = envelope.get('message', {})
        if not pubsub_message:
            logger.error("No message field in envelope")
            return ('Bad Request: invalid Pub/Sub message format', 400)

        # Get message data
        message_data = base64.b64decode(pubsub_message['data']).decode('utf-8')
        request_data = json.loads(message_data)

        # Extract parameters
        game_date = request_data.get('game_date')
        reason = request_data.get('reason', 'feature_upgrade')
        mode = request_data.get('mode', 'regenerate_with_supersede')
        metadata = request_data.get('metadata', {})

        logger.info(
            f"Received Pub/Sub regeneration request: "
            f"date={game_date}, reason={reason}, mode={mode}"
        )

        # Validate mode
        if mode != 'regenerate_with_supersede':
            logger.error(f"Unsupported mode: {mode}")
            return ('Bad Request: unsupported mode', 400)

        # Call internal regeneration function
        result = _regenerate_with_supersede_internal(game_date, reason, metadata)

        # Return 200 to ack Pub/Sub message
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Pub/Sub regeneration handler failed: {e}", exc_info=True)
        # Return 200 to ack message even on error - we don't want infinite retries
        # The error is logged and tracked in the audit table
        return jsonify({
            'status': 'error',
            'error': str(e),
            'note': 'Message acknowledged to prevent retry loop'
        }), 200


@app.route('/regenerate-with-supersede', methods=['POST'])
@require_api_key
def regenerate_with_supersede():
    """
    HTTP endpoint for prediction regeneration (authenticated).

    Returns 202 Accepted immediately and processes regeneration in a background
    thread. Use /status to poll for completion.

    This endpoint is for direct HTTP calls requiring API key authentication.
    For Pub/Sub-triggered regeneration, use /regenerate-pubsub.

    Request body:
    {
        "game_date": "2026-01-17",
        "reason": "bdb_upgrade",
        "metadata": {
            "upgrade_from": "nbac_fallback",
            "upgrade_to": "bigdataball",
            ...
        }
    }

    Response (202 Accepted):
    {
        "status": "accepted",
        "game_date": "2026-01-17",
        "batch_id": "regen_2026-01-17_bdb_upgrade_1770685280",
        "note": "Regeneration started in background. Poll /status for progress."
    }
    """
    try:
        # Parse request
        data = request.json
        game_date = data['game_date']
        reason = data.get('reason', 'feature_upgrade')
        metadata = data.get('metadata', {})

        # Validate game_date format
        datetime.strptime(game_date, '%Y-%m-%d')

        # Generate batch_id upfront so we can return it immediately
        batch_id = f"regen_{game_date}_{reason}_{int(time.time())}"

        # Run regeneration in background thread (Session 176)
        def _run_regeneration():
            try:
                result = _regenerate_with_supersede_internal(game_date, reason, metadata)
                if result['status'] == 'success':
                    logger.info(
                        f"Background regeneration completed for {game_date}: "
                        f"{result.get('regenerated_count', 0)} predictions published"
                    )
                else:
                    logger.error(
                        f"Background regeneration failed for {game_date}: "
                        f"{result.get('error', 'unknown')}"
                    )
            except Exception as e:
                logger.error(f"Background regeneration crashed for {game_date}: {e}", exc_info=True)

        thread = threading.Thread(target=_run_regeneration, daemon=True)
        thread.start()

        logger.info(f"Regeneration accepted for {game_date}, reason={reason}, processing in background")

        return jsonify({
            'status': 'accepted',
            'game_date': game_date,
            'batch_id': batch_id,
            'note': 'Regeneration started in background. Poll /status for progress.'
        }), 202

    except KeyError:
        return jsonify({
            'status': 'error',
            'error': 'Missing required field: game_date'
        }), 400
    except ValueError as e:
        return jsonify({
            'status': 'error',
            'error': f'Invalid game_date format (expected YYYY-MM-DD): {e}'
        }), 400
    except Exception as e:
        logger.error(f"Prediction regeneration failed: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/check-lines', methods=['POST'])
@require_api_key
def check_lines():
    """
    Session 152: Hourly line check — detect new/moved lines, trigger targeted re-prediction.

    Called by Cloud Scheduler every hour 8 AM – 6 PM ET. Detects:
    1. Players predicted WITHOUT lines who now have lines available
    2. Players whose lines moved >= threshold since prediction was made

    For affected players: supersedes old predictions, generates new ones.
    Phase 6 re-export triggers automatically via existing event-driven flow.

    Request body:
    {
        "game_date": "2026-02-07",         // optional, defaults to TODAY (ET)
        "line_change_threshold": 1.0,      // optional, min line move to trigger
        "dry_run": false                   // optional, detect only, don't re-predict
    }
    """
    try:
        from zoneinfo import ZoneInfo
        from predictions.coordinator.quality_alerts import send_line_check_alert

        data = request.get_json() or {}

        # Resolve game date
        game_date_str = data.get('game_date')
        if game_date_str and game_date_str != 'TODAY':
            game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
        else:
            game_date = datetime.now(ZoneInfo('America/New_York')).date()

        line_change_threshold = data.get('line_change_threshold', 1.0)
        dry_run = data.get('dry_run', False)

        logger.info(
            f"Line check starting for {game_date} "
            f"(threshold={line_change_threshold}, dry_run={dry_run})"
        )

        # Check if games exist and haven't all started
        from google.cloud import bigquery as bq
        client = get_bq_client()
        games_query = f"""
        SELECT
            COUNT(*) as total_games,
            COUNTIF(game_status = 1) as scheduled_games
        FROM `{PROJECT_ID}.nba_reference.nba_schedule`
        WHERE game_date = @game_date
        """
        job_config = bq.QueryJobConfig(
            query_parameters=[
                bq.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )
        games_result = list(client.query(games_query, job_config=job_config).result())
        total_games = games_result[0].total_games if games_result else 0
        scheduled_games = games_result[0].scheduled_games if games_result else 0

        if total_games == 0:
            logger.info(f"Line check: no games on {game_date}")
            return jsonify({'status': 'no_games', 'game_date': str(game_date)}), 200

        if scheduled_games == 0:
            logger.info(f"Line check: all {total_games} games already started/finished on {game_date}")
            return jsonify({
                'status': 'all_games_started',
                'game_date': str(game_date),
                'total_games': total_games
            }), 200

        # Detect players needing re-prediction
        player_loader = get_player_loader()

        new_line_players = player_loader.get_players_with_new_lines(game_date)
        stale_line_players = player_loader.get_players_with_stale_predictions(
            game_date, line_change_threshold=line_change_threshold
        )

        # Union + dedup
        all_affected = sorted(set(new_line_players + stale_line_players))

        if not all_affected:
            logger.info(f"Line check: no changes detected for {game_date}")
            return jsonify({
                'status': 'no_changes',
                'game_date': str(game_date),
                'new_lines': 0,
                'line_moves': 0
            }), 200

        logger.info(
            f"Line check: {len(all_affected)} players affected "
            f"({len(new_line_players)} new lines, {len(stale_line_players)} line moves)"
        )

        if dry_run:
            send_line_check_alert(
                game_date=game_date,
                new_line_players=new_line_players,
                stale_line_players=stale_line_players,
                batch_id=None,
                dry_run=True,
            )
            return jsonify({
                'status': 'dry_run',
                'game_date': str(game_date),
                'new_lines': len(new_line_players),
                'line_moves': len(stale_line_players),
                'total_affected': len(all_affected),
                'affected_players': all_affected[:50],
            }), 200

        # Supersede old predictions for affected players
        superseded_count = _mark_predictions_superseded_for_players(
            game_date=str(game_date),
            player_lookups=all_affected,
            reason='line_check',
            metadata={
                'new_line_count': len(new_line_players),
                'stale_line_count': len(stale_line_players),
                'threshold': line_change_threshold,
            }
        )

        # Generate new predictions for affected players
        gen_result = _generate_predictions_for_players(
            game_date=str(game_date),
            player_lookups=all_affected,
            reason='line_check',
            metadata={
                'new_line_count': len(new_line_players),
                'stale_line_count': len(stale_line_players),
                'threshold': line_change_threshold,
            }
        )

        batch_id = gen_result.get('batch_id')

        # Send Slack notification
        send_line_check_alert(
            game_date=game_date,
            new_line_players=new_line_players,
            stale_line_players=stale_line_players,
            batch_id=batch_id,
            dry_run=False,
        )

        return jsonify({
            'status': 'success',
            'game_date': str(game_date),
            'new_lines': len(new_line_players),
            'line_moves': len(stale_line_players),
            'total_affected': len(all_affected),
            'superseded_count': superseded_count,
            'requests_published': gen_result.get('requests_published', 0),
            'batch_id': batch_id,
        }), 200

    except Exception as e:
        logger.error(f"Line check failed: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/morning-summary', methods=['POST'])
@require_api_key
def morning_summary():
    """
    Session 152: Send morning prediction + line coverage summary to Slack.

    Called by Cloud Scheduler at 7:30 AM ET daily. Queries today's predictions
    and line source stats, then sends a formatted Slack message.

    Request body:
    {
        "game_date": "2026-02-07"  // optional, defaults to TODAY (ET)
    }
    """
    try:
        from zoneinfo import ZoneInfo
        from google.cloud import bigquery as bq
        from predictions.coordinator.quality_alerts import send_morning_line_summary

        data = request.get_json() or {}

        game_date_str = data.get('game_date')
        if game_date_str and game_date_str != 'TODAY':
            game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
        else:
            game_date = datetime.now(ZoneInfo('America/New_York')).date()

        logger.info(f"Morning summary starting for {game_date}")

        client = get_bq_client()

        # Query prediction stats
        pred_query = f"""
        SELECT
            COUNT(*) as total,
            COUNTIF(current_points_line IS NOT NULL) as with_lines,
            COUNTIF(current_points_line IS NULL) as without_lines,
            COUNTIF(is_actionable) as actionable,
            COUNTIF(ABS(predicted_points - current_points_line) >= 3) as medium_edge,
            COUNTIF(ABS(predicted_points - current_points_line) >= 5) as high_edge,
            COUNTIF(vegas_line_source = 'odds_api') as vls_odds_api,
            COUNTIF(vegas_line_source = 'bettingpros') as vls_bettingpros,
            COUNTIF(vegas_line_source = 'both') as vls_both,
            COUNTIF(vegas_line_source = 'none' OR vegas_line_source IS NULL) as vls_none
        FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        WHERE game_date = @game_date
          AND is_active = TRUE
          AND system_id = 'catboost_v9'
        """

        job_config = bq.QueryJobConfig(
            query_parameters=[
                bq.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )
        pred_rows = list(client.query(pred_query, job_config=job_config).result())

        if not pred_rows or pred_rows[0].total == 0:
            logger.info(f"Morning summary: no predictions for {game_date}")
            return jsonify({
                'status': 'no_predictions',
                'game_date': str(game_date)
            }), 200

        pr = pred_rows[0]

        # Query feature quality stats
        quality_query = f"""
        SELECT
            AVG(feature_quality_score) as avg_quality,
            COUNTIF(NOT is_quality_ready) as blocked_count
        FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
        WHERE game_date = @game_date
        """
        quality_rows = list(client.query(quality_query, job_config=job_config).result())
        qr = quality_rows[0] if quality_rows else None

        # Query subset pick counts
        subset_query = f"""
        SELECT
            d.subset_name,
            COUNT(DISTINCT p.player_lookup) as pick_count
        FROM `{PROJECT_ID}.nba_predictions.dynamic_subset_definitions` d
        CROSS JOIN `{PROJECT_ID}.nba_predictions.player_prop_predictions` p
        WHERE d.is_active = TRUE
          AND d.system_id = 'catboost_v9'
          AND p.game_date = @game_date
          AND p.is_active = TRUE
          AND p.system_id = 'catboost_v9'
          AND p.recommendation IN ('OVER', 'UNDER')
          AND p.current_points_line IS NOT NULL
          AND ABS(p.predicted_points - p.current_points_line) >= COALESCE(d.min_edge, 0)
          AND p.confidence_score >= COALESCE(d.min_confidence, 0)
        GROUP BY d.subset_name
        ORDER BY pick_count DESC
        """
        subset_rows = list(client.query(subset_query, job_config=job_config).result())
        subset_stats = {row.subset_name: row.pick_count for row in subset_rows}

        # Send Slack summary
        send_morning_line_summary(
            game_date=game_date,
            prediction_stats={
                'total': pr.total,
                'with_lines': pr.with_lines,
                'without_lines': pr.without_lines,
                'actionable': pr.actionable,
                'medium_edge': pr.medium_edge,
                'high_edge': pr.high_edge,
            },
            line_source_stats={
                'odds_api': pr.vls_odds_api,
                'bettingpros': pr.vls_bettingpros,
                'both': pr.vls_both,
                'none': pr.vls_none,
            },
            subset_stats=subset_stats,
            feature_stats={
                'avg_quality': float(qr.avg_quality or 0) if qr else 0,
                'blocked_count': int(qr.blocked_count or 0) if qr else 0,
            },
        )

        return jsonify({
            'status': 'success',
            'game_date': str(game_date),
            'total_predictions': pr.total,
            'with_lines': pr.with_lines,
            'without_lines': pr.without_lines,
        }), 200

    except Exception as e:
        logger.error(f"Morning summary failed: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


def _regenerate_with_supersede_internal(
    game_date: str,
    reason: str,
    metadata: dict
) -> dict:
    """
    Internal function to regenerate predictions with superseding.

    Called by both HTTP endpoint and Pub/Sub handler.

    Args:
        game_date: Date to regenerate predictions for (YYYY-MM-DD string)
        reason: Reason for regeneration (e.g., 'bdb_upgrade')
        metadata: Context metadata (upgrade info, etc.)

    Returns:
        dict with status, counts, and timing information
    """
    import time
    start_time = time.time()

    try:
        logger.info(f"Starting prediction regeneration for {game_date}, reason: {reason}")

        # Step 1: Mark existing predictions as superseded
        superseded_count = _mark_predictions_superseded(game_date, reason, metadata)
        logger.info(f"Marked {superseded_count} predictions as superseded")

        # Step 2: Generate new predictions
        regeneration_result = _generate_predictions_for_date(game_date, reason, metadata)
        regenerated_count = regeneration_result.get('requests_published', 0)

        if regeneration_result.get('status') == 'error':
            logger.error(f"Prediction generation failed: {regeneration_result.get('error')}")
            # Still log to audit even if generation failed
            _log_prediction_regeneration(game_date, reason, metadata, {
                'superseded_count': superseded_count,
                'regenerated_count': 0,
                'status': 'failed',
                'error': regeneration_result.get('error')
            })
            return {
                'status': 'error',
                'game_date': game_date,
                'superseded_count': superseded_count,
                'error': regeneration_result.get('error'),
                'processing_time_seconds': round(time.time() - start_time, 2)
            }

        logger.info(f"Published {regenerated_count} prediction requests for {game_date}")

        # Step 3: Track in audit log
        _log_prediction_regeneration(game_date, reason, metadata, {
            'superseded_count': superseded_count,
            'regenerated_count': regenerated_count,
            'status': 'success',
            'batch_id': regeneration_result.get('batch_id')
        })

        processing_time = time.time() - start_time

        return {
            'status': 'success',
            'game_date': game_date,
            'superseded_count': superseded_count,
            'regenerated_count': regenerated_count,
            'batch_id': regeneration_result.get('batch_id'),
            'processing_time_seconds': round(processing_time, 2),
            'note': f'Predictions marked as superseded and {regenerated_count} new prediction requests published to workers.'
        }

    except Exception as e:
        logger.error(f"Prediction regeneration failed: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'processing_time_seconds': round(time.time() - start_time, 2)
        }


def _mark_predictions_superseded(
    game_date: str,
    reason: str,
    metadata: dict
) -> int:
    """
    Mark existing predictions for a date as superseded.

    Args:
        game_date: Date of predictions to supersede
        reason: Reason for superseding (e.g., 'bdb_upgrade')
        metadata: Additional context

    Returns:
        Number of predictions marked as superseded
    """
    import json as json_module
    from google.cloud import bigquery

    client = bigquery.Client()
    project_id = client.project

    # Query to update existing predictions
    query = f"""
    UPDATE `{project_id}.nba_predictions.player_prop_predictions`
    SET
        superseded = TRUE,
        superseded_at = CURRENT_TIMESTAMP(),
        superseded_reason = @reason,
        superseded_metadata = PARSE_JSON(@metadata_json),
        is_active = FALSE
    WHERE game_date = @game_date
      AND (superseded IS NULL OR superseded = FALSE)
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "STRING", game_date),
            bigquery.ScalarQueryParameter("reason", "STRING", reason),
            bigquery.ScalarQueryParameter("metadata_json", "STRING", json_module.dumps(metadata))
        ]
    )

    query_job = client.query(query, job_config=job_config)
    result = query_job.result()

    # Get count of updated rows
    superseded_count = result.num_dml_affected_rows if hasattr(result, 'num_dml_affected_rows') else 0

    logger.info(f"Marked {superseded_count} predictions as superseded for {game_date}")
    return superseded_count


def _mark_predictions_superseded_for_players(
    game_date: str,
    player_lookups: List[str],
    reason: str,
    metadata: dict
) -> int:
    """
    Session 152: Mark existing predictions as superseded for SPECIFIC players only.

    Same as _mark_predictions_superseded() but scoped to a list of players
    instead of the entire date. Used by /check-lines for targeted re-prediction.

    Args:
        game_date: Date of predictions to supersede
        player_lookups: List of player_lookups to supersede
        reason: Reason for superseding (e.g., 'line_check_new_lines')
        metadata: Additional context

    Returns:
        Number of predictions marked as superseded
    """
    import json as json_module
    from google.cloud import bigquery

    if not player_lookups:
        return 0

    client = bigquery.Client()
    project_id = client.project

    query = f"""
    UPDATE `{project_id}.nba_predictions.player_prop_predictions`
    SET
        superseded = TRUE,
        superseded_at = CURRENT_TIMESTAMP(),
        superseded_reason = @reason,
        superseded_metadata = PARSE_JSON(@metadata_json),
        is_active = FALSE
    WHERE game_date = @game_date
      AND player_lookup IN UNNEST(@player_lookups)
      AND (superseded IS NULL OR superseded = FALSE)
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "STRING", game_date),
            bigquery.ScalarQueryParameter("reason", "STRING", reason),
            bigquery.ScalarQueryParameter("metadata_json", "STRING", json_module.dumps(metadata)),
            bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
        ]
    )

    query_job = client.query(query, job_config=job_config)
    result = query_job.result()

    superseded_count = result.num_dml_affected_rows if hasattr(result, 'num_dml_affected_rows') else 0

    logger.info(
        f"Marked {superseded_count} predictions as superseded for "
        f"{len(player_lookups)} players on {game_date} (reason={reason})"
    )
    return superseded_count


def _log_prediction_regeneration(
    game_date: str,
    reason: str,
    metadata: dict,
    results: dict
) -> None:
    """
    Log prediction regeneration event to audit table.

    Args:
        game_date: Date regenerated
        reason: Reason for regeneration
        metadata: Context metadata
        results: Regeneration results (counts, etc.)
    """
    import json as json_module
    from google.cloud import bigquery
    from datetime import datetime, timezone

    client = bigquery.Client()
    project_id = client.project

    # Use streaming inserts for JSON fields (avoids schema conversion issues)
    table_id = f"{project_id}.nba_predictions.prediction_regeneration_audit"

    audit_record = {
        'regeneration_timestamp': datetime.now(timezone.utc),
        'game_date': game_date,
        'reason': reason,
        'metadata': json_module.dumps(metadata),  # JSON field needs string for insert_rows
        'superseded_count': results.get('superseded_count', 0),
        'regenerated_count': results.get('regenerated_count', 0),
        'triggered_by': 'coordinator_endpoint'
    }

    # Insert audit record
    try:
        # Use insert_rows_json instead of load_table_from_json for JSON fields
        errors = client.insert_rows_json(table_id, [audit_record])

        if errors:
            logger.warning(f"Errors inserting audit record: {errors}")
        else:
            logger.info(f"Logged regeneration event to audit table")

    except Exception as e:
        logger.warning(f"Failed to log audit record: {e}")
        # Don't fail overall process if audit logging fails


def _generate_predictions_for_date(
    game_date: str,
    reason: str,
    metadata: dict
) -> dict:
    """
    Generate new predictions for a specific date.

    This function reuses the existing prediction infrastructure to regenerate
    predictions when upstream features improve (e.g., BDB data arrives).

    Args:
        game_date: Date to generate predictions for (YYYY-MM-DD string)
        reason: Reason for regeneration (e.g., 'bdb_upgrade')
        metadata: Context metadata (upgrade info, etc.)

    Returns:
        dict with:
            - status: 'success' or 'error'
            - requests_published: Number of prediction requests published
            - batch_id: Batch identifier for tracking
            - error: Error message if status=='error'
    """
    try:
        # Convert game_date string to date object
        game_date_obj = datetime.strptime(game_date, '%Y-%m-%d').date()
        logger.info(f"Generating predictions for {game_date_obj}")

        # Create batch ID for tracking
        batch_id = f"regen_{game_date}_{reason}_{int(time.time())}"

        # Get players with games on this date
        # Reuse existing PlayerLoader infrastructure
        player_loader = get_player_loader()

        # Get prediction requests for all players on this date
        # Use min_minutes=15 and use_multiple_lines=False for regeneration
        # (single line regeneration is faster and sufficient for upgrades)
        requests = player_loader.create_prediction_requests(
            game_date=game_date_obj,
            min_minutes=15,
            use_multiple_lines=False,
            dataset_prefix=''  # Production dataset
        )

        if not requests:
            logger.warning(f"No players found for {game_date} - possibly no games scheduled")
            return {
                'status': 'success',
                'requests_published': 0,
                'batch_id': batch_id,
                'note': 'No players found for this date'
            }

        logger.info(f"Found {len(requests)} players with games on {game_date}")

        # Create batch state in Firestore (required for worker completion tracking)
        try:
            state_manager = get_state_manager()
            correlation_id = f"regen_{reason}"

            # Multi-instance mode: Use transaction to prevent duplicate batch creation
            if ENABLE_MULTI_INSTANCE:
                instance_manager = get_coordinator_instance_manager()
                instance_id = instance_manager.instance_id

                # Use transaction-based creation for safety
                batch_state = state_manager.create_batch_with_transaction(
                    batch_id=batch_id,
                    game_date=game_date,
                    expected_players=len(requests),
                    correlation_id=correlation_id,
                    dataset_prefix='',
                    instance_id=instance_id
                )

                if batch_state is None:
                    # Batch already exists - another instance created it
                    logger.warning(
                        f"Regeneration batch {batch_id} already exists (created by another instance)"
                    )
                    return {
                        'status': 'already_exists',
                        'batch_id': batch_id,
                        'message': 'Batch was created by another coordinator instance'
                    }

                # Claim the batch for this instance
                claimed = state_manager.claim_batch_for_processing(
                    batch_id=batch_id,
                    instance_id=instance_id
                )
                if not claimed:
                    logger.warning(f"Could not claim batch {batch_id} - may be processed by another instance")

                logger.info(
                    f"✅ Regeneration batch state persisted to Firestore: {batch_id} "
                    f"(expected={len(requests)} players, instance={instance_id})"
                )
            else:
                # Single-instance mode: Use simple create
                batch_state = state_manager.create_batch(
                    batch_id=batch_id,
                    game_date=game_date,
                    expected_players=len(requests),
                    correlation_id=correlation_id,
                    dataset_prefix=''
                )
                logger.info(
                    f"✅ Regeneration batch state persisted to Firestore: {batch_id} "
                    f"(expected={len(requests)} players)"
                )
        except Exception as e:
            # This is critical - without persistent state, consolidation won't work
            logger.error(f"❌ CRITICAL: Failed to persist regeneration batch state to Firestore: {e}", exc_info=True)
            return {
                'status': 'error',
                'requests_published': 0,
                'batch_id': batch_id,
                'error': f'Failed to create batch state: {str(e)}'
            }

        # BATCH OPTIMIZATION: Pre-load historical games for all players
        # This provides massive speedup (331x) - see coordinator.py:857
        try:
            player_lookups = [r.get('player_lookup') for r in requests if r.get('player_lookup')]
            if player_lookups:
                batch_start = time.time()
                logger.info(f"Batch loading historical games for {len(player_lookups)} players")

                # Import PredictionDataLoader to use batch loading method
                from predictions.worker.data_loaders import PredictionDataLoader
                data_loader = PredictionDataLoader(project_id=PROJECT_ID, dataset_prefix='')

                batch_historical_games = data_loader.load_historical_games_batch(
                    player_lookups=player_lookups,
                    game_date=game_date_obj,
                    lookback_days=90,
                    max_games=30
                )

                batch_elapsed = time.time() - batch_start
                total_games = sum(len(games) for games in batch_historical_games.values())
                logger.info(
                    f"Batch loaded {total_games} historical games for "
                    f"{len(batch_historical_games)} players in {batch_elapsed:.2f}s"
                )
            else:
                batch_historical_games = None
                logger.warning("No valid player lookups found for batch loading")

        except Exception as e:
            # Non-fatal: workers can fall back to individual queries
            logger.warning(f"Batch historical load failed (workers will use individual queries): {e}")
            batch_historical_games = None

        # Publish prediction requests to Pub/Sub
        # Workers will receive these and generate predictions asynchronously
        published_count = publish_prediction_requests(
            requests=requests,
            batch_id=batch_id,
            batch_historical_games=batch_historical_games,
            dataset_prefix=''  # Production dataset
        )

        if published_count == 0:
            return {
                'status': 'error',
                'requests_published': 0,
                'batch_id': batch_id,
                'error': 'Failed to publish any prediction requests'
            }

        logger.info(
            f"Successfully published {published_count}/{len(requests)} prediction requests "
            f"for {game_date} (batch_id: {batch_id})"
        )

        return {
            'status': 'success',
            'requests_published': published_count,
            'batch_id': batch_id,
            'players_found': len(requests),
            'reason': reason
        }

    except Exception as e:
        logger.error(f"Prediction generation failed for {game_date}: {e}", exc_info=True)
        return {
            'status': 'error',
            'requests_published': 0,
            'error': str(e)
        }


def _generate_predictions_for_players(
    game_date: str,
    player_lookups: List[str],
    reason: str,
    metadata: dict
) -> dict:
    """
    Session 152: Generate predictions for SPECIFIC players only.

    Reuses the existing prediction infrastructure but filters to only the
    target players. Used by /check-lines for targeted re-prediction after
    line changes or new line arrivals.

    Args:
        game_date: Date to generate predictions for (YYYY-MM-DD string)
        player_lookups: List of player_lookups to generate predictions for
        reason: Reason for generation (e.g., 'line_check')
        metadata: Context metadata

    Returns:
        dict with status, counts, batch_id
    """
    try:
        game_date_obj = datetime.strptime(game_date, '%Y-%m-%d').date()
        target_set = set(player_lookups)

        batch_id = f"linecheck_{game_date}_{int(time.time())}"
        logger.info(
            f"Generating targeted predictions for {len(target_set)} players "
            f"on {game_date} (batch_id={batch_id}, reason={reason})"
        )

        # Get ALL prediction requests for this date, then filter to targets
        player_loader = get_player_loader()
        all_requests = player_loader.create_prediction_requests(
            game_date=game_date_obj,
            min_minutes=15,
            use_multiple_lines=False,
            dataset_prefix=''
        )

        # Filter to target players only
        requests = [r for r in all_requests if r.get('player_lookup') in target_set]

        if not requests:
            logger.warning(
                f"No matching prediction requests for {len(target_set)} target players on {game_date}"
            )
            return {
                'status': 'success',
                'requests_published': 0,
                'batch_id': batch_id,
                'note': 'No matching players found in prediction requests'
            }

        logger.info(f"Filtered to {len(requests)}/{len(all_requests)} requests for target players")

        # Create batch state in Firestore
        try:
            state_manager = get_state_manager()
            correlation_id = f"linecheck_{reason}"

            if ENABLE_MULTI_INSTANCE:
                instance_manager = get_coordinator_instance_manager()
                instance_id = instance_manager.instance_id

                batch_state = state_manager.create_batch_with_transaction(
                    batch_id=batch_id,
                    game_date=game_date,
                    expected_players=len(requests),
                    correlation_id=correlation_id,
                    dataset_prefix='',
                    instance_id=instance_id
                )

                if batch_state is None:
                    logger.warning(f"Line check batch {batch_id} already exists")
                    return {
                        'status': 'already_exists',
                        'batch_id': batch_id,
                        'message': 'Batch was created by another coordinator instance'
                    }

                state_manager.claim_batch_for_processing(
                    batch_id=batch_id,
                    instance_id=instance_id
                )
            else:
                state_manager.create_batch(
                    batch_id=batch_id,
                    game_date=game_date,
                    expected_players=len(requests),
                    correlation_id=correlation_id,
                    dataset_prefix=''
                )

            logger.info(f"Line check batch state created: {batch_id} ({len(requests)} players)")

        except Exception as e:
            logger.error(f"Failed to create line check batch state: {e}", exc_info=True)
            return {
                'status': 'error',
                'requests_published': 0,
                'batch_id': batch_id,
                'error': f'Failed to create batch state: {str(e)}'
            }

        # Batch-load historical games for target players
        batch_historical_games = None
        try:
            batch_start = time.time()
            from predictions.worker.data_loaders import PredictionDataLoader
            data_loader = PredictionDataLoader(project_id=PROJECT_ID, dataset_prefix='')

            batch_historical_games = data_loader.load_historical_games_batch(
                player_lookups=list(target_set),
                game_date=game_date_obj,
                lookback_days=90,
                max_games=30
            )
            batch_elapsed = time.time() - batch_start
            total_games = sum(len(games) for games in batch_historical_games.values())
            logger.info(
                f"Batch loaded {total_games} historical games for "
                f"{len(batch_historical_games)} target players in {batch_elapsed:.2f}s"
            )
        except Exception as e:
            logger.warning(f"Batch historical load failed for line check: {e}")

        # Publish prediction requests
        published_count = publish_prediction_requests(
            requests=requests,
            batch_id=batch_id,
            batch_historical_games=batch_historical_games,
            dataset_prefix='',
            prediction_run_mode='LINE_CHECK'
        )

        if published_count == 0:
            return {
                'status': 'error',
                'requests_published': 0,
                'batch_id': batch_id,
                'error': 'Failed to publish any prediction requests'
            }

        logger.info(
            f"Line check: published {published_count}/{len(requests)} requests "
            f"for {game_date} (batch_id={batch_id})"
        )

        return {
            'status': 'success',
            'requests_published': published_count,
            'batch_id': batch_id,
            'players_found': len(requests),
            'reason': reason
        }

    except Exception as e:
        logger.error(f"Targeted prediction generation failed for {game_date}: {e}", exc_info=True)
        return {
            'status': 'error',
            'requests_published': 0,
            'error': str(e)
        }


@app.route('/complete', methods=['POST'])
@require_api_key
def handle_completion_event():
    """
    Handle prediction-ready events from workers

    Week 1 Update: Added idempotency checking to prevent duplicate processing.

    This endpoint is called by Pub/Sub push subscription when
    a worker completes predictions for a player.

    Message format:
    {
        'player_lookup': 'lebron-james',
        'game_date': '2025-11-08',
        'predictions_generated': 5,
        'timestamp': '2025-11-08T10:30:00.123Z'
    }
    """
    global current_tracker

    try:
        # Parse Pub/Sub message
        envelope = request.get_json()
        if not envelope:
            logger.error("No Pub/Sub message received", exc_info=True)
            return ('Bad Request: no Pub/Sub message received', 400)

        pubsub_message = envelope.get('message', {})
        if not pubsub_message:
            logger.error("No message field in envelope", exc_info=True)
            return ('Bad Request: invalid Pub/Sub message format', 400)

        # Week 1: Extract message ID for idempotency
        message_id = pubsub_message.get('messageId') or pubsub_message.get('message_id')

        # Week 1: Check for duplicate message
        if message_id and check_and_mark_message_processed(message_id):
            logger.info(f"Duplicate message ignored: {message_id}")
            return ('', 204)  # Success - already processed

        # Decode message data
        message_data = base64.b64decode(pubsub_message['data']).decode('utf-8')
        event = json.loads(message_data)
        
        player_lookup = event.get('player_lookup')
        batch_id = event.get('batch_id')  # Workers should include batch_id in completion events
        predictions_count = event.get('predictions_generated', 0)

        logger.info(f"Completion: {player_lookup} (batch={batch_id}, predictions={predictions_count})")

        # Process completion event using Firestore (PERSISTENT - survives restarts!)
        try:
            if not batch_id:
                logger.error("Completion event missing batch_id - cannot process", exc_info=True)
                return ('Bad Request: batch_id required', 400)

            state_manager = get_state_manager()

            # Use safe completion with retries for reliability
            batch_complete = state_manager.record_completion_safe(
                batch_id=batch_id,
                player_lookup=player_lookup,
                predictions_count=predictions_count,
                instance_id=_instance_manager.instance_id if _instance_manager else None
            )
            logger.info(f"Recorded: {player_lookup} -> batch_complete={batch_complete}")

            # BACKWARD COMPATIBILITY: Also update in-memory tracker if it exists
            if current_tracker and current_batch_id == batch_id:
                current_tracker.process_completion_event(event)

            # If batch is now complete, publish summary and trigger consolidation
            if batch_complete:
                logger.info(f"Batch {batch_id} complete! Triggering consolidation...")
                publish_batch_summary_from_firestore(batch_id)
                logger.info(f"Consolidation triggered for batch {batch_id}")
        except Exception as e:
            logger.error(f"ERROR in completion handler: {e}", exc_info=True)
            logger.error(f"Error recording completion to Firestore: {e}", exc_info=True)
            # CRITICAL: Return 500 so Pub/Sub retries - completion event cannot be lost!
            # Worker already succeeded, but we MUST track completion for batch consolidation
            # Week 1: Idempotency prevents duplicate processing on retry
            return ('Internal Server Error: Failed to record completion', 500)

        return ('', 204)  # Success

    except Exception as e:
        logger.error(f"FATAL ERROR processing completion: {e}", exc_info=True)
        return ('Internal Server Error', 500)


@app.route('/status', methods=['GET'])
@require_api_key
def get_batch_status():
    """
    Get current batch status (REQUIRES AUTHENTICATION)

    Query params:
        batch_id: Optional batch ID to check

    Returns:
        Current progress and statistics

    Authentication:
        Requires X-API-Key header or 'key' query parameter
    """
    global current_tracker, current_batch_id
    
    requested_batch_id = request.args.get('batch_id')
    
    # Check if requested batch matches current batch
    if requested_batch_id and requested_batch_id != current_batch_id:
        return jsonify({
            'status': 'not_found',
            'message': f'Batch {requested_batch_id} not found',
            'current_batch': current_batch_id
        }), 404
    
    if not current_tracker:
        return jsonify({
            'status': 'no_active_batch',
            'current_batch': None
        }), 200
    
    # Get current progress
    progress = current_tracker.get_progress()
    
    # Check if stalled
    is_stalled = current_tracker.is_stalled()
    
    return jsonify({
        'status': 'complete' if current_tracker.is_complete else 'in_progress',
        'batch_id': current_batch_id,
        'progress': progress,
        'is_stalled': is_stalled,
        'summary': current_tracker.get_summary() if current_tracker.is_complete else None
    }), 200


def _track_batch_cleanup_event(stalled_count: int, results: list) -> None:
    """
    Track batch cleanup events in Firestore and send Slack alert if systemic issue detected.

    Systemic issue = 3+ cleanups within 1 hour (indicates workers are consistently failing).

    Added in Session 132 as part of automated batch cleanup (Option A quick win).

    Args:
        stalled_count: Number of batches that were auto-completed
        results: List of cleanup results with batch details
    """
    try:
        from google.cloud import firestore
        from datetime import datetime, timedelta
        import os

        db = firestore.Client(project='nba-props-platform')

        # Record this cleanup event
        cleanup_ref = db.collection('batch_cleanup_events').document()
        cleanup_ref.set({
            'timestamp': firestore.SERVER_TIMESTAMP,
            'stalled_count': stalled_count,
            'batch_ids': [r['batch_id'] for r in results if r['was_stalled']],
            'results': results
        })

        # Check for systemic issue (3+ cleanups in last hour)
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        recent_cleanups = db.collection('batch_cleanup_events') \
            .where('timestamp', '>=', one_hour_ago) \
            .stream()

        recent_count = sum(1 for _ in recent_cleanups)

        # Send Slack alert if threshold exceeded
        if recent_count >= 3:
            from shared.utils.slack_channels import send_to_slack

            webhook_url = os.environ.get('SLACK_WEBHOOK_URL')  # #daily-orchestration
            if webhook_url:
                batch_list = "\n".join([f"• {r['batch_id']}" for r in results if r['was_stalled']][:5])

                text = f"""🚨 *Systemic Batch Stall Issue Detected*

*{recent_count} cleanups* in the last hour (threshold: 3)
*{stalled_count} batches* auto-completed in this run

*Recently stalled batches:*
{batch_list}

*Possible causes:*
• Workers crashing or timing out
• Dependency service failures
• Resource constraints (CPU/memory)

_Check worker logs and /health/deep endpoint for issues_"""

                send_to_slack(
                    webhook_url=webhook_url,
                    text=text,
                    icon_emoji=":rotating_light:"
                )
                logger.warning(f"Systemic stall issue: {recent_count} cleanups in last hour")

    except Exception as e:
        # Don't fail the cleanup operation if tracking fails
        logger.error(f"Error tracking batch cleanup event: {e}", exc_info=True)


@app.route('/check-stalled', methods=['POST'])
@require_api_key
def check_stalled_batches():
    """
    Check for stalled batches and complete them with partial results.

    This endpoint can be called manually or by a scheduled job to prevent
    batches from waiting indefinitely for workers that will never respond.

    Request body (optional):
    {
        "batch_id": "batch_2026-01-15_123456",  // Optional: specific batch
        "stall_threshold_minutes": 10,          // Optional: default 10
        "min_completion_pct": 95.0              // Optional: default 95%
    }

    Returns:
        JSON with results of stall check
    """
    try:
        request_data = request.get_json() or {}
        batch_id = request_data.get('batch_id')
        stall_threshold = request_data.get('stall_threshold_minutes', 10)
        min_completion = request_data.get('min_completion_pct', 95.0)

        state_manager = get_state_manager()
        results = []

        if batch_id:
            # Check specific batch
            completed = state_manager.check_and_complete_stalled_batch(
                batch_id=batch_id,
                stall_threshold_minutes=stall_threshold,
                min_completion_pct=min_completion
            )
            results.append({
                'batch_id': batch_id,
                'was_stalled': completed,
                'action': 'completed_with_partial' if completed else 'no_action'
            })

            # If batch was completed, trigger consolidation
            if completed:
                logger.info(f"Triggering consolidation for stalled batch {batch_id}")
                publish_batch_summary_from_firestore(batch_id)
        else:
            # Check all active batches
            active_batches = state_manager.get_active_batches()
            for batch in active_batches:
                completed = state_manager.check_and_complete_stalled_batch(
                    batch_id=batch.batch_id,
                    stall_threshold_minutes=stall_threshold,
                    min_completion_pct=min_completion
                )
                results.append({
                    'batch_id': batch.batch_id,
                    'was_stalled': completed,
                    'progress': f"{len(batch.completed_players)}/{batch.expected_players}",
                    'action': 'completed_with_partial' if completed else 'no_action'
                })

                if completed:
                    logger.info(f"Triggering consolidation for stalled batch {batch.batch_id}")
                    publish_batch_summary_from_firestore(batch.batch_id)

        stalled_count = sum(1 for r in results if r['was_stalled'])

        # Track cleanup events for systemic issue detection (Session 132)
        if stalled_count > 0:
            _track_batch_cleanup_event(stalled_count, results)

        return jsonify({
            'status': 'success',
            'batches_checked': len(results),
            'batches_completed': stalled_count,
            'results': results
        }), 200

    except Exception as e:
        logger.error(f"Error checking stalled batches: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/reset', methods=['POST'])
@require_api_key
def reset_batch():
    """
    Session 159: Force-reset a stuck batch so a new one can start.

    Unlike /check-stalled (which requires 95%+ completion), this endpoint
    unconditionally marks the batch as complete/failed and clears the in-memory
    tracker. Use when a batch is stuck at 0% due to worker failures.

    Request body:
    {
        "batch_id": "batch_2026-02-07_123456",  // Optional: specific batch
        "game_date": "2026-02-07"                // Optional: reset by game date
    }

    At least one of batch_id or game_date must be provided.
    """
    global current_tracker, current_batch_id, current_game_date

    try:
        request_data = request.get_json() or {}
        batch_id = request_data.get('batch_id')
        game_date = request_data.get('game_date')

        if not batch_id and not game_date:
            return jsonify({
                'status': 'error',
                'message': 'Provide batch_id or game_date'
            }), 400

        state_manager = get_state_manager()

        # If game_date provided but not batch_id, find active batch for that date
        if not batch_id and game_date:
            active_batches = state_manager.get_active_batches()
            matching = [b for b in active_batches if str(b.game_date) == game_date]
            if matching:
                batch_id = matching[0].batch_id
            elif current_batch_id and current_game_date and str(current_game_date) == game_date:
                batch_id = current_batch_id

        if not batch_id:
            return jsonify({
                'status': 'no_batch',
                'message': f'No active batch found for game_date={game_date}'
            }), 404

        # Force-complete the batch in Firestore
        completed = state_manager.check_and_complete_stalled_batch(
            batch_id=batch_id,
            stall_threshold_minutes=0,  # No threshold - force immediate
            min_completion_pct=0.0       # No minimum - force regardless of progress
        )

        # Reset in-memory tracker — set to None so /start won't see "already_running"
        # Bug fix (Session 164): reset() sets is_complete=False which blocks new batches
        current_tracker = None
        current_batch_id = None
        current_game_date = None

        logger.warning(
            f"BATCH RESET: batch_id={batch_id}, firestore_completed={completed}, "
            f"in_memory_tracker_cleared=True"
        )

        return jsonify({
            'status': 'reset',
            'batch_id': batch_id,
            'firestore_completed': completed,
            'tracker_cleared': True,
            'message': 'Batch reset. You can now trigger a new batch with /start.'
        }), 200

    except Exception as e:
        logger.error(f"Error resetting batch: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/cleanup-duplicates', methods=['POST'])
@require_api_key
def cleanup_duplicate_predictions():
    """
    Clean up duplicate predictions (streaming buffer safe).

    SESSION 28 FIX: This endpoint should be called 2+ hours after predictions
    to deactivate duplicates that couldn't be cleaned immediately due to
    BigQuery's streaming buffer (which locks rows for 30-90 minutes).

    The immediate deactivation in consolidate_batch() fails silently because
    rows inserted by MERGE are in the streaming buffer.

    Recommended usage:
    - Cloud Scheduler job runs at 10:00 AM (2 hours after 8 AM predictions)
    - Or call manually after verifying streaming buffer has cleared

    Request body:
    {
        "game_date": "2026-01-30",  // Required: YYYY-MM-DD, "TODAY", or "YESTERDAY"
        "dry_run": false            // Optional: just count without deactivating
    }

    Returns:
        200 OK with cleanup results
    """
    try:
        request_data = request.get_json() or {}
        game_date_str = request_data.get('game_date')
        dry_run = request_data.get('dry_run', False)

        if not game_date_str:
            return jsonify({
                'status': 'error',
                'message': 'game_date is required'
            }), 400

        # Support TODAY, YESTERDAY, or explicit YYYY-MM-DD
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        if game_date_str.upper() == "TODAY":
            game_date = datetime.now(ZoneInfo('America/New_York')).date()
            game_date_str = game_date.isoformat()
            logger.info(f"TODAY resolved to: {game_date_str}")
        elif game_date_str.upper() == "YESTERDAY":
            game_date = datetime.now(ZoneInfo('America/New_York')).date() - timedelta(days=1)
            game_date_str = game_date.isoformat()
            logger.info(f"YESTERDAY resolved to: {game_date_str}")
        else:
            # Validate date format
            try:
                game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({
                    'status': 'error',
                    'message': 'Invalid date format. Use YYYY-MM-DD, TODAY, or YESTERDAY.'
                }), 400

        logger.info(
            f"Cleaning up duplicate predictions for {game_date} "
            f"(dry_run={dry_run})"
        )

        # Use the batch consolidator's cleanup method
        consolidator = get_batch_consolidator()
        result = consolidator.cleanup_duplicate_predictions(
            game_date=game_date_str,
            dry_run=dry_run
        )

        if 'error' in result:
            logger.error(f"Duplicate cleanup failed: {result['error']}")
            return jsonify({
                'status': 'error',
                'message': result['error'],
                'details': result
            }), 500

        logger.info(
            f"Duplicate cleanup {'(DRY RUN) ' if dry_run else ''}"
            f"for {game_date}: found={result['duplicates_found']}, "
            f"deactivated={result['duplicates_deactivated']}"
        )

        return jsonify({
            'status': 'success',
            **result
        }), 200

    except Exception as e:
        logger.error(f"Error in cleanup_duplicate_predictions: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/check-signal', methods=['POST'])
@require_api_key
def check_prediction_signal():
    """
    Check today's prediction signals for anomalies.

    SESSION 81: Monitors for extreme UNDER/OVER skews that historically
    correlate with lower hit rates. Returns signal status and can send alerts.

    Based on Session 70 analysis:
    - Balanced (25-45% OVER): 82% hit rate on high-edge picks
    - Heavy UNDER (<25% OVER): 54% hit rate (barely above breakeven)

    Request body:
    {
        "game_date": "2026-02-02",  // Optional: defaults to TODAY
        "send_alert": true          // Optional: send Slack alert if RED (default: true)
    }

    Returns:
        200 OK with signal status (GREEN/YELLOW/RED)
    """
    from zoneinfo import ZoneInfo

    try:
        request_data = request.get_json() or {}
        game_date_str = request_data.get('game_date', 'TODAY')
        send_alert = request_data.get('send_alert', True)

        # Resolve date
        if game_date_str.upper() == "TODAY":
            game_date = datetime.now(ZoneInfo('America/New_York')).date()
            game_date_str = game_date.isoformat()

        logger.info(f"Checking prediction signal for {game_date_str}")

        # Query signal data
        from shared.clients import get_bigquery_client
        bq_client = get_bigquery_client(PROJECT_ID)
        query = f"""
        SELECT
          game_date,
          system_id,
          total_picks,
          high_edge_picks,
          ROUND(pct_over, 1) as pct_over,
          ROUND(pct_under, 1) as pct_under,
          daily_signal,
          signal_explanation,
          skew_category
        FROM nba_predictions.daily_prediction_signals
        WHERE game_date = DATE('{game_date_str}')
          AND system_id = 'catboost_v9'
        LIMIT 1
        """

        result = list(bq_client.query(query).result())

        if not result:
            return jsonify({
                'status': 'warning',
                'message': f'No signal data found for {game_date_str}',
                'game_date': game_date_str,
                'signal': None
            }), 200

        row = result[0]
        signal = row.daily_signal
        pct_over = row.pct_over
        explanation = row.signal_explanation

        response = {
            'status': 'success',
            'game_date': game_date_str,
            'signal': signal,
            'pct_over': pct_over,
            'total_picks': row.total_picks,
            'high_edge_picks': row.high_edge_picks,
            'explanation': explanation,
            'skew_category': row.skew_category
        }

        # Log and potentially alert
        if signal == 'RED':
            logger.warning(
                f"RED signal detected for {game_date_str}: "
                f"{pct_over}% OVER - {explanation}"
            )

            # Could add Slack webhook here if send_alert is True
            # For now, just log the warning

        elif signal == 'YELLOW':
            logger.info(f"YELLOW signal for {game_date_str}: {explanation}")
        else:
            logger.info(f"GREEN signal for {game_date_str}: balanced predictions")

        return jsonify(response), 200

    except Exception as e:
        logger.error(f"Error in check_prediction_signal: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/cleanup-staging', methods=['POST'])
@require_api_key
def cleanup_staging_tables():
    """
    Clean up orphaned staging tables from failed or incomplete prediction batches.

    SESSION 81 FIX: Staging tables accumulate when batch consolidation fails
    or is interrupted. This endpoint removes tables older than max_age_hours.

    Recommended usage:
    - Cloud Scheduler job runs daily at 3 AM ET
    - Or call manually after investigating failed batches

    Request body:
    {
        "max_age_hours": 24,  // Optional: delete tables older than this (default: 24)
        "dry_run": false      // Optional: just count without deleting
    }

    Returns:
        200 OK with cleanup results
    """
    try:
        request_data = request.get_json() or {}
        max_age_hours = request_data.get('max_age_hours', 24)
        dry_run = request_data.get('dry_run', False)

        logger.info(
            f"Starting staging table cleanup (max_age_hours={max_age_hours}, "
            f"dry_run={dry_run})"
        )

        # Use the batch consolidator's cleanup method
        consolidator = get_batch_consolidator()
        result = consolidator.cleanup_orphaned_staging_tables(
            max_age_hours=max_age_hours,
            dry_run=dry_run
        )

        logger.info(
            f"Staging cleanup {'(DRY RUN) ' if dry_run else ''}"
            f"complete: found={result.get('tables_found', 0)}, "
            f"deleted={result.get('tables_deleted', 0)}"
        )

        return jsonify({
            'status': 'success',
            **result
        }), 200

    except Exception as e:
        logger.error(f"Error in cleanup_staging_tables: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


def publish_with_retry(publisher, topic_path: str, message_bytes: bytes,
                       player_lookup: str, max_retries: int = 3) -> bool:
    """
    Publish a message to Pub/Sub with exponential backoff retry.

    Args:
        publisher: Pub/Sub publisher client
        topic_path: Full topic path
        message_bytes: Encoded message data
        player_lookup: Player identifier for logging
        max_retries: Maximum number of retry attempts (default 3)

    Returns:
        True if publish succeeded, False otherwise

    Retry delays: 1s, 2s, 4s (exponential backoff)
    """
    last_exception = None

    for attempt in range(max_retries):
        try:
            future = publisher.publish(topic_path, data=message_bytes)
            # Wait for publish confirmation with timeout
            future.result(timeout=5.0)
            return True
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                # Exponential backoff: 1s, 2s, 4s
                delay = 2 ** attempt
                logger.warning(
                    f"Pub/Sub publish attempt {attempt + 1}/{max_retries} failed for "
                    f"{player_lookup}: {e}. Retrying in {delay}s..."
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"Pub/Sub publish failed after {max_retries} attempts for "
                    f"{player_lookup}: {e}",
                    exc_info=True
                )

    return False


def publish_prediction_requests(
    requests: List[Dict],
    batch_id: str,
    batch_historical_games: Optional[Dict[str, List[Dict]]] = None,
    dataset_prefix: str = '',
    prediction_run_mode: str = 'OVERNIGHT'
) -> int:
    """
    Publish prediction requests to Pub/Sub

    Args:
        requests: List of prediction request dicts
        batch_id: Batch identifier for tracking
        batch_historical_games: Optional pre-loaded historical games (batch optimization)
                                Dict mapping player_lookup -> list of historical games
        dataset_prefix: Optional dataset prefix for test isolation (e.g., "test")
        prediction_run_mode: Run mode for traceability (EARLY, OVERNIGHT, SAME_DAY, BACKFILL)

    Returns:
        Number of successfully published messages
    """
    publisher = get_pubsub_publisher()
    topic_path = publisher.topic_path(PROJECT_ID, PREDICTION_REQUEST_TOPIC)

    published_count = 0
    failed_count = 0
    publish_start_time = time.time()

    # Use heartbeat logger to track long publish operations (5-min intervals)
    with HeartbeatLogger(f"Publishing {len(requests)} prediction requests", interval=300):
        for request_data in requests:
            # Add batch metadata
            message = {
                **request_data,
                'batch_id': batch_id,
                'timestamp': datetime.now().isoformat(),
                'correlation_id': current_correlation_id or batch_id,  # Include correlation_id for tracing
                'prediction_run_mode': prediction_run_mode  # Session 76: Track run mode for analysis
            }

            # Add dataset_prefix for test isolation if specified
            if dataset_prefix:
                message['dataset_prefix'] = dataset_prefix

            # BATCH OPTIMIZATION: Include pre-loaded historical games if available
            if batch_historical_games:
                player_lookup = request_data.get('player_lookup')
                if player_lookup and player_lookup in batch_historical_games:
                    # Add historical games to message (worker will use this instead of querying)
                    message['historical_games_batch'] = batch_historical_games[player_lookup]

            # Publish to Pub/Sub with retry logic
            message_bytes = json.dumps(message).encode('utf-8')
            player_lookup = request_data.get('player_lookup', 'unknown')

            if publish_with_retry(publisher, topic_path, message_bytes, player_lookup):
                published_count += 1

                # Rate limit: ~50 messages/second to allow worker cold-start ramp-up
                # Session 101: Added to prevent cold start auth failures
                # Session 171: Reduced from 0.1s to 0.02s (45s→9s for 450 players)
                time.sleep(0.02)

                # Log every 50 players (more frequent than heartbeat for progress visibility)
                if published_count % 50 == 0:
                    logger.info(f"Published {published_count}/{len(requests)} requests")
            else:
                failed_count += 1

                # Mark player as failed in tracker
                if current_tracker:
                    current_tracker.mark_player_failed(
                        player_lookup,
                        "Pub/Sub publish failed after retries"
                    )

    publish_duration = time.time() - publish_start_time
    publish_rate = published_count / publish_duration if publish_duration > 0 else 0
    logger.info(
        f"PUBLISH_METRICS: Published {published_count} requests in {publish_duration:.1f}s "
        f"({publish_rate:.1f} req/s), {failed_count} failed "
        f"[batch={batch_id}, mode={prediction_run_mode}]"
    )

    return published_count


def send_prediction_completion_email(summary: Dict, game_date: str, batch_id: str):
    """
    Send prediction completion summary email via AWS SES.

    Args:
        summary: Summary dict from ProgressTracker.get_summary()
        game_date: Date predictions were generated for
        batch_id: Batch identifier
    """
    try:
        from shared.utils.email_alerting_ses import EmailAlerterSES

        # Get games count from BigQuery (or estimate from players)
        # For now, estimate: ~15 players per game average
        completed = summary.get('completed_players', 0)
        expected = summary.get('expected_players', 0)
        games_count = max(1, completed // 15) if completed > 0 else 0

        # Build failed players list with reasons
        failed_list = summary.get('failed_player_list', [])
        failed_players = [
            {'name': player, 'reason': 'Prediction generation failed'}
            for player in failed_list
        ]

        # Calculate confidence distribution (placeholder - would need actual prediction data)
        # In production, query nba_predictions.player_prop_predictions for this
        total_predictions = summary.get('total_predictions', 0)
        # Estimate distribution (would be replaced with actual query)
        high_conf = int(total_predictions * 0.4)
        med_conf = int(total_predictions * 0.45)
        low_conf = total_predictions - high_conf - med_conf

        # Build email data
        prediction_data = {
            'date': game_date,
            'games_count': games_count,
            'players_predicted': completed,
            'players_total': expected,
            'failed_players': failed_players,
            'confidence_distribution': {
                'high': high_conf,
                'medium': med_conf,
                'low': low_conf
            },
            'top_recommendations': [],  # Would need to query predictions table
            'duration_minutes': int(summary.get('duration_seconds', 0) / 60)
        }

        # Send email
        alerter = EmailAlerterSES()
        success = alerter.send_prediction_completion_summary(prediction_data)

        if success:
            logger.info(f"📧 Prediction completion email sent for {game_date}")
        else:
            logger.warning(f"Failed to send prediction completion email for {game_date}")

        # Send to Slack #nba-predictions channel
        try:
            from shared.utils.slack_channels import send_prediction_summary_to_slack
            slack_success = send_prediction_summary_to_slack(prediction_data)
            if slack_success:
                logger.info(f"💬 Prediction completion sent to Slack for {game_date}")
        except Exception as slack_err:
            logger.debug(f"Slack notification skipped: {slack_err}")

    except ImportError as e:
        logger.warning(f"Email alerter not available (non-fatal): {e}")
    except Exception as e:
        logger.error(f"Error sending prediction completion email (non-fatal): {e}", exc_info=True)


def publish_batch_summary_from_firestore(batch_id: str):
    """
    Publish batch summary using persistent state from Firestore

    This function is used when completion events trigger consolidation
    after a container restart (when in-memory tracker is lost).

    Args:
        batch_id: Batch identifier
    """
    logger.info(f"Starting publish_batch_summary_from_firestore for {batch_id}")
    try:
        # Get batch state from Firestore
        state_manager = get_state_manager()
        batch_state = state_manager.get_batch_state(batch_id)

        if not batch_state:
            logger.error(f"Cannot publish summary - batch state not found: {batch_id}", exc_info=True)
            return

        # Extract game_date and build summary
        game_date = batch_state.game_date

        logger.info(
            f"Publishing batch summary: {batch_id} "
            f"({len(batch_state.completed_players)}/{batch_state.expected_players} players, "
            f"game_date={game_date})"
        )
        logger.info(
            f"Publishing batch summary from Firestore: {batch_id} "
            f"({len(batch_state.completed_players)}/{batch_state.expected_players} players)"
        )

        # Step 1: Consolidate staging tables into main predictions table
        try:
            logger.info(f"Starting consolidation for batch {batch_id}, game_date={game_date}")
            consolidator = get_batch_consolidator()
            consolidation_result = consolidator.consolidate_batch(
                batch_id=batch_id,
                game_date=game_date,
                cleanup=True  # Delete staging tables after successful merge
            )

            if consolidation_result.success:
                logger.info(
                    f"Consolidation SUCCESS: {consolidation_result.rows_affected} rows merged "
                    f"from {consolidation_result.staging_tables_merged} staging tables, "
                    f"cleaned={consolidation_result.staging_tables_cleaned}"
                )

                # Step 1.4: Check batch PVL bias (Session 170) + skew & vegas source (Session 171)
                try:
                    from predictions.coordinator.quality_alerts import (
                        send_pvl_bias_alert, send_recommendation_skew_alert,
                        send_vegas_source_alert, send_direction_mismatch_alert
                    )
                    pvl_query = f"""
                    SELECT
                        ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl,
                        COUNT(*) as prediction_count,
                        prediction_run_mode
                    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
                    WHERE game_date = @game_date
                      AND system_id = 'catboost_v9'
                      AND is_active = TRUE
                      AND current_points_line IS NOT NULL
                    GROUP BY prediction_run_mode
                    """
                    pvl_config = bigquery.QueryJobConfig(
                        query_parameters=[
                            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
                        ]
                    )
                    pvl_client = bigquery.Client(project=PROJECT_ID)
                    pvl_rows = list(pvl_client.query(pvl_query, job_config=pvl_config).result())

                    # Session 171: Alert when PVL check returns empty results
                    if not pvl_rows:
                        logger.warning(
                            f"PVL bias check: NO predictions with lines for {game_date} — "
                            f"batch may be empty or all predictions lack current_points_line"
                        )

                    for pvl_row in pvl_rows:
                        avg_pvl = pvl_row.avg_pvl or 0.0
                        if abs(avg_pvl) > 2.0:
                            send_pvl_bias_alert(
                                game_date=game_date,
                                run_mode=pvl_row.prediction_run_mode or 'UNKNOWN',
                                avg_pvl=avg_pvl,
                                prediction_count=pvl_row.prediction_count,
                            )
                        else:
                            logger.info(f"PVL bias check OK: avg_pvl={avg_pvl:+.2f} ({pvl_row.prediction_run_mode})")

                    # Session 171: Check recommendation distribution skew
                    skew_query = f"""
                    SELECT
                        COUNTIF(recommendation = 'OVER') as overs,
                        COUNTIF(recommendation = 'UNDER') as unders,
                        COUNT(*) as total,
                        prediction_run_mode
                    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
                    WHERE game_date = @game_date
                      AND system_id = 'catboost_v9'
                      AND is_active = TRUE
                      AND current_points_line IS NOT NULL
                    GROUP BY prediction_run_mode
                    """
                    skew_rows = list(pvl_client.query(skew_query, job_config=pvl_config).result())
                    for skew_row in skew_rows:
                        s_total = skew_row.total or 0
                        s_overs = skew_row.overs or 0
                        s_unders = skew_row.unders or 0
                        if s_total >= 10:
                            over_pct = s_overs / s_total * 100
                            under_pct = s_unders / s_total * 100
                            if over_pct < 15 or under_pct < 15:
                                send_recommendation_skew_alert(
                                    game_date=game_date,
                                    run_mode=skew_row.prediction_run_mode or 'UNKNOWN',
                                    overs=s_overs,
                                    unders=s_unders,
                                    total=s_total,
                                )
                            else:
                                logger.info(
                                    f"Recommendation skew OK: {over_pct:.0f}% OVER / {under_pct:.0f}% UNDER "
                                    f"({skew_row.prediction_run_mode})"
                                )

                    # Session 171: Monitor vegas_source distribution (recovery_median frequency)
                    vegas_src_query = f"""
                    SELECT
                        JSON_EXTRACT_SCALAR(features_snapshot, '$.vegas_source') as source,
                        COUNT(*) as cnt
                    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
                    WHERE game_date = @game_date
                      AND system_id = 'catboost_v9'
                      AND is_active = TRUE
                    GROUP BY 1
                    """
                    vegas_src_rows = list(pvl_client.query(vegas_src_query, job_config=pvl_config).result())
                    source_counts = {}
                    src_total = 0
                    for vs_row in vegas_src_rows:
                        source = vs_row.source or 'unknown'
                        source_counts[source] = vs_row.cnt
                        src_total += vs_row.cnt
                    recovery_count = source_counts.get('recovery_median', 0)
                    if src_total > 0 and recovery_count / src_total > 0.30:
                        send_vegas_source_alert(
                            game_date=game_date,
                            run_mode='UNKNOWN',
                            source_counts=source_counts,
                            total=src_total,
                        )
                    elif src_total > 0:
                        logger.info(
                            f"Vegas source check OK: recovery_median={recovery_count}/{src_total} "
                            f"({recovery_count/src_total*100:.0f}%)"
                        )
                    else:
                        logger.info("Vegas source check: no predictions found")

                    # Session 176: Check recommendation direction alignment
                    direction_query = f"""
                    SELECT
                        COUNTIF(predicted_points > current_points_line AND recommendation = 'UNDER') as above_but_under,
                        COUNTIF(predicted_points < current_points_line AND recommendation = 'OVER') as below_but_over,
                        COUNT(*) as total,
                        prediction_run_mode
                    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
                    WHERE game_date = @game_date
                      AND system_id = 'catboost_v9'
                      AND is_active = TRUE
                      AND current_points_line IS NOT NULL
                    GROUP BY prediction_run_mode
                    """
                    dir_rows = list(pvl_client.query(direction_query, job_config=pvl_config).result())
                    for dir_row in dir_rows:
                        abu = dir_row.above_but_under or 0
                        bbo = dir_row.below_but_over or 0
                        d_total = dir_row.total or 0
                        if abu + bbo > 0:
                            send_direction_mismatch_alert(
                                game_date=game_date,
                                run_mode=dir_row.prediction_run_mode or 'UNKNOWN',
                                above_but_under=abu,
                                below_but_over=bbo,
                                total=d_total,
                            )
                        else:
                            logger.info(
                                f"Direction alignment OK: 0 mismatches out of {d_total} "
                                f"({dir_row.prediction_run_mode})"
                            )

                except Exception as pvl_err:
                    logger.warning(f"Post-consolidation quality checks failed (non-fatal): {pvl_err}")

                # Step 1.5: Calculate daily prediction signals (Session 71)
                try:
                    logger.info(f"Calculating daily prediction signals for {game_date}...")
                    signal_result = calculate_daily_signals(game_date=game_date)
                    if signal_result['success']:
                        logger.info(
                            f"Daily signals calculated: {signal_result['systems_processed']} systems"
                        )
                    else:
                        logger.warning(
                            f"Signal calculation failed (non-fatal): {signal_result.get('error')}"
                        )
                except Exception as signal_err:
                    # Don't fail batch if signal calculation fails
                    logger.warning(f"Signal calculation failed (non-fatal): {signal_err}")
            else:
                logger.error(f"Consolidation FAILED: {consolidation_result.error_message}", exc_info=True)
        except Exception as e:
            logger.error(f"Consolidation EXCEPTION: {e}", exc_info=True)

        # Step 2: Publish Phase 5 completion event to trigger Phase 6
        try:
            logger.info("Publishing Phase 5 completion to Pub/Sub...")
            # Calculate duration if timestamps are available
            duration_seconds = None
            if batch_state.start_time and batch_state.completion_time:
                duration_seconds = (batch_state.completion_time - batch_state.start_time).total_seconds()

            unified_publisher = UnifiedPubSubPublisher(project_id=PROJECT_ID)
            unified_publisher.publish_completion(
                topic='nba-phase5-predictions-complete',
                processor_name='PredictionCoordinator',
                phase='phase_5_predictions',
                execution_id=batch_id,
                correlation_id=batch_state.correlation_id or batch_id,
                game_date=game_date,
                output_table='player_prop_predictions',
                output_dataset='nba_predictions',
                status='success',
                record_count=len(batch_state.completed_players),
                records_failed=len(batch_state.failed_players),
                trigger_source='automatic',
                duration_seconds=duration_seconds,
                metadata={
                    'batch_id': batch_id,
                    'expected_players': batch_state.expected_players,
                    'completed_players': len(batch_state.completed_players),
                    'total_predictions': batch_state.total_predictions,
                    'completion_percentage': batch_state.get_completion_percentage()
                }
            )
            logger.info(f"Phase 5 completion published for batch: {batch_id}")
        except Exception as e:
            logger.error(f"Failed to publish Phase 5 completion: {e}", exc_info=True)

        # Step 3: Log batch completion to processor_run_history for unified monitoring
        # (This was missing from Firestore path - fixes "running" status stuck forever)
        try:
            completed = len(batch_state.completed_players)
            expected = batch_state.expected_players
            failed = len(batch_state.failed_players)

            # Determine status based on completion
            if completed == expected:
                status = 'success'
            elif completed > 0:
                status = 'partial'
            else:
                status = 'failed'

            # Calculate duration
            duration_seconds = None
            if batch_state.start_time and batch_state.completion_time:
                duration_seconds = (batch_state.completion_time - batch_state.start_time).total_seconds()

            get_run_history().complete_batch(
                status=status,
                records_processed=completed,
                records_failed=failed,
                duration_seconds=duration_seconds or 0,
                summary={
                    'expected': expected,
                    'completed': completed,
                    'failed': failed,
                    'total_predictions': batch_state.total_predictions,
                    'completion_percentage': batch_state.get_completion_percentage()
                }
            )
            logger.info(f"Run history updated: status={status}, completed={completed}/{expected}")
        except Exception as e:
            # Don't fail the batch if run history logging fails
            logger.warning(f"Failed to update run history (non-fatal): {e}")

        logger.info(f"Batch summary published successfully: {batch_id}")

    except Exception as e:
        logger.error(f"ERROR publishing batch summary from Firestore: {e}", exc_info=True)


def publish_batch_summary(tracker: ProgressTracker, batch_id: str):
    """
    Publish unified batch completion summary (LEGACY - uses in-memory tracker)

    Uses UnifiedPubSubPublisher for consistency with Phases 1-4.
    Also logs to processor_run_history for unified monitoring.
    Sends prediction completion email notification.

    Flow:
    1. Consolidate staging tables (merge all worker writes into main table)
    2. Check coverage and send alerts if below thresholds
    3. Log to run history
    4. Publish completion message
    5. Send email notification

    Args:
        tracker: Progress tracker with final stats
        batch_id: Batch identifier
    """
    global current_correlation_id, current_game_date

    try:
        # Use unified publisher
        unified_publisher = UnifiedPubSubPublisher(project_id=PROJECT_ID)

        summary = tracker.get_summary()
        game_date = current_game_date.isoformat() if current_game_date else date.today().isoformat()

        # Step 1: Consolidate staging tables into main predictions table
        # This is critical for the batch staging write pattern to work
        try:
            consolidator = get_batch_consolidator()
            consolidation_result = consolidator.consolidate_batch(
                batch_id=batch_id,
                game_date=game_date,
                cleanup=True  # Delete staging tables after successful merge
            )

            if consolidation_result.success:
                logger.info(
                    f"✅ Consolidation complete: {consolidation_result.rows_affected} rows merged "
                    f"from {consolidation_result.staging_tables_merged} staging tables"
                )
                # Update summary with consolidation info
                summary['consolidation'] = {
                    'rows_affected': consolidation_result.rows_affected,
                    'staging_tables_merged': consolidation_result.staging_tables_merged,
                    'staging_tables_cleaned': consolidation_result.staging_tables_cleaned,
                    'success': True
                }

                # Step 1.4: Check batch PVL bias (Session 170) + skew & vegas source (Session 171)
                try:
                    from predictions.coordinator.quality_alerts import (
                        send_pvl_bias_alert, send_recommendation_skew_alert,
                        send_vegas_source_alert, send_direction_mismatch_alert
                    )
                    pvl_query = f"""
                    SELECT
                        ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl,
                        COUNT(*) as prediction_count,
                        prediction_run_mode
                    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
                    WHERE game_date = @game_date
                      AND system_id = 'catboost_v9'
                      AND is_active = TRUE
                      AND current_points_line IS NOT NULL
                    GROUP BY prediction_run_mode
                    """
                    pvl_config = bigquery.QueryJobConfig(
                        query_parameters=[
                            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
                        ]
                    )
                    pvl_client = bigquery.Client(project=PROJECT_ID)
                    pvl_rows = list(pvl_client.query(pvl_query, job_config=pvl_config).result())

                    # Session 171: Alert when PVL check returns empty results
                    if not pvl_rows:
                        logger.warning(
                            f"PVL bias check: NO predictions with lines for {game_date} — "
                            f"batch may be empty or all predictions lack current_points_line"
                        )

                    for pvl_row in pvl_rows:
                        avg_pvl = pvl_row.avg_pvl or 0.0
                        if abs(avg_pvl) > 2.0:
                            send_pvl_bias_alert(
                                game_date=game_date,
                                run_mode=pvl_row.prediction_run_mode or 'UNKNOWN',
                                avg_pvl=avg_pvl,
                                prediction_count=pvl_row.prediction_count,
                            )
                        else:
                            logger.info(f"PVL bias check OK: avg_pvl={avg_pvl:+.2f} ({pvl_row.prediction_run_mode})")

                    # Session 171: Check recommendation distribution skew
                    skew_query = f"""
                    SELECT
                        COUNTIF(recommendation = 'OVER') as overs,
                        COUNTIF(recommendation = 'UNDER') as unders,
                        COUNT(*) as total,
                        prediction_run_mode
                    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
                    WHERE game_date = @game_date
                      AND system_id = 'catboost_v9'
                      AND is_active = TRUE
                      AND current_points_line IS NOT NULL
                    GROUP BY prediction_run_mode
                    """
                    skew_rows = list(pvl_client.query(skew_query, job_config=pvl_config).result())
                    for skew_row in skew_rows:
                        s_total = skew_row.total or 0
                        s_overs = skew_row.overs or 0
                        s_unders = skew_row.unders or 0
                        if s_total >= 10:
                            over_pct = s_overs / s_total * 100
                            under_pct = s_unders / s_total * 100
                            if over_pct < 15 or under_pct < 15:
                                send_recommendation_skew_alert(
                                    game_date=game_date,
                                    run_mode=skew_row.prediction_run_mode or 'UNKNOWN',
                                    overs=s_overs,
                                    unders=s_unders,
                                    total=s_total,
                                )
                            else:
                                logger.info(
                                    f"Recommendation skew OK: {over_pct:.0f}% OVER / {under_pct:.0f}% UNDER "
                                    f"({skew_row.prediction_run_mode})"
                                )

                    # Session 171: Monitor vegas_source distribution (recovery_median frequency)
                    vegas_src_query = f"""
                    SELECT
                        JSON_EXTRACT_SCALAR(features_snapshot, '$.vegas_source') as source,
                        COUNT(*) as cnt
                    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
                    WHERE game_date = @game_date
                      AND system_id = 'catboost_v9'
                      AND is_active = TRUE
                    GROUP BY 1
                    """
                    vegas_src_rows = list(pvl_client.query(vegas_src_query, job_config=pvl_config).result())
                    source_counts = {}
                    src_total = 0
                    for vs_row in vegas_src_rows:
                        source = vs_row.source or 'unknown'
                        source_counts[source] = vs_row.cnt
                        src_total += vs_row.cnt
                    recovery_count = source_counts.get('recovery_median', 0)
                    if src_total > 0 and recovery_count / src_total > 0.30:
                        send_vegas_source_alert(
                            game_date=game_date,
                            run_mode='UNKNOWN',
                            source_counts=source_counts,
                            total=src_total,
                        )
                    elif src_total > 0:
                        logger.info(
                            f"Vegas source check OK: recovery_median={recovery_count}/{src_total} "
                            f"({recovery_count/src_total*100:.0f}%)"
                        )
                    else:
                        logger.info("Vegas source check: no predictions found")

                    # Session 176: Check recommendation direction alignment
                    direction_query = f"""
                    SELECT
                        COUNTIF(predicted_points > current_points_line AND recommendation = 'UNDER') as above_but_under,
                        COUNTIF(predicted_points < current_points_line AND recommendation = 'OVER') as below_but_over,
                        COUNT(*) as total,
                        prediction_run_mode
                    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
                    WHERE game_date = @game_date
                      AND system_id = 'catboost_v9'
                      AND is_active = TRUE
                      AND current_points_line IS NOT NULL
                    GROUP BY prediction_run_mode
                    """
                    dir_rows = list(pvl_client.query(direction_query, job_config=pvl_config).result())
                    for dir_row in dir_rows:
                        abu = dir_row.above_but_under or 0
                        bbo = dir_row.below_but_over or 0
                        d_total = dir_row.total or 0
                        if abu + bbo > 0:
                            send_direction_mismatch_alert(
                                game_date=game_date,
                                run_mode=dir_row.prediction_run_mode or 'UNKNOWN',
                                above_but_under=abu,
                                below_but_over=bbo,
                                total=d_total,
                            )
                        else:
                            logger.info(
                                f"Direction alignment OK: 0 mismatches out of {d_total} "
                                f"({dir_row.prediction_run_mode})"
                            )

                except Exception as pvl_err:
                    logger.warning(f"Post-consolidation quality checks failed (non-fatal): {pvl_err}")

                # Step 1.5: Calculate daily prediction signals (Session 71)
                try:
                    logger.info(f"Calculating daily prediction signals for {game_date}...")
                    signal_result = calculate_daily_signals(game_date=game_date)
                    if signal_result['success']:
                        logger.info(
                            f"Daily signals calculated: {signal_result['systems_processed']} systems"
                        )
                    else:
                        logger.warning(
                            f"Signal calculation failed (non-fatal): {signal_result.get('error')}"
                        )
                except Exception as signal_err:
                    # Don't fail batch if signal calculation fails
                    logger.warning(f"Signal calculation failed (non-fatal): {signal_err}")
            else:
                logger.error(f"❌ Consolidation failed: {consolidation_result.error_message}", exc_info=True)
                summary['consolidation'] = {
                    'success': False,
                    'error': consolidation_result.error_message
                }
        except Exception as e:
            # Don't fail the batch summary if consolidation fails
            logger.error(f"Consolidation failed (non-fatal): {e}", exc_info=True)
            summary['consolidation'] = {'success': False, 'error': str(e)}

        # Check prediction coverage and send alerts if below thresholds
        try:
            coverage_monitor = PredictionCoverageMonitor(project_id=PROJECT_ID)
            expected_players = summary.get('expected', 0)
            completed_players = summary.get('completed', 0)

            coverage_ok = coverage_monitor.check_coverage(
                players_expected=expected_players,
                players_predicted=completed_players,
                game_date=current_game_date or date.today(),
                batch_id=batch_id,
                additional_context={
                    'correlation_id': current_correlation_id,
                    'failed_players': summary.get('failed', 0)
                }
            )

            # Track missing players if coverage is not 100%
            if completed_players < expected_players:
                # Get the sets from tracker for detailed missing player tracking
                expected_set = tracker.get_expected_players() if hasattr(tracker, 'get_expected_players') else set()
                completed_set = tracker.completed_players if hasattr(tracker, 'completed_players') else set()

                if expected_set and completed_set:
                    missing_players = coverage_monitor.track_missing_players(
                        expected_set=expected_set,
                        predicted_set=completed_set,
                        game_date=current_game_date or date.today(),
                        log_all=False  # Only log summary for large sets
                    )
                    if missing_players:
                        logger.info(f"Coverage monitor identified {len(missing_players)} missing players")

            logger.info(f"Coverage check complete: {'PASSED' if coverage_ok else 'BELOW THRESHOLD'}")
        except Exception as e:
            # Don't fail the batch summary if coverage monitoring fails
            logger.warning(f"Coverage monitoring failed (non-fatal): {e}")

        # Determine status based on completion
        if summary.get('completed', 0) == summary.get('expected', 0):
            status = 'success'
        elif summary.get('completed', 0) > 0:
            status = 'partial'
        else:
            status = 'failed'

        # Log batch completion to processor_run_history for unified monitoring
        try:
            get_run_history().complete_batch(
                status=status,
                records_processed=summary.get('completed', 0),
                records_failed=summary.get('failed', 0),
                duration_seconds=summary.get('duration_seconds', 0),
                summary=summary
            )
        except Exception as e:
            # Don't fail the batch if run history logging fails
            logger.warning(f"Failed to log batch completion (non-fatal): {e}")

        # Publish unified message
        message_id = unified_publisher.publish_completion(
            topic='nba-phase5-predictions-complete',
            processor_name='PredictionCoordinator',
            phase='phase_5_predictions',
            execution_id=batch_id,
            correlation_id=current_correlation_id or batch_id,
            game_date=game_date,
            output_table='player_prop_predictions',
            output_dataset='nba_predictions',
            status=status,
            record_count=summary.get('completed', 0),
            records_failed=summary.get('failed', 0),
            parent_processor=None,  # Could track Phase 4 processor
            trigger_source='scheduler',
            trigger_message_id=None,
            duration_seconds=summary.get('duration_seconds', 0),
            error_message=None,
            error_type=None,
            metadata={
                # Phase 5 specific metadata
                'batch_id': batch_id,
                'expected_predictions': summary.get('expected', 0),
                'completed_predictions': summary.get('completed', 0),
                'failed_predictions': summary.get('failed', 0),
                'completion_pct': summary.get('completion_pct', 0),
                'stall_detected': summary.get('stall_detected', False),

                # Include full summary
                'summary': summary
            },
            skip_downstream=False
        )

        if message_id:
            logger.info(
                f"✅ Published unified batch summary for {batch_id} "
                f"(message_id={message_id}, correlation_id={current_correlation_id})"
            )
            logger.info(f"Summary: {json.dumps(summary, indent=2)}")
        else:
            logger.error("Failed to publish batch summary")

        # Send prediction completion email
        send_prediction_completion_email(summary, game_date, batch_id)

    except Exception as e:
        logger.error(f"Error publishing batch summary: {e}", exc_info=True)


if __name__ == '__main__':
    # For local testing
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)

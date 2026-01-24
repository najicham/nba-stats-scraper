"""
NBA Admin Dashboard - Pipeline Orchestration Monitoring

A Flask-based admin dashboard for monitoring the NBA Props pipeline.
Shows phase completion status, errors, scheduler history, and allows manual actions.
"""

import os
import sys
import json
import logging
import secrets
import urllib.request
import threading
import time
import hashlib
from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo
from flask import Flask, render_template, jsonify, request
import requests
from google.cloud import bigquery

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Validate required environment variables at startup
# Import path setup needed before shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from shared.utils.env_validation import validate_required_env_vars
from shared.endpoints.health import create_health_blueprint, HealthChecker
validate_required_env_vars(
    ['GCP_PROJECT_ID', 'ADMIN_DASHBOARD_API_KEY'],
    service_name='AdminDashboard'
)


# =============================================================================
# RATE LIMITING (P1-DASH-2)
# =============================================================================

class InMemoryRateLimiter:
    """
    Simple in-memory rate limiter using sliding window approach.

    Limits requests per IP address within a configurable time window.
    Includes automatic cleanup of expired entries to prevent memory leaks.
    """

    def __init__(self, requests_per_minute: int = 100, cleanup_interval_seconds: int = 60):
        """
        Initialize rate limiter.

        Args:
            requests_per_minute: Maximum requests allowed per minute per IP
            cleanup_interval_seconds: How often to clean up expired entries
        """
        self.requests_per_minute = requests_per_minute
        self.window_seconds = 60  # 1 minute window
        self.cleanup_interval = cleanup_interval_seconds

        # Dict of IP -> list of request timestamps
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def _cleanup_expired(self) -> None:
        """Remove expired entries from the rate limit tracker."""
        current_time = time.time()
        cutoff_time = current_time - self.window_seconds

        # Only cleanup periodically to avoid overhead
        if current_time - self._last_cleanup < self.cleanup_interval:
            return

        with self._lock:
            self._last_cleanup = current_time
            # Remove IPs with no recent requests
            expired_ips = []
            for ip, timestamps in self._requests.items():
                # Filter to only recent timestamps
                recent = [t for t in timestamps if t > cutoff_time]
                if recent:
                    self._requests[ip] = recent
                else:
                    expired_ips.append(ip)

            for ip in expired_ips:
                del self._requests[ip]

            if expired_ips:
                logger.debug(f"Rate limiter cleanup: removed {len(expired_ips)} expired IPs")

    def is_allowed(self, ip: str) -> tuple[bool, int]:
        """
        Check if a request from the given IP is allowed.

        Args:
            ip: The client IP address

        Returns:
            Tuple of (is_allowed, remaining_requests)
        """
        current_time = time.time()
        cutoff_time = current_time - self.window_seconds

        # Trigger cleanup periodically
        self._cleanup_expired()

        with self._lock:
            if ip not in self._requests:
                self._requests[ip] = []

            # Filter to only timestamps within the window
            recent_requests = [t for t in self._requests[ip] if t > cutoff_time]

            if len(recent_requests) >= self.requests_per_minute:
                # Rate limit exceeded
                self._requests[ip] = recent_requests
                return False, 0

            # Allow request and record timestamp
            recent_requests.append(current_time)
            self._requests[ip] = recent_requests
            remaining = self.requests_per_minute - len(recent_requests)
            return True, remaining

    def get_retry_after(self, ip: str) -> int:
        """
        Get the number of seconds until the client can retry.

        Args:
            ip: The client IP address

        Returns:
            Seconds until the oldest request in the window expires
        """
        current_time = time.time()
        cutoff_time = current_time - self.window_seconds

        with self._lock:
            if ip not in self._requests:
                return 0

            recent_requests = [t for t in self._requests[ip] if t > cutoff_time]
            if not recent_requests:
                return 0

            # Time until oldest request expires
            oldest = min(recent_requests)
            return max(1, int((oldest + self.window_seconds) - current_time))


# Initialize rate limiter: 100 requests per minute per IP
rate_limiter = InMemoryRateLimiter(requests_per_minute=100)


# =============================================================================
# AUDIT LOGGING (P2-DASH-3)
# =============================================================================

class AuditLogger:
    """
    Logs admin actions to BigQuery for audit trail.

    Writes to nba_analytics.admin_audit_log table with fields:
    - timestamp: When the action occurred
    - user_ip: Client IP address
    - action_type: Type of action (force_predictions, retry_phase, trigger_self_heal)
    - endpoint: The API endpoint called
    - parameters: JSON string of request parameters
    - result: success/failure/error
    - api_key_hash: Last 8 characters of API key hash for identification
    """

    TABLE_ID = 'nba-props-platform.nba_analytics.admin_audit_log'

    def __init__(self):
        self._client = None
        self._table = None
        self._initialized = False

    @property
    def client(self):
        """Lazy initialization of BigQuery client."""
        if self._client is None:
            try:
                project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
                self._client = bigquery.Client(project=project_id)
            except Exception as e:
                logger.warning(f"Failed to initialize BigQuery client for audit logging: {e}")
        return self._client

    def _get_api_key_hash(self) -> str:
        """
        Get a safe hash identifier for the API key used in the request.

        Returns last 8 characters of SHA256 hash for identification without exposing the key.
        """
        # Check header first
        provided_key = request.headers.get('X-API-Key')
        if not provided_key:
            # Check query param
            provided_key = request.args.get('key')

        if not provided_key:
            return 'no_key'

        # Hash the key and return last 8 chars
        key_hash = hashlib.sha256(provided_key.encode()).hexdigest()
        return key_hash[-8:]

    def log_action(
        self,
        action_type: str,
        endpoint: str,
        parameters: dict,
        result: str,
        user_ip: str = None
    ) -> bool:
        """
        Log an admin action to BigQuery.

        Args:
            action_type: Type of action (e.g., 'force_predictions', 'retry_phase')
            endpoint: The API endpoint path
            parameters: Request parameters as dict
            result: Result of the action ('success', 'failure', 'error')
            user_ip: Client IP (optional, will be auto-detected if not provided)

        Returns:
            True if logged successfully, False otherwise
        """
        if self.client is None:
            logger.warning("Audit logging skipped: BigQuery client not available")
            return False

        try:
            # Build the audit record
            timestamp = datetime.now(ZoneInfo('UTC'))

            row = {
                'timestamp': timestamp.isoformat(),
                'user_ip': user_ip or get_client_ip(),
                'action_type': action_type,
                'endpoint': endpoint,
                'parameters': json.dumps(parameters) if parameters else '{}',
                'result': result,
                'api_key_hash': self._get_api_key_hash()
            }

            # Insert the row using streaming insert
            errors = self.client.insert_rows_json(
                self.TABLE_ID,
                [row]
            )

            if errors:
                logger.error(f"Failed to insert audit log: {errors}")
                return False

            logger.debug(f"Audit log recorded: {action_type} -> {result}")
            return True

        except Exception as e:
            # Log the error but don't fail the main request
            logger.error(f"Error writing audit log to BigQuery: {e}")
            return False


# Initialize audit logger
audit_logger = AuditLogger()


def get_client_ip() -> str:
    """
    Get the client's IP address, handling proxy headers.

    Returns:
        The client IP address
    """
    # Check for forwarded headers (when behind load balancer/proxy)
    if request.headers.get('X-Forwarded-For'):
        # X-Forwarded-For can contain multiple IPs; first is the client
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    else:
        return request.remote_addr or 'unknown'


def rate_limit(f):
    """
    Decorator to apply rate limiting to an endpoint.

    Returns 429 Too Many Requests when rate limit is exceeded.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_ip = get_client_ip()
        allowed, remaining = rate_limiter.is_allowed(client_ip)

        if not allowed:
            retry_after = rate_limiter.get_retry_after(client_ip)
            logger.warning(f"Rate limit exceeded for IP {client_ip}")

            response = jsonify({
                'error': 'Too Many Requests',
                'message': f'Rate limit exceeded. Maximum {rate_limiter.requests_per_minute} requests per minute.',
                'retry_after': retry_after
            })
            response.status_code = 429
            response.headers['Retry-After'] = str(retry_after)
            response.headers['X-RateLimit-Limit'] = str(rate_limiter.requests_per_minute)
            response.headers['X-RateLimit-Remaining'] = '0'
            return response

        # Execute the endpoint
        response = f(*args, **kwargs)

        # Add rate limit headers to successful responses
        if hasattr(response, 'headers'):
            response.headers['X-RateLimit-Limit'] = str(rate_limiter.requests_per_minute)
            response.headers['X-RateLimit-Remaining'] = str(remaining)

        return response

    return decorated_function


app = Flask(__name__)

# Health check endpoints (Phase 1 - Task 1.1: Add Health Endpoints)
# Note: HealthChecker simplified in Week 1 to only require service_name
app.register_blueprint(create_health_blueprint('admin-dashboard'))
logger.info("Health check endpoints registered: /health, /ready, /health/deep")

# Prometheus metrics endpoint
# Initialize metrics collector for this service
prometheus_metrics = PrometheusMetrics(service_name='admin-dashboard', version='1.0.0')
app.register_blueprint(create_metrics_blueprint(prometheus_metrics))
logger.info("Prometheus metrics endpoint registered: /metrics, /metrics/json")

# Register custom metrics for admin dashboard
dashboard_api_requests = prometheus_metrics.register_counter(
    'dashboard_api_requests_total',
    'Total dashboard API requests by endpoint',
    ['endpoint', 'sport']
)
dashboard_action_requests = prometheus_metrics.register_counter(
    'dashboard_action_requests_total',
    'Total admin action requests',
    ['action_type', 'result']
)
pipeline_status_checks = prometheus_metrics.register_counter(
    'pipeline_status_checks_total',
    'Total pipeline status checks',
    ['sport', 'date_type']
)

# Import services
from services.bigquery_service import BigQueryService
from services.firestore_service import FirestoreService
from services.logging_service import LoggingService

# Initialize services
bq_service = BigQueryService()
firestore_service = FirestoreService()
logging_service = LoggingService()

# API Key for simple authentication (required in production)
API_KEY = os.environ.get('ADMIN_DASHBOARD_API_KEY')
if not API_KEY:
    logger.warning("ADMIN_DASHBOARD_API_KEY not set - all authenticated requests will be rejected")

# Pipeline Reconciliation Function URL (R-007)
RECONCILIATION_FUNCTION_URL = os.environ.get(
    'RECONCILIATION_FUNCTION_URL',
    'https://pipeline-reconciliation-f7p3g7f6ya-wl.a.run.app'
)

# Cloud Run service URLs (sport-specific)
SERVICE_URLS = {
    'nba': {
        'prediction_coordinator': 'https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app',
        'phase3_analytics': 'https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app',
        'phase4_precompute': 'https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app',
        'self_heal': 'https://self-heal-f7p3g7f6ya-wl.a.run.app',
    },
    'mlb': {
        'prediction_worker': 'https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app',
        'phase3_analytics': 'https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app',
        'phase4_precompute': 'https://mlb-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app',
        'phase6_grading': 'https://mlb-phase6-grading-f7p3g7f6ya-wl.a.run.app',
        'self_heal': 'https://mlb-self-heal-f7p3g7f6ya-wl.a.run.app',
    }
}

# Supported sports
SUPPORTED_SPORTS = ['nba', 'mlb']
DEFAULT_SPORT = 'nba'


def get_sport_from_request() -> str:
    """Get sport parameter from request, defaulting to NBA."""
    sport = request.args.get('sport', DEFAULT_SPORT).lower()
    if sport not in SUPPORTED_SPORTS:
        sport = DEFAULT_SPORT
    return sport


def get_service_for_sport(sport: str) -> tuple:
    """
    Get BigQuery and Firestore services for a specific sport.

    Returns:
        Tuple of (BigQueryService, FirestoreService)
    """
    return BigQueryService(sport=sport), FirestoreService(sport=sport)


def get_auth_token(audience: str) -> str:
    """
    Get identity token for authenticated service calls using metadata server.
    Only works when running in GCP (Cloud Run/Cloud Functions).

    Args:
        audience: The URL of the service to call

    Returns:
        Identity token string
    """
    metadata_url = f"http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience={audience}"
    req = urllib.request.Request(metadata_url, headers={"Metadata-Flavor": "Google"})

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode("utf-8")
    except Exception as e:
        logger.warning(f"Could not get auth token (expected in local dev): {e}")
        return None


def call_cloud_run_service(service_key: str, endpoint: str, method: str = 'POST',
                           payload: dict = None, timeout: int = 120,
                           sport: str = 'nba') -> dict:
    """
    Make an authenticated call to a Cloud Run service.

    Args:
        service_key: Key in SERVICE_URLS dict
        endpoint: Endpoint path (e.g., '/start', '/process-date')
        method: HTTP method
        payload: JSON payload for POST requests
        timeout: Request timeout in seconds
        sport: 'nba' or 'mlb'

    Returns:
        Dict with 'success', 'status_code', 'response', and 'error' keys
    """
    sport_urls = SERVICE_URLS.get(sport, SERVICE_URLS['nba'])
    if service_key not in sport_urls:
        return {'success': False, 'error': f'Unknown service: {service_key} for sport: {sport}'}

    base_url = sport_urls[service_key]
    url = f"{base_url}{endpoint}"

    # Get auth token
    token = get_auth_token(base_url)

    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'

    try:
        if method.upper() == 'POST':
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        else:
            response = requests.get(url, headers=headers, timeout=timeout)

        return {
            'success': response.status_code in (200, 201, 202),
            'status_code': response.status_code,
            'response': response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
        }
    except requests.exceptions.Timeout:
        return {'success': False, 'error': 'Request timed out'}
    except requests.exceptions.RequestException as e:
        return {'success': False, 'error': str(e)}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def check_auth():
    """Check API key authentication."""
    # Allow unauthenticated access in dev mode
    if os.environ.get('FLASK_ENV') == 'development':
        return True

    # Reject all requests if API key not configured
    if not API_KEY:
        logger.error("Authentication failed: ADMIN_DASHBOARD_API_KEY not configured")
        return False

    # Check header
    provided_key = request.headers.get('X-API-Key')
    if provided_key and secrets.compare_digest(provided_key, API_KEY):
        return True

    # Check query param (for browser access)
    provided_key = request.args.get('key')
    if provided_key and secrets.compare_digest(provided_key, API_KEY):
        return True

    return False


def get_et_dates():
    """Get today and tomorrow in ET timezone."""
    et = ZoneInfo('America/New_York')
    now_et = datetime.now(et)
    today = now_et.date()
    tomorrow = today + timedelta(days=1)
    return today, tomorrow, now_et


def clamp_param(value: int, min_val: int, max_val: int, default: int) -> int:
    """
    Clamp a query parameter to safe bounds.

    Prevents abuse via extremely large values that could cause expensive queries.

    Args:
        value: The input value
        min_val: Minimum allowed value
        max_val: Maximum allowed value
        default: Default if value is None

    Returns:
        Clamped value within bounds
    """
    if value is None:
        return default
    return max(min_val, min(max_val, value))


# Query parameter bounds (prevent abuse)
PARAM_BOUNDS = {
    'limit': (1, 100, 20),      # min, max, default
    'hours': (1, 168, 24),      # max 7 days
    'days': (1, 90, 7),         # max 90 days
}


# =============================================================================
# HEALTH CHECK ENDPOINTS
# =============================================================================

@app.route('/')
@rate_limit
def index():
    """Root endpoint - basic service info."""
    return jsonify({
        'status': 'healthy',
        'service': 'admin-dashboard',
        'supported_sports': SUPPORTED_SPORTS,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })

# /health endpoint now provided by shared health blueprint (see initialization above)
# The blueprint provides: /health (liveness), /ready (readiness), /health/deep (deep checks)


# =============================================================================
# DASHBOARD PAGES
# =============================================================================

@app.route('/dashboard')
@rate_limit
def dashboard():
    """Main dashboard page - supports both NBA and MLB via ?sport= parameter."""
    if not check_auth():
        return render_template('auth_required.html'), 401

    sport = get_sport_from_request()
    bq_svc, fs_svc = get_service_for_sport(sport)

    today, tomorrow, now_et = get_et_dates()

    # Get pipeline status for today and tomorrow
    try:
        if sport == 'mlb':
            today_status = bq_svc.get_mlb_daily_status(today)
            tomorrow_status = bq_svc.get_mlb_daily_status(tomorrow)
        else:
            today_status = bq_svc.get_daily_status(today)
            tomorrow_status = bq_svc.get_daily_status(tomorrow)
    except Exception as e:
        logger.error(f"Error fetching {sport} status: {e}")
        today_status = None
        tomorrow_status = None

    # Get recent errors
    try:
        recent_errors = logging_service.get_recent_errors(limit=10)
    except Exception as e:
        logger.error(f"Error fetching errors: {e}")
        recent_errors = []

    # Get reliability summary for status card banner (R-007)
    reliability_summary = None
    reliability_gaps = 0
    try:
        yesterday = (datetime.now(ZoneInfo('America/New_York')).date() - timedelta(days=1)).strftime('%Y-%m-%d')
        response = requests.get(
            f"{RECONCILIATION_FUNCTION_URL}?date={yesterday}",
            timeout=10
        )
        if response.ok:
            r007_data = response.json()
            reliability_summary = {
                'r007': {
                    'date': yesterday,
                    'gaps_found': r007_data.get('gaps_found', 0),
                    'status': r007_data.get('status', 'UNKNOWN'),
                    'high_severity_count': len([
                        g for g in r007_data.get('gaps', [])
                        if g.get('severity') == 'HIGH'
                    ])
                }
            }
            reliability_gaps = r007_data.get('gaps_found', 0)
    except Exception as e:
        logger.warning(f"Failed to fetch reliability summary: {e}")

    return render_template(
        'dashboard.html',
        sport=sport,
        supported_sports=SUPPORTED_SPORTS,
        today=today,
        tomorrow=tomorrow,
        now_et=now_et,
        today_status=today_status,
        tomorrow_status=tomorrow_status,
        recent_errors=recent_errors,
        reliability_summary=reliability_summary,
        reliability_gaps=reliability_gaps
    )


# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.route('/api/status')
@rate_limit
def api_status():
    """Get current pipeline status for today and tomorrow - supports ?sport= parameter."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    sport = get_sport_from_request()
    bq_svc, _ = get_service_for_sport(sport)
    today, tomorrow, now_et = get_et_dates()

    # Track metrics
    dashboard_api_requests.inc(labels={'endpoint': '/api/status', 'sport': sport})
    pipeline_status_checks.inc(labels={'sport': sport, 'date_type': 'today_tomorrow'})

    try:
        if sport == 'mlb':
            today_status = bq_svc.get_mlb_daily_status(today)
            tomorrow_status = bq_svc.get_mlb_daily_status(tomorrow)
            today_games = bq_svc.get_mlb_games_detail(today)
            tomorrow_games = bq_svc.get_mlb_games_detail(tomorrow)
        else:
            today_status = bq_svc.get_daily_status(today)
            tomorrow_status = bq_svc.get_daily_status(tomorrow)
            today_games = bq_svc.get_games_detail(today)
            tomorrow_games = bq_svc.get_games_detail(tomorrow)

        return jsonify({
            'sport': sport,
            'timestamp': now_et.isoformat(),
            'today': {
                'date': today.isoformat(),
                'status': today_status,
                'games': today_games
            },
            'tomorrow': {
                'date': tomorrow.isoformat(),
                'status': tomorrow_status,
                'games': tomorrow_games
            }
        })
    except Exception as e:
        logger.error(f"Error in api_status for {sport}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/games/<date>')
@rate_limit
def api_games(date):
    """Get detailed game status for a specific date."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        from datetime import date as date_type
        target_date = date_type.fromisoformat(date)
        games = bq_service.get_games_detail(target_date)
        return jsonify({'date': date, 'games': games})
    except Exception as e:
        logger.error(f"Error in api_games: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/errors')
@rate_limit
def api_errors():
    """Get recent errors from Cloud Logging."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        limit = clamp_param(request.args.get('limit', type=int), *PARAM_BOUNDS['limit'])
        hours = clamp_param(request.args.get('hours', type=int), *PARAM_BOUNDS['hours'])
        errors = logging_service.get_recent_errors(limit=limit, hours=hours)
        return jsonify({'errors': errors})
    except Exception as e:
        logger.error(f"Error in api_errors: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/orchestration/<date>')
@rate_limit
def api_orchestration(date):
    """Get orchestration state from Firestore."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        phase3_state = firestore_service.get_phase_completion('phase3_completion', date)
        phase4_state = firestore_service.get_phase_completion('phase4_completion', date)

        return jsonify({
            'date': date,
            'phase3': phase3_state,
            'phase4': phase4_state
        })
    except Exception as e:
        logger.error(f"Error in api_orchestration: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/schedulers')
@rate_limit
def api_schedulers():
    """Get scheduler job status and recent runs."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        schedulers = logging_service.get_scheduler_history(hours=12)
        return jsonify({'schedulers': schedulers})
    except Exception as e:
        logger.error(f"Error in api_schedulers: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/stuck-processors')
@rate_limit
def api_stuck_processors():
    """
    Get processors that are stuck (running > 30 minutes).

    Returns:
        JSON with list of stuck processors and count
    """
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        stuck_processors = firestore_service.get_run_history_stuck()
        return jsonify({
            'stuck_processors': stuck_processors,
            'count': len(stuck_processors),
            'threshold_minutes': 30
        })
    except Exception as e:
        logger.error(f"Error in api_stuck_processors: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/firestore-health')
@rate_limit
def api_firestore_health():
    """
    Get Firestore health status including connectivity, latency, and stuck processors.

    Returns:
        JSON with Firestore health metrics
    """
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        from monitoring.firestore_health_check import FirestoreHealthMonitor

        monitor = FirestoreHealthMonitor()
        health_result = monitor.check_health()

        return jsonify({
            'status': health_result.get('status', 'unknown'),
            'connectivity': health_result.get('connectivity', {}),
            'write_latency_ms': health_result.get('write_latency_ms'),
            'stuck_processors': health_result.get('stuck_processors', []),
            'stuck_count': health_result.get('stuck_count', 0),
            'phase_staleness': health_result.get('phase_staleness', {}),
            'checked_at': datetime.now().isoformat()
        })
    except ImportError as e:
        logger.error(f"Failed to import FirestoreHealthMonitor: {e}")
        return jsonify({
            'status': 'error',
            'error': 'Health monitor not available',
            'checked_at': datetime.now().isoformat()
        }), 503
    except Exception as e:
        logger.error(f"Error in api_firestore_health: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/history')
@rate_limit
def api_history():
    """Get historical pipeline status for the last 7 days."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        history = bq_service.get_pipeline_history(days=7)
        return jsonify({'history': history})
    except Exception as e:
        logger.error(f"Error in api_history: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# HTMX PARTIAL ENDPOINTS
# =============================================================================

@app.route('/partials/status-cards')
@rate_limit
def partial_status_cards():
    """HTMX partial: Status cards for today and tomorrow."""
    if not check_auth():
        return '<div class="text-red-500">Unauthorized</div>', 401

    sport = get_sport_from_request()
    bq_svc, _ = get_service_for_sport(sport)
    today, tomorrow, now_et = get_et_dates()

    try:
        if sport == 'mlb':
            today_status = bq_svc.get_mlb_daily_status(today)
            tomorrow_status = bq_svc.get_mlb_daily_status(tomorrow)
        else:
            today_status = bq_svc.get_daily_status(today)
            tomorrow_status = bq_svc.get_daily_status(tomorrow)
    except Exception as e:
        return f'<div class="text-red-500">Error: {e}</div>', 500

    # Get reliability summary for banner
    reliability_summary = None
    try:
        yesterday = (datetime.now(ZoneInfo('America/New_York')).date() - timedelta(days=1)).strftime('%Y-%m-%d')
        response = requests.get(
            f"{RECONCILIATION_FUNCTION_URL}?date={yesterday}",
            timeout=10
        )
        if response.ok:
            r007_data = response.json()
            reliability_summary = {
                'r007': {
                    'date': yesterday,
                    'gaps_found': r007_data.get('gaps_found', 0),
                    'status': r007_data.get('status', 'UNKNOWN'),
                    'high_severity_count': len([
                        g for g in r007_data.get('gaps', [])
                        if g.get('severity') == 'HIGH'
                    ])
                }
            }
    except Exception as e:
        logger.warning(f"Failed to fetch reliability summary for status cards: {e}")

    return render_template(
        'components/status_cards.html',
        today=today,
        tomorrow=tomorrow,
        today_status=today_status,
        tomorrow_status=tomorrow_status,
        reliability_summary=reliability_summary
    )


@app.route('/partials/games-table/<date>')
@rate_limit
def partial_games_table(date):
    """HTMX partial: Games table for a specific date."""
    if not check_auth():
        return '<div class="text-red-500">Unauthorized</div>', 401

    try:
        from datetime import date as date_type
        target_date = date_type.fromisoformat(date)
        games = bq_service.get_games_detail(target_date)
    except Exception as e:
        return f'<div class="text-red-500">Error: {e}</div>', 500

    return render_template(
        'components/games_table.html',
        date=date,
        games=games
    )


@app.route('/partials/error-feed')
@rate_limit
def partial_error_feed():
    """HTMX partial: Recent errors feed."""
    if not check_auth():
        return '<div class="text-red-500">Unauthorized</div>', 401

    try:
        errors = logging_service.get_recent_errors(limit=10)
    except Exception as e:
        return f'<div class="text-red-500">Error: {e}</div>', 500

    return render_template('components/error_feed.html', errors=errors)


@app.route('/api/processor-failures')
@rate_limit
def api_processor_failures():
    """Get recent processor failures."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    hours = clamp_param(request.args.get('hours', type=int), *PARAM_BOUNDS['hours'])
    try:
        failures = bq_service.get_processor_failures(hours=hours)
        return jsonify({'failures': failures, 'count': len(failures)})
    except Exception as e:
        logger.error(f"Error in api_processor_failures: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/partials/processor-failures')
@rate_limit
def partial_processor_failures():
    """HTMX partial: Processor failures display."""
    if not check_auth():
        return '<div class="text-red-500">Unauthorized</div>', 401

    hours = clamp_param(request.args.get('hours', type=int), *PARAM_BOUNDS['hours'])
    try:
        failures = bq_service.get_processor_failures(hours=hours)
    except Exception as e:
        return f'<div class="text-red-500">Error: {e}</div>', 500

    return render_template('components/processor_failures.html', failures=failures)


@app.route('/api/coverage-metrics')
@rate_limit
def api_coverage_metrics():
    """Get coverage metrics for recent days."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    days = clamp_param(request.args.get('days', type=int), *PARAM_BOUNDS['days'])
    try:
        coverage = bq_service.get_player_game_summary_coverage(days=days)
        grading = bq_service.get_grading_status(days=days)
        return jsonify({
            'player_game_summary_coverage': coverage,
            'grading_status': grading
        })
    except Exception as e:
        logger.error(f"Error in api_coverage_metrics: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/partials/coverage-metrics')
@rate_limit
def partial_coverage_metrics():
    """HTMX partial: Coverage metrics display."""
    if not check_auth():
        return '<div class="text-red-500">Unauthorized</div>', 401

    days = clamp_param(request.args.get('days', type=int), *PARAM_BOUNDS['days'])
    try:
        coverage = bq_service.get_player_game_summary_coverage(days=days)
        grading = bq_service.get_grading_status(days=days)
    except Exception as e:
        return f'<div class="text-red-500">Error: {e}</div>', 500

    return render_template(
        'components/coverage_metrics.html',
        coverage=coverage,
        grading=grading
    )


@app.route('/partials/calibration')
@rate_limit
def partial_calibration():
    """HTMX partial: Calibration analysis display."""
    if not check_auth():
        return '<div class="text-red-500">Unauthorized</div>', 401

    days = clamp_param(request.args.get('days', type=int), *PARAM_BOUNDS['days'])
    try:
        calibration_summary = bq_service.get_calibration_summary(days=days)
        calibration_data = bq_service.get_calibration_data(days=days)
    except Exception as e:
        return f'<div class="text-red-500">Error loading calibration data: {e}</div>', 500

    return render_template(
        'components/calibration.html',
        calibration_summary=calibration_summary,
        calibration_data=calibration_data,
        days=days
    )


@app.route('/partials/roi')
@rate_limit
def partial_roi():
    """HTMX partial: ROI analysis display."""
    if not check_auth():
        return '<div class="text-red-500">Unauthorized</div>', 401

    days = clamp_param(request.args.get('days', type=int), *PARAM_BOUNDS['days'])
    try:
        roi_summary = bq_service.get_roi_summary(days=days)
    except Exception as e:
        return f'<div class="text-red-500">Error loading ROI data: {e}</div>', 500

    return render_template(
        'components/roi_analysis.html',
        roi_summary=roi_summary,
        days=days
    )


@app.route('/partials/player-insights')
@rate_limit
def partial_player_insights():
    """HTMX partial: Player insights display."""
    if not check_auth():
        return '<div class="text-red-500">Unauthorized</div>', 401

    try:
        insights = bq_service.get_player_insights(limit_top=10, limit_bottom=10)
    except Exception as e:
        return f'<div class="text-red-500">Error loading player insights: {e}</div>', 500

    return render_template(
        'components/player_insights.html',
        most_predictable=insights['most_predictable'],
        least_predictable=insights['least_predictable']
    )


@app.route('/partials/system-performance')
@rate_limit
def partial_system_performance():
    """HTMX partial: System performance display."""
    if not check_auth():
        return '<div class="text-red-500">Unauthorized</div>', 401

    return render_template('components/system_performance.html')


@app.route('/api/grading-by-system')
@rate_limit
def api_grading_by_system():
    """Get grading breakdown by prediction system."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    days = clamp_param(request.args.get('days', type=int), *PARAM_BOUNDS['days'])
    try:
        grading_by_system = bq_service.get_grading_by_system(days=days)
        return jsonify({
            'grading_by_system': grading_by_system,
            'days': days
        })
    except Exception as e:
        logger.error(f"Error in api_grading_by_system: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/calibration-data')
@rate_limit
def api_calibration_data():
    """Get detailed calibration data by system and confidence bucket."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    days = clamp_param(request.args.get('days', type=int), *PARAM_BOUNDS['days'])
    try:
        calibration_data = bq_service.get_calibration_data(days=days)
        return jsonify({
            'calibration_data': calibration_data,
            'days': days
        })
    except Exception as e:
        logger.error(f"Error in api_calibration_data: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/calibration-summary')
@rate_limit
def api_calibration_summary():
    """Get calibration health summary for all systems."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    days = clamp_param(request.args.get('days', type=int), *PARAM_BOUNDS['days'])
    try:
        calibration_summary = bq_service.get_calibration_summary(days=days)
        return jsonify({
            'calibration_summary': calibration_summary,
            'days': days
        })
    except Exception as e:
        logger.error(f"Error in api_calibration_summary: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/roi-summary')
@rate_limit
def api_roi_summary():
    """Get ROI summary with flat betting and confidence-based strategies."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    days = clamp_param(request.args.get('days', type=int), *PARAM_BOUNDS['days'])
    try:
        roi_summary = bq_service.get_roi_summary(days=days)
        return jsonify({
            'roi_summary': roi_summary,
            'days': days
        })
    except Exception as e:
        logger.error(f"Error in api_roi_summary: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/roi-daily')
@rate_limit
def api_roi_daily():
    """Get daily ROI breakdown by system."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    days = clamp_param(request.args.get('days', type=int), *PARAM_BOUNDS['days'])
    try:
        roi_daily = bq_service.get_roi_daily_breakdown(days=days)
        return jsonify({
            'roi_daily': roi_daily,
            'days': days
        })
    except Exception as e:
        logger.error(f"Error in api_roi_daily: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# ACTION ENDPOINTS
# =============================================================================

@app.route('/api/actions/force-predictions', methods=['POST'])
@rate_limit
def action_force_predictions():
    """Force prediction generation for a specific date."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    target_date = data.get('date')
    endpoint = '/api/actions/force-predictions'
    parameters = {'date': target_date}

    if not target_date:
        # Log failed action due to missing parameters
        audit_logger.log_action('force_predictions', endpoint, parameters, 'failure')
        return jsonify({'error': 'date required'}), 400

    try:
        logger.info(f"Force predictions requested for {target_date}")

        # Call the prediction coordinator
        result = call_cloud_run_service(
            'prediction_coordinator',
            '/start',
            payload={'game_date': target_date}
        )

        if result.get('success'):
            # Log successful action to BigQuery audit trail
            audit_logger.log_action('force_predictions', endpoint, parameters, 'success')
            # Track metrics
            dashboard_action_requests.inc(labels={'action_type': 'force_predictions', 'result': 'success'})

            return jsonify({
                'status': 'triggered',
                'date': target_date,
                'message': 'Force predictions job triggered successfully',
                'service_response': result.get('response')
            })
        else:
            # Log failed action to BigQuery audit trail
            audit_logger.log_action('force_predictions', endpoint, parameters, 'failure')
            # Track metrics
            dashboard_action_requests.inc(labels={'action_type': 'force_predictions', 'result': 'failure'})

            return jsonify({
                'status': 'failed',
                'date': target_date,
                'error': result.get('error', 'Unknown error'),
                'status_code': result.get('status_code')
            }), 500

    except Exception as e:
        logger.error(f"Error forcing predictions: {e}")
        # Log error action to BigQuery audit trail
        audit_logger.log_action('force_predictions', endpoint, parameters, 'error')
        # Track metrics
        dashboard_action_requests.inc(labels={'action_type': 'force_predictions', 'result': 'error'})
        return jsonify({'error': str(e)}), 500


@app.route('/api/actions/retry-phase', methods=['POST'])
@rate_limit
def action_retry_phase():
    """Retry a specific phase for a date."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    target_date = data.get('date')
    phase = data.get('phase')
    endpoint = '/api/actions/retry-phase'
    parameters = {'date': target_date, 'phase': phase}

    if not target_date or not phase:
        # Log failed action due to missing parameters
        audit_logger.log_action('retry_phase', endpoint, parameters, 'failure')
        return jsonify({'error': 'date and phase required'}), 400

    try:
        logger.info(f"Retry phase {phase} requested for {target_date}")

        # Determine which service to call based on phase
        if phase == '3' or phase == 'phase3':
            result = call_cloud_run_service(
                'phase3_analytics',
                '/process-date-range',
                payload={
                    'start_date': target_date,
                    'end_date': target_date,
                    'processors': ['PlayerGameSummaryProcessor', 'UpcomingPlayerGameContextProcessor'],
                    'backfill_mode': False
                }
            )
        elif phase == '4' or phase == 'phase4':
            result = call_cloud_run_service(
                'phase4_precompute',
                '/process-date',
                payload={
                    'analysis_date': target_date,
                    'processors': ['MLFeatureStoreProcessor'],
                    'strict_mode': False
                }
            )
        elif phase == '5' or phase == 'phase5' or phase == 'predictions':
            result = call_cloud_run_service(
                'prediction_coordinator',
                '/start',
                payload={'game_date': target_date}
            )
        elif phase == 'self_heal' or phase == 'heal':
            result = call_cloud_run_service(
                'self_heal',
                '/',
                method='GET'
            )
        else:
            # Log failed action due to unknown phase
            audit_logger.log_action('retry_phase', endpoint, parameters, 'failure')
            return jsonify({'error': f'Unknown phase: {phase}. Valid phases: 3, 4, 5, predictions, self_heal'}), 400

        if result.get('success'):
            # Log successful action to BigQuery audit trail
            audit_logger.log_action('retry_phase', endpoint, parameters, 'success')

            return jsonify({
                'status': 'triggered',
                'date': target_date,
                'phase': phase,
                'message': f'Phase {phase} retry triggered successfully',
                'service_response': result.get('response')
            })
        else:
            # Log failed action to BigQuery audit trail
            audit_logger.log_action('retry_phase', endpoint, parameters, 'failure')

            return jsonify({
                'status': 'failed',
                'date': target_date,
                'phase': phase,
                'error': result.get('error', 'Unknown error'),
                'status_code': result.get('status_code')
            }), 500

    except Exception as e:
        logger.error(f"Error retrying phase: {e}")
        # Log error action to BigQuery audit trail
        audit_logger.log_action('retry_phase', endpoint, parameters, 'error')
        return jsonify({'error': str(e)}), 500


@app.route('/api/actions/trigger-self-heal', methods=['POST'])
@rate_limit
def action_trigger_self_heal():
    """Trigger the self-heal pipeline check."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    endpoint = '/api/actions/trigger-self-heal'
    parameters = {}

    try:
        logger.info("Self-heal trigger requested")

        result = call_cloud_run_service(
            'self_heal',
            '/',
            method='GET'
        )

        if result.get('success'):
            # Log successful action to BigQuery audit trail
            audit_logger.log_action('trigger_self_heal', endpoint, parameters, 'success')

            return jsonify({
                'status': 'triggered',
                'message': 'Self-heal check triggered successfully',
                'service_response': result.get('response')
            })
        else:
            # Log failed action to BigQuery audit trail
            audit_logger.log_action('trigger_self_heal', endpoint, parameters, 'failure')

            return jsonify({
                'status': 'failed',
                'error': result.get('error', 'Unknown error')
            }), 500

    except Exception as e:
        logger.error(f"Error triggering self-heal: {e}")
        # Log error action to BigQuery audit trail
        audit_logger.log_action('trigger_self_heal', endpoint, parameters, 'error')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# RELIABILITY MONITORING (R-006, R-007, R-008)
# =============================================================================

@app.route('/api/reliability/reconciliation')
@rate_limit
def api_reconciliation_status():
    """
    Get R-007 pipeline reconciliation status for recent dates.

    Query params:
        days: Number of days to check (default: 7)
        date: Specific date to check (overrides days)
    """
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        specific_date = request.args.get('date')
        days = int(request.args.get('days', 7))

        if specific_date:
            # Check specific date
            response = requests.get(
                f"{RECONCILIATION_FUNCTION_URL}?date={specific_date}",
                timeout=30
            )
            if response.ok:
                return jsonify({
                    'dates': [response.json()],
                    'checked': 1
                })
            else:
                return jsonify({'error': f'Reconciliation check failed: {response.status_code}'}), 500

        # Check multiple recent dates
        et_tz = ZoneInfo('America/New_York')
        today = datetime.now(et_tz).date()
        results = []

        for i in range(days):
            check_date = today - timedelta(days=i+1)  # Start from yesterday
            date_str = check_date.strftime('%Y-%m-%d')

            try:
                response = requests.get(
                    f"{RECONCILIATION_FUNCTION_URL}?date={date_str}",
                    timeout=30
                )
                if response.ok:
                    results.append(response.json())
                else:
                    results.append({
                        'date': date_str,
                        'status': 'ERROR',
                        'error': f'HTTP {response.status_code}'
                    })
            except requests.Timeout:
                results.append({
                    'date': date_str,
                    'status': 'TIMEOUT',
                    'error': 'Request timed out'
                })
            except Exception as e:
                results.append({
                    'date': date_str,
                    'status': 'ERROR',
                    'error': str(e)
                })

        return jsonify({
            'dates': results,
            'checked': len(results)
        })

    except Exception as e:
        logger.error(f"Error fetching reconciliation status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/reliability/summary')
@rate_limit
def api_reliability_summary():
    """
    Get a quick summary of reliability status for dashboard cards.

    Returns counts of recent R-006, R-007, R-008 issues.
    """
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        et_tz = ZoneInfo('America/New_York')
        yesterday = (datetime.now(et_tz).date() - timedelta(days=1)).strftime('%Y-%m-%d')

        # Get yesterday's reconciliation status
        r007_status = {'gaps_found': 0, 'status': 'UNKNOWN'}
        try:
            response = requests.get(
                f"{RECONCILIATION_FUNCTION_URL}?date={yesterday}",
                timeout=15
            )
            if response.ok:
                r007_status = response.json()
        except Exception as e:
            logger.warning(f"Failed to get R-007 status: {e}")

        # Query Cloud Logging for R-006 and R-008 alerts (last 24 hours)
        # Note: This requires additional Cloud Logging API setup
        # For now, return what we have from R-007

        return jsonify({
            'r007': {
                'date': yesterday,
                'gaps_found': r007_status.get('gaps_found', 0),
                'status': r007_status.get('status', 'UNKNOWN'),
                'high_severity_count': len([
                    g for g in r007_status.get('gaps', [])
                    if g.get('severity') == 'HIGH'
                ])
            },
            'r006': {
                'warnings_24h': 0,  # TODO: Query Cloud Logging
                'note': 'Cloud Logging query not yet implemented'
            },
            'r008': {
                'failures_24h': 0,  # TODO: Query Cloud Logging
                'note': 'Cloud Logging query not yet implemented'
            },
            'last_updated': datetime.now(et_tz).isoformat()
        })

    except Exception as e:
        logger.error(f"Error fetching reliability summary: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/partials/reliability-tab')
@rate_limit
def partial_reliability_tab():
    """Render the reliability tab content."""
    if not check_auth():
        return '<div class="text-red-500">Unauthorized</div>', 401

    try:
        et_tz = ZoneInfo('America/New_York')
        yesterday = (datetime.now(et_tz).date() - timedelta(days=1)).strftime('%Y-%m-%d')

        # Get recent reconciliation results (last 3 days for quick view)
        results = []
        today = datetime.now(et_tz).date()

        for i in range(3):
            check_date = today - timedelta(days=i+1)
            date_str = check_date.strftime('%Y-%m-%d')

            try:
                response = requests.get(
                    f"{RECONCILIATION_FUNCTION_URL}?date={date_str}",
                    timeout=20
                )
                if response.ok:
                    results.append(response.json())
                else:
                    results.append({
                        'date': date_str,
                        'status': 'ERROR',
                        'gaps_found': -1
                    })
            except Exception as e:
                results.append({
                    'date': date_str,
                    'status': 'ERROR',
                    'gaps_found': -1,
                    'error': str(e)
                })

        return render_template(
            'components/reliability_tab.html',
            reconciliation_results=results,
            last_check=datetime.now(et_tz).strftime('%Y-%m-%d %H:%M:%S ET')
        )

    except Exception as e:
        logger.error(f"Error rendering reliability tab: {e}")
        return f'<div class="text-red-500">Error loading reliability data: {e}</div>', 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)

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
@app.route('/health')
@rate_limit
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'service': 'admin-dashboard',
        'supported_sports': SUPPORTED_SPORTS,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })


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

    return render_template(
        'dashboard.html',
        sport=sport,
        supported_sports=SUPPORTED_SPORTS,
        today=today,
        tomorrow=tomorrow,
        now_et=now_et,
        today_status=today_status,
        tomorrow_status=tomorrow_status,
        recent_errors=recent_errors
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

    today, tomorrow, now_et = get_et_dates()

    try:
        today_status = bq_service.get_daily_status(today)
        tomorrow_status = bq_service.get_daily_status(tomorrow)
    except Exception as e:
        return f'<div class="text-red-500">Error: {e}</div>', 500

    return render_template(
        'components/status_cards.html',
        today=today,
        tomorrow=tomorrow,
        today_status=today_status,
        tomorrow_status=tomorrow_status
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

            return jsonify({
                'status': 'triggered',
                'date': target_date,
                'message': 'Force predictions job triggered successfully',
                'service_response': result.get('response')
            })
        else:
            # Log failed action to BigQuery audit trail
            audit_logger.log_action('force_predictions', endpoint, parameters, 'failure')

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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)

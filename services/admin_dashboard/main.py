"""
NBA Admin Dashboard - Pipeline Orchestration Monitoring

A Flask-based admin dashboard for monitoring the NBA Props pipeline.
Shows phase completion status, errors, scheduler history, and allows manual actions.
"""

import os
import logging
import secrets
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, render_template, jsonify, request
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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

# Cloud Run service URLs
SERVICE_URLS = {
    'prediction_coordinator': 'https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app',
    'phase3_analytics': 'https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app',
    'phase4_precompute': 'https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app',
    'self_heal': 'https://self-heal-f7p3g7f6ya-wl.a.run.app',
}


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
                           payload: dict = None, timeout: int = 120) -> dict:
    """
    Make an authenticated call to a Cloud Run service.

    Args:
        service_key: Key in SERVICE_URLS dict
        endpoint: Endpoint path (e.g., '/start', '/process-date')
        method: HTTP method
        payload: JSON payload for POST requests
        timeout: Request timeout in seconds

    Returns:
        Dict with 'success', 'status_code', 'response', and 'error' keys
    """
    if service_key not in SERVICE_URLS:
        return {'success': False, 'error': f'Unknown service: {service_key}'}

    base_url = SERVICE_URLS[service_key]
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
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'service': 'admin-dashboard',
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })


# =============================================================================
# DASHBOARD PAGES
# =============================================================================

@app.route('/dashboard')
def dashboard():
    """Main dashboard page."""
    if not check_auth():
        return render_template('auth_required.html'), 401

    today, tomorrow, now_et = get_et_dates()

    # Get pipeline status for today and tomorrow
    try:
        today_status = bq_service.get_daily_status(today)
        tomorrow_status = bq_service.get_daily_status(tomorrow)
    except Exception as e:
        logger.error(f"Error fetching status: {e}")
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
def api_status():
    """Get current pipeline status for today and tomorrow."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    today, tomorrow, now_et = get_et_dates()

    try:
        today_status = bq_service.get_daily_status(today)
        tomorrow_status = bq_service.get_daily_status(tomorrow)
        today_games = bq_service.get_games_detail(today)
        tomorrow_games = bq_service.get_games_detail(tomorrow)

        return jsonify({
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
        logger.error(f"Error in api_status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/games/<date>')
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
def action_force_predictions():
    """Force prediction generation for a specific date."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    target_date = data.get('date')

    if not target_date:
        return jsonify({'error': 'date required'}), 400

    try:
        logger.info(f"Force predictions requested for {target_date}")

        # Log the action for audit trail
        _log_admin_action('force_predictions', {'date': target_date})

        # Call the prediction coordinator
        result = call_cloud_run_service(
            'prediction_coordinator',
            '/start',
            payload={'game_date': target_date}
        )

        if result.get('success'):
            return jsonify({
                'status': 'triggered',
                'date': target_date,
                'message': 'Force predictions job triggered successfully',
                'service_response': result.get('response')
            })
        else:
            return jsonify({
                'status': 'failed',
                'date': target_date,
                'error': result.get('error', 'Unknown error'),
                'status_code': result.get('status_code')
            }), 500

    except Exception as e:
        logger.error(f"Error forcing predictions: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/actions/retry-phase', methods=['POST'])
def action_retry_phase():
    """Retry a specific phase for a date."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    target_date = data.get('date')
    phase = data.get('phase')

    if not target_date or not phase:
        return jsonify({'error': 'date and phase required'}), 400

    try:
        logger.info(f"Retry phase {phase} requested for {target_date}")

        # Log the action for audit trail
        _log_admin_action('retry_phase', {'date': target_date, 'phase': phase})

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
            return jsonify({'error': f'Unknown phase: {phase}. Valid phases: 3, 4, 5, predictions, self_heal'}), 400

        if result.get('success'):
            return jsonify({
                'status': 'triggered',
                'date': target_date,
                'phase': phase,
                'message': f'Phase {phase} retry triggered successfully',
                'service_response': result.get('response')
            })
        else:
            return jsonify({
                'status': 'failed',
                'date': target_date,
                'phase': phase,
                'error': result.get('error', 'Unknown error'),
                'status_code': result.get('status_code')
            }), 500

    except Exception as e:
        logger.error(f"Error retrying phase: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/actions/trigger-self-heal', methods=['POST'])
def action_trigger_self_heal():
    """Trigger the self-heal pipeline check."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        logger.info("Self-heal trigger requested")

        # Log the action for audit trail
        _log_admin_action('trigger_self_heal', {})

        result = call_cloud_run_service(
            'self_heal',
            '/',
            method='GET'
        )

        if result.get('success'):
            return jsonify({
                'status': 'triggered',
                'message': 'Self-heal check triggered successfully',
                'service_response': result.get('response')
            })
        else:
            return jsonify({
                'status': 'failed',
                'error': result.get('error', 'Unknown error')
            }), 500

    except Exception as e:
        logger.error(f"Error triggering self-heal: {e}")
        return jsonify({'error': str(e)}), 500


def _log_admin_action(action: str, details: dict):
    """
    Log admin actions for audit trail.

    Args:
        action: Action name
        details: Action details
    """
    try:
        # Log to console for now
        # TODO: Consider logging to BigQuery for persistent audit trail
        log_entry = {
            'timestamp': datetime.now(ZoneInfo('America/New_York')).isoformat(),
            'action': action,
            'details': details,
            'source': 'admin_dashboard'
        }
        logger.info(f"ADMIN_ACTION: {log_entry}")
    except Exception as e:
        logger.warning(f"Failed to log admin action: {e}")


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)

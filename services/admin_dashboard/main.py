"""
NBA Admin Dashboard - Pipeline Orchestration Monitoring

A Flask-based admin dashboard for monitoring the NBA Props pipeline.
Shows phase completion status, errors, scheduler history, and allows manual actions.
"""

import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, render_template, jsonify, request

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

# API Key for simple authentication
API_KEY = os.environ.get('ADMIN_DASHBOARD_API_KEY', 'dev-key-change-me')


def check_auth():
    """Check API key authentication."""
    # Allow unauthenticated access in dev mode
    if os.environ.get('FLASK_ENV') == 'development':
        return True

    # Check header
    provided_key = request.headers.get('X-API-Key')
    if provided_key == API_KEY:
        return True

    # Check query param (for browser access)
    provided_key = request.args.get('key')
    if provided_key == API_KEY:
        return True

    return False


def get_et_dates():
    """Get today and tomorrow in ET timezone."""
    et = ZoneInfo('America/New_York')
    now_et = datetime.now(et)
    today = now_et.date()
    tomorrow = today + timedelta(days=1)
    return today, tomorrow, now_et


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
        limit = request.args.get('limit', 20, type=int)
        hours = request.args.get('hours', 6, type=int)
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
        # TODO: Implement actual force predictions call
        # This would call the prediction coordinator endpoint
        logger.info(f"Force predictions requested for {target_date}")
        return jsonify({
            'status': 'triggered',
            'date': target_date,
            'message': 'Force predictions job triggered'
        })
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
        # TODO: Implement actual phase retry
        logger.info(f"Retry phase {phase} requested for {target_date}")
        return jsonify({
            'status': 'triggered',
            'date': target_date,
            'phase': phase,
            'message': f'Phase {phase} retry triggered'
        })
    except Exception as e:
        logger.error(f"Error retrying phase: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)

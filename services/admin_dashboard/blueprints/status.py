"""
Status Blueprint - Main dashboard and status endpoints

Routes:
- GET /: Main dashboard page
- GET /dashboard: Dashboard with parameters
- GET /api/status: Pipeline status API
- GET /api/games/<date>: Games for a specific date
- GET /api/errors: Recent errors
- GET /api/orchestration/<date>: Orchestration status
- GET /api/schedulers: Scheduler status
- GET /api/stuck-processors: Stuck processor detection
- GET /api/firestore-health: Firestore health check
- GET /api/history: Run history
- GET /api/history/extended: Extended history
- GET /api/history/weekly: Weekly history
- GET /api/history/monthly: Monthly history
- GET /api/history/comparison: Historical comparison
- GET /api/processor-failures: Processor failure details
"""

import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, jsonify, request

from google.cloud import bigquery

from ..services.rate_limiter import rate_limit
from ..services.auth import check_auth

logger = logging.getLogger(__name__)

status_bp = Blueprint('status', __name__)


def get_bq_client():
    """Get BigQuery client."""
    project_id = os.environ.get('GCP_PROJECT_ID')
    return bigquery.Client(project=project_id)


def get_et_dates():
    """Get current and previous dates in ET timezone."""
    et = ZoneInfo('America/New_York')
    now = datetime.now(et)
    today = now.strftime('%Y-%m-%d')
    yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    return today, yesterday


def clamp_param(value: int, min_val: int, max_val: int, default: int) -> int:
    """Clamp a parameter value to a valid range."""
    try:
        val = int(value)
        return max(min_val, min(max_val, val))
    except (TypeError, ValueError):
        return default


@status_bp.route('/')
@rate_limit
def index():
    """Main dashboard page."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    today, yesterday = get_et_dates()
    return render_template('dashboard.html',
                          today_date=today,
                          yesterday_date=yesterday)


@status_bp.route('/dashboard')
@rate_limit
def dashboard():
    """Dashboard with parameters."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    today, yesterday = get_et_dates()

    # Get optional date parameter
    date_param = request.args.get('date', today)

    return render_template('dashboard.html',
                          today_date=today,
                          yesterday_date=yesterday,
                          selected_date=date_param)


@status_bp.route('/api/status')
@rate_limit
def api_status():
    """Pipeline status API."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')
        today, _ = get_et_dates()

        # Query pipeline status for today
        query = f"""
            SELECT
                phase,
                processor_name,
                status,
                records_processed,
                started_at,
                completed_at,
                error_message
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE DATE(started_at) = @today
            ORDER BY started_at DESC
            LIMIT 100
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("today", "STRING", today)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        status_data = [dict(row) for row in results]

        return jsonify({
            'date': today,
            'processors': status_data,
            'count': len(status_data)
        })

    except Exception as e:
        logger.error(f"Error fetching status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@status_bp.route('/api/games/<date>')
@rate_limit
def api_games(date):
    """Games for a specific date."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT *
            FROM `{project_id}.nba_raw.schedule`
            WHERE game_date = @date
            ORDER BY game_time
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("date", "STRING", date)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        games = [dict(row) for row in results]

        return jsonify({'date': date, 'games': games, 'count': len(games)})

    except Exception as e:
        logger.error(f"Error fetching games: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@status_bp.route('/api/errors')
@rate_limit
def api_errors():
    """Recent errors."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT *
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE status = 'failed'
            ORDER BY started_at DESC
            LIMIT 50
        """

        results = client.query(query).result()
        errors = [dict(row) for row in results]

        return jsonify({'errors': errors, 'count': len(errors)})

    except Exception as e:
        logger.error(f"Error fetching errors: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@status_bp.route('/api/orchestration/<date>')
@rate_limit
def api_orchestration(date):
    """Orchestration status for a date."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                phase,
                COUNT(*) as total,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) as running
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE DATE(started_at) = @date
            GROUP BY phase
            ORDER BY phase
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("date", "STRING", date)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        phases = [dict(row) for row in results]

        return jsonify({'date': date, 'phases': phases})

    except Exception as e:
        logger.error(f"Error fetching orchestration: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@status_bp.route('/api/schedulers')
@rate_limit
def api_schedulers():
    """Scheduler status."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    # Return placeholder - actual implementation depends on scheduler system
    return jsonify({
        'schedulers': [],
        'message': 'Scheduler status endpoint'
    })


@status_bp.route('/api/stuck-processors')
@rate_limit
def api_stuck_processors():
    """Detect stuck processors."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        # Find processors running for more than 30 minutes
        query = f"""
            SELECT *
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE status = 'running'
            AND started_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
            ORDER BY started_at
        """

        results = client.query(query).result()
        stuck = [dict(row) for row in results]

        return jsonify({'stuck_processors': stuck, 'count': len(stuck)})

    except Exception as e:
        logger.error(f"Error checking stuck processors: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@status_bp.route('/api/firestore-health')
@rate_limit
def api_firestore_health():
    """Firestore health check."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    try:
        from google.cloud import firestore

        db = firestore.Client()
        # Try to read from a collection
        docs = list(db.collection('health_check').limit(1).stream())

        return jsonify({
            'status': 'healthy',
            'message': 'Firestore connection successful'
        })

    except Exception as e:
        logger.error(f"Firestore health check failed: {e}", exc_info=True)
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 503


@status_bp.route('/api/history')
@rate_limit
def api_history():
    """Run history."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    limit = clamp_param(request.args.get('limit', 50), 1, 500, 50)

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT *
            FROM `{project_id}.nba_pipeline.processor_run_history`
            ORDER BY started_at DESC
            LIMIT @limit
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("limit", "INT64", limit)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        history = [dict(row) for row in results]

        return jsonify({'history': history, 'count': len(history)})

    except Exception as e:
        logger.error(f"Error fetching history: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@status_bp.route('/api/history/extended')
@rate_limit
def api_history_extended():
    """Extended history with more details."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    days = clamp_param(request.args.get('days', 7), 1, 30, 7)

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                DATE(started_at) as date,
                phase,
                COUNT(*) as total_runs,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                AVG(TIMESTAMP_DIFF(completed_at, started_at, SECOND)) as avg_duration_seconds
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
            GROUP BY DATE(started_at), phase
            ORDER BY date DESC, phase
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("days", "INT64", days)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        history = [dict(row) for row in results]

        return jsonify({'history': history, 'days': days})

    except Exception as e:
        logger.error(f"Error fetching extended history: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@status_bp.route('/api/history/weekly')
@rate_limit
def api_history_weekly():
    """Weekly history summary."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    weeks = clamp_param(request.args.get('weeks', 4), 1, 12, 4)

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                DATE_TRUNC(DATE(started_at), WEEK) as week,
                COUNT(*) as total_runs,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                ROUND(100.0 * SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @weeks WEEK)
            GROUP BY week
            ORDER BY week DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("weeks", "INT64", weeks)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        history = [dict(row) for row in results]

        return jsonify({'history': history, 'weeks': weeks})

    except Exception as e:
        logger.error(f"Error fetching weekly history: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@status_bp.route('/api/history/monthly')
@rate_limit
def api_history_monthly():
    """Monthly history summary."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    months = clamp_param(request.args.get('months', 3), 1, 12, 3)

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                DATE_TRUNC(DATE(started_at), MONTH) as month,
                COUNT(*) as total_runs,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                ROUND(100.0 * SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @months MONTH)
            GROUP BY month
            ORDER BY month DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("months", "INT64", months)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        history = [dict(row) for row in results]

        return jsonify({'history': history, 'months': months})

    except Exception as e:
        logger.error(f"Error fetching monthly history: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@status_bp.route('/api/history/comparison')
@rate_limit
def api_history_comparison():
    """Historical comparison."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return jsonify({
        'message': 'Historical comparison endpoint',
        'data': []
    })


@status_bp.route('/api/processor-failures')
@rate_limit
def api_processor_failures():
    """Processor failure details."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    limit = clamp_param(request.args.get('limit', 20), 1, 100, 20)

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                processor_name,
                phase,
                error_message,
                started_at,
                data_date
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE status = 'failed'
            ORDER BY started_at DESC
            LIMIT @limit
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("limit", "INT64", limit)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        failures = [dict(row) for row in results]

        return jsonify({'failures': failures, 'count': len(failures)})

    except Exception as e:
        logger.error(f"Error fetching processor failures: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

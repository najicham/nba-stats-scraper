"""
Partials Blueprint - HTMX partial views

Routes for HTML fragments used by HTMX for dynamic page updates.
"""

import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, request

from google.cloud import bigquery

from ..services.rate_limiter import rate_limit
from ..services.auth import check_auth
from ..services.client_pool import get_bigquery_client as get_shared_bq_client

logger = logging.getLogger(__name__)

partials_bp = Blueprint('partials', __name__)


def get_bq_client():
    """Get BigQuery client (uses shared client pool)."""
    return get_shared_bq_client()


def clamp_param(value: int, min_val: int, max_val: int, default: int) -> int:
    """Clamp a parameter value to a valid range."""
    try:
        val = int(value)
        return max(min_val, min(max_val, val))
    except (TypeError, ValueError):
        return default


@partials_bp.route('/status-cards')
@rate_limit
def partial_status_cards():
    """Status cards partial."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        # Get today's date in ET
        et = ZoneInfo('America/New_York')
        today = datetime.now(et).strftime('%Y-%m-%d')

        query = f"""
            SELECT
                phase,
                COUNT(*) as total,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE DATE(started_at) = @today
            GROUP BY phase
            ORDER BY phase
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("today", "STRING", today)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        phases = [dict(row) for row in results]

        return render_template('partials/status_cards.html', phases=phases, date=today)

    except Exception as e:
        logger.error(f"Error fetching status cards: {e}", exc_info=True)
        return f'<div class="error">Error loading status cards: {str(e)}</div>'


@partials_bp.route('/games-table/<date>')
@rate_limit
def partial_games_table(date):
    """Games table partial."""
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

        return render_template('partials/games_table.html', games=games, date=date)

    except Exception as e:
        logger.error(f"Error fetching games table: {e}", exc_info=True)
        return f'<div class="error">Error loading games: {str(e)}</div>'


@partials_bp.route('/error-feed')
@rate_limit
def partial_error_feed():
    """Error feed partial."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                processor_name,
                error_message,
                started_at,
                phase
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE status = 'failed'
            ORDER BY started_at DESC
            LIMIT 10
        """

        results = client.query(query).result()
        errors = [dict(row) for row in results]

        return render_template('partials/error_feed.html', errors=errors)

    except Exception as e:
        logger.error(f"Error fetching error feed: {e}", exc_info=True)
        return f'<div class="error">Error loading errors: {str(e)}</div>'


@partials_bp.route('/processor-failures')
@rate_limit
def partial_processor_failures():
    """Processor failures partial."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return render_template('partials/processor_failures.html', failures=[])


@partials_bp.route('/coverage-metrics')
@rate_limit
def partial_coverage_metrics():
    """Coverage metrics partial."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return render_template('partials/coverage_metrics.html', metrics={})


@partials_bp.route('/calibration')
@rate_limit
def partial_calibration():
    """Calibration partial."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return render_template('partials/calibration.html', data={})


@partials_bp.route('/roi')
@rate_limit
def partial_roi():
    """ROI partial."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return render_template('partials/roi.html', data={})


@partials_bp.route('/player-insights')
@rate_limit
def partial_player_insights():
    """Player insights partial."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return render_template('partials/player_insights.html', insights=[])


@partials_bp.route('/system-performance')
@rate_limit
def partial_system_performance():
    """System performance partial."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return render_template('partials/system_performance.html', performance={})


@partials_bp.route('/extended-history')
@rate_limit
def partial_extended_history():
    """Extended history partial."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return render_template('partials/extended_history.html', history=[])


@partials_bp.route('/audit-logs')
@rate_limit
def partial_audit_logs():
    """Audit logs partial."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return render_template('partials/audit_logs.html', logs=[])


@partials_bp.route('/reliability-tab')
@rate_limit
def partial_reliability_tab():
    """Reliability tab partial."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return render_template('partials/reliability_tab.html', data={})


@partials_bp.route('/trends')
@rate_limit
def partial_trends():
    """Trends partial."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return render_template('partials/trends.html', trends={})


@partials_bp.route('/scraper-costs')
@rate_limit
def partial_scraper_costs():
    """Scraper costs partial."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return render_template('partials/scraper_costs.html', costs={})


@partials_bp.route('/latency-dashboard')
@rate_limit
def partial_latency_dashboard():
    """Latency dashboard partial."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return render_template('partials/latency_dashboard.html', latency={})

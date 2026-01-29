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

from services.admin_dashboard.services.rate_limiter import rate_limit
from services.admin_dashboard.services.auth import check_auth
from services.admin_dashboard.services.client_pool import get_bigquery_client as get_shared_bq_client

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
    """Error feed partial with categorization."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    sport = request.args.get('sport', 'nba')

    try:
        # Import the helper function from status blueprint
        from services.admin_dashboard.blueprints.status import (
            _get_game_dates_with_games,
            _is_expected_no_data_error
        )

        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')
        hours = 24

        # Get game dates with scheduled games
        game_dates = _get_game_dates_with_games(hours)

        # Query all errors
        query = f"""
            SELECT *
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE status = 'failed'
              AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
            ORDER BY started_at DESC
            LIMIT 100
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("hours", "INT64", hours)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        all_errors = [dict(row) for row in results]

        # Categorize errors
        real_errors = []
        expected_errors = []

        for error in all_errors:
            if _is_expected_no_data_error(
                error.get('error_message'),
                error.get('data_date'),
                game_dates
            ):
                expected_errors.append(error)
            else:
                real_errors.append(error)

        return render_template(
            'components/error_feed.html',
            real_errors=real_errors,
            expected_errors=expected_errors,
            noise_reduction=len(expected_errors)
        )

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

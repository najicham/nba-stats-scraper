"""
Analytics Blueprint - Coverage metrics and calibration data

Routes:
- GET /coverage-metrics: Coverage metrics
- GET /calibration-data: Calibration data
- GET /calibration-summary: Calibration summary
- GET /roi-summary: ROI summary
- GET /roi-daily: Daily ROI data
"""

import os
import logging
from flask import Blueprint, jsonify, request

from google.cloud import bigquery

from services.admin_dashboard.services.rate_limiter import rate_limit
from services.admin_dashboard.services.auth import check_auth

logger = logging.getLogger(__name__)

analytics_bp = Blueprint('analytics', __name__)


def get_bq_client():
    """Get BigQuery client."""
    project_id = os.environ.get('GCP_PROJECT_ID')
    return bigquery.Client(project=project_id)


def clamp_param(value: int, min_val: int, max_val: int, default: int) -> int:
    """Clamp a parameter value to a valid range."""
    try:
        val = int(value)
        return max(min_val, min(max_val, val))
    except (TypeError, ValueError):
        return default


@analytics_bp.route('/coverage-metrics')
@rate_limit
def api_coverage_metrics():
    """Coverage metrics."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    days = clamp_param(request.args.get('days', 7), 1, 30, 7)

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                game_date,
                total_players,
                predicted_players,
                ROUND(100.0 * predicted_players / NULLIF(total_players, 0), 2) as coverage_pct
            FROM `{project_id}.nba_predictions.daily_coverage`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
            ORDER BY game_date DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("days", "INT64", days)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        data = [dict(row) for row in results]

        return jsonify({'data': data, 'days': days})

    except Exception as e:
        logger.error(f"Error fetching coverage metrics: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/calibration-data')
@rate_limit
def api_calibration_data():
    """Calibration data."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    days = clamp_param(request.args.get('days', 30), 1, 90, 30)

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                confidence_bucket,
                total_predictions,
                correct_predictions,
                ROUND(100.0 * correct_predictions / NULLIF(total_predictions, 0), 2) as actual_accuracy
            FROM `{project_id}.nba_predictions.calibration_buckets`
            WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
            GROUP BY confidence_bucket
            ORDER BY confidence_bucket
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("days", "INT64", days)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        data = [dict(row) for row in results]

        return jsonify({'data': data, 'days': days})

    except Exception as e:
        logger.error(f"Error fetching calibration data: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/calibration-summary')
@rate_limit
def api_calibration_summary():
    """Calibration summary."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return jsonify({
        'message': 'Calibration summary endpoint',
        'summary': {}
    })


@analytics_bp.route('/roi-summary')
@rate_limit
def api_roi_summary():
    """ROI summary."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return jsonify({
        'message': 'ROI summary endpoint',
        'summary': {}
    })


@analytics_bp.route('/roi-daily')
@rate_limit
def api_roi_daily():
    """Daily ROI data."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    days = clamp_param(request.args.get('days', 30), 1, 90, 30)

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                game_date,
                total_bets,
                winning_bets,
                total_wagered,
                total_return,
                ROUND((total_return - total_wagered) / NULLIF(total_wagered, 0) * 100, 2) as roi_pct
            FROM `{project_id}.nba_predictions.daily_roi`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
            ORDER BY game_date DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("days", "INT64", days)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        data = [dict(row) for row in results]

        return jsonify({'data': data, 'days': days})

    except Exception as e:
        logger.error(f"Error fetching daily ROI: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

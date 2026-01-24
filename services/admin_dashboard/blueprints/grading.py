"""
Grading Blueprint - Prediction grading metrics and history

Routes:
- GET /extended: Extended grading data
- GET /weekly: Weekly grading summary
- GET /comparison: Historical grading comparison
- GET /by-system: Grading by prediction system
"""

import os
import logging
from flask import Blueprint, jsonify, request

from google.cloud import bigquery

from ..services.rate_limiter import rate_limit
from ..services.auth import check_auth

logger = logging.getLogger(__name__)

grading_bp = Blueprint('grading', __name__)


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


@grading_bp.route('/extended')
@rate_limit
def api_grading_extended():
    """Extended grading data."""
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
                COUNT(*) as total_predictions,
                SUM(CASE WHEN correct THEN 1 ELSE 0 END) as correct,
                ROUND(100.0 * SUM(CASE WHEN correct THEN 1 ELSE 0 END) / COUNT(*), 2) as accuracy
            FROM `{project_id}.nba_predictions.graded_predictions`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
            GROUP BY game_date
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
        logger.error(f"Error fetching extended grading: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@grading_bp.route('/weekly')
@rate_limit
def api_grading_weekly():
    """Weekly grading summary."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    weeks = clamp_param(request.args.get('weeks', 4), 1, 12, 4)

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                DATE_TRUNC(game_date, WEEK) as week,
                COUNT(*) as total_predictions,
                SUM(CASE WHEN correct THEN 1 ELSE 0 END) as correct,
                ROUND(100.0 * SUM(CASE WHEN correct THEN 1 ELSE 0 END) / COUNT(*), 2) as accuracy
            FROM `{project_id}.nba_predictions.graded_predictions`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @weeks WEEK)
            GROUP BY week
            ORDER BY week DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("weeks", "INT64", weeks)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        data = [dict(row) for row in results]

        return jsonify({'data': data, 'weeks': weeks})

    except Exception as e:
        logger.error(f"Error fetching weekly grading: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@grading_bp.route('/comparison')
@rate_limit
def api_grading_comparison():
    """Historical grading comparison."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return jsonify({
        'message': 'Grading comparison endpoint',
        'data': []
    })


@grading_bp.route('/by-system')
@rate_limit
def api_grading_by_system():
    """Grading by prediction system."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    days = clamp_param(request.args.get('days', 7), 1, 30, 7)

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                prediction_system,
                COUNT(*) as total_predictions,
                SUM(CASE WHEN correct THEN 1 ELSE 0 END) as correct,
                ROUND(100.0 * SUM(CASE WHEN correct THEN 1 ELSE 0 END) / COUNT(*), 2) as accuracy
            FROM `{project_id}.nba_predictions.graded_predictions`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
            GROUP BY prediction_system
            ORDER BY accuracy DESC
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
        logger.error(f"Error fetching grading by system: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

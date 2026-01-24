"""
Trends Blueprint - Trend charts and analysis

Routes:
- GET /accuracy: Accuracy trends
- GET /latency: Latency trends
- GET /errors: Error trends
- GET /volume: Volume trends
- GET /accuracy-by-system: Accuracy by system trends
- GET /all: All trends combined
"""

import os
import logging
from flask import Blueprint, jsonify, request

from google.cloud import bigquery

from ..services.rate_limiter import rate_limit
from ..services.auth import check_auth

logger = logging.getLogger(__name__)

trends_bp = Blueprint('trends', __name__)


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


@trends_bp.route('/accuracy')
@rate_limit
def api_trends_accuracy():
    """Accuracy trends."""
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
                ROUND(100.0 * SUM(CASE WHEN correct THEN 1 ELSE 0 END) / COUNT(*), 2) as accuracy
            FROM `{project_id}.nba_predictions.graded_predictions`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
            GROUP BY game_date
            ORDER BY game_date
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
        logger.error(f"Error fetching accuracy trends: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@trends_bp.route('/latency')
@rate_limit
def api_trends_latency():
    """Latency trends."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    days = clamp_param(request.args.get('days', 30), 1, 90, 30)

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                DATE(started_at) as date,
                AVG(TIMESTAMP_DIFF(completed_at, started_at, SECOND)) as avg_latency_seconds,
                MAX(TIMESTAMP_DIFF(completed_at, started_at, SECOND)) as max_latency_seconds
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
                AND completed_at IS NOT NULL
            GROUP BY date
            ORDER BY date
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
        logger.error(f"Error fetching latency trends: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@trends_bp.route('/errors')
@rate_limit
def api_trends_errors():
    """Error trends."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    days = clamp_param(request.args.get('days', 30), 1, 90, 30)

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                DATE(started_at) as date,
                COUNT(*) as total_runs,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as errors,
                ROUND(100.0 * SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) / COUNT(*), 2) as error_rate
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
            GROUP BY date
            ORDER BY date
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
        logger.error(f"Error fetching error trends: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@trends_bp.route('/volume')
@rate_limit
def api_trends_volume():
    """Volume trends."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    days = clamp_param(request.args.get('days', 30), 1, 90, 30)

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                DATE(started_at) as date,
                COUNT(*) as total_runs,
                SUM(COALESCE(records_processed, 0)) as total_records
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
            GROUP BY date
            ORDER BY date
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
        logger.error(f"Error fetching volume trends: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@trends_bp.route('/accuracy-by-system')
@rate_limit
def api_trends_accuracy_by_system():
    """Accuracy by system trends."""
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
                prediction_system,
                ROUND(100.0 * SUM(CASE WHEN correct THEN 1 ELSE 0 END) / COUNT(*), 2) as accuracy
            FROM `{project_id}.nba_predictions.graded_predictions`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
            GROUP BY game_date, prediction_system
            ORDER BY game_date, prediction_system
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
        logger.error(f"Error fetching accuracy by system trends: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@trends_bp.route('/all')
@rate_limit
def api_trends_all():
    """All trends combined."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    return jsonify({
        'message': 'All trends endpoint',
        'data': {
            'accuracy': [],
            'latency': [],
            'errors': [],
            'volume': []
        }
    })

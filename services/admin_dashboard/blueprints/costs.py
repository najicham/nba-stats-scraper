"""
Costs Blueprint - Scraper costs and leaderboard

Routes:
- GET /: Scraper costs overview
- GET /leaderboard: Costs leaderboard
"""

import os
import logging
from flask import Blueprint, jsonify, request

from google.cloud import bigquery

from services.admin_dashboard.services.rate_limiter import rate_limit
from services.admin_dashboard.services.auth import check_auth

logger = logging.getLogger(__name__)

costs_bp = Blueprint('costs', __name__)


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


@costs_bp.route('/')
@rate_limit
def api_scraper_costs():
    """Scraper costs overview."""
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
                SUM(TIMESTAMP_DIFF(completed_at, started_at, SECOND)) as total_seconds,
                COUNT(*) as run_count,
                SUM(records_processed) as total_records
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
                AND completed_at IS NOT NULL
            GROUP BY date
            ORDER BY date DESC
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
        logger.error(f"Error fetching scraper costs: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@costs_bp.route('/leaderboard')
@rate_limit
def api_scraper_costs_leaderboard():
    """Costs leaderboard."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    days = clamp_param(request.args.get('days', 7), 1, 30, 7)

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                processor_name,
                phase,
                COUNT(*) as run_count,
                SUM(TIMESTAMP_DIFF(completed_at, started_at, SECOND)) as total_seconds,
                AVG(TIMESTAMP_DIFF(completed_at, started_at, SECOND)) as avg_seconds,
                SUM(COALESCE(records_processed, 0)) as total_records
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
                AND completed_at IS NOT NULL
            GROUP BY processor_name, phase
            ORDER BY total_seconds DESC
            LIMIT 30
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
        logger.error(f"Error fetching costs leaderboard: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

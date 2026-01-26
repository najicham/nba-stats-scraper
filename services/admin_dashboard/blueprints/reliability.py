"""
Reliability Blueprint - Reconciliation and reliability metrics

Routes:
- GET /reconciliation: Reconciliation status
- GET /summary: Reliability summary
"""

import os
import logging
from flask import Blueprint, jsonify, request

from google.cloud import bigquery

from services.admin_dashboard.services.rate_limiter import rate_limit
from services.admin_dashboard.services.auth import check_auth

logger = logging.getLogger(__name__)

reliability_bp = Blueprint('reliability', __name__)


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


@reliability_bp.route('/reconciliation')
@rate_limit
def api_reconciliation_status():
    """Reconciliation status."""
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
                ROUND(100.0 * SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
            GROUP BY date, phase
            ORDER BY date DESC, phase
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
        logger.error(f"Error fetching reconciliation status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@reliability_bp.route('/summary')
@rate_limit
def api_reliability_summary():
    """Reliability summary."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                phase,
                COUNT(*) as total_runs,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                ROUND(100.0 * SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate,
                AVG(TIMESTAMP_DIFF(completed_at, started_at, SECOND)) as avg_duration
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
            GROUP BY phase
            ORDER BY phase
        """

        results = client.query(query).result()
        data = [dict(row) for row in results]

        # Calculate overall summary
        total_runs = sum(r.get('total_runs', 0) for r in data)
        total_success = sum(r.get('success', 0) for r in data)
        overall_rate = round(100.0 * total_success / total_runs, 2) if total_runs > 0 else 0

        return jsonify({
            'phases': data,
            'overall': {
                'total_runs': total_runs,
                'total_success': total_success,
                'success_rate': overall_rate
            }
        })

    except Exception as e:
        logger.error(f"Error fetching reliability summary: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

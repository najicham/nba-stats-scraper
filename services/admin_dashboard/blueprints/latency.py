"""
Latency Blueprint - Latency metrics and bottleneck detection

Routes:
- GET /game/<game_id>: Latency for a specific game
- GET /date/<date_str>: Latency for a specific date
- GET /bottlenecks: Latency bottlenecks
- GET /slow-executions: Slow execution detection
- GET /pipeline-metrics: Pipeline latency metrics
"""

import os
import logging
from flask import Blueprint, jsonify, request

from google.cloud import bigquery

from ..services.rate_limiter import rate_limit
from ..services.auth import check_auth

logger = logging.getLogger(__name__)

latency_bp = Blueprint('latency', __name__)


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


@latency_bp.route('/game/<game_id>')
@rate_limit
def api_game_latency(game_id):
    """Latency for a specific game."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                processor_name,
                phase,
                started_at,
                completed_at,
                TIMESTAMP_DIFF(completed_at, started_at, SECOND) as duration_seconds
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE run_metadata LIKE @game_id_pattern
            ORDER BY started_at
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_id_pattern", "STRING", f"%{game_id}%")
            ]
        )

        results = client.query(query, job_config=job_config).result()
        data = [dict(row) for row in results]

        return jsonify({'game_id': game_id, 'data': data})

    except Exception as e:
        logger.error(f"Error fetching game latency: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@latency_bp.route('/date/<date_str>')
@rate_limit
def api_date_latency(date_str):
    """Latency for a specific date."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                processor_name,
                phase,
                started_at,
                completed_at,
                TIMESTAMP_DIFF(completed_at, started_at, SECOND) as duration_seconds,
                status
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE DATE(started_at) = @date
                AND completed_at IS NOT NULL
            ORDER BY duration_seconds DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("date", "STRING", date_str)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        data = [dict(row) for row in results]

        return jsonify({'date': date_str, 'data': data})

    except Exception as e:
        logger.error(f"Error fetching date latency: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@latency_bp.route('/bottlenecks')
@rate_limit
def api_latency_bottlenecks():
    """Latency bottlenecks."""
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
                AVG(TIMESTAMP_DIFF(completed_at, started_at, SECOND)) as avg_duration,
                MAX(TIMESTAMP_DIFF(completed_at, started_at, SECOND)) as max_duration,
                APPROX_QUANTILES(TIMESTAMP_DIFF(completed_at, started_at, SECOND), 100)[OFFSET(95)] as p95_duration
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
                AND completed_at IS NOT NULL
            GROUP BY processor_name, phase
            ORDER BY avg_duration DESC
            LIMIT 20
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
        logger.error(f"Error fetching bottlenecks: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@latency_bp.route('/slow-executions')
@rate_limit
def api_slow_executions():
    """Slow execution detection."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    threshold = clamp_param(request.args.get('threshold', 300), 60, 3600, 300)

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                processor_name,
                phase,
                started_at,
                completed_at,
                TIMESTAMP_DIFF(completed_at, started_at, SECOND) as duration_seconds,
                data_date
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE TIMESTAMP_DIFF(completed_at, started_at, SECOND) > @threshold
                AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
            ORDER BY duration_seconds DESC
            LIMIT 50
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("threshold", "INT64", threshold)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        data = [dict(row) for row in results]

        return jsonify({'data': data, 'threshold': threshold})

    except Exception as e:
        logger.error(f"Error fetching slow executions: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@latency_bp.route('/pipeline-metrics')
@rate_limit
def api_pipeline_latency_metrics():
    """Pipeline latency metrics."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    try:
        client = get_bq_client()
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
            SELECT
                phase,
                AVG(TIMESTAMP_DIFF(completed_at, started_at, SECOND)) as avg_duration,
                MAX(TIMESTAMP_DIFF(completed_at, started_at, SECOND)) as max_duration,
                MIN(TIMESTAMP_DIFF(completed_at, started_at, SECOND)) as min_duration,
                COUNT(*) as run_count
            FROM `{project_id}.nba_pipeline.processor_run_history`
            WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
                AND completed_at IS NOT NULL
            GROUP BY phase
            ORDER BY phase
        """

        results = client.query(query).result()
        data = [dict(row) for row in results]

        return jsonify({'data': data})

    except Exception as e:
        logger.error(f"Error fetching pipeline metrics: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

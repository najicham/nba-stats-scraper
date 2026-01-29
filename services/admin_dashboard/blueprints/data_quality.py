"""
Data Quality Blueprint - Monitor prevention system effectiveness.

Tracks:
- Processor version distribution
- Deployment freshness
- Schema validation history
- Scraper failure cleanup effectiveness
- Data quality score

Routes:
- GET /api/data-quality/version-distribution: Processor version distribution
- GET /api/data-quality/deployment-freshness: Deployment freshness check
- GET /api/data-quality/scraper-cleanup-stats: Scraper cleanup effectiveness
- GET /api/data-quality/score: Overall data quality score
"""

import os
import logging
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request

from google.cloud import bigquery

from services.admin_dashboard.services.rate_limiter import rate_limit
from services.admin_dashboard.services.auth import check_auth

logger = logging.getLogger(__name__)

data_quality_bp = Blueprint('data_quality', __name__)


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


@data_quality_bp.route('/api/data-quality/version-distribution')
@rate_limit
def get_version_distribution():
    """
    Get processor version distribution for recent data.

    Shows which processor versions processed data in the last 7 days.
    Alerts if multiple versions or stale versions detected.
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    sport = request.args.get('sport', 'nba')
    days = clamp_param(request.args.get('days', 7), 1, 30, 7)

    project_id = os.environ.get('GCP_PROJECT_ID')

    query = f"""
    SELECT
        processor_version,
        COUNT(*) as record_count,
        MAX(processed_at) as last_seen,
        MIN(processed_at) as first_seen,
        COUNT(DISTINCT game_date) as dates_processed
    FROM `{project_id}.{sport}_analytics.player_game_summary`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
      AND processor_version IS NOT NULL
    GROUP BY processor_version
    ORDER BY last_seen DESC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("days", "INT64", days)
        ]
    )

    try:
        client = get_bq_client()
        result = client.query(query, job_config=job_config).result()

        versions = []
        for row in result:
            versions.append({
                'version': row.processor_version,
                'record_count': row.record_count,
                'last_seen': row.last_seen.isoformat() if row.last_seen else None,
                'first_seen': row.first_seen.isoformat() if row.first_seen else None,
                'dates_processed': row.dates_processed
            })

        # Calculate alerts
        has_multiple_versions = len(versions) > 1
        has_stale_version = any(
            (datetime.now() - datetime.fromisoformat(v['last_seen'])).days > 1
            for v in versions if v['last_seen']
        )

        return jsonify({
            'versions': versions,
            'alerts': {
                'multiple_versions': has_multiple_versions,
                'stale_versions': has_stale_version
            },
            'days': days
        })

    except Exception as e:
        logger.error(f"Failed to get version distribution: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@data_quality_bp.route('/api/data-quality/deployment-freshness')
@rate_limit
def get_deployment_freshness():
    """
    Check freshness of processor deployments.

    Alerts if processors haven't run recently or are using old code.
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    sport = request.args.get('sport', 'nba')
    project_id = os.environ.get('GCP_PROJECT_ID')

    query = f"""
    SELECT
        processor_name,
        processor_version,
        MAX(processed_at) as last_run,
        COUNT(DISTINCT DATE(processed_at)) as days_active
    FROM `{project_id}.{sport}_orchestration.processor_run_history`
    WHERE DATE(processed_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    GROUP BY processor_name, processor_version
    ORDER BY last_run DESC
    """

    try:
        client = get_bq_client()
        result = client.query(query).result()

        processors = []
        stale_count = 0

        for row in result:
            hours_since_run = (datetime.now() - row.last_run).total_seconds() / 3600
            is_stale = hours_since_run > 48

            if is_stale:
                stale_count += 1

            processors.append({
                'name': row.processor_name,
                'version': row.processor_version,
                'last_run': row.last_run.isoformat(),
                'hours_since_run': round(hours_since_run, 1),
                'days_active': row.days_active,
                'is_stale': is_stale
            })

        return jsonify({
            'processors': processors,
            'stale_count': stale_count,
            'total_count': len(processors)
        })

    except Exception as e:
        logger.error(f"Failed to check deployment freshness: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@data_quality_bp.route('/api/data-quality/scraper-cleanup-stats')
@rate_limit
def get_scraper_cleanup_stats():
    """
    Get scraper failure cleanup effectiveness metrics.

    Shows how many failures were auto-cleaned vs still pending.
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    sport = request.args.get('sport', 'nba')
    days = clamp_param(request.args.get('days', 7), 1, 30, 7)
    project_id = os.environ.get('GCP_PROJECT_ID')

    query_cleanup = f"""
    SELECT
        DATE(backfilled_at) as cleanup_date,
        COUNT(*) as failures_cleaned,
        AVG(retry_count) as avg_retries,
        MAX(retry_count) as max_retries
    FROM `{project_id}.{sport}_orchestration.scraper_failures`
    WHERE backfilled = TRUE
      AND backfilled_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
    GROUP BY cleanup_date
    ORDER BY cleanup_date DESC
    """

    query_pending = f"""
    SELECT
        scraper_name,
        COUNT(*) as pending_count,
        MIN(game_date) as oldest_failure
    FROM `{project_id}.{sport}_orchestration.scraper_failures`
    WHERE backfilled = FALSE
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
    GROUP BY scraper_name
    ORDER BY pending_count DESC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("days", "INT64", days)
        ]
    )

    try:
        client = get_bq_client()

        # Get cleanup history
        result = client.query(query_cleanup, job_config=job_config).result()
        cleanup_history = []
        total_cleaned = 0

        for row in result:
            total_cleaned += row.failures_cleaned
            cleanup_history.append({
                'date': row.cleanup_date.isoformat(),
                'cleaned': row.failures_cleaned,
                'avg_retries': round(row.avg_retries, 1) if row.avg_retries else 0,
                'max_retries': row.max_retries
            })

        # Get pending failures
        result = client.query(query_pending, job_config=job_config).result()
        pending_failures = []
        total_pending = 0

        for row in result:
            total_pending += row.pending_count
            pending_failures.append({
                'scraper': row.scraper_name,
                'count': row.pending_count,
                'oldest': row.oldest_failure.isoformat()
            })

        return jsonify({
            'cleanup_history': cleanup_history,
            'pending_failures': pending_failures,
            'summary': {
                'total_cleaned': total_cleaned,
                'total_pending': total_pending,
                'cleanup_rate': round(
                    total_cleaned / (total_cleaned + total_pending) * 100, 1
                ) if (total_cleaned + total_pending) > 0 else 0
            },
            'days': days
        })

    except Exception as e:
        logger.error(f"Failed to get cleanup stats: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@data_quality_bp.route('/api/data-quality/score')
@rate_limit
def get_data_quality_score():
    """
    Calculate overall data quality score (0-100).

    Combines multiple metrics:
    - Version currency (25 points)
    - Deployment freshness (25 points)
    - Data completeness (25 points)
    - Cleanup effectiveness (25 points)
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    sport = request.args.get('sport', 'nba')

    try:
        score_breakdown = {}

        # 1. Version Currency (25 points)
        # Deduct points if multiple versions or old versions
        version_response = _get_version_score(sport)
        score_breakdown['version_currency'] = version_response

        # 2. Deployment Freshness (25 points)
        freshness_response = _get_freshness_score(sport)
        score_breakdown['deployment_freshness'] = freshness_response

        # 3. Data Completeness (25 points) - simplified for now
        # TODO: Add actual completeness check
        score_breakdown['data_completeness'] = 25

        # 4. Cleanup Effectiveness (25 points)
        cleanup_response = _get_cleanup_score(sport)
        score_breakdown['cleanup_effectiveness'] = cleanup_response

        # Calculate overall score
        overall_score = sum(score_breakdown.values())

        # Determine status
        if overall_score >= 95:
            status = 'excellent'
        elif overall_score >= 85:
            status = 'good'
        elif overall_score >= 70:
            status = 'fair'
        else:
            status = 'poor'

        return jsonify({
            'overall_score': overall_score,
            'status': status,
            'breakdown': score_breakdown,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Failed to calculate quality score: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


def _get_version_score(sport: str) -> int:
    """Calculate version currency score."""
    try:
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
        SELECT
            processor_version,
            MAX(processed_at) as last_seen
        FROM `{project_id}.{sport}_analytics.player_game_summary`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND processor_version IS NOT NULL
        GROUP BY processor_version
        """

        client = get_bq_client()
        result = client.query(query).result()

        versions = list(result)
        version_score = 25

        # Deduct if multiple versions
        if len(versions) > 1:
            version_score -= 10

        # Deduct if any version is stale (>1 day old)
        for row in versions:
            if row.last_seen:
                hours_old = (datetime.now() - row.last_seen).total_seconds() / 3600
                if hours_old > 24:
                    version_score -= 10
                    break

        return max(0, version_score)
    except Exception as e:
        logger.error(f"Error calculating version score: {e}", exc_info=True)
        return 0


def _get_freshness_score(sport: str) -> int:
    """Calculate deployment freshness score."""
    try:
        project_id = os.environ.get('GCP_PROJECT_ID')

        query = f"""
        SELECT
            processor_name,
            MAX(processed_at) as last_run
        FROM `{project_id}.{sport}_orchestration.processor_run_history`
        WHERE DATE(processed_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        GROUP BY processor_name
        """

        client = get_bq_client()
        result = client.query(query).result()

        processors = list(result)
        if not processors:
            return 0

        stale_count = 0
        for row in processors:
            hours_since_run = (datetime.now() - row.last_run).total_seconds() / 3600
            if hours_since_run > 48:
                stale_count += 1

        stale_ratio = stale_count / len(processors)
        freshness_score = int(25 * (1 - stale_ratio))

        return freshness_score
    except Exception as e:
        logger.error(f"Error calculating freshness score: {e}", exc_info=True)
        return 0


def _get_cleanup_score(sport: str) -> int:
    """Calculate cleanup effectiveness score."""
    try:
        project_id = os.environ.get('GCP_PROJECT_ID')

        query_stats = f"""
        SELECT
            SUM(CASE WHEN backfilled = TRUE THEN 1 ELSE 0 END) as cleaned,
            SUM(CASE WHEN backfilled = FALSE THEN 1 ELSE 0 END) as pending
        FROM `{project_id}.{sport}_orchestration.scraper_failures`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        """

        client = get_bq_client()
        result = client.query(query_stats).result()

        row = next(result, None)
        if not row:
            return 25  # No failures is good

        cleaned = row.cleaned or 0
        pending = row.pending or 0

        if cleaned + pending == 0:
            return 25  # No failures is good

        cleanup_rate = cleaned / (cleaned + pending)
        cleanup_score = int(25 * cleanup_rate)

        return cleanup_score
    except Exception as e:
        logger.error(f"Error calculating cleanup score: {e}", exc_info=True)
        return 0

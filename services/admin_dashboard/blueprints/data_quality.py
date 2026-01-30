"""
Data Quality Blueprint - Monitor prevention system effectiveness.

Tracks:
- Processor version distribution
- Deployment freshness
- Schema validation history
- Scraper failure cleanup effectiveness
- Data quality score

Routes:
- GET /data-quality: Data quality dashboard page
- GET /api/data-quality/version-distribution: Processor version distribution
- GET /api/data-quality/deployment-freshness: Deployment freshness check
- GET /api/data-quality/scraper-cleanup-stats: Scraper cleanup effectiveness
- GET /api/data-quality/score: Overall data quality score
- GET /api/errors: Error feed with categorization (real vs expected)
"""

import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, jsonify, request, render_template

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


@data_quality_bp.route('/data-quality')
@rate_limit
def data_quality_page():
    """Data quality dashboard page."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    sport = request.args.get('sport', 'nba')

    # Get today's date in ET
    et = ZoneInfo('America/New_York')
    today = datetime.now(et).strftime('%Y-%m-%d')

    return render_template('data_quality.html', sport=sport, today=today)




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


# =============================================================================
# VALIDATION METRICS (Session 31)
# =============================================================================

@data_quality_bp.route('/api/data-quality/validation-summary')
@rate_limit
def get_validation_summary():
    """
    Get validation metrics from the v_daily_validation_summary view.

    Shows DNP voiding, feature store health, prediction bounds, etc.
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    days = clamp_param(request.args.get('days', 7), 1, 30, 7)
    project_id = os.environ.get('GCP_PROJECT_ID')

    try:
        client = get_bq_client()

        # Query the validation summary view
        query = f"""
        SELECT
            check_date,
            -- Feature Store Health
            l5_cache_match_pct,
            duplicate_count,
            invalid_array_count,
            feature_bounds_violations_pct,
            prop_line_coverage_pct,
            -- Prediction Quality
            dnp_graded_count,
            placeholder_graded_count,
            prediction_outlier_pct,
            high_confidence_accuracy_pct,
            -- Cross-Phase Health
            row_count_variance_pct,
            grading_completeness_pct,
            player_flow_completeness_pct,
            -- Overall Status
            overall_status,
            issues_count,
            warnings_count
        FROM `{project_id}.nba_predictions.v_daily_validation_summary`
        WHERE check_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        ORDER BY check_date DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("days", "INT64", days)
            ]
        )

        result = client.query(query, job_config=job_config).result()

        validations = []
        for row in result:
            validations.append({
                'date': row.check_date.isoformat() if row.check_date else None,
                'feature_store': {
                    'l5_cache_match_pct': float(row.l5_cache_match_pct) if row.l5_cache_match_pct else None,
                    'duplicate_count': row.duplicate_count,
                    'invalid_array_count': row.invalid_array_count,
                    'bounds_violations_pct': float(row.feature_bounds_violations_pct) if row.feature_bounds_violations_pct else None,
                    'prop_line_coverage_pct': float(row.prop_line_coverage_pct) if row.prop_line_coverage_pct else None,
                },
                'prediction_quality': {
                    'dnp_graded_count': row.dnp_graded_count,
                    'placeholder_graded_count': row.placeholder_graded_count,
                    'outlier_pct': float(row.prediction_outlier_pct) if row.prediction_outlier_pct else None,
                    'high_conf_accuracy_pct': float(row.high_confidence_accuracy_pct) if row.high_confidence_accuracy_pct else None,
                },
                'cross_phase': {
                    'row_count_variance_pct': float(row.row_count_variance_pct) if row.row_count_variance_pct else None,
                    'grading_completeness_pct': float(row.grading_completeness_pct) if row.grading_completeness_pct else None,
                    'player_flow_pct': float(row.player_flow_completeness_pct) if row.player_flow_completeness_pct else None,
                },
                'overall_status': row.overall_status,
                'issues_count': row.issues_count,
                'warnings_count': row.warnings_count,
            })

        # Calculate summary stats
        pass_count = sum(1 for v in validations if v['overall_status'] == 'PASS')
        fail_count = sum(1 for v in validations if v['overall_status'] == 'FAIL')
        warn_count = sum(1 for v in validations if v['overall_status'] == 'WARN')

        return jsonify({
            'validations': validations,
            'summary': {
                'days_checked': len(validations),
                'pass_count': pass_count,
                'fail_count': fail_count,
                'warn_count': warn_count,
                'health_pct': round(pass_count / len(validations) * 100, 1) if validations else 0,
            },
            'days': days
        })

    except Exception as e:
        logger.error(f"Failed to get validation summary: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@data_quality_bp.route('/api/data-quality/dnp-voiding')
@rate_limit
def get_dnp_voiding_status():
    """
    Get DNP voiding check results for recent dates.

    DNP = Did Not Play (actual_points=0 AND minutes_played=0/NULL).
    These should be voided (prediction_correct=NULL), not graded.
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    days = clamp_param(request.args.get('days', 7), 1, 30, 7)
    project_id = os.environ.get('GCP_PROJECT_ID')

    try:
        client = get_bq_client()

        query = f"""
        SELECT
            game_date,
            COUNTIF(actual_points = 0 AND (minutes_played = 0 OR minutes_played IS NULL)) as total_dnp,
            COUNTIF(actual_points = 0 AND (minutes_played = 0 OR minutes_played IS NULL) AND prediction_correct IS NULL) as dnp_voided,
            COUNTIF(actual_points = 0 AND (minutes_played = 0 OR minutes_played IS NULL) AND prediction_correct IS NOT NULL) as dnp_graded_incorrectly
        FROM `{project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        GROUP BY game_date
        ORDER BY game_date DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("days", "INT64", days)
            ]
        )

        result = client.query(query, job_config=job_config).result()

        dnp_data = []
        total_incorrect = 0
        for row in result:
            incorrect = row.dnp_graded_incorrectly or 0
            total_incorrect += incorrect
            dnp_data.append({
                'date': row.game_date.isoformat(),
                'total_dnp': row.total_dnp or 0,
                'voided': row.dnp_voided or 0,
                'incorrectly_graded': incorrect,
                'status': 'PASS' if incorrect == 0 else 'FAIL',
            })

        return jsonify({
            'dnp_data': dnp_data,
            'summary': {
                'days_checked': len(dnp_data),
                'total_incorrect': total_incorrect,
                'status': 'PASS' if total_incorrect == 0 else 'FAIL',
            },
            'days': days
        })

    except Exception as e:
        logger.error(f"Failed to get DNP voiding status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@data_quality_bp.route('/api/data-quality/prediction-integrity')
@rate_limit
def get_prediction_integrity():
    """
    Check for prediction value drift between tables.

    Compares predicted_points in player_prop_predictions vs prediction_accuracy.
    Catches grading bugs that corrupt values during grading.
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    days = clamp_param(request.args.get('days', 7), 1, 30, 7)
    project_id = os.environ.get('GCP_PROJECT_ID')

    try:
        client = get_bq_client()

        query = f"""
        SELECT
            pa.game_date,
            pa.system_id,
            COUNT(*) as total_records,
            COUNTIF(ABS(pa.predicted_points - p.predicted_points) > 0.5) as drift_records,
            ROUND(100.0 * COUNTIF(ABS(pa.predicted_points - p.predicted_points) > 0.5) / COUNT(*), 1) as drift_pct,
            ROUND(MAX(ABS(pa.predicted_points - p.predicted_points)), 1) as max_drift
        FROM `{project_id}.nba_predictions.prediction_accuracy` pa
        JOIN `{project_id}.nba_predictions.player_prop_predictions` p
            ON pa.player_lookup = p.player_lookup
            AND pa.game_id = p.game_id
            AND pa.system_id = p.system_id
        WHERE pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        GROUP BY pa.game_date, pa.system_id
        HAVING drift_pct > 0
        ORDER BY pa.game_date DESC, drift_pct DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("days", "INT64", days)
            ]
        )

        result = client.query(query, job_config=job_config).result()

        drift_data = []
        total_drift_records = 0
        for row in result:
            total_drift_records += row.drift_records
            drift_data.append({
                'date': row.game_date.isoformat(),
                'system_id': row.system_id,
                'total_records': row.total_records,
                'drift_records': row.drift_records,
                'drift_pct': row.drift_pct,
                'max_drift': row.max_drift,
            })

        return jsonify({
            'drift_data': drift_data,
            'summary': {
                'dates_with_drift': len(set(d['date'] for d in drift_data)),
                'systems_affected': len(set(d['system_id'] for d in drift_data)),
                'total_drift_records': total_drift_records,
                'status': 'PASS' if total_drift_records == 0 else 'FAIL',
            },
            'days': days
        })

    except Exception as e:
        logger.error(f"Failed to get prediction integrity: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

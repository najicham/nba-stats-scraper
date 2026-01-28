"""
Pipeline Health Summary Cloud Function

Generates and sends a daily email summary of pipeline health.
Triggered by Cloud Scheduler at 6 AM Pacific Time.

Architecture:
- Triggered by: HTTP (Cloud Scheduler)
- Queries: BigQuery processor_run_history table
- Sends: Email via AWS SES

Version: 1.0
Created: 2025-11-30
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from google.cloud import bigquery
import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')

# Phase configuration
# Filter by processor_name patterns since phase column may not be populated
PHASE_CONFIG = {
    'Phase 1 (Scrapers)': {
        'phase_filter': "processor_name LIKE '%Scraper%' OR processor_name LIKE '%scraper%'",
        'expected_count': 21
    },
    'Phase 2 (Raw)': {
        'phase_filter': """(
            processor_name LIKE '%Processor'
            AND processor_name NOT LIKE '%Summary%'
            AND processor_name NOT LIKE '%Composite%'
            AND processor_name NOT LIKE '%Cache%'
            AND processor_name NOT LIKE '%Zone%'
            AND processor_name NOT LIKE '%Feature%'
            AND processor_name NOT LIKE '%Context%'
            AND processor_name NOT LIKE 'Prediction%'
        )""",
        'expected_count': 21
    },
    'Phase 3 (Analytics)': {
        'phase_filter': """(
            (processor_name LIKE '%GameSummaryProcessor'
             OR processor_name LIKE '%GameContextProcessor')
            AND processor_name NOT LIKE 'Async%'
        )""",
        'expected_count': 5
    },
    'Phase 4 (Precompute)': {
        'phase_filter': """(
            processor_name LIKE '%CompositeFactors%'
            OR processor_name LIKE '%DailyCache%'
            OR processor_name LIKE '%ZoneAnalysis%'
            OR processor_name LIKE '%FeatureStore%'
        )""",
        'expected_count': 5
    },
    'Phase 5 (Predictions)': {
        'phase_filter': "processor_name LIKE 'Prediction%' OR processor_name = 'PredictionCoordinator'",
        'expected_count': 1  # Coordinator run
    }
}


@functions_framework.http
def pipeline_health_summary(request):
    """
    Generate and send daily pipeline health summary email.

    Triggered by Cloud Scheduler HTTP request.

    Query params:
        - date: Optional date to report on (YYYY-MM-DD), defaults to yesterday

    Returns:
        JSON response with status
    """
    try:
        # Parse date from request or default to yesterday
        request_json = request.get_json(silent=True) or {}
        request_args = request.args

        date_str = (
            request_json.get('date') or
            request_args.get('date') or
            (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')
        )

        logger.info(f"Generating pipeline health summary for {date_str}")

        # Initialize BigQuery client
        bq_client = bigquery.Client(project=PROJECT_ID)

        # Gather health data
        health_data = gather_health_data(bq_client, date_str)

        # Send email
        success = send_health_email(health_data)

        if success:
            logger.info(f"✅ Pipeline health summary sent for {date_str}")
            return {'status': 'success', 'date': date_str, 'email_sent': True}, 200
        else:
            logger.error(f"Failed to send health summary email for {date_str}")
            return {'status': 'error', 'date': date_str, 'email_sent': False, 'error': 'Email send failed'}, 500

    except Exception as e:
        logger.error(f"Error generating pipeline health summary: {e}", exc_info=True)
        return {'status': 'error', 'error': str(e)}, 500


def gather_health_data(bq_client: bigquery.Client, date_str: str) -> Dict:
    """
    Query BigQuery for pipeline health metrics.

    Args:
        bq_client: BigQuery client
        date_str: Date to report on (YYYY-MM-DD)

    Returns:
        Dictionary with health data for email
    """
    phases = {}
    total_records = 0
    total_duration_seconds = 0
    earliest_start = None
    latest_end = None

    for phase_name, config in PHASE_CONFIG.items():
        phase_data = query_phase_status(
            bq_client,
            date_str,
            config['phase_filter'],
            config['expected_count']
        )
        phases[phase_name] = phase_data

        # Aggregate totals
        total_records += phase_data.get('records_processed', 0)

        if phase_data.get('earliest_start'):
            if earliest_start is None or phase_data['earliest_start'] < earliest_start:
                earliest_start = phase_data['earliest_start']

        if phase_data.get('latest_end'):
            if latest_end is None or phase_data['latest_end'] > latest_end:
                latest_end = phase_data['latest_end']

    # Calculate total duration
    if earliest_start and latest_end:
        total_duration_seconds = (latest_end - earliest_start).total_seconds()

    # Check for gaps
    gaps_detected = query_gaps_count(bq_client, date_str)

    # Check roster coverage (added after Jan 23 incident)
    roster_coverage = query_roster_coverage(bq_client, date_str)

    # Determine overall quality
    data_quality = determine_overall_quality(phases)

    return {
        'date': date_str,
        'phases': phases,
        'total_duration_minutes': int(total_duration_seconds / 60),
        'data_quality': data_quality,
        'gaps_detected': gaps_detected,
        'records_processed': total_records,
        'roster_coverage': roster_coverage  # Added after Jan 23 incident
    }


def query_phase_status(
    bq_client: bigquery.Client,
    date_str: str,
    phase_filter: str,
    expected_count: int
) -> Dict:
    """
    Query status for a specific phase.

    Args:
        bq_client: BigQuery client
        date_str: Date to query
        phase_filter: SQL WHERE clause for this phase
        expected_count: Expected number of processors

    Returns:
        Dictionary with phase status
    """
    # FIX: Use COUNT(DISTINCT processor_name) for each status to count unique
    # processors, not total rows. A processor may run multiple times per day.
    query = f"""
    SELECT
        COUNT(DISTINCT processor_name) as processor_count,
        COUNT(DISTINCT CASE WHEN status = 'success' THEN processor_name END) as success_count,
        COUNT(DISTINCT CASE WHEN status = 'partial' THEN processor_name END) as partial_count,
        COUNT(DISTINCT CASE WHEN status IN ('failed', 'error') THEN processor_name END) as failed_count,
        SUM(COALESCE(records_processed, 0)) as records_processed,
        MIN(started_at) as earliest_start,
        MAX(processed_at) as latest_end
    FROM `{PROJECT_ID}.nba_reference.processor_run_history`
    WHERE data_date = '{date_str}'
      AND ({phase_filter})
    """

    try:
        result = bq_client.query(query).result(timeout=60)
        row = list(result)[0]

        complete = row.success_count + row.partial_count
        total = expected_count

        # Determine status
        if complete >= total:
            status = 'success'
        elif complete > 0:
            status = 'partial'
        elif row.failed_count > 0:
            status = 'failed'
        else:
            status = 'not_started'

        return {
            'complete': complete,
            'total': total,
            'status': status,
            'records_processed': row.records_processed or 0,
            'earliest_start': row.earliest_start,
            'latest_end': row.latest_end
        }

    except Exception as e:
        logger.error(f"Error querying phase status: {e}")
        return {
            'complete': 0,
            'total': expected_count,
            'status': 'unknown',
            'records_processed': 0
        }


def query_roster_coverage(bq_client: bigquery.Client, date_str: str) -> Dict:
    """
    Query ESPN roster coverage to catch stale roster data.

    This check was added after the Jan 23, 2026 incident where stale ESPN rosters
    (last updated Jan 14) caused POR/SAC players to be missing from predictions.

    Args:
        bq_client: BigQuery client
        date_str: Date to check

    Returns:
        Dictionary with roster coverage status
    """
    query = f"""
    WITH roster_freshness AS (
        SELECT
            team_abbr,
            MAX(roster_date) as latest_roster,
            DATE_DIFF(DATE('{date_str}'), MAX(roster_date), DAY) as age_days
        FROM `{PROJECT_ID}.nba_raw.espn_team_rosters`
        WHERE roster_date >= DATE_SUB(DATE('{date_str}'), INTERVAL 90 DAY)
        GROUP BY team_abbr
    )
    SELECT
        COUNT(*) as total_teams,
        COUNTIF(age_days <= 3) as teams_current,
        COUNTIF(age_days > 3 AND age_days <= 5) as teams_stale,
        COUNTIF(age_days > 5) as teams_critical,
        MAX(age_days) as max_age_days
    FROM roster_freshness
    """

    try:
        result = bq_client.query(query).result(timeout=60)
        row = list(result)[0]

        # Determine status
        if row.total_teams >= 30 and row.teams_critical == 0 and row.teams_stale == 0:
            status = 'ok'
        elif row.teams_critical > 0:
            status = 'critical'
        elif row.teams_stale > 0:
            status = 'warning'
        else:
            status = 'unknown'

        return {
            'total_teams': row.total_teams or 0,
            'teams_current': row.teams_current or 0,
            'teams_stale': row.teams_stale or 0,
            'teams_critical': row.teams_critical or 0,
            'max_age_days': row.max_age_days or 0,
            'status': status
        }
    except Exception as e:
        logger.error(f"Error querying roster coverage: {e}")
        return {
            'total_teams': 0,
            'teams_current': 0,
            'teams_stale': 0,
            'teams_critical': 0,
            'max_age_days': 0,
            'status': 'error'
        }


def query_gaps_count(bq_client: bigquery.Client, date_str: str) -> int:
    """
    Query for any detected data gaps on this date.

    Args:
        bq_client: BigQuery client
        date_str: Date to query

    Returns:
        Number of gaps detected
    """
    # Check for failed processors or missing expected processors
    query = f"""
    SELECT COUNT(*) as gap_count
    FROM `{PROJECT_ID}.nba_reference.processor_run_history`
    WHERE data_date = '{date_str}'
      AND status IN ('failed', 'error')
    """

    try:
        result = bq_client.query(query).result(timeout=60)
        row = list(result)[0]
        return row.gap_count or 0
    except Exception as e:
        logger.error(f"Error querying gaps: {e}")
        return 0


def determine_overall_quality(phases: Dict) -> str:
    """
    Determine overall data quality based on phase statuses.

    Args:
        phases: Dictionary of phase statuses

    Returns:
        Quality level: GOLD, SILVER, BRONZE, or UNKNOWN
    """
    all_success = all(p['status'] == 'success' for p in phases.values())
    any_failed = any(p['status'] == 'failed' for p in phases.values())
    any_partial = any(p['status'] == 'partial' for p in phases.values())

    if all_success:
        return 'GOLD'
    elif any_failed:
        return 'BRONZE'
    elif any_partial:
        return 'SILVER'
    else:
        return 'UNKNOWN'


def send_health_email(health_data: Dict) -> bool:
    """
    Send the health summary email via AWS SES and Slack.

    Args:
        health_data: Health data dictionary

    Returns:
        True if sent successfully, False otherwise
    """
    email_success = False
    slack_success = False

    # Send email
    try:
        from shared.utils.email_alerting_ses import EmailAlerterSES
        alerter = EmailAlerterSES()
        email_success = alerter.send_pipeline_health_summary(health_data)
    except ImportError as e:
        logger.error(f"Failed to import EmailAlerterSES: {e}")
    except Exception as e:
        logger.error(f"Failed to send health email: {e}")

    # Send to Slack #nba-pipeline-health channel
    try:
        from shared.utils.slack_channels import send_health_summary_to_slack
        slack_success = send_health_summary_to_slack(health_data)
        if slack_success:
            logger.info("💬 Health summary sent to Slack")
    except Exception as e:
        logger.debug(f"Slack notification skipped: {e}")

    return email_success or slack_success


def query_prediction_stats(bq_client: bigquery.Client, date_str: str) -> Dict:
    """
    Query prediction-specific statistics for the date.

    Args:
        bq_client: BigQuery client
        date_str: Date to query

    Returns:
        Dictionary with prediction stats
    """
    query = f"""
    SELECT
        COUNT(*) as total_predictions,
        COUNT(CASE WHEN confidence_score >= 0.8 THEN 1 END) as high_confidence,
        COUNT(CASE WHEN confidence_score >= 0.5 AND confidence_score < 0.8 THEN 1 END) as medium_confidence,
        COUNT(CASE WHEN confidence_score < 0.5 THEN 1 END) as low_confidence,
        AVG(confidence_score) as avg_confidence
    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
    WHERE game_date = '{date_str}'
      AND is_active = TRUE
    """

    try:
        result = bq_client.query(query).result(timeout=60)
        row = list(result)[0]

        return {
            'total': row.total_predictions or 0,
            'high_confidence': row.high_confidence or 0,
            'medium_confidence': row.medium_confidence or 0,
            'low_confidence': row.low_confidence or 0,
            'avg_confidence': float(row.avg_confidence) if row.avg_confidence else 0.0
        }

    except Exception as e:
        logger.error(f"Error querying prediction stats: {e}")
        return {
            'total': 0,
            'high_confidence': 0,
            'medium_confidence': 0,
            'low_confidence': 0,
            'avg_confidence': 0.0
        }


# For local testing
if __name__ == '__main__':
    import sys

    # Validate required AWS credentials from environment variables
    aws_access_key = os.environ.get('AWS_SES_ACCESS_KEY_ID')
    aws_secret_key = os.environ.get('AWS_SES_SECRET_ACCESS_KEY')

    if not aws_access_key or not aws_secret_key:
        logger.warning(
            "AWS credentials not set. Set AWS_SES_ACCESS_KEY_ID and "
            "AWS_SES_SECRET_ACCESS_KEY environment variables to enable email alerts."
        )

    # Set defaults for optional config from environment variables
    if not os.environ.get('AWS_SES_REGION'):
        os.environ['AWS_SES_REGION'] = os.environ.get('AWS_SES_REGION', 'us-west-2')
    if not os.environ.get('AWS_SES_FROM_EMAIL'):
        logger.warning("AWS_SES_FROM_EMAIL not set, email sending may fail")
    if not os.environ.get('EMAIL_ALERTS_TO'):
        logger.warning("EMAIL_ALERTS_TO not set, email sending may fail")

    # Get date from command line or use yesterday
    if len(sys.argv) > 1:
        test_date = sys.argv[1]
    else:
        test_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')

    print(f"Testing pipeline health summary for {test_date}")

    # Initialize BigQuery client
    bq_client = bigquery.Client(project=PROJECT_ID)

    # Gather and print health data
    health_data = gather_health_data(bq_client, test_date)

    import json
    print("\nHealth Data:")
    print(json.dumps(health_data, indent=2, default=str))

    # Optionally send email
    if '--send' in sys.argv:
        print("\nSending email...")
        success = send_health_email(health_data)
        print(f"Email sent: {success}")
    else:
        print("\nAdd --send flag to send email")

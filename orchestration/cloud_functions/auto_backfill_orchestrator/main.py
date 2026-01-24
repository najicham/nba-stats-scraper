"""
Auto-Backfill Orchestrator Cloud Function
==========================================
Automatically triggers backfill for failed processors.

Detects failed processor runs and triggers appropriate backfills while
respecting circuit breaker logic and rate limits.

Schedule: Every 30 minutes via Cloud Scheduler
Or: Called by stale-processor-monitor after auto-recovery

Version: 1.0
Created: 2026-01-24
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import json

from google.cloud import bigquery, pubsub_v1
from google.cloud.bigquery import ScalarQueryParameter
import functions_framework

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Standardized GCP project ID - uses centralized config
from shared.config.gcp_config import get_project_id
PROJECT_ID = get_project_id()

# Rate limiting
MAX_BACKFILLS_PER_RUN = 5  # Don't trigger more than 5 backfills per invocation
BACKFILL_COOLDOWN_HOURS = 2  # Don't retry within 2 hours

# Circuit breaker
MAX_ATTEMPTS = 3  # Don't retry more than 3 times per date

# Processor dependencies - which processors can be backfilled independently
INDEPENDENT_PROCESSORS = [
    'PlayerShotZoneAnalysisProcessor',
    'TeamDefenseZoneAnalysisProcessor',
]

DEPENDENT_PROCESSORS = [
    'PlayerDailyCacheProcessor',
    'PlayerCompositeFactorsProcessor',
    'MLFeatureStoreProcessor',
]


@functions_framework.http
def auto_backfill_orchestrator(request):
    """
    Detect failed processors and trigger backfills.

    Query params:
        - dry_run: If true, don't trigger backfills (just report)
        - date: Specific date to check (default: last 24h)
        - processor: Specific processor to backfill (optional)
        - max_backfills: Override MAX_BACKFILLS_PER_RUN

    Returns:
        JSON response with backfill results
    """
    try:
        request_json = request.get_json(silent=True) or {}
        dry_run = request_json.get('dry_run', request.args.get('dry_run', 'false')).lower() == 'true'
        specific_date = request_json.get('date', request.args.get('date'))
        specific_processor = request_json.get('processor', request.args.get('processor'))
        max_backfills = int(request_json.get('max_backfills', MAX_BACKFILLS_PER_RUN))

        logger.info(
            f"Auto-backfill orchestrator running (dry_run={dry_run}, "
            f"date={specific_date}, processor={specific_processor})"
        )

        bq_client = bigquery.Client(project=PROJECT_ID)

        # Find failed processors needing backfill
        failed_runs = find_failed_runs(
            bq_client, specific_date, specific_processor
        )

        logger.info(f"Found {len(failed_runs)} failed runs to consider")

        # Filter by circuit breaker and cooldown
        eligible_runs = filter_eligible_runs(bq_client, failed_runs)

        logger.info(f"{len(eligible_runs)} runs eligible for backfill")

        # Limit to max backfills
        runs_to_backfill = eligible_runs[:max_backfills]

        results = {
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'total_failed': len(failed_runs),
            'eligible': len(eligible_runs),
            'triggered': 0,
            'backfills': []
        }

        if not dry_run:
            for run in runs_to_backfill:
                backfill_result = trigger_backfill(bq_client, run)
                results['backfills'].append(backfill_result)
                if backfill_result['success']:
                    results['triggered'] += 1
        else:
            # Just report what would be backfilled
            for run in runs_to_backfill:
                results['backfills'].append({
                    'processor_name': run['processor_name'],
                    'data_date': run['data_date'],
                    'dry_run': True,
                    'would_trigger': True
                })

        # Log summary
        logger.info(
            f"Backfill complete: {results['triggered']}/{len(runs_to_backfill)} triggered "
            f"(dry_run={dry_run})"
        )

        return results, 200

    except Exception as e:
        logger.error(f"Auto-backfill orchestrator error: {e}", exc_info=True)
        return {'status': 'error', 'error': str(e)}, 500


def find_failed_runs(
    bq_client: bigquery.Client,
    specific_date: Optional[str] = None,
    specific_processor: Optional[str] = None
) -> List[Dict]:
    """
    Find failed processor runs that might need backfill.

    Args:
        bq_client: BigQuery client
        specific_date: Specific date to check (optional)
        specific_processor: Specific processor to check (optional)

    Returns:
        List of failed run records
    """
    # Build parameterized query with optional filters
    query_parameters = []

    if specific_date:
        date_filter = "data_date = @specific_date"
        query_parameters.append(
            ScalarQueryParameter("specific_date", "DATE", specific_date)
        )
    else:
        date_filter = "data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)"

    if specific_processor:
        processor_filter = "AND processor_name = @specific_processor"
        query_parameters.append(
            ScalarQueryParameter("specific_processor", "STRING", specific_processor)
        )
    else:
        processor_filter = ""

    query = f"""
    WITH latest_runs AS (
        SELECT
            processor_name,
            data_date,
            status,
            failure_category,
            skip_reason,
            started_at,
            completed_at,
            ROW_NUMBER() OVER (
                PARTITION BY processor_name, data_date
                ORDER BY started_at DESC
            ) as rn
        FROM `{PROJECT_ID}.nba_reference.processor_run_history`
        WHERE {date_filter}
          {processor_filter}
    )
    SELECT
        processor_name,
        data_date,
        status,
        failure_category,
        skip_reason,
        started_at,
        completed_at
    FROM latest_runs
    WHERE rn = 1
      AND status IN ('failed', 'skipped')
      AND failure_category NOT IN ('no_data_available', 'offseason')
    ORDER BY data_date DESC, processor_name
    """

    try:
        job_config = bigquery.QueryJobConfig(query_parameters=query_parameters)
        result = list(bq_client.query(query, job_config=job_config).result())
        runs = []
        for row in result:
            runs.append({
                'processor_name': row.processor_name,
                'data_date': str(row.data_date),
                'status': row.status,
                'failure_category': row.failure_category,
                'skip_reason': row.skip_reason,
                'started_at': row.started_at.isoformat() if row.started_at else None,
                'completed_at': row.completed_at.isoformat() if row.completed_at else None
            })
        return runs

    except Exception as e:
        logger.error(f"Error finding failed runs: {e}", exc_info=True)
        return []


def filter_eligible_runs(bq_client: bigquery.Client, runs: List[Dict]) -> List[Dict]:
    """
    Filter runs by circuit breaker and cooldown.

    Args:
        bq_client: BigQuery client
        runs: List of failed runs

    Returns:
        List of eligible runs
    """
    if not runs:
        return []

    eligible = []

    for run in runs:
        # Check circuit breaker (reprocess_attempts table)
        processor_name = run['processor_name']
        data_date = run['data_date']

        cb_query = f"""
        SELECT
            MAX(attempt_number) as attempts,
            MAX(attempted_at) as last_attempt,
            LOGICAL_OR(circuit_breaker_tripped) as tripped
        FROM `{PROJECT_ID}.nba_orchestration.reprocess_attempts`
        WHERE processor_name = @processor_name
          AND analysis_date = DATE(@data_date)
        """

        try:
            cb_job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    ScalarQueryParameter("processor_name", "STRING", processor_name),
                    ScalarQueryParameter("data_date", "STRING", data_date),
                ]
            )
            cb_result = list(bq_client.query(cb_query, job_config=cb_job_config).result())

            if cb_result and cb_result[0]:
                row = cb_result[0]
                attempts = row.attempts or 0
                last_attempt = row.last_attempt
                tripped = row.tripped or False

                # Circuit breaker tripped
                if tripped:
                    logger.debug(f"Skipping {processor_name}/{data_date}: circuit breaker tripped")
                    continue

                # Max attempts reached
                if attempts >= MAX_ATTEMPTS:
                    logger.debug(f"Skipping {processor_name}/{data_date}: max attempts ({attempts})")
                    continue

                # Cooldown period
                if last_attempt:
                    cooldown_until = last_attempt + timedelta(hours=BACKFILL_COOLDOWN_HOURS)
                    if datetime.now(timezone.utc) < cooldown_until.replace(tzinfo=timezone.utc):
                        logger.debug(f"Skipping {processor_name}/{data_date}: cooldown until {cooldown_until}")
                        continue

        except Exception as e:
            logger.warning(f"Error checking circuit breaker for {processor_name}: {e}")
            # Continue anyway if we can't check

        eligible.append(run)

    return eligible


def trigger_backfill(bq_client: bigquery.Client, run: Dict) -> Dict:
    """
    Trigger backfill for a processor/date.

    Args:
        bq_client: BigQuery client
        run: Run info dict

    Returns:
        Backfill result dict
    """
    processor_name = run['processor_name']
    data_date = run['data_date']

    logger.info(f"Triggering backfill for {processor_name} on {data_date}")

    result = {
        'processor_name': processor_name,
        'data_date': data_date,
        'success': False,
        'method': None,
        'message': None
    }

    try:
        # Record the backfill attempt
        record_backfill_attempt(bq_client, processor_name, data_date)

        # Determine backfill method based on processor type
        if processor_name in INDEPENDENT_PROCESSORS:
            # Can trigger directly via Pub/Sub
            success = trigger_via_pubsub(processor_name, data_date)
            result['method'] = 'pubsub'
            result['success'] = success
            result['message'] = 'Pub/Sub trigger sent' if success else 'Pub/Sub trigger failed'

        elif processor_name in DEPENDENT_PROCESSORS:
            # Need to trigger via Cloud Run job or wait for dependencies
            success = trigger_via_cloud_run(processor_name, data_date)
            result['method'] = 'cloud_run'
            result['success'] = success
            result['message'] = 'Cloud Run job triggered' if success else 'Cloud Run trigger failed'

        else:
            # Unknown processor - try generic Pub/Sub
            success = trigger_via_pubsub(processor_name, data_date)
            result['method'] = 'pubsub_generic'
            result['success'] = success
            result['message'] = 'Generic Pub/Sub trigger sent' if success else 'Pub/Sub trigger failed'

        logger.info(f"Backfill result for {processor_name}: {result['message']}")

    except Exception as e:
        logger.error(f"Error triggering backfill for {processor_name}: {e}", exc_info=True)
        result['message'] = str(e)

    return result


def record_backfill_attempt(bq_client: bigquery.Client, processor_name: str, data_date: str):
    """Record backfill attempt in reprocess_attempts table."""
    query = f"""
    INSERT INTO `{PROJECT_ID}.nba_orchestration.reprocess_attempts`
    (processor_name, entity_id, analysis_date, attempt_number, attempted_at,
     completeness_pct, skip_reason, circuit_breaker_tripped, notes)
    SELECT
        @processor_name as processor_name,
        'auto_backfill' as entity_id,
        DATE(@data_date) as analysis_date,
        COALESCE(MAX(attempt_number), 0) + 1 as attempt_number,
        CURRENT_TIMESTAMP() as attempted_at,
        0.0 as completeness_pct,
        'auto_backfill_triggered' as skip_reason,
        FALSE as circuit_breaker_tripped,
        'Triggered by auto_backfill_orchestrator' as notes
    FROM `{PROJECT_ID}.nba_orchestration.reprocess_attempts`
    WHERE processor_name = @processor_name
      AND analysis_date = DATE(@data_date)
    """

    try:
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                ScalarQueryParameter("processor_name", "STRING", processor_name),
                ScalarQueryParameter("data_date", "STRING", data_date),
            ]
        )
        bq_client.query(query, job_config=job_config).result()
    except Exception as e:
        logger.warning(f"Failed to record backfill attempt: {e}")


def trigger_via_pubsub(processor_name: str, data_date: str) -> bool:
    """
    Trigger processor via Pub/Sub message.

    Args:
        processor_name: Name of processor
        data_date: Date to process

    Returns:
        True if message published successfully
    """
    try:
        publisher = pubsub_v1.PublisherClient()

        # Determine appropriate topic based on processor phase
        if 'Phase3' in processor_name or 'Analytics' in processor_name:
            topic_name = f'projects/{PROJECT_ID}/topics/nba-phase3-trigger'
        elif 'Phase4' in processor_name or 'Precompute' in processor_name or processor_name in DEPENDENT_PROCESSORS:
            topic_name = f'projects/{PROJECT_ID}/topics/nba-phase4-trigger'
        else:
            topic_name = f'projects/{PROJECT_ID}/topics/nba-backfill-trigger'

        message = {
            'processor_name': processor_name,
            'analysis_date': data_date,
            'trigger_source': 'auto_backfill_orchestrator',
            'triggered_at': datetime.now(timezone.utc).isoformat()
        }

        future = publisher.publish(
            topic_name,
            json.dumps(message).encode('utf-8'),
            processor_name=processor_name,
            analysis_date=data_date,
            source='auto_backfill'
        )

        message_id = future.result(timeout=10)
        logger.info(f"Published backfill trigger to {topic_name}: {message_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to publish to Pub/Sub: {e}", exc_info=True)
        return False


def trigger_via_cloud_run(processor_name: str, data_date: str) -> bool:
    """
    Trigger processor via Cloud Run job.

    Args:
        processor_name: Name of processor
        data_date: Date to process

    Returns:
        True if job triggered successfully
    """
    try:
        # Use Cloud Run Jobs API
        from google.cloud import run_v2

        client = run_v2.JobsClient()

        # Map processor to Cloud Run job name
        job_mapping = {
            'PlayerDailyCacheProcessor': 'player-daily-cache-backfill',
            'PlayerCompositeFactorsProcessor': 'player-composite-factors-backfill',
            'MLFeatureStoreProcessor': 'ml-feature-store-backfill',
        }

        job_name = job_mapping.get(processor_name, f'{processor_name.lower()}-backfill')
        job_path = f'projects/{PROJECT_ID}/locations/us-west2/jobs/{job_name}'

        # Run the job with overrides
        request = run_v2.RunJobRequest(
            name=job_path,
            overrides=run_v2.RunJobRequest.Overrides(
                container_overrides=[
                    run_v2.RunJobRequest.Overrides.ContainerOverride(
                        env=[
                            run_v2.EnvVar(name='ANALYSIS_DATE', value=data_date),
                            run_v2.EnvVar(name='TRIGGER_SOURCE', value='auto_backfill'),
                        ]
                    )
                ]
            )
        )

        operation = client.run_job(request=request)
        logger.info(f"Cloud Run job triggered: {job_name} for {data_date}")
        return True

    except Exception as e:
        logger.error(f"Failed to trigger Cloud Run job: {e}", exc_info=True)
        # Fall back to Pub/Sub
        logger.info("Falling back to Pub/Sub trigger")
        return trigger_via_pubsub(processor_name, data_date)


def send_backfill_summary_alert(results: Dict) -> bool:
    """
    Send Slack alert with backfill summary.

    Args:
        results: Backfill results dict

    Returns:
        True if alert sent
    """
    try:
        from shared.utils.slack_alerting import send_slack_alert

        triggered = results['triggered']
        total = len(results['backfills'])

        if triggered == 0:
            return False  # Don't alert if nothing triggered

        text = f"Auto-Backfill: {triggered}/{total} processors triggered"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": ":arrows_counterclockwise: Auto-Backfill Triggered"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Triggered:* {triggered}\n"
                        f"*Eligible:* {results['eligible']}\n"
                        f"*Total Failed:* {results['total_failed']}"
                    )
                }
            }
        ]

        for bf in results['backfills'][:5]:
            if bf.get('success'):
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":white_check_mark: *{bf['processor_name']}* ({bf['data_date']}) - {bf['method']}"
                    }
                })

        send_slack_alert(
            channel='#nba-alerts',
            text=text,
            blocks=blocks
        )
        return True

    except Exception as e:
        logger.error(f"Failed to send backfill alert: {e}", exc_info=True)
        return False


@functions_framework.http
def health(request):
    """Health check endpoint for auto_backfill_orchestrator."""
    return json.dumps({
        'status': 'healthy',
        'function': 'auto_backfill_orchestrator',
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}

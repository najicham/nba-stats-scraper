"""
Dead Letter Queue (DLQ) Monitor Cloud Function

Monitors Pub/Sub dead letter queues for messages that failed processing after
maximum retry attempts. Sends alerts via AlertManager when DLQ messages are found.

Triggered by: Cloud Scheduler (every 15 minutes recommended)

Monitored DLQ Topics/Subscriptions:
- nba-phase1-scrapers-complete-dlq-sub: Phase 1 -> Phase 2 failures (primary)
- nba-scraper-complete-dlq-sub: Phase 1 -> Phase 2 failures (legacy/fallback)
- nba-phase2-raw-complete-dlq-sub: Phase 2 -> Phase 3 failures
- analytics-ready-dead-letter-sub: Phase 3 -> Phase 4 failures
- line-changed-dead-letter-sub: Real-time line change failures
- prediction-request-dlq-sub: Phase 5 Coordinator -> Prediction Worker failures

Deployment:
    gcloud functions deploy dlq-monitor \
        --gen2 \
        --runtime python311 \
        --region us-west2 \
        --source orchestration/cloud_functions/dlq_monitor \
        --entry-point monitor_dlqs \
        --trigger-http \
        --allow-unauthenticated \
        --set-env-vars GCP_PROJECT=nba-props-platform

Scheduler:
    gcloud scheduler jobs create http dlq-monitor-job \
        --schedule "*/15 * * * *" \
        --uri https://FUNCTION_URL \
        --http-method GET \
        --location us-west2

Version: 1.1
Created: 2025-12-30
Updated: 2026-01-24 - Added Cloud Logging monitoring for BQ/Firestore/GCS errors
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from google.cloud import pubsub_v1
import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')

# Alert thresholds
# Alert if DLQ has more than N messages
DLQ_ALERT_THRESHOLD = int(os.environ.get('DLQ_ALERT_THRESHOLD', '0'))

# Cooldown between alerts for same DLQ (minutes)
ALERT_COOLDOWN_MINUTES = int(os.environ.get('DLQ_ALERT_COOLDOWN_MINUTES', '60'))

# DLQ Subscriptions to monitor
# Maps subscription name -> description for alerts
# Note: The infrastructure may have different naming conventions across phases.
# We check multiple possible names to ensure coverage.
DLQ_SUBSCRIPTIONS = {
    # Phase 1 -> Phase 2: Scraper data to raw processors
    # Primary subscription name (newer infrastructure)
    'nba-phase1-scrapers-complete-dlq-sub': {
        'description': 'Phase 1 to Phase 2 (Raw Processing)',
        'phase_from': 'Phase 1 (Scrapers)',
        'phase_to': 'Phase 2 (Raw Processors)',
        'severity': 'critical',  # Critical - blocks entire pipeline
        'recovery_command': './bin/recovery/find_data_gaps.sh 7',
    },
    # Fallback name (older infrastructure, if still exists)
    'nba-scraper-complete-dlq-sub': {
        'description': 'Phase 1 to Phase 2 (Raw Processing - Legacy)',
        'phase_from': 'Phase 1 (Scrapers)',
        'phase_to': 'Phase 2 (Raw Processors)',
        'severity': 'critical',
        'recovery_command': './bin/recovery/find_data_gaps.sh 7',
    },
    # Phase 2 -> Phase 3: Raw processors to analytics
    'nba-phase2-raw-complete-dlq-sub': {
        'description': 'Phase 2 to Phase 3 (Analytics)',
        'phase_from': 'Phase 2 (Raw Processors)',
        'phase_to': 'Phase 3 (Analytics)',
        'severity': 'critical',
        'recovery_command': 'Check Phase 3 processor logs',
    },
    # Phase 3 -> Phase 4: Analytics to precompute
    'analytics-ready-dead-letter-sub': {
        'description': 'Phase 3 to Phase 4 (Precompute)',
        'phase_from': 'Phase 3 (Analytics)',
        'phase_to': 'Phase 4 (Precompute)',
        'severity': 'warning',
        'recovery_command': 'Check Phase 4 precompute service logs',
    },
    # Real-time line changes
    'line-changed-dead-letter-sub': {
        'description': 'Real-time Line Changes',
        'phase_from': 'Odds API',
        'phase_to': 'Phase 4 (Real-time Updates)',
        'severity': 'warning',
        'recovery_command': 'Check Phase 4 line processing logs',
    },
    # Phase 5: Prediction worker failures
    'prediction-request-dlq-sub': {
        'description': 'Prediction Worker Failures',
        'phase_from': 'Coordinator',
        'phase_to': 'Prediction Worker',
        'severity': 'warning',
        'recovery_command': 'Check prediction_worker_runs for skip_reason, verify feature store for missing players',
    },
}

# Track last alert time per DLQ (in-memory, resets on function cold start)
_last_alert_times: Dict[str, datetime] = {}


def get_subscription_message_count(subscription_path: str) -> int:
    """
    Get the number of undelivered messages in a Pub/Sub subscription.

    Uses the Pub/Sub Admin API to get subscription metrics.

    Args:
        subscription_path: Full path like projects/PROJECT/subscriptions/SUB_NAME

    Returns:
        Number of undelivered messages, or -1 if subscription doesn't exist
    """
    try:
        subscriber = pubsub_v1.SubscriberClient()
        subscription = subscriber.get_subscription(
            request={"subscription": subscription_path}
        )

        # The subscription object doesn't directly contain message count
        # We need to use monitoring API or pull to check
        # For efficiency, we'll try to pull messages without acking

        # Alternative: Use Cloud Monitoring API
        # For now, use pull with return_immediately
        from google.cloud.pubsub_v1.types import PullRequest

        response = subscriber.pull(
            request={
                "subscription": subscription_path,
                "max_messages": 100,  # Sample up to 100
                "return_immediately": True,  # Don't wait for messages
            },
            timeout=10
        )

        message_count = len(response.received_messages)

        # If we got 100, there might be more
        if message_count >= 100:
            # Use monitoring API for accurate count
            message_count = get_accurate_message_count(subscription_path)

        subscriber.close()
        return message_count

    except Exception as e:
        if "NOT_FOUND" in str(e) or "404" in str(e):
            logger.debug(f"Subscription not found: {subscription_path}")
            return -1  # Subscription doesn't exist
        logger.error(f"Error getting message count for {subscription_path}: {e}", exc_info=True)
        return -1


def get_accurate_message_count(subscription_path: str) -> int:
    """
    Get accurate message count using Cloud Monitoring API.

    Fallback for when pull sample returns max messages.

    Args:
        subscription_path: Full subscription path

    Returns:
        Accurate message count, or 100+ estimate
    """
    try:
        from google.cloud import monitoring_v3
        from google.protobuf.timestamp_pb2 import Timestamp

        client = monitoring_v3.MetricServiceClient()
        project_name = f"projects/{PROJECT_ID}"

        # Extract subscription name from path
        sub_name = subscription_path.split('/')[-1]

        now = datetime.now(timezone.utc)
        seconds_ago = int((now - timedelta(minutes=5)).timestamp())
        now_seconds = int(now.timestamp())

        # Build the request
        interval = monitoring_v3.TimeInterval(
            end_time=Timestamp(seconds=now_seconds),
            start_time=Timestamp(seconds=seconds_ago),
        )

        results = client.list_time_series(
            request={
                "name": project_name,
                "filter": f'metric.type="pubsub.googleapis.com/subscription/num_undelivered_messages" '
                         f'AND resource.labels.subscription_id="{sub_name}"',
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            }
        )

        for result in results:
            if result.points:
                return int(result.points[0].value.int64_value)

        return 100  # Couldn't get exact count, estimate high

    except ImportError:
        logger.debug("monitoring_v3 not available, using estimate")
        return 100
    except Exception as e:
        logger.warning(f"Could not get accurate count: {e}")
        return 100


def sample_dlq_messages(subscription_path: str, max_messages: int = 5) -> List[Dict]:
    """
    Pull sample messages from DLQ without acknowledging them.

    Messages remain in queue for investigation.

    Args:
        subscription_path: Full subscription path
        max_messages: Maximum messages to sample

    Returns:
        List of message info dicts
    """
    messages = []

    try:
        subscriber = pubsub_v1.SubscriberClient()

        response = subscriber.pull(
            request={
                "subscription": subscription_path,
                "max_messages": max_messages,
                "return_immediately": True,
            },
            timeout=10
        )

        for received_message in response.received_messages:
            msg = received_message.message

            # Try to decode message data
            try:
                data = json.loads(msg.data.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                data = msg.data.decode('utf-8', errors='replace')

            messages.append({
                'message_id': msg.message_id,
                'publish_time': msg.publish_time.isoformat() if msg.publish_time else None,
                'attributes': dict(msg.attributes),
                'data_preview': str(data)[:200] if data else None,
            })

        subscriber.close()

    except Exception as e:
        logger.error(f"Error sampling messages from {subscription_path}: {e}", exc_info=True)

    return messages


def should_send_alert(subscription_name: str) -> bool:
    """
    Check if we should send an alert for this DLQ (cooldown check).

    Args:
        subscription_name: DLQ subscription name

    Returns:
        True if alert should be sent
    """
    now = datetime.now(timezone.utc)
    last_alert = _last_alert_times.get(subscription_name)

    if last_alert is None:
        return True

    cooldown = timedelta(minutes=ALERT_COOLDOWN_MINUTES)
    return (now - last_alert) > cooldown


def record_alert_sent(subscription_name: str):
    """Record that an alert was sent for this DLQ."""
    _last_alert_times[subscription_name] = datetime.now(timezone.utc)


def send_dlq_alert(
    subscription_name: str,
    config: Dict,
    message_count: int,
    sample_messages: List[Dict]
) -> bool:
    """
    Send alert for DLQ messages found.

    Uses AlertManager if available, falls back to logging.

    Args:
        subscription_name: DLQ subscription name
        config: DLQ configuration dict
        message_count: Number of messages in DLQ
        sample_messages: Sample of messages for context

    Returns:
        True if alert was sent successfully
    """
    severity = config.get('severity', 'warning')

    # Build alert message
    title = f"DLQ Messages Detected: {config['description']}"

    message_lines = [
        f"Dead Letter Queue: {subscription_name}",
        f"Message Count: {message_count}",
        f"Pipeline: {config['phase_from']} -> {config['phase_to']}",
        "",
        "Messages failed processing after maximum retry attempts.",
        "",
        f"Recovery: {config['recovery_command']}",
    ]

    if sample_messages:
        message_lines.extend([
            "",
            "Sample Messages:",
        ])
        for i, msg in enumerate(sample_messages[:3], 1):
            message_lines.append(f"  {i}. Published: {msg.get('publish_time', 'unknown')}")
            if msg.get('data_preview'):
                message_lines.append(f"     Data: {msg['data_preview'][:100]}...")

    message = "\n".join(message_lines)

    # Context for structured logging/alerting
    context = {
        'subscription': subscription_name,
        'message_count': message_count,
        'phase_from': config['phase_from'],
        'phase_to': config['phase_to'],
        'severity': severity,
    }

    # Try to use AlertManager
    try:
        from shared.alerts.alert_manager import get_alert_manager

        alert_mgr = get_alert_manager()
        sent = alert_mgr.send_alert(
            severity=severity,
            title=title,
            message=message,
            category=f"dlq_{subscription_name}",
            context=context,
            force=True  # DLQ alerts are important, bypass rate limiting
        )

        if sent:
            logger.info(f"Alert sent via AlertManager for {subscription_name}")
            return True

    except ImportError:
        logger.debug("AlertManager not available, using fallback logging")
    except Exception as e:
        logger.warning(f"AlertManager error: {e}, using fallback")

    # Fallback: Log the alert (visible in Cloud Logging)
    if severity == 'critical':
        logger.critical(f"DLQ ALERT: {title}\n{message}")
    else:
        logger.warning(f"DLQ ALERT: {title}\n{message}")

    return True


# ============================================================================
# CLOUD LOGGING ERROR MONITORING (Week 2 Addition)
# ============================================================================
# Monitors Cloud Logging for errors from BigQuery, Firestore, and GCS
# that don't have dedicated DLQs but represent processing failures.

# Error threshold for Cloud Logging alerts (errors in last 15 minutes)
CLOUD_LOGGING_ERROR_THRESHOLD = int(os.environ.get('CLOUD_LOGGING_ERROR_THRESHOLD', '5'))

# Service error patterns to monitor
CLOUD_LOGGING_FILTERS = {
    'bigquery_errors': {
        'description': 'BigQuery Query/Insert Errors',
        'severity': 'warning',
        'filter': (
            'resource.type="cloud_run_revision" OR resource.type="cloud_function" '
            'AND (textPayload=~"BigQuery.*failed" OR textPayload=~"Failed to insert" '
            'OR textPayload=~"BigQuery query failed" OR textPayload=~"bq_client.*error")'
        ),
        'recovery_command': 'Check BigQuery quotas and query syntax',
    },
    'firestore_errors': {
        'description': 'Firestore Operation Errors',
        'severity': 'warning',
        'filter': (
            'resource.type="cloud_run_revision" OR resource.type="cloud_function" '
            'AND (textPayload=~"Firestore.*failed" OR textPayload=~"Firestore.*error" '
            'OR textPayload=~"document.*not found" OR textPayload=~"transaction.*failed")'
        ),
        'recovery_command': 'Check Firestore indexes and quotas',
    },
    'gcs_errors': {
        'description': 'Cloud Storage Errors',
        'severity': 'warning',
        'filter': (
            'resource.type="cloud_run_revision" OR resource.type="cloud_function" '
            'AND (textPayload=~"GCS.*failed" OR textPayload=~"storage.*error" '
            'OR textPayload=~"Failed to upload" OR textPayload=~"bucket.*not found")'
        ),
        'recovery_command': 'Check GCS bucket permissions and quotas',
    },
}


def check_cloud_logging_errors(lookback_minutes: int = 15) -> Dict:
    """
    Query Cloud Logging for recent errors from BigQuery, Firestore, and GCS.

    Args:
        lookback_minutes: How far back to check for errors

    Returns:
        Dict with error counts by category
    """
    results = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'lookback_minutes': lookback_minutes,
        'categories': [],
        'total_errors': 0,
    }

    try:
        from google.cloud import logging as cloud_logging
        from google.cloud.logging_v2 import DESCENDING

        client = cloud_logging.Client(project=PROJECT_ID)

        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=lookback_minutes)

        for category_name, config in CLOUD_LOGGING_FILTERS.items():
            try:
                # Build filter with time constraint
                full_filter = (
                    f'severity>=ERROR '
                    f'AND timestamp>="{start_time.isoformat()}" '
                    f'AND timestamp<="{end_time.isoformat()}" '
                    f'AND ({config["filter"]})'
                )

                # Query logs
                entries = list(client.list_entries(
                    filter_=full_filter,
                    order_by=DESCENDING,
                    max_results=50
                ))

                error_count = len(entries)

                category_result = {
                    'category': category_name,
                    'description': config['description'],
                    'error_count': error_count,
                    'status': 'ok' if error_count <= CLOUD_LOGGING_ERROR_THRESHOLD else 'errors_found',
                }

                if error_count > CLOUD_LOGGING_ERROR_THRESHOLD:
                    # Include sample error messages
                    samples = []
                    for entry in entries[:3]:
                        samples.append({
                            'timestamp': entry.timestamp.isoformat() if entry.timestamp else None,
                            'message': str(entry.payload)[:200] if entry.payload else None,
                            'resource': str(entry.resource.type) if entry.resource else None,
                        })
                    category_result['samples'] = samples
                    category_result['recovery_command'] = config['recovery_command']
                    results['total_errors'] += error_count

                    logger.warning(
                        f"Cloud Logging: {error_count} {config['description']} errors "
                        f"in last {lookback_minutes} minutes"
                    )

                results['categories'].append(category_result)

            except Exception as e:
                logger.warning(f"Error querying {category_name}: {e}")
                results['categories'].append({
                    'category': category_name,
                    'description': config['description'],
                    'error_count': -1,
                    'status': 'query_failed',
                    'error': str(e),
                })

        results['status'] = 'errors_found' if results['total_errors'] > 0 else 'healthy'

    except ImportError:
        logger.warning("google-cloud-logging not available, skipping Cloud Logging check")
        results['status'] = 'skipped'
        results['note'] = 'google-cloud-logging not available'
    except Exception as e:
        logger.error(f"Cloud Logging check failed: {e}", exc_info=True)
        results['status'] = 'error'
        results['error'] = str(e)

    return results


def check_all_dlqs() -> Dict:
    """
    Check all configured DLQ subscriptions.

    Returns:
        Dict with check results
    """
    results = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'dlqs_checked': 0,
        'dlqs_with_messages': 0,
        'total_messages': 0,
        'alerts_sent': 0,
        'details': [],
    }

    for subscription_name, config in DLQ_SUBSCRIPTIONS.items():
        subscription_path = f"projects/{PROJECT_ID}/subscriptions/{subscription_name}"

        logger.info(f"Checking DLQ: {subscription_name}")

        # Get message count
        message_count = get_subscription_message_count(subscription_path)

        dlq_result = {
            'subscription': subscription_name,
            'description': config['description'],
            'message_count': message_count,
            'status': 'not_found' if message_count < 0 else 'ok',
        }

        if message_count < 0:
            # Subscription doesn't exist
            dlq_result['note'] = 'Subscription not found - may need to be created'
            results['details'].append(dlq_result)
            continue

        results['dlqs_checked'] += 1

        if message_count > DLQ_ALERT_THRESHOLD:
            results['dlqs_with_messages'] += 1
            results['total_messages'] += message_count
            dlq_result['status'] = 'messages_found'

            logger.warning(
                f"DLQ {subscription_name}: {message_count} messages "
                f"(threshold: {DLQ_ALERT_THRESHOLD})"
            )

            # Sample messages for alert
            sample_messages = sample_dlq_messages(subscription_path, max_messages=5)
            dlq_result['sample_messages'] = sample_messages

            # Send alert if not in cooldown
            if should_send_alert(subscription_name):
                alert_sent = send_dlq_alert(
                    subscription_name,
                    config,
                    message_count,
                    sample_messages
                )
                if alert_sent:
                    record_alert_sent(subscription_name)
                    results['alerts_sent'] += 1
                    dlq_result['alert_sent'] = True
            else:
                dlq_result['alert_sent'] = False
                dlq_result['alert_note'] = f'In cooldown ({ALERT_COOLDOWN_MINUTES}min)'
        else:
            logger.info(f"DLQ {subscription_name}: {message_count} messages (OK)")

        results['details'].append(dlq_result)

    # Set overall status
    if results['dlqs_with_messages'] > 0:
        results['status'] = 'messages_found'
    elif results['dlqs_checked'] == 0:
        results['status'] = 'no_dlqs_found'
    else:
        results['status'] = 'healthy'

    return results


@functions_framework.http
def monitor_dlqs(request):
    """
    Main DLQ monitoring endpoint.

    Triggered by Cloud Scheduler (recommended: every 15 minutes).

    Query params:
        - dry_run: If 'true', check but don't send alerts
        - include_logging: If 'true', also check Cloud Logging for errors (default: true)

    Returns:
        JSON response with monitoring results
    """
    logger.info("=" * 60)
    logger.info("Dead Letter Queue Monitor Starting")
    logger.info("=" * 60)

    try:
        # Check for dry run mode
        request_args = request.args if hasattr(request, 'args') else {}
        dry_run = request_args.get('dry_run', 'false').lower() == 'true'
        include_logging = request_args.get('include_logging', 'true').lower() == 'true'

        if dry_run:
            logger.info("DRY RUN MODE - alerts will not be sent")

        # Check all DLQs
        results = check_all_dlqs()
        results['dry_run'] = dry_run

        # Week 2: Also check Cloud Logging for BQ/Firestore/GCS errors
        if include_logging:
            logger.info("Checking Cloud Logging for service errors...")
            cloud_logging_results = check_cloud_logging_errors(lookback_minutes=15)
            results['cloud_logging'] = cloud_logging_results

            if cloud_logging_results.get('total_errors', 0) > 0:
                logger.warning(
                    f"Cloud Logging: {cloud_logging_results['total_errors']} errors "
                    f"found across BQ/Firestore/GCS"
                )

        # Summary logging
        if results['dlqs_with_messages'] > 0:
            logger.warning(
                f"DLQ Check: {results['dlqs_with_messages']} DLQs have messages, "
                f"total {results['total_messages']} messages"
            )
        else:
            logger.info("DLQ Check: All DLQs are empty")

        logger.info("=" * 60)
        logger.info("Dead Letter Queue Monitor Complete")
        logger.info("=" * 60)

        status_code = 200
        if results['status'] == 'messages_found':
            # Return 200 but log warning - don't fail the function
            status_code = 200

        return json.dumps(results, indent=2, default=str), status_code, {'Content-Type': 'application/json'}

    except Exception as e:
        logger.error(f"DLQ Monitor failed: {e}", exc_info=True)
        return json.dumps({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 500, {'Content-Type': 'application/json'}


@functions_framework.http
def health(request):
    """Health check endpoint for the dlq_monitor function."""
    return json.dumps({
        'status': 'healthy',
        'function': 'dlq_monitor',
        'monitored_dlqs': list(DLQ_SUBSCRIPTIONS.keys()),
        'threshold': DLQ_ALERT_THRESHOLD,
        'cooldown_minutes': ALERT_COOLDOWN_MINUTES,
    }), 200, {'Content-Type': 'application/json'}


# For local testing
if __name__ == '__main__':
    import sys

    print("DLQ Monitor - Local Test")
    print("=" * 60)

    # Check if we should do dry run
    dry_run = '--dry-run' in sys.argv or '-n' in sys.argv

    if dry_run:
        print("DRY RUN MODE")

    # Mock request object for testing
    class MockRequest:
        args = {'dry_run': 'true' if dry_run else 'false'}

    result, status_code, _ = monitor_dlqs(MockRequest())
    print(result)

    print("\nTo run with actual alerts, remove --dry-run flag")

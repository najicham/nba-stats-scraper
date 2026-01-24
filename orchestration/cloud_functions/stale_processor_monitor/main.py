"""
Stale Processor Monitor Cloud Function
=======================================
Detects and auto-recovers stale processors based on heartbeat data.

Runs every 5 minutes via Cloud Scheduler.
- Checks Firestore for processors with stale heartbeats (> 5 min)
- Auto-recovers dead processors (> 15 min): marks failed, clears locks
- Sends alerts for stale/dead processors

This replaces the previous 4-hour timeout with 15-minute detection,
enabling much faster recovery from stuck processors.

Version: 1.0
Created: 2026-01-24
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List

from google.cloud import firestore, bigquery
import functions_framework

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')

# Thresholds (in seconds)
STALE_THRESHOLD = 300   # 5 minutes - warn
DEAD_THRESHOLD = 900    # 15 minutes - auto-recover
HEARTBEAT_COLLECTION = "processor_heartbeats"


@functions_framework.http
def stale_processor_monitor(request):
    """
    Check for stale processors and auto-recover dead ones.

    Triggered by Cloud Scheduler every 5 minutes.

    Query params:
        - dry_run: If true, don't auto-recover (just report)
        - cleanup: If true, also cleanup old heartbeat docs

    Returns:
        JSON response with check results
    """
    try:
        request_json = request.get_json(silent=True) or {}
        dry_run = request_json.get('dry_run', False)
        cleanup = request_json.get('cleanup', False)

        logger.info(f"Checking for stale processors (dry_run={dry_run})")

        # Initialize clients
        fs_client = firestore.Client(project=PROJECT_ID)
        bq_client = bigquery.Client(project=PROJECT_ID)

        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(seconds=STALE_THRESHOLD)
        dead_threshold = now - timedelta(seconds=DEAD_THRESHOLD)

        # Check all running processors
        results = {
            'checked_at': now.isoformat(),
            'stale_processors': [],
            'dead_processors': [],
            'recovered': [],
            'healthy_count': 0
        }

        docs = (
            fs_client.collection(HEARTBEAT_COLLECTION)
            .where('status', '==', 'running')
            .stream()
        )

        for doc in docs:
            data = doc.to_dict()
            last_heartbeat = data.get('last_heartbeat')

            if not last_heartbeat:
                continue

            # Convert Firestore timestamp
            if hasattr(last_heartbeat, 'timestamp'):
                last_heartbeat = datetime.fromtimestamp(
                    last_heartbeat.timestamp(),
                    tz=timezone.utc
                )

            age_seconds = (now - last_heartbeat).total_seconds()

            processor_info = {
                'doc_id': doc.id,
                'processor_name': data.get('processor_name'),
                'run_id': data.get('run_id'),
                'data_date': data.get('data_date'),
                'last_heartbeat': last_heartbeat.isoformat(),
                'age_seconds': int(age_seconds),
                'progress': f"{data.get('progress', 0)}/{data.get('total', 0)}",
                'status_message': data.get('status_message', '')
            }

            if last_heartbeat < dead_threshold:
                # Dead processor - auto-recover
                results['dead_processors'].append(processor_info)

                if not dry_run:
                    recovery_result = auto_recover_processor(
                        fs_client, bq_client, doc.id, processor_info
                    )
                    if recovery_result['success']:
                        results['recovered'].append(processor_info)

            elif last_heartbeat < stale_threshold:
                # Stale processor - warn but don't recover yet
                results['stale_processors'].append(processor_info)
            else:
                # Healthy
                results['healthy_count'] += 1

        # Send alerts if needed
        if results['dead_processors'] or results['stale_processors']:
            if not dry_run:
                send_stale_alert(results)

        # Cleanup old heartbeats
        if cleanup:
            cleanup_count = cleanup_old_heartbeats(fs_client)
            results['cleanup_count'] = cleanup_count

        # Log summary
        logger.info(
            f"Stale check complete: "
            f"{results['healthy_count']} healthy, "
            f"{len(results['stale_processors'])} stale, "
            f"{len(results['dead_processors'])} dead, "
            f"{len(results['recovered'])} recovered"
        )

        return {
            'status': 'ok',
            'summary': {
                'healthy': results['healthy_count'],
                'stale': len(results['stale_processors']),
                'dead': len(results['dead_processors']),
                'recovered': len(results['recovered'])
            },
            'details': results
        }, 200

    except Exception as e:
        logger.error(f"Error in stale processor monitor: {e}", exc_info=True)
        return {'status': 'error', 'error': str(e)}, 500


def auto_recover_processor(
    fs_client: firestore.Client,
    bq_client: bigquery.Client,
    doc_id: str,
    processor_info: Dict
) -> Dict:
    """
    Auto-recover a dead processor.

    Args:
        fs_client: Firestore client
        bq_client: BigQuery client
        doc_id: Heartbeat document ID
        processor_info: Processor information

    Returns:
        Recovery result dict
    """
    processor_name = processor_info['processor_name']
    data_date = processor_info['data_date']
    run_id = processor_info['run_id']

    logger.warning(
        f"Auto-recovering dead processor: {processor_name} "
        f"(data_date={data_date}, age={processor_info['age_seconds']}s)"
    )

    result = {'success': False, 'actions': []}

    try:
        # 1. Mark heartbeat as failed
        fs_client.collection(HEARTBEAT_COLLECTION).document(doc_id).update({
            'status': 'failed',
            'failure_reason': 'auto_recovery_stale_heartbeat',
            'recovered_at': datetime.now(timezone.utc)
        })
        result['actions'].append('marked_heartbeat_failed')

        # 2. Update processor_run_history
        update_query = f"""
        UPDATE `{PROJECT_ID}.nba_reference.processor_run_history`
        SET status = 'failed',
            failure_category = 'STALE_HEARTBEAT',
            skip_reason = 'Auto-recovered: heartbeat stale for {processor_info["age_seconds"]}s'
        WHERE processor_name = @processor_name
          AND data_date = @data_date
          AND status = 'running'
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("processor_name", "STRING", processor_name),
                bigquery.ScalarQueryParameter("data_date", "DATE", data_date),
            ]
        )

        bq_client.query(update_query, job_config=job_config).result()
        result['actions'].append('updated_run_history')

        # 3. Clear processing lock
        lock_id = f"{processor_name}_{data_date}"
        try:
            fs_client.collection('processing_locks').document(lock_id).delete()
            result['actions'].append('cleared_lock')
        except Exception:
            pass  # Lock may not exist

        result['success'] = True
        logger.info(f"Recovered {processor_name}: {result['actions']}")

    except Exception as e:
        logger.error(f"Recovery failed for {processor_name}: {e}")
        result['error'] = str(e)

    return result


def send_stale_alert(results: Dict) -> bool:
    """
    Send Slack alert for stale/dead processors.

    Args:
        results: Check results dict

    Returns:
        True if alert sent
    """
    try:
        from shared.utils.slack_alerting import send_slack_alert

        dead_count = len(results['dead_processors'])
        stale_count = len(results['stale_processors'])
        recovered_count = len(results['recovered'])

        # Build message
        text = f"Stale Processor Alert: {dead_count} dead, {stale_count} stale"
        if recovered_count > 0:
            text += f" ({recovered_count} auto-recovered)"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": ":warning: Stale Processor Alert"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Dead (>15min):* {dead_count}\n"
                        f"*Stale (>5min):* {stale_count}\n"
                        f"*Auto-recovered:* {recovered_count}"
                    )
                }
            }
        ]

        # Add details for dead processors
        for proc in results['dead_processors'][:5]:  # Limit to 5
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":skull: *{proc['processor_name']}* ({proc['data_date']})\n"
                        f"Last heartbeat: {proc['age_seconds']}s ago | "
                        f"Progress: {proc['progress']}"
                    )
                }
            })

        send_slack_alert(
            channel='#nba-alerts',
            text=text,
            blocks=blocks
        )
        return True

    except Exception as e:
        logger.error(f"Failed to send stale alert: {e}")
        return False


def cleanup_old_heartbeats(fs_client: firestore.Client, max_age_days: int = 7) -> int:
    """
    Clean up old heartbeat documents.

    Args:
        fs_client: Firestore client
        max_age_days: Delete docs older than this

    Returns:
        Number of docs deleted
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    docs = (
        fs_client.collection(HEARTBEAT_COLLECTION)
        .where('updated_at', '<', cutoff)
        .limit(500)
        .stream()
    )

    batch = fs_client.batch()
    count = 0

    for doc in docs:
        batch.delete(doc.reference)
        count += 1

    if count > 0:
        batch.commit()
        logger.info(f"Cleaned up {count} old heartbeat documents")

    return count


@functions_framework.http
def health(request):
    """Health check endpoint for stale_processor_monitor."""
    return json.dumps({
        'status': 'healthy',
        'function': 'stale_processor_monitor',
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}

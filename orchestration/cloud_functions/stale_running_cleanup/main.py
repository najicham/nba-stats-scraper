"""
Layer 2 Stale Running Cleanup Cloud Function

Cleans up processor_run_history records stuck in 'running' state for >4 hours.
This is Layer 2 of the Three-Layer Defense Model:
- Layer 1: Graceful Degradation (treats stale as failed, allows processing to continue)
- Layer 2: Self-Healing (this function - cleans up stuck records)
- Layer 3: Observability (dashboards, alerts)

Schedule: Every 30 minutes (*/30 * * * *)
Table: nba_reference.processor_run_history

How it works:
1. Queries for records with status='running' and started_at > 4 hours ago
2. Updates them to status='failed' with an audit note
3. Optionally sends Slack notification if webhook is configured

Created: 2026-01-12 (Session 21)
"""

import functions_framework
from flask import jsonify
from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client
from orchestration.shared.utils.slack_retry import send_slack_webhook_with_retry
from datetime import datetime, timezone
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("GCP_PROJECT_ID") or os.environ.get("GCP_PROJECT", "nba-props-platform")
STALE_THRESHOLD_HOURS = 4  # Match Layer 1's threshold


def send_slack_notification(message: str):
    """Send notification to Slack if webhook is configured."""
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if not webhook_url:
        logger.info("Slack webhook not configured, skipping notification")
        return False

    payload = {"text": message}
    success = send_slack_webhook_with_retry(webhook_url, payload, timeout=10)

    if success:
        logger.info("Slack notification sent successfully")
    else:
        logger.error("Failed to send Slack notification after retries", exc_info=True)

    return success


def get_stale_running_details(client: bigquery.Client) -> list:
    """Get details of stale running records before cleanup."""
    query = f"""
    SELECT
        processor_name,
        COUNT(*) as stuck_count,
        MIN(started_at) as oldest_started,
        MAX(started_at) as newest_started
    FROM `{PROJECT_ID}.nba_reference.processor_run_history`
    WHERE status = 'running'
      AND started_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {STALE_THRESHOLD_HOURS} HOUR)
    GROUP BY processor_name
    ORDER BY stuck_count DESC
    """

    results = []
    for row in client.query(query).result():
        results.append({
            'processor': row.processor_name,
            'count': row.stuck_count,
            'oldest': row.oldest_started.isoformat() if row.oldest_started else None,
            'newest': row.newest_started.isoformat() if row.newest_started else None
        })
    return results


def cleanup_stale_records(client: bigquery.Client) -> int:
    """Mark stale running records as failed. Returns count of updated records.

    Note: The errors column is JSON type, so we use JSON_OBJECT to structure
    the cleanup metadata while preserving any original errors.
    """
    update_query = f"""
    UPDATE `{PROJECT_ID}.nba_reference.processor_run_history`
    SET
        status = 'failed',
        errors = JSON_OBJECT(
            'cleanup_reason', 'stale_running_cleanup',
            'message', 'marked as failed after being stuck in running state',
            'hours_stuck', TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, HOUR),
            'cleanup_timestamp', CAST(CURRENT_TIMESTAMP() AS STRING),
            'original_errors', errors
        )
    WHERE status = 'running'
      AND started_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {STALE_THRESHOLD_HOURS} HOUR)
    """

    # Execute the update
    job = client.query(update_query)
    job.result()  # Wait for completion

    return job.num_dml_affected_rows or 0


@functions_framework.http
def cleanup_stale_running(request):
    """
    Main entry point for the stale running cleanup function.

    HTTP trigger - called by Cloud Scheduler every 30 minutes.

    Returns:
        JSON response with cleanup results
    """
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "threshold_hours": STALE_THRESHOLD_HOURS,
        "status": "ok",
        "cleaned": 0,
        "details": []
    }

    try:
        client = get_bigquery_client(project_id=PROJECT_ID)

        # Get details before cleanup (for logging and Slack)
        stale_details = get_stale_running_details(client)
        total_stale = sum(d['count'] for d in stale_details)

        if total_stale == 0:
            logger.info("No stale running records found")
            result["message"] = "No stale records found"
            return jsonify(result), 200

        # Log details
        logger.warning(f"Found {total_stale} stale running records to clean up:")
        for detail in stale_details:
            logger.warning(f"  - {detail['processor']}: {detail['count']} stuck")

        # Perform cleanup
        cleaned_count = cleanup_stale_records(client)

        result["cleaned"] = cleaned_count
        result["details"] = stale_details
        result["message"] = f"Cleaned {cleaned_count} stale running records"

        logger.info(f"Successfully cleaned {cleaned_count} stale running records")

        # Send Slack notification if any records were cleaned
        if cleaned_count > 0:
            processor_summary = ", ".join(
                f"{d['processor']}({d['count']})"
                for d in stale_details[:5]  # Limit to top 5
            )
            if len(stale_details) > 5:
                processor_summary += f", +{len(stale_details) - 5} more"

            slack_message = (
                f":broom: *Stale Running Cleanup*\n"
                f"Marked {cleaned_count} stuck records as failed\n"
                f"Processors: {processor_summary}"
            )
            send_slack_notification(slack_message)

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Stale cleanup failed: {str(e)}", exc_info=True)
        result["status"] = "error"
        result["error"] = str(e)

        # Try to notify about failure
        send_slack_notification(
            f":x: *Stale Running Cleanup Failed*\nError: {str(e)[:200]}"
        )

        return jsonify(result), 500


@functions_framework.http
def health(request):
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'function': 'stale_running_cleanup',
        'threshold_hours': STALE_THRESHOLD_HOURS
    }), 200


# For local testing
if __name__ == "__main__":
    from flask import Flask, request
    app = Flask(__name__)

    @app.route("/", methods=["GET", "POST"])
    def test():
        return cleanup_stale_running(request)

    @app.route("/health", methods=["GET"])
    def test_health():
        return health(request)

    app.run(debug=True, port=8080)

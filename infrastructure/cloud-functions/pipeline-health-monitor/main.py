"""
Cloud Function for real-time pipeline health monitoring.

Checks pipeline health every 30 minutes during game hours and sends Slack
alerts when the success rate drops below 90%.
"""
import functions_framework
from google.cloud import bigquery
import requests
import os
from datetime import datetime, timezone

SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK_URL')
SUCCESS_THRESHOLD = 90.0  # Alert if success rate drops below 90%


@functions_framework.http
def check_pipeline_health(request):
    """
    Check pipeline health and alert on failures.

    Queries the last 2 hours of pipeline events for Phase 3 and Phase 4,
    calculates success rate, and sends Slack alert if below threshold.
    """
    client = bigquery.Client()

    # Query for recent pipeline events
    query = """
    SELECT
        phase,
        event_type,
        COUNT(*) as event_count
    FROM `nba-props-platform.nba_orchestration.pipeline_event_log`
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
      AND phase IN ('phase_3', 'phase_4', 'phase_5')
      AND event_type IN ('processor_start', 'processor_complete', 'processor_failed')
    GROUP BY phase, event_type
    ORDER BY phase, event_type
    """

    try:
        results = list(client.query(query).result())

        # Calculate success metrics
        phase_metrics = {}
        for row in results:
            phase = row.phase
            if phase not in phase_metrics:
                phase_metrics[phase] = {
                    'started': 0,
                    'completed': 0,
                    'failed': 0
                }

            if row.event_type == 'processor_start':
                phase_metrics[phase]['started'] = row.event_count
            elif row.event_type == 'processor_complete':
                phase_metrics[phase]['completed'] = row.event_count
            elif row.event_type == 'processor_failed':
                phase_metrics[phase]['failed'] = row.event_count

        # Check if any phase has issues
        alerts = []
        for phase, metrics in phase_metrics.items():
            total_finished = metrics['completed'] + metrics['failed']
            if total_finished > 0:
                success_rate = (metrics['completed'] / total_finished) * 100

                if success_rate < SUCCESS_THRESHOLD:
                    alerts.append({
                        'phase': phase,
                        'success_rate': success_rate,
                        'completed': metrics['completed'],
                        'failed': metrics['failed'],
                        'started': metrics['started']
                    })

        # Send Slack alert if needed
        if alerts and SLACK_WEBHOOK:
            alert_message = _build_alert_message(alerts)
            response = requests.post(
                SLACK_WEBHOOK,
                json={'text': alert_message},
                timeout=10
            )

            if response.status_code != 200:
                print(f"Failed to send Slack alert: {response.status_code}")

            return {
                'status': 'alert_sent',
                'alerts': alerts,
                'message': alert_message
            }, 500

        # No issues found
        summary = {
            phase: {
                'success_rate': (metrics['completed'] / (metrics['completed'] + metrics['failed']) * 100)
                    if (metrics['completed'] + metrics['failed']) > 0 else 100.0,
                'completed': metrics['completed'],
                'failed': metrics['failed']
            }
            for phase, metrics in phase_metrics.items()
        }

        return {
            'status': 'healthy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'summary': summary
        }, 200

    except Exception as e:
        error_msg = f"Health check failed: {str(e)}"
        print(error_msg)

        if SLACK_WEBHOOK:
            requests.post(
                SLACK_WEBHOOK,
                json={'text': f'🚨 Pipeline Health Monitor Error\n```{error_msg}```'},
                timeout=10
            )

        return {'status': 'error', 'error': str(e)}, 500


def _build_alert_message(alerts):
    """Build formatted Slack alert message."""
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    message_parts = [
        f"⚠️ *Pipeline Health Alert* - {timestamp}",
        "",
        f"Success rate dropped below {SUCCESS_THRESHOLD}% threshold:",
        ""
    ]

    for alert in alerts:
        phase_name = alert['phase'].replace('_', ' ').title()
        message_parts.extend([
            f"*{phase_name}*",
            f"• Success Rate: {alert['success_rate']:.1f}%",
            f"• Completed: {alert['completed']}",
            f"• Failed: {alert['failed']}",
            f"• Started: {alert['started']}",
            ""
        ])

    message_parts.append("Check logs: https://console.cloud.google.com/logs")

    return "\n".join(message_parts)

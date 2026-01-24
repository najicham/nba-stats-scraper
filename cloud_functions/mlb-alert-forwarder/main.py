"""
MLB Alert Forwarder - Cloud Function to forward Pub/Sub alerts to Slack

This Cloud Function subscribes to the mlb-monitoring-alerts Pub/Sub topic
and forwards alerts to Slack with proper formatting based on severity.

Trigger: Pub/Sub topic: mlb-monitoring-alerts
Runtime: Python 3.11
"""

import base64
import json
import os
import logging
from typing import Dict, Any
from datetime import datetime

import requests
import time
from google.cloud import secretmanager

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# GCP project
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')

# Secret Manager client (initialized once)
secret_client = secretmanager.SecretManagerServiceClient()


def get_slack_webhook(severity: str = 'default') -> str:
    """
    Get Slack webhook URL from Secret Manager based on alert severity.

    Args:
        severity: Alert severity (critical, warning, info)

    Returns:
        Slack webhook URL
    """
    # Map severity to secret name
    secret_mapping = {
        'critical': 'slack-webhook-monitoring-error',
        'error': 'slack-webhook-monitoring-error',
        'warning': 'slack-webhook-monitoring-warning',
        'info': 'slack-webhook-default',
        'default': 'slack-webhook-default'
    }

    secret_name = secret_mapping.get(severity.lower(), 'slack-webhook-default')
    secret_path = f"projects/{PROJECT_ID}/secrets/{secret_name}/versions/latest"

    try:
        response = secret_client.access_secret_version(request={"name": secret_path})
        webhook_url = response.payload.data.decode('UTF-8')
        return webhook_url
    except Exception as e:
        logger.error(f"Failed to get Slack webhook from Secret Manager: {e}")
        # Fallback to env var if available
        return os.environ.get('SLACK_WEBHOOK_URL', '')


def format_slack_message(alert: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format alert data into Slack message payload.

    Args:
        alert: Alert data dictionary

    Returns:
        Slack message payload
    """
    severity = alert.get('severity', 'info').lower()
    title = alert.get('title', 'MLB Alert')
    message = alert.get('message', 'No details provided')
    context = alert.get('context', {})
    timestamp = alert.get('timestamp', datetime.utcnow().isoformat())

    # Map severity to emoji and color
    severity_config = {
        'critical': {'emoji': ':rotating_light:', 'color': '#FF0000', 'label': 'CRITICAL'},
        'error': {'emoji': ':x:', 'color': '#FF0000', 'label': 'ERROR'},
        'warning': {'emoji': ':warning:', 'color': '#FFA500', 'label': 'WARNING'},
        'info': {'emoji': ':information_source:', 'color': '#0000FF', 'label': 'INFO'}
    }
    config = severity_config.get(severity, severity_config['info'])

    # Build Slack message blocks
    blocks = [
        {
            'type': 'header',
            'text': {
                'type': 'plain_text',
                'text': f"{config['emoji']} {title}",
                'emoji': True
            }
        },
        {
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': message
            }
        }
    ]

    # Add context fields if present
    if context:
        fields = []
        for key, value in list(context.items())[:10]:  # Limit to 10 fields
            # Format key nicely (replace underscores, capitalize)
            formatted_key = key.replace('_', ' ').title()
            fields.append({
                'type': 'mrkdwn',
                'text': f"*{formatted_key}:*\n{value}"
            })

        if fields:
            blocks.append({
                'type': 'section',
                'fields': fields
            })

    # Add footer with timestamp
    blocks.append({
        'type': 'context',
        'elements': [
            {
                'type': 'mrkdwn',
                'text': f"*Severity:* {config['label']} | *Time:* {timestamp}"
            }
        ]
    })

    # Build full payload
    payload = {
        'attachments': [{
            'color': config['color'],
            'blocks': blocks
        }]
    }

    return payload


def mlb_alert_forwarder(event: Dict[str, Any], context: Any) -> None:
    """
    Cloud Function entry point triggered by Pub/Sub.

    Args:
        event: Pub/Sub event data containing alert information
        context: Cloud Function context
    """
    try:
        # Decode Pub/Sub message
        if 'data' not in event:
            logger.error("No data in Pub/Sub event")
            return

        pubsub_message = base64.b64decode(event['data']).decode('utf-8')
        logger.info(f"Received Pub/Sub message: {pubsub_message[:200]}")

        # Parse alert data
        try:
            alert = json.loads(pubsub_message)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse alert JSON: {e}")
            return

        # Validate required fields
        if 'severity' not in alert or 'title' not in alert:
            logger.error(f"Alert missing required fields: {alert}")
            return

        # Get appropriate Slack webhook
        severity = alert.get('severity', 'info')
        webhook_url = get_slack_webhook(severity)

        if not webhook_url:
            logger.error(f"No Slack webhook URL configured for severity: {severity}")
            return

        # Format message for Slack
        slack_payload = format_slack_message(alert)

        # Send to Slack with retry logic for transient failures
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                response = requests.post(
                    webhook_url,
                    json=slack_payload,
                    timeout=10
                )

                if response.status_code == 200:
                    logger.info(
                        f"Successfully sent alert to Slack: {alert.get('title')} "
                        f"(severity: {severity})"
                    )
                    break
                elif response.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    logger.warning(f"Slack returned {response.status_code}, retrying...")
                    time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s
                    continue
                else:
                    logger.error(
                        f"Failed to send alert to Slack: {response.status_code} - "
                        f"{response.text[:200]}"
                    )
                    break
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    logger.warning(f"Request failed, retrying: {e}")
                    time.sleep(2 ** attempt)
                    continue
                logger.error(f"Failed to send alert after retries: {e}")

    except (requests.exceptions.RequestException, ValueError, KeyError) as e:
        logger.error(f"Error processing alert: {e}", exc_info=True)


# For testing locally
if __name__ == '__main__':
    # Test event
    test_alert = {
        'severity': 'warning',
        'title': 'MLB Gap Detection Alert',
        'message': 'Found 3 data gaps in yesterdays pipeline run',
        'context': {
            'date': '2025-08-15',
            'gaps_found': 3,
            'missing_games': ['NYY vs BOS', 'LAD vs SF', 'CHC vs STL'],
            'pipeline_stage': 'analytics'
        },
        'timestamp': datetime.utcnow().isoformat()
    }

    test_event = {
        'data': base64.b64encode(json.dumps(test_alert).encode('utf-8'))
    }

    print("Testing MLB alert forwarder...")
    mlb_alert_forwarder(test_event, None)

"""
Deployment Drift Monitor Cloud Function

Runs every 2 hours to check for deployment drift and alert via Slack.

Alerts when services have stale code (commits since deployment).
"""

import subprocess
import json
import os
from datetime import datetime
from google.cloud import secretmanager
import requests
import functions_framework


def get_secret(secret_id: str) -> str:
    """Retrieve secret from GCP Secret Manager"""
    client = secretmanager.SecretManagerServiceClient()
    project_id = os.environ.get('GCP_PROJECT', 'nba-props-platform')
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode('UTF-8')


def check_deployment_drift():
    """Run deployment drift check and parse results"""
    try:
        # Run the existing drift check script
        result = subprocess.run(
            ['./bin/check-deployment-drift.sh', '--verbose'],
            capture_output=True,
            text=True,
            timeout=60
        )

        # Parse output for service status
        services_with_drift = []
        lines = result.stdout.split('\n')

        for line in lines:
            if 'STALE DEPLOYMENT' in line or 'commits behind' in line:
                # Extract service name and drift info
                # Example: "❌ nba-phase3-analytics-processors: STALE DEPLOYMENT"
                if ':' in line:
                    service = line.split(':')[0].replace('❌', '').replace('⚠️', '').strip()
                    services_with_drift.append(service)

        return {
            'has_drift': len(services_with_drift) > 0,
            'services': services_with_drift,
            'total_services': len(services_with_drift),
            'raw_output': result.stdout,
            'timestamp': datetime.utcnow().isoformat()
        }

    except subprocess.TimeoutExpired:
        return {
            'has_drift': True,
            'error': 'Drift check timed out',
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            'has_drift': True,
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


def determine_severity(drift_info):
    """Determine alert severity based on drift info"""
    if not drift_info.get('has_drift'):
        return 'OK'

    num_services = drift_info.get('total_services', 0)

    # Severity based on number of services with drift
    if num_services >= 3:
        return 'CRITICAL'
    elif num_services >= 2:
        return 'WARNING'
    else:
        return 'INFO'


def send_slack_alert(drift_info, severity):
    """Send Slack alert for deployment drift"""
    try:
        # Get appropriate webhook based on severity
        if severity == 'CRITICAL':
            webhook_url = get_secret('SLACK_WEBHOOK_URL_ERROR')
            emoji = '🔴'
        elif severity == 'WARNING':
            webhook_url = get_secret('SLACK_WEBHOOK_URL_WARNING')
            emoji = '⚠️'
        else:
            webhook_url = get_secret('SLACK_WEBHOOK_URL')
            emoji = 'ℹ️'

        services_list = '\n'.join([f"   • {svc}" for svc in drift_info.get('services', [])])

        message = {
            "text": f"{emoji} Deployment Drift Detected",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{emoji} {severity}: Deployment Drift Detected"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Services with stale code:*\n{services_list}\n\n*Action:* Deploy these services to production"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"```./bin/deploy-service.sh <service-name>```\n\n_Checked at {drift_info.get('timestamp')}_"
                    }
                }
            ]
        }

        response = requests.post(webhook_url, json=message, timeout=10)
        response.raise_for_status()

        return {'success': True, 'status_code': response.status_code}

    except Exception as e:
        print(f"Error sending Slack alert: {e}")
        return {'success': False, 'error': str(e)}


@functions_framework.http
def deployment_drift_monitor(request):
    """
    HTTP Cloud Function entry point.
    Checks deployment drift and sends alerts if needed.
    """
    print("Starting deployment drift check...")

    # Check deployment drift
    drift_info = check_deployment_drift()
    print(f"Drift check result: {json.dumps(drift_info, indent=2)}")

    # Determine severity
    severity = determine_severity(drift_info)
    print(f"Severity: {severity}")

    # Send alert if drift detected
    if drift_info.get('has_drift'):
        alert_result = send_slack_alert(drift_info, severity)
        print(f"Alert sent: {alert_result}")

        return {
            'status': 'drift_detected',
            'severity': severity,
            'services': drift_info.get('services', []),
            'alert_sent': alert_result.get('success', False)
        }, 200
    else:
        print("No drift detected - all services up to date")
        return {
            'status': 'healthy',
            'message': 'All services up to date'
        }, 200


@functions_framework.cloud_event
def deployment_drift_monitor_scheduled(cloud_event):
    """
    Cloud Scheduler entry point.
    Triggered by Cloud Scheduler every 2 hours.
    """
    print(f"Scheduled drift check triggered at {datetime.utcnow().isoformat()}")

    # Same logic as HTTP function
    drift_info = check_deployment_drift()
    severity = determine_severity(drift_info)

    if drift_info.get('has_drift'):
        send_slack_alert(drift_info, severity)
        print(f"Alert sent for {len(drift_info.get('services', []))} services")
    else:
        print("No drift detected")

    return {'status': 'completed'}

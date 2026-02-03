#!/usr/bin/env python3
"""
Morning Deployment Check - Automated stale service detection with Slack alerts.

This script:
1. Checks all critical services for deployment drift
2. Sends Slack alerts if any services are stale
3. Can be run as a Cloud Scheduler job (6 AM ET daily)

Usage:
    python bin/monitoring/morning_deployment_check.py              # Check and alert
    python bin/monitoring/morning_deployment_check.py --dry-run    # Check without alerting
    python bin/monitoring/morning_deployment_check.py --slack-test # Test Slack webhook

Environment Variables:
    SLACK_WEBHOOK_URL_WARNING - Webhook for #nba-alerts channel
    GCP_PROJECT_ID - GCP project (default: nba-props-platform)
"""

import os
import subprocess
import json
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import argparse


# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
REGION = 'us-west2'

# Critical services that must be checked
CRITICAL_SERVICES = {
    'prediction-worker': {
        'source_dirs': ['predictions/worker', 'shared'],
        'priority': 'P0',
        'description': 'Generates predictions'
    },
    'prediction-coordinator': {
        'source_dirs': ['predictions/coordinator', 'shared'],
        'priority': 'P0',
        'description': 'Orchestrates prediction batches'
    },
    'nba-phase3-analytics-processors': {
        'source_dirs': ['data_processors/analytics', 'shared'],
        'priority': 'P1',
        'description': 'Game analytics processing'
    },
    'nba-phase4-precompute-processors': {
        'source_dirs': ['data_processors/precompute', 'shared'],
        'priority': 'P1',
        'description': 'ML feature generation'
    },
    'nba-phase1-scrapers': {
        'source_dirs': ['scrapers'],
        'priority': 'P1',
        'description': 'Data collection'
    },
}


def get_deployment_timestamp(service: str) -> Optional[datetime]:
    """Get the deployment timestamp for a Cloud Run service."""
    try:
        result = subprocess.run(
            [
                'gcloud', 'run', 'revisions', 'list',
                f'--service={service}',
                f'--region={REGION}',
                f'--project={PROJECT_ID}',
                '--limit=1',
                '--format=value(metadata.creationTimestamp)'
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            timestamp_str = result.stdout.strip()
            # Parse ISO format timestamp
            return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
    except Exception as e:
        print(f"  Error getting deployment time for {service}: {e}")
    return None


def get_latest_code_change(source_dirs: List[str]) -> Optional[datetime]:
    """Get the timestamp of the latest code change in the source directories."""
    latest_timestamp = None

    for dir_path in source_dirs:
        if not os.path.isdir(dir_path):
            continue
        try:
            result = subprocess.run(
                ['git', 'log', '-1', '--format=%aI', '--', dir_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                timestamp = datetime.fromisoformat(result.stdout.strip())
                if latest_timestamp is None or timestamp > latest_timestamp:
                    latest_timestamp = timestamp
        except Exception as e:
            print(f"  Error getting code change time for {dir_path}: {e}")

    return latest_timestamp


def check_service_drift(service: str, config: Dict) -> Dict:
    """Check if a service has deployment drift."""
    result = {
        'service': service,
        'priority': config['priority'],
        'description': config['description'],
        'is_stale': False,
        'drift_minutes': 0,
        'deployed_at': None,
        'code_changed_at': None,
        'error': None
    }

    deployed_at = get_deployment_timestamp(service)
    if not deployed_at:
        result['error'] = 'Could not get deployment timestamp'
        return result

    code_changed_at = get_latest_code_change(config['source_dirs'])
    if not code_changed_at:
        result['error'] = 'Could not get code change timestamp'
        return result

    result['deployed_at'] = deployed_at
    result['code_changed_at'] = code_changed_at

    # Check if code changed after deployment
    if code_changed_at > deployed_at:
        result['is_stale'] = True
        drift_delta = code_changed_at - deployed_at
        result['drift_minutes'] = int(drift_delta.total_seconds() / 60)

    return result


def check_all_services() -> Tuple[List[Dict], List[Dict]]:
    """Check all critical services for drift."""
    stale_services = []
    healthy_services = []

    print("=== Morning Deployment Check ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"Project: {PROJECT_ID}")
    print("")

    for service, config in CRITICAL_SERVICES.items():
        print(f"Checking {service}...")
        result = check_service_drift(service, config)

        if result['error']:
            print(f"  ⚠️  Error: {result['error']}")
        elif result['is_stale']:
            print(f"  ❌ STALE: Code changed {result['drift_minutes']} minutes after deployment")
            stale_services.append(result)
        else:
            print(f"  ✅ Up to date")
            healthy_services.append(result)

    return stale_services, healthy_services


def format_slack_message(stale_services: List[Dict]) -> Dict:
    """Format a Slack message for stale services alert."""
    if not stale_services:
        return {
            "text": "✅ Morning Deployment Check: All services up to date",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "✅ *Morning Deployment Check*\n\nAll critical services are running the latest code."
                    }
                }
            ]
        }

    # Build the alert message
    p0_services = [s for s in stale_services if s['priority'] == 'P0']
    p1_services = [s for s in stale_services if s['priority'] == 'P1']

    severity = "🚨 *CRITICAL*" if p0_services else "⚠️ *WARNING*"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{severity} Morning Deployment Check\n\n*{len(stale_services)} service(s) running stale code*"
            }
        },
        {"type": "divider"}
    ]

    for service in stale_services:
        drift_hours = service['drift_minutes'] // 60
        drift_mins = service['drift_minutes'] % 60
        drift_str = f"{drift_hours}h {drift_mins}m" if drift_hours > 0 else f"{drift_mins}m"

        deployed_str = service['deployed_at'].strftime('%Y-%m-%d %H:%M UTC') if service['deployed_at'] else 'Unknown'
        code_str = service['code_changed_at'].strftime('%Y-%m-%d %H:%M UTC') if service['code_changed_at'] else 'Unknown'

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{service['service']}* ({service['priority']})\n" +
                       f"_{service['description']}_\n" +
                       f"• Deployed: {deployed_str}\n" +
                       f"• Code changed: {code_str}\n" +
                       f"• Drift: *{drift_str}*"
            }
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "*Action Required:*\n```./bin/deploy-service.sh <service-name>```"
        }
    })

    return {
        "text": f"⚠️ Morning Deployment Check: {len(stale_services)} stale service(s)",
        "blocks": blocks
    }


def send_slack_alert(message: Dict, dry_run: bool = False) -> bool:
    """Send alert to Slack."""
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL_WARNING')

    if not webhook_url:
        print("WARNING: SLACK_WEBHOOK_URL_WARNING not set - skipping Slack alert")
        print("Message would have been:")
        print(json.dumps(message, indent=2))
        return False

    if dry_run:
        print("DRY RUN - Would send to Slack:")
        print(json.dumps(message, indent=2))
        return True

    try:
        response = requests.post(
            webhook_url,
            json=message,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        if response.status_code == 200:
            print("✅ Slack alert sent successfully")
            return True
        else:
            print(f"❌ Slack alert failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error sending Slack alert: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Morning deployment drift check')
    parser.add_argument('--dry-run', action='store_true', help='Check without sending alerts')
    parser.add_argument('--slack-test', action='store_true', help='Send test message to Slack')
    parser.add_argument('--always-alert', action='store_true', help='Send Slack even if no issues')
    args = parser.parse_args()

    # Test mode
    if args.slack_test:
        test_message = {
            "text": "🧪 Test: Morning Deployment Check",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "🧪 *Test Alert*\n\nThis is a test of the morning deployment check system."
                    }
                }
            ]
        }
        send_slack_alert(test_message, dry_run=args.dry_run)
        return

    # Run the check
    stale_services, healthy_services = check_all_services()

    print("")
    print("=== Summary ===")
    print(f"Total checked: {len(stale_services) + len(healthy_services)}")
    print(f"Stale: {len(stale_services)}")
    print(f"Healthy: {len(healthy_services)}")

    # Send alert if there are stale services or if always-alert is set
    if stale_services or args.always_alert:
        message = format_slack_message(stale_services)
        send_slack_alert(message, dry_run=args.dry_run)
    else:
        print("\n✅ All services up to date - no alert needed")

    # Exit with error code if stale services found (for CI/CD)
    if stale_services:
        exit(1)


if __name__ == '__main__':
    main()

"""GCS Freshness Monitor Cloud Function.

Checks freshness of exported JSON files in the GCS API bucket. Alerts to
Slack when files are stale (>max_age_hours) or missing.

Triggered by Cloud Scheduler every 6 hours (6 AM, 12 PM, 6 PM, 12 AM ET).
Always returns 200 (reporter pattern).

Created: 2026-03-04 (Session 405)
"""

import functions_framework
import json
import logging
import os
import requests
from datetime import datetime, timezone
from flask import Request
from google.cloud import storage
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL_ALERTS')
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
GCS_API_BUCKET = 'nba-props-platform-api'

# Same as daily_health_check — single source of truth for monitored exports
MONITORED_EXPORTS = {
    'v1/tonight/all-players.json': {'max_age_hours': 12, 'severity': 'critical'},
    'v1/status.json': {'max_age_hours': 24, 'severity': 'fail'},
    'v1/systems/signal-health.json': {'max_age_hours': 24, 'severity': 'fail'},
    'v1/systems/model-health.json': {'max_age_hours': 24, 'severity': 'fail'},
    'v1/best-bets/all.json': {'max_age_hours': 24, 'severity': 'fail'},
    'v1/best-bets/today.json': {'max_age_hours': 24, 'severity': 'fail'},
    'v1/best-bets/latest.json': {'max_age_hours': 24, 'severity': 'fail'},
    'v1/best-bets/record.json': {'max_age_hours': 36, 'severity': 'warn'},
    'v1/best-bets/history.json': {'max_age_hours': 36, 'severity': 'warn'},
    'v1/signal-best-bets/latest.json': {'max_age_hours': 24, 'severity': 'critical'},
}


def check_freshness() -> Dict:
    """Check freshness of all monitored GCS exports.

    Returns dict with overall status, individual results, and issues.
    """
    client = storage.Client(project=PROJECT_ID)
    bucket = client.bucket(GCS_API_BUCKET)
    now = datetime.now(timezone.utc)

    results = []
    critical_issues = []
    fail_issues = []
    warn_issues = []

    for path, config in MONITORED_EXPORTS.items():
        max_hours = config['max_age_hours']
        severity = config['severity']

        blob = bucket.blob(path)
        if not blob.exists():
            result = {
                'path': path,
                'status': 'MISSING',
                'severity': severity,
                'message': f'File not found in gs://{GCS_API_BUCKET}/{path}',
            }
            results.append(result)
            if severity == 'critical':
                critical_issues.append(result)
            elif severity == 'fail':
                fail_issues.append(result)
            else:
                warn_issues.append(result)
            continue

        blob.reload()
        updated = blob.updated
        age_hours = (now - updated).total_seconds() / 3600

        if age_hours > max_hours:
            result = {
                'path': path,
                'status': 'STALE',
                'severity': severity,
                'age_hours': round(age_hours, 1),
                'max_age_hours': max_hours,
                'last_updated': updated.isoformat(),
                'message': f'Stale: {age_hours:.1f}h old (threshold: {max_hours}h)',
            }
            results.append(result)
            if severity == 'critical':
                critical_issues.append(result)
            elif severity == 'fail':
                fail_issues.append(result)
            else:
                warn_issues.append(result)
        else:
            results.append({
                'path': path,
                'status': 'FRESH',
                'severity': 'pass',
                'age_hours': round(age_hours, 1),
                'max_age_hours': max_hours,
                'last_updated': updated.isoformat(),
            })

    fresh_count = sum(1 for r in results if r['status'] == 'FRESH')

    if critical_issues:
        overall = 'CRITICAL'
    elif fail_issues:
        overall = 'FAIL'
    elif warn_issues:
        overall = 'WARNING'
    else:
        overall = 'PASS'

    return {
        'overall': overall,
        'fresh_count': fresh_count,
        'total_count': len(MONITORED_EXPORTS),
        'results': results,
        'critical_issues': critical_issues,
        'fail_issues': fail_issues,
        'warn_issues': warn_issues,
    }


def build_slack_payload(freshness: Dict) -> Optional[Dict]:
    """Build Slack alert payload for freshness issues. Returns None if all fresh."""
    overall = freshness['overall']
    if overall == 'PASS':
        return None

    emoji_map = {'CRITICAL': '🚨', 'FAIL': '❌', 'WARNING': '⚠️'}
    color_map = {'CRITICAL': '#8B0000', 'FAIL': '#FF4500', 'WARNING': '#FF8C00'}

    emoji = emoji_map.get(overall, '⚠️')
    color = color_map.get(overall, '#FF8C00')

    # Build issue lines
    all_issues = (freshness['critical_issues'] + freshness['fail_issues']
                  + freshness['warn_issues'])
    issue_lines = []
    for issue in all_issues:
        sev = issue['severity'].upper()
        path = issue['path']
        msg = issue['message']
        issue_lines.append(f"• [{sev}] `{path}` — {msg}")

    blocks = [
        {
            'type': 'header',
            'text': {
                'type': 'plain_text',
                'text': f'{emoji} GCS EXPORT FRESHNESS — {overall}',
                'emoji': True,
            }
        },
        {
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': (
                    f"*{freshness['fresh_count']}/{freshness['total_count']}* "
                    f"exports fresh | *{len(all_issues)} issues:*\n\n"
                    + '\n'.join(issue_lines[:10])  # Cap at 10 lines
                ),
            }
        },
        {
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': (
                    '*Action:* Check Phase 6 export pipeline. '
                    'Manual trigger: `gcloud scheduler jobs run phase6-export`'
                ),
            }
        },
        {
            'type': 'context',
            'elements': [{
                'type': 'mrkdwn',
                'text': (
                    f"Bucket: gs://{GCS_API_BUCKET} | "
                    f"Run: {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
                ),
            }]
        },
    ]

    return {
        'attachments': [{
            'color': color,
            'blocks': blocks,
        }]
    }


def send_slack_alert(payload: Dict) -> bool:
    """Send Slack alert. Returns True on success."""
    if not SLACK_WEBHOOK_URL:
        logger.warning("No SLACK_WEBHOOK_URL_ALERTS set — skipping alert")
        return False

    try:
        resp = requests.post(
            SLACK_WEBHOOK_URL,
            json=payload,
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


@functions_framework.http
def gcs_freshness_monitor(request: Request):
    """HTTP entry point for GCS freshness monitoring.

    Triggered by Cloud Scheduler every 6 hours.
    Always returns 200 (reporter pattern).
    """
    logger.info("Starting GCS freshness check...")

    try:
        freshness = check_freshness()
        overall = freshness['overall']

        logger.info(
            f"Freshness check: {overall} — "
            f"{freshness['fresh_count']}/{freshness['total_count']} fresh"
        )

        alert_sent = False
        if overall != 'PASS':
            payload = build_slack_payload(freshness)
            if payload:
                alert_sent = send_slack_alert(payload)
                logger.info(f"Alert sent: {alert_sent}")

        return json.dumps({
            'status': overall,
            'fresh_count': freshness['fresh_count'],
            'total_count': freshness['total_count'],
            'issues': len(freshness['critical_issues']) + len(freshness['fail_issues']),
            'alert_sent': alert_sent,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }), 200, {'Content-Type': 'application/json'}

    except Exception as e:
        logger.error(f"Error in GCS freshness check: {e}", exc_info=True)
        return json.dumps({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }), 200, {'Content-Type': 'application/json'}


# Gen2 CRITICAL: Main alias
main = gcs_freshness_monitor


if __name__ == '__main__':
    """Local testing: python orchestration/cloud_functions/gcs_freshness_monitor/main.py"""
    freshness = check_freshness()
    print(f"\nOverall: {freshness['overall']}")
    print(f"Fresh: {freshness['fresh_count']}/{freshness['total_count']}")

    for r in freshness['results']:
        status = r['status']
        path = r['path']
        age = r.get('age_hours', 'N/A')
        print(f"  [{status:>8}] {path} — age: {age}h")

    if freshness['overall'] != 'PASS':
        payload = build_slack_payload(freshness)
        print(f"\nSlack payload would be sent: {json.dumps(payload, indent=2)[:500]}...")

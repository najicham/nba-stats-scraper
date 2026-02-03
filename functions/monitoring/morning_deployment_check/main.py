"""
Morning Deployment Check - Cloud Function

Checks if Cloud Run services are running stale code by comparing:
1. commit-sha label on deployed service
2. Latest commit affecting service source dirs (from GitHub API)

Triggered via Cloud Scheduler at 6 AM ET daily.
"""

import os
import json
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import functions_framework

from google.cloud import run_v2


# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
REGION = 'us-west2'
GITHUB_REPO = 'najicham/nba-stats-scraper'  # owner/repo

# Critical services to check
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


def get_deployed_commit(service_name: str) -> Optional[Dict]:
    """Get the deployed commit SHA and timestamp from Cloud Run service labels."""
    try:
        client = run_v2.ServicesClient()
        name = f"projects/{PROJECT_ID}/locations/{REGION}/services/{service_name}"

        service = client.get_service(name=name)
        labels = dict(service.labels) if service.labels else {}

        return {
            'commit_sha': labels.get('commit-sha'),
            'deployed_at': labels.get('deployed-at'),
        }
    except Exception as e:
        print(f"Error getting service {service_name}: {e}")
        return None


def get_latest_commit_for_paths(paths: List[str], after_sha: Optional[str] = None) -> Optional[Dict]:
    """
    Get the latest commit that modified any of the given paths.
    Uses GitHub API (no auth needed for public repos, rate limited to 60/hour).
    """
    github_token = os.environ.get('GITHUB_TOKEN')
    headers = {}
    if github_token:
        headers['Authorization'] = f'token {github_token}'

    try:
        # Get commits for each path and find the most recent
        latest_commit = None
        latest_date = None

        for path in paths:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/commits"
            params = {'path': path, 'per_page': 1}

            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code != 200:
                print(f"GitHub API error for {path}: {response.status_code}")
                continue

            commits = response.json()
            if not commits:
                continue

            commit = commits[0]
            commit_date = datetime.fromisoformat(
                commit['commit']['author']['date'].replace('Z', '+00:00')
            )

            if latest_date is None or commit_date > latest_date:
                latest_date = commit_date
                latest_commit = {
                    'sha': commit['sha'][:8],
                    'full_sha': commit['sha'],
                    'date': commit_date,
                    'message': commit['commit']['message'].split('\n')[0],
                    'path': path
                }

        return latest_commit
    except Exception as e:
        print(f"Error fetching GitHub commits: {e}")
        return None


def is_commit_ancestor(ancestor_sha: str, descendant_sha: str) -> bool:
    """Check if ancestor_sha is an ancestor of descendant_sha using GitHub API."""
    github_token = os.environ.get('GITHUB_TOKEN')
    headers = {}
    if github_token:
        headers['Authorization'] = f'token {github_token}'

    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/compare/{ancestor_sha}...{descendant_sha}"
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            # If ancestor is behind or identical, it means deployed is ancestor of (or same as) latest
            return data.get('status') in ['behind', 'identical']
        return False
    except Exception as e:
        print(f"Error comparing commits: {e}")
        return False


def check_service_drift(service_name: str, config: Dict) -> Dict:
    """Check if a service has deployment drift."""
    result = {
        'service': service_name,
        'priority': config['priority'],
        'description': config['description'],
        'is_stale': False,
        'deployed_sha': None,
        'latest_sha': None,
        'latest_commit_msg': None,
        'error': None
    }

    # Get deployed commit info
    deployed = get_deployed_commit(service_name)
    if not deployed or not deployed.get('commit_sha'):
        result['error'] = 'Could not get deployed commit SHA'
        return result

    result['deployed_sha'] = deployed['commit_sha']
    result['deployed_at'] = deployed.get('deployed_at')

    # Get latest commit for service paths
    latest = get_latest_commit_for_paths(config['source_dirs'])
    if not latest:
        result['error'] = 'Could not get latest commit from GitHub'
        return result

    result['latest_sha'] = latest['sha']
    result['latest_commit_msg'] = latest['message']
    result['latest_commit_date'] = latest['date'].isoformat()
    result['changed_path'] = latest['path']

    # Check if deployed commit is an ancestor of latest
    # If they're different and deployed is not ancestor, we have drift
    if deployed['commit_sha'] != latest['sha']:
        # Full SHA comparison (deployed has short, latest has full)
        if not latest['full_sha'].startswith(deployed['commit_sha']):
            # Check if deployed is an ancestor of latest
            if not is_commit_ancestor(deployed['commit_sha'], latest['full_sha']):
                result['is_stale'] = True

    return result


def check_all_services() -> Tuple[List[Dict], List[Dict]]:
    """Check all critical services for drift."""
    stale_services = []
    healthy_services = []

    print(f"=== Morning Deployment Check ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"Project: {PROJECT_ID}")
    print()

    for service, config in CRITICAL_SERVICES.items():
        print(f"Checking {service}...")
        result = check_service_drift(service, config)

        if result['error']:
            print(f"  ⚠️  Error: {result['error']}")
        elif result['is_stale']:
            print(f"  ❌ STALE: deployed={result['deployed_sha']}, latest={result['latest_sha']}")
            stale_services.append(result)
        else:
            print(f"  ✅ Up to date ({result['deployed_sha']})")
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

    p0_services = [s for s in stale_services if s['priority'] == 'P0']
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
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{service['service']}* ({service['priority']})\n"
                    f"_{service['description']}_\n"
                    f"• Deployed: `{service['deployed_sha']}`\n"
                    f"• Latest: `{service['latest_sha']}` - {service.get('latest_commit_msg', 'N/A')}\n"
                    f"• Changed: `{service.get('changed_path', 'N/A')}`"
                )
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


def send_slack_alert(message: Dict) -> bool:
    """Send alert to Slack."""
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL_WARNING')

    if not webhook_url:
        print("WARNING: SLACK_WEBHOOK_URL_WARNING not set - skipping Slack alert")
        print(f"Message: {json.dumps(message, indent=2)}")
        return False

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


@functions_framework.http
def run_check(request):
    """HTTP Cloud Function entrypoint."""
    # Parse request params
    always_alert = False
    if request.args.get('always_alert') == 'true':
        always_alert = True

    # Run the check
    stale_services, healthy_services = check_all_services()

    print()
    print("=== Summary ===")
    print(f"Total checked: {len(stale_services) + len(healthy_services)}")
    print(f"Stale: {len(stale_services)}")
    print(f"Healthy: {len(healthy_services)}")

    # Send alert if stale services or always_alert
    if stale_services or always_alert:
        message = format_slack_message(stale_services)
        send_slack_alert(message)
    else:
        print("\n✅ All services up to date - no alert needed")

    # Return response
    response_data = {
        'status': 'stale' if stale_services else 'healthy',
        'stale_count': len(stale_services),
        'healthy_count': len(healthy_services),
        'stale_services': [s['service'] for s in stale_services],
        'timestamp': datetime.now(timezone.utc).isoformat()
    }

    return json.dumps(response_data), 200 if not stale_services else 500

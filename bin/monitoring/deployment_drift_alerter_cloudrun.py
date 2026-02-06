#!/usr/bin/env python3
"""
Deployment Drift Alerter for Cloud Run (Session 136)

Simplified version that uses GitHub API instead of local git.
Checks if deployed Cloud Run services are behind the main branch.

Usage:
    python bin/monitoring/deployment_drift_alerter_cloudrun.py

Sends alerts to #deployment-alerts when services have stale deployments.
"""

import logging
import os
import subprocess
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Add shared to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from shared.utils.slack_alerts import send_slack_alert
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"
REGION = "us-west2"
GITHUB_REPO = "najiabdel/nba-stats-scraper"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"

# Map services to monitor
SERVICES_TO_MONITOR = [
    "prediction-worker",
    "prediction-coordinator",
    "nba-phase1-scrapers",
    "nba-phase2-raw-processors",
    "nba-phase3-analytics-processors",
    "nba-phase4-precompute-processors",
    "nba-grading-service",
    "phase3-to-phase4-orchestrator",
    "phase4-to-phase5-orchestrator",
    "nba-admin-dashboard",
]


def get_latest_github_commit() -> Tuple[Optional[str], Optional[int]]:
    """
    Get the latest commit SHA and timestamp from GitHub main branch.

    Returns:
        Tuple of (commit_sha, timestamp) or (None, None)
    """
    try:
        url = f"{GITHUB_API}/commits/main"
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            logger.error(f"GitHub API returned {response.status_code}")
            return None, None

        data = response.json()
        commit_sha = data['sha']
        commit_date = data['commit']['committer']['date']

        # Parse timestamp
        dt = datetime.fromisoformat(commit_date.replace('Z', '+00:00'))
        timestamp = int(dt.timestamp())

        logger.info(f"Latest GitHub commit: {commit_sha[:7]} at {commit_date}")
        return commit_sha, timestamp

    except Exception as e:
        logger.error(f"Failed to get GitHub commit: {e}")
        return None, None


def get_deployment_timestamp(service: str) -> Optional[int]:
    """
    Get the deployment timestamp for a service.

    Args:
        service: Cloud Run service name

    Returns:
        Unix timestamp of deployment, or None if not found
    """
    try:
        result = subprocess.run(
            [
                "gcloud", "run", "revisions", "list",
                f"--service={service}",
                f"--region={REGION}",
                f"--project={PROJECT_ID}",
                "--limit=1",
                "--format=value(metadata.creationTimestamp)"
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0 or not result.stdout.strip():
            logger.warning(f"Service {service} not found or no revisions")
            return None

        timestamp_str = result.stdout.strip()

        # Convert to epoch
        result = subprocess.run(
            ["date", "-d", timestamp_str, "+%s"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            return int(result.stdout.strip())
        else:
            logger.error(f"Failed to parse timestamp for {service}: {timestamp_str}")
            return None

    except Exception as e:
        logger.error(f"Error getting deployment timestamp for {service}: {e}")
        return None


def check_deployment_drift() -> List[Dict]:
    """
    Check all services for deployment drift.

    Returns:
        List of drifted services with metadata
    """
    # Get latest GitHub commit
    github_sha, github_timestamp = get_latest_github_commit()

    if not github_timestamp:
        logger.error("Could not get GitHub commit info - skipping drift check")
        return []

    drifted_services = []

    for service in SERVICES_TO_MONITOR:
        deploy_timestamp = get_deployment_timestamp(service)

        if not deploy_timestamp:
            continue

        # Check if deployment is older than latest commit
        age_hours = (github_timestamp - deploy_timestamp) / 3600

        if age_hours > 2:  # More than 2 hours old
            drifted_services.append({
                'service': service,
                'deploy_timestamp': deploy_timestamp,
                'github_timestamp': github_timestamp,
                'drift_hours': age_hours
            })
            logger.warning(f"Service {service} is {age_hours:.1f} hours behind")

    return drifted_services


def send_drift_alert(drifted_services: List[Dict]):
    """Send Slack alert for drifted services."""
    if not drifted_services:
        logger.info("No deployment drift detected")
        return

    # Build alert message
    message_lines = [
        f"🚨 *Deployment Drift Detected* ({len(drifted_services)} services)",
        "",
        "The following services have stale deployments:",
        ""
    ]

    for service in drifted_services:
        hours = service['drift_hours']
        message_lines.append(
            f"• `{service['service']}` - {hours:.1f}h behind main branch"
        )

    message_lines.extend([
        "",
        "*To deploy:*",
        "```",
        "./bin/deploy-service.sh <service-name>",
        "```",
        "",
        f"_Automated check at {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}_"
    ])

    message = "\n".join(message_lines)

    # Send to #deployment-alerts
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL_DEPLOYMENT_ALERTS')

    if not webhook_url:
        logger.error("SLACK_WEBHOOK_URL_DEPLOYMENT_ALERTS not set")
        return

    try:
        send_slack_alert(message, webhook_url=webhook_url)
        logger.info(f"Sent drift alert for {len(drifted_services)} services")
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")


def main():
    """Main entry point."""
    logger.info("Starting deployment drift check")

    drifted_services = check_deployment_drift()

    if drifted_services:
        send_drift_alert(drifted_services)
        sys.exit(1)  # Exit with error if drift found
    else:
        logger.info("All services up to date")
        sys.exit(0)


if __name__ == "__main__":
    main()

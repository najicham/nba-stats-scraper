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
    "nba-scrapers",
    "nba-phase2-raw-processors",
    "nba-phase3-analytics-processors",
    "nba-phase4-precompute-processors",
    "nba-grading-service",
    "phase3-to-phase4-orchestrator",
    "phase4-to-phase5-orchestrator",
    "nba-admin-dashboard",
]

# Expected minScale annotation per service. Drift here is a config regression,
# not a code regression — caught Apr 27 when a Cloud Build trigger substitution
# silently re-set prediction-worker to min=1, costing ~$10/day.
# Orchestrators stay at min=1 to prevent cold-start gaps (Feb 23 incident).
EXPECTED_MIN_INSTANCES = {
    "prediction-worker": 0,
    "prediction-coordinator": 1,
    "nba-scrapers": 0,
    "nba-phase2-raw-processors": 0,
    "nba-phase3-analytics-processors": 0,
    "nba-phase4-precompute-processors": 0,
    "nba-grading-service": 0,
    "phase3-to-phase4-orchestrator": 1,
    "phase4-to-phase5-orchestrator": 1,
    "nba-admin-dashboard": 0,
}


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


def fetch_all_min_instances() -> Optional[Dict[str, int]]:
    """
    Fetch the minScale annotation for every Cloud Run service in the region in one call.

    One `services list` returns everything in ~2s; running 10 sequential
    `services describe` calls is flake-prone under subprocess timeouts.

    Returns:
        Dict mapping service name to minScale int (0 when annotation is unset),
        or None if the call fails.
    """
    try:
        result = subprocess.run(
            [
                "gcloud", "run", "services", "list",
                f"--region={REGION}",
                f"--project={PROJECT_ID}",
                "--format=csv[no-heading](metadata.name,"
                "spec.template.metadata.annotations['autoscaling.knative.dev/minScale'])"
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            logger.warning(f"Failed to list services for minScale check: {result.stderr.strip()}")
            return None

        scales: Dict[str, int] = {}
        for line in result.stdout.strip().splitlines():
            if "," not in line:
                continue
            name, raw = line.split(",", 1)
            name = name.strip()
            raw = raw.strip()
            if not name:
                continue
            scales[name] = int(raw) if raw else 0

        return scales

    except Exception as e:
        logger.error(f"Error listing services for minScale check: {e}")
        return None


def check_min_instances(service: str, all_scales: Dict[str, int]) -> Optional[Dict]:
    """
    Check whether a service's live minScale annotation matches expectations.

    Returns a config-drift dict if the live value differs from EXPECTED_MIN_INSTANCES,
    None if it matches or no expectation is set.
    """
    expected = EXPECTED_MIN_INSTANCES.get(service)
    if expected is None:
        return None

    if service not in all_scales:
        logger.warning(f"Service {service} not present in services list — cannot check minScale")
        return None

    actual = all_scales[service]
    if actual == expected:
        return None

    return {
        'service': service,
        'kind': 'config_drift',
        'attribute': 'min_instances',
        'expected': expected,
        'actual': actual,
    }


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
    all_scales = fetch_all_min_instances() or {}

    for service in SERVICES_TO_MONITOR:
        deploy_timestamp = get_deployment_timestamp(service)

        if deploy_timestamp:
            age_hours = (github_timestamp - deploy_timestamp) / 3600

            if age_hours > 2:
                drifted_services.append({
                    'service': service,
                    'deploy_timestamp': deploy_timestamp,
                    'github_timestamp': github_timestamp,
                    'drift_hours': age_hours
                })
                logger.warning(f"Service {service} is {age_hours:.1f} hours behind")

        config_drift = check_min_instances(service, all_scales)
        if config_drift:
            logger.warning(
                f"Config drift in {service}: {config_drift['attribute']} "
                f"expected={config_drift['expected']} actual={config_drift['actual']}"
            )
            drifted_services.append(config_drift)

    return drifted_services


def send_drift_alert(drifted_services: List[Dict]):
    """Send Slack alert for drifted services."""
    if not drifted_services:
        logger.info("No deployment drift detected")
        return

    code_drifts = [d for d in drifted_services if d.get('kind') != 'config_drift']
    config_drifts = [d for d in drifted_services if d.get('kind') == 'config_drift']

    message_lines = [
        f"🚨 *Deployment Drift Detected* ({len(drifted_services)} issue(s))",
        "",
    ]

    if code_drifts:
        message_lines.append(f"*Code drift — {len(code_drifts)} service(s) behind main:*")
        for service in code_drifts:
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
        ])

    if config_drifts:
        message_lines.append(f"*Config drift — {len(config_drifts)} service(s) with unexpected settings:*")
        for drift in config_drifts:
            svc = drift['service']
            message_lines.append(
                f"• `{svc}` — `{drift['attribute']}` expected `{drift['expected']}`, "
                f"got `{drift['actual']}`"
            )
            if drift['attribute'] == 'min_instances':
                message_lines.append(
                    f"  Fix: `gcloud run services update {svc} --region={REGION} "
                    f"--project={PROJECT_ID} --min-instances={drift['expected']}`"
                )
                message_lines.append(
                    "  Also check Cloud Build trigger substitution `_MIN_INSTANCES` — "
                    "auto-deploy can re-introduce the regression."
                )
        message_lines.append("")

    message_lines.append(
        f"_Automated check at {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}_"
    )

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

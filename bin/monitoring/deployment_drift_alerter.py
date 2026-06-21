#!/usr/bin/env python3
"""
Deployment Drift Alerter (Session 135 - Resilience Layer 1)

Monitors for deployment drift and sends Slack alerts every 2 hours.
Mirrors logic from bin/check-deployment-drift.sh.

Usage:
    python bin/monitoring/deployment_drift_alerter.py

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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"
REGION = "us-west2"

# Map services to their source directories
# Keep in sync with bin/check-deployment-drift.sh
SERVICE_SOURCES = {
    # Predictions
    "prediction-worker": ["predictions/worker", "shared"],
    "prediction-coordinator": ["predictions/coordinator", "shared"],

    # NBA Processing
    "nba-scrapers": ["scrapers"],
    "nba-phase2-raw-processors": ["data_processors/phase2"],
    "nba-phase3-analytics-processors": ["data_processors/phase3", "shared"],
    "nba-phase4-precompute-processors": ["data_processors/phase4", "shared"],

    # Grading
    "nba-grading-service": ["data_processors/grading/nba", "shared", "predictions/shared"],

    # Orchestration
    "phase3-to-phase4-orchestrator": ["orchestration/phase3_to_phase4"],
    "phase4-to-phase5-orchestrator": ["orchestration/phase4_to_phase5"],

    # Admin
    "nba-admin-dashboard": ["admin_dashboard"],
}

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

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout getting deployment info for {service}")
        return None
    except Exception as e:
        logger.error(f"Error getting deployment timestamp for {service}: {e}")
        return None


def get_latest_commit_timestamp(source_dirs: List[str]) -> Tuple[Optional[int], Optional[str]]:
    """
    Get the latest commit timestamp affecting the source directories.

    Args:
        source_dirs: List of source directories to check

    Returns:
        Tuple of (unix timestamp, commit hash) or (None, None)
    """
    latest_epoch = 0
    latest_hash = None

    for dir_path in source_dirs:
        if not os.path.isdir(dir_path):
            continue

        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%H %at %s", "--", dir_path],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0 or not result.stdout.strip():
                continue

            parts = result.stdout.strip().split(' ', 2)
            if len(parts) >= 2:
                commit_hash = parts[0]
                commit_epoch = int(parts[1])

                if commit_epoch > latest_epoch:
                    latest_epoch = commit_epoch
                    latest_hash = commit_hash

        except Exception as e:
            logger.error(f"Error getting commit info for {dir_path}: {e}")
            continue

    if latest_epoch == 0:
        return None, None

    return latest_epoch, latest_hash


def get_recent_commits(source_dirs: List[str], since_epoch: int, limit: int = 5) -> List[str]:
    """
    Get recent commits since a timestamp.

    Args:
        source_dirs: List of source directories
        since_epoch: Unix timestamp to start from
        limit: Max commits to return

    Returns:
        List of commit summaries
    """
    commits = []

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"--since=@{since_epoch}", "--"] + source_dirs,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0 and result.stdout.strip():
            commits = result.stdout.strip().split('\n')[:limit]

    except Exception as e:
        logger.error(f"Error getting recent commits: {e}")

    return commits


def check_service_drift(service: str, source_dirs: List[str]) -> Optional[Dict]:
    """
    Check if a service has deployment drift.

    Args:
        service: Service name
        source_dirs: Source directories for the service

    Returns:
        Drift info dict if drifted, None otherwise
    """
    # Get deployment timestamp
    deploy_epoch = get_deployment_timestamp(service)
    if deploy_epoch is None:
        return None

    # Get latest commit timestamp
    commit_epoch, commit_hash = get_latest_commit_timestamp(source_dirs)
    if commit_epoch is None:
        return None

    # Check for drift
    if commit_epoch <= deploy_epoch:
        return None  # No drift

    # Calculate drift
    drift_hours = (commit_epoch - deploy_epoch) / 3600

    # Get recent commits
    recent_commits = get_recent_commits(source_dirs, deploy_epoch, limit=5)

    return {
        'service': service,
        'deploy_epoch': deploy_epoch,
        'commit_epoch': commit_epoch,
        'commit_hash': commit_hash,
        'drift_hours': drift_hours,
        'recent_commits': recent_commits,
        'source_dirs': source_dirs
    }


def fetch_all_min_instances() -> Optional[Dict[str, int]]:
    """
    Fetch the minScale annotation for every Cloud Run service in the region in one call.

    Sequential `services describe` calls hit subprocess timeout flakes when run 10x
    in a tight loop. One `services list` call returns everything in ~2s.

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

    except subprocess.TimeoutExpired:
        logger.error("Timeout listing services for minScale check")
        return None
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


def format_slack_alert(drifted_services: List[Dict]) -> str:
    """
    Format Slack alert message for drifted services.

    Args:
        drifted_services: List of drift info dicts

    Returns:
        Formatted Slack message
    """
    if not drifted_services:
        return None

    code_drifts = [d for d in drifted_services if d.get('kind') != 'config_drift']
    config_drifts = [d for d in drifted_services if d.get('kind') == 'config_drift']

    lines = ["⚠️ *Deployment Drift Detected*", ""]

    if code_drifts:
        lines.append(f"*Code drift — {len(code_drifts)} service(s) with stale deployments:*")
        lines.append("")

        for drift in code_drifts:
            service = drift['service']
            drift_hours = drift['drift_hours']
            deploy_date = datetime.fromtimestamp(drift['deploy_epoch']).strftime('%Y-%m-%d %H:%M')
            commit_date = datetime.fromtimestamp(drift['commit_epoch']).strftime('%Y-%m-%d %H:%M')

            lines.append(f"*{service}*")
            lines.append(f"• Deployed: {deploy_date}")
            lines.append(f"• Code changed: {commit_date}")
            lines.append(f"• Drift: {drift_hours:.1f} hours behind")

            if drift['recent_commits']:
                lines.append("• Recent commits:")
                for commit in drift['recent_commits'][:3]:
                    lines.append(f"  - {commit}")

            lines.append(f"• Deploy: `./bin/deploy-service.sh {service}`")
            lines.append("")

    if config_drifts:
        lines.append(f"*Config drift — {len(config_drifts)} service(s) with unexpected settings:*")
        lines.append("")

        for drift in config_drifts:
            service = drift['service']
            attribute = drift['attribute']
            expected = drift['expected']
            actual = drift['actual']

            lines.append(f"*{service}*")
            lines.append(f"• `{attribute}` expected `{expected}`, got `{actual}`")
            if attribute == 'min_instances':
                lines.append(
                    f"• Fix: `gcloud run services update {service} --region={REGION} "
                    f"--project={PROJECT_ID} --min-instances={expected}`"
                )
                lines.append(
                    "• Also check Cloud Build trigger substitution `_MIN_INSTANCES` — "
                    "auto-deploy can re-introduce the regression."
                )
            lines.append("")

    lines.append("_Run `./bin/check-deployment-drift.sh --verbose` for full details_")

    return "\n".join(lines)


def main():
    """Main entry point."""
    logger.info("Starting deployment drift check")

    drifted_services = []
    all_scales = fetch_all_min_instances() or {}

    for service, source_dirs in SERVICE_SOURCES.items():
        logger.info(f"Checking {service}...")

        drift = check_service_drift(service, source_dirs)
        if drift:
            logger.warning(f"Found drift in {service}: {drift['drift_hours']:.1f} hours behind")
            drifted_services.append(drift)
        else:
            logger.info(f"{service} is up to date")

        config_drift = check_min_instances(service, all_scales)
        if config_drift:
            logger.warning(
                f"Config drift in {service}: {config_drift['attribute']} "
                f"expected={config_drift['expected']} actual={config_drift['actual']}"
            )
            drifted_services.append(config_drift)

    # Send alert if drift found
    if drifted_services:
        logger.warning(f"Found {len(drifted_services)} drifted services")

        message = format_slack_alert(drifted_services)

        # Send to #deployment-alerts channel
        success = send_slack_alert(
            message=message,
            channel="#deployment-alerts",
            alert_type="DEPLOYMENT_DRIFT"
        )

        if success:
            logger.info("Sent deployment drift alert to Slack")
        else:
            logger.error("Failed to send deployment drift alert")

        return 1
    else:
        logger.info("All services up to date - no alerts sent")
        return 0


if __name__ == "__main__":
    sys.exit(main())

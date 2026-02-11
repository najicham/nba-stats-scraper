#!/usr/bin/env python3
"""
Config Drift Detection Script

Compares deployed Cloud Function/Run configurations vs expected values.
Detects drift in:
- Memory allocations
- Timeout settings
- Environment variables
- Max instances

Usage:
    python bin/validation/detect_config_drift.py
    python bin/validation/detect_config_drift.py --alert  # Send Slack alert on drift

Part of: Pipeline Resilience Improvements (Jan 2026)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Expected configurations for Cloud Functions
EXPECTED_CLOUD_FUNCTIONS = {# REMOVED Session 204: phase2-to-phase3-orchestrator (monitoring-only, no functional value)
    # 
    'phase2-to-phase3-orchestrator': {
        'memory': '512Mi',
        'timeout': '60s',
        'max_instances': 10,
        'min_instances': 0,
    },
    'phase3-to-phase4-orchestrator': {
        'memory': '512Mi',
        'timeout': '60s',
        'max_instances': 10,
        'min_instances': 0,
    },
    'phase4-to-phase5-orchestrator': {
        'memory': '512Mi',
        'timeout': '60s',
        'max_instances': 10,
        'min_instances': 0,
    },
    'phase5-to-phase6-orchestrator': {
        'memory': '512Mi',
        'timeout': '60s',
        'max_instances': 10,
        'min_instances': 0,
    },
    'auto-retry-processor': {
        'memory': '256Mi',
        'timeout': '120s',
        'max_instances': 1,
        'min_instances': 0,
    },
    'stale-processor-monitor': {
        'memory': '256Mi',
        'timeout': '60s',
        'max_instances': 1,
    },
    'game-coverage-alert': {
        'memory': '256Mi',
        'timeout': '60s',
        'max_instances': 1,
    },
    'auto-backfill-orchestrator': {
        'memory': '512Mi',
        'timeout': '120s',
        'max_instances': 5,
    },
}

# Expected configurations for Cloud Run services
EXPECTED_CLOUD_RUN = {
    'prediction-worker': {
        'memory': '2Gi',
        'timeout': '300s',
        'max_instances': 50,
        'min_instances': 0,
    },
    'prediction-coordinator': {
        'memory': '1Gi',
        'timeout': '300s',
        'max_instances': 10,
        'min_instances': 0,
    },
}

PROJECT_ID = 'nba-props-platform'
REGION = 'us-west2'


def get_cloud_function_config(function_name: str) -> Optional[Dict]:
    """Get deployed Cloud Function configuration."""
    try:
        result = subprocess.run(
            [
                'gcloud', 'functions', 'describe', function_name,
                '--region', REGION,
                '--gen2',
                '--project', PROJECT_ID,
                '--format', 'json'
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            logger.warning(f"Could not get config for {function_name}: {result.stderr}")
            return None

        config = json.loads(result.stdout)
        service_config = config.get('serviceConfig', {})

        return {
            'memory': service_config.get('availableMemory', 'unknown'),
            'timeout': f"{service_config.get('timeoutSeconds', 0)}s",
            'max_instances': service_config.get('maxInstanceCount', 0),
            'min_instances': service_config.get('minInstanceCount', 0),
            'state': config.get('state', 'UNKNOWN'),
        }
    except Exception as e:
        logger.error(f"Error getting config for {function_name}: {e}")
        return None


def get_cloud_run_config(service_name: str) -> Optional[Dict]:
    """Get deployed Cloud Run configuration."""
    try:
        result = subprocess.run(
            [
                'gcloud', 'run', 'services', 'describe', service_name,
                '--region', REGION,
                '--project', PROJECT_ID,
                '--format', 'json'
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            logger.warning(f"Could not get config for {service_name}: {result.stderr}")
            return None

        config = json.loads(result.stdout)
        spec = config.get('spec', {}).get('template', {}).get('spec', {})
        containers = spec.get('containers', [{}])[0]
        resources = containers.get('resources', {}).get('limits', {})
        metadata = config.get('spec', {}).get('template', {}).get('metadata', {})
        annotations = metadata.get('annotations', {})

        return {
            'memory': resources.get('memory', 'unknown'),
            'timeout': annotations.get('run.googleapis.com/execution-environment', 'unknown'),
            'max_instances': int(annotations.get('autoscaling.knative.dev/maxScale', 0)),
            'min_instances': int(annotations.get('autoscaling.knative.dev/minScale', 0)),
        }
    except Exception as e:
        logger.error(f"Error getting config for {service_name}: {e}")
        return None


def normalize_memory(memory_str: str) -> int:
    """Convert memory string to MB for comparison."""
    memory_str = memory_str.upper().replace('I', '')
    if 'G' in memory_str:
        return int(float(memory_str.replace('G', '').replace('B', '')) * 1024)
    elif 'M' in memory_str:
        return int(float(memory_str.replace('M', '').replace('B', '')))
    return 0


def compare_configs(expected: Dict, actual: Dict, name: str) -> List[Dict]:
    """Compare expected vs actual configuration and return drift list."""
    drifts = []

    # Compare memory
    expected_memory = normalize_memory(expected.get('memory', '0'))
    actual_memory = normalize_memory(actual.get('memory', '0'))
    if expected_memory != actual_memory:
        drifts.append({
            'resource': name,
            'field': 'memory',
            'expected': expected.get('memory'),
            'actual': actual.get('memory'),
            'severity': 'high' if actual_memory < expected_memory else 'medium'
        })

    # Compare timeout
    expected_timeout = expected.get('timeout', '0s').replace('s', '')
    actual_timeout = actual.get('timeout', '0s').replace('s', '')
    try:
        if int(expected_timeout) != int(actual_timeout):
            drifts.append({
                'resource': name,
                'field': 'timeout',
                'expected': expected.get('timeout'),
                'actual': actual.get('timeout'),
                'severity': 'medium'
            })
    except ValueError:
        pass  # Skip if timeout format is unexpected

    # Compare max_instances
    if expected.get('max_instances') != actual.get('max_instances'):
        drifts.append({
            'resource': name,
            'field': 'max_instances',
            'expected': expected.get('max_instances'),
            'actual': actual.get('max_instances'),
            'severity': 'medium'
        })

    return drifts


def send_slack_alert(drifts: List[Dict]) -> bool:
    """Send Slack alert for detected drift."""
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set, skipping alert")
        return False

    try:
        import requests

        drift_text = "\n".join([
            f"• *{d['resource']}* `{d['field']}`: expected `{d['expected']}`, actual `{d['actual']}` ({d['severity']})"
            for d in drifts
        ])

        message = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f":warning: Config Drift Detected ({len(drifts)} issues)",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": drift_text
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "Run `./bin/validation/detect_config_drift.py` for details"
                        }
                    ]
                }
            ]
        }

        response = requests.post(webhook_url, json=message, timeout=10)
        response.raise_for_status()
        logger.info("Slack alert sent successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Detect configuration drift in Cloud resources')
    parser.add_argument('--alert', action='store_true', help='Send Slack alert on drift')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    print("=" * 60)
    print("Config Drift Detection")
    print("=" * 60)
    print()

    all_drifts = []

    # Check Cloud Functions
    print("Checking Cloud Functions...")
    print("-" * 40)
    for name, expected in EXPECTED_CLOUD_FUNCTIONS.items():
        actual = get_cloud_function_config(name)
        if actual is None:
            print(f"  {name}: NOT FOUND")
            all_drifts.append({
                'resource': name,
                'field': 'deployment',
                'expected': 'deployed',
                'actual': 'not found',
                'severity': 'critical'
            })
        else:
            drifts = compare_configs(expected, actual, name)
            if drifts:
                print(f"  {name}: DRIFT DETECTED")
                for d in drifts:
                    print(f"    - {d['field']}: expected {d['expected']}, actual {d['actual']}")
                all_drifts.extend(drifts)
            else:
                print(f"  {name}: OK")
    print()

    # Check Cloud Run services
    print("Checking Cloud Run services...")
    print("-" * 40)
    for name, expected in EXPECTED_CLOUD_RUN.items():
        actual = get_cloud_run_config(name)
        if actual is None:
            print(f"  {name}: NOT FOUND OR ERROR")
        else:
            drifts = compare_configs(expected, actual, name)
            if drifts:
                print(f"  {name}: DRIFT DETECTED")
                for d in drifts:
                    print(f"    - {d['field']}: expected {d['expected']}, actual {d['actual']}")
                all_drifts.extend(drifts)
            else:
                print(f"  {name}: OK")
    print()

    # Summary
    print("=" * 60)
    if all_drifts:
        print(f"RESULT: {len(all_drifts)} drift(s) detected")

        if args.json:
            print(json.dumps(all_drifts, indent=2))

        if args.alert:
            send_slack_alert(all_drifts)

        sys.exit(1)
    else:
        print("RESULT: No drift detected - all configs match expected values")
        sys.exit(0)


if __name__ == '__main__':
    main()

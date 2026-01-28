#!/usr/bin/env python3
"""
Post-Deployment Health Check Script

Verifies Cloud Functions start successfully after deployment by checking
Cloud Run logs for startup success or failure indicators.

Usage:
    python bin/validation/post_deployment_health_check.py phase3-to-phase4-orchestrator
    python bin/validation/post_deployment_health_check.py --service phase2-to-phase3-orchestrator
    python bin/validation/post_deployment_health_check.py --service my-function --region us-central1
    python bin/validation/post_deployment_health_check.py --service my-function --timeout 120

Exit codes:
    0 - Healthy (startup succeeded or service is running)
    1 - Unhealthy (startup failed or import errors detected)
    2 - Unknown (could not determine status, e.g., no recent logs)

Created: 2026-01-28
Reason: Catch Cloud Function startup failures immediately after deployment
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple


# Default configuration
DEFAULT_PROJECT = "nba-props-platform"
DEFAULT_REGION = "us-west2"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_LOG_WINDOW_MINUTES = 5

# Success indicators in Cloud Run logs
STARTUP_SUCCESS_PATTERNS = [
    "STARTUP TCP probe succeeded",
    "Default STARTUP TCP probe succeeded",
    "Listening on port",
    "Function is ready",
]

# Failure indicators (import errors, exceptions during startup)
STARTUP_FAILURE_PATTERNS = [
    "ModuleNotFoundError",
    "ImportError",
    "SyntaxError",
    "Container failed to start",
    "Container called exit",
    "STARTUP TCP probe failed",
    "Failed to start",
    "Error: could not handle the request",
    "NameError",
    "AttributeError: module",
]


def run_gcloud_command(args: list, timeout: int = 30) -> Tuple[int, str, str]:
    """
    Run a gcloud command and return (returncode, stdout, stderr).
    """
    try:
        result = subprocess.run(
            ["gcloud"] + args,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", "gcloud CLI not found"
    except Exception as e:
        return -1, "", str(e)


def get_cloud_run_service_name(function_name: str, project: str, region: str) -> Optional[str]:
    """
    Get the Cloud Run service name for a gen2 Cloud Function.
    Gen2 functions run as Cloud Run services.
    """
    # For gen2 functions, the Cloud Run service name is typically the same
    # as the function name, but we'll verify it exists
    args = [
        "run", "services", "describe", function_name,
        "--region", region,
        "--project", project,
        "--format", "value(metadata.name)",
    ]

    returncode, stdout, stderr = run_gcloud_command(args)

    if returncode == 0 and stdout.strip():
        return stdout.strip()

    return None


def check_cloud_run_logs(
    service_name: str,
    project: str,
    region: str,
    minutes: int = DEFAULT_LOG_WINDOW_MINUTES
) -> Tuple[bool, bool, list]:
    """
    Check Cloud Run logs for startup success/failure.

    Returns:
        Tuple of (found_success, found_failure, relevant_log_lines)
    """
    # Calculate the time window
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=minutes)

    # Format timestamps for gcloud logging
    start_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build the filter for Cloud Run logs
    # Cloud Run logs are in the run.googleapis.com/revision_name resource
    log_filter = (
        f'resource.type="cloud_run_revision" '
        f'resource.labels.service_name="{service_name}" '
        f'timestamp>="{start_str}"'
    )

    args = [
        "logging", "read", log_filter,
        "--project", project,
        "--format", "json",
        "--limit", "100",
    ]

    returncode, stdout, stderr = run_gcloud_command(args, timeout=60)

    if returncode != 0:
        print(f"  Warning: Could not read logs: {stderr.strip()}")
        return False, False, []

    if not stdout.strip():
        return False, False, []

    try:
        logs = json.loads(stdout)
    except json.JSONDecodeError:
        print(f"  Warning: Could not parse logs")
        return False, False, []

    found_success = False
    found_failure = False
    relevant_lines = []

    for entry in logs:
        # Get the log message
        message = ""
        if "textPayload" in entry:
            message = entry["textPayload"]
        elif "jsonPayload" in entry:
            payload = entry["jsonPayload"]
            if isinstance(payload, dict):
                message = payload.get("message", "") or payload.get("msg", "") or str(payload)
            else:
                message = str(payload)

        if not message:
            continue

        # Check for success patterns
        for pattern in STARTUP_SUCCESS_PATTERNS:
            if pattern in message:
                found_success = True
                relevant_lines.append(f"[SUCCESS] {message[:200]}")
                break

        # Check for failure patterns
        for pattern in STARTUP_FAILURE_PATTERNS:
            if pattern in message:
                found_failure = True
                relevant_lines.append(f"[FAILURE] {message[:200]}")
                break

    return found_success, found_failure, relevant_lines


def check_function_status(function_name: str, project: str, region: str) -> Tuple[str, str]:
    """
    Check the current status of a Cloud Function.

    Returns:
        Tuple of (state, update_time)
    """
    args = [
        "functions", "describe", function_name,
        "--gen2",
        "--region", region,
        "--project", project,
        "--format", "json",
    ]

    returncode, stdout, stderr = run_gcloud_command(args, timeout=30)

    if returncode != 0:
        return "UNKNOWN", ""

    try:
        func_info = json.loads(stdout)
        state = func_info.get("state", "UNKNOWN")
        update_time = func_info.get("updateTime", "")
        return state, update_time
    except json.JSONDecodeError:
        return "UNKNOWN", ""


def wait_for_deployment(
    function_name: str,
    project: str,
    region: str,
    timeout_seconds: int
) -> bool:
    """
    Wait for deployment to complete (function state becomes ACTIVE).

    Returns True if deployment completed successfully, False otherwise.
    """
    start_time = time.time()
    poll_interval = 5  # seconds

    print(f"  Waiting for deployment to complete (timeout: {timeout_seconds}s)...")

    while time.time() - start_time < timeout_seconds:
        state, update_time = check_function_status(function_name, project, region)

        if state == "ACTIVE":
            print(f"  Function state: ACTIVE")
            return True
        elif state in ["FAILED", "UNKNOWN"]:
            print(f"  Function state: {state}")
            return False
        else:
            # Still deploying
            elapsed = int(time.time() - start_time)
            print(f"  Function state: {state} (waiting... {elapsed}s)")
            time.sleep(poll_interval)

    print(f"  Timeout waiting for deployment")
    return False


def run_health_check(
    service_name: str,
    project: str = DEFAULT_PROJECT,
    region: str = DEFAULT_REGION,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    log_window_minutes: int = DEFAULT_LOG_WINDOW_MINUTES
) -> int:
    """
    Run the post-deployment health check.

    Returns:
        0 - Healthy
        1 - Unhealthy
        2 - Unknown
    """
    print("=" * 60)
    print("POST-DEPLOYMENT HEALTH CHECK")
    print("=" * 60)
    print(f"  Service:  {service_name}")
    print(f"  Project:  {project}")
    print(f"  Region:   {region}")
    print(f"  Timeout:  {timeout_seconds}s")
    print("-" * 60)

    # Step 1: Wait for deployment to complete
    print("\n[1/3] Checking deployment status...")
    if not wait_for_deployment(service_name, project, region, timeout_seconds):
        print("\n" + "=" * 60)
        print("HEALTH CHECK RESULT: UNHEALTHY")
        print("  Deployment did not complete successfully")
        print("=" * 60)
        return 1

    # Step 2: Give the service a moment to start up
    print("\n[2/3] Waiting for service startup (10s)...")
    time.sleep(10)

    # Step 3: Check logs for startup success/failure
    print(f"\n[3/3] Checking logs from last {log_window_minutes} minutes...")

    found_success, found_failure, relevant_lines = check_cloud_run_logs(
        service_name, project, region, log_window_minutes
    )

    if relevant_lines:
        print("\n  Relevant log entries:")
        for line in relevant_lines[:10]:  # Show up to 10 entries
            print(f"    {line}")

    # Determine health status
    print("\n" + "=" * 60)

    if found_failure:
        print("HEALTH CHECK RESULT: UNHEALTHY")
        print("  Startup failure detected in logs")
        print("=" * 60)
        print("\nTroubleshooting:")
        print(f"  View full logs: gcloud functions logs read {service_name} --region {region} --limit 50")
        print(f"  Check function: gcloud functions describe {service_name} --region {region} --gen2")
        return 1

    if found_success:
        print("HEALTH CHECK RESULT: HEALTHY")
        print("  Startup succeeded, function is running")
        print("=" * 60)
        return 0

    # No clear success or failure - check function state
    state, _ = check_function_status(service_name, project, region)

    if state == "ACTIVE":
        print("HEALTH CHECK RESULT: HEALTHY")
        print("  Function is ACTIVE (no startup issues detected)")
        print("=" * 60)
        return 0

    print("HEALTH CHECK RESULT: UNKNOWN")
    print("  Could not determine startup status from logs")
    print("  Function may still be initializing")
    print("=" * 60)
    print("\nTroubleshooting:")
    print(f"  View logs: gcloud functions logs read {service_name} --region {region} --limit 50")
    print(f"  Re-run check: python bin/validation/post_deployment_health_check.py {service_name}")
    return 2


def main():
    parser = argparse.ArgumentParser(
        description="Post-deployment health check for Cloud Functions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check health of a specific function
  python bin/validation/post_deployment_health_check.py phase3-to-phase4-orchestrator

  # Specify region and project
  python bin/validation/post_deployment_health_check.py --service my-function --region us-central1

  # Increase timeout for slow deployments
  python bin/validation/post_deployment_health_check.py --service my-function --timeout 120
        """
    )

    parser.add_argument(
        "service",
        nargs="?",
        help="Cloud Function/service name to check"
    )
    parser.add_argument(
        "--service", "-s",
        dest="service_flag",
        help="Cloud Function/service name (alternative to positional)"
    )
    parser.add_argument(
        "--project", "-p",
        default=DEFAULT_PROJECT,
        help=f"GCP project ID (default: {DEFAULT_PROJECT})"
    )
    parser.add_argument(
        "--region", "-r",
        default=DEFAULT_REGION,
        help=f"GCP region (default: {DEFAULT_REGION})"
    )
    parser.add_argument(
        "--timeout", "-t",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Timeout in seconds to wait for deployment (default: {DEFAULT_TIMEOUT_SECONDS})"
    )
    parser.add_argument(
        "--log-window",
        type=int,
        default=DEFAULT_LOG_WINDOW_MINUTES,
        help=f"Minutes of logs to check (default: {DEFAULT_LOG_WINDOW_MINUTES})"
    )

    args = parser.parse_args()

    # Get service name from either positional or flag argument
    service_name = args.service or args.service_flag

    if not service_name:
        parser.error("Service name is required")

    return run_health_check(
        service_name=service_name,
        project=args.project,
        region=args.region,
        timeout_seconds=args.timeout,
        log_window_minutes=args.log_window
    )


if __name__ == "__main__":
    sys.exit(main())

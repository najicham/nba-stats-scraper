#!/usr/bin/env python3
"""
Validate auto-deploy consistency.

Ensures every Cloud Run service monitored by check-deployment-drift.sh
is also covered by auto-deploy.yml. Cloud Functions are excluded (they
deploy via cloudbuild-functions.yaml).

Session 335: Created to prevent silent drift accumulation when a new
Cloud Run service is added to drift monitoring but not to auto-deploy.

Usage:
    python .pre-commit-hooks/validate_auto_deploy_consistency.py
"""

import os
import re
import sys


# Services intentionally excluded from auto-deploy (manual deploy only)
EXCLUDED_SERVICES = {
    'nba-admin-dashboard',
}

# Known name aliases: drift-check name -> auto-deploy name
# Some services use different names between the two files
SERVICE_ALIASES = {
    'nba-phase1-scrapers': 'nba-scrapers',
}


def parse_drift_check_services(filepath: str) -> dict:
    """Parse Cloud Run service names from check-deployment-drift.sh.

    Returns dict of service_name -> source_dirs string.
    """
    services = {}
    with open(filepath, 'r') as f:
        content = f.read()

    # Match lines like: ["service-name"]="source/dir shared"
    pattern = r'\["([^"]+)"\]="([^"]*)"'
    for match in re.finditer(pattern, content):
        service_name = match.group(1)
        source_dirs = match.group(2)
        services[service_name] = source_dirs

    return services


def parse_auto_deploy_services(filepath: str) -> set:
    """Parse Cloud Run service names from auto-deploy.yml.

    Looks for 'service:' fields in the deploy job definitions.
    """
    services = set()
    with open(filepath, 'r') as f:
        content = f.read()

    # Match 'service: service-name' in the workflow
    for match in re.finditer(r'service:\s+(\S+)', content):
        services.add(match.group(1))

    return services


def is_cloud_run_service(service_name: str, source_dirs: str) -> bool:
    """Determine if a service is Cloud Run (has Dockerfile) vs Cloud Function.

    Cloud Functions have source dirs under orchestration/cloud_functions/
    or monitoring/. Cloud Run services have Dockerfiles.
    """
    dirs = source_dirs.strip().split()
    # If ALL source dirs are under cloud function paths, it's a Cloud Function
    cf_prefixes = (
        'orchestration/cloud_functions/',
        'monitoring/',
    )
    all_cf = all(
        any(d.startswith(p) for p in cf_prefixes)
        for d in dirs if d != 'shared'
    )
    # Filter out entries where the only non-shared dir is a CF path
    non_shared_dirs = [d for d in dirs if d != 'shared']
    if not non_shared_dirs:
        return False
    return not all_cf


def main() -> int:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    drift_check_path = os.path.join(repo_root, 'bin', 'check-deployment-drift.sh')
    auto_deploy_path = os.path.join(repo_root, '.github', 'workflows', 'auto-deploy.yml')

    if not os.path.exists(drift_check_path):
        print(f"SKIP: {drift_check_path} not found")
        return 0

    if not os.path.exists(auto_deploy_path):
        print(f"SKIP: {auto_deploy_path} not found")
        return 0

    drift_services = parse_drift_check_services(drift_check_path)
    auto_deploy_services = parse_auto_deploy_services(auto_deploy_path)

    # Filter to Cloud Run services only
    cloud_run_services = {
        name for name, dirs in drift_services.items()
        if is_cloud_run_service(name, dirs)
    }

    # Remove excluded services
    cloud_run_services -= EXCLUDED_SERVICES

    # Resolve known aliases: map drift-check names to auto-deploy names
    resolved_services = set()
    for name in cloud_run_services:
        resolved_services.add(SERVICE_ALIASES.get(name, name))

    # Find Cloud Run services in drift check but missing from auto-deploy
    missing = resolved_services - auto_deploy_services

    if missing:
        print("ERROR: Cloud Run services monitored for drift but missing from auto-deploy:")
        for service in sorted(missing):
            print(f"  - {service}")
        print()
        print("Fix: Add these services to .github/workflows/auto-deploy.yml")
        print(f"Excluded (manual deploy): {sorted(EXCLUDED_SERVICES)}")
        return 1

    print(f"OK: All {len(cloud_run_services)} Cloud Run services have auto-deploy coverage")
    return 0


if __name__ == '__main__':
    sys.exit(main())

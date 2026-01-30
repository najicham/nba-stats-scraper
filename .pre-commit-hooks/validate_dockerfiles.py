#!/usr/bin/env python3
"""
Pre-commit hook: Validate Dockerfiles for all deployable services.

This hook ensures every Cloud Run service has a dedicated Dockerfile
and prevents the "wrong code deployment" issue where --source . picks
up the wrong Dockerfile.

Created: 2026-01-29 (Post-mortem from wrong deployment incident)
"""

import os
import sys
from pathlib import Path

# Map of Cloud Run services to their expected Dockerfiles
SERVICE_DOCKERFILE_MAP = {
    # Predictions
    "prediction-coordinator": "predictions/coordinator/Dockerfile",
    "prediction-worker": "predictions/worker/Dockerfile",

    # Data Processors
    "nba-phase3-analytics-processors": "data_processors/analytics/Dockerfile",
    "nba-phase4-precompute-processors": "data_processors/precompute/Dockerfile",

    # Scrapers
    "nba-scrapers": "scrapers/Dockerfile",
    "nba-phase1-scrapers": "scrapers/Dockerfile",

    # Note: Add future services here when they are created
    # "mlb-phase1-scrapers": "scrapers/mlb/Dockerfile",
}

# Services that share Dockerfiles (allowed)
SHARED_DOCKERFILES = {
    "scrapers/Dockerfile": ["nba-scrapers", "nba-phase1-scrapers"],
}


def validate_dockerfiles() -> int:
    """Validate that all required Dockerfiles exist."""
    repo_root = Path(__file__).parent.parent
    errors = []

    # Track which Dockerfiles we've verified
    verified = set()

    for service, dockerfile_path in SERVICE_DOCKERFILE_MAP.items():
        full_path = repo_root / dockerfile_path

        if dockerfile_path in verified:
            continue

        if not full_path.exists():
            errors.append(
                f"Missing Dockerfile for {service}: {dockerfile_path}\n"
                f"  This service cannot be deployed correctly without its Dockerfile.\n"
                f"  Create the Dockerfile or update SERVICE_DOCKERFILE_MAP."
            )
        else:
            verified.add(dockerfile_path)

            # Validate Dockerfile has correct entry point
            content = full_path.read_text()
            if "CMD" not in content and "ENTRYPOINT" not in content:
                errors.append(
                    f"Dockerfile {dockerfile_path} missing CMD or ENTRYPOINT"
                )

    # Check that bin/deploy-service.sh supports all services
    deploy_script = repo_root / "bin" / "deploy-service.sh"
    if deploy_script.exists():
        script_content = deploy_script.read_text()
        for service in SERVICE_DOCKERFILE_MAP:
            if service not in script_content:
                errors.append(
                    f"Service '{service}' not in bin/deploy-service.sh\n"
                    f"  Add support for this service in the deployment script."
                )

    # Report results
    if errors:
        print("=" * 60)
        print("DOCKERFILE VALIDATION FAILED")
        print("=" * 60)
        print()
        for error in errors:
            print(f"ERROR: {error}")
            print()
        print("=" * 60)
        print("Fix the above issues before committing.")
        print("See: docs/09-handoff/2026-01-29-POSTMORTEM-SCRAPER-WRONG-DEPLOYMENT.md")
        print("=" * 60)
        return 1

    print("Dockerfile validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(validate_dockerfiles())

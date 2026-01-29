#!/usr/bin/env python3
"""
Config Drift Detection Script

Compares production configuration with git-committed version to detect drift.
Should be run before validation to catch config issues early.

Usage:
    python scripts/detect_config_drift.py
    python scripts/detect_config_drift.py --service nba-phase1-scrapers
"""

import argparse
import subprocess
import sys
import os
import json
import yaml

PROJECT_ID = "nba-props-platform"
REGION = "us-west2"
CONFIG_FILE = "config/workflows.yaml"


def get_deployed_commit(service_name):
    """Get the commit SHA deployed to the service."""
    try:
        result = subprocess.run(
            [
                "gcloud", "run", "services", "describe", service_name,
                "--region", REGION,
                "--project", PROJECT_ID,
                "--format=json"
            ],
            capture_output=True,
            text=True,
            check=True
        )

        service_info = json.loads(result.stdout)
        commit_sha = service_info.get("metadata", {}).get("labels", {}).get("commit-sha")

        return commit_sha
    except Exception as e:
        print(f"❌ Error getting deployed commit: {e}")
        return None


def get_config_from_commit(commit_sha):
    """Get config file contents from a specific commit."""
    try:
        result = subprocess.run(
            ["git", "show", f"{commit_sha}:{CONFIG_FILE}"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError:
        print(f"❌ Error: Could not find config in commit {commit_sha}")
        return None


def get_current_config():
    """Get current committed config (HEAD)."""
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{CONFIG_FILE}"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError:
        print(f"❌ Error: Could not read current config from git")
        return None


def compare_configs(config1, config2):
    """Compare two config files and return differences."""
    try:
        yaml1 = yaml.safe_load(config1)
        yaml2 = yaml.safe_load(config2)

        # Focus on betting_lines workflow (the critical one from incident)
        betting1 = yaml1.get("workflows", {}).get("betting_lines", {})
        betting2 = yaml2.get("workflows", {}).get("betting_lines", {})

        differences = []

        # Check window_before_game_hours (critical parameter)
        window1 = betting1.get("schedule", {}).get("window_before_game_hours")
        window2 = betting2.get("schedule", {}).get("window_before_game_hours")

        if window1 != window2:
            differences.append({
                "workflow": "betting_lines",
                "parameter": "window_before_game_hours",
                "production": window1,
                "current": window2,
                "critical": True
            })

        # Check frequency
        freq1 = betting1.get("schedule", {}).get("frequency_hours")
        freq2 = betting2.get("schedule", {}).get("frequency_hours")

        if freq1 != freq2:
            differences.append({
                "workflow": "betting_lines",
                "parameter": "frequency_hours",
                "production": freq1,
                "current": freq2,
                "critical": False
            })

        # Check business hours
        bh1 = betting1.get("schedule", {}).get("business_hours")
        bh2 = betting2.get("schedule", {}).get("business_hours")

        if bh1 != bh2:
            differences.append({
                "workflow": "betting_lines",
                "parameter": "business_hours",
                "production": bh1,
                "current": bh2,
                "critical": False
            })

        return differences
    except Exception as e:
        print(f"❌ Error comparing configs: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description='Detect config drift between production and git'
    )
    parser.add_argument(
        '--service',
        type=str,
        default='nba-phase1-scrapers',
        help='Cloud Run service name'
    )

    args = parser.parse_args()

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Config Drift Detection")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()
    print(f"Service: {args.service}")
    print(f"Region: {REGION}")
    print(f"Config: {CONFIG_FILE}")
    print()

    # Step 1: Get deployed commit
    print("📦 Step 1: Getting deployed commit...")
    deployed_commit = get_deployed_commit(args.service)

    if not deployed_commit:
        print("❌ Could not determine deployed commit")
        print("   This check requires the service to have commit-sha label")
        sys.exit(1)

    print(f"   Deployed commit: {deployed_commit}")

    # Step 2: Get current HEAD commit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )
        current_commit = result.stdout.strip()
        print(f"   Current HEAD: {current_commit}")
    except subprocess.SubprocessError as e:
        print(f"❌ Could not determine current commit: {e}")
        sys.exit(1)

    print()

    # Step 3: Compare commits
    if deployed_commit == current_commit:
        print("✅ Production is up-to-date with HEAD")
        print("   No deployment needed")
        print()
    else:
        print("⚠️  Production is behind HEAD")
        print(f"   Commits behind: {deployed_commit}..{current_commit}")
        print()

        # Show commits between
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", f"{deployed_commit}..{current_commit}"],
                capture_output=True,
                text=True,
                check=True
            )
            commits = result.stdout.strip().split('\n')
            print(f"   {len(commits)} commit(s) ahead:")
            for commit in commits[:5]:  # Show first 5
                print(f"      {commit}")
            if len(commits) > 5:
                print(f"      ... and {len(commits) - 5} more")
            print()
        except subprocess.SubprocessError:
            # Non-critical: just skip showing commit history if git fails
            pass

    # Step 4: Check config differences
    print("🔍 Step 2: Checking config drift...")

    deployed_config = get_config_from_commit(deployed_commit)
    current_config = get_current_config()

    if not deployed_config or not current_config:
        print("❌ Could not load configs for comparison")
        sys.exit(1)

    differences = compare_configs(deployed_config, current_config)

    if differences is None:
        print("❌ Error comparing configs")
        sys.exit(1)

    if not differences:
        print("✅ No config drift detected")
        print("   Production config matches current HEAD")
        print()
        sys.exit(0)

    # Report differences
    print(f"⚠️  {len(differences)} config difference(s) detected:")
    print()

    has_critical = False
    for diff in differences:
        if diff["critical"]:
            print(f"   🚨 CRITICAL: {diff['workflow']}.{diff['parameter']}")
            has_critical = True
        else:
            print(f"   ⚠️  {diff['workflow']}.{diff['parameter']}")

        print(f"      Production: {diff['production']}")
        print(f"      HEAD:       {diff['current']}")
        print()

    # Summary and recommendations
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Recommendations")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()

    if has_critical:
        print("🚨 CRITICAL config drift detected!")
        print()
        print("   This drift can cause:")
        print("   - Workflow timing issues")
        print("   - Missing data collection")
        print("   - Validation false positives")
        print()
        print("   Action required: Deploy updated config immediately")
        print(f"   Command: ./bin/scrapers/deploy/deploy_scrapers_simple.sh")
        print()
        sys.exit(2)  # Exit code 2 = critical drift
    else:
        print("⚠️  Non-critical config drift detected")
        print()
        print("   Consider deploying to keep production in sync")
        print()
        sys.exit(1)  # Exit code 1 = drift but not critical


if __name__ == "__main__":
    main()

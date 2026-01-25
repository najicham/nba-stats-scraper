#!/usr/bin/env python3
"""
Validate Orchestration Config Against Workflows.yaml

This script prevents the processor name mismatch issue that caused the 2026-01-24 outage.
It compares the processor names in orchestration_config.py with the processor_name values
in workflows.yaml to ensure they match.

Usage:
    python bin/validation/validate_orchestration_config.py
    python bin/validation/validate_orchestration_config.py --fix  # Show suggested fixes

Run this:
- Before deploying orchestrators
- As part of CI/CD pipeline
- After modifying orchestration_config.py or workflows.yaml

Created: 2026-01-24
Reason: Processor name mismatch caused Phase 2 orchestration to fail (1/6 complete)
"""

import sys
import yaml
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def load_workflows_processor_names() -> dict[str, str]:
    """Load processor_name values from workflows.yaml."""
    workflows_path = project_root / "config" / "workflows.yaml"

    with open(workflows_path) as f:
        config = yaml.safe_load(f)

    processor_names = {}

    # Check scrapers section (main source of processor_name)
    for scraper_name, scraper_config in config.get("scrapers", {}).items():
        if isinstance(scraper_config, dict) and "processor_name" in scraper_config:
            processor_names[scraper_name] = scraper_config["processor_name"]

    # Also check workflows section if it exists
    for workflow_name, workflow_config in config.get("workflows", {}).items():
        if isinstance(workflow_config, dict) and "processor_name" in workflow_config:
            processor_names[workflow_name] = workflow_config["processor_name"]

    return processor_names


def load_orchestration_config_names() -> tuple[list[str], list[str], list[str]]:
    """Load processor names from orchestration_config.py."""
    from shared.config.orchestration_config import get_orchestration_config

    config = get_orchestration_config()
    transitions = config.phase_transitions

    return (
        transitions.phase2_expected_processors,
        transitions.phase2_required_processors,
        transitions.phase2_optional_processors,
    )


def validate_config(fix_mode: bool = False) -> bool:
    """Validate that orchestration config matches workflows.yaml."""
    print("=" * 60)
    print("Orchestration Config Validation")
    print("=" * 60)
    print()

    # Load both configs
    workflow_names = load_workflows_processor_names()
    expected, required, optional = load_orchestration_config_names()

    all_orchestration_names = set(expected + required + optional)
    all_workflow_names = set(workflow_names.values())

    print(f"Workflows.yaml processor_names: {len(workflow_names)}")
    print(f"Orchestration config processors: {len(all_orchestration_names)}")
    print()

    # Check for mismatches
    issues = []

    # Check if orchestration names exist in workflows
    for name in all_orchestration_names:
        if name not in all_workflow_names:
            # Find closest match
            closest = None
            for wf_name in all_workflow_names:
                if name.replace("_", "") in wf_name.replace("_", "") or \
                   wf_name.replace("_", "") in name.replace("_", ""):
                    closest = wf_name
                    break

            issues.append({
                "type": "NOT_IN_WORKFLOWS",
                "name": name,
                "closest_match": closest,
            })

    # Check Phase 2 specific (p2_* prefix convention)
    for name in expected:
        if not name.startswith("p2_"):
            issues.append({
                "type": "MISSING_PREFIX",
                "name": name,
                "suggested": f"p2_{name}",
            })

    # Report results
    if issues:
        print("VALIDATION FAILED")
        print("-" * 60)

        for issue in issues:
            if issue["type"] == "NOT_IN_WORKFLOWS":
                print(f"ERROR: '{issue['name']}' not found in workflows.yaml")
                if issue["closest_match"]:
                    print(f"       Closest match: '{issue['closest_match']}'")
                    if fix_mode:
                        print(f"       FIX: Replace '{issue['name']}' with '{issue['closest_match']}'")
            elif issue["type"] == "MISSING_PREFIX":
                print(f"WARNING: '{issue['name']}' missing 'p2_' prefix")
                if fix_mode:
                    print(f"       FIX: Rename to '{issue['suggested']}'")
            print()

        print("-" * 60)
        print(f"Found {len(issues)} issues")

        if fix_mode:
            print()
            print("To fix, update shared/config/orchestration_config.py")
            print("Then run: python bin/maintenance/sync_shared_utils.py --all")
            print("Then redeploy: ./bin/orchestrators/deploy_phase2_to_phase3.sh")

        return False
    else:
        print("VALIDATION PASSED")
        print("-" * 60)
        print("All orchestration processor names match workflows.yaml")
        print()

        # Show the mapping for verification
        print("Phase 2 Expected Processors:")
        for name in expected:
            status = "OK" if name in all_workflow_names else "MISSING"
            print(f"  [{status}] {name}")

        return True


def main():
    fix_mode = "--fix" in sys.argv

    try:
        success = validate_config(fix_mode)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()

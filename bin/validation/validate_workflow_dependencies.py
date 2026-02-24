#!/usr/bin/env python3
"""
Validate GitHub Actions Workflow Dependencies

Detects workflows with schedule triggers that reference disabled scrapers.
Prevents wasted CI minutes and spurious BQ errors from monitoring dead sources.

Usage:
    python bin/validation/validate_workflow_dependencies.py

Exit codes:
    0 = PASS (no issues found)
    1 = FAIL (workflows reference disabled scrapers with active schedules)

Created: Session 334 (2026-02-23)
Context: BDL workflows were generating ~97 BQ errors/day before Session 333 disabled them.
"""

import os
import re
import sys
import yaml

# Paths relative to repo root
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SCRAPER_CONFIG = os.path.join(REPO_ROOT, 'shared', 'config', 'scraper_retry_config.yaml')
WORKFLOWS_DIR = os.path.join(REPO_ROOT, '.github', 'workflows')

# Mapping: scraper config prefix -> search patterns in workflow files
# Each disabled scraper family maps to strings that would appear in workflows monitoring it
SCRAPER_FAMILY_PATTERNS = {
    'bdl': ['bdl_', 'bdl-', 'balldontlie', 'ball_dont_lie', 'ball-dont-lie'],
    'bdb': ['bdb_', 'bdb-', 'bigdataball'],
    'espn': ['espn_', 'espn-'],
    'pbpstats': ['pbpstats_', 'pbpstats-'],
}


def load_disabled_scrapers(config_path: str) -> set:
    """Parse scraper_retry_config.yaml and return set of disabled scraper prefixes."""
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    disabled_prefixes = set()
    scrapers = config.get('scrapers', {})
    for name, settings in scrapers.items():
        if not settings.get('enabled', True):
            # Extract family prefix (e.g., 'bdl' from 'bdl_live_box_scores')
            for family in SCRAPER_FAMILY_PATTERNS:
                if name.startswith(family):
                    disabled_prefixes.add(family)
                    break
    return disabled_prefixes


def has_active_schedule(content: str) -> bool:
    """Check if a workflow file has an active (uncommented) schedule trigger."""
    for line in content.splitlines():
        stripped = line.strip()
        # Skip commented lines
        if stripped.startswith('#'):
            continue
        # Look for schedule trigger (part of `on:` block)
        if re.match(r'^schedule:', stripped) or re.match(r'schedule:', stripped):
            return True
        # Also match indented schedule under on: block
        if re.match(r'^\s+schedule:', line) and not stripped.startswith('#'):
            return True
    return False


def scan_workflow(filepath: str, disabled_prefixes: set) -> list:
    """Scan a workflow file for references to disabled scraper families."""
    with open(filepath, 'r') as f:
        content = f.read()

    if not has_active_schedule(content):
        return []

    findings = []
    filename = os.path.basename(filepath)
    content_lower = content.lower()

    for prefix in disabled_prefixes:
        patterns = SCRAPER_FAMILY_PATTERNS.get(prefix, [prefix])
        for pattern in patterns:
            if pattern.lower() in content_lower:
                findings.append({
                    'workflow': filename,
                    'disabled_family': prefix,
                    'matched_pattern': pattern,
                })
                break  # One finding per family per workflow is enough

    return findings


def main():
    print("=" * 60)
    print("Workflow Dependency Validator")
    print("=" * 60)

    # Step 1: Load disabled scrapers
    if not os.path.exists(SCRAPER_CONFIG):
        print(f"ERROR: Config not found: {SCRAPER_CONFIG}")
        sys.exit(1)

    disabled = load_disabled_scrapers(SCRAPER_CONFIG)
    print(f"\nDisabled scraper families: {sorted(disabled) if disabled else '(none)'}")

    if not disabled:
        print("\nPASS: No disabled scrapers found.")
        sys.exit(0)

    # Step 2: Scan workflows
    if not os.path.isdir(WORKFLOWS_DIR):
        print(f"ERROR: Workflows directory not found: {WORKFLOWS_DIR}")
        sys.exit(1)

    workflow_files = sorted(
        f for f in os.listdir(WORKFLOWS_DIR) if f.endswith('.yml') or f.endswith('.yaml')
    )
    print(f"Scanning {len(workflow_files)} workflow files...\n")

    all_findings = []
    for wf in workflow_files:
        filepath = os.path.join(WORKFLOWS_DIR, wf)
        findings = scan_workflow(filepath, disabled)
        all_findings.extend(findings)

    # Step 3: Report
    if all_findings:
        print("FAIL: Workflows with active schedules reference disabled scrapers:\n")
        for f in all_findings:
            print(f"  - {f['workflow']} references disabled scraper '{f['disabled_family']}' "
                  f"(matched '{f['matched_pattern']}') but has a schedule trigger")
        print(f"\nTotal issues: {len(all_findings)}")
        print("\nFix: Comment out the schedule trigger or remove the workflow.")
        sys.exit(1)
    else:
        print("PASS: No scheduled workflows reference disabled scrapers.")
        sys.exit(0)


if __name__ == '__main__':
    main()

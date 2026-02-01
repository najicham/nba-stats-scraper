#!/usr/bin/env python3
"""
Pre-commit hook to validate Cloud Function symlinks are present.

This prevents deployment failures caused by missing shared/ module symlinks.
Added after Feb 1, 2026 incident where phase3_data_quality_check.py was missing.

Usage:
    python .pre-commit-hooks/validate_cloud_function_symlinks.py

Exit Codes:
    0 - All symlinks present
    1 - Missing symlinks detected
"""

import os
import sys
from pathlib import Path

# Cloud Functions that use shared/ symlinks
CLOUD_FUNCTIONS = [
    'auto_backfill_orchestrator',
    'daily_health_summary',
    'phase2_to_phase3',
    'phase3_to_phase4',
    'phase4_to_phase5',
    'phase5_to_phase6',
    'self_heal',
]

# Files in shared/validation/ that MUST be symlinked
# (based on what __init__.py imports)
REQUIRED_VALIDATION_SYMLINKS = [
    'phase3_data_quality_check.py',
    # Add more as needed when new files are added to shared/validation/
]

def get_repo_root() -> Path:
    """Get the repository root directory."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / '.git').exists():
            return current
        current = current.parent
    raise RuntimeError("Could not find repository root")

def check_symlinks() -> list:
    """Check for missing symlinks in Cloud Functions."""
    repo_root = get_repo_root()
    missing = []

    for func in CLOUD_FUNCTIONS:
        validation_dir = repo_root / 'orchestration' / 'cloud_functions' / func / 'shared' / 'validation'

        if not validation_dir.exists():
            # Skip if the Cloud Function doesn't have shared/validation
            continue

        for required_file in REQUIRED_VALIDATION_SYMLINKS:
            symlink_path = validation_dir / required_file
            source_path = repo_root / 'shared' / 'validation' / required_file

            # Check if source file exists
            if not source_path.exists():
                continue  # Source doesn't exist, skip

            # Check if symlink exists
            if not symlink_path.exists():
                missing.append({
                    'cloud_function': func,
                    'file': required_file,
                    'path': str(symlink_path),
                    'fix_command': f"cd {validation_dir} && ln -s ../../../../../shared/validation/{required_file} {required_file}"
                })
            elif not symlink_path.is_symlink():
                # File exists but is not a symlink (could cause issues)
                missing.append({
                    'cloud_function': func,
                    'file': required_file,
                    'path': str(symlink_path),
                    'issue': 'Not a symlink (regular file)',
                    'fix_command': f"rm {symlink_path} && cd {validation_dir} && ln -s ../../../../../shared/validation/{required_file} {required_file}"
                })

    return missing

def main():
    """Main entry point."""
    print("Checking Cloud Function symlinks...")

    missing = check_symlinks()

    if missing:
        print(f"\n{'='*60}")
        print(f" MISSING SYMLINKS DETECTED ({len(missing)} issues)")
        print(f"{'='*60}\n")

        for item in missing:
            print(f"Cloud Function: {item['cloud_function']}")
            print(f"  Missing: {item['file']}")
            print(f"  Path: {item['path']}")
            if 'issue' in item:
                print(f"  Issue: {item['issue']}")
            print(f"  Fix: {item['fix_command']}")
            print()

        print("To fix all missing symlinks, run:")
        print()
        for item in missing:
            print(f"  {item['fix_command']}")
        print()

        sys.exit(1)

    print("All Cloud Function symlinks present")
    sys.exit(0)

if __name__ == '__main__':
    main()

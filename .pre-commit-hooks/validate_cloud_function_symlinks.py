#!/usr/bin/env python3
"""
Pre-commit hook to validate Cloud Function symlinks.

Two checks:

1. REQUIRED symlinks are present. Prevents deployment failures caused by missing
   shared/ module symlinks. Added after the Feb 1, 2026 incident where
   phase3_data_quality_check.py was missing.

2. No symlink anywhere in the repo DANGLES. Added 2026-08-21: `54d08d56` deleted
   `shared/utils/bigquery_client.py` and left six vendored symlinks pointing at
   it. Nothing imported the module, so nothing failed -- but a dangling symlink
   makes gcloud's upload enumeration crash outright:

       ERROR: gcloud crashed (FileNotFoundError): [Errno 2] No such file or
       directory: './orchestration/cloud_functions/phase5_to_phase6/shared/
       utils/bigquery_client.py'

   That breaks every `gcloud builds submit` from the repo root -- which is the
   ONLY build path for the twelve scraper-backfill Cloud Run jobs, since they
   have no Cloud Build trigger. Cloud Build TRIGGERS check out from git and are
   unaffected, so this stayed invisible for three months.

Usage:
    python .pre-commit-hooks/validate_cloud_function_symlinks.py

Exit Codes:
    0 - All symlinks present and resolvable
    1 - Missing or dangling symlinks detected
"""

import os
import sys
from pathlib import Path

# Cloud Functions that use per-FILE shared/validation/ symlinks
# (CFs like `grading` and `grading-gap-detector` use a dir-level `shared/`
# symlink instead — they don't need entries here.)
CLOUD_FUNCTIONS = [
    'auto_backfill_orchestrator',
    'daily_health_summary',
    'phase3_to_phase4',
    'phase4_to_phase5',
    'phase5_to_phase6',
    'self_heal',
]

# Files in shared/validation/ that MUST be symlinked
# (based on what __init__.py imports)
REQUIRED_VALIDATION_SYMLINKS = [
    'phase3_data_quality_check.py',
    'scraper_config_validator.py',  # Added Session 117 - required by __init__.py
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

# Directories that are not part of any upload context and are noisy to walk.
DANGLING_SCAN_SKIP = {
    '.git', '.venv', 'venv', 'env', 'ENV', '__pycache__', 'node_modules',
    '.pytest_cache', '.mypy_cache', '.claude', 'models',
}


def check_dangling_symlinks() -> list:
    """Every symlink in the repo must resolve. See the module docstring."""
    repo_root = get_repo_root()
    dangling = []

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in DANGLING_SCAN_SKIP]
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            if p.is_symlink() and not p.exists():
                dangling.append({
                    'path': str(p.relative_to(repo_root)),
                    'target': os.readlink(p),
                })

    return dangling


def main():
    """Main entry point."""
    print("Checking Cloud Function symlinks...")

    missing = check_symlinks()
    dangling = check_dangling_symlinks()

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

    if dangling:
        print(f"\n{'='*60}")
        print(f" DANGLING SYMLINKS DETECTED ({len(dangling)})")
        print(f"{'='*60}\n")
        print("A symlink whose target no longer exists makes")
        print("`gcloud builds submit` crash during file enumeration, breaking")
        print("every manual source upload. Delete the link or restore the target.\n")
        for item in dangling:
            print(f"  {item['path']}")
            print(f"     -> {item['target']}  (missing)")
            print(f"     fix: git rm {item['path']}")
        print()
        sys.exit(1)

    print("All Cloud Function symlinks present and resolvable")
    sys.exit(0)

if __name__ == '__main__':
    main()

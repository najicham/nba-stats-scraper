#!/usr/bin/env python3
"""
Sync Shared Utils to Cloud Functions

Syncs utility files from the canonical shared/ directory to all cloud function
and prediction service shared/ directories.

This ensures that bug fixes and improvements in the canonical versions are
propagated to all deployable units.

Usage:
    # Dry run (show what would be synced)
    python bin/maintenance/sync_shared_utils.py --dry-run

    # Sync all files
    python bin/maintenance/sync_shared_utils.py

    # Sync specific file
    python bin/maintenance/sync_shared_utils.py --file slack_channels.py

    # Show differences only
    python bin/maintenance/sync_shared_utils.py --diff

Created: 2026-01-24
"""

import argparse
import filecmp
import os
import shutil
import sys
from pathlib import Path
from typing import List, Tuple

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Canonical source directories
CANONICAL_SOURCES = {
    'utils': PROJECT_ROOT / 'shared' / 'utils',
    'alerts': PROJECT_ROOT / 'shared' / 'alerts',
    'backfill': PROJECT_ROOT / 'shared' / 'backfill',
    'clients': PROJECT_ROOT / 'shared' / 'clients',
    'config': PROJECT_ROOT / 'shared' / 'config',
    'validation': PROJECT_ROOT / 'shared' / 'validation',
}

# Files to sync and their canonical locations
FILES_TO_SYNC = {
    # utils/
    'slack_channels.py': 'utils',
    'metrics_utils.py': 'utils',
    'storage_client.py': 'utils',
    'auth_utils.py': 'utils',
    'mlb_game_id_converter.py': 'utils',
    'game_id_converter.py': 'utils',
    'nba_team_mapper.py': 'utils',
    'mlb_team_mapper.py': 'utils',
    'travel_team_info.py': 'utils',
    'sentry_config.py': 'utils',

    # alerts/
    'rate_limiter.py': 'alerts',
    'alert_types.py': 'alerts',
    'email_alerting.py': 'alerts',
    'backfill_progress_tracker.py': 'alerts',

    # backfill/
    'checkpoint.py': 'backfill',
    'schedule_utils.py': 'backfill',

    # clients/
    'bigquery_retry.py': 'clients',
}

# Target directories that contain shared/ subdirectories
TARGET_PARENTS = [
    PROJECT_ROOT / 'predictions' / 'worker',
    PROJECT_ROOT / 'predictions' / 'coordinator',
    PROJECT_ROOT / 'orchestration' / 'cloud_functions' / 'phase2_to_phase3',
    PROJECT_ROOT / 'orchestration' / 'cloud_functions' / 'phase3_to_phase4',
    PROJECT_ROOT / 'orchestration' / 'cloud_functions' / 'phase4_to_phase5',
    PROJECT_ROOT / 'orchestration' / 'cloud_functions' / 'phase5_to_phase6',
    PROJECT_ROOT / 'orchestration' / 'cloud_functions' / 'prediction_monitoring',
    PROJECT_ROOT / 'orchestration' / 'cloud_functions' / 'daily_health_summary',
    PROJECT_ROOT / 'orchestration' / 'cloud_functions' / 'self_heal',
]


def find_file_in_target(target_parent: Path, filename: str, subdir: str) -> Path | None:
    """Find a file in the target's shared directory."""
    # Try the expected path
    target_path = target_parent / 'shared' / subdir / filename
    if target_path.exists():
        return target_path

    # Search in shared/ recursively
    shared_dir = target_parent / 'shared'
    if shared_dir.exists():
        for path in shared_dir.rglob(filename):
            return path

    return None


def compare_files(source: Path, target: Path) -> Tuple[bool, str]:
    """Compare two files and return (are_identical, diff_summary)."""
    if not target.exists():
        return False, "Target does not exist"

    if filecmp.cmp(source, target, shallow=False):
        return True, "Identical"

    # Get line counts
    with open(source) as f:
        source_lines = len(f.readlines())
    with open(target) as f:
        target_lines = len(f.readlines())

    return False, f"Different (source: {source_lines} lines, target: {target_lines} lines)"


def sync_file(source: Path, target: Path, dry_run: bool = False) -> bool:
    """Sync a single file from source to target."""
    if dry_run:
        print(f"  Would copy: {source.name} -> {target}")
        return True

    try:
        # Ensure target directory exists
        target.parent.mkdir(parents=True, exist_ok=True)

        # Copy file
        shutil.copy2(source, target)
        print(f"  Synced: {source.name} -> {target}")
        return True
    except Exception as e:
        print(f"  ERROR syncing {source.name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Sync shared utils to cloud functions')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be synced')
    parser.add_argument('--diff', action='store_true', help='Show differences only')
    parser.add_argument('--file', help='Sync only specific file')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    print("=" * 60)
    print("Shared Utils Sync")
    print("=" * 60)

    if args.dry_run:
        print("Mode: DRY RUN (no changes will be made)")
    elif args.diff:
        print("Mode: DIFF ONLY (showing differences)")
    else:
        print("Mode: SYNC (files will be copied)")
    print()

    # Filter files if specific file requested
    files_to_process = FILES_TO_SYNC
    if args.file:
        if args.file in FILES_TO_SYNC:
            files_to_process = {args.file: FILES_TO_SYNC[args.file]}
        else:
            print(f"ERROR: Unknown file '{args.file}'")
            print(f"Available files: {', '.join(FILES_TO_SYNC.keys())}")
            sys.exit(1)

    # Process each file
    total_synced = 0
    total_skipped = 0
    total_errors = 0
    total_different = 0

    for filename, subdir in files_to_process.items():
        source_path = CANONICAL_SOURCES[subdir] / filename

        if not source_path.exists():
            print(f"\nWARNING: Canonical source not found: {source_path}")
            continue

        print(f"\n{filename} (from shared/{subdir}/):")

        for target_parent in TARGET_PARENTS:
            if not target_parent.exists():
                continue

            target_path = find_file_in_target(target_parent, filename, subdir)

            if target_path is None:
                if args.verbose:
                    print(f"  Not present in: {target_parent.name}")
                continue

            # Compare files
            are_identical, diff_summary = compare_files(source_path, target_path)

            if are_identical:
                total_skipped += 1
                if args.verbose:
                    print(f"  IDENTICAL: {target_parent.name}")
            else:
                total_different += 1
                print(f"  DIFFERENT: {target_parent.name} - {diff_summary}")

                if not args.diff:
                    if sync_file(source_path, target_path, dry_run=args.dry_run):
                        total_synced += 1
                    else:
                        total_errors += 1

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Files checked: {len(files_to_process)}")
    print(f"Identical (skipped): {total_skipped}")
    print(f"Different: {total_different}")
    if not args.diff:
        print(f"Synced: {total_synced}")
    print(f"Errors: {total_errors}")

    if args.dry_run:
        print("\nTo apply changes, run without --dry-run")

    return 0 if total_errors == 0 else 1


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""
Fix old shared.utils imports to use orchestration.shared.utils for consolidated modules.

This script updates import statements in Cloud Functions to use the consolidated
utility modules from orchestration/shared/utils/ instead of the old shared/utils/ pattern.

Usage:
    python bin/maintenance/fix_consolidated_imports.py --dry-run
    python bin/maintenance/fix_consolidated_imports.py --apply
"""

import argparse
import re
from pathlib import Path
from typing import List, Tuple

# Modules that were consolidated to orchestration.shared.utils
CONSOLIDATED_MODULES = [
    'completion_tracker',
    'phase_execution_logger',
    'bigquery_utils',
    'notification_system',
    'proxy_manager',
    'player_name_resolver',
    'roster_manager',
    'nba_team_mapper',
    'email_alerting_ses',
    'schedule',  # For schedule.service imports
]

def find_files_to_fix() -> List[Path]:
    """Find all Python files with old import patterns for consolidated modules."""
    files_to_fix = []

    for py_file in Path('orchestration/cloud_functions').rglob('*.py'):
        with open(py_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check if file imports any consolidated modules with old pattern
        for module in CONSOLIDATED_MODULES:
            pattern = f"from shared\\.utils\\.{module}"
            if re.search(pattern, content):
                files_to_fix.append(py_file)
                break  # Only add once per file

    return sorted(set(files_to_fix))


def fix_imports_in_file(file_path: Path, dry_run: bool = True) -> Tuple[bool, int]:
    """
    Fix imports in a single file.

    Returns:
        (changed, num_changes): Whether file was changed and number of changes made
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        original_content = f.read()

    content = original_content
    changes = 0

    # Fix each consolidated module import
    for module in CONSOLIDATED_MODULES:
        # Pattern: from shared.utils.MODULE import X
        old_pattern = f"from shared\\.utils\\.{module}"
        new_replacement = f"from orchestration.shared.utils.{module}"

        new_content, num_replacements = re.subn(old_pattern, new_replacement, content)
        if num_replacements > 0:
            content = new_content
            changes += num_replacements

    if changes > 0 and not dry_run:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

    return changes > 0, changes


def main():
    parser = argparse.ArgumentParser(description='Fix consolidated module imports')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without changing it')
    parser.add_argument('--apply', action='store_true', help='Actually apply the changes')
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("ERROR: Must specify either --dry-run or --apply")
        return 1

    # Find files that need fixing
    print("Scanning for files with old import patterns...")
    files_to_fix = find_files_to_fix()

    if not files_to_fix:
        print("✅ No files found with old import patterns!")
        return 0

    print(f"\nFound {len(files_to_fix)} files with old import patterns\n")

    # Fix each file
    total_changes = 0
    for file_path in files_to_fix:
        changed, num_changes = fix_imports_in_file(file_path, dry_run=args.dry_run)
        if changed:
            total_changes += num_changes
            status = "Would fix" if args.dry_run else "Fixed"
            print(f"  {status}: {file_path} ({num_changes} import{'s' if num_changes > 1 else ''})")

    print(f"\n{'=' * 80}")
    if args.dry_run:
        print(f"DRY RUN: Would fix {total_changes} imports across {len(files_to_fix)} files")
        print(f"Run with --apply to make changes")
    else:
        print(f"✅ Fixed {total_changes} imports across {len(files_to_fix)} files")
    print(f"{'=' * 80}\n")

    return 0


if __name__ == '__main__':
    exit(main())

#!/usr/bin/env python3
"""
Consolidate duplicate shared/utils files across Cloud Functions.

This script identifies duplicate files across Cloud Function directories
and consolidates them into a central orchestration/shared/utils/ directory.

Eliminates ~30,000 lines of duplicate code.

Usage:
    python bin/maintenance/consolidate_cloud_function_utils.py --dry-run
    python bin/maintenance/consolidate_cloud_function_utils.py --execute

Created: 2026-01-25 (Session 20 - Task #5: Cloud Function Consolidation)
"""

import argparse
import hashlib
import os
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Cloud Functions to consolidate
CLOUD_FUNCTIONS = [
    'auto_backfill_orchestrator',
    'daily_health_summary',
    'phase2_to_phase3',
    'phase3_to_phase4',
    'phase4_to_phase5',
    'phase5_to_phase6',
    'self_heal',
   'prediction_monitoring',
]

PROJECT_ROOT = Path(__file__).parent.parent.parent
CLOUD_FUNCTIONS_DIR = PROJECT_ROOT / 'orchestration' / 'cloud_functions'
CENTRAL_SHARED_DIR = PROJECT_ROOT / 'orchestration' / 'shared' / 'utils'


def calculate_file_hash(file_path: Path) -> str:
    """Calculate MD5 hash of file contents."""
    if not file_path.exists():
        return ""

    with open(file_path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def find_duplicate_files() -> Dict[str, Dict[str, List[Path]]]:
    """
    Find all duplicate files across Cloud Functions.

    Returns:
        Dict mapping relative_path -> {hash -> [file_paths]}
    """
    # Map: relative_path -> {hash -> list of full paths}
    file_map: Dict[str, Dict[str, List[Path]]] = defaultdict(lambda: defaultdict(list))

    for cf_name in CLOUD_FUNCTIONS:
        shared_utils = CLOUD_FUNCTIONS_DIR / cf_name / 'shared' / 'utils'

        if not shared_utils.exists():
            print(f"⚠️  {cf_name}: No shared/utils directory")
            continue

        # Find all .py files
        for py_file in shared_utils.rglob('*.py'):
            # Get relative path from shared/utils/
            rel_path = py_file.relative_to(shared_utils)
            file_hash = calculate_file_hash(py_file)

            if file_hash:
                file_map[str(rel_path)][file_hash].append(py_file)

    return file_map


def identify_candidates_for_consolidation(
    file_map: Dict[str, Dict[str, List[Path]]],
    min_duplicates: int = 5
) -> List[Tuple[str, str, List[Path]]]:
    """
    Identify files that should be consolidated.

    Args:
        file_map: Output from find_duplicate_files()
        min_duplicates: Minimum number of duplicates to consider

    Returns:
        List of (relative_path, hash, file_paths) for consolidation
    """
    candidates = []

    for rel_path, hash_map in sorted(file_map.items()):
        # Skip __pycache__ and test files
        if '__pycache__' in rel_path or '/tests/' in rel_path or rel_path.startswith('tests/'):
            continue

        # Find most common hash (canonical version)
        for file_hash, file_paths in hash_map.items():
            if len(file_paths) >= min_duplicates:
                candidates.append((rel_path, file_hash, file_paths))

    return candidates


def consolidate_files(candidates: List[Tuple[str, str, List[Path]]], dry_run: bool = True):
    """
    Consolidate duplicate files to central shared directory.

    Args:
        candidates: List of (relative_path, hash, file_paths) to consolidate
        dry_run: If True, only print what would be done
    """
    print(f"\n{'='*80}")
    print(f"{'DRY RUN - ' if dry_run else ''}Consolidating {len(candidates)} files")
    print(f"{'='*80}\n")

    total_lines_saved = 0

    for rel_path, file_hash, file_paths in candidates:
        # Use first file as canonical source
        source_file = file_paths[0]

        # Determine destination in central shared
        dest_file = CENTRAL_SHARED_DIR / rel_path

        # Check if file already exists centrally
        if dest_file.exists():
            existing_hash = calculate_file_hash(dest_file)
            if existing_hash == file_hash:
                print(f"✅ {rel_path} - Already centralized (same hash)")
                continue
            else:
                print(f"⚠️  {rel_path} - Central file exists but DIFFERENT hash!")
                print(f"   Central: {existing_hash}")
                print(f"   Duplicates: {file_hash}")
                continue

        # Count lines in source
        with open(source_file, 'r') as f:
            line_count = len(f.readlines())

        duplicates_count = len(file_paths)
        lines_saved = line_count * (duplicates_count - 1)  # -1 because we keep one
        total_lines_saved += lines_saved

        print(f"📦 {rel_path}")
        print(f"   Lines: {line_count} × {duplicates_count} duplicates = {lines_saved} lines saved")
        print(f"   Source: {source_file.relative_to(PROJECT_ROOT)}")
        print(f"   Dest: {dest_file.relative_to(PROJECT_ROOT)}")

        if not dry_run:
            # Create destination directory if needed
            dest_file.parent.mkdir(parents=True, exist_ok=True)

            # Copy file to central location
            shutil.copy2(source_file, dest_file)
            print(f"   ✅ Copied to central location")

        print()

    print(f"\n{'='*80}")
    print(f"Total lines that would be saved: {total_lines_saved:,}")
    print(f"{'='*80}\n")


def generate_import_updates(candidates: List[Tuple[str, str, List[Path]]]) -> Dict[str, List[str]]:
    """
    Generate import statement updates needed for each Cloud Function.

    Returns:
        Dict mapping cloud_function_name -> list of import changes needed
    """
    import_updates = defaultdict(list)

    for rel_path, file_hash, file_paths in candidates:
        # Convert path to module name
        # e.g., "completeness_checker.py" -> "completeness_checker"
        # e.g., "player_registry/reader.py" -> "player_registry.reader"
        module_path = str(rel_path).replace('/', '.').replace('.py', '')

        old_import = f"from shared.utils.{module_path} import"
        new_import = f"from shared.utils.{module_path} import"

        for file_path in file_paths:
            # Determine which cloud function this is
            cf_name = file_path.parts[file_path.parts.index('cloud_functions') + 1]
            import_updates[cf_name].append(f"  {old_import} → {new_import}")

    return import_updates


def main():
    parser = argparse.ArgumentParser(description='Consolidate Cloud Function duplicate utilities')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without doing it')
    parser.add_argument('--execute', action='store_true', help='Actually perform the consolidation')
    parser.add_argument('--min-duplicates', type=int, default=5, help='Minimum duplicates to consolidate')
    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        print("ERROR: Must specify either --dry-run or --execute")
        return 1

    print(f"\n🔍 Scanning {len(CLOUD_FUNCTIONS)} Cloud Functions for duplicate files...\n")

    # Find all duplicate files
    file_map = find_duplicate_files()

    # Identify consolidation candidates
    candidates = identify_candidates_for_consolidation(file_map, args.min_duplicates)

    if not candidates:
        print("✅ No duplicate files found (or already consolidated)")
        return 0

    # Consolidate files
    consolidate_files(candidates, dry_run=args.dry_run)

    # Generate import update guide
    if args.dry_run:
        print("\n📝 Import Updates Needed:\n")
        import_updates = generate_import_updates(candidates)
        for cf_name, updates in sorted(import_updates.items()):
            print(f"{cf_name}:")
            for update in updates[:5]:  # Show first 5
                print(update)
            if len(updates) > 5:
                print(f"  ... and {len(updates) - 5} more")
            print()

    return 0


if __name__ == '__main__':
    exit(main())

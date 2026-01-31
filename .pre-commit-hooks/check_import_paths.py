#!/usr/bin/env python3
"""
Pre-commit hook: Check import paths in shared code.

Prevents shared code from importing from shared.utils.
Shared code should only import from shared.utils.

This prevents circular dependencies and import errors like those in Session 33/34.
"""

import re
import sys
from pathlib import Path


def check_file(filepath: Path) -> list:
    """Check a single file for incorrect import paths."""
    errors = []

    # Only check files in shared/ directory
    if not str(filepath).startswith('shared/'):
        return errors

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                # Check for: from shared.utils import ...
                # or: import orchestration.shared.utils
                patterns = [
                    r'from\s+orchestration\.shared\.',
                    r'import\s+orchestration\.shared\.'
                ]

                for pattern in patterns:
                    if re.search(pattern, line):
                        errors.append({
                            'file': str(filepath),
                            'line': line_num,
                            'content': line.strip(),
                            'pattern': pattern
                        })
    except Exception as e:
        print(f"Warning: Could not read {filepath}: {e}", file=sys.stderr)

    return errors


def main():
    """Check all Python files in shared/ directory."""
    shared_dir = Path('shared')

    if not shared_dir.exists():
        print("✅ No shared/ directory found, skipping check")
        return 0

    all_errors = []

    for py_file in shared_dir.rglob('*.py'):
        errors = check_file(py_file)
        all_errors.extend(errors)

    if all_errors:
        print("❌ Import path violations found:\n")
        print("=" * 80)
        print("Shared code must not import from orchestration.shared.*")
        print("Use 'from shared.utils.*' instead")
        print("=" * 80)
        print()

        for error in all_errors:
            print(f"File: {error['file']}:{error['line']}")
            print(f"  Found: {error['content']}")
            print()

        print("=" * 80)
        print(f"Total violations: {len(all_errors)}")
        print()
        print("Fix: Change 'from shared.utils.*' to 'from shared.utils.*'")
        print("=" * 80)
        return 1

    print("✅ All import paths valid in shared/ directory")
    return 0


if __name__ == '__main__':
    sys.exit(main())

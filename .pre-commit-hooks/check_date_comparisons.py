#!/usr/bin/env python3
"""
Pre-commit hook: Check for potentially dangerous date comparisons

Flags patterns like:
- game_date <= @game_date (should usually be <)
- cache_date <= @cache_date (should usually be <)
- ROWS BETWEEN X PRECEDING AND CURRENT ROW (includes current row)

These patterns can cause data leakage where rolling averages include
the current game's data, which shouldn't be available at prediction time.

Background:
- Session 27 (2026-01-29) discovered an L5/L10 bug caused by date comparison
- Feature store was using <= instead of < which caused data leakage
- This hook helps prevent similar bugs in future code changes

Exit codes:
- 0: No suspicious patterns found
- 1: Suspicious patterns found (warning only, doesn't block commit)

Usage:
  python .pre-commit-hooks/check_date_comparisons.py [files...]
"""

import re
import sys
from pathlib import Path
from typing import List, Tuple, Set


# Patterns that might indicate date comparison issues
SUSPICIOUS_PATTERNS = [
    # game_date <= patterns (should usually be <)
    (
        r"game_date\s*<=\s*['\"]?\{",
        "game_date <= with variable - should this be < to exclude current date?"
    ),
    (
        r"game_date\s*<=\s*@",
        "game_date <= with parameter - should this be < to exclude current date?"
    ),
    # cache_date <= patterns
    (
        r"cache_date\s*<=\s*['\"]?\{",
        "cache_date <= with variable - should this be < to exclude current date?"
    ),
    (
        r"cache_date\s*<=\s*@",
        "cache_date <= with parameter - should this be < to exclude current date?"
    ),
    # CURRENT ROW in window functions (includes current row in average)
    (
        r"ROWS\s+BETWEEN\s+\d+\s+PRECEDING\s+AND\s+CURRENT\s+ROW",
        "Window includes CURRENT ROW - verify this doesn't cause data leakage"
    ),
    (
        r"ROWS\s+BETWEEN\s+UNBOUNDED\s+PRECEDING\s+AND\s+CURRENT\s+ROW",
        "Window includes CURRENT ROW - verify this doesn't cause data leakage"
    ),
]

# Patterns that indicate the suspicious pattern is actually OK
EXCEPTION_PATTERNS = [
    r"days_rest",           # days_rest calculation needs <=
    r"last_game_date",      # Finding last game before a date
    r"WHERE.*<=.*ORDER BY", # Range query with ORDER BY is usually OK
    r"--.*<=",              # In a comment
    r"#.*<=",               # In a Python comment
    r"end_date",            # End of a date range is OK
    r"to_date",             # End of a date range
    r"max_date",            # Finding max date
]

# File patterns to check
INCLUDE_PATTERNS = [
    "*.py",
    "*.sql",
]

# File patterns to exclude
EXCLUDE_PATTERNS = [
    "*test*.py",
    "*_test.py",
    "test_*.py",
    "conftest.py",
    "*migrations*",
    ".pre-commit-hooks/*",
]


def should_check_file(file_path: Path) -> bool:
    """Determine if a file should be checked."""
    # Check if matches include patterns
    matches_include = any(
        file_path.match(pattern) for pattern in INCLUDE_PATTERNS
    )
    if not matches_include:
        return False

    # Check if matches exclude patterns
    matches_exclude = any(
        file_path.match(pattern) for pattern in EXCLUDE_PATTERNS
    )
    if matches_exclude:
        return False

    return True


def is_exception(line: str) -> bool:
    """Check if a line matches an exception pattern."""
    for pattern in EXCEPTION_PATTERNS:
        if re.search(pattern, line, re.IGNORECASE):
            return True
    return False


def check_file(file_path: Path) -> List[Tuple[int, str, str]]:
    """
    Check a file for suspicious date comparison patterns.

    Returns:
        List of (line_number, line_content, warning_message)
    """
    issues = []

    try:
        content = file_path.read_text()
    except Exception as e:
        return [(0, "", f"Could not read file: {e}")]

    lines = content.split('\n')

    for line_num, line in enumerate(lines, 1):
        # Skip empty lines and comments
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('--'):
            continue

        # Check for suspicious patterns
        for pattern, message in SUSPICIOUS_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                # Check if it's an exception
                if not is_exception(line):
                    issues.append((line_num, stripped[:100], message))
                    break  # Only report one issue per line

    return issues


def main():
    """Main entry point."""
    # Get files to check
    if len(sys.argv) > 1:
        files = [Path(f) for f in sys.argv[1:]]
    else:
        # If no files specified, check all Python and SQL files
        files = list(Path('.').rglob('*.py')) + list(Path('.').rglob('*.sql'))

    # Filter to relevant files
    files = [f for f in files if should_check_file(f)]

    all_issues = []

    for file_path in files:
        issues = check_file(file_path)
        for line_num, line_content, message in issues:
            all_issues.append({
                'file': str(file_path),
                'line': line_num,
                'content': line_content,
                'message': message,
            })

    # Report findings
    if all_issues:
        print("=" * 70)
        print("DATE COMPARISON CHECK: Potential issues found")
        print("=" * 70)
        print()
        print("The following patterns may cause data leakage (e.g., L5/L10 bug):")
        print("Review each to ensure correct date comparison is used.")
        print()

        for issue in all_issues:
            print(f"File: {issue['file']}:{issue['line']}")
            print(f"  Code: {issue['content']}")
            print(f"  Warning: {issue['message']}")
            print()

        print("=" * 70)
        print(f"Total: {len(all_issues)} potential issues")
        print()
        print("NOTE: This is a WARNING only. If these patterns are intentional,")
        print("add a comment explaining why (e.g., '# <= is correct for range end').")
        print("=" * 70)

        # Exit with warning (0) - we don't block commits, just warn
        # Change to sys.exit(1) to block commits
        return 0
    else:
        print("Date comparison check: OK (no suspicious patterns found)")
        return 0


if __name__ == "__main__":
    sys.exit(main())

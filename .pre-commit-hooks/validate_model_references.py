#!/usr/bin/env python3
"""Pre-commit hook: Detect hardcoded model system_ids in production code.

Session 333: Hardcoded system_ids like system_id = 'catboost_v9' cause
cascading failures when the champion model changes. Production code should
use get_champion_model_id() or get_best_bets_model_id() from
shared/config/model_selection.py instead.

This hook scans production directories for hardcoded catboost_v* assignments
to system_id variables, including SQL string literals and function defaults.
"""
import re
import sys
import os


# Directories to scan for hardcoded model references
SCAN_DIRS = [
    'ml/signals',
    'predictions',
    'data_processors',
    'orchestration',
]

# Paths to exclude (hardcoded IDs are legitimate here)
EXCLUDE_DIRS = [
    'bin/',
    'docs/',
    'tests/',
    'ml/experiments/',
    '.pre-commit-hooks/',
    # Prediction system classes define their own identity — legitimate
    'predictions/worker/prediction_systems/',
]

EXCLUDE_FILES = [
    'shared/config/model_selection.py',
    'shared/config/cross_model_subsets.py',
    # Worker labels V12 predictions in its main loop — legitimate system labeling
    'predictions/worker/worker.py',
]

# Pattern 1: Assignment of system_id to a catboost_v* string literal
# Matches: system_id = 'catboost_v9', SYSTEM_ID = "catboost_v12",
#          system_id: str = 'catboost_v9' (type-annotated defaults)
# Does NOT match: model_id = 'catboost_v9' (model_id is dynamic)
ASSIGNMENT_PATTERN = re.compile(
    r"""(?i)system_id\s*(?::\s*\w+\s*)?\s*=\s*['"]catboost_v""",
)

# Pattern 2: default='catboost_v*' or default="catboost_v*" (function defaults)
DEFAULT_PATTERN = re.compile(
    r"""default\s*=\s*['"]catboost_v""",
)

# Pattern 3: SQL LIKE with catboost_v pattern (dynamic queries -- EXCLUDE)
SQL_LIKE_PATTERN = re.compile(
    r"""LIKE\s+['"]catboost_v""", re.IGNORECASE,
)

# Pattern 4: .startswith('catboost_v (dynamic pattern matching -- EXCLUDE)
STARTSWITH_PATTERN = re.compile(
    r"""\.startswith\s*\(\s*['"]catboost_v""",
)


def is_comment_line(line: str) -> bool:
    """Check if line is a Python comment (ignoring leading whitespace)."""
    return line.lstrip().startswith('#')


def is_in_docstring(lines: list, line_idx: int) -> bool:
    """Heuristic check if a line is inside a docstring.

    Tracks triple-quote pairs from the start of the file up to the target line.
    """
    in_docstring = False
    for i in range(line_idx):
        stripped = lines[i].strip()
        # Count triple quotes on this line
        dq_count = stripped.count('"""')
        sq_count = stripped.count("'''")
        total = dq_count + sq_count
        if total % 2 == 1:
            in_docstring = not in_docstring
    return in_docstring


def should_exclude(filepath: str) -> bool:
    """Check if a filepath should be excluded from scanning."""
    # Normalize path separators
    normalized = filepath.replace(os.sep, '/')

    for exclude_file in EXCLUDE_FILES:
        if normalized.endswith(exclude_file) or normalized == exclude_file:
            return True

    for exclude_dir in EXCLUDE_DIRS:
        if normalized.startswith(exclude_dir) or ('/' + exclude_dir) in normalized:
            return True

    return False


def scan_file(filepath: str) -> list:
    """Scan a single file for hardcoded model references.

    Returns list of (line_number, line_text) tuples for violations.
    """
    violations = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except (UnicodeDecodeError, PermissionError, FileNotFoundError):
        return violations

    for line_num, line in enumerate(lines):
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            continue

        # Skip comment lines
        if is_comment_line(line):
            continue

        # Skip lines inside docstrings
        if is_in_docstring(lines, line_num):
            continue

        # Check if line has a catboost_v reference at all (fast path)
        if 'catboost_v' not in line.lower():
            continue

        # Exclude SQL LIKE patterns (dynamic queries)
        if SQL_LIKE_PATTERN.search(line):
            continue

        # Exclude .startswith() patterns (dynamic pattern matching)
        if STARTSWITH_PATTERN.search(line):
            continue

        # Check for assignment patterns
        if ASSIGNMENT_PATTERN.search(line):
            violations.append((line_num + 1, stripped))
            continue

        # Check for default= patterns
        if DEFAULT_PATTERN.search(line):
            violations.append((line_num + 1, stripped))
            continue

    return violations


def main():
    print("Checking for hardcoded model system_ids in production code...")
    errors = []
    checked = 0

    for scan_dir in SCAN_DIRS:
        if not os.path.exists(scan_dir):
            continue
        for root, _, files in os.walk(scan_dir):
            for f in files:
                if not f.endswith('.py'):
                    continue

                filepath = os.path.join(root, f)

                if should_exclude(filepath):
                    continue

                checked += 1
                violations = scan_file(filepath)
                for line_num, line_text in violations:
                    errors.append(f"  {filepath}:{line_num}: {line_text}")

    if errors:
        print(f"\n{'='*60}")
        print("FAILED: Found hardcoded model system_ids")
        print(f"{'='*60}")
        for err in errors:
            print(err)
        print(f"\nHardcoded system_ids break when the champion model changes.")
        print(f"Use get_champion_model_id() or get_best_bets_model_id() from")
        print(f"shared/config/model_selection.py instead.")
        print(f"\nChecked {checked} files, found {len(errors)} violations")
        return 1

    print(f"  Checked {checked} files - no hardcoded model references found")
    return 0


if __name__ == '__main__':
    sys.exit(main())

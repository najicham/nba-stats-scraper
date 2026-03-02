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
    # Display metadata — these show model info to users, not query filters
    'data_processors/publishing/model_health_exporter.py',
    'data_processors/publishing/system_performance_exporter.py',
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


def find_module_docstring_end(lines: list) -> int:
    """Find the line index where the module-level docstring ends.

    Only identifies the FIRST triple-quoted block in the file (the true module
    docstring). Returns -1 if no module docstring is found. All other
    triple-quoted strings (SQL queries, class/method docstrings) are NOT
    treated as docstrings for the purpose of this hook.
    """
    # Skip leading blank lines and comments to find the module docstring
    first_code_line = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            first_code_line = i
            break

    # Check if the first non-comment line starts a docstring
    first_stripped = lines[first_code_line].strip() if first_code_line < len(lines) else ''
    if not (first_stripped.startswith('"""') or first_stripped.startswith("'''")):
        return -1  # No module docstring

    quote_char = '"""' if first_stripped.startswith('"""') else "'''"

    # Single-line docstring: """text"""
    if first_stripped.count(quote_char) >= 2:
        return first_code_line

    # Multi-line: find closing triple-quote
    for i in range(first_code_line + 1, len(lines)):
        if quote_char in lines[i]:
            return i

    return len(lines) - 1  # Unclosed docstring — treat rest as docstring


def is_in_module_docstring(lines: list, line_idx: int) -> bool:
    """Check if a line is inside the module-level docstring only.

    Unlike the previous is_in_docstring(), this does NOT skip SQL queries
    or class/method docstrings — only the file's very first triple-quoted block.
    """
    end = find_module_docstring_end(lines)
    if end == -1:
        return False
    # Find the start (first non-blank, non-comment line)
    start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            start = i
            break
    return start <= line_idx <= end


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

        # Skip lines inside module-level docstrings only (not SQL queries)
        if is_in_module_docstring(lines, line_num):
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

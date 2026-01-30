#!/usr/bin/env python3
"""
Pre-commit hook: Validate BettingPros table queries include market_type filter.

The bettingpros_player_points_props table (despite its name) contains ALL prop types:
- points, assists, rebounds, blocks, steals, threes

Any query against this table MUST filter by market_type='points' when working with
points predictions, otherwise it will mix in other prop types.

This hook catches this common mistake before code is committed.

Session 36 Fix: Added after discovering grading bug on 2026-01-12 where predictions
were graded against wrong line values (average of all prop types instead of points-only).
"""

import re
import sys
from pathlib import Path

# Files to scan (Python code that might query BettingPros)
SCAN_PATTERNS = [
    "data_processors/**/*.py",
    "predictions/**/*.py",
    "shared/**/*.py",
    "orchestration/**/*.py",
    "ml/**/*.py",
]

# Table name patterns to check
BETTINGPROS_TABLE_PATTERNS = [
    r"bettingpros_player_points_props",
    r"bettingpros_player_props",  # Future-proofing
]

# Required filter patterns (at least one must be present)
REQUIRED_FILTERS = [
    r"market_type\s*=\s*['\"]points['\"]",
    r"market_type\s*IN\s*\([^)]*['\"]points['\"]",
]

# Exclusions (files that intentionally query all market types)
EXCLUDED_FILES = [
    "bettingpros_player_props_processor.py",  # Raw processor handles all types
    "test_",  # Test files may intentionally query all types
]


def find_python_files() -> list[Path]:
    """Find all Python files matching scan patterns."""
    import glob

    files = []
    for pattern in SCAN_PATTERNS:
        files.extend(Path(".").glob(pattern))
    return [f for f in files if f.is_file()]


def should_exclude(filepath: Path) -> bool:
    """Check if file should be excluded from validation."""
    return any(excl in str(filepath) for excl in EXCLUDED_FILES)


def extract_query_blocks(content: str) -> list[tuple[int, str]]:
    """Extract SQL query strings from Python code with line numbers."""
    queries = []

    # Match triple-quoted strings that look like SQL (contain SELECT/FROM)
    triple_quote_pattern = r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')'

    for match in re.finditer(triple_quote_pattern, content):
        query = match.group(0)
        if re.search(r'\bSELECT\b', query, re.IGNORECASE) or re.search(r'\bFROM\b', query, re.IGNORECASE):
            # Calculate line number
            line_num = content[:match.start()].count('\n') + 1
            queries.append((line_num, query))

    return queries


def check_query_for_issues(query: str) -> list[str]:
    """Check a SQL query for missing market_type filter on bettingpros table."""
    issues = []

    # Check if query references bettingpros table
    has_bettingpros = any(
        re.search(pattern, query, re.IGNORECASE)
        for pattern in BETTINGPROS_TABLE_PATTERNS
    )

    if not has_bettingpros:
        return issues

    # Check if query has required filter
    has_filter = any(
        re.search(pattern, query, re.IGNORECASE)
        for pattern in REQUIRED_FILTERS
    )

    if not has_filter:
        issues.append(
            "Query references bettingpros_player_points_props but missing "
            "market_type='points' filter. This table contains ALL prop types "
            "(points, assists, rebounds, blocks, steals, threes) - you must "
            "filter by market_type to avoid mixing data."
        )

    return issues


def validate_file(filepath: Path) -> list[tuple[int, str]]:
    """Validate a single file, returning list of (line_num, issue) tuples."""
    if should_exclude(filepath):
        return []

    try:
        content = filepath.read_text()
    except Exception as e:
        return [(0, f"Error reading file: {e}")]

    issues = []
    for line_num, query in extract_query_blocks(content):
        for issue in check_query_for_issues(query):
            issues.append((line_num, issue))

    return issues


def main():
    """Main entry point for pre-commit hook."""
    all_issues = []

    for filepath in find_python_files():
        issues = validate_file(filepath)
        for line_num, issue in issues:
            all_issues.append((filepath, line_num, issue))

    if all_issues:
        print("=" * 70)
        print("BETTINGPROS QUERY VALIDATION FAILED")
        print("=" * 70)
        print()
        for filepath, line_num, issue in all_issues:
            print(f"File: {filepath}:{line_num}")
            print(f"Issue: {issue}")
            print()
        print("Fix: Add 'AND market_type = \\'points\\'' to your query WHERE clause")
        print("=" * 70)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()

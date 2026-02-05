#!/usr/bin/env python3
"""
Pre-commit hook to validate SQL queries for common issues.

Session 123 Prevention: Check for validation query anti-patterns that can
hide data quality issues.

Checks:
1. Suspicious date equality joins (cache_date = game_date)
2. Missing partition filters on large tables
3. Missing NULL handling in aggregations
"""

import re
import sys
from pathlib import Path
from typing import List, Tuple


def check_suspicious_date_join(content: str, filepath: str) -> List[str]:
    """
    Check for suspicious date equality joins.

    Session 123 Issue: cache_date = game_date is almost always wrong
    because cache_date is the analysis date, while the cache contains
    games from BEFORE that date.
    """
    issues = []

    # Pattern 1: cache_date = game_date (Session 123 anti-pattern)
    pattern1 = r'cache_date\s*=\s*(\w+\.)?game_date'
    if re.search(pattern1, content, re.IGNORECASE):
        issues.append(
            "🚨 CRITICAL: Found 'cache_date = game_date' join. "
            "This is the Session 123 anti-pattern! "
            "Cache tables contain data FROM BEFORE cache_date, not ON cache_date. "
            "Use: game_date < cache_date"
        )

    # Pattern 2: Analysis date equality without context
    pattern2 = r'(\w+_date)\s*=\s*(\w+\.)?(\w+_date)'
    matches = re.findall(pattern2, content, re.IGNORECASE)
    if matches:
        for match in matches:
            if 'cache' in match[0].lower() or 'analysis' in match[0].lower():
                issues.append(
                    f"⚠️  WARNING: Found '{match[0]} = {match[2]}' equality join. "
                    f"Verify this is semantically correct. "
                    f"Analysis/cache dates often contain historical data, not same-day data."
                )

    return issues


def check_missing_partition_filter(content: str, filepath: str) -> List[str]:
    """Check for queries missing partition filters on large tables."""
    issues = []

    # Tables that require partition filters
    partitioned_tables = {
        'player_game_summary': 'game_date',
        'player_daily_cache': 'cache_date',
        'player_prop_predictions': 'game_date',
        'nbac_schedule': 'game_date',
        'team_game_summary': 'game_date',
    }

    for table, partition_field in partitioned_tables.items():
        if table.lower() in content.lower():
            # Check if there's a WHERE clause with the partition field
            where_pattern = rf'WHERE.*{partition_field}'
            if not re.search(where_pattern, content, re.IGNORECASE | re.DOTALL):
                issues.append(
                    f"⚠️  WARNING: Query references '{table}' but may be missing "
                    f"partition filter on '{partition_field}'. "
                    f"This can cause performance issues or query failures."
                )

    return issues


def check_missing_null_handling(content: str, filepath: str) -> List[str]:
    """Check for division or aggregations without NULL handling."""
    issues = []

    # Pattern: Division without NULLIF
    division_pattern = r'/\s*([A-Za-z_][A-Za-z0-9_\.]*)\s*(?!,)'
    if re.search(division_pattern, content):
        if 'NULLIF' not in content.upper():
            issues.append(
                "⚠️  WARNING: Found division but no NULLIF. "
                "Division by zero can cause query failures. "
                "Use: value / NULLIF(denominator, 0)"
            )

    return issues


def check_validation_query_best_practices(content: str, filepath: str) -> List[str]:
    """Check for validation query best practices."""
    issues = []

    # If this looks like a validation query
    if any(keyword in content.lower() for keyword in ['validation', 'check', 'audit', 'quality']):
        # Should have comments explaining data model
        if 'data model' not in content.lower() and 'assumption' not in content.lower():
            issues.append(
                "ℹ️  INFO: Validation queries should document data model assumptions. "
                "Add comments explaining what each date field means."
            )

        # Should explain expected results
        if 'expected:' not in content.lower():
            issues.append(
                "ℹ️  INFO: Validation queries should document expected results. "
                "Add comment like: -- Expected: Should return ~0% for clean data"
            )

    return issues


def analyze_file(filepath: Path) -> Tuple[List[str], List[str], List[str]]:
    """
    Analyze a file for SQL query issues.

    Returns:
        (critical_issues, warnings, info)
    """
    try:
        content = filepath.read_text()
    except Exception as e:
        return ([], [f"Error reading {filepath}: {e}"], [])

    # Skip if no SQL content
    if not any(keyword in content.upper() for keyword in ['SELECT', 'FROM', 'WHERE', 'JOIN']):
        return ([], [], [])

    critical = []
    warnings = []
    info = []

    # Run all checks
    for issue in check_suspicious_date_join(content, str(filepath)):
        if '🚨 CRITICAL' in issue:
            critical.append(issue)
        else:
            warnings.append(issue)

    warnings.extend(check_missing_partition_filter(content, str(filepath)))
    warnings.extend(check_missing_null_handling(content, str(filepath)))
    info.extend(check_validation_query_best_practices(content, str(filepath)))

    return (critical, warnings, info)


def main():
    """Main entry point for pre-commit hook."""
    if len(sys.argv) < 2:
        print("Usage: validate_sql_queries.py <file1> [file2 ...]")
        return 0

    total_critical = 0
    total_warnings = 0
    total_info = 0

    for filepath in sys.argv[1:]:
        path = Path(filepath)
        if not path.exists():
            continue

        critical, warnings, info = analyze_file(path)

        if critical or warnings or info:
            print(f"\n📄 {filepath}:")

            for issue in critical:
                print(f"  {issue}")
                total_critical += 1

            for issue in warnings:
                print(f"  {issue}")
                total_warnings += 1

            for issue in info:
                print(f"  {issue}")
                total_info += 1

    # Summary
    if total_critical or total_warnings or total_info:
        print(f"\n{'='*60}")
        print(f"Summary: {total_critical} critical, {total_warnings} warnings, {total_info} info")
        print(f"{'='*60}")

    # Fail if critical issues found
    if total_critical > 0:
        print("\n❌ CRITICAL issues found. Please fix before committing.")
        print("See Session 123 for examples of validation query anti-patterns.")
        return 1

    if total_warnings > 0:
        print("\n⚠️  Warnings found. Review before committing.")

    return 0


if __name__ == '__main__':
    sys.exit(main())

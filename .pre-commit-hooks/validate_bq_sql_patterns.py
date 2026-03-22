#!/usr/bin/env python3
"""
Pre-commit hook to validate BigQuery-compatible SQL patterns.

Session 478 Prevention: A multi-column IN subquery caused a 6-day grading outage.
BigQuery rejects several valid ANSI/PostgreSQL SQL patterns at query execution time
(not at Python parse time), making them invisible to syntax checks and unit tests
with mocked BQ clients.

Checks:
1. Multi-column IN subqueries: (col1, col2) IN (SELECT ...) — BQ requires EXISTS
2. PostgreSQL-style cast operator: ::type — BQ requires CAST(x AS TYPE)
3. ILIKE operator — BQ only supports LIKE (case-sensitive) or REGEXP_CONTAINS
4. EXCEPT ALL / INTERSECT ALL — BQ only supports EXCEPT DISTINCT / INTERSECT DISTINCT
"""

import re
import sys
from pathlib import Path
from typing import List, Tuple


# Pattern 1: Multi-column IN subquery
# Matches: (col1, col2) IN ( or (col1, col2, col3) IN (
# The root cause of the Session 478 6-day outage.
MULTI_COL_IN_PATTERN = re.compile(
    r'\(\s*[a-zA-Z_][a-zA-Z0-9_.]*\s*,\s*[a-zA-Z_][a-zA-Z0-9_.]+'
    r'(?:\s*,\s*[a-zA-Z_][a-zA-Z0-9_.]+)*\s*\)\s+IN\s*\(',
    re.IGNORECASE,
)

# Pattern 2: PostgreSQL-style cast ::type — rejected by BigQuery
POSTGRES_CAST_PATTERN = re.compile(r'::[a-zA-Z]+\b')

# Pattern 3: ILIKE — case-insensitive LIKE, not supported in BigQuery
ILIKE_PATTERN = re.compile(r'\bILIKE\b', re.IGNORECASE)

# Pattern 4: EXCEPT ALL or INTERSECT ALL — BQ only supports DISTINCT variants
EXCEPT_ALL_PATTERN = re.compile(r'\b(EXCEPT|INTERSECT)\s+ALL\b', re.IGNORECASE)


def extract_sql_content(content: str) -> List[Tuple[int, str]]:
    """
    Extract SQL strings from Python source files.
    Returns list of (line_number, sql_fragment) tuples.
    Handles triple-quoted strings (most common SQL pattern in this codebase).
    """
    results = []

    # Find triple-quoted strings (both ''' and \"\"\")
    triple_quote_pattern = re.compile(
        r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')',
        re.DOTALL,
    )

    for match in triple_quote_pattern.finditer(content):
        fragment = match.group(0)
        # Only check strings that look like SQL (contain FROM, SELECT, WHERE, UPDATE)
        if re.search(r'\b(SELECT|FROM|WHERE|UPDATE|INSERT|DELETE)\b', fragment, re.IGNORECASE):
            line_num = content[:match.start()].count('\n') + 1
            results.append((line_num, fragment))

    # Also check single-line strings with clear SQL keywords
    single_line_pattern = re.compile(
        r'["\']([^"\']*\b(?:SELECT|FROM|WHERE|IN\s*\()\b[^"\']*)["\']',
        re.IGNORECASE,
    )
    for match in single_line_pattern.finditer(content):
        fragment = match.group(1)
        line_num = content[:match.start()].count('\n') + 1
        results.append((line_num, fragment))

    return results


def check_file(filepath: Path) -> List[str]:
    """Check a single file for BQ-incompatible SQL patterns."""
    issues = []

    try:
        content = filepath.read_text(encoding='utf-8', errors='replace')
    except Exception as e:
        return [f"Could not read {filepath}: {e}"]

    # For .py files, extract SQL strings first
    if filepath.suffix == '.py':
        sql_fragments = extract_sql_content(content)
    elif filepath.suffix == '.sql':
        sql_fragments = [(1, content)]
    else:
        return []

    for line_num, fragment in sql_fragments:
        # Check 1: Multi-column IN subquery
        match = MULTI_COL_IN_PATTERN.search(fragment)
        if match:
            # Allow suppression with # noqa: bq-sql comment
            fragment_line = fragment[:match.start()].count('\n')
            actual_line = line_num + fragment_line
            surrounding = fragment[max(0, match.start()-40):match.end()+40].replace('\n', ' ')
            issues.append(
                f"  {filepath}:{actual_line}: Multi-column IN subquery (BigQuery unsupported)\n"
                f"    Found: ...{surrounding.strip()}...\n"
                f"    Fix: Use EXISTS (SELECT 1 FROM t WHERE t.a = outer.a AND t.b = outer.b)\n"
                f"    This pattern is valid ANSI SQL but raises 400 BadRequest in BigQuery."
            )

        # Check 2: PostgreSQL ::cast
        match = POSTGRES_CAST_PATTERN.search(fragment)
        if match:
            surrounding = fragment[max(0, match.start()-20):match.end()+20].replace('\n', ' ')
            issues.append(
                f"  {filepath}:{line_num}: PostgreSQL-style cast '::type' (BigQuery unsupported)\n"
                f"    Found: ...{surrounding.strip()}...\n"
                f"    Fix: Use CAST(expression AS TYPE) instead of expression::TYPE"
            )

        # Check 3: ILIKE
        match = ILIKE_PATTERN.search(fragment)
        if match:
            surrounding = fragment[max(0, match.start()-20):match.end()+20].replace('\n', ' ')
            issues.append(
                f"  {filepath}:{line_num}: ILIKE operator (BigQuery unsupported)\n"
                f"    Found: ...{surrounding.strip()}...\n"
                f"    Fix: Use REGEXP_CONTAINS(col, r'(?i)pattern') for case-insensitive matching"
            )

        # Check 4: EXCEPT ALL / INTERSECT ALL
        match = EXCEPT_ALL_PATTERN.search(fragment)
        if match:
            surrounding = fragment[max(0, match.start()-20):match.end()+20].replace('\n', ' ')
            issues.append(
                f"  {filepath}:{line_num}: {match.group(0).upper()} (BigQuery unsupported)\n"
                f"    Found: ...{surrounding.strip()}...\n"
                f"    Fix: Use EXCEPT DISTINCT or INTERSECT DISTINCT"
            )

    return issues


def main() -> int:
    files = [Path(f) for f in sys.argv[1:]]
    if not files:
        return 0

    all_issues = []
    for filepath in files:
        if filepath.suffix in ('.py', '.sql'):
            issues = check_file(filepath)
            all_issues.extend(issues)

    if all_issues:
        print("\n🚨 BigQuery-incompatible SQL patterns detected:")
        print("=" * 60)
        for issue in all_issues:
            print(issue)
        print()
        print("These patterns are valid in ANSI SQL / PostgreSQL but fail in BigQuery")
        print("at query execution time — invisible to Python syntax checks or mocked BQ tests.")
        print("Fix the SQL before committing. See Session 478 for background.")
        print()
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())

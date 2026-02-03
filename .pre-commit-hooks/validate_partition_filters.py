#!/usr/bin/env python3
"""
Pre-commit hook: Validate BigQuery partition filter requirements

Scans Python code for BigQuery queries that access partitioned tables
without required partition filters, which causes 400 BadRequest errors.

Prevents: Sessions 73-74 - 400 errors from missing partition filters

Exit codes:
- 0: All queries have required partition filters
- 1: Found queries missing partition filters (would cause 400 errors)
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Set


# Map tables to their partition fields and whether filter is REQUIRED
# Based on schemas/bigquery/**/*.sql with require_partition_filter=TRUE
PARTITIONED_TABLES = {
    # nba_raw tables (12 tables from Sessions 73-74)
    'nba_raw.bdl_player_boxscores': {'field': 'game_date', 'required': True},
    'nba_raw.espn_scoreboard': {'field': 'game_date', 'required': True},
    'nba_raw.espn_team_rosters': {'field': 'roster_date', 'required': True},  # Non-standard!
    'nba_raw.espn_boxscores': {'field': 'game_date', 'required': True},
    'nba_raw.bigdataball_play_by_play': {'field': 'game_date', 'required': True},
    'nba_raw.odds_api_game_lines': {'field': 'game_date', 'required': True},
    'nba_raw.bettingpros_player_points_props': {'field': 'game_date', 'required': True},
    'nba_raw.nbac_schedule': {'field': 'game_date', 'required': True},
    'nba_raw.nbac_team_boxscore': {'field': 'game_date', 'required': True},
    'nba_raw.nbac_play_by_play': {'field': 'game_date', 'required': True},
    'nba_raw.nbac_scoreboard_v2': {'field': 'game_date', 'required': True},
    'nba_raw.nbac_referee_game_assignments': {'field': 'game_date', 'required': True},
    'nba_raw.nbac_player_boxscores': {'field': 'game_date', 'required': True},
    'nba_raw.player_movement_raw': {'field': 'game_date', 'required': True},
    'nba_raw.kalshi_player_points_props': {'field': 'game_date', 'required': True},

    # nba_predictions tables
    'nba_predictions.player_prop_predictions': {'field': 'game_date', 'required': True},
    'nba_predictions.prediction_accuracy': {'field': 'game_date', 'required': True},
    'nba_predictions.system_daily_performance': {'field': 'performance_date', 'required': True},

    # nba_reference tables
    'nba_reference.source_coverage_log': {'field': 'log_date', 'required': True},

    # Orchestration tables
    'nba_orchestration.name_resolution_log': {'field': 'log_date', 'required': True},
}


def extract_sql_queries_from_file(py_file: Path) -> List[Tuple[int, str]]:
    """
    Extract SQL queries from Python file.

    Returns:
        List of (line_number, query_text) tuples
    """
    if not py_file.exists():
        return []

    content = py_file.read_text()
    queries = []

    # Pattern 1: Triple-quoted strings (common for SQL)
    # """SELECT ...""" or '''SELECT ...'''
    triple_quote_pattern = re.compile(
        r'("""|' + r"''')" + r'(.*?)' + r'\1',
        re.DOTALL | re.IGNORECASE
    )

    for match in triple_quote_pattern.finditer(content):
        query = match.group(2)
        # Only consider if it looks like SQL (contains FROM keyword)
        if re.search(r'\bFROM\b', query, re.IGNORECASE):
            line_num = content[:match.start()].count('\n') + 1
            queries.append((line_num, query))

    # Pattern 2: bq.query() calls with inline SQL
    # bq.query("SELECT ..." or bq.query("""SELECT ...""")
    # This is less common but can happen
    inline_pattern = re.compile(
        r'\.query\s*\(\s*["\']+(.*?)["\']',
        re.DOTALL | re.IGNORECASE
    )

    for match in inline_pattern.finditer(content):
        query = match.group(1)
        if re.search(r'\bFROM\b', query, re.IGNORECASE):
            line_num = content[:match.start()].count('\n') + 1
            # Avoid duplicates from triple-quoted strings
            if not any(q[0] == line_num for q in queries):
                queries.append((line_num, query))

    return queries


def parse_tables_from_query(query: str) -> Set[str]:
    """
    Extract table references from SQL query.

    Handles:
    - FROM table_name
    - JOIN table_name
    - FROM `project.dataset.table`
    - FROM dataset.table

    Returns:
        Set of table references in dataset.table format
    """
    tables = set()

    # Normalize: remove backticks, extra whitespace
    normalized = query.replace('`', '').strip()

    # Pattern: FROM|JOIN followed by table reference
    # Matches: dataset.table or project:dataset.table
    table_pattern = re.compile(
        r'\b(?:FROM|JOIN)\s+'
        r'(?:[a-z0-9_-]+[:.])?'  # Optional project
        r'([a-z0-9_]+\.[a-z0-9_]+)',  # dataset.table
        re.IGNORECASE
    )

    for match in table_pattern.finditer(normalized):
        table_ref = match.group(1).lower()
        tables.add(table_ref)

    return tables


def has_partition_filter(query: str, partition_field: str) -> bool:
    """
    Check if query has a filter on the partition field.

    Looks for patterns like:
    - WHERE game_date >= ...
    - WHERE game_date = ...
    - WHERE game_date BETWEEN ... AND ...
    - AND game_date >= ...

    Returns:
        True if partition filter is present
    """
    # Normalize query
    normalized = query.replace('\n', ' ').strip()

    # Check for partition field in WHERE clause
    # Pattern: WHERE ... partition_field ...
    where_pattern = re.compile(
        rf'\bWHERE\b.*?\b{partition_field}\b',
        re.IGNORECASE | re.DOTALL
    )

    if where_pattern.search(normalized):
        return True

    # Also check for AND clauses (partition filter might not be first condition)
    and_pattern = re.compile(
        rf'\bAND\b.*?\b{partition_field}\b',
        re.IGNORECASE | re.DOTALL
    )

    if and_pattern.search(normalized):
        return True

    return False


def validate_partition_filters_in_file(py_file: Path) -> List[str]:
    """
    Validate all SQL queries in a Python file have required partition filters.

    Returns:
        List of error messages
    """
    issues = []

    queries = extract_sql_queries_from_file(py_file)

    for line_num, query in queries:
        tables = parse_tables_from_query(query)

        for table in tables:
            if table in PARTITIONED_TABLES:
                config = PARTITIONED_TABLES[table]

                if config['required']:
                    partition_field = config['field']

                    # Check if partition filter exists
                    if not has_partition_filter(query, partition_field):
                        issues.append(
                            f"  {py_file.name}:{line_num} - Query on {table} "
                            f"missing required filter: {partition_field}"
                        )

    return issues


def validate_all_python_files() -> Tuple[bool, List[str]]:
    """
    Scan all Python files for partition filter violations.

    Returns:
        Tuple of (is_valid, messages)
    """
    messages = []
    project_root = Path(__file__).parent.parent

    # Files/directories to scan
    scan_paths = [
        project_root / "orchestration",
        project_root / "data_processors",
        project_root / "predictions",
        project_root / "scrapers",
        project_root / "backfill_jobs",
        project_root / "monitoring",
    ]

    # Collect all Python files
    python_files = []
    for scan_path in scan_paths:
        if scan_path.exists() and scan_path.is_dir():
            python_files.extend(scan_path.rglob("*.py"))

    messages.append(f"P1-1: Checking partition filter requirements...")
    messages.append(f"Scanning {len(python_files)} Python file(s)")
    messages.append(f"Monitoring {len(PARTITIONED_TABLES)} partitioned table(s)")
    messages.append("")

    # Validate each file
    all_issues = []
    files_with_issues = []

    for py_file in python_files:
        issues = validate_partition_filters_in_file(py_file)
        if issues:
            all_issues.extend(issues)
            files_with_issues.append(py_file.name)

    is_valid = len(all_issues) == 0

    if not is_valid:
        messages.append("=" * 70)
        messages.append("CRITICAL: Missing partition filters detected")
        messages.append("=" * 70)
        messages.append("")
        messages.append(f"Found {len(all_issues)} query(ies) missing required partition filters")
        messages.append(f"Affected files: {len(files_with_issues)}")
        messages.append("")
        messages.extend(all_issues)
        messages.append("")
        messages.append("These queries will FAIL with 400 BadRequest errors:")
        messages.append('  "Cannot query over table without a filter over column(s)')
        messages.append('   that can be used for partition elimination"')
        messages.append("")
        messages.append("FIX: Add partition filter to WHERE clause:")
        messages.append("  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)")
        messages.append("  OR WHERE game_date = CURRENT_DATE()")
        messages.append("")
        messages.append("Reference: Sessions 73-74 - Cleanup processor 400 errors")
    else:
        messages.append("=" * 70)
        messages.append("✅ PARTITION FILTER CHECK PASSED")
        messages.append("=" * 70)
        messages.append(f"All queries on partitioned tables have required filters")

    return is_valid, messages


def main():
    """Entry point for pre-commit hook."""
    print("=" * 70)
    print("BigQuery Partition Filter Validator (P1-1)")
    print("Prevents: Sessions 73-74 - 400 errors from missing filters")
    print("=" * 70)
    print()

    is_valid, messages = validate_all_python_files()

    for msg in messages:
        print(msg)

    if not is_valid:
        print()
        print("=" * 70)
        print("VALIDATION FAILED - Missing partition filters")
        print("=" * 70)
        sys.exit(1)
    else:
        print()
        print("=" * 70)
        print("VALIDATION PASSED")
        print("=" * 70)
        sys.exit(0)


if __name__ == "__main__":
    main()

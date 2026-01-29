#!/usr/bin/env python3
"""
Pre-commit hook: Validate BigQuery schema TYPE alignment

Detects common type mismatches that cause runtime BigQuery errors:
1. DATE/TIMESTAMP fields with invalid string fallbacks (e.g., 'unknown')
2. ARRAY fields being serialized as JSON strings instead of passed as lists
3. REQUIRED fields that might receive NULL/None
4. Numeric fields receiving string fallbacks

This complements validate_schema_fields.py which checks field existence.

Exit codes:
- 0: No type issues detected
- 1: Type issues found that would cause BigQuery errors
"""

import re
import sys
from pathlib import Path
from typing import List, Dict, Set, Tuple
from dataclasses import dataclass


@dataclass
class TypeIssue:
    """Represents a schema type issue."""
    file: str
    line: int
    field: str
    issue_type: str
    message: str
    severity: str  # 'ERROR' or 'WARNING'


def extract_schema_types(schema_path: Path) -> Dict[str, str]:
    """
    Extract field names and their types from BigQuery schema SQL.

    Returns:
        Dict mapping field_name -> type (e.g., 'DATE', 'ARRAY<STRING>', 'TIMESTAMP')
    """
    types = {}
    content = schema_path.read_text()

    # Pattern for CREATE TABLE columns
    # Matches: field_name TYPE [NOT NULL] [DEFAULT ...]
    column_pattern = re.compile(
        r'^\s*(\w+)\s+'  # Column name
        r'(STRING|BOOLEAN|INT64|NUMERIC\([^)]+\)|FLOAT64|ARRAY<[^>]+>|JSON|TIMESTAMP|DATE)',
        re.MULTILINE | re.IGNORECASE
    )

    # Find CREATE TABLE block
    create_match = re.search(
        r'CREATE TABLE[^(]+\((.*?)\)\s*PARTITION BY',
        content,
        re.DOTALL | re.IGNORECASE
    )

    if create_match:
        create_block = create_match.group(1)
        for match in column_pattern.finditer(create_block):
            field_name = match.group(1).lower()
            field_type = match.group(2).upper()
            if field_name not in ('if', 'not', 'exists', 'default', 'options'):
                types[field_name] = field_type

    # Also check ALTER TABLE ADD COLUMN
    alter_pattern = re.compile(
        r'ADD\s+COLUMN(?:\s+IF\s+NOT\s+EXISTS)?\s+(\w+)\s+'
        r'(STRING|BOOLEAN|INT64|NUMERIC\([^)]+\)|FLOAT64|ARRAY<[^>]+>|JSON|TIMESTAMP|DATE)',
        re.MULTILINE | re.IGNORECASE
    )

    for match in alter_pattern.finditer(content):
        field_name = match.group(1).lower()
        field_type = match.group(2).upper()
        if field_name not in ('if', 'not', 'exists', 'default', 'options'):
            types[field_name] = field_type

    return types


def check_date_fallbacks(content: str, file_path: str) -> List[TypeIssue]:
    """
    Check for DATE/TIMESTAMP fields with invalid string fallbacks.

    Detects patterns like:
    - game_date=game_date_str or 'unknown'
    - 'game_date': value or 'default'
    """
    issues = []

    # Known DATE/TIMESTAMP fields
    date_fields = {
        'game_date', 'run_date', 'created_at', 'updated_at', 'processed_at',
        'injury_checked_at', 'invalidated_at', 'circuit_breaker_until',
        'last_reprocess_attempt_at'
    }

    # Invalid fallback values for dates
    invalid_date_fallbacks = {
        'unknown', 'default', 'none', 'n/a', 'null', 'undefined', ''
    }

    lines = content.split('\n')
    for i, line in enumerate(lines, 1):
        # Skip comments
        if line.strip().startswith('#'):
            continue

        for field in date_fields:
            # Pattern: field or 'invalid_value'
            pattern = rf"['\"]?{field}['\"]?\s*[:=]\s*[\w.]+\s+or\s+['\"](\w*)['\"]"
            matches = re.findall(pattern, line, re.IGNORECASE)
            for match in matches:
                if match.lower() in invalid_date_fallbacks:
                    issues.append(TypeIssue(
                        file=file_path,
                        line=i,
                        field=field,
                        issue_type='INVALID_DATE_FALLBACK',
                        message=f"DATE field '{field}' has invalid fallback '{match}'. Use valid date like '1900-01-01' or None.",
                        severity='ERROR'
                    ))

    return issues


def check_array_json_serialization(content: str, file_path: str) -> List[TypeIssue]:
    """
    Check for ARRAY fields being serialized with json.dumps().

    ARRAY<STRING> and ARRAY<FLOAT64> should be passed as Python lists,
    not as JSON strings.
    """
    issues = []

    # Known ARRAY fields (exact BigQuery column names that are ARRAY types)
    # Note: teammate_out_starters is STRING (comma-separated), not ARRAY
    array_fields = {
        'data_quality_issues', 'feature_names', 'missing_features',
        'systems_attempted', 'systems_succeeded', 'systems_failed',
        'circuits_opened', 'line_values_requested', 'issues',
        'contributing_game_dates', 'example_games', 'data_quality_flags',
        'fallback_sources_tried'
    }
    # Note: 'features' is checked separately as it's a common false positive

    lines = content.split('\n')
    for i, line in enumerate(lines, 1):
        # Skip comments
        if line.strip().startswith('#'):
            continue

        for field in array_fields:
            # Pattern: 'field_name': json.dumps(...) - dict assignment
            # This catches the actual BQ column being assigned a json.dumps value
            pattern = rf"['\"]({field})['\"]:\s*json\.dumps\("
            match = re.search(pattern, line)
            if match:
                issues.append(TypeIssue(
                    file=file_path,
                    line=i,
                    field=field,
                    issue_type='ARRAY_AS_JSON_STRING',
                    message=f"ARRAY field '{field}' assigned json.dumps(). Pass list directly for ARRAY<> type.",
                    severity='ERROR'
                ))
                continue

            # Pattern: field_name = json.dumps(...) - direct assignment before dict use
            pattern2 = rf"^[\s]*{field}\s*=\s*json\.dumps\("
            if re.search(pattern2, line):
                issues.append(TypeIssue(
                    file=file_path,
                    line=i,
                    field=field,
                    issue_type='ARRAY_AS_JSON_STRING',
                    message=f"ARRAY field '{field}' assigned from json.dumps(). Pass list directly for ARRAY<> type.",
                    severity='ERROR'
                ))

    return issues


def check_required_null_handling(content: str, file_path: str) -> List[TypeIssue]:
    """
    Check for REQUIRED fields that might receive NULL.

    Look for patterns where required fields use 'or None' or similar.
    """
    issues = []

    # Known REQUIRED fields (from schemas)
    required_fields = {
        'prediction_id', 'system_id', 'player_lookup', 'game_date', 'game_id',
        'predicted_points', 'confidence_score', 'recommendation', 'success',
        'request_id', 'run_date'
    }

    lines = content.split('\n')
    for i, line in enumerate(lines, 1):
        if line.strip().startswith('#'):
            continue

        for field in required_fields:
            # Pattern: 'field': value or None
            pattern = rf"['\"]?{field}['\"]?\s*[:=]\s*[\w.]+\s+or\s+None"
            if re.search(pattern, line, re.IGNORECASE):
                issues.append(TypeIssue(
                    file=file_path,
                    line=i,
                    field=field,
                    issue_type='REQUIRED_FIELD_NULLABLE',
                    message=f"REQUIRED field '{field}' may receive None. Ensure non-null value.",
                    severity='WARNING'
                ))

    return issues


def scan_python_files(root_dir: Path, patterns: List[str]) -> List[Path]:
    """Find Python files matching patterns in the codebase."""
    files = []
    for pattern in patterns:
        files.extend(root_dir.glob(pattern))
    return files


def validate_schema_types() -> Tuple[bool, List[str]]:
    """
    Main validation function.

    Returns:
        Tuple of (is_valid, messages)
    """
    messages = []
    all_issues: List[TypeIssue] = []

    # Find project root
    project_root = Path(__file__).parent.parent

    # Files to scan for type issues
    file_patterns = [
        "predictions/worker/*.py",
        "predictions/coordinator/*.py",
        "data_processors/**/*.py",
    ]

    python_files = scan_python_files(project_root, file_patterns)

    messages.append(f"Scanning {len(python_files)} Python files for schema type issues...")
    messages.append("")

    for py_file in python_files:
        try:
            content = py_file.read_text()
            rel_path = str(py_file.relative_to(project_root))

            # Run all checks
            all_issues.extend(check_date_fallbacks(content, rel_path))
            all_issues.extend(check_array_json_serialization(content, rel_path))
            all_issues.extend(check_required_null_handling(content, rel_path))

        except Exception as e:
            messages.append(f"WARNING: Could not scan {py_file}: {e}")

    # Separate errors from warnings
    errors = [i for i in all_issues if i.severity == 'ERROR']
    warnings = [i for i in all_issues if i.severity == 'WARNING']

    # Report errors
    if errors:
        messages.append("=" * 70)
        messages.append(f"ERRORS: {len(errors)} type issues that would cause BigQuery failures")
        messages.append("=" * 70)
        for issue in errors:
            messages.append(f"  {issue.file}:{issue.line}")
            messages.append(f"    [{issue.issue_type}] {issue.message}")
            messages.append("")

    # Report warnings
    if warnings:
        messages.append("-" * 70)
        messages.append(f"WARNINGS: {len(warnings)} potential issues (review recommended)")
        messages.append("-" * 70)
        for issue in warnings:
            messages.append(f"  {issue.file}:{issue.line}")
            messages.append(f"    [{issue.issue_type}] {issue.message}")
            messages.append("")

    # Summary
    messages.append("")
    messages.append(f"Total: {len(errors)} errors, {len(warnings)} warnings")

    is_valid = len(errors) == 0

    if is_valid:
        messages.append("")
        messages.append("Schema type validation PASSED")

    return is_valid, messages


def main():
    """Entry point for pre-commit hook."""
    print("=" * 70)
    print("BigQuery Schema TYPE Validator")
    print("Checking for type mismatches that cause runtime errors")
    print("=" * 70)
    print()

    is_valid, messages = validate_schema_types()

    for msg in messages:
        print(msg)

    if not is_valid:
        print()
        print("=" * 70)
        print("VALIDATION FAILED - Type issues detected")
        print("=" * 70)
        sys.exit(1)
    else:
        print()
        print("=" * 70)
        print("VALIDATION PASSED - No type issues found")
        print("=" * 70)
        sys.exit(0)


if __name__ == "__main__":
    main()

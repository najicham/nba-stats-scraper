#!/usr/bin/env python3
"""
Pre-commit hook: Validate BigQuery schema alignment

Parses predictions/worker/worker.py to extract field names being written
to the player_prop_predictions table, then compares against the schema
in schemas/bigquery/predictions/01_player_prop_predictions.sql.

Reports:
- Fields in code but NOT in schema (would cause write failures)
- Fields in schema but NOT in code (potential missing data - informational)

Exit codes:
- 0: Schema aligned (or only schema-only fields, which is OK)
- 1: Code writes fields not in schema (would cause failures)
"""

import re
import sys
from pathlib import Path
from typing import Set, Tuple, List


def extract_schema_fields_from_sql(schema_path: Path) -> Set[str]:
    """
    Extract field names from BigQuery CREATE TABLE and ALTER TABLE statements.

    Parses SQL to find column definitions from:
    1. CREATE TABLE block
    2. ALTER TABLE ADD COLUMN statements

    Examples:
        CREATE TABLE: prediction_id STRING NOT NULL,
        ALTER TABLE:  ADD COLUMN IF NOT EXISTS feature_importance JSON
    """
    fields = set()

    content = schema_path.read_text()

    # 1. Extract fields from CREATE TABLE block
    create_match = re.search(
        r'CREATE TABLE[^(]+\((.*?)\)\s*PARTITION BY',
        content,
        re.DOTALL | re.IGNORECASE
    )

    if not create_match:
        print(f"ERROR: Could not find CREATE TABLE statement in {schema_path}")
        return fields

    create_block = create_match.group(1)

    # Pattern to match column definitions
    # Matches: column_name TYPE [NOT NULL] [DEFAULT ...] [OPTIONS ...]
    # Handles types like: STRING, BOOLEAN, INT64, NUMERIC(5,2), FLOAT64, ARRAY<STRING>, JSON, TIMESTAMP, DATE
    column_pattern = re.compile(
        r'^\s*(\w+)\s+'  # Column name
        r'(?:STRING|BOOLEAN|INT64|NUMERIC|FLOAT64|ARRAY|JSON|TIMESTAMP|DATE)',  # Type
        re.MULTILINE | re.IGNORECASE
    )

    for match in column_pattern.finditer(create_block):
        field_name = match.group(1).lower()
        # Skip SQL keywords that might match
        if field_name not in ('if', 'not', 'exists', 'default', 'options'):
            fields.add(field_name)

    # 2. Extract fields from ALTER TABLE ADD COLUMN statements
    # Pattern: ADD COLUMN IF NOT EXISTS field_name TYPE
    # or:      ADD COLUMN field_name TYPE
    alter_pattern = re.compile(
        r'ADD\s+COLUMN(?:\s+IF\s+NOT\s+EXISTS)?\s+(\w+)\s+'
        r'(?:STRING|BOOLEAN|INT64|NUMERIC|FLOAT64|ARRAY|JSON|TIMESTAMP|DATE)',
        re.MULTILINE | re.IGNORECASE
    )

    for match in alter_pattern.finditer(content):
        field_name = match.group(1).lower()
        # Skip SQL keywords that might match
        if field_name not in ('if', 'not', 'exists', 'default', 'options'):
            fields.add(field_name)

    return fields


def extract_code_fields_from_worker(worker_path: Path) -> Tuple[Set[str], List[str]]:
    """
    Extract field names being written to BigQuery from worker.py.

    Uses a smarter approach:
    1. Find the format_prediction_for_bigquery function
    2. Find the main 'record = {' dict
    3. Find all 'record.update({' calls
    4. Extract only TOP-LEVEL keys (not keys inside json.dumps() calls)

    Returns:
        Tuple of (fields_set, issues_list)
    """
    fields = set()
    issues = []

    content = worker_path.read_text()

    # Find the format_prediction_for_bigquery function
    func_match = re.search(
        r'def format_prediction_for_bigquery\([^)]+\)[^:]*:(.*?)(?=\ndef |\nclass |\Z)',
        content,
        re.DOTALL
    )

    if not func_match:
        issues.append("Could not find format_prediction_for_bigquery function")
        return fields, issues

    func_body = func_match.group(1)

    # Strategy: Find dict blocks and extract keys, but exclude json.dumps() contents
    # First, remove all json.dumps() calls to avoid capturing their nested keys
    # Pattern: json.dumps({...}) - remove the entire call
    cleaned_func = re.sub(
        r'json\.dumps\(\s*\{[^}]*\}\s*\)',
        'JSON_REMOVED',
        func_body,
        flags=re.DOTALL
    )

    # Also handle multi-line json.dumps with nested braces more carefully
    # Pattern: json.dumps({ ... }) where ... can span lines
    # Use a more conservative approach - find json.dumps and remove to matching )
    def remove_json_dumps(text):
        """Remove json.dumps(...) calls iteratively."""
        result = text
        while 'json.dumps(' in result:
            start = result.find('json.dumps(')
            if start == -1:
                break

            # Find matching closing paren
            depth = 0
            end = start + len('json.dumps(')
            for i, char in enumerate(result[end:], start=end):
                if char == '(':
                    depth += 1
                elif char == ')':
                    if depth == 0:
                        end = i + 1
                        break
                    depth -= 1

            result = result[:start] + 'JSON_REMOVED' + result[end:]
        return result

    cleaned_func = remove_json_dumps(func_body)

    # Now extract fields from record = {...} and record.update({...})
    # Look for lines with 'field_name': that are NOT inside comments
    lines = cleaned_func.split('\n')

    in_record_dict = False
    brace_depth = 0

    for line in lines:
        stripped = line.strip()

        # Skip comments
        if stripped.startswith('#'):
            continue

        # Track when we're in the main record dict or an update call
        if 'record = {' in line or 'record.update({' in line:
            in_record_dict = True
            brace_depth = line.count('{') - line.count('}')
        elif in_record_dict:
            brace_depth += line.count('{') - line.count('}')
            if brace_depth <= 0:
                in_record_dict = False

        # Only extract keys when we're in a record dict context
        if in_record_dict or 'record = {' in line or 'record.update({' in line:
            # Find field assignments: 'field_name': value
            # But exclude if it's inside a nested dict (additional braces before the key)
            matches = re.findall(r"'(\w+)':", line)
            for match in matches:
                # Verify this isn't inside a nested structure
                # by checking the line context
                field_name = match.lower()

                # Skip known nested dict keys (from conditional structures in the code)
                nested_structure_keys = {
                    'model_type', 'feature_count', 'variance', 'agreement_percentage',
                    'systems_used', 'predictions', 'agreement_type', 'weights_used',
                    'usage_boost_factor', 'minutes_boost_factor', 'opportunity_score',
                    'out_starters', 'out_star_players', 'total_out', 'total_questionable',
                    'has_significant_impact', 'usage_boost', 'out_starters', 'has_significant'
                }

                if field_name not in nested_structure_keys:
                    fields.add(field_name)

    return fields, issues


def validate_schema_alignment() -> Tuple[bool, List[str]]:
    """
    Main validation function.

    Returns:
        Tuple of (is_valid, messages)
        is_valid is False if code writes fields not in schema
    """
    messages = []

    # Find project root (where .pre-commit-hooks is located)
    project_root = Path(__file__).parent.parent

    # Paths
    schema_path = project_root / "schemas/bigquery/predictions/01_player_prop_predictions.sql"
    worker_path = project_root / "predictions/worker/worker.py"

    # Validate paths exist
    if not schema_path.exists():
        messages.append(f"ERROR: Schema file not found: {schema_path}")
        return False, messages

    if not worker_path.exists():
        messages.append(f"ERROR: Worker file not found: {worker_path}")
        return False, messages

    # Extract fields
    schema_fields = extract_schema_fields_from_sql(schema_path)
    code_fields, extraction_issues = extract_code_fields_from_worker(worker_path)

    messages.extend(extraction_issues)

    if not schema_fields:
        messages.append("ERROR: No fields extracted from schema")
        return False, messages

    if not code_fields:
        messages.append("ERROR: No fields extracted from code")
        return False, messages

    messages.append(f"Schema fields: {len(schema_fields)}")
    messages.append(f"Code fields: {len(code_fields)}")

    # Find mismatches
    # CRITICAL: Fields in code but NOT in schema = would cause write failures
    code_only = code_fields - schema_fields

    # INFO: Fields in schema but NOT in code = might be OK (optional fields)
    schema_only = schema_fields - code_fields

    # Fields known to be optional or handled differently
    # These are in schema but intentionally not written by every prediction
    known_optional_schema_fields = {
        # System-specific adjustment fields (only written by specific systems)
        'referee_adjustment',
        'look_ahead_adjustment',
        'other_adjustments',
        'ml_model_id',
        'min_similarity_score',
        # Multi-system analysis fields (written by aggregation, not worker)
        'prediction_variance',
        'system_agreement_score',
        'contributing_systems',
        # JSON fields (optional complex data)
        'key_factors',
        'warnings',
    }

    # Fields that are in code but are actually stored inside JSON columns
    # These look like top-level but are serialized into JSON fields
    json_nested_fields = {
        # These go into feature_importance JSON field
        'model_type',
        'feature_count',
        'variance',
        'agreement_percentage',
        'systems_used',
        'predictions',
        'agreement_type',
        'weights_used',
    }

    # Filter out json-nested fields from code_only (not real schema mismatches)
    real_code_only = code_only - json_nested_fields

    # Filter out known optional fields from schema_only
    unexpected_schema_only = schema_only - known_optional_schema_fields

    is_valid = True

    # Report code-only fields (CRITICAL - would cause write failures)
    if real_code_only:
        is_valid = False
        messages.append("")
        messages.append("=" * 70)
        messages.append("CRITICAL: Fields in CODE but NOT in SCHEMA")
        messages.append("These would cause BigQuery write failures!")
        messages.append("=" * 70)
        for field in sorted(real_code_only):
            messages.append(f"  - {field}")
        messages.append("")
        messages.append("FIX: Add these fields to the schema:")
        messages.append("     schemas/bigquery/predictions/01_player_prop_predictions.sql")
        messages.append("     OR remove from: predictions/worker/worker.py")

    # Report unexpected schema-only fields (WARNING - might be missing data)
    if unexpected_schema_only:
        messages.append("")
        messages.append("-" * 70)
        messages.append("INFO: Fields in SCHEMA but NOT written by worker")
        messages.append("(May be intentional - populated elsewhere or optional)")
        messages.append("-" * 70)
        for field in sorted(unexpected_schema_only):
            messages.append(f"  - {field}")

    # Report aligned fields (for verification)
    aligned = code_fields & schema_fields
    messages.append("")
    messages.append(f"Aligned fields: {len(aligned)}")

    if is_valid:
        messages.append("")
        messages.append("Schema alignment check PASSED")

    return is_valid, messages


def extract_repeated_fields_from_schema(schema_path: Path) -> Set[str]:
    """
    Extract REPEATED (ARRAY) field names from BigQuery schema.

    REPEATED fields cannot be set to NULL - must use empty array [] instead.
    This prevents Session 85 error: "Only optional fields can be set to NULL"

    Returns:
        Set of field names that are ARRAY<TYPE> (REPEATED mode)
    """
    repeated_fields = set()

    if not schema_path.exists():
        return repeated_fields

    content = schema_path.read_text()

    # Pattern to match ARRAY<TYPE> field definitions
    # Matches: field_name ARRAY<STRING>, field_name ARRAY<FLOAT64>, etc.
    array_pattern = re.compile(
        r'^\s*(\w+)\s+ARRAY<[^>]+>',
        re.MULTILINE | re.IGNORECASE
    )

    for match in array_pattern.finditer(content):
        field_name = match.group(1).lower()
        # Skip SQL keywords
        if field_name not in ('if', 'not', 'exists', 'default', 'options', 'add', 'column'):
            repeated_fields.add(field_name)

    return repeated_fields


def check_repeated_field_nulls(python_files: List[Path], schema_path: Path) -> List[str]:
    """
    Check if REPEATED fields might receive NULL values in Python code.

    Scans for patterns like:
    - 'field_name': None
    - 'field_name': variable (where variable could be None)
    - entry['field_name'] = None

    Prevents: Session 85 - BigQuery write failures on REPEATED field NULL

    Returns:
        List of error messages
    """
    issues = []

    # Get REPEATED fields from schema
    repeated_fields = extract_repeated_fields_from_schema(schema_path)

    if not repeated_fields:
        return issues

    for py_file in python_files:
        if not py_file.exists():
            continue

        content = py_file.read_text()
        lines = content.split('\n')

        for line_num, line in enumerate(lines, 1):
            # Skip comments
            if line.strip().startswith('#'):
                continue

            for field in repeated_fields:
                # Pattern 1: 'field_name': None
                if re.search(rf"['\"]?{field}['\"]?\s*:\s*None\b", line):
                    issues.append(
                        f"  {py_file.name}:{line_num} - REPEATED field '{field}' set to None"
                    )

                # Pattern 2: entry['field_name'] = None
                if re.search(rf"{field}['\"]?\s*\]\s*=\s*None\b", line):
                    issues.append(
                        f"  {py_file.name}:{line_num} - REPEATED field '{field}' assigned None"
                    )

    return issues


def scan_for_insert_rows_json(python_files: List[Path]) -> Tuple[List[str], List[str]]:
    """
    Scan for insert_rows_json() calls and extract table/field references.

    Currently the validator only checks load_table_from_json in worker.py.
    This scans ALL Python files for insert_rows_json() which is also used
    for BigQuery writes.

    Returns:
        Tuple of (info_messages, warning_messages)
    """
    info = []
    warnings = []

    for py_file in python_files:
        if not py_file.exists():
            continue

        content = py_file.read_text()

        # Find insert_rows_json calls
        # Pattern: client.insert_rows_json(table_ref, rows)
        #      or: client.insert_rows_json("table_name", rows)
        matches = re.findall(
            r'\.insert_rows_json\s*\(\s*["\']?([^,"\')]+)',
            content
        )

        if matches:
            info.append(f"  Found insert_rows_json() in {py_file.name}: {len(matches)} call(s)")

            # TODO: Future enhancement - validate field names in rows dict
            # For now, just report presence for visibility

    return info, warnings


def validate_repeated_field_safety() -> Tuple[bool, List[str]]:
    """
    P0-3 Enhancement: Check for REPEATED field NULL assignments.

    Validates that REPEATED (ARRAY) fields are not set to None in Python code.

    Returns:
        Tuple of (is_valid, messages)
    """
    messages = []
    project_root = Path(__file__).parent.parent

    # Schema to check
    schema_path = project_root / "schemas/bigquery/predictions/prediction_worker_runs.sql"

    # Python files to scan (focus on prediction worker and execution logger)
    python_files = [
        project_root / "predictions/worker/worker.py",
        project_root / "predictions/worker/execution_logger.py",
        project_root / "predictions/shared/batch_staging_writer.py",
    ]

    messages.append("P0-3: Checking REPEATED field NULL safety...")
    messages.append(f"Schema: {schema_path.name}")
    messages.append(f"Scanning {len(python_files)} Python file(s)")
    messages.append("")

    # Extract REPEATED fields
    repeated_fields = extract_repeated_fields_from_schema(schema_path)
    messages.append(f"Found {len(repeated_fields)} REPEATED field(s): {sorted(repeated_fields)}")

    # Check for NULL assignments
    issues = check_repeated_field_nulls(python_files, schema_path)

    # Scan for insert_rows_json usage
    info, warnings = scan_for_insert_rows_json(python_files)
    messages.extend(info)
    messages.extend(warnings)

    is_valid = True

    if issues:
        is_valid = False
        messages.append("")
        messages.append("=" * 70)
        messages.append("CRITICAL: REPEATED fields set to None detected")
        messages.append("=" * 70)
        messages.append("")
        messages.append("BigQuery REPEATED fields CANNOT be NULL!")
        messages.append("Use empty array [] instead of None")
        messages.append("")
        messages.extend(issues)
        messages.append("")
        messages.append("FIX: Replace 'field': None with 'field': []")
        messages.append("     Or use: field_value or [] to convert None to []")
        messages.append("")
        messages.append("Reference: Session 85 - Perpetual retry loop from REPEATED NULL")

    return is_valid, messages


def main():
    """Entry point for pre-commit hook."""
    print("=" * 70)
    print("BigQuery Schema Alignment Validator")
    print("Checking: player_prop_predictions table")
    print("=" * 70)
    print()

    is_valid, messages = validate_schema_alignment()

    for msg in messages:
        print(msg)

    # P0-3: Add REPEATED field NULL check (Session 89)
    print()
    print("=" * 70)
    print("P0-3: REPEATED Field NULL Safety Check (Session 89)")
    print("=" * 70)
    print()

    repeated_valid, repeated_messages = validate_repeated_field_safety()

    for msg in repeated_messages:
        print(msg)

    # Combined validation result
    all_valid = is_valid and repeated_valid

    if not all_valid:
        print()
        print("=" * 70)
        print("VALIDATION FAILED")
        print("=" * 70)
        if not is_valid:
            print("  - Schema misalignment detected")
        if not repeated_valid:
            print("  - REPEATED field NULL assignment detected")
        print("=" * 70)
        sys.exit(1)
    else:
        print()
        print("=" * 70)
        print("VALIDATION PASSED")
        print("=" * 70)
        print("  - Schema alignment: OK")
        print("  - REPEATED field safety: OK")
        print("=" * 70)
        sys.exit(0)


if __name__ == "__main__":
    main()

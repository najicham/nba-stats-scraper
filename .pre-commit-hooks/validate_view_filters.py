#!/usr/bin/env python3
"""
View Filter Validator (Session 209 - Layer 1 Prevention)

Ensures BigQuery views querying prediction tables have quality filter documentation.
Uses SQL annotation comments (simpler than YAML config, harder to go stale).

Pattern: Views in schemas/bigquery/predictions/views/ must have:

    -- @quality-filter: applied
    -- Filters by quality_alert_level = 'green' when require_quality_ready = TRUE

    OR

    -- @quality-filter: exempt
    -- Reason: Debug view showing all predictions including low-quality

This would have caught the Session 209 bug before it reached production.

Usage:
    python .pre-commit-hooks/validate_view_filters.py

Exit codes:
    0 - All views have valid annotations
    1 - One or more views missing or invalid annotations
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Colors for terminal output
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
NC = '\033[0m'  # No Color

# Directories to check for views that query prediction tables
VIEW_DIRECTORIES = [
    'schemas/bigquery/predictions/views/',
    'schemas/bigquery/predictions/',  # For multi-step DDL files with views
]

# Annotation pattern
ANNOTATION_PATTERN = re.compile(
    r'--\s*@quality-filter:\s*(applied|exempt)',
    re.IGNORECASE
)

# Reason pattern (required for exempt)
REASON_PATTERN = re.compile(
    r'--\s*Reason:\s*(.+)',
    re.IGNORECASE
)


def find_sql_files(repo_root: Path) -> List[Path]:
    """Find all SQL files in view directories."""
    sql_files = []

    for directory in VIEW_DIRECTORIES:
        dir_path = repo_root / directory
        if not dir_path.exists():
            continue

        # Find all .sql files
        sql_files.extend(dir_path.glob('*.sql'))

    return sorted(sql_files)


def is_view_definition(file_path: Path) -> bool:
    """
    Check if SQL file contains a VIEW definition (not just table creation).
    """
    try:
        content = file_path.read_text()
    except Exception as e:
        print(f"{YELLOW}⚠️  Warning: Could not read {file_path}: {e}{NC}")
        return False

    # Look for CREATE VIEW or CREATE OR REPLACE VIEW
    content_upper = content.upper()
    return 'CREATE VIEW' in content_upper or 'CREATE OR REPLACE VIEW' in content_upper


def file_queries_prediction_tables(file_path: Path) -> bool:
    """
    Check if SQL file creates a view that queries prediction tables.

    Returns True if file contains:
    1. CREATE VIEW or CREATE OR REPLACE VIEW, AND
    2. References to prediction tables:
       - nba_predictions.player_prop_predictions
       - nba_predictions.prediction_accuracy
       - nba_predictions.ml_feature_store_v2
       - nba_predictions.current_subset_picks
       - nba_predictions.v_dynamic_subset_performance
       - nba_predictions.v_scenario_subset_performance
    """
    # First check if this is a view definition
    if not is_view_definition(file_path):
        return False

    try:
        content = file_path.read_text()
    except Exception as e:
        print(f"{YELLOW}⚠️  Warning: Could not read {file_path}: {e}{NC}")
        return False

    # Tables that require quality filtering consideration
    prediction_tables = [
        'player_prop_predictions',
        'prediction_accuracy',
        'ml_feature_store_v2',
        'current_subset_picks',
        'v_dynamic_subset_performance',
        'v_scenario_subset_performance',
    ]

    # Check if content references any prediction tables
    content_lower = content.lower()
    for table in prediction_tables:
        if table.lower() in content_lower:
            return True

    return False


def extract_annotation(file_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract @quality-filter annotation and reason from SQL file.

    Returns:
        (annotation_type, reason) where:
        - annotation_type: 'applied', 'exempt', or None
        - reason: Exempt reason text or None
    """
    try:
        content = file_path.read_text()
    except Exception as e:
        print(f"{YELLOW}⚠️  Warning: Could not read {file_path}: {e}{NC}")
        return None, None

    # Find annotation
    annotation_match = ANNOTATION_PATTERN.search(content)
    if not annotation_match:
        return None, None

    annotation_type = annotation_match.group(1).lower()

    # If exempt, find reason
    reason = None
    if annotation_type == 'exempt':
        reason_match = REASON_PATTERN.search(content)
        if reason_match:
            reason = reason_match.group(1).strip()

    return annotation_type, reason


def validate_file(file_path: Path) -> Tuple[bool, str]:
    """
    Validate a single SQL file.

    Returns:
        (is_valid, error_message)
    """
    # Check if file queries prediction tables
    if not file_queries_prediction_tables(file_path):
        # File doesn't query prediction tables, no annotation required
        return True, ""

    # File queries prediction tables, annotation required
    annotation_type, reason = extract_annotation(file_path)

    if annotation_type is None:
        error_msg = f"""
{RED}❌ {file_path.relative_to(file_path.parents[2])}{NC}

Missing @quality-filter annotation.

Add to view header:
  {GREEN}-- @quality-filter: applied
  -- Filters by quality_alert_level = 'green' for quality-filtered subsets{NC}

OR if intentionally unfiltered:
  {YELLOW}-- @quality-filter: exempt
  -- Reason: [explain why this view should not filter]{NC}

Session 209: Quality filtering prevents contaminated metrics (12.1% vs 50.3% HR)
"""
        return False, error_msg

    # Validate annotation based on type
    if annotation_type == 'applied':
        # Applied annotation is valid
        return True, ""

    elif annotation_type == 'exempt':
        # Exempt requires reason
        if not reason:
            error_msg = f"""
{RED}❌ {file_path.relative_to(file_path.parents[2])}{NC}

@quality-filter: exempt requires a Reason.

Add after the annotation:
  {YELLOW}-- Reason: [explain why this view should not filter]{NC}

Example reasons:
  - Debug view showing all predictions including low-quality
  - Historical analysis view (pre-quality-tracking)
  - Test view for validation purposes
"""
            return False, error_msg

        return True, ""

    else:
        # Unknown annotation type
        error_msg = f"""
{RED}❌ {file_path.relative_to(file_path.parents[2])}{NC}

Invalid @quality-filter annotation: '{annotation_type}'

Valid values: 'applied' or 'exempt'
"""
        return False, error_msg


def main() -> int:
    """
    Main validation function.

    Returns:
        0 if all validations pass, 1 if any fail
    """
    # Get repository root
    repo_root = Path(__file__).parent.parent

    # Find SQL files
    sql_files = find_sql_files(repo_root)

    if not sql_files:
        print(f"{YELLOW}⚠️  No SQL files found in view directories{NC}")
        return 0

    print(f"🔍 Checking {len(sql_files)} SQL files for quality filter annotations...\n")

    # Validate each file
    errors = []
    valid_count = 0

    for file_path in sql_files:
        is_valid, error_msg = validate_file(file_path)

        if is_valid:
            valid_count += 1
        else:
            errors.append(error_msg)

    # Print results
    if errors:
        print("\n".join(errors))
        print(f"\n{RED}❌ {len(errors)} file(s) failed validation{NC}")
        print(f"{GREEN}✅ {valid_count} file(s) passed{NC}\n")
        return 1
    else:
        print(f"{GREEN}✅ All {valid_count} file(s) passed validation{NC}\n")
        return 0


if __name__ == '__main__':
    sys.exit(main())

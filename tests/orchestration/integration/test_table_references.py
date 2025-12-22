#!/usr/bin/env python3
"""
BigQuery Table Reference Validation Tests

This test ensures all BigQuery table references in orchestration code
actually exist in BigQuery. This prevents silent failures caused by
typos or incorrect table names (like the bdl_box_scores vs bdl_player_boxscores bug).

Run: pytest tests/orchestration/integration/test_table_references.py -v
"""

import os
import re
import sys
from pathlib import Path
from typing import Set, List, Tuple

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from google.cloud import bigquery


# Pattern to match BigQuery table references like:
# `nba-props-platform.nba_raw.table_name`
# `nba-props-platform.nba_orchestration.table_name`
# etc.
TABLE_REFERENCE_PATTERN = re.compile(
    r'`nba-props-platform\.(\w+)\.(\w+)`'
)

# Files to scan for table references
ORCHESTRATION_FILES = [
    'orchestration/master_controller.py',
    'orchestration/workflow_executor.py',
]

# Known tables that are views or may not exist yet (skip validation)
SKIP_VALIDATION = {
    # Views are created dynamically
    'nba_orchestration.v_recent_execution_failures',
    'nba_orchestration.v_todays_executions',
}


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent.parent


def extract_table_references(file_path: Path) -> List[Tuple[str, str, int]]:
    """
    Extract all BigQuery table references from a Python file.

    Returns:
        List of (dataset.table, full_reference, line_number) tuples
    """
    references = []

    with open(file_path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            matches = TABLE_REFERENCE_PATTERN.findall(line)
            for dataset, table in matches:
                full_ref = f"{dataset}.{table}"
                references.append((full_ref, f"`nba-props-platform.{full_ref}`", line_num))

    return references


def get_all_table_references() -> List[Tuple[str, str, str, int]]:
    """
    Scan all orchestration files for BigQuery table references.

    Returns:
        List of (dataset.table, full_reference, file_path, line_number) tuples
    """
    project_root = get_project_root()
    all_references = []

    for file_rel_path in ORCHESTRATION_FILES:
        file_path = project_root / file_rel_path
        if file_path.exists():
            refs = extract_table_references(file_path)
            for ref, full_ref, line_num in refs:
                all_references.append((ref, full_ref, file_rel_path, line_num))

    return all_references


def table_exists(client: bigquery.Client, dataset: str, table: str) -> bool:
    """Check if a BigQuery table exists."""
    try:
        table_ref = f"nba-props-platform.{dataset}.{table}"
        client.get_table(table_ref)
        return True
    except Exception:
        return False


class TestTableReferences:
    """Test suite for BigQuery table reference validation."""

    @pytest.fixture(scope="class")
    def bq_client(self):
        """Create BigQuery client for testing."""
        return bigquery.Client(project="nba-props-platform")

    @pytest.fixture(scope="class")
    def table_references(self):
        """Get all table references from orchestration code."""
        return get_all_table_references()

    def test_table_references_found(self, table_references):
        """Ensure we found table references to validate."""
        assert len(table_references) > 0, (
            "No table references found in orchestration files. "
            "Either the pattern is wrong or files are missing."
        )
        print(f"\nFound {len(table_references)} table references to validate")

    def test_all_tables_exist(self, bq_client, table_references):
        """
        Validate that all referenced BigQuery tables exist.

        This is the key test that would have caught the bdl_box_scores bug.
        """
        missing_tables = []
        validated_tables = set()

        for ref, full_ref, file_path, line_num in table_references:
            # Skip known exceptions
            if ref in SKIP_VALIDATION:
                continue

            # Skip if already validated
            if ref in validated_tables:
                continue

            dataset, table = ref.split('.')
            if not table_exists(bq_client, dataset, table):
                missing_tables.append({
                    'reference': ref,
                    'full_reference': full_ref,
                    'file': file_path,
                    'line': line_num
                })
            else:
                validated_tables.add(ref)

        # Report results
        print(f"\nValidated {len(validated_tables)} unique tables")

        if missing_tables:
            error_msg = "\n\n🚨 MISSING BIGQUERY TABLES DETECTED 🚨\n"
            error_msg += "The following table references in orchestration code do not exist:\n\n"

            for item in missing_tables:
                error_msg += f"  ❌ {item['reference']}\n"
                error_msg += f"     File: {item['file']}:{item['line']}\n"
                error_msg += f"     Reference: {item['full_reference']}\n\n"

            error_msg += "This can cause silent failures in workflow evaluation.\n"
            error_msg += "Please verify the table names are correct.\n"

            pytest.fail(error_msg)

    def test_no_typos_in_common_tables(self, bq_client):
        """
        Explicitly test commonly mistyped table names.

        This test documents known table name patterns to prevent
        future typos like bdl_box_scores vs bdl_player_boxscores.
        """
        # Tables that actually exist (correct names)
        correct_tables = [
            ('nba_raw', 'bdl_player_boxscores'),  # NOT bdl_box_scores
            ('nba_raw', 'bigdataball_play_by_play'),
            ('nba_raw', 'nbac_injury_report'),
            ('nba_orchestration', 'scraper_execution_log'),
            ('nba_orchestration', 'workflow_decisions'),
            ('nba_orchestration', 'workflow_executions'),
        ]

        for dataset, table in correct_tables:
            assert table_exists(bq_client, dataset, table), (
                f"Expected table {dataset}.{table} does not exist. "
                "This may indicate the table was renamed or deleted."
            )

        # Tables that should NOT exist (common typos)
        typo_tables = [
            ('nba_raw', 'bdl_box_scores'),  # Common typo - correct is bdl_player_boxscores
            ('nba_raw', 'bdl_boxscores'),   # Another typo variant
        ]

        for dataset, table in typo_tables:
            if table_exists(bq_client, dataset, table):
                pytest.fail(
                    f"Table {dataset}.{table} exists but was expected to be a typo. "
                    "If this is intentional, remove it from the typo_tables list."
                )


class TestTableReferenceExtraction:
    """Unit tests for the table reference extraction logic."""

    def test_pattern_matches_standard_reference(self):
        """Test that pattern matches standard BigQuery references."""
        line = "FROM `nba-props-platform.nba_raw.bdl_player_boxscores`"
        matches = TABLE_REFERENCE_PATTERN.findall(line)
        assert matches == [('nba_raw', 'bdl_player_boxscores')]

    def test_pattern_matches_multiple_references(self):
        """Test pattern matches multiple references on same line."""
        line = "JOIN `nba-props-platform.nba_raw.table1` ON `nba-props-platform.nba_raw.table2`"
        matches = TABLE_REFERENCE_PATTERN.findall(line)
        assert len(matches) == 2
        assert ('nba_raw', 'table1') in matches
        assert ('nba_raw', 'table2') in matches

    def test_pattern_matches_orchestration_tables(self):
        """Test pattern matches orchestration dataset tables."""
        line = "INSERT INTO `nba-props-platform.nba_orchestration.workflow_decisions`"
        matches = TABLE_REFERENCE_PATTERN.findall(line)
        assert matches == [('nba_orchestration', 'workflow_decisions')]

    def test_extraction_from_sample_code(self):
        """Test extraction from realistic code sample."""
        sample_code = '''
        query = f"""
            SELECT DISTINCT game_id
            FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
            WHERE game_date = '{yesterday}'
        """
        '''

        # Create a temp file to test extraction
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(sample_code)
            temp_path = Path(f.name)

        try:
            refs = extract_table_references(temp_path)
            assert len(refs) == 1
            assert refs[0][0] == 'nba_raw.bdl_player_boxscores'
        finally:
            temp_path.unlink()


if __name__ == '__main__':
    # Allow running directly for quick validation
    print("BigQuery Table Reference Validation")
    print("=" * 50)

    refs = get_all_table_references()
    print(f"\nFound {len(refs)} table references:\n")

    # Group by file
    by_file = {}
    for ref, full_ref, file_path, line_num in refs:
        if file_path not in by_file:
            by_file[file_path] = []
        by_file[file_path].append((ref, line_num))

    for file_path, file_refs in by_file.items():
        print(f"\n{file_path}:")
        unique_refs = sorted(set(r[0] for r in file_refs))
        for ref in unique_refs:
            lines = [r[1] for r in file_refs if r[0] == ref]
            print(f"  - {ref} (lines: {', '.join(map(str, lines))})")

    print("\n" + "=" * 50)
    print("Run 'pytest tests/orchestration/integration/test_table_references.py -v' for full validation")

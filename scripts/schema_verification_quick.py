#!/usr/bin/env python3
"""Quick Schema Verification - matches table names only"""
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set
from collections import defaultdict
import re

PROJECT_ID = "nba-props-platform"
DATASETS = ["nba_analytics", "nba_precompute", "nba_predictions", "nba_reference", "nba_raw", "nba_orchestration"]
SCHEMA_DIR = Path("schemas/bigquery")


def get_deployed_table_names() -> Dict[str, Set[str]]:
    """Get table names from BigQuery (fast, no schema details)"""
    print("🔍 Getting deployed table names...")
    deployed = {}

    for dataset in DATASETS:
        try:
            cmd = ["bq", "ls", "--format=json", f"{PROJECT_ID}:{dataset}"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
            tables = json.loads(result.stdout.strip())

            # Only get table IDs for real tables (not views)
            table_names = {
                t["tableReference"]["tableId"]
                for t in tables
                if t.get("type") == "TABLE"
            }
            deployed[dataset] = table_names
            print(f"  ✓ {dataset}: {len(table_names)} tables")
        except Exception as e:
            print(f"  ✗ {dataset}: Error - {e}")
            deployed[dataset] = set()

    return deployed


def extract_table_names_from_schema(file_path: Path) -> Set[str]:
    """Extract table names from schema SQL file"""
    try:
        content = file_path.read_text()
        table_names = set()

        # Patterns for CREATE TABLE [IF NOT EXISTS] `project.dataset.table`
        patterns = [
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`[^`]+\.([^`]+)`',
            r'CREATE\s+OR\s+REPLACE\s+TABLE\s+`[^`]+\.([^`]+)`',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            table_names.update(matches)

        return table_names
    except Exception as e:
        return set()


def get_schema_table_mappings() -> Dict[str, Set[str]]:
    """Map dataset -> set of table names defined in schema files"""
    print("\n📂 Analyzing schema files...")
    schema_tables = defaultdict(set)

    if not SCHEMA_DIR.exists():
        print(f"  ✗ Schema directory not found: {SCHEMA_DIR}")
        return dict(schema_tables)

    # Organize files by dataset
    dataset_map = {
        "analytics": "nba_analytics",
        "nba_analytics": "nba_analytics",
        "precompute": "nba_precompute",
        "nba_precompute": "nba_precompute",
        "predictions": "nba_predictions",
        "nba_predictions": "nba_predictions",
        "nba_reference": "nba_reference",
        "raw": "nba_raw",
        "nba_raw": "nba_raw",
        "orchestration": "nba_orchestration",
        "nba_orchestration": "nba_orchestration",
    }

    for sql_file in SCHEMA_DIR.glob("**/*.sql"):
        # Determine dataset from path
        relative = sql_file.relative_to(SCHEMA_DIR)
        first_dir = relative.parts[0] if relative.parts else None
        dataset = dataset_map.get(first_dir)

        if dataset:
            tables = extract_table_names_from_schema(sql_file)
            schema_tables[dataset].update(tables)

    for dataset, tables in sorted(schema_tables.items()):
        print(f"  ✓ {dataset}: {len(tables)} tables in schema files")

    return dict(schema_tables)


def main():
    print("🚀 Quick Schema Verification\n")

    deployed = get_deployed_table_names()
    schema_tables = get_schema_table_mappings()

    print("\n" + "="*80)
    print("SCHEMA COVERAGE ANALYSIS")
    print("="*80)

    total_deployed = sum(len(tables) for tables in deployed.values())
    total_with_schema = 0
    total_missing = 0

    missing_by_dataset = {}

    for dataset in DATASETS:
        deployed_tables = deployed.get(dataset, set())
        schema_table_set = schema_tables.get(dataset, set())

        with_schema = deployed_tables & schema_table_set
        missing = deployed_tables - schema_table_set

        total_with_schema += len(with_schema)
        total_missing += len(missing)

        if missing:
            missing_by_dataset[dataset] = sorted(missing)

        coverage = (len(with_schema) / len(deployed_tables) * 100) if deployed_tables else 100
        status = "✅" if coverage == 100 else "⚠️ "

        print(f"\n{status} {dataset}:")
        print(f"   Deployed: {len(deployed_tables)} | With Schema: {len(with_schema)} | Missing: {len(missing)} | Coverage: {coverage:.0f}%")

        if missing and len(missing) <= 10:
            print(f"   Missing schemas: {', '.join(sorted(missing))}")
        elif missing:
            print(f"   Missing schemas: {', '.join(sorted(list(missing)[:5]))}... (+{len(missing)-5} more)")

    print("\n" + "="*80)
    print(f"\n📊 SUMMARY:")
    print(f"   Total Tables: {total_deployed}")
    print(f"   With Schema:  {total_with_schema}")
    print(f"   Missing:      {total_missing}")

    coverage = (total_with_schema / total_deployed * 100) if total_deployed else 100
    print(f"   Coverage:     {coverage:.1f}%")

    if missing_by_dataset:
        print(f"\n❌ TABLES MISSING SCHEMA FILES:")
        for dataset, tables in sorted(missing_by_dataset.items()):
            print(f"\n   {dataset} ({len(tables)} tables):")
            for table in tables:
                print(f"      - {table}")

    print("\n" + "="*80)

    if total_missing == 0:
        print("\n✅ Perfect! All deployed tables have schema files.")
        return 0
    else:
        print(f"\n⚠️  Action needed: {total_missing} tables missing schema files")
        return 1


if __name__ == "__main__":
    sys.exit(main())

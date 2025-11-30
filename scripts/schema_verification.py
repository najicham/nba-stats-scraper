#!/usr/bin/env python3
"""
Schema Verification Script
Compares deployed BigQuery tables with schema files to identify gaps
"""
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict

# Project configuration
PROJECT_ID = "nba-props-platform"
DATASETS = [
    "nba_analytics",
    "nba_precompute",
    "nba_predictions",
    "nba_reference",
    "nba_raw",
    "nba_orchestration"
]
SCHEMA_DIR = Path("schemas/bigquery")


def run_command(cmd: List[str], timeout: int = 30) -> str:
    """Run a shell command and return output"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {' '.join(cmd)}")
        print(f"Error: {e.stderr}")
        return ""
    except subprocess.TimeoutExpired:
        print(f"Command timed out: {' '.join(cmd)}")
        return ""


def get_deployed_tables() -> Dict[str, List[Dict]]:
    """Get all deployed tables from BigQuery"""
    print("🔍 Inventorying deployed tables...")
    deployed = {}

    for dataset in DATASETS:
        print(f"  - Checking {dataset}...")
        cmd = ["bq", "ls", "--format=json", f"{PROJECT_ID}:{dataset}"]
        output = run_command(cmd, timeout=15)

        if output:
            try:
                tables = json.loads(output)
                deployed[dataset] = []

                for table in tables:
                    table_id = table["tableReference"]["tableId"]
                    table_type = table.get("type", "UNKNOWN")

                    # Get detailed schema for tables (not views)
                    field_count = 0
                    if table_type == "TABLE":
                        schema_cmd = ["bq", "show", "--schema", "--format=prettyjson",
                                     f"{PROJECT_ID}:{dataset}.{table_id}"]
                        schema_output = run_command(schema_cmd, timeout=10)
                        if schema_output:
                            try:
                                fields = json.loads(schema_output)
                                field_count = len(fields)
                            except json.JSONDecodeError:
                                pass

                    deployed[dataset].append({
                        "table_id": table_id,
                        "type": table_type,
                        "field_count": field_count,
                        "has_partitioning": "timePartitioning" in table or "rangePartitioning" in table,
                        "has_clustering": "clustering" in table
                    })

                print(f"    ✓ Found {len(tables)} tables ({len([t for t in tables if t.get('type') == 'TABLE'])} tables, {len([t for t in tables if t.get('type') == 'VIEW'])} views)")
            except json.JSONDecodeError:
                print(f"    ✗ Failed to parse JSON for {dataset}")
                deployed[dataset] = []
        else:
            deployed[dataset] = []

    return deployed


def find_schema_files() -> Dict[str, List[Path]]:
    """Find all schema SQL files organized by dataset"""
    print("\n📂 Inventorying schema files...")
    schema_files = defaultdict(list)

    if not SCHEMA_DIR.exists():
        print(f"  ✗ Schema directory not found: {SCHEMA_DIR}")
        return schema_files

    # Find all .sql files
    all_files = list(SCHEMA_DIR.glob("**/*.sql"))
    print(f"  ✓ Found {len(all_files)} schema files")

    # Organize by dataset based on directory structure
    for file_path in all_files:
        relative = file_path.relative_to(SCHEMA_DIR)
        parts = relative.parts

        # Try to determine which dataset this belongs to
        dataset = None
        if len(parts) > 0:
            first_part = parts[0]
            # Map directory names to datasets
            if first_part in ["analytics", "nba_analytics"]:
                dataset = "nba_analytics"
            elif first_part in ["precompute", "nba_precompute"]:
                dataset = "nba_precompute"
            elif first_part in ["predictions", "nba_predictions"]:
                dataset = "nba_predictions"
            elif first_part in ["nba_reference"]:
                dataset = "nba_reference"
            elif first_part in ["raw", "nba_raw"]:
                dataset = "nba_raw"
            elif first_part in ["orchestration", "nba_orchestration"]:
                dataset = "nba_orchestration"
            elif first_part in ["static", "nba_static"]:
                dataset = "nba_static"
            elif first_part in ["processing"]:
                dataset = "processing"
            elif first_part in ["validation"]:
                dataset = "validation"
            elif first_part in ["monitoring"]:
                dataset = "monitoring"

        if dataset:
            schema_files[dataset].append(file_path)
        else:
            schema_files["_other"].append(file_path)

    # Print summary
    for dataset, files in sorted(schema_files.items()):
        print(f"  - {dataset}: {len(files)} files")

    return dict(schema_files)


def extract_table_names_from_schema(file_path: Path) -> List[str]:
    """Extract table names from a schema SQL file"""
    table_names = []
    try:
        content = file_path.read_text()

        # Look for CREATE TABLE statements
        import re
        # Pattern: CREATE TABLE [IF NOT EXISTS] `project.dataset.table_name` or CREATE TABLE table_name
        patterns = [
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`[^`]+\.([^`]+)`',  # CREATE TABLE [IF NOT EXISTS] `project.dataset.table`
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_]+)\s*\(',  # CREATE TABLE [IF NOT EXISTS] table_name (
            r'CREATE\s+OR\s+REPLACE\s+TABLE\s+`[^`]+\.([^`]+)`',
            r'CREATE\s+OR\s+REPLACE\s+TABLE\s+([a-zA-Z0-9_]+)\s*\(',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            table_names.extend(matches)

        # Also look for VIEW statements
        view_patterns = [
            r'CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?`[^`]+\.([^`]+)`',
            r'CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_]+)\s+AS',
        ]

        for pattern in view_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            table_names.extend(matches)

    except Exception as e:
        print(f"  ✗ Error reading {file_path}: {e}")

    return list(set(table_names))  # Remove duplicates


def create_gap_analysis(deployed: Dict[str, List[Dict]], schema_files: Dict[str, List[Path]]) -> Dict:
    """Compare deployed tables with schema files"""
    print("\n📊 Creating gap analysis...")

    analysis = {
        "with_schema": [],
        "missing_schema": [],
        "extra_schema": [],
        "schema_file_summary": {},
        "totals": {
            "deployed_tables": 0,
            "deployed_views": 0,
            "schema_files": 0,
            "tables_with_schema": 0,
            "tables_missing_schema": 0,
            "extra_schema_files": 0
        }
    }

    # Build a map of all tables defined in schema files
    schema_table_map = {}  # table_name -> file_path
    for dataset, files in schema_files.items():
        for file_path in files:
            tables = extract_table_names_from_schema(file_path)
            for table in tables:
                if table not in schema_table_map:
                    schema_table_map[table] = []
                schema_table_map[table].append(str(file_path))

    analysis["schema_file_summary"] = {
        table: files for table, files in schema_table_map.items()
    }

    # Check each deployed table
    for dataset, tables in deployed.items():
        for table in tables:
            table_id = table["table_id"]
            table_type = table["type"]

            analysis["totals"]["deployed_tables"] += 1 if table_type == "TABLE" else 0
            analysis["totals"]["deployed_views"] += 1 if table_type == "VIEW" else 0

            # Check if this table has a schema file
            if table_id in schema_table_map:
                analysis["with_schema"].append({
                    "dataset": dataset,
                    "table": table_id,
                    "type": table_type,
                    "field_count": table["field_count"],
                    "schema_files": schema_table_map[table_id]
                })
                analysis["totals"]["tables_with_schema"] += 1
            else:
                # Only flag missing schema for actual tables, not views (views can be dynamic)
                if table_type == "TABLE":
                    analysis["missing_schema"].append({
                        "dataset": dataset,
                        "table": table_id,
                        "type": table_type,
                        "field_count": table["field_count"],
                        "has_partitioning": table["has_partitioning"],
                        "has_clustering": table["has_clustering"]
                    })
                    analysis["totals"]["tables_missing_schema"] += 1

    # Find schema files for tables that don't exist
    deployed_table_names = set()
    for dataset, tables in deployed.items():
        for table in tables:
            deployed_table_names.add(table["table_id"])

    for table_name, files in schema_table_map.items():
        if table_name not in deployed_table_names:
            # Check if it's a dataset definition or other special file
            if not table_name.startswith("nba_") and table_name not in ["datasets", "validation_results"]:
                analysis["extra_schema"].append({
                    "table": table_name,
                    "schema_files": files
                })
                analysis["totals"]["extra_schema_files"] += 1

    analysis["totals"]["schema_files"] = sum(len(files) for files in schema_files.values())

    return analysis


def print_gap_analysis(analysis: Dict):
    """Print the gap analysis results"""
    print("\n" + "="*80)
    print("SCHEMA VERIFICATION REPORT")
    print("="*80)

    totals = analysis["totals"]
    print(f"\n📈 TOTALS:")
    print(f"  • Deployed Tables:          {totals['deployed_tables']}")
    print(f"  • Deployed Views:           {totals['deployed_views']}")
    print(f"  • Schema Files:             {totals['schema_files']}")
    print(f"  • Tables with Schema:       {totals['tables_with_schema']} ✓")
    print(f"  • Tables Missing Schema:    {totals['tables_missing_schema']} ⚠️")
    print(f"  • Extra Schema Files:       {totals['extra_schema_files']} ⚠️")

    coverage = (totals['tables_with_schema'] / totals['deployed_tables'] * 100) if totals['deployed_tables'] > 0 else 0
    print(f"\n  Coverage: {coverage:.1f}%")

    if analysis["missing_schema"]:
        print(f"\n❌ TABLES MISSING SCHEMA FILES ({len(analysis['missing_schema'])}):")
        print(f"{'Dataset':<20} {'Table':<40} {'Fields':<10} {'Part':<5} {'Clust':<5}")
        print("-"*80)
        for item in sorted(analysis["missing_schema"], key=lambda x: (x["dataset"], x["table"])):
            print(f"{item['dataset']:<20} {item['table']:<40} {item['field_count']:<10} "
                  f"{'✓' if item['has_partitioning'] else '':<5} "
                  f"{'✓' if item['has_clustering'] else '':<5}")

    if analysis["extra_schema"]:
        print(f"\n⚠️  SCHEMA FILES WITHOUT DEPLOYED TABLES ({len(analysis['extra_schema'])}):")
        for item in sorted(analysis["extra_schema"], key=lambda x: x["table"]):
            print(f"  • {item['table']}")
            for file in item['schema_files']:
                print(f"    - {file}")

    print("\n" + "="*80)

    # Write detailed JSON report
    report_path = Path("schema_verification_report.json")
    with open(report_path, "w") as f:
        json.dump(analysis, f, indent=2)
    print(f"\n📄 Detailed report saved to: {report_path}")


def main():
    """Main execution function"""
    print("🚀 Starting Schema Verification\n")

    # Phase 1: Inventory
    deployed = get_deployed_tables()
    schema_files = find_schema_files()

    # Phase 2: Gap Analysis
    analysis = create_gap_analysis(deployed, schema_files)

    # Phase 3: Report
    print_gap_analysis(analysis)

    # Exit with error code if there are missing schemas
    if analysis["totals"]["tables_missing_schema"] > 0:
        print("\n⚠️  Action Required: Some tables are missing schema files")
        return 1
    else:
        print("\n✅ All tables have schema files!")
        return 0


if __name__ == "__main__":
    sys.exit(main())

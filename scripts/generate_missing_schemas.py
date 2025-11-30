#!/usr/bin/env python3
"""
Generate schema SQL files for tables missing schemas
"""
import json
import subprocess
from pathlib import Path
from typing import Dict, List

PROJECT_ID = "nba-props-platform"
SCHEMA_BASE = Path("schemas/bigquery")

# Tables that need schema files (excluding temp/test tables)
TABLES_TO_GENERATE = [
    ("nba_precompute", "daily_game_context"),
    ("nba_precompute", "daily_opponent_defense_zones"),
    ("nba_predictions", "current_ml_predictions"),
    ("nba_predictions", "prediction_accuracy"),
    ("nba_reference", "player_name_mappings"),
]


def get_table_schema(dataset: str, table: str) -> Dict:
    """Get table schema from BigQuery"""
    try:
        cmd = ["bq", "show", "--format=prettyjson", f"{PROJECT_ID}:{dataset}.{table}"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
        return json.loads(result.stdout.strip())
    except Exception as e:
        print(f"  ✗ Error getting schema for {dataset}.{table}: {e}")
        return {}


def type_to_sql(field: Dict) -> str:
    """Convert BigQuery field type to SQL type"""
    field_type = field["type"]
    mode = field.get("mode", "NULLABLE")

    # Handle NUMERIC with precision/scale
    if field_type == "NUMERIC":
        precision = field.get("precision", "38")
        scale = field.get("scale", "9")
        sql_type = f"NUMERIC({precision}, {scale})"
    elif field_type == "BIGNUMERIC":
        precision = field.get("precision", "76")
        scale = field.get("scale", "38")
        sql_type = f"BIGNUMERIC({precision}, {scale})"
    elif field_type == "STRING":
        sql_type = "STRING"
    elif field_type == "INT64":
        sql_type = "INT64"
    elif field_type == "FLOAT64":
        sql_type = "FLOAT64"
    elif field_type == "BOOL":
        sql_type = "BOOL"
    elif field_type == "BOOLEAN":
        sql_type = "BOOLEAN"
    elif field_type == "BYTES":
        sql_type = "BYTES"
    elif field_type == "DATE":
        sql_type = "DATE"
    elif field_type == "DATETIME":
        sql_type = "DATETIME"
    elif field_type == "TIME":
        sql_type = "TIME"
    elif field_type == "TIMESTAMP":
        sql_type = "TIMESTAMP"
    elif field_type == "GEOGRAPHY":
        sql_type = "GEOGRAPHY"
    elif field_type == "JSON":
        sql_type = "JSON"
    elif field_type == "RECORD":
        sql_type = "STRUCT<...>"  # Simplified for now
    else:
        sql_type = field_type

    # Add mode
    if mode == "REQUIRED":
        sql_type += " NOT NULL"
    elif mode == "REPEATED":
        sql_type = f"ARRAY<{sql_type}>"

    return sql_type


def generate_create_table_sql(dataset: str, table: str, schema_info: Dict) -> str:
    """Generate CREATE TABLE SQL statement"""
    fields = schema_info.get("schema", {}).get("fields", [])
    clustering = schema_info.get("clustering", {}).get("fields", [])
    partition_def = schema_info.get("timePartitioning") or schema_info.get("partitionDefinition")

    # Build field definitions
    field_lines = []
    for field in fields:
        field_name = field["name"]
        field_type = type_to_sql(field)
        description = field.get("description", "")

        if description:
            field_lines.append(f"  {field_name} {field_type},  -- {description}")
        else:
            field_lines.append(f"  {field_name} {field_type},")

    # Remove trailing comma from last field
    if field_lines:
        field_lines[-1] = field_lines[-1].rstrip(",")

    fields_sql = "\n".join(field_lines)

    # Build partitioning clause
    partition_clause = ""
    if partition_def:
        if "partitionedColumn" in partition_def:
            # New-style partitioning
            partition_field = partition_def["partitionedColumn"][0]["field"]
            partition_clause = f"\nPARTITION BY DATE({partition_field})"
        elif "field" in partition_def:
            # Time partitioning
            partition_field = partition_def["field"]
            partition_type = partition_def.get("type", "DAY")
            partition_clause = f"\nPARTITION BY {partition_type}({partition_field})"

            # Add expiration if set
            if "expirationMs" in partition_def:
                expiration_days = int(partition_def["expirationMs"]) / (1000 * 60 * 60 * 24)
                partition_clause += f"\nOPTIONS(partition_expiration_days={int(expiration_days)})"

    # Build clustering clause
    cluster_clause = ""
    if clustering:
        cluster_fields = ", ".join(clustering)
        cluster_clause = f"\nCLUSTER BY {cluster_fields}"

    # Generate full SQL
    sql = f"""-- ============================================================================
-- {table.replace('_', ' ').title()} Table Schema
-- ============================================================================
-- Dataset: {dataset}
-- Table: {table}
-- Auto-generated from deployed BigQuery table
-- ============================================================================

CREATE TABLE IF NOT EXISTS `{PROJECT_ID}.{dataset}.{table}` (
{fields_sql}
){partition_clause}{cluster_clause};
"""
    return sql


def generate_schema_file(dataset: str, table: str):
    """Generate schema file for a table"""
    print(f"\n📝 Generating schema for {dataset}.{table}...")

    # Get schema from BigQuery
    schema_info = get_table_schema(dataset, table)
    if not schema_info:
        print(f"  ✗ Could not get schema")
        return False

    # Generate SQL
    sql = generate_create_table_sql(dataset, table, schema_info)

    # Determine output path
    dataset_dir = SCHEMA_BASE / dataset
    dataset_dir.mkdir(parents=True, exist_ok=True)

    output_file = dataset_dir / f"{table}.sql"

    # Write file
    output_file.write_text(sql)
    print(f"  ✓ Created {output_file}")

    return True


def main():
    print("🚀 Generating Missing Schema Files\n")

    success_count = 0
    fail_count = 0

    for dataset, table in TABLES_TO_GENERATE:
        if generate_schema_file(dataset, table):
            success_count += 1
        else:
            fail_count += 1

    print("\n" + "="*80)
    print(f"✅ Generated {success_count} schema files")
    if fail_count > 0:
        print(f"❌ Failed to generate {fail_count} schema files")

    print("\nRun verification again to check coverage:")
    print("  python3 scripts/schema_verification_quick.py")


if __name__ == "__main__":
    main()

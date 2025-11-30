# BigQuery Schema Files

This directory contains CREATE TABLE definitions for all BigQuery tables in the `nba-props-platform` project.

## Directory Structure

```
schemas/bigquery/
├── nba_analytics/          # Phase 3 analytics tables (5 tables)
├── nba_precompute/         # Phase 4 precompute tables (6 tables)
├── nba_predictions/        # Phase 5 prediction tables (14 table/view definitions)
├── nba_reference/          # Reference data tables (7 tables)
├── nba_raw/                # Phase 2 raw data tables (30 tables)
├── nba_orchestration/      # Orchestration & workflow tables (7 tables)
├── orchestration/          # Legacy orchestration schemas
├── precompute/             # Legacy precompute schemas
├── analytics/              # Legacy analytics schemas
├── predictions/            # Legacy prediction schemas
├── raw/                    # Legacy raw schemas
├── static/                 # Static reference tables
├── processing/             # Processing metadata tables
├── validation/             # Validation tables
└── monitoring/             # Monitoring views
```

**Note:** Some directories contain legacy schema files. The canonical location for each dataset's schemas is the directory matching the BigQuery dataset name (e.g., `nba_analytics/` for the `nba_analytics` dataset).

## Naming Conventions

- **Table schemas:** `{table_name}.sql` (e.g., `player_game_summary.sql`)
- **Multiple related tables:** `{group}_tables.sql` (e.g., `player_game_summary_tables.sql` contains the main table + quality check views)
- **Views:** Can be in separate files or included with related table schemas

## Schema File Format

All schema files follow this format:

```sql
-- ============================================================================
-- Table Name and Purpose
-- ============================================================================
-- Dataset: nba_{dataset}
-- Table: {table_name}
-- Purpose: Brief description
-- Dependencies: List of upstream tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_{dataset}.{table_name}` (
  -- IDENTIFIERS
  field_name TYPE [NOT NULL],

  -- DATA FIELDS
  ...

  -- METADATA
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(partition_field)
CLUSTER BY field1, field2, field3;
```

## Schema Verification

### Quick Check

Run the verification script to check if all production tables have schema files:

```bash
./bin/verify_schemas.sh
```

Expected output for 100% coverage:
```
✅ SUCCESS: All production tables have schema files!
```

### Detailed Analysis

For detailed schema analysis:

```bash
python3 scripts/schema_verification_quick.py
```

This will show:
- Coverage percentage by dataset
- List of tables missing schemas
- List of schema files without deployed tables

## Generating Missing Schemas

If a new table is deployed without a schema file, generate it automatically:

### Single Table

```bash
# Get schema from BigQuery
bq show --schema --format=prettyjson \
  nba-props-platform:nba_analytics.new_table > /tmp/schema.json

# Manually create SQL file
nano schemas/bigquery/nba_analytics/new_table.sql
```

### Multiple Tables

Update `scripts/generate_missing_schemas.py` with the tables to generate, then run:

```bash
python3 scripts/generate_missing_schemas.py
```

## Schema Update Workflow

When you modify a BigQuery table schema:

1. **Update the deployed table** (via processor code or manual `bq update`)
2. **Update the schema file** to match
3. **Run verification** to ensure sync:
   ```bash
   ./bin/verify_schemas.sh
   ```
4. **Commit changes** to version control

## Current Schema Coverage

As of the latest verification:

| Dataset | Tables | With Schema | Coverage |
|---------|--------|-------------|----------|
| nba_analytics | 5 | 5 | 100% ✅ |
| nba_precompute | 6 | 6 | 100% ✅ |
| nba_predictions | 5 | 5 | 100% ✅ |
| nba_reference | 11 | 7 | 64%* |
| nba_raw | 18 | 14 | 78%* |
| nba_orchestration | 7 | 7 | 100% ✅ |
| **Total** | **52** | **44** | **84.6%** |

*Note: Missing schemas are temp/test/backup tables that should not be documented.*

**Production table coverage: 100% ✅**

## Temp/Test Tables (No Schema Required)

The following table patterns do NOT need schema files:
- `*_temp_*` - Temporary tables
- `*_backup_*` - Backup tables
- `*_FIXED*` - Test/migration tables
- `*_test_*` - Test tables

These are excluded from schema verification.

## Maintenance

Run schema verification before major changes:

```bash
# Before backfill
./bin/verify_schemas.sh

# Before deployment
./bin/verify_schemas.sh

# Monthly review
python3 scripts/schema_verification_quick.py
```

## Questions?

See:
- **Schema Management Guide:** `docs/06-reference/schema-management.md` (if created)
- **Verification Scripts:** `scripts/schema_verification_quick.py`
- **Generation Script:** `scripts/generate_missing_schemas.py`
- **Handoff Doc:** `docs/09-handoff/2025-11-29-schema-verification-complete.md`

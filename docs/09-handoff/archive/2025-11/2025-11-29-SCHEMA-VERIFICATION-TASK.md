# Schema Verification Task - Pre-Backfill Requirement

**Created:** 2025-11-29
**Priority:** HIGH - Must complete before historical backfill
**Estimated Time:** 1-2 hours
**Chat Type:** NEW CHAT SESSION

---

## 🎯 Purpose

Verify and synchronize all BigQuery table schemas before executing historical data backfill (2020-2024 seasons). This ensures:
- All deployed tables have corresponding schema files
- All schema files match actual deployed table schemas
- Schema documentation is complete and accurate
- No schema drift between deployed tables and documented schemas

**Why This Matters:**
During backfill, we'll process ~220 days of historical data across Phase 3 and Phase 4. If schemas are incorrect or missing, we risk:
- Data type mismatches causing processor failures
- Missing columns causing incomplete data
- Undocumented schema changes causing confusion
- Failed backfill runs requiring debugging and re-running

---

## 📋 Current State (What We Know)

### Infrastructure Status ✅
- v1.0 deployed and operational
- All orchestrators (Phase 2→3, Phase 3→4) active
- Phase 4 defensive checks implemented
- Alert suppression system ready
- Backfill infrastructure exists

### Schema Files Found
- **84 total schema SQL files** in `schemas/bigquery/`
- Organized by dataset: analytics, precompute, predictions, reference, raw, etc.
- Most major tables have schema files

### Deployed Tables Found
- **nba_analytics:** 8 tables (including 3 quality check tables)
- **nba_precompute:** 9 tables (6 regular + 3 views)
- **nba_predictions:** 12+ tables
- **nba_reference:** 12+ tables
- **nba_raw:** 50+ tables

### Known Issues
- ❓ Some deployed tables may lack schema files (e.g., `daily_game_context`, `daily_opponent_defense_zones`)
- ❓ Some schema files may not match deployed schemas (field count, types, etc.)
- ❓ Schema files found in different locations (`schemas/bigquery/nba_analytics/` vs `schemas/bigquery/analytics/`)
- ❓ Some tables have old/outdated schema files

---

## 🎯 Tasks to Complete

### Task 1: Inventory All Deployed Tables

**Action:** Query BigQuery to get complete list of all tables in each dataset

**Datasets to Check:**
- `nba-props-platform:nba_analytics`
- `nba-props-platform:nba_precompute`
- `nba-props-platform:nba_predictions`
- `nba-props-platform:nba_reference`
- `nba-props-platform:nba_raw`
- `nba-props-platform:nba_orchestration`
- `nba-props-platform:nba_static` (if exists)

**For Each Table, Capture:**
- Table name
- Number of fields
- Field names and types
- Partitioning info
- Clustering info
- Table description (if any)

**Output:** Complete inventory CSV or JSON file

---

### Task 2: Inventory All Schema Files

**Action:** Find all schema SQL files in the repository

**Locations to Check:**
- `schemas/bigquery/analytics/`
- `schemas/bigquery/precompute/`
- `schemas/bigquery/predictions/`
- `schemas/bigquery/nba_reference/`
- `schemas/bigquery/raw/`
- `schemas/bigquery/nba_analytics/` (if exists)
- `schemas/bigquery/nba_precompute/` (if exists)
- Any other schema directories

**For Each Schema File, Capture:**
- File path
- Table name (extracted from filename or SQL)
- Number of CREATE TABLE statements
- Field count per table

**Output:** Complete schema file inventory

---

### Task 3: Compare Deployed vs Schema Files

**Action:** Match deployed tables with schema files and identify gaps

**Create Three Lists:**

1. **✅ Tables with matching schema files**
   - Deployed table exists
   - Schema file exists
   - Field count matches (approximately - minor differences OK)

2. **❌ Deployed tables WITHOUT schema files**
   - Table exists in BigQuery
   - No corresponding schema file found
   - **Action needed:** Generate schema file from deployed table

3. **❌ Schema files WITHOUT deployed tables**
   - Schema file exists
   - No corresponding table in BigQuery
   - **Action needed:** Verify if table should exist, or remove stale schema file

**Output:** Gap analysis report with three categorized lists

---

### Task 4: Generate Missing Schema Files

**Action:** For each deployed table without a schema file, generate schema SQL

**Method:**
```bash
# Example command to extract schema
bq show --schema --format=prettyjson \
  nba-props-platform:nba_analytics.player_game_summary \
  > /tmp/player_game_summary_schema.json

# Then convert to CREATE TABLE SQL
```

**For Each Missing Schema:**
1. Extract schema from BigQuery
2. Convert to CREATE TABLE SQL statement
3. Include partitioning and clustering info
4. Add table description/comments
5. Save to appropriate location in `schemas/bigquery/`

**Output:** New schema files for all previously undocumented tables

---

### Task 5: Verify Schema Accuracy

**Action:** For tables that have schema files, verify they match deployed schemas

**Check:**
- Field count matches
- Field names match
- Field types match
- Required/nullable status matches
- Partitioning definition matches
- Clustering definition matches

**For Mismatches:**
- Document the differences
- Update schema file to match deployed table
- Add comment explaining when/why schema changed

**Output:** Updated schema files that accurately reflect deployed tables

---

### Task 6: Organize Schema Files

**Action:** Ensure consistent schema file organization

**Standard Structure:**
```
schemas/bigquery/
├── nba_analytics/
│   ├── player_game_summary.sql
│   ├── team_defense_game_summary.sql
│   ├── team_offense_game_summary.sql
│   ├── upcoming_player_game_context.sql
│   └── upcoming_team_game_context.sql
├── nba_precompute/
│   ├── player_composite_factors.sql
│   ├── player_daily_cache.sql
│   ├── player_shot_zone_analysis.sql
│   ├── team_defense_zone_analysis.sql
│   ├── daily_game_context.sql (if missing)
│   └── daily_opponent_defense_zones.sql (if missing)
├── nba_predictions/
│   ├── player_prop_predictions.sql
│   ├── prediction_worker_runs.sql
│   └── [other prediction tables]
├── nba_reference/
│   ├── processor_run_history.sql
│   ├── nba_players_registry.sql
│   └── [other reference tables]
└── nba_raw/
    └── [all raw tables]
```

**Rename/Move Files if Needed:**
- Move files from `analytics/` to `nba_analytics/` if that's the standard
- Ensure consistent naming convention
- Remove duplicate or outdated schema files

**Output:** Clean, organized schema directory structure

---

### Task 7: Create Schema Sync Verification Script

**Action:** Create a script that verifies schemas stay in sync

**Script Location:** `bin/verify_schemas.sh`

**Script Should:**
1. Compare all deployed tables with schema files
2. Report any mismatches (field count, field names, types)
3. Identify new tables without schema files
4. Identify stale schema files without deployed tables
5. Exit with error code if any issues found

**Usage:**
```bash
# Run verification
./bin/verify_schemas.sh

# Expected output if all synced:
✅ All schemas verified
   - 120 tables checked
   - 120 schema files found
   - 0 mismatches
   - 0 missing schema files
   - 0 stale schema files
```

**Output:** Automated verification script for ongoing schema monitoring

---

### Task 8: Update Documentation

**Action:** Document the schema verification process and results

**Create/Update:**

1. **`docs/06-reference/schema-management.md`**
   - How schemas are organized
   - How to generate schema from deployed table
   - How to update schema when table changes
   - How to run verification script

2. **`schemas/bigquery/README.md`**
   - Directory structure explanation
   - Naming conventions
   - How to add new schema files
   - Schema sync workflow

3. **`docs/09-handoff/2025-11-29-schema-verification-complete.md`**
   - Summary of what was done
   - Number of schema files generated
   - Number of schema files updated
   - Any issues found and resolved
   - Current schema state (100% synced)

**Output:** Complete schema documentation

---

## 📊 Success Criteria

**Schema verification is COMPLETE when:**

✅ **100% Coverage**
- Every deployed table has a schema file
- Every schema file matches a deployed table (or is documented as future/deprecated)

✅ **Accuracy Verified**
- All schema files match deployed table schemas
- Field counts, names, types all correct
- Partitioning and clustering documented

✅ **Organized & Clean**
- Schema files in consistent directory structure
- Clear naming conventions
- No duplicate or outdated files

✅ **Automated Verification**
- `bin/verify_schemas.sh` script exists
- Script successfully verifies all schemas
- Script can be run in CI/CD for ongoing validation

✅ **Documented**
- Schema management guide exists
- Handoff document created with results
- README in schemas directory

---

## 🚀 Recommended Approach

### Phase 1: Discovery (30 minutes)
1. Run inventory queries for all datasets
2. List all schema files
3. Create gap analysis report

### Phase 2: Generate Missing Schemas (30 minutes)
1. Extract schemas from BigQuery for missing tables
2. Convert to SQL CREATE TABLE statements
3. Save to appropriate locations

### Phase 3: Verify & Update (30 minutes)
1. Compare existing schema files with deployed tables
2. Update any mismatched schema files
3. Add comments for any discrepancies

### Phase 4: Organize & Automate (30 minutes)
1. Organize schema files into clean structure
2. Create verification script
3. Test verification script
4. Document process

---

## 🔗 Related Documentation

**Current Project:**
- `docs/09-handoff/NEXT-SESSION-BACKFILL.md` - Backfill execution plan
- `docs/08-projects/current/backfill/BACKFILL-STRATEGY-PHASES-1-5.md` - Comprehensive strategy
- `docs/08-projects/current/backfill/PHASE4-DEFENSIVE-CHECKS-PLAN.md` - Phase 4 checks

**After Schema Work:**
- Return to backfill planning chat
- Finalize backfill execution strategy
- Execute small test (7 days)
- Execute full historical backfill

---

## 💬 Suggested Prompt for New Chat

```
I need help verifying and synchronizing all BigQuery table schemas before
executing a historical data backfill.

Context:
- I have a BigQuery project: nba-props-platform
- Multiple datasets: nba_analytics, nba_precompute, nba_predictions,
  nba_reference, nba_raw
- Schema files in schemas/bigquery/ directory
- Need to ensure 100% accuracy before backfilling 4 years of data

Tasks:
1. Inventory all deployed BigQuery tables (get schemas with bq show --schema)
2. Inventory all schema SQL files in schemas/bigquery/
3. Compare and identify:
   - Tables missing schema files
   - Schema files not matching deployed tables
   - Stale/outdated schema files
4. Generate missing schema files from deployed tables
5. Update inaccurate schema files to match deployed schemas
6. Organize schema files into clean structure
7. Create bin/verify_schemas.sh script to verify schemas stay synced
8. Document the schema management process

Please read this task document first:
docs/09-handoff/2025-11-29-SCHEMA-VERIFICATION-TASK.md

Then let's work through each task systematically.
```

---

## 📝 Deliverables for Backfill Chat

When you return to the backfill planning chat, bring:

1. **✅ Confirmation:** All schemas verified and synced
2. **📋 Summary:** Number of schemas generated/updated
3. **🔍 Issues Found:** Any schema problems discovered and resolved
4. **📄 Handoff Doc:** `docs/09-handoff/2025-11-29-schema-verification-complete.md`
5. **🛠️ Verification Script:** `bin/verify_schemas.sh` working and tested

**Then we'll:**
- Finalize backfill execution strategy
- Discuss every step and edge case
- Create comprehensive backfill documentation
- Execute small test run (7 days)
- Execute full historical backfill (2021-2024)

---

**Good luck with the schema verification! See you back in the backfill chat when ready! 🚀**

---

## Appendix: Quick Reference Commands

### Get Table Schema
```bash
bq show --schema --format=prettyjson \
  nba-props-platform:nba_analytics.player_game_summary
```

### List All Tables in Dataset
```bash
bq ls --format=json nba-props-platform:nba_analytics
```

### Get Table Info (including partitioning/clustering)
```bash
bq show --format=prettyjson \
  nba-props-platform:nba_analytics.player_game_summary
```

### Count Fields in Schema File
```bash
grep -c "^[[:space:]]*[a-zA-Z_]" \
  schemas/bigquery/nba_analytics/player_game_summary.sql
```

### Find All Schema Files
```bash
find schemas/bigquery -name "*.sql" -type f | sort
```

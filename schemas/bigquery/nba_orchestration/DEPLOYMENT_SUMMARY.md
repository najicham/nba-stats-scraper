# NBA Orchestration Dataset - Deployment Summary

**File:** `schemas/bigquery/nba_orchestration/DEPLOYMENT_SUMMARY.md`  
**Date:** November 10, 2025  
**Status:** ✅ Ready for Deployment

## What Was Created

### Directory Structure

```
schemas/bigquery/nba_orchestration/
├── README.md                         # Comprehensive usage guide
├── datasets.sql                      # Dataset definition
├── scraper_execution_log.sql         # Table 1: Every scraper run
├── workflow_decisions.sql            # Table 2: Controller decisions
├── daily_expected_schedule.sql       # Table 3: Expected schedule
├── cleanup_operations.sql            # Table 4: Self-healing operations
├── deploy_tables.sh                  # Deployment script (executable)
└── DEPLOYMENT_SUMMARY.md            # This file
```

### Tables Overview

| Table | Fields | Purpose | Key Feature |
|-------|--------|---------|-------------|
| `scraper_execution_log` | 18 | Every scraper run | 3-status tracking (success/no_data/failed) |
| `workflow_decisions` | 14 | Controller evaluation decisions | Expected vs actual monitoring |
| `daily_expected_schedule` | 11 | Expected workflow schedule | Locked at 5 AM ET for Grafana |
| `cleanup_operations` | 10 | Self-healing recovery operations | Pub/Sub republishing (Week 2+) |

**Total Fields:** 53 fields across 4 tables

## Quick Start (3 Steps)

### Step 1: Deploy Tables (5 minutes)

```bash
cd schemas/bigquery/nba_orchestration
./deploy_tables.sh
```

**Expected Output:**
```
✅ Dataset created successfully
✅ Table created successfully: scraper_execution_log
✅ Table created successfully: workflow_decisions
✅ Table created successfully: daily_expected_schedule
✅ Table created successfully: cleanup_operations
🎉 Deployment Complete!
```

### Step 2: Verify (1 minute)

```bash
# List tables
bq ls nba-props-platform:nba_orchestration

# Test query
bq query --use_legacy_sql=false "
SELECT 
  table_name,
  table_type
FROM \`nba-props-platform.nba_orchestration.INFORMATION_SCHEMA.TABLES\`
ORDER BY table_name
"
```

**Expected Result:** 4 tables listed

### Step 3: Test with Scraper (2 minutes)

```bash
# Run injury report scraper
python -m scrapers.nbacom.nbac_injury_report \
  --gamedate 20250115 \
  --hour 8 \
  --period AM

# Check log
bq query --use_legacy_sql=false "
SELECT 
  scraper_name,
  status,
  source,
  triggered_by,
  JSON_VALUE(data_summary, '$.record_count') as records
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
ORDER BY triggered_at DESC
LIMIT 1
"
```

**Expected Result:** One row showing the scraper execution

## Key Features Implemented

### 1. Three-Status System ⭐

The breakthrough innovation for discovery mode:

- **`success`**: Got data (record_count > 0) → Stop trying
- **`no_data`**: Tried but empty (record_count = 0) → Keep trying
- **`failed`**: Real error → Retry immediately

**Why it matters:** Distinguishes "not published yet" from "real error"

### 2. Source Tracking 📍

Every execution knows where it came from:

- `CONTROLLER` - Master workflow controller (automated)
- `MANUAL` - Direct API call (testing)
- `LOCAL` - Dev machine (development)
- `CLOUD_RUN` - Direct endpoint (integration tests)
- `SCHEDULER` - Cloud Scheduler (legacy cron)
- `RECOVERY` - Cleanup processor (self-healing)

**Use case:** Cost analysis, debugging, automation metrics

### 3. Expected vs Actual Monitoring 📊

Daily schedule locked at 5 AM ET enables Grafana dashboards:

```
Expected: betting_lines at 11:00 AM
Actual:   betting_lines at 11:02 AM
Status:   ✅ ON TIME (2 min delay)
```

**Alert conditions:**
- 🔴 MISSING - Expected but didn't run
- 🟡 LATE - Ran >30 min after expected
- ✅ ON TIME - Ran within 30 min window

### 4. Self-Healing System 🔧

Cleanup processor checks for missing files every 30 minutes:

1. Scan GCS for scraper output files
2. Check BigQuery for processing records
3. Find files without processing (missed Pub/Sub)
4. Republish Pub/Sub messages (Week 2+)

**Week 1 behavior:** Monitoring only (`pubsub_enabled=false`)

## Table-Specific Details

### scraper_execution_log

**Partitioning:** Daily on `triggered_at`  
**Clustering:** `scraper_name, workflow, status, source`  
**Retention:** 90 days

**Sample Query:**
```sql
-- Check if injury report found data today
SELECT status, JSON_VALUE(data_summary, '$.record_count') as records
FROM scraper_execution_log
WHERE scraper_name = 'nbac_injury_report'
  AND DATE(triggered_at) = CURRENT_DATE()
ORDER BY triggered_at DESC
LIMIT 1;
```

### workflow_decisions

**Partitioning:** Daily on `decision_time`  
**Clustering:** `workflow_name, action, alert_level`  
**Retention:** 90 days

**Sample Query:**
```sql
-- Today's workflow summary
SELECT 
  workflow_name,
  action,
  COUNT(*) as decisions,
  STRING_AGG(DISTINCT reason ORDER BY reason LIMIT 3) as sample_reasons
FROM workflow_decisions
WHERE DATE(decision_time) = CURRENT_DATE()
GROUP BY workflow_name, action;
```

### daily_expected_schedule

**Partitioning:** Daily on `date`  
**Clustering:** `workflow_name, expected_run_time`  
**Retention:** 90 days

**Sample Query:**
```sql
-- Today's expected schedule
SELECT 
  workflow_name,
  FORMAT_TIMESTAMP('%H:%M', expected_run_time, 'America/New_York') as time_et,
  reason,
  priority
FROM daily_expected_schedule
WHERE date = CURRENT_DATE('America/New_York')
ORDER BY expected_run_time;
```

### cleanup_operations

**Partitioning:** Daily on `cleanup_time`  
**Clustering:** `missing_files_found, republished_count`  
**Retention:** 90 days

**Sample Query:**
```sql
-- Recent cleanup activity
SELECT 
  cleanup_time,
  files_checked,
  missing_files_found,
  republished_count,
  pubsub_enabled
FROM cleanup_operations
WHERE DATE(cleanup_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY cleanup_time DESC
LIMIT 20;
```

## Implementation Priority

### Priority 1: Deploy Tables ✅ (Ready Now)

```bash
./schemas/bigquery/nba_orchestration/deploy_tables.sh
```

**Time:** 5 minutes  
**Result:** All 4 tables created and verified

### Priority 2: Add Logging to Scraper Base (Next)

**File:** `scrapers/scraper_base.py`

Add these methods:
1. `_determine_execution_source()` - Detect source (CONTROLLER/MANUAL/LOCAL/etc.)
2. `_log_execution_to_bigquery()` - Log to scraper_execution_log
3. `_log_failed_execution_to_bigquery()` - Log failures

**Integration point:** Call from `run()` method before returning

**Time:** 2-3 hours  
**Result:** Every scraper automatically logs to BigQuery

### Priority 3: Create Config File (Next)

**File:** `config/workflows.yaml`

Define workflows:
```yaml
workflows:
  morning_operations:
    enabled: true
    priority: "HIGH"
    schedule:
      ideal_window:
        start_hour: 6
        end_hour: 10
      run_once_daily: true
    execution_plan:
      type: "parallel"
      scrapers:
        - nbac_schedule_api
        - nbac_player_list
```

**Time:** 2-3 hours  
**Result:** Declarative workflow configuration

### Priority 4: Implement Master Controller (Week 2)

**File:** `orchestration/master_controller.py`

Core logic:
1. Load workflows from config
2. Evaluate each workflow (should it run?)
3. Log decision to workflow_decisions
4. Trigger scrapers if action='RUN'
5. Generate daily_expected_schedule at 5 AM ET

**Time:** 1-2 days  
**Result:** Automated workflow orchestration

## Testing Checklist

After deployment, verify:

- [ ] All 4 tables exist in BigQuery
- [ ] Partitioning configured (check INFORMATION_SCHEMA)
- [ ] Clustering configured (check INFORMATION_SCHEMA)
- [ ] Sample data inserts successfully
- [ ] JSON fields parse correctly (`JSON_VALUE` works)
- [ ] Partition filtering performs well (<1 second queries)
- [ ] Views create successfully (if using helper views)
- [ ] Alert queries return expected results

## Migration from Handoff Document

This deployment replaces the complete schema package from the handoff document:

**What changed:**
- ✅ JSON schemas → SQL schemas (following project pattern)
- ✅ Added comprehensive field comments
- ✅ Included sample data in SQL comments
- ✅ Added validation queries in each table file
- ✅ Created deployment script
- ✅ Wrote comprehensive README

**What stayed the same:**
- Schema structure (all fields preserved)
- Partitioning strategy
- Clustering keys
- 3-status system design
- Discovery mode logic

## Support & Documentation

**Main Documentation:**
- `README.md` - Complete usage guide
- Individual SQL files - Detailed field descriptions, sample data, validation queries

**Quick References:**
- Three-status system: See `scraper_execution_log.sql` header
- Discovery mode: See `README.md` "Discovery Mode Example"
- Expected vs actual: See `daily_expected_schedule.sql` validation queries
- Self-healing: See `cleanup_operations.sql` header

**Troubleshooting:**
- JSON fields return NULL → Check `README.md` "Troubleshooting" section
- Query scans too much → Always filter on partition keys
- Missing workflows → Check `workflow_decisions` for SKIP/ABORT

## Next Conversation Handoff

**Continue with:** Implementation of scraper base class logging

**You'll need:**
- This deployment (tables must exist first)
- Access to `scrapers/scraper_base.py`
- Understanding of 3-status system (success/no_data/failed)
- BigQuery insert utility (`shared/utils/bigquery_utils.py`)

**Starting point:** See `README.md` "Integration Examples" section for code templates

## Success Criteria

✅ **Deployment successful if:**
1. All 4 tables exist in `nba_orchestration` dataset
2. Test queries run without errors
3. Sample scraper execution logs to BigQuery
4. Status field shows correct values (success/no_data/failed)
5. Source tracking works (LOCAL for dev runs)

✅ **Ready for Phase 1 orchestration implementation**

---

**Questions?** Review the comprehensive README.md or individual table SQL files for detailed documentation.

**Issues?** Run validation queries in each SQL file to diagnose problems.

**Ready to proceed?** Start with Priority 2: Add logging to scraper_base.py

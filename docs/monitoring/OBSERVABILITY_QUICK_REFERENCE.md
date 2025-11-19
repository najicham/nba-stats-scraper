# Observability Quick Reference Card

**File:** `docs/monitoring/OBSERVABILITY_QUICK_REFERENCE.md`
**Created:** 2025-11-18
**Purpose:** One-page reference for what's logged vs what's missing
**Audience:** Quick lookup for engineers troubleshooting or planning improvements

---

## 📊 At-A-Glance Status

| Category | Phase 1 (Scrapers) | Phase 2-5 (Processors) |
|----------|-------------------|------------------------|
| **Execution Logging** | ✅ `scraper_execution_log` | ❌ Missing table |
| **Error Details** | ✅ Structured (BigQuery) | ⚠️ Cloud Logging only (30 days) |
| **Parameters** | ✅ `opts` JSON field | ❌ Not tracked |
| **Retries** | ✅ `retry_count` field | ⚠️ Partial |
| **Dependencies** | N/A | ❌ Not logged |
| **Quality Metadata** | N/A | ❓ Design exists, unclear if implemented |
| **Historical Analysis** | ✅ Permanent (BigQuery) | ❌ 30-day limit (Cloud Logging) |

---

## ✅ What You CAN See Today

### Phase 1 Scrapers (Excellent Visibility)

**Table:** `nba_orchestration.scraper_execution_log`

✅ **What failed?**
```sql
SELECT scraper_name, error_message
FROM `nba_orchestration.scraper_execution_log`
WHERE status = 'failed' AND DATE(triggered_at) = CURRENT_DATE();
```

✅ **What parameters failed?**
```sql
SELECT scraper_name, opts, error_message
FROM `nba_orchestration.scraper_execution_log`
WHERE status = 'failed' AND DATE(triggered_at) = CURRENT_DATE();
-- opts contains: {"date": "2025-11-18", "season": "2025", "group": "prod"}
```

✅ **Did it retry and succeed?**
```sql
SELECT scraper_name, JSON_VALUE(opts, '$.date') as date_param,
       status, triggered_at
FROM `nba_orchestration.scraper_execution_log`
WHERE scraper_name = 'nbac_injury_report'
  AND DATE(triggered_at) = CURRENT_DATE()
ORDER BY triggered_at;
-- See multiple attempts with same params
```

✅ **Performance trends**
```sql
SELECT scraper_name, AVG(duration_seconds), COUNT(*)
FROM `nba_orchestration.scraper_execution_log`
WHERE DATE(triggered_at) >= CURRENT_DATE() - 7
GROUP BY scraper_name;
```

---

## ❌ What You CANNOT See Today

### Phase 2-5 Processors (Major Gaps)

❌ **Did processor run today?**
- Current: Check Cloud Run job status via `gcloud` command
- Missing: No `processor_execution_log` table
- Workaround: Query output tables for row counts (indirect)

❌ **Why did processor fail?**
- Current: Search Cloud Logging text (30-day retention)
- Missing: No structured error tracking in BigQuery
- Workaround: Manual log search, expires after 30 days

❌ **What dependency was missing?**
- Current: Search Cloud Logging for "dependency check failed"
- Missing: No `dependency_check_log` table
- Workaround: Manually query tables to see what existed at failure time

❌ **Which delivery attempt succeeded?**
- Current: See final result only
- Missing: No Pub/Sub retry attempt tracking
- Workaround: Check DLQ count, hope logs still available

❌ **Did processor use fallback data?**
- Current: Unclear if metadata is being stored
- Missing: Needs verification if `data_source` field exists
- Workaround: Can't tell without checking implementation

---

## 🎯 Quick Decision Guide

### "Something failed today. How do I debug?"

**Phase 1 (Scraper):**
1. ✅ Query `scraper_execution_log` for failures
2. ✅ See exact parameters that failed
3. ✅ Check if later retry succeeded
4. ✅ View error message and type
5. ✅ Total time: 2-5 minutes

**Phase 2-5 (Processor):**
1. ⚠️ Check Cloud Run job executions via `gcloud`
2. ⚠️ Search Cloud Logging for errors (hope they exist)
3. ❌ Manually query tables to see what dependencies existed
4. ❌ Can't see parameters or retry history
5. ⚠️ Total time: 15-30 minutes (or more)

---

## 🔧 Missing Capabilities Checklist

Use this to prioritize improvements:

### Critical (Blocking Operations)
- [ ] **Processor execution log** - Can't see if processors ran
- [ ] **Processor error tracking** - Errors expire after 30 days
- [ ] **Dependency check log** - Can't see what was missing

### Important (Improves Debugging)
- [ ] **Pub/Sub retry visibility** - Don't know which attempt succeeded
- [ ] **Parameter tracking** - Can't see what inputs processor used
- [ ] **Performance tracking** - Can't track processor duration trends

### Nice to Have (Quality Monitoring)
- [ ] **Data quality metadata** - Can't see if fallback data used
- [ ] **Fallback tracking** - Can't track degraded quality
- [ ] **Early season handling** - Can't see placeholder records

---

## 📋 Recommended Tables to Create

### Priority 1: processor_execution_log
```sql
CREATE TABLE nba_orchestration.processor_execution_log (
  execution_id STRING,
  processor_name STRING,
  phase STRING,
  triggered_at TIMESTAMP,
  status STRING,  -- 'success', 'failed', 'partial'
  input_params JSON,
  rows_processed INT64,
  error_type STRING,
  error_message STRING
);
```

### Priority 2: dependency_check_log
```sql
CREATE TABLE nba_orchestration.dependency_check_log (
  check_id STRING,
  check_time TIMESTAMP,
  processor_name STRING,
  required_table STRING,
  required_partition JSON,
  check_result STRING,  -- 'PASS', 'FAIL'
  row_count INT64,
  error_message STRING
);
```

---

## 🚀 Quick Commands Reference

### Check Scraper Health
```sql
-- Today's failures
SELECT scraper_name, COUNT(*) as failures
FROM `nba_orchestration.scraper_execution_log`
WHERE status = 'failed' AND DATE(triggered_at) = CURRENT_DATE()
GROUP BY scraper_name;
```

### Check Processor Health (Current Workaround)
```bash
# List recent executions
gcloud run jobs executions list \
  --job=phase3-player-game-summary \
  --limit=5

# Check logs for errors
gcloud logging read \
  "resource.type=cloud_run_job AND severity>=ERROR" \
  --limit=20 \
  --freshness=1h
```

### Check Dependencies (Manual)
```sql
-- Phase 3 depends on Phase 2
SELECT 'nbac_gamebook_player_stats', COUNT(*)
FROM `nba_raw.nbac_gamebook_player_stats`
WHERE game_date = CURRENT_DATE() - 1;
```

### Check Pub/Sub DLQ
```bash
# See if messages are stuck
gcloud pubsub subscriptions describe nba-scraper-complete-dlq-sub \
  --format="value(numUndeliveredMessages)"
```

---

## 📖 Full Documentation

For detailed information, see:
- **Full Gap Analysis:** `04-observability-gaps-and-improvement-plan.md`
- **Current Monitoring:** `01-grafana-monitoring-guide.md`
- **Daily Health Check:** `02-grafana-daily-health-check.md`

---

## 🔄 Status Summary

**Created:** 2025-11-18
**Current Implementation:** Phase 1 excellent, Phase 2-5 gaps
**Recommended Next Step:** Create `processor_execution_log` table (6-8 hours)
**Long-term Goal:** Full observability parity across all phases

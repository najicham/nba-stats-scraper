# Grafana Monitoring Guide - Pipeline Run History (Phases 2-5)

**File:** `docs/07-monitoring/grafana/pipeline-monitoring.md`
**Created:** 2025-11-16
**Last Updated:** 2025-11-30
**Purpose:** Monitor Phase 2-5 pipeline health using the unified `processor_run_history` table
**Status:** Current
**Related:** Phase 1 orchestration monitoring in `monitoring-guide.md`

---

## Overview

This guide provides monitoring queries for the **Phase 2-5 data processing pipeline** using the unified `processor_run_history` table:

| Phase | Processors | What They Do |
|-------|------------|--------------|
| Phase 2 (Raw) | `NbacPlayerBoxscoreProcessor`, etc. | Load scraped data to BigQuery |
| Phase 3 (Analytics) | `PlayerGameSummaryProcessor`, etc. | Compute player/team analytics |
| Phase 4 (Precompute) | `MLFeatureStoreProcessor`, etc. | Build ML features |
| Phase 5 (Predictions) | `PredictionCoordinator` | Generate player predictions |

**Key Table:** `nba_reference.processor_run_history` - All phases log to this unified table.

---

## Key Tables

### `nba_reference.processor_run_history`

**Purpose:** Unified tracking of all processor runs across Phases 2-5

**Key fields:**
```sql
processor_name STRING              -- e.g., 'PlayerGameSummaryProcessor'
run_id STRING                      -- Unique run identifier
status STRING                      -- 'running', 'success', 'failed'
data_date DATE                     -- Date being processed
started_at TIMESTAMP               -- When processing started
processed_at TIMESTAMP             -- When processing finished
duration_seconds FLOAT64           -- How long it took

-- Phase identification
phase STRING                       -- 'phase_2_raw', 'phase_3', 'phase_4_precompute', 'phase_5_predictions'
output_table STRING                -- Target table name
output_dataset STRING              -- Target dataset name

-- Triggering
trigger_source STRING              -- 'pubsub', 'scheduler', 'manual', 'api'
trigger_message_id STRING          -- Pub/Sub message that triggered this
parent_processor STRING            -- Upstream processor name

-- Results
records_processed INT64            -- Number of records processed
records_skipped INT64              -- Number skipped
errors STRING                      -- JSON error details if failed
summary STRING                     -- JSON summary data

-- Cloud Run metadata
cloud_run_service STRING           -- Service name
cloud_run_revision STRING          -- Deployment revision
```

### `nba_orchestration.scraper_execution_log`

**Purpose:** Phase 1 scraper execution tracking (separate from processor_run_history)

See `monitoring-guide.md` for Phase 1 queries.

---

## Dashboard 1: Pipeline Health Overview

**Goal:** Answer "Is the Phase 2-5 pipeline healthy?" in 30 seconds

**Dashboard JSON:** `dashboards/pipeline-run-history-dashboard.json`
**SQL Queries:** `dashboards/pipeline-run-history-queries.sql`

---

### Panel 1: Pipeline Health Status

**Type:** Stat Panel (Large)
**Update:** Every 5 minutes

```sql
WITH today_stats AS (
  SELECT
    COUNT(*) as total_runs,
    COUNTIF(status = 'success') as success_count,
    COUNTIF(status = 'failed') as failed_count,
    COUNTIF(status = 'running') as running_count
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE data_date = CURRENT_DATE()
)
SELECT
  CASE
    WHEN total_runs = 0 THEN 'NO DATA'
    WHEN failed_count = 0 AND success_count > 0 THEN 'HEALTHY'
    WHEN success_count * 1.0 / NULLIF(success_count + failed_count, 0) >= 0.9 THEN 'HEALTHY'
    WHEN success_count * 1.0 / NULLIF(success_count + failed_count, 0) >= 0.7 THEN 'DEGRADED'
    ELSE 'UNHEALTHY'
  END as health_status
FROM today_stats
```

**Visualization:**
- Green: HEALTHY
- Yellow: DEGRADED
- Red: UNHEALTHY
- Blue: NO DATA

---

### Panel 2: Pipeline Health by Phase

**Type:** Table
**Update:** Every 5 minutes
**Purpose:** See health breakdown by pipeline phase

```sql
SELECT
  COALESCE(phase, 'unknown') as phase,
  COUNT(*) as total_runs,
  COUNTIF(status = 'success') as success,
  COUNTIF(status = 'failed') as failed,
  COUNTIF(status = 'running') as running,
  ROUND(COUNTIF(status = 'success') * 100.0 /
        NULLIF(COUNTIF(status IN ('success', 'failed')), 0), 1) as success_rate,
  ROUND(AVG(duration_seconds), 1) as avg_duration_sec
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY phase
ORDER BY phase
```

**Table Settings:**
- Conditional formatting on "success_rate" column
- Red: < 80%
- Yellow: 80-95%
- Green: > 95%

---

### Panel 3: Recent Failed Runs

**Type:** Table
**Update:** Every 5 minutes
**Purpose:** Identify failing processors quickly

```sql
SELECT
  started_at,
  processor_name,
  phase,
  data_date,
  status,
  ROUND(duration_seconds, 1) as duration_sec,
  trigger_source,
  SUBSTR(COALESCE(
    JSON_VALUE(errors, '$[0].error_message'),
    errors,
    'N/A'
  ), 1, 100) as error_preview
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'failed'
  AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY started_at DESC
LIMIT 25
```

**Action for each failure:**
- Check Cloud Run logs for detailed stack trace
- Verify upstream dependencies completed
- Check for data quality issues

---

### Panel 4: Success Rate Trend (Last 30 Days)

**Type:** Time Series
**Update:** Every 10 minutes

```sql
SELECT
  TIMESTAMP(data_date) as time,
  COALESCE(phase, 'unknown') as metric,
  ROUND(COUNTIF(status = 'success') * 100.0 /
        NULLIF(COUNTIF(status IN ('success', 'failed')), 0), 1) as value
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY data_date, phase
ORDER BY time, phase
```

**Visualization:** Line chart with phase as series
**Thresholds:**
- Green: > 90%
- Yellow: 70-90%
- Red: < 70%

---

### Panel 5: Phase 5 Prediction Runs

**Type:** Table
**Update:** Every 5 minutes
**Purpose:** Track prediction batch executions specifically

```sql
SELECT
  started_at,
  data_date as game_date,
  status,
  records_processed as predictions,
  ROUND(duration_seconds, 1) as duration_sec,
  trigger_source,
  JSON_VALUE(summary, '$.correlation_id') as correlation_id
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_5_predictions'
  AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
ORDER BY started_at DESC
LIMIT 20
```

**Watch for:**
- Status should be 'success' for game days
- Predictions count should match expected players (~450)
- Duration should be consistent (not increasing over time)

---

### Panel 6: Stale Running Processors (Alert)

**Type:** Table
**Update:** Every 1 minute
**Purpose:** Detect stuck processors

```sql
SELECT
  started_at,
  processor_name,
  phase,
  data_date,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) as minutes_running
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'running'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) > 60
ORDER BY started_at
```

**Alert:** If any row appears, processor may be stuck. Check Cloud Run logs.

---

## Alert Configurations

### Critical Alerts

**Alert 1: Pipeline Unhealthy**
```sql
-- Alert if success rate < 70% in last 2 hours
SELECT
  ROUND(COUNTIF(status = 'success') * 100.0 /
        NULLIF(COUNTIF(status IN ('success', 'failed')), 0), 1) as success_rate
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
HAVING success_rate < 70
```

**Alert 2: Stale Running Processor**
```sql
-- Alert if any processor running > 60 minutes
SELECT COUNT(*) as stale_count
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'running'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) > 60
HAVING stale_count > 0
```

### Warning Alerts

**Alert 3: Phase 5 Predictions Failed**
```sql
-- Alert if prediction batch failed
SELECT COUNT(*) as failed_predictions
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_5_predictions'
  AND status = 'failed'
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
HAVING failed_predictions > 0
```

---

## Quick Actions Reference

### When Panel 2 shows low success rate for a phase

1. Check failed runs in Panel 3
2. Identify the failing processor(s)
3. Check Cloud Run logs:
   ```bash
   gcloud run services logs read nba-phase2-raw-processors --region=us-west2 --limit=50
   gcloud run services logs read nba-phase3-analytics --region=us-west2 --limit=50
   ```

### When Panel 6 shows stale running processors

1. Check if processor is actually stuck vs. just slow
2. Check Cloud Run service health:
   ```bash
   gcloud run services describe nba-phase2-raw-processors --region=us-west2
   ```
3. If truly stuck, may need to wait for timeout or manually restart

### When Phase 5 predictions fail

1. Check ML feature store completed for the date
2. Verify player data exists for the game date
3. Check prediction worker logs:
   ```bash
   gcloud run services logs read nba-prediction-worker --region=us-west2 --limit=50
   ```

---

## Expected Patterns

### Normal Behavior (Game Day)

**Phase 2 (Raw):**
- Expected runs: 20-50 (depends on scrapers)
- Success rate: >95%
- Avg duration: 30-120 seconds

**Phase 3 (Analytics):**
- Expected runs: 5-10
- Success rate: >95%
- Avg duration: 60-300 seconds

**Phase 4 (Precompute):**
- Expected runs: 5-10
- Success rate: >95%
- Avg duration: 60-300 seconds

**Phase 5 (Predictions):**
- Expected runs: 1-3 per game date
- Success rate: 100% (any failure = no predictions)
- Records processed: ~450 predictions

### Warning Signs

**Critical Issues:**
- Any phase success rate < 70%
- Processor running > 60 minutes
- Phase 5 status = 'failed'
- No runs for expected game date

**Warning Signs:**
- Success rate 70-90%
- Duration increasing over time
- Same processor failing repeatedly

---

## Integration with Phase 1 Monitoring

**Combined health check workflow:**

1. **Check Phase 1 Orchestration** (see `monitoring-guide.md`)
   - Are scrapers running?
   - Are workflows executing?

2. **Check Phase 2-5 Pipeline** (this dashboard)
   - Are processors running?
   - Any failures?
   - Predictions generated?

3. **Check Data Quality** (see `completeness-dashboard.json`)
   - Is data complete?
   - Any circuit breakers active?

---

## Related Documentation

- `monitoring-guide.md` - Phase 1 orchestration monitoring
- `daily-health-check.md` - Quick daily health check
- `dashboards/completeness-dashboard.json` - Data quality monitoring
- `dashboards/pipeline-run-history-dashboard.json` - This dashboard
- `dashboards/pipeline-run-history-queries.sql` - SQL queries

---

**Last Updated:** 2025-11-30
**Version:** 2.0 (rewritten to use processor_run_history table)
**Status:** Ready for Implementation

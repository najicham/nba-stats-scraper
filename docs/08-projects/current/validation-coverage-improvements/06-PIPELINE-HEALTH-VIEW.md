# Pipeline Health View - Single Source of Truth

**Priority**: P1
**Effort**: 4-6 hours
**Status**: Investigation

---

## Problem Statement

No single place to see the health of all phases and processors. Debugging requires querying multiple tables and checking logs.

---

## Proposed Solution

Create comprehensive health summary view showing:
- Last successful run per phase/processor
- Failures in last 24h
- Health status (HEALTHY/DEGRADED/UNHEALTHY/STALE)

### Schema
```sql
CREATE OR REPLACE VIEW nba_monitoring.pipeline_health_summary AS
WITH processor_runs AS (
  -- Aggregate from scraper_execution_log and phase_execution_log
  SELECT
    phase,
    processor_name,
    MAX(CASE WHEN status = 'success' THEN completed_at END) as last_success_time,
    MAX(CASE WHEN status = 'success' THEN game_date END) as last_success_date,
    COUNTIF(status IN ('failed', 'partial') 
      AND completed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)) as failures_24h,
    COUNT(*) as total_runs_24h
  FROM (
    -- Union of execution logs from different phases
    SELECT 'phase1_scraper' as phase, scraper_name as processor_name, status, triggered_at as completed_at, game_date
    FROM nba_orchestration.scraper_execution_log
    UNION ALL
    SELECT phase, processor_name, status, execution_timestamp as completed_at, game_date
    FROM nba_orchestration.phase_execution_log
  )
  WHERE completed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  GROUP BY phase, processor_name
)
SELECT
  phase,
  processor_name,
  last_success_time,
  last_success_date,
  failures_24h,
  total_runs_24h,
  DATE_DIFF(CURRENT_DATE(), last_success_date, DAY) as days_since_success,
  CASE
    WHEN last_success_time IS NULL THEN 'NEVER_RAN'
    WHEN DATE_DIFF(CURRENT_DATE(), last_success_date, DAY) > 7 THEN 'STALE'
    WHEN failures_24h > 5 THEN 'UNHEALTHY'
    WHEN failures_24h > 0 THEN 'DEGRADED'
    ELSE 'HEALTHY'
  END as health_status
FROM processor_runs
ORDER BY 
  CASE health_status
    WHEN 'UNHEALTHY' THEN 1
    WHEN 'STALE' THEN 2
    WHEN 'NEVER_RAN' THEN 3
    WHEN 'DEGRADED' THEN 4
    ELSE 5
  END,
  phase, processor_name;
```

---

## Implementation Plan

### Step 1: Audit Existing Tables
Identify all tables containing execution data:
- `nba_orchestration.scraper_execution_log`
- `nba_orchestration.phase_execution_log`
- `nba_reference.processor_run_history`
- Firestore collections

### Step 2: Create View
```sql
-- monitoring/bigquery_views/pipeline_health_summary.sql
```

### Step 3: Create Scheduled Refresh
Hourly scheduled query to materialize the view for faster queries.

### Step 4: Add to /validate-daily
Include health summary at top of validation output.

---

## Investigation Questions

1. What tables contain processor run history?
2. What's the schema of each table?
3. How do we map processor names consistently across tables?
4. Should we include Firestore phase_completion collections?
5. What thresholds define DEGRADED vs UNHEALTHY?

---

## Success Criteria

- [ ] Single query shows all processor health
- [ ] Health status accurately reflects current state
- [ ] Dashboard or report shows health summary

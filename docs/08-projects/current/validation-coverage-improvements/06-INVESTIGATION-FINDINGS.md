# Pipeline Health View - Investigation Findings

**Investigated**: 2026-01-28
**Status**: Partial Implementation Exists, Needs Extension

---

## Key Finding: Foundation Exists, Gaps in Phase 1/2 Coverage

Existing views at `monitoring/bigquery_views/` cover Phases 3-5 only. Need to extend for complete pipeline visibility.

---

## 1. Tables with Processor Run History

| Table | Phase | Key Fields |
|-------|-------|------------|
| `nba_orchestration.scraper_execution_log` | Phase 1 | scraper_name, status, triggered_at, game_date |
| `nba_orchestration.phase_execution_log` | Orchestrators | phase_name, status, execution_timestamp |
| `nba_reference.processor_run_history` | Phases 2/3/4 | processor_name, phase, status, data_date |
| `nba_processing.precompute_processor_runs` | Phase 4 | processor_name, success, run_date |

---

## 2. Status Field Inconsistencies (Need Normalization)

| Table | Status Values |
|-------|---------------|
| scraper_execution_log | 'success', 'no_data', 'failed' |
| phase_execution_log | 'complete', 'partial', 'deadline_exceeded' |
| processor_run_history | 'running', 'success', 'failed', 'partial', 'skipped' |
| precompute_processor_runs | BOOLEAN `success` field |

**Normalization needed:**
```sql
CASE 
  WHEN status IN ('success', 'complete') THEN 'success'
  WHEN status IN ('failed', 'partial', 'deadline_exceeded') THEN 'failed'
  WHEN status = 'no_data' THEN 'no_data'
  WHEN status = 'skipped' THEN 'skipped'
END
```

---

## 3. Firestore Collections

**Pattern**: `{phase}_completion` (e.g., `phase3_completion`)

**Document ID**: `game_date` (YYYY-MM-DD)

**Dual-Write Strategy**:
1. Primary: Firestore (real-time)
2. Backup: BigQuery `nba_orchestration.phase_completions`

---

## 4. Existing Partial Implementation

**Location**: `monitoring/bigquery_views/`

| View | Coverage |
|------|----------|
| `pipeline_health_summary.sql` | Phases 3, 4, 5 only |
| `processor_error_summary.sql` | Error classification |
| `prediction_coverage_metrics.sql` | Phase 5 predictions |
| `pipeline_latency_metrics.sql` | End-to-end timing |

**Gaps:**
- ❌ No Phase 1 (scrapers)
- ❌ No Phase 2 (raw processing)
- ❌ No per-processor health
- ❌ No orchestrator data
- ❌ No staleness detection

---

## 5. Recommended Health Thresholds

```sql
CASE
  WHEN last_success_time IS NULL THEN 'NEVER_RAN'
  WHEN DATE_DIFF(CURRENT_DATE(), last_success_date, DAY) > 7 THEN 'STALE'
  WHEN failures_24h > 5 THEN 'UNHEALTHY'
  WHEN failures_24h > 0 THEN 'DEGRADED'
  ELSE 'HEALTHY'
END
```

**Existing thresholds from codebase:**
- Completion: ≥90% HEALTHY, ≥75% DEGRADED, <75% CRITICAL
- Latency: ≤3h HEALTHY, ≤6h DEGRADED, >6h SLOW

---

## 6. Implementation Plan

### Step 1: Create Unified UNION Query
```sql
-- Phase 1: Scrapers
SELECT 'phase1' as phase, scraper_name as processor_name, ...
FROM nba_orchestration.scraper_execution_log

UNION ALL

-- Phases 2/3/4: Processors
SELECT phase, processor_name, ...
FROM nba_reference.processor_run_history

UNION ALL

-- Phase 4: Precompute (alternative source)
SELECT 'phase4' as phase, processor_name, ...
FROM nba_processing.precompute_processor_runs
```

### Step 2: Create Materialized View
- Hourly scheduled query refresh
- Write to `nba_monitoring.pipeline_health_summary_materialized`

### Step 3: Add to /validate-daily
```sql
SELECT phase, processor_name, health_status, failures_24h
FROM nba_monitoring.pipeline_health_summary
WHERE health_status IN ('UNHEALTHY', 'STALE', 'NEVER_RAN')
ORDER BY health_status, failures_24h DESC
LIMIT 20;
```

---

## 7. Critical Considerations

**Failure Category Filtering** - Use to reduce noise:
```sql
WHERE failure_category NOT IN ('no_data_available')
```
This reduces alerts by 90%+ by excluding expected "no data" situations.

**Firestore vs BigQuery Latency:**
- Firestore: Real-time (seconds)
- BigQuery: 1-90 min lag
- Query Firestore for "today", BigQuery for history

---

## Summary

| Component | Status |
|-----------|--------|
| Phase 1 tracking | ❌ Not in current views |
| Phase 2 tracking | ❌ Not in current views |
| Phase 3/4/5 tracking | ✅ Partial implementation |
| Per-processor health | ❌ Need to add |
| Staleness detection | ❌ Need to add |
| Threshold definitions | ✅ Defined in codebase |

# Grafana Monitoring FAQ & Troubleshooting Guide

**File:** `docs/07-monitoring/grafana/faq-troubleshooting.md`
**Created:** 2025-11-30
**Purpose:** Quick answers to common monitoring questions
**Audience:** Operators, Developers, On-call

---

## Quick Reference: Which Dashboard Do I Use?

| Question | Dashboard | Panel |
|----------|-----------|-------|
| Is the pipeline healthy? | Pipeline Run History | Panel 1: Pipeline Health |
| Are processors succeeding? | Pipeline Run History | Panel 2: Success Rate |
| Which processors are failing? | Pipeline Run History | Panel 7: Processor Success Rates |
| Why did a processor fail? | Pipeline Run History | Panel 4: Recent Failed Runs |
| Did predictions run today? | Pipeline Run History | Panel 6: Phase 5 Predictions |
| Is there a stalled pipeline? | Pipeline Run History | Panel 11: Pipeline Latency |
| How do I trace a pipeline run? | Pipeline Run History | Panel 12: Pipeline Flow Trace |
| Are there data quality issues? | Data Quality | Panel 1: Data Quality Health |
| How many unresolved names? | Data Quality | Panel 2: Unresolved Names |
| Which circuit breakers are open? | Data Quality | Panel 3: Open Circuit Breakers |
| Is data complete for predictions? | Completeness | Panel 1-3: Completeness stats |
| Are scrapers running? | Daily Health Check | Use monitoring-guide.md queries |

---

## Common Questions

### Pipeline Health

#### Q: How do I check if the entire pipeline is working?

**Dashboard:** Pipeline Run History
**Panel:** 1. Pipeline Health

Look for:
- **HEALTHY** (green) = All phases working, >90% success rate
- **DEGRADED** (yellow) = Some failures, 70-90% success rate
- **UNHEALTHY** (red) = Major issues, <70% success rate
- **NO DATA** (blue) = No runs today (off-season or scrapers paused)

**Quick SQL:**
```sql
SELECT
  CASE
    WHEN COUNTIF(status = 'failed') = 0 THEN 'HEALTHY'
    WHEN COUNTIF(status = 'success') * 1.0 / COUNT(*) >= 0.9 THEN 'HEALTHY'
    WHEN COUNTIF(status = 'success') * 1.0 / COUNT(*) >= 0.7 THEN 'DEGRADED'
    ELSE 'UNHEALTHY'
  END as health
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date = CURRENT_DATE()
```

---

#### Q: Why is the pipeline showing UNHEALTHY?

**Dashboard:** Pipeline Run History

**Check these panels in order:**
1. **Panel 4: Failed Runs (Today)** - See which processors failed
2. **Panel 9: Recent Failed Runs** - Get error details
3. **Panel 7: Processor Success Rates** - Find worst performers

**Common causes:**
- BigQuery connection timeouts
- Missing upstream data (dependency failures)
- Code bugs (check Cloud Run logs)
- Circuit breaker open (check Data Quality dashboard)

---

#### Q: How do I check if predictions ran today?

**Dashboard:** Pipeline Run History
**Panel:** 6. Phase 5: Prediction Coordinator Runs

Look for:
- **status = SUCCESS** with today's date
- **predictions_generated** count (~450 for full slate)
- **duration_sec** should be consistent (not increasing)

If missing, check:
1. Did Phase 4 complete? (Panel 6: Health by Phase)
2. Is there a circuit breaker open? (Data Quality dashboard)
3. Check Cloud Run logs for prediction coordinator

---

### Debugging Failures

#### Q: A processor failed - how do I find out why?

**Dashboard:** Pipeline Run History
**Panel:** 9. Recent Failed Runs (Last 7 Days)

This shows:
- **started_at** - When it failed
- **processor_name** - Which processor
- **error_preview** - First 100 chars of error

**For full error details:**
```bash
# Check Cloud Run logs
gcloud run services logs read nba-phase3-analytics --region=us-west2 --limit=50
```

---

#### Q: The same processor keeps failing - what do I do?

**Dashboard:** Pipeline Run History
**Panel:** 7. Processor Success Rates (Worst First)

If a processor has <90% success rate:
1. Check error patterns in Panel 9
2. Look at Cloud Run logs for stack traces
3. Check if circuit breaker is triggered (Data Quality dashboard)
4. Verify upstream dependencies exist

**Circuit breaker check:**
```sql
SELECT processor_name, state, failure_count, last_error_message
FROM `nba-props-platform.nba_orchestration.circuit_breaker_state`
WHERE processor_name LIKE '%PROCESSOR_NAME%'
```

---

#### Q: How do I trace a specific pipeline execution?

**Dashboard:** Pipeline Run History
**Panel:** 12. Pipeline Flow Trace (Today - Chronological)

This shows all processors in execution order with:
- **phase** (color-coded)
- **processor_name**
- **status**
- **correlation_id** (for tracing)

**To trace by correlation ID:**
```sql
SELECT started_at, phase, processor_name, status, records_processed
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE JSON_VALUE(summary, '$.correlation_id') = 'YOUR_CORRELATION_ID'
ORDER BY started_at ASC
```

---

#### Q: The pipeline seems stuck - how do I check?

**Dashboard:** Pipeline Run History
**Panel:** 11. End-to-End Pipeline Latency

Look for:
- **phase5_status = PENDING** (yellow) - Phase 5 hasn't run yet
- **pipeline_latency_min > 60** (red) - Taking too long
- Missing Phase 5 rows = Pipeline never completed

**Check for stalled processors:**
```sql
SELECT processor_name, phase, started_at,
       TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) as minutes_running
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'running'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) > 60
```

---

### Data Quality

#### Q: How do I check if there are data quality issues?

**Dashboard:** Data Quality
**Panel:** 1. Data Quality Health

Look for:
- **HEALTHY** = <50 unresolved names, no open circuit breakers
- **WARNING** = 50-100 unresolved names OR some circuit breakers
- **CRITICAL** = >100 unresolved names OR >5 open circuit breakers

---

#### Q: What are unresolved player names and why do they matter?

**Dashboard:** Data Quality
**Panel:** 2. Unresolved Names + Panel 10. Unresolved Names Detail

**What they are:** Player names from data sources that can't be matched to our registry.

**Why they matter:**
- Unmatched names = missing player data
- Missing data = incomplete predictions
- High counts indicate data source changes or new players

**Common sources:**
- `nbac_gamebook` - NBA.com format changes
- `bdl_boxscores` - Ball Don't Lie API variations
- `espn_rosters` - ESPN naming differences

---

#### Q: A circuit breaker is OPEN - what does that mean?

**Dashboard:** Data Quality
**Panel:** 3. Open Circuit Breakers + Panel 8. Circuit Breaker States

**What it means:**
- Processor failed repeatedly (5+ times)
- System blocked further attempts to prevent cascade failures
- Processing for that phase is paused

**What to do:**
1. Check **last_error_message** in Panel 8
2. Fix the root cause
3. The circuit breaker will auto-reset after timeout (or manually reset)

**Check circuit breaker details:**
```sql
SELECT processor_name, state, failure_count, last_failure, last_error_message
FROM `nba-props-platform.nba_orchestration.circuit_breaker_state`
WHERE state = 'OPEN'
```

---

### Completeness & Production Readiness

#### Q: How do I check if data is complete for a game date?

**Dashboard:** Completeness
**Panel:** 1-3: Completeness overview stats

Look for:
- **is_production_ready = TRUE** for all required tables
- **completeness_percentage > 95%**
- No **circuit_breaker_active** flags

---

#### Q: Predictions didn't run but Phase 4 completed - why?

Possible causes:
1. **Data not production ready** - Check Completeness dashboard
2. **Circuit breaker open** - Check Data Quality dashboard
3. **Insufficient data** - Not enough player games for the date
4. **Pub/Sub issue** - Check Cloud Logging for Phase 4→5 trigger

**Debug query:**
```sql
-- Check if Phase 4 published completion
SELECT *
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_4_precompute'
  AND data_date = CURRENT_DATE()
  AND status = 'success'
```

---

### Performance

#### Q: How long should the pipeline take?

**Dashboard:** Pipeline Run History
**Panel:** 11. Pipeline Latency

**Expected times (game day):**
- Phase 2 (Raw): 5-15 minutes
- Phase 3 (Analytics): 5-10 minutes
- Phase 4 (Precompute): 5-10 minutes
- Phase 5 (Predictions): 2-5 minutes
- **Total end-to-end: 20-40 minutes**

**Warning thresholds:**
- Yellow: 30-60 minutes
- Red: >60 minutes

---

#### Q: Which processors are slowest?

**Dashboard:** Pipeline Run History
**Panel:** 10. Processing Duration by Processor

Shows average and P95 duration by processor. Focus on:
- Processors with increasing duration over time
- Processors taking >5 minutes regularly

---

### Scrapers (Phase 1)

#### Q: How do I check if scrapers are running?

**Dashboard:** Use queries from `monitoring-guide.md`

Or quick check:
```sql
SELECT
  scraper_name,
  COUNT(*) as runs_today,
  MAX(triggered_at) as last_run
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE DATE(triggered_at) = CURRENT_DATE()
GROUP BY scraper_name
ORDER BY last_run DESC
```

**Note:** If scrapers are paused (Cloud Scheduler jobs disabled), this will be empty.

---

#### Q: Scrapers aren't running - what do I check?

1. **Cloud Scheduler jobs:**
   ```bash
   gcloud scheduler jobs list --location=us-west2 | grep nba-
   ```
   Look for `PAUSED` status

2. **Enable a scraper:**
   ```bash
   gcloud scheduler jobs resume JOB_NAME --location=us-west2
   ```

3. **Check scraper service:**
   ```bash
   gcloud run services describe nba-phase1-scrapers --region=us-west2
   ```

---

## Troubleshooting Flowchart

```
Pipeline Issue Detected
         │
         ▼
┌─────────────────────┐
│ Check Pipeline      │
│ Health (Panel 1)    │
└─────────┬───────────┘
          │
    ┌─────┴─────┐
    │           │
    ▼           ▼
UNHEALTHY    HEALTHY
    │           │
    │           └─► Check specific phase
    │               you're concerned about
    ▼
┌─────────────────────┐
│ Check Failed Runs   │
│ (Panel 9)           │
└─────────┬───────────┘
          │
    ┌─────┴─────┐
    │           │
    ▼           ▼
Found        Not Found
Failures     Failures
    │           │
    │           └─► Check Circuit Breakers
    │               (Data Quality Dashboard)
    ▼
┌─────────────────────┐
│ Check Error Message │
│ + Cloud Run Logs    │
└─────────┬───────────┘
          │
    ┌─────┴─────┐
    │           │
    ▼           ▼
Transient    Persistent
Error        Error
    │           │
    │           └─► Fix code/config
    │               and redeploy
    ▼
Wait for retry
(Pub/Sub auto-retries)
```

---

## Quick Commands Reference

### Check Pipeline Status
```bash
# Pipeline health
bq query --use_legacy_sql=false "
SELECT phase, status, COUNT(*) as runs
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE data_date = CURRENT_DATE()
GROUP BY phase, status
ORDER BY phase"
```

### Check Failures
```bash
# Recent failures
bq query --use_legacy_sql=false "
SELECT started_at, processor_name, phase
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE status = 'failed' AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
ORDER BY started_at DESC
LIMIT 10"
```

### Check Circuit Breakers
```bash
# Open circuit breakers
bq query --use_legacy_sql=false "
SELECT processor_name, state, failure_count, last_error_message
FROM \`nba-props-platform.nba_orchestration.circuit_breaker_state\`
WHERE state IN ('OPEN', 'HALF_OPEN')"
```

### Check Data Quality
```bash
# Unresolved names count
bq query --use_legacy_sql=false "
SELECT COUNT(*) as unresolved
FROM \`nba-props-platform.nba_reference.unresolved_player_names\`
WHERE status = 'pending' OR status IS NULL"
```

---

## Related Documentation

| Topic | Document |
|-------|----------|
| Setup & Installation | `setup.md` |
| Pipeline Monitoring | `pipeline-monitoring.md` |
| Data Quality Monitoring | `data-quality-monitoring.md` |
| Daily Health Check | `daily-health-check.md` |
| Phase 1 Orchestration | `monitoring-guide.md` |
| Alert System | `../alerting/alert-system.md` |
| DLQ Recovery | `../../02-operations/dlq-recovery.md` |
| Orchestrator Monitoring | `../../02-operations/orchestrator-monitoring.md` |

---

**Last Updated:** 2025-11-30
**Version:** 1.0

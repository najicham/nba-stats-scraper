# Orchestration & Monitoring Improvements Plan

**Created:** December 27, 2025 (Session 174)
**Status:** Planning
**Priority:** Medium-High

---

## Executive Summary

The daily orchestration system works but has observability gaps that make debugging difficult. This document outlines improvements to make daily validation easier and more comprehensive.

**Current Pain Points:**
1. Can't easily query "what processors ran today" for Phase 2-5
2. Dependency failures only visible in Cloud Logging (30-day retention)
3. No structured tracking of Pub/Sub message delivery
4. Firestore state not easily queryable
5. Multiple scattered monitoring docs

---

## Current State Assessment

### What Works Well ✅

| Capability | Status | Notes |
|------------|--------|-------|
| Phase 1 Scraper Logging | Excellent | `nba_orchestration.scraper_execution_log` has full visibility |
| Validation Script | Good | `bin/validate_pipeline.py` comprehensive but underutilized |
| Firestore State | Working | Tracks completion but hard to query |
| Run History Table | Partial | `nba_reference.processor_run_history` exists but incomplete |
| Email Alerts | Working | Rate-limited, configured |
| Cloud Schedulers | Working | All 20+ jobs enabled |

### What's Missing ❌

| Gap | Impact | Priority |
|-----|--------|----------|
| Centralized processor execution log | Can't track Phase 2-5 runs | High |
| Dependency check log | Can't debug "why did it fail?" | Medium-High |
| Pub/Sub delivery tracking | Don't know retry count | Low |
| Daily summary dashboard | Manual checks required | Medium |
| Automated validation | No proactive alerting | Medium |

---

## Improvement Plan

### Phase 1: Quick Wins (1-2 days)

These can be done with minimal code changes:

#### 1.1 Create Daily Health Summary Script

Create a single script that runs all validation checks:

```bash
bin/monitoring/daily_health_summary.sh
```

**What it does:**
- Runs `validate_pipeline.py` for yesterday
- Checks all services healthy
- Checks orchestrator functions
- Checks Pub/Sub backlogs/DLQs
- Checks Firestore completion state
- Outputs summary with ✅/❌ indicators

**Effort:** 2-3 hours

#### 1.2 Add Morning Validation Scheduler

Create Cloud Scheduler job that:
- Runs at 8 AM ET daily
- Calls health check endpoint
- Sends email summary of issues

```bash
gcloud scheduler jobs create http daily-validation-check \
  --schedule="0 8 * * *" \
  --time-zone="America/New_York" \
  --uri="https://nba-phase1-scrapers-xxx.run.app/daily-health" \
  --oidc-service-account-email=scheduler-invoker@nba-props-platform.iam.gserviceaccount.com
```

**Effort:** 2-3 hours

#### 1.3 Update Run History Logging

Ensure all Phase 2-5 processors log to `nba_reference.processor_run_history`:

**Current state:** Some processors log, some don't (RunHistoryMixin exists)

**Fix:** Audit all processors, ensure `record_run_complete()` called consistently

**Effort:** 2-4 hours (audit + fixes)

---

### Phase 2: Better Tracking (1 week)

#### 2.1 Create Processor Execution Log Table

Similar to `scraper_execution_log` but for Phase 2-5:

```sql
CREATE TABLE nba_orchestration.processor_execution_log (
  execution_id STRING NOT NULL,
  processor_name STRING NOT NULL,
  phase STRING NOT NULL,  -- 'phase2', 'phase3', 'phase4', 'phase5'
  triggered_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP,
  duration_seconds FLOAT64,
  status STRING NOT NULL,  -- 'success', 'failed', 'partial', 'skipped'

  -- Context
  data_date DATE,
  trigger_source STRING,  -- 'pubsub', 'scheduler', 'manual', 'orchestrator'
  pubsub_message_id STRING,
  correlation_id STRING,

  -- Results
  records_processed INT64,
  records_created INT64,
  records_updated INT64,

  -- Errors
  error_type STRING,
  error_message STRING,

  -- Metadata
  input_params JSON,
  cloud_run_revision STRING,
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(triggered_at)
CLUSTER BY processor_name, status;
```

**Effort:** 6-8 hours total
- Table creation: 1 hour
- Update all processors: 4-5 hours
- Testing: 2 hours

#### 2.2 Create Dependency Check Log Table

Track what dependencies were checked and results:

```sql
CREATE TABLE nba_orchestration.dependency_check_log (
  check_id STRING NOT NULL,
  check_time TIMESTAMP NOT NULL,
  processor_name STRING NOT NULL,
  data_date DATE,

  -- What was checked
  required_table STRING NOT NULL,
  required_partition STRING,  -- e.g., "game_date=2025-12-27"

  -- Result
  check_result STRING NOT NULL,  -- 'PASS', 'FAIL', 'SKIP'
  row_count INT64,

  -- If failed
  error_message STRING,
  fallback_available BOOLEAN,
  fallback_used BOOLEAN,

  -- Link to execution
  execution_id STRING
)
PARTITION BY DATE(check_time);
```

**Effort:** 4-6 hours

#### 2.3 Daily Health Dashboard (Looker/Data Studio)

Create simple dashboard showing:
- Last 7 days: games vs data processed
- Today's status: Phase 1-5 completion
- Errors in last 24h by service
- Predictions generated vs expected

**Effort:** 4-6 hours (using BigQuery as data source)

---

### Phase 3: Proactive Alerting (2 weeks)

#### 3.1 Automated Validation with Alerts

Create Cloud Function that:
- Runs `validate_pipeline.py` for yesterday at 8 AM
- Compares actual vs expected
- Sends alert if significant gaps

```python
# Pseudocode
expected_games = get_schedule_for_date(yesterday)
actual_boxscores = query_boxscore_count(yesterday)

if actual_boxscores < expected_games:
    send_alert(f"Missing boxscores: {expected_games - actual_boxscores} games")
```

**Effort:** 8-10 hours

#### 3.2 Firestore State Monitoring

Create function that:
- Checks Firestore completion docs at 2 PM ET
- Verifies all phases triggered
- Alerts if not

**Effort:** 4-6 hours

#### 3.3 DLQ Auto-Alerting

Cloud Function triggered by DLQ messages:
- Parse failed message
- Send immediate alert with context
- Log to BigQuery for analysis

**Effort:** 4-6 hours

---

### Phase 4: Long-Term (1 month+)

#### 4.1 Grafana Dashboards

If Grafana is set up:
- Real-time pipeline status
- Historical trends
- Alert integration

#### 4.2 Data Quality Scores

Track data quality metrics:
- Fallback source usage rate
- Missing player percentage
- Prediction confidence distribution

#### 4.3 ML Feature Store Quality

Monitor Phase 4 output:
- Feature completeness
- Feature freshness
- Anomaly detection

---

## Implementation Priority

| Item | Priority | Effort | Impact |
|------|----------|--------|--------|
| 1.1 Daily Health Script | High | 2-3h | High |
| 1.2 Morning Validation Scheduler | High | 2-3h | High |
| 1.3 Fix Run History Logging | High | 2-4h | Medium |
| 2.1 Processor Execution Log | Medium | 6-8h | High |
| 2.2 Dependency Check Log | Medium | 4-6h | Medium |
| 2.3 Daily Dashboard | Medium | 4-6h | Medium |
| 3.1 Automated Validation Alerts | Low | 8-10h | High |
| 3.2 Firestore Monitoring | Low | 4-6h | Medium |
| 3.3 DLQ Auto-Alerting | Low | 4-6h | Medium |

**Recommended order:**
1. Phase 1 items (quick wins)
2. Item 2.1 (processor log)
3. Item 2.3 (dashboard)
4. Item 3.1 (automated alerts)
5. Rest as time permits

---

## Success Metrics

After improvements, we should be able to:

1. **Answer in <30 seconds:**
   - "Did yesterday's pipeline complete successfully?"
   - "What failed and why?"
   - "Are today's predictions ready?"

2. **Automated alerts for:**
   - Phase not completing by expected time
   - Data missing for completed games
   - DLQ messages (immediate)
   - Service health issues

3. **Historical analysis:**
   - Trend of processing times
   - Error rates by processor
   - Dependency failure patterns

---

## Related Documents

- `docs/07-monitoring/observability-gaps.md` - Detailed gap analysis
- `docs/02-operations/daily-validation-checklist.md` - Current validation process
- `docs/01-architecture/orchestration/orchestrators.md` - How orchestration works

---

*Created: December 27, 2025*
*Owner: Platform Team*

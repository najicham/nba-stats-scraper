# Pipeline Resilience Plan

**Created:** 2026-01-24
**Status:** In Progress
**Priority:** P0

---

## Executive Summary

Following the 2026-01-24 orchestration failure (processor name mismatch causing 1/6 Phase 2 completion), this plan outlines improvements to make the pipeline more resilient with auto-retry capabilities and comprehensive logging.

---

## Root Causes Addressed

| Issue | Impact | Root Cause |
|-------|--------|------------|
| Processor name mismatch | Phase 2 showed 1/6 complete | Config names didn't match workflows.yaml |
| BigQuery metadata error | Silent logging failures | Dict not serialized to JSON |
| Cloud Function OOM | Startup failures | 256MB insufficient for orchestrators |
| Missing shared modules | Deploy failures | __init__.py imports missing files |
| AttributeError in processor | Backfill failures | Call to non-existent method |

---

## Implemented Fixes (2026-01-24)

### 1. Validation Scripts

| Script | Purpose | When to Run |
|--------|---------|-------------|
| `bin/validation/validate_orchestration_config.py` | Ensures processor names match workflows.yaml | Before orchestrator deploy |
| `bin/validation/validate_cloud_function_imports.py` | Ensures all shared modules exist | Before any Cloud Function deploy |
| `bin/monitoring/check_cloud_resources.sh` | Monitors memory allocations | Daily / before deploy |

### 2. Deploy Script Pre-checks

All orchestrator deploy scripts now include:
```bash
# Validate orchestration config
python bin/validation/validate_orchestration_config.py || exit 1

# Validate Cloud Function imports
python bin/validation/validate_cloud_function_imports.py --function FUNCTION_NAME || exit 1
```

### 3. Memory Standardization

All orchestrator deploy scripts updated: `MEMORY="256MB"` → `MEMORY="512MB"`

### 4. Simplified Cloud Function Imports

All Cloud Function `shared/utils/__init__.py` files simplified to only import modules that exist locally.

---

## Proposed Resilience Improvements

### Phase 1: Auto-Retry System (P0)

#### 1.1 Failed Processor Recovery Table

Create BigQuery table to track failed processors for auto-retry:

```sql
CREATE TABLE nba_orchestration.failed_processor_queue (
  id STRING,
  game_date DATE,
  phase STRING,
  processor_name STRING,
  error_message STRING,
  error_type STRING,  -- 'transient' or 'permanent'
  retry_count INT64,
  max_retries INT64 DEFAULT 3,
  first_failure_at TIMESTAMP,
  last_retry_at TIMESTAMP,
  next_retry_at TIMESTAMP,
  status STRING,  -- 'pending', 'retrying', 'succeeded', 'failed_permanent'
  resolution_notes STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP
)
PARTITION BY game_date;
```

#### 1.2 Auto-Retry Cloud Function

Create `auto-retry-processor` Cloud Function:
- Triggered every 15 minutes by Cloud Scheduler
- Queries `failed_processor_queue` for pending retries
- Triggers appropriate processor via Pub/Sub
- Updates retry count and status

```python
def auto_retry_failed_processors():
    """
    1. Query failed_processor_queue WHERE status='pending' AND next_retry_at <= NOW()
    2. For each failed processor:
       a. Publish retry message to appropriate Pub/Sub topic
       b. Update status to 'retrying'
       c. Increment retry_count
    3. If retry_count >= max_retries, mark as 'failed_permanent'
    4. Log all actions to nba_orchestration.retry_audit_log
    """
```

#### 1.3 Error Classification

Classify errors as transient (auto-retry) or permanent (alert only):

| Error Type | Classification | Action |
|------------|----------------|--------|
| Connection timeout | Transient | Auto-retry with backoff |
| Rate limit (429) | Transient | Auto-retry with delay |
| OOM | Transient | Auto-retry (if memory increased) |
| Schema mismatch | Permanent | Alert, require manual fix |
| Missing table | Permanent | Alert, require manual fix |
| Code bug (AttributeError) | Permanent | Alert, require code fix |

### Phase 2: Comprehensive Audit Logging (P0)

#### 2.1 Pipeline Event Log Table

```sql
CREATE TABLE nba_orchestration.pipeline_event_log (
  event_id STRING,
  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  event_type STRING,  -- 'phase_start', 'phase_complete', 'processor_start', 'processor_complete', 'error', 'retry', 'recovery'
  phase STRING,
  processor_name STRING,
  game_date DATE,
  correlation_id STRING,

  -- Context
  trigger_source STRING,  -- 'scheduled', 'manual', 'retry', 'backfill'
  parent_event_id STRING,  -- For tracking retry chains

  -- Metrics
  duration_seconds FLOAT64,
  records_processed INT64,

  -- Error details (if applicable)
  error_type STRING,
  error_message STRING,
  stack_trace STRING,

  -- Resolution (if applicable)
  resolution_action STRING,
  resolution_by STRING,  -- 'auto' or 'manual'

  -- Metadata
  metadata JSON
)
PARTITION BY DATE(timestamp)
CLUSTER BY event_type, phase, processor_name;
```

#### 2.2 Event Logging Integration

Add logging to all processors:

```python
# At processor start
log_pipeline_event(
    event_type='processor_start',
    phase='phase_3',
    processor_name='player_game_summary',
    game_date=game_date,
    correlation_id=correlation_id,
    trigger_source='scheduled'
)

# At processor completion
log_pipeline_event(
    event_type='processor_complete',
    phase='phase_3',
    processor_name='player_game_summary',
    game_date=game_date,
    correlation_id=correlation_id,
    duration_seconds=elapsed,
    records_processed=count
)

# On error
log_pipeline_event(
    event_type='error',
    phase='phase_3',
    processor_name='player_game_summary',
    game_date=game_date,
    error_type=classify_error(e),
    error_message=str(e),
    stack_trace=traceback.format_exc()
)
```

### Phase 3: Self-Healing Dashboard (P1)

#### 3.1 Recovery Dashboard View

```sql
CREATE VIEW nba_orchestration.v_recovery_dashboard AS
SELECT
  game_date,
  phase,
  processor_name,
  status,
  retry_count,
  error_type,
  LEFT(error_message, 200) as error_summary,
  first_failure_at,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), first_failure_at, MINUTE) as minutes_since_failure,
  CASE
    WHEN status = 'pending' AND retry_count < max_retries THEN 'Will auto-retry'
    WHEN status = 'retrying' THEN 'Retry in progress'
    WHEN status = 'failed_permanent' THEN 'NEEDS MANUAL FIX'
    ELSE status
  END as action_needed
FROM nba_orchestration.failed_processor_queue
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY first_failure_at DESC;
```

#### 3.2 Daily Recovery Summary Email

Extend daily health email to include:
- Failed processors requiring manual intervention
- Auto-retry success/failure rates
- Processors recovered automatically vs manually

### Phase 4: Proactive Monitoring (P1)

#### 4.1 Memory Warning Alert

Create Cloud Monitoring alert:
```yaml
displayName: "Cloud Function Memory Warning"
conditions:
  - displayName: "Memory usage > 80%"
    conditionThreshold:
      filter: 'resource.type="cloud_run_revision" AND metric.type="run.googleapis.com/container/memory/utilizations"'
      comparison: COMPARISON_GT
      thresholdValue: 0.8
      duration: "60s"
```

#### 4.2 Processor Completion Alert

Alert if Phase N doesn't complete within expected window:
```yaml
displayName: "Phase 2 Completion Timeout"
conditions:
  - displayName: "Phase 2 not complete after 2 hours"
    conditionAbsent:
      filter: 'resource.type="cloud_run_revision" AND jsonPayload.message=~"Phase 2.*complete"'
      duration: "7200s"
```

#### 4.3 Config Drift Detection

Daily job to detect config drift:
```bash
#!/bin/bash
# bin/monitoring/check_config_drift.sh

# Check orchestration config vs workflows.yaml
python bin/validation/validate_orchestration_config.py || \
  send_slack_alert "Orchestration config drift detected"

# Check Cloud Function imports
python bin/validation/validate_cloud_function_imports.py || \
  send_slack_alert "Cloud Function import issues detected"

# Check memory allocations
./bin/monitoring/check_cloud_resources.sh --check-logs | grep -q "LOW" && \
  send_slack_alert "Low memory allocation detected"
```

---

## Implementation Roadmap

### Week 1 (Immediate) - ✅ COMPLETE (Jan 25)

- [x] Create validation scripts
- [x] Add pre-deploy checks to orchestrator scripts
- [x] Fix Cloud Function __init__.py files
- [x] Standardize memory to 512MB
- [x] Create failed_processor_queue table (2026-01-25)
- [x] Create pipeline_event_log table (2026-01-25)
- [x] Create pipeline_logger utility (2026-01-25)
- [x] Deploy auto-retry Cloud Function (2026-01-25)
- [x] Create Cloud Scheduler job for auto-retry (2026-01-25)
- [x] Redeploy all orchestrators with fixes (2026-01-25)

### Week 2 - ✅ COMPLETE (Jan 25)

- [x] Implement auto-retry Cloud Function (done in Week 1)
- [x] Add event logging to Phase 3 analytics processors (analytics_base.py)
- [x] Add event logging to Phase 4 precompute processors (precompute_base.py)
- [x] Create recovery dashboard view (nba_orchestration.v_recovery_dashboard)
- [x] Set up memory warning alert (bin/monitoring/setup_memory_alerts.sh)
- [x] Extend daily health email with recovery stats (bin/alerts/daily_summary/main.py)
- [x] Implement config drift detection (bin/validation/detect_config_drift.py)
- [x] Create e2e tests for auto-retry (tests/e2e/test_auto_retry.py)

### Week 3

- [ ] Add Phase completion timeout alerts
- [ ] Create runbook for manual recovery procedures

### Week 4

- [ ] Test auto-retry with simulated failures
- [ ] Document all recovery procedures
- [ ] Train on new monitoring tools
- [ ] Retrospective and refinements

---

## Quick Reference: Recovery Commands

### Check Pipeline Health
```bash
# Full health check
/home/naji/code/nba-stats-scraper/bin/monitoring/daily_health_check.sh $(date +%Y-%m-%d)

# Check orchestration state
python bin/monitoring/check_orchestration_state.py $(date +%Y-%m-%d)

# Check memory allocations
./bin/monitoring/check_cloud_resources.sh --check-logs
```

### Manual Recovery
```bash
# Reprocess Phase 3 for specific dates
./bin/backfill/run_year_phase3.sh --start-date 2026-01-23 --end-date 2026-01-24

# Clear stuck Firestore state
python3 -c "
from google.cloud import firestore
db = firestore.Client()
db.collection('phase2_completion').document('2026-01-24').delete()
print('State cleared')
"

# Trigger scraper workflow
curl -X POST https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/run \
  -H "Content-Type: application/json" \
  -d '{"workflow": "post_game_window_3", "game_date": "2026-01-24"}'
```

### Pre-Deployment Validation
```bash
# Before deploying any orchestrator
python bin/validation/validate_orchestration_config.py
python bin/validation/validate_cloud_function_imports.py
./bin/monitoring/check_cloud_resources.sh
```

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Mean time to detect failure | 4+ hours | < 15 minutes |
| Auto-recovery rate | 0% | > 80% for transient errors |
| Manual intervention required | 100% | < 20% |
| Config drift detection | Reactive | Proactive (daily) |
| Pre-deploy validation | None | 100% of deploys |

---

## Related Documents

- [Troubleshooting Runbook](../../00-orchestration/troubleshooting.md)
- [Services Inventory](../../00-orchestration/services.md)
- [Daily Operations Runbook](../../02-operations/daily-operations-runbook.md)

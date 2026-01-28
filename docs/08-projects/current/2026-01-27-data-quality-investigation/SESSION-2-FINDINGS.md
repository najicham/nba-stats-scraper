# Session 2 Findings - 2026-01-28

**Date**: 2026-01-28
**Status**: Investigation Complete, Issues Found

---

## Deployment Status

| Task | Status | Details |
|------|--------|---------|
| Schema changes | ✅ Complete | 13 columns added to player_game_summary, 3 to team_offense |
| Cloud Run deploy | ✅ Complete | nba-phase4-precompute-processors revision 00060-g4z active |
| Git push | ✅ Complete | 2 commits pushed to origin/main |

---

## Critical Issue Found: Pipeline Stalled

### Root Cause: Missing Module in Orchestrator

**Service**: `phase3-to-phase4-orchestrator`
**Error**: `ModuleNotFoundError: No module named 'shared.utils'`
**Impact**: Phase 4 and Phase 5 not triggered since Jan 25

**Error location**: `orchestration/shared/utils/bigquery_utils.py:23`
```python
from shared.utils.retry_with_jitter import retry_with_jitter
```

**Why it failed**: The orchestrator container doesn't have the `shared/` module from the main repo. The import path references `shared.utils` which doesn't exist in the orchestrator's build context.

### Immediate Fix Required

Option 1: Fix the import path in `bigquery_utils.py` to use relative imports
Option 2: Update the orchestrator Dockerfile to include the shared module
Option 3: Redeploy the orchestrator with corrected build context

---

## Other Issues Found

### 1. Missing Pub/Sub Topic
- **Topic**: `nba-scraper-trigger` returns 404
- **Impact**: Phase 3 can't trigger missing boxscore scrapes
- **Severity**: P2 (non-blocking, has fallback)

### 2. Boxscore Completeness
- **Current**: 6/7 games (85.7%) for Jan 27
- **Missing**: 1 game not scraped
- **Severity**: P3 (partial data)

### 3. High Usage Rates (Non-Issue)
- Quenton Jackson: 80.6% (1 minute, garbage time)
- Nahshon Hyland: 68.2% (3 minutes, garbage time)
- **Status**: Legitimate values, not calculation errors

---

## Observability Gaps Identified

During this investigation, we identified several observability gaps that made debugging harder:

### Gap 1: No Centralized Error Table
**Problem**: Errors only visible in Cloud Run logs
**What we did**: Manually checked logs for 5+ services
**Solution**: Create `nba_orchestration.service_errors` table

```sql
CREATE TABLE nba_orchestration.service_errors (
  timestamp TIMESTAMP,
  service_name STRING,
  phase STRING,
  error_type STRING,  -- 'module_not_found', 'timeout', 'quota_exceeded'
  error_message STRING,
  stack_trace STRING,
  game_date DATE,
  severity STRING  -- 'critical', 'error', 'warning'
);
```

### Gap 2: No "Last Successful Run" Dashboard
**Problem**: No easy way to see when each phase last ran successfully
**What we did**: Query multiple tables and logs
**Solution**: Create `nba_orchestration.pipeline_health_summary` view

```sql
CREATE VIEW nba_orchestration.pipeline_health_summary AS
SELECT
  phase,
  processor_name,
  MAX(CASE WHEN status = 'success' THEN game_date END) as last_success_date,
  MAX(CASE WHEN status = 'success' THEN completed_at END) as last_success_time,
  COUNT(CASE WHEN status = 'failed' AND completed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR) THEN 1 END) as failures_last_24h
FROM nba_orchestration.phase_completions
GROUP BY phase, processor_name;
```

### Gap 3: No Alert on Phase Execution Gaps
**Problem**: phase_execution_log had no entries for Jan 26-27, but no alert
**What we did**: Discovered gap while querying
**Solution**: Add Cloud Monitoring alert for stale phase execution

### Gap 4: Validation Skills Don't Check Module Errors
**Problem**: /validate-daily doesn't catch service deployment issues
**Solution**: Add check for recent service errors in logs

---

## Recommendations

### Immediate (Today)
1. **Fix orchestrator module import** - Either fix import path or redeploy with shared module
2. **Manually trigger Phase 4** for Jan 26-27 to backfill predictions

### Short-term (This Week)
1. Create `service_errors` table and add logging
2. Create `pipeline_health_summary` view
3. Add Phase execution gap check to /validate-daily
4. Add Cloud Monitoring alert for stale phases

### Medium-term
1. Build unified observability dashboard
2. Add service deployment validation (check required modules exist)
3. Implement circuit breaker status visibility in validation

---

## Files to Update

| File | Change |
|------|--------|
| `orchestration/shared/utils/bigquery_utils.py` | Fix import path |
| `.claude/skills/validate-daily/SKILL.md` | Add Phase execution gap check |
| `monitoring/queries/` | Add service_errors and pipeline_health queries |

---

## Next Steps for Next Session

```
Continue from 2026-01-28 session.

## Completed
- Schema changes deployed
- Phase 4 precompute service deployed
- Root cause of pipeline stall identified (missing module)

## TODO
1. Fix orchestrator module import (phase3-to-phase4-orchestrator)
2. Redeploy orchestrator
3. Backfill predictions for Jan 26-27
4. Implement observability improvements:
   - service_errors table
   - pipeline_health_summary view
   - Phase execution gap alerts

## Reference
docs/08-projects/current/2026-01-27-data-quality-investigation/SESSION-2-FINDINGS.md
```

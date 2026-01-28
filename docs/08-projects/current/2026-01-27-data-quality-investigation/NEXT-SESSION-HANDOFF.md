# Next Session Handoff - Fix Orchestrators + Improve Observability

**Date**: 2026-01-28
**Commit**: 7ff0185f

---

## Copy This Prompt to Start Next Session

```
Continue data quality work from 2026-01-28 session.

## Context
We deployed schema changes and Phase 4 service successfully, then ran validation
and discovered the pipeline has been stalled since Jan 25. Root cause: the
phase3-to-phase4-orchestrator has a ModuleNotFoundError (shared.utils missing).

## P0 - Fix Production (Do First)

### 1. Fix Orchestrator Module Imports
7 files in orchestration/shared/utils/ import from 'shared.utils' which doesn't
exist in Cloud Function deployments. Need to change to 'orchestration.shared.utils'.

Files to fix:
- orchestration/shared/utils/bigquery_utils.py (lines 23-24)
- orchestration/shared/utils/bigquery_utils_v2.py
- orchestration/shared/utils/odds_preference.py
- orchestration/shared/utils/odds_player_props_preference.py
- orchestration/shared/utils/processor_alerting.py
- orchestration/shared/utils/data_freshness_checker.py
- orchestration/shared/utils/phase_execution_logger.py

May need to copy gcp_config.py from shared/config/ to orchestration/shared/utils/

### 2. Redeploy Orchestrators
After fixing imports:
- gcloud run deploy phase3-to-phase4-orchestrator --source=orchestration/cloud_functions/phase3_to_phase4 --region=us-west2
- gcloud run deploy phase4-to-phase5-orchestrator --source=orchestration/cloud_functions/phase4_to_phase5 --region=us-west2

### 3. Backfill Missing Predictions
Manually trigger Phase 4 for Jan 26, 27 to generate predictions.

## P1 - Improve Observability (After P0)

### 1. Update /validate-daily Skill
Add "Phase 0.5" checks to detect stalled orchestrators:
- Query for missing phase_execution_log entries
- Query for stalled orchestrators (started but not completed)
- Query for phase transition timing gaps

### 2. Create Pipeline Health View
Enhance existing monitoring/bigquery_views/pipeline_health_summary.sql to show:
- Last successful run per phase/processor
- Failures in last 24h
- Health status (HEALTHY/DEGRADED/UNHEALTHY/STALE)

### 3. (Optional) Create service_errors Table
Centralized error logging for all Cloud Run services.

## Reference Documents
- docs/08-projects/current/2026-01-27-data-quality-investigation/MASTER-ACTION-LIST.md
- docs/08-projects/current/2026-01-27-data-quality-investigation/SESSION-2-FINDINGS.md
```

---

## Session 2 Summary (What Was Done)

| Task | Status |
|------|--------|
| Deploy BigQuery schema (16 columns) | ✅ Complete |
| Deploy Phase 4 precompute service | ✅ Complete |
| Push commits to origin/main | ✅ Complete |
| Run /validate-daily | ✅ Complete |
| Investigate pipeline stall | ✅ Complete |
| Identify root cause (ModuleNotFoundError) | ✅ Complete |
| Explore observability improvements | ✅ Complete |
| Create master action list | ✅ Complete |
| Fix orchestrator imports | ⏳ Next session |
| Update validation skills | ⏳ Next session |

---

## Files Created This Session

1. `SESSION-2-FINDINGS.md` - Investigation results, root cause analysis
2. `MASTER-ACTION-LIST.md` - Prioritized action items with effort estimates
3. This handoff document

---

## Quick Reference: P0 Fix

**The error**:
```
File: orchestration/shared/utils/bigquery_utils.py:23
Error: ModuleNotFoundError: No module named 'shared.utils'
```

**The fix**:
```python
# BEFORE (broken):
from shared.utils.retry_with_jitter import retry_with_jitter
from shared.config.gcp_config import get_project_id

# AFTER (fixed):
from orchestration.shared.utils.retry_with_jitter import retry_with_jitter
from orchestration.shared.utils.gcp_config import get_project_id
```

---

## Validation Skill Improvements to Make

### Add to /validate-daily (Phase 0.5)

```sql
-- Query 1: Missing phase execution logs
WITH expected_phases AS (
  SELECT 'phase2_to_phase3' as phase_name UNION ALL
  SELECT 'phase3_to_phase4' UNION ALL
  SELECT 'phase4_to_phase5'
),
actual_logs AS (
  SELECT DISTINCT phase_name
  FROM nba_orchestration.phase_execution_log
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
)
SELECT e.phase_name,
  CASE WHEN a.phase_name IS NULL THEN 'MISSING' ELSE 'EXISTS' END as status
FROM expected_phases e
LEFT JOIN actual_logs a USING (phase_name);

-- Query 2: Phase transition timing gaps
SELECT
  phase_name,
  TIMESTAMP_DIFF(execution_timestamp,
    LAG(execution_timestamp) OVER (ORDER BY execution_timestamp), MINUTE) as gap_minutes,
  CASE
    WHEN gap_minutes > 30 THEN 'CRITICAL'
    WHEN gap_minutes > 15 THEN 'WARNING'
    ELSE 'OK'
  END as status
FROM nba_orchestration.phase_execution_log
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);
```

### Add Known Issue #8

```markdown
8. **Phase Orchestrator Stalled** ⚠️ WATCH FOR THIS
   - Symptom: phase_execution_log has no entry for expected phase
   - Impact: Downstream phases don't run, stale cache, missing predictions
   - Detection: Use Phase 0.5 checks
   - Fix: Check orchestrator Cloud Run logs, fix imports, redeploy
```

---

## Commits This Session

```
7ff0185f docs: Add master action list for data quality and observability
faf81353 docs: Add session 2 findings - orchestrator module issue discovered
```

---

## Effort Estimates

| Priority | Task | Hours |
|----------|------|-------|
| P0-1 | Fix orchestrator imports | 2-3 |
| P0-2 | Redeploy + backfill | 1 |
| P1-1 | Update /validate-daily skill | 3-4 |
| P1-2 | Pipeline health view | 4-6 |
| P1-3 | Service errors table | 8-10 |
| **Total** | | **18-24** |

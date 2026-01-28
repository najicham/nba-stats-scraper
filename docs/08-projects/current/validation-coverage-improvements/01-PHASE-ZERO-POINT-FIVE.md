# Phase 0.5 Checks - Orchestrator Health Detection

**Priority**: P1 (Critical)
**Effort**: 3-4 hours
**Status**: Investigation

---

## Problem Statement

The `phase3-to-phase4-orchestrator` was failing silently for 2+ days (Jan 25-28) due to a `ModuleNotFoundError`. Our current validation system didn't detect this because:

1. `/validate-daily` only checks Phase 2/3/4 processor completions
2. No checks for orchestrator health (the bridges between phases)
3. No phase execution log gap detection
4. No service deployment error detection

---

## What We Need

Add "Phase 0.5" checks that run BEFORE the main validation to catch:

### Check 1: Missing Phase Execution Logs
```sql
-- Query: Detect missing orchestrator runs
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
  CASE WHEN a.phase_name IS NULL THEN 'MISSING' ELSE 'OK' END as status
FROM expected_phases e
LEFT JOIN actual_logs a USING (phase_name);
```

### Check 2: Stalled Orchestrators
```sql
-- Query: Detect orchestrators that started but didn't complete
SELECT 
  phase_name,
  game_date,
  start_time,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), start_time, MINUTE) as minutes_stalled
FROM nba_orchestration.phase_execution_log
WHERE status IN ('started', 'running')
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), start_time, MINUTE) > 30
ORDER BY start_time;
```

### Check 3: Phase Transition Timing Gaps
```sql
-- Query: Detect gaps between phase completions
WITH phase_times AS (
  SELECT
    game_date,
    phase_name,
    MAX(execution_timestamp) as completed_at
  FROM nba_orchestration.phase_execution_log
  WHERE status = 'complete'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY game_date, phase_name
)
SELECT
  p1.game_date,
  p1.phase_name as from_phase,
  p2.phase_name as to_phase,
  TIMESTAMP_DIFF(p2.completed_at, p1.completed_at, MINUTE) as gap_minutes
FROM phase_times p1
JOIN phase_times p2 ON p1.game_date = p2.game_date
WHERE (p1.phase_name = 'phase2_to_phase3' AND p2.phase_name = 'phase3_to_phase4')
   OR (p1.phase_name = 'phase3_to_phase4' AND p2.phase_name = 'phase4_to_phase5')
HAVING gap_minutes > 60;  -- Alert if >60 min gap
```

### Check 4: Service Deployment Errors (from Cloud Logging)
```sql
-- Query: Check for recent service errors in Cloud Logging export
SELECT
  timestamp,
  resource.labels.service_name,
  jsonPayload.message,
  severity
FROM `nba-props-platform.cloud_logging.run_googleapis_com_stderr`
WHERE timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND severity = 'ERROR'
  AND jsonPayload.message LIKE '%ModuleNotFoundError%'
ORDER BY timestamp DESC
LIMIT 50;
```

---

## Implementation Plan

### Step 1: Update `/validate-daily` Skill
File: `.claude/skills/validate-daily/SKILL.md`

Add new Phase 0.5 section before existing checks:

```markdown
## Phase 0.5: Orchestrator Health (Run First!)

Before checking processors, verify the orchestrators are healthy:

1. Check `nba_orchestration.phase_execution_log` for yesterday
2. Verify all 3 phase transitions have logs
3. Check for stalled orchestrators (>30 min running)
4. Check for phase timing gaps (>60 min between phases)

**If ANY Phase 0.5 check fails**: Stop and report immediately!
```

### Step 2: Create BigQuery Views
Create reusable views for orchestrator health:

```sql
-- monitoring/bigquery_views/orchestrator_health.sql
CREATE OR REPLACE VIEW nba_monitoring.orchestrator_health AS
...
```

### Step 3: Add Slack Alert for Critical Gaps
When Phase 0.5 detects issues, send immediate Slack alert (not just 6 AM email).

---

## Investigation Questions

Before implementing, investigate:

1. What is the exact schema of `nba_orchestration.phase_execution_log`?
2. Are there other tables that track orchestrator state (Firestore)?
3. What's the expected timing for each phase transition?
4. Do we have Cloud Logging export to BigQuery for stderr?
5. What Slack webhook should critical alerts use?

---

## Success Criteria

After implementation:
- [ ] Missing orchestrator runs detected within 30 min
- [ ] Stalled orchestrators detected within 30 min
- [ ] Phase timing gaps detected within 1 hour
- [ ] Service deployment errors surfaced in validation output

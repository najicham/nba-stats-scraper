# Grafana Daily Health Check Guide - NBA Orchestration

**File:** `docs/monitoring/02-grafana-daily-health-check.md`
**Created:** 2025-11-14 16:24 PST
**Last Updated:** 2025-11-15 (moved from orchestration/ to monitoring/)
**Purpose:** Quick daily monitoring dashboard for NBA orchestration system health
**Status:** Current

---

## Overview

This guide provides the **essential queries** for a simple, at-a-glance daily health check dashboard in Grafana. For comprehensive monitoring, see `grafana-monitoring-guide.md`.

**Goal:** Answer one question in 30 seconds: *"Is the orchestration system healthy?"*

---

## Dashboard Layout

### Single-Page Dashboard with 6 Panels

```
┌─────────────────────────────────────────────────────────┐
│  Row 1: Health Status (Large KPI Panels)                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ Overall  │ │Execution │ │ Scraper  │ │ Missing  │   │
│  │  Health  │ │ Success  │ │ Success  │ │   Exec   │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
├─────────────────────────────────────────────────────────┤
│  Row 2: Today's Summary Table                           │
│  ┌─────────────────────────────────────────────────┐   │
│  │ Complete Daily Metrics (One Row)                │   │
│  └─────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────┤
│  Row 3: Recent Failures                                 │
│  ┌─────────────────────────────────────────────────┐   │
│  │ Failed Scrapers (Last 24h)                      │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## Panel 1: Overall Health Status ⭐

**Type:** Stat Panel (Large)
**Update:** Every 5 minutes

### Query

```sql
WITH
schedule_check AS (
  SELECT COUNT(*) as scheduled_workflows
  FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
  WHERE date = CURRENT_DATE('America/New_York')
),
decisions_check AS (
  SELECT
    COUNT(*) as total_decisions,
    COUNTIF(action = 'RUN') as run_decisions
  FROM `nba-props-platform.nba_orchestration.workflow_decisions`
  WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
),
executions_check AS (
  SELECT
    COUNT(*) as total_executions,
    COUNTIF(status = 'completed') as completed,
    SUM(scrapers_succeeded) as scrapers_succeeded,
    SUM(scrapers_failed) as scrapers_failed
  FROM `nba-props-platform.nba_orchestration.workflow_executions`
  WHERE DATE(execution_time, 'America/New_York') = CURRENT_DATE('America/New_York')
),
missing_executions AS (
  SELECT COUNT(*) as missing_count
  FROM `nba-props-platform.nba_orchestration.workflow_decisions` d
  LEFT JOIN `nba-props-platform.nba_orchestration.workflow_executions` e
    ON d.decision_id = e.decision_id
  WHERE DATE(d.decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
    AND d.action = 'RUN'
    AND e.execution_id IS NULL
)

SELECT
  CASE
    WHEN s.scheduled_workflows > 0
     AND e.total_executions > 0
     AND m.missing_count = 0
     AND (e.completed * 100.0 / NULLIF(e.total_executions, 0)) >= 80
    THEN 'HEALTHY'
    WHEN s.scheduled_workflows > 0
     AND e.total_executions > 0
     AND (e.completed * 100.0 / NULLIF(e.total_executions, 0)) >= 50
    THEN 'DEGRADED'
    WHEN s.scheduled_workflows = 0 AND d.total_decisions = 0
    THEN 'NO GAMES TODAY'
    ELSE 'UNHEALTHY'
  END as health_status
FROM schedule_check s
CROSS JOIN decisions_check d
CROSS JOIN executions_check e
CROSS JOIN missing_executions m
```

### Visualization Settings

- **Value:** health_status
- **Thresholds:**
  - Green (✅): "HEALTHY"
  - Blue (ℹ️): "NO GAMES TODAY"
  - Yellow (⚠️): "DEGRADED"
  - Red (❌): "UNHEALTHY"
- **Text Mode:** Value and name
- **Font Size:** Extra large

---

## Panel 2: Execution Success Rate

**Type:** Stat Panel
**Update:** Every 5 minutes

### Query

```sql
SELECT
  ROUND(COUNTIF(status = 'completed') * 100.0 / COUNT(*), 1) as success_rate
FROM `nba-props-platform.nba_orchestration.workflow_executions`
WHERE DATE(execution_time, 'America/New_York') = CURRENT_DATE('America/New_York')
```

### Visualization Settings

- **Unit:** Percent (0-100)
- **Thresholds:**
  - Red: < 80%
  - Yellow: 80-90%
  - Green: > 90%
- **Display:** Value with unit "%"

---

## Panel 3: Scraper Success Rate

**Type:** Stat Panel
**Update:** Every 5 minutes

### Query

```sql
-- NOTE: "no_data" is SUCCESS (scraper ran correctly, just found no new data)
-- Only "failed" is actual failure
SELECT
  ROUND(
    COUNTIF(status IN ('success', 'no_data')) * 100.0 / COUNT(*),
    1
  ) as success_rate
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE DATE(triggered_at, 'America/New_York') = CURRENT_DATE('America/New_York')
```

### Visualization Settings

- **Unit:** Percent (0-100)
- **Thresholds:**
  - Red: < 95%
  - Yellow: 95-98%
  - Green: > 98%
- **Display:** Value with unit "%"

**Note:** Expected success rate is 97-99%. "no_data" counts as success.

---

## Panel 4: Missing Executions

**Type:** Stat Panel
**Update:** Every 5 minutes

### Query

```sql
SELECT COUNT(*) as missing_count
FROM `nba-props-platform.nba_orchestration.workflow_decisions` d
LEFT JOIN `nba-props-platform.nba_orchestration.workflow_executions` e
  ON d.decision_id = e.decision_id
WHERE DATE(d.decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND d.action = 'RUN'
  AND e.execution_id IS NULL
```

### Visualization Settings

- **Unit:** Number
- **Thresholds:**
  - Green: 0
  - Yellow: 1-2
  - Red: > 2
- **Display:** Value only

**Meaning:**
- **0** = Perfect! All RUN decisions were executed
- **1-2** = Minor lag, likely still executing
- **>2** = Problem! Investigate immediately

---

## Panel 5: Today's Complete Health Summary ⭐

**Type:** Table
**Update:** Every 5 minutes

### Query (The Same One From quick_health_check.sh)

```sql
WITH
schedule_check AS (
  SELECT COUNT(*) as scheduled_workflows
  FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
  WHERE date = CURRENT_DATE('America/New_York')
),
decisions_check AS (
  SELECT
    COUNT(*) as total_decisions,
    COUNTIF(action = 'RUN') as run_decisions,
    COUNTIF(action = 'SKIP') as skip_decisions,
    COUNTIF(action = 'ABORT') as abort_decisions,
    MAX(decision_time) as last_decision
  FROM `nba-props-platform.nba_orchestration.workflow_decisions`
  WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
),
executions_check AS (
  SELECT
    COUNT(*) as total_executions,
    COUNTIF(status = 'completed') as completed,
    COUNTIF(status = 'failed') as failed,
    SUM(scrapers_succeeded) as scrapers_succeeded,
    SUM(scrapers_failed) as scrapers_failed,
    MAX(execution_time) as last_execution
  FROM `nba-props-platform.nba_orchestration.workflow_executions`
  WHERE DATE(execution_time, 'America/New_York') = CURRENT_DATE('America/New_York')
),
cleanup_check AS (
  SELECT
    COUNT(*) as cleanup_runs,
    SUM(missing_files_found) as total_missing,
    MAX(cleanup_time) as last_cleanup
  FROM `nba-props-platform.nba_orchestration.cleanup_operations`
  WHERE DATE(cleanup_time, 'America/New_York') = CURRENT_DATE('America/New_York')
),
missing_executions AS (
  SELECT COUNT(*) as missing_count
  FROM `nba-props-platform.nba_orchestration.workflow_decisions` d
  LEFT JOIN `nba-props-platform.nba_orchestration.workflow_executions` e
    ON d.decision_id = e.decision_id
  WHERE DATE(d.decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
    AND d.action = 'RUN'
    AND e.execution_id IS NULL
)

SELECT
  -- Schedule
  s.scheduled_workflows,

  -- Decisions
  d.total_decisions,
  d.run_decisions,
  d.skip_decisions,
  d.abort_decisions,
  FORMAT_TIMESTAMP('%H:%M %Z', d.last_decision, 'America/New_York') as last_decision_et,

  -- Executions
  e.total_executions,
  e.completed as executions_completed,
  e.failed as executions_failed,
  ROUND(e.completed * 100.0 / NULLIF(e.total_executions, 0), 1) as execution_success_pct,
  e.scrapers_succeeded,
  e.scrapers_failed,
  ROUND(e.scrapers_succeeded * 100.0 / NULLIF(e.scrapers_succeeded + e.scrapers_failed, 0), 1) as scraper_success_pct,
  FORMAT_TIMESTAMP('%H:%M %Z', e.last_execution, 'America/New_York') as last_execution_et,

  -- Cleanup
  c.cleanup_runs,
  c.total_missing as missing_files_recovered,
  FORMAT_TIMESTAMP('%H:%M %Z', c.last_cleanup, 'America/New_York') as last_cleanup_et,

  -- Missing executions
  m.missing_count as run_decisions_not_executed,

  -- Health indicator
  CASE
    WHEN s.scheduled_workflows > 0
     AND e.total_executions > 0
     AND m.missing_count = 0
     AND (e.completed * 100.0 / NULLIF(e.total_executions, 0)) >= 80
    THEN '✅ HEALTHY'
    WHEN s.scheduled_workflows > 0
     AND e.total_executions > 0
     AND (e.completed * 100.0 / NULLIF(e.total_executions, 0)) >= 50
    THEN '⚠️ DEGRADED'
    WHEN s.scheduled_workflows = 0 AND d.total_decisions = 0
    THEN 'ℹ️ NO GAMES TODAY'
    ELSE '❌ UNHEALTHY'
  END as health_status

FROM schedule_check s
CROSS JOIN decisions_check d
CROSS JOIN executions_check e
CROSS JOIN cleanup_check c
CROSS JOIN missing_executions m
```

### Visualization Settings

- **Style:** Table (one row)
- **Column width:** Auto
- **Highlight:** Color-code health_status column

**This is the same query as `./bin/orchestration/quick_health_check.sh`**

---

## Panel 6: Failed Scrapers (Last 24h)

**Type:** Table
**Update:** Every 5 minutes

### Query

```sql
SELECT
  FORMAT_TIMESTAMP('%H:%M %Z', triggered_at, 'America/New_York') as time_et,
  scraper_name,
  workflow,
  error_type,
  error_message
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE DATE(triggered_at, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND status = 'failed'
ORDER BY triggered_at DESC
LIMIT 20
```

### Visualization Settings

- **Style:** Table
- **Columns:** All visible
- **Sort:** time_et descending (most recent first)

**Note:** Empty table = no failures today (good!)

---

## How to Read the Dashboard

### Morning Check (After 9 AM ET)

1. **Overall Health Panel:** Should show "✅ HEALTHY" or "ℹ️ NO GAMES TODAY"
2. **Execution Success Rate:** Should be >90%
3. **Scraper Success Rate:** Should be >97%
4. **Missing Executions:** Should be 0
5. **Summary Table:** Review all metrics in one row
6. **Failed Scrapers:** Should be empty or have only minor/expected failures

### End of Day Check (After 11 PM ET)

Same checks, but now you're verifying the complete day's execution.

**Expected Metrics (Typical Game Day with 19 games):**
- Scheduled workflows: ~19
- Total decisions: 100-120
- Run decisions: 35-45
- Skip decisions: 60-80
- Execution success: 80-90%
- Scraper success: 97-99%
- Missing executions: 0

---

## What's Normal vs. Concerning

### ✅ Normal Patterns

**High "no_data" counts (400-500):**
- NORMAL! These are hourly checks that found no new data
- "no_data" = success, not failure
- Don't include in failure metrics

**Some SKIP decisions (60-80):**
- NORMAL! Workflows scheduled but conditions not met
- Examples: Not within time window, no games today, already ran

**Occasional failures (1-3 per day):**
- NORMAL! APIs have transient issues
- Look for patterns: same scraper failing repeatedly = problem

### ⚠️ Warning Signs

**Execution success < 80%:**
- Multiple workflows failing
- Check failed scrapers table for patterns

**Scraper success < 95%:**
- Too many failures
- Review error types to identify root cause

**Missing executions > 0:**
- Workflows were decided to RUN but didn't execute
- Check orchestration service health

**All failures from one scraper:**
- Code bug (like today's nbac_injury_report)
- Deploy fix immediately

**Health status = UNHEALTHY:**
- System-wide problem
- Check Cloud Run services, Pub/Sub, and Cloud Scheduler

---

## Common Failure Patterns

### Pattern 1: Parameter Type Errors
```
Error: 'int' object has no attribute 'zfill'
Action: Fix parameter type conversion in scraper
Example: str(opts["hour"]).zfill(2)
```

### Pattern 2: JSON Decode Errors
```
Error: JSON decode failed: Expecting value
Cause: External API returned non-JSON (HTML error, rate limit)
Action: Usually transient, monitor for recurrence
```

### Pattern 3: Missing Dependencies
```
Error: No event_ids found
Cause: Dependency scraper failed (e.g., oddsa_events failed before oddsa_player_props)
Action: Fix upstream scraper first
```

---

## Alert Conditions

Set up Grafana alerts on these queries:

### Critical Alert: System Unhealthy
```sql
-- Alert if health_status != 'HEALTHY' for > 30 minutes
-- (Use Panel 1 query, check health_status value)
```

### Warning Alert: High Failure Rate
```sql
-- Alert if scraper_success_pct < 95% for > 1 hour
-- (Use Panel 3 query)
```

### Info Alert: Missing Executions
```sql
-- Alert if missing_count > 0 for > 15 minutes
-- (Use Panel 4 query)
```

---

## Quick Actions for Each Status

### ✅ HEALTHY
- Nothing to do! System operating normally
- Review failed scrapers table for any patterns

### ⚠️ DEGRADED
1. Check **executions_failed** count in summary table
2. Review **Failed Scrapers** table
3. Identify if single scraper or widespread issue
4. Run: `./bin/orchestration/investigate_scraper_failures.sh`

### ❌ UNHEALTHY
1. Run: `./bin/orchestration/check_system_status.sh`
2. Check Cloud Run services are running
3. Check Cloud Scheduler jobs are enabled
4. Review Pub/Sub queue backlogs
5. Check GCP console for any alerts

### ℹ️ NO GAMES TODAY
- Expected during All-Star break, playoffs off-days
- Minimal orchestration activity
- Still verify critical scrapers (schedule, player list) ran

---

## Dashboard Refresh Settings

**Recommended refresh intervals:**
- **During active hours (6 AM - 11 PM ET):** Every 5 minutes
- **Overnight (11 PM - 6 AM ET):** Every 15 minutes
- **Manual refresh:** Always available

**Time range:** "Today so far" (from midnight ET to now)

---

## Companion Shell Script

This dashboard mirrors the output of:
```bash
./bin/orchestration/quick_health_check.sh
```

**Use the shell script when:**
- You want instant results (no Grafana needed)
- Debugging from terminal
- Scripting/automation

**Use Grafana dashboard when:**
- Visual monitoring
- Historical trends
- Alert notifications needed
- Sharing with team

---

## Related Documentation

**For daily monitoring:**
- This guide (quick daily check)
- `bin/orchestration/quick_health_check.sh` (terminal equivalent)

**For deep investigation:**
- `grafana-monitoring-guide.md` (comprehensive monitoring)
- `bin/orchestration/investigate_scraper_failures.sh` (failure analysis)
- `bin/orchestration/check_system_status.sh` (detailed system health)

**For understanding orchestration:**
- `.claude/claude_project_instructions.md` (Phase 1 Orchestration section)
- `bin/orchestration/README.md` (workflow schedule system)

---

## Example: Reading Today's Results (Nov 14, 2025)

**Summary Table showed:**
```
scheduled_workflows: 19
total_decisions: 112
run_decisions: 43
execution_success_pct: 81.0%
scraper_success_pct: 97.8%
missing_executions: 1
health_status: ⚠️ DEGRADED
```

**Interpretation:**
- ⚠️ DEGRADED status = not critical but needs attention
- 81% execution success = slightly below 90% threshold
- 97.8% scraper success = good (above 95%)
- 1 missing execution = minor lag, likely still executing

**Action taken:**
- Checked failed scrapers table
- Found nbac_injury_report failing 5 times (parameter bug)
- Fixed code, redeployed
- Tomorrow should show ✅ HEALTHY

---

**Last Updated:** 2025-11-14
**Version:** 1.0
**Companion to:** grafana-monitoring-guide.md (comprehensive version)

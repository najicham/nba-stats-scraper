# Grafana Monitoring Guide - NBA Orchestration System

**File:** `docs/monitoring/01-grafana-monitoring-guide.md`
**Created:** 2025-11-14 16:26 PST
**Last Updated:** 2025-11-15 (moved from orchestration/ to monitoring/)
**Purpose:** Comprehensive BigQuery queries and dashboard insights for Grafana monitoring
**Status:** Current

---

## Overview

This guide provides comprehensive BigQuery queries for monitoring the NBA orchestration system through Grafana. The orchestration system logs all execution data to BigQuery tables, which Grafana can query directly.

**For quick daily monitoring, see:** `grafana-daily-health-check-guide.md` (simplified 6-panel dashboard)

### Key Tables

1. **`nba_orchestration.workflow_executions`** - High-level workflow execution tracking
2. **`nba_orchestration.scraper_execution_log`** - Detailed scraper execution logs
3. **`nba_orchestration.workflow_decisions`** - Master controller RUN/SKIP/ABORT decisions
4. **`nba_orchestration.daily_expected_schedule`** - Expected workflows for the day
5. **`nba_orchestration.cleanup_operations`** - Missing file recovery tracking

---

## Table Schemas

### workflow_executions

Key fields:
- `execution_id` (STRING) - Unique workflow execution UUID
- `execution_time` (TIMESTAMP) - When workflow started
- `workflow_name` (STRING) - Name of workflow (e.g., "morning_operations")
- `status` (STRING) - "completed" or "failed"
- `scrapers_requested` (ARRAY<STRING>) - List of scrapers requested
- `scrapers_triggered` (INTEGER) - Total scraper executions triggered
- `scrapers_succeeded` (INTEGER) - Count of successful executions
- `scrapers_failed` (INTEGER) - Count of failed executions
- `duration_seconds` (FLOAT) - Total workflow duration
- `error_message` (STRING) - Error details if workflow failed

### scraper_execution_log

Key fields:
- `execution_id` (STRING) - Scraper execution ID (8-char hex)
- `scraper_name` (STRING) - Name of scraper
- `workflow` (STRING) - Parent workflow name
- `status` (STRING) - "success", "no_data", or "failed"
  - **IMPORTANT:** "no_data" = successful execution with no new data (NOT a failure!)
  - Only "failed" represents actual failures
- `triggered_at` (TIMESTAMP) - Execution start time
- `completed_at` (TIMESTAMP) - Execution end time
- `duration_seconds` (FLOAT) - Execution duration
- `source` (STRING) - "SCHEDULER", "CONTROLLER", or "MANUAL"
- `environment` (STRING) - "production" or "development"
- `error_type` (STRING) - Exception class name if failed
- `error_message` (STRING) - Error details if failed
- `opts` (JSON) - Scraper parameters used
- `data_summary` (JSON) - Scraper stats (record count, etc.)
- `gcs_path` (STRING) - Output file path in GCS
- `retry_count` (INTEGER) - Number of retries attempted

### workflow_decisions

Key fields:
- `decision_id` (STRING) - Unique decision UUID
- `decision_time` (TIMESTAMP) - When decision was made
- `workflow_name` (STRING) - Name of workflow evaluated
- `action` (STRING) - "RUN", "SKIP", or "ABORT"
- `reason` (STRING) - Why this action was chosen
- `context` (JSON) - Decision context (schedule, conditions, etc.)
- `controller_version` (STRING) - Version of master controller

**Purpose:** Track what the master controller decided to do. Compare with workflow_executions to find missing executions.

### daily_expected_schedule

Key fields:
- `date` (DATE) - The date for this schedule
- `workflow_name` (STRING) - Workflow expected to run
- `expected_run_time` (TIMESTAMP) - When it should run
- `reason` (STRING) - Why it's scheduled
- `game_context` (JSON) - Related game information
- `generated_at` (TIMESTAMP) - When schedule was generated

**Purpose:** Pre-computed expected schedule for monitoring. Compare against actual executions to detect issues.

### cleanup_operations

Key fields:
- `cleanup_id` (STRING) - Unique cleanup operation UUID
- `cleanup_time` (TIMESTAMP) - When cleanup ran
- `missing_files_found` (INTEGER) - Number of missing files detected
- `files_recovered` (INTEGER) - Number successfully recovered
- `recovery_method` (STRING) - How files were recovered
- `errors` (JSON) - Any errors encountered

**Purpose:** Track automatic recovery of missing data files. Non-zero missing files may indicate scraper issues.

---

## Understanding Success vs Failure

**CRITICAL:** The `status` field in `scraper_execution_log` has three values:

1. **"success"** = Scraper ran successfully AND found new data
2. **"no_data"** = Scraper ran successfully BUT found no new data (e.g., hourly check, no games today)
3. **"failed"** = Scraper encountered an error and did not complete

### What Counts as Success?

**Both "success" and "no_data" are successful executions!**

On a typical day with 19 games:
- ~500 total scraper executions
- ~50-100 "success" (found new data)
- ~400-450 "no_data" (ran correctly, no new data)
- ~5-10 "failed" (actual errors)

**When calculating success rates:**
```sql
-- CORRECT: Count both success and no_data as successful
COUNTIF(status IN ('success', 'no_data')) / COUNT(*) * 100

-- WRONG: Only count 'success'
COUNTIF(status = 'success') / COUNT(*) * 100  -- This would show 10-20%!
```

**Why so many "no_data" results?**
- Workflows run hourly to check for new data
- If no games in progress, scrapers return "no_data"
- This is expected and healthy behavior
- Only investigate "no_data" if it persists when games ARE happening

---

## Key Metrics to Monitor

### 1. Overall System Health
Combined view of all health indicators (NEW - see Panel 0)

### 2. Workflow Success Rate
Track overall health of orchestration system

### 3. Scraper Success Rate (including no_data)
Identify problematic scrapers - remember "no_data" = success!

### 4. Missing Executions
Detect when RUN decisions don't result in executions

### 5. Execution Duration
Detect performance degradation

### 6. Error Patterns
Group errors by type for troubleshooting

---

## Grafana Dashboard Queries

### Panel 0: Daily Health Check (⭐ MOST IMPORTANT)

**Metric:** Complete system health in one view

```sql
-- This is the same query as ./bin/orchestration/quick_health_check.sh
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

**Visualization:** Table (single row with all metrics)

**Use:** Start your daily check here! This one panel shows everything you need.

---

### Panel 0b: Missing Executions Detector

**Metric:** Find RUN decisions that didn't execute

```sql
SELECT
  FORMAT_TIMESTAMP('%H:%M %Z', d.decision_time, 'America/New_York') as decision_time_et,
  d.workflow_name,
  d.action,
  d.reason,
  CASE
    WHEN e.execution_id IS NULL THEN '❌ MISSING'
    ELSE '✅ EXECUTED'
  END as execution_status
FROM `nba-props-platform.nba_orchestration.workflow_decisions` d
LEFT JOIN `nba-props-platform.nba_orchestration.workflow_executions` e
  ON d.decision_id = e.decision_id
WHERE DATE(d.decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND d.action = 'RUN'
  AND e.execution_id IS NULL
ORDER BY d.decision_time DESC
```

**Visualization:** Table

**Use:** Should be empty! If rows appear, workflow executor has issues.

---

### Panel 1: Workflow Success Rate (Last 24 Hours)

**Metric:** Percentage of successful workflows

```sql
SELECT
  COUNTIF(status = 'completed') / COUNT(*) * 100 as success_rate
FROM `nba-props-platform.nba_orchestration.workflow_executions`
WHERE execution_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
```

**Visualization:** Stat panel with threshold colors (green >95%, yellow >90%, red ≤90%)

---

### Panel 2: Workflow Executions Over Time

**Metric:** Workflow execution counts by status

```sql
SELECT
  TIMESTAMP_TRUNC(execution_time, HOUR) as time,
  status,
  COUNT(*) as count
FROM `nba-props-platform.nba_orchestration.workflow_executions`
WHERE execution_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY time, status
ORDER BY time DESC
```

**Visualization:** Time series graph with status as series

---

### Panel 3: Scraper Success Rate by Name (Last 24 Hours)

**Metric:** Success rate per scraper (CORRECTED - counts "no_data" as success)

```sql
SELECT
  scraper_name,
  COUNTIF(status = 'success') as found_data,
  COUNTIF(status = 'no_data') as no_new_data,
  COUNTIF(status = 'failed') as failures,
  COUNT(*) as total_runs,
  -- CORRECT: Both 'success' and 'no_data' are successful
  ROUND(COUNTIF(status IN ('success', 'no_data')) / COUNT(*) * 100, 1) as success_rate
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY scraper_name
ORDER BY success_rate ASC, total_runs DESC
```

**Visualization:** Table with conditional formatting on success_rate
- Green: >98%
- Yellow: 95-98%
- Red: <95%

**Note:** Success rate should be 97-100% for most scrapers. "no_data" is NOT a failure!

---

### Panel 4: Failed Scraper Executions (Last 24 Hours)

**Metric:** List of recent failures with details

```sql
SELECT
  triggered_at,
  scraper_name,
  workflow,
  error_type,
  error_message,
  JSON_VALUE(opts, '$.date') as date_param,
  JSON_VALUE(opts, '$.season') as season_param
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE status = 'failed'
  AND triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY triggered_at DESC
LIMIT 20
```

**Visualization:** Table sorted by time (most recent first)

---

### Panel 5: Scraper Execution Duration (P95)

**Metric:** 95th percentile duration by scraper

```sql
SELECT
  scraper_name,
  APPROX_QUANTILES(duration_seconds, 100)[OFFSET(50)] as p50_seconds,
  APPROX_QUANTILES(duration_seconds, 100)[OFFSET(95)] as p95_seconds,
  APPROX_QUANTILES(duration_seconds, 100)[OFFSET(99)] as p99_seconds,
  COUNT(*) as execution_count
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND status IN ('success', 'no_data')  -- Exclude failures
GROUP BY scraper_name
HAVING execution_count > 5  -- Only scrapers with sufficient data
ORDER BY p95_seconds DESC
```

**Visualization:** Bar chart or table

---

### Panel 6: Workflow Duration Trend

**Metric:** Average workflow duration over time

```sql
SELECT
  TIMESTAMP_TRUNC(execution_time, HOUR) as time,
  workflow_name,
  AVG(duration_seconds) as avg_duration,
  MAX(duration_seconds) as max_duration
FROM `nba-props-platform.nba_orchestration.workflow_executions`
WHERE execution_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND status = 'completed'
GROUP BY time, workflow_name
ORDER BY time DESC
```

**Visualization:** Time series with workflow_name as series

---

### Panel 7: Error Type Breakdown (Last 24 Hours)

**Metric:** Most common error types

```sql
SELECT
  error_type,
  COUNT(*) as count,
  ARRAY_AGG(DISTINCT scraper_name LIMIT 5) as affected_scrapers
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE status = 'failed'
  AND triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND error_type IS NOT NULL
GROUP BY error_type
ORDER BY count DESC
LIMIT 10
```

**Visualization:** Pie chart or table

---

### Panel 8: Data Completeness (No Data Rate)

**Metric:** Scrapers returning no data

```sql
SELECT
  scraper_name,
  COUNTIF(status = 'no_data') as no_data_count,
  COUNTIF(status = 'success') as success_count,
  COUNT(*) as total,
  ROUND(COUNTIF(status = 'no_data') / COUNT(*) * 100, 1) as no_data_rate
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY scraper_name
HAVING no_data_count > 0
ORDER BY no_data_rate DESC
```

**Visualization:** Table

**Note:** "no_data" is normal for some scrapers (e.g., off-season, no games today). Use this to identify unexpected gaps.

---

### Panel 9: Scrapers Per Workflow Execution

**Metric:** Distribution of scraper counts per workflow

```sql
SELECT
  workflow_name,
  TIMESTAMP_TRUNC(execution_time, HOUR) as time,
  AVG(scrapers_triggered) as avg_scrapers,
  AVG(scrapers_succeeded) as avg_succeeded,
  AVG(scrapers_failed) as avg_failed
FROM `nba-props-platform.nba_orchestration.workflow_executions`
WHERE execution_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY workflow_name, time
ORDER BY time DESC
```

**Visualization:** Time series stacked area chart

---

### Panel 10: Recent Workflow Executions

**Metric:** Latest workflow executions with key stats

```sql
SELECT
  execution_time,
  workflow_name,
  status,
  scrapers_triggered,
  scrapers_succeeded,
  scrapers_failed,
  ROUND(duration_seconds, 1) as duration_sec,
  ROUND(scrapers_succeeded / scrapers_triggered * 100, 1) as success_pct
FROM `nba-props-platform.nba_orchestration.workflow_executions`
WHERE execution_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY execution_time DESC
LIMIT 20
```

**Visualization:** Table

---

### Panel 11: Scraper Execution Volume by Hour

**Metric:** Execution counts by hour of day

```sql
SELECT
  EXTRACT(HOUR FROM triggered_at) as hour_of_day,
  COUNT(*) as execution_count,
  COUNTIF(status = 'success') as successes,
  COUNTIF(status = 'failed') as failures
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY hour_of_day
ORDER BY hour_of_day
```

**Visualization:** Bar chart

**Use:** Identify peak execution times and ensure resources are available

---

### Panel 12: Multi-Team Scraper Performance

**Metric:** Performance of br_season_roster (30 team executions)

```sql
SELECT
  DATE(triggered_at) as date,
  JSON_VALUE(opts, '$.teamAbbr') as team,
  status,
  duration_seconds
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE scraper_name = 'basketball_ref_season_roster'
  AND triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY date DESC, team
```

**Visualization:** Heatmap or table

**Use:** Ensure all 30 teams are being processed successfully

---

## Pub/Sub Monitoring (Indirect via Database)

While Grafana may not directly access Pub/Sub, you can infer Pub/Sub health from database logs:

### Panel 13: Processor Lag Detection

**Query:** Time between scraper completion and processor execution

```sql
-- Note: This requires joining with processor logs
-- For now, monitor via scraper completion times
SELECT
  DATE(completed_at) as date,
  COUNT(*) as scrapers_completed,
  COUNTIF(gcs_path IS NOT NULL) as data_written_to_gcs
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE completed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND status = 'success'
GROUP BY date
ORDER BY date DESC
```

**Use:** If scrapers complete but processors don't run, Pub/Sub may have issues

---

### Panel 14: Scraper Source Distribution

**Metric:** Where executions are coming from

```sql
SELECT
  source,
  environment,
  COUNT(*) as count
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY source, environment
ORDER BY count DESC
```

**Visualization:** Pie chart

**Values:**
- `SCHEDULER` - Cloud Scheduler triggered
- `CONTROLLER` - Workflow executor triggered
- `MANUAL` - Manually triggered

---

## Alert Queries

### Alert 1: High Workflow Failure Rate

**Condition:** >10% of workflows failed in last hour

```sql
SELECT
  COUNTIF(status = 'failed') / COUNT(*) * 100 as failure_rate
FROM `nba-props-platform.nba_orchestration.workflow_executions`
WHERE execution_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
HAVING failure_rate > 10
```

---

### Alert 2: Critical Scraper Failures

**Condition:** Critical scrapers (odds, schedule) failed

```sql
SELECT
  scraper_name,
  COUNT(*) as failure_count
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE status = 'failed'
  AND triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND scraper_name IN (
    'oddsa_events',
    'oddsa_player_props',
    'oddsa_game_lines',
    'nbac_schedule_api'
  )
GROUP BY scraper_name
HAVING failure_count > 0
```

---

### Alert 3: No Executions in Expected Window

**Condition:** No workflow executions in last 2 hours (during business hours)

```sql
SELECT
  COUNT(*) as execution_count
FROM `nba-props-platform.nba_orchestration.workflow_executions`
WHERE execution_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
HAVING execution_count = 0
```

**Note:** Only alert during expected execution windows (check your workflow schedules)

---

### Alert 4: Scraper Duration Anomaly

**Condition:** Scraper taking 3x longer than usual

```sql
WITH recent_avg AS (
  SELECT
    scraper_name,
    AVG(duration_seconds) as avg_duration
  FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
  WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    AND status = 'success'
  GROUP BY scraper_name
),
recent_executions AS (
  SELECT
    scraper_name,
    duration_seconds
  FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
  WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
    AND status = 'success'
)
SELECT
  re.scraper_name,
  re.duration_seconds as recent_duration,
  ra.avg_duration,
  re.duration_seconds / ra.avg_duration as ratio
FROM recent_executions re
JOIN recent_avg ra ON re.scraper_name = ra.scraper_name
WHERE re.duration_seconds > ra.avg_duration * 3
  AND ra.avg_duration > 5  -- Ignore very fast scrapers
```

---

## Dashboard Layout Recommendations

### Overview Dashboard

Top row (KPIs):
1. Workflow Success Rate (24h)
2. Scraper Success Rate (24h)
3. Active Workflows (current)
4. Failed Executions (24h)

Middle row:
1. Workflow Executions Over Time (7d)
2. Scraper Success Rate by Name (24h)

Bottom row:
1. Recent Failures Table
2. Error Type Breakdown

---

### Detailed Scraper Dashboard

Top row:
1. Scraper Execution Volume by Hour
2. Scraper Duration (P95)

Middle row:
1. Data Completeness (No Data Rate)
2. Multi-Team Scraper Performance

Bottom row:
1. Execution History Table (filterable by scraper)

---

### Performance Dashboard

1. Workflow Duration Trend
2. Scraper Duration Trend
3. Execution Volume by Hour
4. Source Distribution

---

## Time Range Variables

Create Grafana variables for flexible time ranges:

```
$__timeFrom: Auto (Grafana time picker)
$__timeTo: Auto (Grafana time picker)
```

Update queries to use:
```sql
WHERE triggered_at >= $__timeFrom
  AND triggered_at <= $__timeTo
```

---

## Useful Filters

Create dropdown variables:

**$workflow_name:**
```sql
SELECT DISTINCT workflow_name
FROM `nba-props-platform.nba_orchestration.workflow_executions`
ORDER BY workflow_name
```

**$scraper_name:**
```sql
SELECT DISTINCT scraper_name
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
ORDER BY scraper_name
```

**$status:**
```sql
SELECT DISTINCT status
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
ORDER BY status
```

Then use in queries:
```sql
WHERE workflow_name = '$workflow_name'
  AND scraper_name = '$scraper_name'
  AND status = '$status'
```

---

## Query Optimization Tips

1. **Always filter by time first** - Use `triggered_at` or `execution_time` in WHERE clause
2. **Use TIMESTAMP_TRUNC for grouping** - More efficient than DATE()
3. **Limit result sets** - Add LIMIT clause for tables
4. **Cache results** - Set appropriate refresh intervals in Grafana
5. **Use partitioned queries** - BigQuery tables are partitioned by date

---

## Expected Patterns

### Normal Behavior (Based on Nov 14, 2025 - 19 Game Day)

**Overall Daily Metrics:**
- **Scheduled workflows:** ~19 (one per game)
- **Total decisions:** 100-120 (hourly evaluations)
- **RUN decisions:** 35-45 (workflows that should execute)
- **SKIP decisions:** 60-80 (scheduled but conditions not met)
- **ABORT decisions:** 0-2 (rare)
- **Total executions:** 35-45 (matching RUN decisions)
- **Execution success rate:** 80-90% (some failures are normal)
- **Scraper success rate:** 97-99% (including "no_data")
- **Total scraper runs:** 500+ (many hourly checks)
- **"no_data" runs:** 400-450 (hourly checks with no new data - NORMAL!)
- **Actual failures:** 5-15 (transient API issues)

**Workflow Patterns:**

- **morning_operations:** Runs HOURLY (not just once!)
  - Schedule: 6 AM - 7 PM+ ET, every hour
  - Triggers: ~34 scrapers per run (30 for br_season_roster + 4 foundation)
  - Expected failures: 0-1 per run
  - Duration: 3-4 minutes

- **betting_lines:** Runs multiple times throughout game day
  - Triggers: Odds API scrapers (events, props, game lines)
  - Expected: 15-20 executions per day
  - "no_data" is common when odds haven't changed

- **injury_discovery:** Runs every 3 hours
  - Triggers: nbac_injury_report
  - Expected: 5-6 executions per day
  - "no_data" common during off-days

- **schedule_dependency:** Runs hourly
  - Triggers: nbac_schedule_api
  - Monitors for schedule changes

**Why so many "no_data" results?**
- Workflows check hourly for new data
- If nothing changed since last check → "no_data"
- 400-450 "no_data" on 500 total runs = 80-90% (EXPECTED!)
- Only investigate if "no_data" persists when games ARE happening

### Warning Signs

**🔴 Critical Issues:**
- Health status = UNHEALTHY
- Execution success < 70%
- Scraper success < 95% (remember: count "no_data" as success!)
- Missing executions > 0 (RUN decisions not executed)
- Same scraper failing repeatedly (5+ times)

**⚠️ Warning Signs:**
- Health status = DEGRADED
- Execution success 70-80%
- Scraper success 95-97%
- Duration increases >50% from baseline
- No executions during expected windows (6 AM - 11 PM ET on game days)

**ℹ️ Normal Variations:**
- Off-season: Fewer executions, more "no_data"
- All-Star break: Minimal activity, "NO GAMES TODAY" status
- Playoffs: Different patterns, more frequent data updates
- Individual team failures (PHX, BKN, CHA): Check team mapping
- Single API timeout: Retry usually succeeds

---

## Direct GCP Monitoring (Outside Grafana)

If you need direct Pub/Sub metrics, use GCP Monitoring (Stackdriver):

**Cloud Console → Monitoring → Dashboards → Pub/Sub**

Key Pub/Sub metrics:
- `pubsub.googleapis.com/subscription/num_undelivered_messages`
- `pubsub.googleapis.com/subscription/oldest_unacked_message_age`
- `pubsub.googleapis.com/topic/send_message_operation_count`

These can be viewed in GCP Monitoring but may not be directly queryable in Grafana unless you set up a Prometheus exporter or GCP monitoring integration.

---

## Contact & Updates

**Last Updated:** 2025-11-14
**Orchestration Version:** Phase 1 (HTTP-based)

**Related Docs:**

**For daily monitoring:**
- `grafana-daily-health-check-guide.md` - Quick 6-panel dashboard (START HERE!)
- `bin/orchestration/quick_health_check.sh` - Terminal equivalent

**For investigation:**
- `bin/orchestration/check_system_status.sh` - Detailed system health
- `bin/orchestration/investigate_scraper_failures.sh` - Failure analysis
- `bin/orchestration/verify_phase1_complete.sh` - Comprehensive verification

**For understanding:**
- `.claude/claude_project_instructions.md` - Phase 1 Orchestration overview
- `bin/orchestration/README.md` - Workflow schedule system

**BigQuery Dataset:** `nba-props-platform.nba_orchestration`

**Tables:**
- `workflow_executions` - Workflow execution tracking
- `scraper_execution_log` - Scraper execution details
- `workflow_decisions` - Master controller decisions (RUN/SKIP/ABORT)
- `daily_expected_schedule` - Expected workflows for monitoring
- `cleanup_operations` - Missing file recovery tracking

**Key Shell Scripts:**
- `./bin/orchestration/quick_health_check.sh` - 30-second health check
- `./bin/orchestration/check_system_status.sh` - Detailed diagnostics
- `./bin/orchestration/investigate_scraper_failures.sh` - Error analysis

---

**End of Grafana Monitoring Guide - Comprehensive Version**

**See also:** `grafana-daily-health-check-guide.md` for simplified daily monitoring


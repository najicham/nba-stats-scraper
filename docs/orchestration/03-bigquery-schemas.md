# Phase 1 BigQuery Schemas

**File:** `docs/orchestration/03-bigquery-schemas.md`
**Created:** 2025-11-13 10:06 PST (split from comprehensive guide)
**Last Updated:** 2025-11-15 (renumbered from 08 to 03)
**Purpose:** BigQuery table schemas and monitoring queries for Phase 1 orchestration
**Status:** Production Deployed
**Audience:** Engineers working with orchestration data in BigQuery

**Related Docs:**
- **Architecture Overview:** See `02-phase1-overview.md` for system architecture
- **Troubleshooting:** See `09-phase1-troubleshooting.md` for manual operations
- **Monitoring Dashboards:** See `04-grafana-monitoring-guide.md` for Grafana setup

---

## Table of Contents

1. [Dataset Overview](#dataset-overview)
2. [Table 1: daily_expected_schedule](#table-1-daily_expected_schedule)
3. [Table 2: workflow_decisions](#table-2-workflow_decisions)
4. [Table 3: cleanup_operations](#table-3-cleanup_operations)
5. [Table 4: scraper_execution_log](#table-4-scraper_execution_log)
6. [Table 5: workflow_executions](#table-5-workflow_executions)

---

## Dataset Overview

**Dataset:** `nba_orchestration`

**Location:** `nba-props-platform.nba_orchestration`

**Tables:** 5 operational tables

**Purpose:** Complete audit trail of orchestration decisions and operations

---

BigQuery Tables

Dataset: nba_orchestration

Location: nba-props-platform.nba_orchestration

Tables: 5 operational tables

Purpose: Complete audit trail of orchestration decisions and operations

Table 1: daily_expected_schedule

Purpose: Daily plan of what workflows SHOULD run

Populated By: Schedule Locker (5 AM ET daily)

Schema:

CREATE TABLE `nba-props-platform.nba_orchestration.daily_expected_schedule` (
  date DATE,                          -- Date this schedule is for
  locked_at TIMESTAMP,                -- When schedule was generated
  workflow_name STRING,               -- Name of workflow
  expected_run_time TIMESTAMP,        -- When workflow should execute
  reason STRING,                      -- Why scheduled (human-readable)
  scrapers ARRAY<STRING>              -- List of scrapers to run
)
PARTITION BY date
CLUSTER BY workflow_name;


Example Data:

date: '2025-11-12'
locked_at: '2025-11-12T10:00:15Z'
workflow_name: 'betting_lines'
expected_run_time: '2025-11-12T13:30:00-05:00'
reason: 'Pre-game betting lines (12 games today)'
scrapers: ['oddsa_events', 'oddsa_player_props', 'oddsa_game_lines']


Typical Row Count:

5-20 rows per day (one per workflow instance)

Empty on days with no games

Monitoring Queries:

Daily Summary:

SELECT 
  date,
  COUNT(*) as workflows_scheduled,
  COUNT(DISTINCT workflow_name) as unique_workflows,
  MIN(expected_run_time) as first_run,
  MAX(expected_run_time) as last_run
FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
WHERE date = CURRENT_DATE('America/New_York')
GROUP BY date;


Workflow Breakdown:

SELECT 
  workflow_name,
  COUNT(*) as scheduled_count,
  MIN(expected_run_time) as earliest,
  MAX(expected_run_time) as latest
FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
WHERE date = CURRENT_DATE('America/New_York')
GROUP BY workflow_name
ORDER BY earliest;


Table 2: workflow_decisions

Purpose: Log every workflow evaluation decision (RUN/SKIP/ABORT)

Populated By: Master Controller (hourly 6-11 PM ET)

Schema:

CREATE TABLE `nba-props-platform.nba_orchestration.workflow_decisions` (
  decision_time TIMESTAMP,            -- When decision was made
  workflow_name STRING,               -- Which workflow
  action STRING,                      -- RUN, SKIP, or ABORT
  reason STRING,                      -- Why this decision
  priority STRING,                    -- CRITICAL, HIGH, MEDIUM, LOW
  alert_level STRING,                 -- NONE, INFO, WARNING, ERROR
  next_check TIMESTAMP,               -- When to check again (for SKIP)
  scrapers ARRAY<STRING>              -- Scrapers for RUN actions
)
PARTITION BY DATE(decision_time)
CLUSTER BY workflow_name, action;


Example Data:

RUN Decision:

decision_time: '2025-11-12T13:30:15-05:00'
workflow_name: 'betting_lines'
action: 'RUN'
reason: 'Ready: 12 games today, 5.5h until first game'
priority: 'CRITICAL'
alert_level: 'NONE'
next_check: NULL
scrapers: ['oddsa_events', 'oddsa_player_props', 'oddsa_game_lines']


SKIP Decision:

decision_time: '2025-11-12T15:00:10-05:00'
workflow_name: 'post_game_window_1'
action: 'SKIP'
reason: 'Not in time window (20:00 ±30min)'
priority: 'HIGH'
alert_level: 'NONE'
next_check: '2025-11-12T20:00:00-05:00'
scrapers: []


ABORT Decision:

decision_time: '2025-11-12T18:55:00-05:00'
workflow_name: 'betting_lines'
action: 'ABORT'
reason: 'Missed window (first game in 5 min, needed 6h lead time)'
priority: 'CRITICAL'
alert_level: 'WARNING'
next_check: NULL
scrapers: []


Typical Row Count:

90-144 rows per day (5-8 workflows × 18 hourly evaluations)

Peak during game days

Monitoring Queries:

Action Summary:

SELECT 
  action,
  COUNT(*) as count,
  ROUND(COUNT(*) / SUM(COUNT(*)) OVER() * 100, 1) as pct
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
GROUP BY action;


Alert Summary:

SELECT 
  alert_level,
  workflow_name,
  COUNT(*) as count
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND alert_level IN ('WARNING', 'ERROR')
GROUP BY alert_level, workflow_name
ORDER BY alert_level DESC, count DESC;


Hourly Pattern:

SELECT 
  EXTRACT(HOUR FROM decision_time AT TIME ZONE 'America/New_York') as hour_et,
  COUNT(*) as evaluations,
  COUNTIF(action = 'RUN') as run_count,
  COUNTIF(action = 'SKIP') as skip_count,
  COUNTIF(action = 'ABORT') as abort_count
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
GROUP BY hour_et
ORDER BY hour_et;


Table 3: cleanup_operations

Purpose: Track self-healing activity (orphaned file detection and recovery)

Populated By: Cleanup Processor (every 15 minutes)

Schema:

CREATE TABLE `nba-props-platform.nba_orchestration.cleanup_operations` (
  cleanup_time TIMESTAMP,             -- When cleanup ran
  cleanup_id STRING,                  -- Unique UUID for this operation
  files_checked INT64,                -- Files examined
  missing_files_found INT64,          -- Files without BigQuery records
  republished_count INT64,            -- Pub/Sub events republished
  duration_seconds FLOAT64            -- Processing time
)
PARTITION BY DATE(cleanup_time)
CLUSTER BY DATE(cleanup_time);


Example Data (Normal):

cleanup_time: '2025-11-12T15:15:00-05:00'
cleanup_id: 'uuid-here'
files_checked: 0
missing_files_found: 0
republished_count: 0
duration_seconds: 0.85


Example Data (Recovery):

cleanup_time: '2025-11-12T14:30:00-05:00'
cleanup_id: 'uuid-here'
files_checked: 12
missing_files_found: 2
republished_count: 2
duration_seconds: 2.15


Typical Row Count:

96 rows per day (every 15 min × 24 hours)

Most rows have 0 missing files (healthy)

Monitoring Queries:

Daily Summary:

SELECT 
  DATE(cleanup_time, 'America/New_York') as date,
  COUNT(*) as cleanup_runs,
  SUM(files_checked) as total_files_checked,
  SUM(missing_files_found) as total_missing,
  SUM(republished_count) as total_republished,
  AVG(duration_seconds) as avg_duration_sec,
  MAX(duration_seconds) as max_duration_sec
FROM `nba-props-platform.nba_orchestration.cleanup_operations`
WHERE DATE(cleanup_time, 'America/New_York') = CURRENT_DATE('America/New_York')
GROUP BY date;


Alert: High Missing File Count:

SELECT 
  cleanup_time,
  files_checked,
  missing_files_found,
  republished_count
FROM `nba-props-platform.nba_orchestration.cleanup_operations`
WHERE DATE(cleanup_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND missing_files_found > 5  -- Alert threshold
ORDER BY cleanup_time DESC;


Table 4: scraper_execution_log

Purpose: Log every scraper execution (when scrapers actually run)

Populated By: Scrapers (via scraper_base.py)

Schema:

CREATE TABLE `nba-props-platform.nba_orchestration.scraper_execution_log` (
  triggered_at TIMESTAMP,             -- When scraper started
  execution_id STRING,                -- Unique UUID
  scraper_name STRING,                -- Which scraper
  status STRING,                      -- SUCCESS or FAILED
  duration_seconds FLOAT64,           -- Execution time
  records_processed INT64,            -- Data collected
  gcs_path STRING,                    -- Output file location
  error_message STRING                -- If FAILED, what went wrong
)
PARTITION BY DATE(triggered_at)
CLUSTER BY scraper_name, status;


Current State: This table is empty because scrapers aren't being triggered automatically yet (Week 2-3).

Future State: When Workflow Executor is deployed, this table will track all scraper executions.

Example Future Data:

triggered_at: '2025-11-12T13:30:45-05:00'
execution_id: 'uuid-here'
scraper_name: 'oddsa_events'
status: 'SUCCESS'
duration_seconds: 28.5
records_processed: 12
gcs_path: 'gs://nba-scraped-data/oddsa-events/2025-11-12/133045.json'
error_message: NULL


Future Monitoring Queries:

Scraper Success Rate:

SELECT 
  scraper_name,
  COUNT(*) as total_runs,
  COUNTIF(status = 'SUCCESS') as successful,
  COUNTIF(status = 'FAILED') as failed,
  ROUND(COUNTIF(status = 'SUCCESS') / COUNT(*) * 100, 1) as success_rate_pct
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE DATE(triggered_at, 'America/New_York') >= CURRENT_DATE('America/New_York') - 7
GROUP BY scraper_name
ORDER BY success_rate_pct ASC, total_runs DESC;


Table 5: workflow_executions

Purpose: Track workflow execution attempts and link decision → execution → scraper runs

Populated By: Workflow Executor (5 min after master controller hourly)

Schema:

CREATE TABLE `nba-props-platform.nba_orchestration.workflow_executions` (
  execution_id STRING NOT NULL,        -- Unique UUID
  execution_time TIMESTAMP NOT NULL,   -- When execution started (partition key)
  workflow_name STRING NOT NULL,       -- Which workflow
  decision_id STRING,                  -- Links to workflow_decisions.decision_id
  
  -- Scraper tracking
  scrapers_requested ARRAY<STRING> NOT NULL,  -- Scrapers to execute
  scrapers_triggered INT64 NOT NULL,          -- Number attempted
  scrapers_succeeded INT64 NOT NULL,          -- Number succeeded
  scrapers_failed INT64 NOT NULL,             -- Number failed
  scraper_execution_ids ARRAY<STRING>,        -- Links to scraper_execution_log
  
  -- Status
  status STRING NOT NULL,              -- completed, failed
  duration_seconds FLOAT64,            -- Execution time
  error_message STRING                 -- If failed, why
)
PARTITION BY DATE(execution_time)
CLUSTER BY workflow_name, status
OPTIONS(
  partition_expiration_days = 90
);


Example Data:

execution_id: 'uuid-abc-123'
execution_time: '2025-11-12T18:05:30-05:00'
workflow_name: 'betting_lines'
decision_id: 'uuid-def-456'
scrapers_requested: ['oddsa_events', 'oddsa_player_props', 'oddsa_game_lines']
scrapers_triggered: 3
scrapers_succeeded: 3
scrapers_failed: 0
scraper_execution_ids: ['exec-001', 'exec-002', 'exec-003']
status: 'completed'
duration_seconds: 12.5
error_message: NULL


Typical Row Count:

0-20 rows per day (one per workflow execution)

Only workflows with RUN decisions create rows

Monitoring Queries:

Daily Summary:

SELECT 
  workflow_name,
  status,
  COUNT(*) as executions,
  AVG(duration_seconds) as avg_duration,
  SUM(scrapers_triggered) as total_scrapers,
  SUM(scrapers_succeeded) as total_succeeded,
  SUM(scrapers_failed) as total_failed
FROM `nba-props-platform.nba_orchestration.workflow_executions`
WHERE DATE(execution_time, 'America/New_York') = CURRENT_DATE('America/New_York')
GROUP BY workflow_name, status;


Execution Success Rate:

SELECT 
  workflow_name,
  COUNT(*) as total_executions,
  COUNTIF(status = 'completed') as successful,
  COUNTIF(status = 'failed') as failed,
  ROUND(COUNTIF(status = 'completed') / COUNT(*) * 100, 1) as success_rate_pct
FROM `nba-props-platform.nba_orchestration.workflow_executions`
WHERE DATE(execution_time, 'America/New_York') >= CURRENT_DATE('America/New_York') - 7
GROUP BY workflow_name
ORDER BY success_rate_pct ASC;


End-to-End Flow (Decision → Execution → Scrapers):

WITH flow AS (
  SELECT 
    d.workflow_name,
    d.decision_time,
    d.action,
    e.execution_time,
    e.status as execution_status,
    e.scrapers_triggered,
    e.scrapers_succeeded,
    e.scraper_execution_ids
  FROM `nba-props-platform.nba_orchestration.workflow_decisions` d
  LEFT JOIN `nba-props-platform.nba_orchestration.workflow_executions` e
    ON d.decision_id = e.decision_id
  WHERE DATE(d.decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
    AND d.action = 'RUN'
)
SELECT 
  f.workflow_name,
  f.decision_time,
  f.execution_time,
  f.execution_status,
  f.scrapers_triggered,
  f.scrapers_succeeded,
  COUNT(s.execution_id) as scraper_runs_logged
FROM flow f
LEFT JOIN `nba-props-platform.nba_orchestration.scraper_execution_log` s
  ON s.execution_id IN UNNEST(f.scraper_execution_ids)
GROUP BY 1,2,3,4,5,6
ORDER BY f.decision_time DESC;


---

## Related Documentation

**For architecture overview:** See `02-phase1-overview.md`

**For troubleshooting:** See `09-phase1-troubleshooting.md`

**For monitoring dashboards:** See `04-grafana-monitoring-guide.md`

---

**Last Updated:** 2025-11-15 11:20 PST
**Status:** ✅ Production Deployed & Operational


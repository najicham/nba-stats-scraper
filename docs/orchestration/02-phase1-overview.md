# Phase 1 Overview - Orchestration & Scheduling

**File:** `docs/orchestration/02-phase1-overview.md`
**Created:** 2025-11-13 10:06 PST (split from comprehensive guide)
**Last Updated:** 2025-11-15 11:15 PST (reorganization - split into focused docs)
**Purpose:** Architecture overview and deployment status for Phase 1 orchestration and scheduling
**Status:** Production Deployed
**Audience:** Engineers learning the Phase 1 system architecture

**Related Docs:**
- **BigQuery Schemas:** See `08-phase1-bigquery-schemas.md` for table structures
- **Troubleshooting:** See `09-phase1-troubleshooting.md` for manual operations and fixes
- **Monitoring:** See `04-grafana-monitoring-guide.md` for comprehensive monitoring queries

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current Architecture](#current-architecture)
3. [Deployed Components](#deployed-components)
4. [Cloud Scheduler Jobs](#cloud-scheduler-jobs)

---

## Executive Summary

### What's Deployed (November 12, 2025)

**Orchestration System Status:** ✅ OPERATIONAL

We have successfully deployed a 3-layer orchestration system that makes intelligent decisions about when NBA data scrapers should run, and automatically executes scrapers.

**Key Components:**

✅ Schedule Locker - Generates daily workflow plan (5 AM ET)

✅ Master Controller - Makes RUN/SKIP/ABORT decisions (hourly 6-11 PM ET)

✅ Workflow Executor - Executes scrapers based on decisions (5 min after controller)

✅ Cleanup Processor - Self-healing for missed Pub/Sub events (every 15 min)

✅ 5 BigQuery Tables - Complete audit trail of decisions and operations (see `08-phase1-bigquery-schemas.md`)

✅ 4 Cloud Scheduler Jobs - Fully automated orchestration

### What It Does

**Current State (November 12, 2025):**

```
5:00 AM ET → Schedule Locker generates daily plan
6:00 AM ET → Master Controller evaluates → RUN decisions logged
6:05 AM ET → Workflow Executor reads decisions → Scrapers execute
7:00 AM ET → Master Controller evaluates → RUN decisions logged
7:05 AM ET → Workflow Executor reads decisions → Scrapers execute
... continues hourly through 11 PM ET ...
```

The system knows when to scrape AND automatically executes scrapers. ✅

**Key Achievement:** 5-minute delay between decision and execution allows for:

- Decision auditing before execution
- Manual intervention if needed (pause scheduler)
- Clear separation of concerns

### Mission Statement

**Phase 1 Mission:**
Intelligently orchestrate 33 NBA data collection scrapers across 7 external sources based on game schedule, timing windows, and data availability patterns.

**Current State:**
Phase 1 orchestration is complete and operational. The system makes intelligent decisions AND executes scrapers automatically. No manual intervention required.

### Architecture Philosophy

**Three-Layer Design:**

**Configuration Layer** (config/workflows.yaml)
- Business logic: "Betting lines run 6h before games"
- Workflow definitions: Which scrapers, when, why

**Orchestration Layer** (Cloud Run: nba-scrapers)
- Schedule Locker: Plans daily execution
- Master Controller: Evaluates current conditions
- Decision Engine: RUN/SKIP/ABORT logic

**Monitoring Layer** (BigQuery)
- Daily plans: What SHOULD run
- Hourly decisions: What we DECIDED
- Audit trail: Complete history

**Future Layer** (Week 2-3):

**Execution Layer** (Workflow Executor)
- Reads RUN decisions
- Resolves scraper parameters
- Triggers scraper endpoints
- Tracks execution status

---

## Current Architecture

### System Diagram (Deployed Nov 12, 2025)

```
┌─────────────────────────────────────────────────────────────────┐
│  Cloud Scheduler (4 Jobs) - GCP Managed                        │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ 1. daily-schedule-locker    (5:00 AM ET)                  │ │
│  │ 2. master-controller-hourly (6-11 PM ET, every hour)      │ │
│  │ 3. cleanup-processor        (Every 15 minutes)            │ │
│  │ 4. execute-workflows        (6:05-11:05 PM ET, hourly)   │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                          ↓ HTTP POST
┌─────────────────────────────────────────────────────────────────┐
│  Cloud Run Service: nba-scrapers (us-west2)                    │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ Orchestration Endpoints (Flask)                           │ │
│  │ • POST /generate-daily-schedule → Schedule Locker         │ │
│  │ • POST /evaluate                → Master Controller       │ │
│  │ • POST /cleanup                 → Cleanup Processor       │ │
│  │ • POST /execute-workflows       → Workflow Executor       │ │
│  │                                                            │ │
│  │ Scraper Endpoints                                         │ │
│  │ • POST /scraper/{name}          → 33 scrapers            │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                          ↓ BigQuery Insert
┌─────────────────────────────────────────────────────────────────┐
│  BigQuery Dataset: nba_orchestration                           │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ 1. daily_expected_schedule (What SHOULD run)              │ │
│  │ 2. workflow_decisions (What we DECIDED - RUN/SKIP/ABORT)  │ │
│  │ 3. cleanup_operations (Self-healing activity)             │ │
│  │ 4. scraper_execution_log (Scraper runs - when they run)  │ │
│  │ 5. workflow_executions (Execution tracking)               │ │
│  └───────────────────────────────────────────────────────────┘ │
│  See 08-phase1-bigquery-schemas.md for table schemas          │
└─────────────────────────────────────────────────────────────────┘
                          ↓ HTTP POST /scrape
┌─────────────────────────────────────────────────────────────────┐
│  Layer 5: Scrapers (Cloud Run: nba-scrapers)                   │
│  • 33 scrapers operational                                      │
│  • Triggered automatically by Workflow Executor                 │
│  • Write JSON to GCS → Publish Pub/Sub events                   │
└─────────────────────────────────────────────────────────────────┘
```

### Daily Timeline (Actual as of Nov 12)

```
5:00 AM ET - Schedule Locker
    ↓ Reads game schedule
    ↓ Reads workflow config
    ↓ Generates daily plan
    ↓ Writes to: daily_expected_schedule
    Result: 5-20 workflows scheduled for today

6:00 AM ET - Master Controller (1st evaluation)
    ↓ Reads daily_expected_schedule
    ↓ Checks current time vs expected times
    ↓ Evaluates: Should "morning_operations" run now?
    ↓ Decision: RUN (ideal window 6-10 AM)
    ↓ Writes to: workflow_decisions
    Result: Decision logged

6:05 AM ET - Workflow Executor (1st execution)
    ↓ Reads workflow_decisions for RUN decisions
    ↓ Finds "morning_operations" RUN decision from 6:00 AM
    ↓ Resolves parameters for each scraper
    ↓ Calls: POST /scrape for each scraper
    ↓ Writes to: workflow_executions
    Result: Scrapers execute automatically

7:00 AM ET - Master Controller (2nd evaluation)
    ↓ Re-evaluates all workflows
    ↓ Decision: morning_operations already decided
    ↓ Decision: betting_lines - SKIP (games not for 12 hours)
    ↓ Writes to: workflow_decisions
    Result: More decisions logged

7:05 AM ET - Workflow Executor (2nd execution)
    ↓ Reads workflow_decisions for new RUN decisions
    ↓ Finds no new RUN decisions (only SKIP)
    ↓ No scrapers to execute
    Result: Quick check, no action needed

... Every hour 6 AM - 11 PM ET ...

Every 15 minutes - Cleanup Processor
    ↓ Checks for orphaned GCS files (files without BigQuery records)
    ↓ Checks for failed Pub/Sub deliveries
    ↓ Re-publishes events if needed
    ↓ Writes to: cleanup_operations
    Result: Self-healing activity tracked
```

### Data Flow

```
Configuration → Planning → Decision → Execution

config/workflows.yaml
    ↓ Read by Schedule Locker
daily_expected_schedule (BigQuery)
    ↓ Read by Master Controller
workflow_decisions (BigQuery)
    ↓ Read by Workflow Executor
workflow_executions (BigQuery)
    ↓ Read by Master Controller (check if already ran)
```

---

## Deployed Components

### 1. Schedule Locker

**Purpose:** Generate daily workflow execution plan at 5 AM ET

**Trigger:** Cloud Scheduler job `daily-schedule-locker` (5 AM ET daily)

**Endpoint:** `POST /generate-daily-schedule`

**What It Does:**

- Reads `config/workflows.yaml` for workflow definitions
- Queries game schedule for today
- Calculates expected run times for each workflow
- Writes plan to `daily_expected_schedule` table

**Example Output:**

```json
{
  "status": "success",
  "schedule": {
    "date": "2025-11-12",
    "games_scheduled": 12,
    "workflows_evaluated": 7,
    "expected_runs": 19,
    "locked_at": "2025-11-12T10:00:15.123456"
  }
}
```

**BigQuery Records Created:**

19 rows in `daily_expected_schedule` (one per workflow instance)

**Example Schedule Entry:**

```
date: '2025-11-12'
workflow_name: 'betting_lines'
expected_run_time: '2025-11-12T13:30:00-05:00'  -- 6h before first game
reason: 'Pre-game betting lines (12 games today)'
scrapers: ['oddsa_events', 'oddsa_player_props', 'oddsa_game_lines']
```

**Success Criteria:**

✅ Runs within 2 minutes (typical: 10-30 seconds)

✅ Generates 5-20 workflow entries (depends on game schedule)

✅ No errors in logs

**Monitoring Query:**

```sql
SELECT
  date,
  locked_at,
  COUNT(*) as workflows_scheduled
FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
WHERE date = CURRENT_DATE('America/New_York')
GROUP BY date, locked_at;
```

---

### 2. Master Controller

**Purpose:** Evaluate workflow execution decisions hourly

**Trigger:** Cloud Scheduler job `master-controller-hourly` (Every hour, 6 AM - 11 PM ET)

**Endpoint:** `POST /evaluate`

**What It Does:**

- Reads `daily_expected_schedule` for today
- For each workflow:
  - Check if within time window
  - Check if already ran today
  - Check game schedule/conditions
  - Evaluate dependencies
- Makes decision: RUN, SKIP, or ABORT
- Writes decisions to `workflow_decisions` table

**Example Output:**

```json
{
  "status": "success",
  "evaluation_time": "2025-11-12T18:30:00-05:00",
  "workflows_evaluated": 8,
  "decisions": [
    {
      "workflow": "betting_lines",
      "action": "RUN",
      "priority": "CRITICAL",
      "reason": "Ready: 12 games today, 0.3h until first game",
      "scrapers": ["oddsa_events", "oddsa_player_props", "oddsa_game_lines"],
      "alert_level": "NONE"
    },
    {
      "workflow": "morning_operations",
      "action": "SKIP",
      "reason": "Already completed today at 06:15 ET",
      "scrapers": [],
      "alert_level": "NONE"
    }
  ]
}
```

**BigQuery Records Created:**

8 rows in `workflow_decisions` (one per workflow evaluated)

**Decision Logic Examples:**

**RUN Decision:**
```
Workflow: betting_lines
Time: 1:30 PM ET
First game: 7:00 PM ET (5.5h away)
Expected: Run 6h before games (1:00 PM ± 30min window)
Decision: RUN (within window, games today, not yet run)
```

**SKIP Decision:**
```
Workflow: post_game_window_1
Time: 3:00 PM ET
Expected: 8:00 PM ET (±30min window)
Decision: SKIP (not in time window)
Next check: 8:00 PM ET
```

**ABORT Decision:**
```
Workflow: betting_lines
Time: 6:55 PM ET
First game: 7:00 PM ET (5 min away)
Expected: Run 6h before games
Decision: ABORT (missed window, too late to collect betting lines)
Alert: WARNING (workflow missed critical window)
```

**Success Criteria:**

✅ Runs every hour 6 AM - 11 PM ET (18 runs daily)

✅ Evaluates 5-8 workflows per run

✅ Completes within 2 minutes (typical: 10-20 seconds)

**Monitoring Query:**

```sql
SELECT
  EXTRACT(HOUR FROM decision_time AT TIME ZONE 'America/New_York') as hour_et,
  COUNT(*) as evaluations,
  COUNTIF(action = 'RUN') as run_decisions,
  COUNTIF(action = 'SKIP') as skip_decisions,
  COUNTIF(action = 'ABORT') as abort_decisions
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
GROUP BY hour_et
ORDER BY hour_et;
```

---

### 3. Cleanup Processor

**Purpose:** Self-healing - detect and recover from failed Pub/Sub deliveries

**Trigger:** Cloud Scheduler job `cleanup-processor` (Every 15 minutes)

**Endpoint:** `POST /cleanup`

**What It Does:**

- Queries `scraper_execution_log` for recent GCS files
- Checks if corresponding BigQuery records exist (Phase 2 processing)
- If missing: Re-publishes Pub/Sub event to trigger Phase 2 processor
- Tracks cleanup activity in `cleanup_operations` table

**Example Output:**

```json
{
  "status": "success",
  "cleanup_result": {
    "cleanup_id": "uuid-here",
    "duration_seconds": 0.85,
    "files_checked": 0,
    "missing_files_found": 0,
    "republished_count": 0
  }
}
```

**Example with Recovery:**

```json
{
  "cleanup_result": {
    "cleanup_id": "uuid-here",
    "duration_seconds": 2.34,
    "files_checked": 15,
    "missing_files_found": 2,
    "republished_count": 2,
    "recovered_files": [
      "gs://bucket/oddsa-events/2025-11-12/140530.json",
      "gs://bucket/bdl-games/2025-11-12/141022.json"
    ]
  }
}
```

**Recovery Scenario:**

1. Scraper runs successfully at 2:00 PM
2. Writes to GCS: `gs://bucket/oddsa-events/2025-11-12/140000.json`
3. Publishes Pub/Sub event
4. Pub/Sub delivery fails (network issue)
5. Phase 2 processor never triggered
6. Cleanup Processor runs at 2:30 PM (30 min later)
7. Detects: GCS file exists, no BigQuery record
8. Re-publishes Pub/Sub event
9. Phase 2 processor triggered successfully
10. Data appears in BigQuery within 5 minutes

**Success Criteria:**

✅ Runs every 15 minutes (96 runs daily)

✅ Completes within 5 seconds (typical: 1-2 seconds)

✅ Missing files detected within 30-45 minutes

✅ Recovery rate >99%

**Monitoring Query:**

```sql
SELECT
  DATE(cleanup_time, 'America/New_York') as date,
  COUNT(*) as cleanup_runs,
  SUM(files_checked) as total_files_checked,
  SUM(missing_files_found) as total_missing,
  SUM(republished_count) as total_republished,
  AVG(duration_seconds) as avg_duration_sec
FROM `nba-props-platform.nba_orchestration.cleanup_operations`
WHERE DATE(cleanup_time, 'America/New_York') = CURRENT_DATE('America/New_York')
GROUP BY date;
```

**Alert Thresholds:**

⚠️ WARNING: >5 missing files in single run

🔴 CRITICAL: >10 missing files in single run

🔴 CRITICAL: No cleanup runs for >30 minutes

---

## Cloud Scheduler Jobs

### Overview

**Total Jobs:** 4 (all active as of Nov 12, 2025)

**Project:** nba-props-platform
**Region:** us-west2
**Timezone:** America/New_York (ET)

**List Jobs:**

```bash
gcloud scheduler jobs list --location=us-west2
```

---

### Job 1: daily-schedule-locker

**Purpose:** Generate daily workflow execution plan

**Schedule:**

- Cron: `0 10 * * *` (10 AM UTC = 5 AM ET)
- Timezone: America/New_York
- Frequency: Once daily at 5:00 AM ET

**Target:**

- Service: nba-scrapers (Cloud Run)
- Endpoint: `POST /generate-daily-schedule`
- Timeout: 180 seconds (3 minutes)

**Configuration:**

```
Job Name: daily-schedule-locker
Location: us-west2
Schedule: 0 10 * * * (America/New_York)
URI: https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/generate-daily-schedule
Method: POST
Body: {}
Auth: OIDC (scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com)
Attempt Deadline: 180s
Retry Config:
  Max Attempts: 3
  Max Backoff: 3600s
  Min Backoff: 5s
```

**Expected Behavior:**

- Runs automatically at 5:00 AM ET every day
- Completes within 10-30 seconds
- Generates 5-20 workflow entries in BigQuery
- No manual intervention required

**Manual Trigger:**

```bash
gcloud scheduler jobs run daily-schedule-locker --location=us-west2
```

**Verify Execution:**

```sql
SELECT * FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
WHERE date = CURRENT_DATE('America/New_York')
ORDER BY expected_run_time;
```

---

### Job 2: master-controller-hourly

**Purpose:** Evaluate workflow execution decisions

**Schedule:**

- Cron: `0 6-23 * * *` (Every hour from 6 AM to 11 PM ET)
- Timezone: America/New_York
- Frequency: 18 times daily (6 AM, 7 AM, ..., 11 PM)

**Target:**

- Service: nba-scrapers (Cloud Run)
- Endpoint: `POST /evaluate`
- Timeout: 180 seconds (3 minutes)

**Configuration:**

```
Job Name: master-controller-hourly
Location: us-west2
Schedule: 0 6-23 * * * (America/New_York)
URI: https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/evaluate
Method: POST
Body: {}
Auth: OIDC
Attempt Deadline: 180s
```

**Expected Behavior:**

- Runs automatically every hour 6 AM - 11 PM ET
- Completes within 10-20 seconds
- Evaluates 5-8 workflows per run
- Creates 5-8 BigQuery records per run (90-144 daily)

**Manual Trigger:**

```bash
gcloud scheduler jobs run master-controller-hourly --location=us-west2
```

**Verify Execution:**

```sql
SELECT
  decision_time,
  workflow_name,
  action,
  reason
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
ORDER BY decision_time DESC
LIMIT 20;
```

---

### Job 3: cleanup-processor

**Purpose:** Self-healing for failed Pub/Sub deliveries

**Schedule:**

- Cron: `*/15 * * * *` (Every 15 minutes)
- Timezone: America/New_York
- Frequency: 96 times daily (every 15 min × 24 hours)

**Target:**

- Service: nba-scrapers (Cloud Run)
- Endpoint: `POST /cleanup`
- Timeout: 180 seconds (3 minutes)

**Configuration:**

```
Job Name: cleanup-processor
Location: us-west2
Schedule: */15 * * * * (America/New_York)
URI: https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/cleanup
Method: POST
Body: {}
Auth: OIDC
Attempt Deadline: 180s
```

**Expected Behavior:**

- Runs automatically every 15 minutes
- Completes within 1-3 seconds (typical)
- Creates 1 BigQuery record per run (96 daily)
- Usually finds 0 missing files (healthy system)

**Manual Trigger:**

```bash
gcloud scheduler jobs run cleanup-processor --location=us-west2
```

**Verify Execution:**

```sql
SELECT
  cleanup_time,
  files_checked,
  missing_files_found,
  republished_count
FROM `nba-props-platform.nba_orchestration.cleanup_operations`
WHERE DATE(cleanup_time, 'America/New_York') = CURRENT_DATE('America/New_York')
ORDER BY cleanup_time DESC
LIMIT 10;
```

---

### Job 4: execute-workflows

**Purpose:** Execute pending workflows (read RUN decisions and trigger scrapers)

**Schedule:**

- Cron: `5 6-23 * * *` (5 minutes past every hour, 6 AM-11 PM ET)
- Timezone: America/New_York
- Frequency: 18 times daily (at :05 each hour)

**Target:**

- Service: nba-scrapers (Cloud Run)
- Endpoint: `POST /execute-workflows`
- Timeout: 180 seconds (3 minutes)

**Configuration:**

```
Job Name: execute-workflows
Location: us-west2
Schedule: 5 6-23 * * * (America/New_York)
URI: https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/execute-workflows
Method: POST
Body: {}
Auth: OIDC (scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com)
Attempt Deadline: 180s
Retry Config:
  Max Attempts: 3
  Max Backoff: 3600s
  Min Backoff: 5s
```

**Expected Behavior:**

- Runs automatically 5 minutes after master-controller
- Reads RUN decisions from `workflow_decisions` table
- Resolves parameters for each scraper
- Calls scrapers via HTTP: `POST /scrape`
- Tracks execution in `workflow_executions` table
- Completes within 30-60 seconds typically

**Manual Trigger:**

```bash
gcloud scheduler jobs run execute-workflows --location=us-west2
```

**Verify Execution:**

```sql
SELECT
  workflow_name,
  status,
  scrapers_triggered,
  scrapers_succeeded,
  scrapers_failed,
  duration_seconds
FROM `nba-props-platform.nba_orchestration.workflow_executions`
WHERE DATE(execution_time, 'America/New_York') = CURRENT_DATE('America/New_York')
ORDER BY execution_time DESC;
```

**Link to Decision:**

```sql
-- Trace decision → execution → scraper runs
SELECT
  d.workflow_name,
  d.action,
  d.decision_time,
  e.execution_time,
  e.status,
  e.scrapers_succeeded,
  e.scrapers_failed
FROM `nba-props-platform.nba_orchestration.workflow_decisions` d
LEFT JOIN `nba-props-platform.nba_orchestration.workflow_executions` e
  ON d.decision_id = e.decision_id
WHERE DATE(d.decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND d.action = 'RUN'
ORDER BY d.decision_time DESC;
```

---

### Managing Scheduler Jobs

**Pause All Jobs (Maintenance):**

```bash
for job in daily-schedule-locker master-controller-hourly cleanup-processor execute-workflows; do
  gcloud scheduler jobs pause $job --location=us-west2
done
```

**Resume All Jobs:**

```bash
for job in daily-schedule-locker master-controller-hourly cleanup-processor execute-workflows; do
  gcloud scheduler jobs resume $job --location=us-west2
done
```

**Check Job Status:**

```bash
gcloud scheduler jobs describe daily-schedule-locker --location=us-west2
```

**View Recent Executions:**

```bash
gcloud logging read \
  "resource.type=cloud_scheduler_job AND resource.labels.job_id=daily-schedule-locker" \
  --limit=10 \
  --format="table(timestamp,httpRequest.status,textPayload)"
```

---

## Related Documentation

**For BigQuery table schemas:** See `08-phase1-bigquery-schemas.md`

**For troubleshooting and manual operations:** See `09-phase1-troubleshooting.md`

**For comprehensive monitoring:** See `04-grafana-monitoring-guide.md`

**For daily health checks:** See `05-grafana-daily-health-check-guide.md`

---

**Last Updated:** 2025-11-15 11:15 PST
**Status:** ✅ Production Deployed & Operational

# Grafana Monitoring Guide - NBA Orchestration System

**Created:** 2025-11-14
**Purpose:** BigQuery queries and dashboard insights for Grafana monitoring

---

## Overview

This guide provides BigQuery queries for monitoring the NBA orchestration system through Grafana. The orchestration system logs all execution data to BigQuery tables, which Grafana can query directly.

### Key Tables

1. **`nba_orchestration.workflow_executions`** - High-level workflow execution tracking
2. **`nba_orchestration.scraper_execution_log`** - Detailed scraper execution logs

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

---

## Key Metrics to Monitor

### 1. Workflow Success Rate
Track overall health of orchestration system

### 2. Scraper Failure Rate
Identify problematic scrapers

### 3. Execution Duration
Detect performance degradation

### 4. Data Completeness
Monitor "no_data" status for scrapers

### 5. Error Patterns
Group errors by type for troubleshooting

---

## Grafana Dashboard Queries

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

**Metric:** Success rate per scraper

```sql
SELECT
  scraper_name,
  COUNTIF(status = 'success') as successes,
  COUNTIF(status = 'failed') as failures,
  COUNTIF(status = 'no_data') as no_data,
  COUNT(*) as total,
  ROUND(COUNTIF(status = 'success') / COUNT(*) * 100, 1) as success_rate
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY scraper_name
ORDER BY success_rate ASC, total DESC
```

**Visualization:** Table with conditional formatting on success_rate

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

### Normal Behavior

- **morning_operations workflow:** Runs daily around 8-10 AM ET
  - Triggers: ~34 scrapers (30 for br_season_roster + 4 foundation scrapers)
  - Expected failures: 0
  - Duration: 3-4 minutes

- **Game day workflows:** Run multiple times on game days
  - Higher scraper volume
  - More "no_data" results off-season

### Warning Signs

- Sudden increase in failure rate (>5%)
- Scrapers consistently returning "no_data" when games are scheduled
- Duration increases >50% from baseline
- No executions during expected windows
- All executions from single team failing (PHX, BKN, CHA - check team mapping)

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
- `docs/orchestration/handoff_2025-11-14.md` - Current fixes
- `docs/orchestration/phase1_monitoring_operations_guide.md` - Operations guide
- `DEPLOYMENT_PLAN.md` - Deployment procedures

**BigQuery Dataset:** nba-props-platform.nba_orchestration
**Tables:**
- workflow_executions
- scraper_execution_log

---

**End of Grafana Monitoring Guide**

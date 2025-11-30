# Grafana Monitoring Guide - Phase 2-3 Event-Driven Pipeline

**File:** `docs/monitoring/03-grafana-phase2-phase3-pipeline-monitoring.md`
**Created:** 2025-11-16
**Last Updated:** 2025-11-16
**Purpose:** Monitor Phase 2 raw processing and Phase 3 analytics pipeline health
**Status:** Current
**Related:** Phase 1 orchestration monitoring in `01-grafana-monitoring-guide.md`

---

## Overview

This guide provides monitoring queries for the **Phase 2→3 event-driven pipeline** that processes NBA data through:

1. **Phase 1 Scrapers** → Publish to `nba-phase1-scrapers-complete`
2. **Phase 2 Raw Processors** → Load to BigQuery, publish to `nba-phase2-raw-complete`
3. **Phase 3 Analytics Processors** → Compute analytics from raw data

**Key Focus:** Visibility into what **should** run vs what **did** run, detecting stuck/blocked processes.

---

## Key Tables

### `nba_orchestration.pipeline_execution_log`

**Purpose:** Track all Phase 2 and Phase 3 processor executions

**Key fields:**
```sql
execution_id STRING              -- Unique execution UUID
processor_name STRING            -- e.g., 'GameboxScoreProcessor'
phase STRING                     -- 'phase2' or 'phase3'
game_date DATE                   -- Date being processed
started_at TIMESTAMP             -- When processing started
completed_at TIMESTAMP           -- When processing finished
duration_seconds FLOAT64         -- How long it took

-- Status tracking
status STRING                    -- 'completed', 'failed', 'partial', 'blocked'
records_processed INT64          -- Number of records processed
records_succeeded INT64          -- Successfully processed
records_failed INT64             -- Failed processing
error_message STRING             -- Error details if failed

-- Triggering
trigger_source STRING            -- 'pubsub', 'scheduler', 'manual', 'backfill'
message_id STRING                -- Pub/Sub message that triggered this
source_table STRING              -- Which Phase 2 table triggered Phase 3

-- Performance
processing_mode STRING           -- 'full_date', 'incremental' (future)
affected_entity_count INT64      -- Number of entities affected (future)
```

### `nba_orchestration.expected_processing_schedule`

**Purpose:** Track what processing SHOULD happen for each date

**Key fields:**
```sql
date DATE                        -- Game date
processor_name STRING            -- Which processor should run
phase STRING                     -- 'phase2' or 'phase3'
expected_run_time TIMESTAMP      -- When it should run
depends_on ARRAY<STRING>         -- Dependencies (e.g., ['GameboxScoreProcessor'])
reason STRING                    -- Why it's scheduled
generated_at TIMESTAMP           -- When schedule was generated
```

---

## Dashboard 1: Pipeline Health Overview

**Goal:** Answer "Is the Phase 2→3 pipeline healthy?" in 30 seconds

---

### Panel 1: Pipeline Health Status ⭐ MOST IMPORTANT

**Type:** Stat Panel (Large)
**Update:** Every 5 minutes

```sql
WITH
todays_expected AS (
  SELECT COUNT(DISTINCT processor_name) as expected_processors
  FROM `nba-props-platform.nba_orchestration.expected_processing_schedule`
  WHERE date = CURRENT_DATE('America/New_York')
),
todays_actual AS (
  SELECT
    COUNT(DISTINCT processor_name) as actual_processors,
    COUNTIF(status = 'completed') as completed,
    COUNTIF(status = 'failed') as failed,
    COUNTIF(status = 'blocked') as blocked
  FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`
  WHERE DATE(started_at, 'America/New_York') = CURRENT_DATE('America/New_York')
),
dlq_check AS (
  -- Note: This would need to query Pub/Sub metrics
  -- For now, use failed count as proxy
  SELECT COUNTIF(status = 'failed') as dlq_count
  FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`
  WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
)

SELECT
  CASE
    WHEN e.expected_processors > 0
     AND a.actual_processors >= e.expected_processors
     AND a.completed * 100.0 / NULLIF(a.completed + a.failed, 0) >= 95
     AND a.blocked = 0
    THEN '✅ HEALTHY'

    WHEN e.expected_processors > 0
     AND a.actual_processors >= e.expected_processors
     AND a.completed * 100.0 / NULLIF(a.completed + a.failed, 0) >= 80
    THEN '⚠️ DEGRADED'

    WHEN a.blocked > 0
    THEN '🚨 BLOCKED'

    WHEN e.expected_processors > 0 AND a.actual_processors < e.expected_processors
    THEN '⏸️ MISSING RUNS'

    WHEN e.expected_processors = 0
    THEN 'ℹ️ NO GAMES TODAY'

    ELSE '❌ UNHEALTHY'
  END as health_status,

  e.expected_processors,
  a.actual_processors,
  a.completed,
  a.failed,
  a.blocked,
  d.dlq_count

FROM todays_expected e
CROSS JOIN todays_actual a
CROSS JOIN dlq_check d
```

**Visualization:**
- Green: ✅ HEALTHY
- Yellow: ⚠️ DEGRADED
- Orange: ⏸️ MISSING RUNS
- Red: 🚨 BLOCKED or ❌ UNHEALTHY
- Blue: ℹ️ NO GAMES TODAY

---

### Panel 2: Expected vs Actual Processing ⭐ KEY VISIBILITY

**Type:** Table
**Update:** Every 5 minutes
**Purpose:** See exactly what should run vs what did run

```sql
WITH expected AS (
  SELECT
    processor_name,
    phase,
    expected_run_time,
    FORMAT_TIMESTAMP('%H:%M ET', expected_run_time, 'America/New_York') as expected_time,
    depends_on,
    reason
  FROM `nba-props-platform.nba_orchestration.expected_processing_schedule`
  WHERE date = CURRENT_DATE('America/New_York')
),
actual AS (
  SELECT
    processor_name,
    phase,
    MAX(started_at) as last_run,
    FORMAT_TIMESTAMP('%H:%M ET', MAX(started_at), 'America/New_York') as last_run_time,
    MAX(status) as status,
    MAX(error_message) as error
  FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`
  WHERE DATE(started_at, 'America/New_York') = CURRENT_DATE('America/New_York')
  GROUP BY processor_name, phase
)

SELECT
  e.processor_name as "Processor",
  e.phase as "Phase",
  e.expected_time as "Expected Time",
  COALESCE(a.last_run_time, '—') as "Actual Time",

  CASE
    WHEN a.processor_name IS NULL THEN '🔴 NOT RUN'
    WHEN a.status = 'blocked' THEN '🚧 BLOCKED'
    WHEN a.status = 'failed' THEN '❌ FAILED'
    WHEN a.status = 'partial' THEN '⚠️ PARTIAL'
    WHEN a.status = 'completed' THEN '✅ COMPLETED'
    ELSE '❓ UNKNOWN'
  END as "Status",

  TIMESTAMP_DIFF(a.last_run, e.expected_run_time, MINUTE) as "Minutes Late",

  CASE
    WHEN a.error IS NOT NULL THEN SUBSTR(a.error, 1, 100)
    ELSE '—'
  END as "Error (if any)",

  ARRAY_TO_STRING(e.depends_on, ', ') as "Dependencies"

FROM expected e
LEFT JOIN actual a
  ON e.processor_name = a.processor_name
  AND e.phase = a.phase

ORDER BY
  CASE
    WHEN a.processor_name IS NULL THEN 1  -- Not run (highest priority)
    WHEN a.status = 'blocked' THEN 2       -- Blocked
    WHEN a.status = 'failed' THEN 3        -- Failed
    WHEN a.status = 'partial' THEN 4       -- Partial
    ELSE 5                                  -- Completed
  END,
  e.expected_run_time
```

**Table Settings:**
- Conditional formatting on "Status" column
- Red background: NOT RUN, FAILED
- Orange background: BLOCKED, PARTIAL
- Green background: COMPLETED

**This is your most important panel!** It shows exactly what's missing or stuck.

---

### Panel 3: Blocked Processing Detection 🚧

**Type:** Table
**Update:** Every 1 minute
**Purpose:** Identify processes stuck waiting for dependencies

```sql
SELECT
  started_at as "Blocked Since",
  processor_name as "Processor",
  game_date as "Date",
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) as "Minutes Blocked",
  error_message as "Reason",

  CASE
    WHEN error_message LIKE '%dependency%' THEN '🔗 Dependency Missing'
    WHEN error_message LIKE '%data not found%' THEN '📭 Missing Data'
    WHEN error_message LIKE '%timeout%' THEN '⏱️ Timeout'
    ELSE '❓ Other'
  END as "Block Type"

FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`

WHERE status = 'blocked'
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)

ORDER BY started_at ASC  -- Oldest first (most urgent)
```

**Alert:** If any row appears, investigate immediately!

**Common block reasons:**
- **Dependency Missing:** Phase 3 waiting for Phase 2 data
- **Missing Data:** Historical data not available (backfill needed)
- **Timeout:** Processing taking too long

**Action for each:**
```bash
# Dependency Missing → Check Phase 2 ran successfully
./bin/processors/check_phase2_status.sh --date 2025-11-15

# Missing Data → Run backfill
python scripts/backfill_raw_data.py --table nbac_gamebook_player_stats --date 2025-11-10

# Timeout → Check processor performance, may need optimization
```

---

### Panel 4: Processing Lag (Phase 1→2→3)

**Type:** Time Series
**Update:** Every 5 minutes
**Purpose:** Track how long it takes data to flow through pipeline

```sql
WITH phase1_complete AS (
  SELECT
    JSON_VALUE(data_summary, '$.game_date') as game_date,
    completed_at as phase1_time
  FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
  WHERE scraper_name = 'nbac_gamebook_player_stats'
    AND status = 'success'
    AND triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
),
phase2_complete AS (
  SELECT
    game_date,
    MIN(completed_at) as phase2_time
  FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`
  WHERE processor_name = 'GameboxScoreProcessor'
    AND phase = 'phase2'
    AND status = 'completed'
    AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  GROUP BY game_date
),
phase3_complete AS (
  SELECT
    game_date,
    MIN(completed_at) as phase3_time
  FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`
  WHERE processor_name = 'PlayerGameSummaryProcessor'
    AND phase = 'phase3'
    AND status = 'completed'
    AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  GROUP BY game_date
)

SELECT
  p1.phase1_time as time,
  TIMESTAMP_DIFF(p2.phase2_time, p1.phase1_time, SECOND) as phase1_to_phase2_seconds,
  TIMESTAMP_DIFF(p3.phase3_time, p2.phase2_time, SECOND) as phase2_to_phase3_seconds,
  TIMESTAMP_DIFF(p3.phase3_time, p1.phase1_time, SECOND) as end_to_end_seconds

FROM phase1_complete p1
LEFT JOIN phase2_complete p2 ON p1.game_date = p2.game_date
LEFT JOIN phase3_complete p3 ON p1.game_date = p3.game_date

WHERE p2.phase2_time IS NOT NULL
  AND p3.phase3_time IS NOT NULL

ORDER BY time DESC
```

**Visualization:** Line chart with 3 series
- Phase 1→2 lag (should be <60s)
- Phase 2→3 lag (should be <30s)
- End-to-end lag (should be <90s)

**Thresholds:**
- Green: <2 minutes end-to-end
- Yellow: 2-5 minutes
- Red: >5 minutes

---

### Panel 5: DLQ Depth Monitor 🚨

**Type:** Stat Panel
**Update:** Every 1 minute
**Purpose:** Detect messages stuck in Dead Letter Queues

```sql
-- NOTE: This queries failed executions as a proxy for DLQ depth
-- Ideally, integrate with Pub/Sub metrics directly

SELECT
  COUNT(*) as dlq_messages

FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`

WHERE status IN ('failed', 'blocked')
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) > 15

-- Failed and stuck for >15 min = likely in DLQ
```

**Thresholds:**
- Green: 0
- Yellow: 1-2
- Red: >2

**If red:** Check DLQs immediately:
```bash
# Check Phase 1→2 DLQ
gcloud pubsub subscriptions describe nba-phase1-scrapers-complete-dlq-sub \
  --format="value(numUndeliveredMessages)"

# Check Phase 2→3 DLQ
gcloud pubsub subscriptions describe nba-phase2-raw-complete-dlq-sub \
  --format="value(numUndeliveredMessages)"

# Pull messages to investigate
gcloud pubsub subscriptions pull nba-phase1-scrapers-complete-dlq-sub --limit=5
```

---

### Panel 6: Processing Performance

**Type:** Table
**Update:** Every 10 minutes
**Purpose:** Track processor performance metrics

```sql
SELECT
  processor_name as "Processor",
  phase as "Phase",
  COUNT(*) as "Total Runs",
  COUNTIF(status = 'completed') as "Completed",
  COUNTIF(status = 'failed') as "Failed",
  COUNTIF(status = 'blocked') as "Blocked",

  ROUND(COUNTIF(status = 'completed') * 100.0 / COUNT(*), 1) as "Success Rate %",

  ROUND(AVG(duration_seconds), 1) as "Avg Duration (s)",
  ROUND(APPROX_QUANTILES(duration_seconds, 100)[OFFSET(95)], 1) as "P95 Duration (s)",

  ROUND(AVG(records_processed), 0) as "Avg Records",
  MAX(completed_at) as "Last Run"

FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`

WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)

GROUP BY processor_name, phase

ORDER BY "Success Rate %" ASC, "Total Runs" DESC
```

**Watch for:**
- Success rate <95% (red flag)
- P95 duration increasing over time (performance degradation)
- Processors not appearing (missing runs)

---

## Dashboard 2: Dependency Tracking

**Goal:** Understand data flow and dependency relationships

---

### Panel 7: Dependency Chain Visualization

**Type:** Table
**Update:** Every 10 minutes
**Purpose:** See which processors depend on which, and if dependencies are met

```sql
WITH processor_deps AS (
  SELECT
    processor_name,
    phase,
    depends_on
  FROM `nba-props-platform.nba_orchestration.expected_processing_schedule`
  WHERE date = CURRENT_DATE('America/New_York')
),
processor_status AS (
  SELECT
    processor_name,
    phase,
    MAX(status) as status,
    MAX(completed_at) as last_complete
  FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`
  WHERE DATE(started_at, 'America/New_York') = CURRENT_DATE('America/New_York')
  GROUP BY processor_name, phase
)

SELECT
  d.processor_name as "Processor",
  d.phase as "Phase",
  ARRAY_TO_STRING(d.depends_on, ', ') as "Depends On",

  -- Check if dependencies are met
  CASE
    WHEN ARRAY_LENGTH(d.depends_on) = 0 THEN '✅ No Dependencies'
    WHEN (
      SELECT COUNT(*)
      FROM UNNEST(d.depends_on) as dep
      LEFT JOIN processor_status ps
        ON ps.processor_name = dep
      WHERE ps.status = 'completed'
    ) = ARRAY_LENGTH(d.depends_on) THEN '✅ Dependencies Met'
    ELSE '❌ Dependencies Missing'
  END as "Dependency Status",

  s.status as "Processor Status",
  s.last_complete as "Last Complete"

FROM processor_deps d
LEFT JOIN processor_status s
  ON d.processor_name = s.processor_name
  AND d.phase = s.phase

ORDER BY d.phase, d.processor_name
```

**Use case:** When a processor is blocked, check if its dependencies completed.

---

### Panel 8: Historical Data Availability

**Type:** Table
**Update:** Every 30 minutes
**Purpose:** Detect missing historical data that might block processing

```sql
WITH date_range AS (
  -- Check last 7 days for data completeness
  SELECT date
  FROM UNNEST(GENERATE_DATE_ARRAY(
    DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY),
    CURRENT_DATE('America/New_York')
  )) as date
),
data_check AS (
  SELECT
    date,
    processor_name,
    COUNT(*) as run_count,
    COUNTIF(status = 'completed') as completed_count
  FROM date_range
  CROSS JOIN (
    SELECT DISTINCT processor_name
    FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`
  )
  LEFT JOIN `nba-props-platform.nba_orchestration.pipeline_execution_log`
    USING (processor_name)
  WHERE DATE(started_at, 'America/New_York') = date
  GROUP BY date, processor_name
)

SELECT
  date as "Date",
  processor_name as "Processor",

  CASE
    WHEN completed_count > 0 THEN '✅ Available'
    WHEN run_count > 0 THEN '⚠️ Ran But Failed'
    ELSE '❌ Missing'
  END as "Data Status"

FROM data_check

WHERE completed_count = 0  -- Only show missing/failed

ORDER BY date DESC, processor_name
```

**Use case:** If Phase 3 is blocked waiting for "week-old data", this shows what's missing.

**Action:**
```bash
# Backfill missing data
python scripts/backfill_phase2.py --processor GameboxScoreProcessor --date 2025-11-10
```

---

### Panel 9: Stuck Messages (Needs Manual Intervention)

**Type:** Table
**Update:** Every 5 minutes
**Purpose:** Identify processing stuck for >1 hour that needs manual action

```sql
SELECT
  started_at as "Stuck Since",
  processor_name as "Processor",
  game_date as "Date",
  status as "Status",
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, HOUR) as "Hours Stuck",

  error_message as "Error",

  CASE
    WHEN error_message LIKE '%missing%historical%data%' THEN '🔧 Backfill Needed'
    WHEN error_message LIKE '%dependency%' THEN '🔗 Check Dependencies'
    WHEN error_message LIKE '%permission%' THEN '🔒 Check Permissions'
    WHEN error_message LIKE '%quota%' THEN '💰 Check Quotas'
    ELSE '❓ Investigate'
  END as "Recommended Action"

FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`

WHERE status IN ('blocked', 'failed')
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, HOUR) >= 1

ORDER BY started_at ASC
```

**Red flag:** Any processing stuck for >1 hour needs immediate attention.

**Actions:**
- **Backfill Needed:** Run backfill script
- **Check Dependencies:** Verify upstream processors completed
- **Check Permissions:** Verify service account has BigQuery access
- **Check Quotas:** Verify BigQuery quotas not exceeded

---

## Dashboard 3: Performance & Optimization

**Goal:** Track performance metrics for optimization decisions (Sprint 8+)

---

### Panel 10: Processing Waste Detection

**Type:** Table
**Update:** Every 30 minutes
**Purpose:** Identify processors reprocessing unchanged data (for Sprint 8 decision)

```sql
SELECT
  processor_name as "Processor",
  game_date as "Date",
  records_processed as "Records Processed",

  -- Future: track records that actually changed
  -- For now, track zero-record runs
  CASE
    WHEN records_processed = 0 THEN '🟡 No Data Processed'
    WHEN records_processed < 10 THEN '🟢 Small Processing'
    ELSE '✅ Normal'
  END as "Waste Indicator",

  duration_seconds as "Duration (s)",

  -- Calculate waste percentage for decisions
  ROUND(
    duration_seconds * 100.0 / NULLIF(
      (SELECT AVG(duration_seconds)
       FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`
       WHERE processor_name = main.processor_name),
      0
    ),
    1
  ) as "% of Avg Duration"

FROM `nba-props-platform.nba_orchestration.pipeline_execution_log` main

WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND records_processed = 0  -- Reprocessed but changed nothing

ORDER BY duration_seconds DESC
```

**Use case:** After 2-4 weeks of production data, use this to decide if Sprint 8 (entity-level) is worth it.

**Decision criteria:**
- If >30% of runs process 0 records → Consider entity-level granularity
- If duration >30s for 0-record runs → Optimization needed

---

### Panel 11: Entity-Level Processing Metrics (Future)

**Type:** Time Series
**Update:** Every 10 minutes
**Purpose:** Track entity-level processing performance (after Sprint 8)

```sql
-- This query will work once entity-level processing is implemented

SELECT
  TIMESTAMP_TRUNC(started_at, HOUR) as time,
  processor_name,
  processing_mode,  -- 'full_date' or 'incremental'

  AVG(affected_entity_count) as avg_entities,
  AVG(duration_seconds) as avg_duration,
  AVG(duration_seconds / NULLIF(affected_entity_count, 0)) as seconds_per_entity

FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`

WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND affected_entity_count > 0

GROUP BY time, processor_name, processing_mode

ORDER BY time DESC
```

**Expected results (after Sprint 8):**
- Incremental mode: 1-10 entities, <5s duration
- Full-date mode: 450 entities, 30-60s duration
- 60x speedup for incremental updates

---

## Alert Configurations

### Critical Alerts (Immediate Action Required)

**Alert 1: Processing Blocked**
```sql
-- Alert if any processor blocked for >15 minutes
SELECT COUNT(*) as blocked_count
FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`
WHERE status = 'blocked'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) > 15
HAVING blocked_count > 0
```
**Action:** Investigate dependencies and missing data immediately

---

**Alert 2: DLQ Growing**
```sql
-- Alert if DLQ has >5 messages
SELECT COUNT(*) as dlq_depth
FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`
WHERE status = 'failed'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, HOUR) <= 1
HAVING dlq_depth > 5
```
**Action:** Check DLQs and investigate error patterns

---

**Alert 3: Pipeline Lag Exceeds SLA**
```sql
-- Alert if end-to-end lag >10 minutes
-- (Use Panel 4 query, check end_to_end_seconds > 600)
```
**Action:** Check Phase 2 and Phase 3 service health

---

### Warning Alerts (Monitor Closely)

**Alert 4: Low Success Rate**
```sql
-- Alert if success rate <90% in last hour
SELECT
  ROUND(COUNTIF(status = 'completed') * 100.0 / COUNT(*), 1) as success_rate
FROM `nba-props-platform.nba_orchestration.pipeline_execution_log`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
HAVING success_rate < 90
```

---

**Alert 5: Missing Expected Processing**
```sql
-- Alert if expected processors haven't run by expected_time + 30 min
SELECT COUNT(*) as missing_count
FROM `nba-props-platform.nba_orchestration.expected_processing_schedule` e
LEFT JOIN `nba-props-platform.nba_orchestration.pipeline_execution_log` a
  ON e.processor_name = a.processor_name
  AND e.date = DATE(a.started_at, 'America/New_York')
WHERE e.date = CURRENT_DATE('America/New_York')
  AND e.expected_run_time < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
  AND a.execution_id IS NULL
HAVING missing_count > 0
```

---

## Quick Actions Reference

### When Panel 2 shows "🔴 NOT RUN"

1. Check if Phase 1 scraper completed:
   ```bash
   ./bin/orchestration/check_system_status.sh
   ```

2. Check Pub/Sub subscription health:
   ```bash
   gcloud pubsub subscriptions describe nba-phase2-raw-sub
   ```

3. Check Phase 2/3 service logs:
   ```bash
   gcloud run services logs read nba-phase2-raw-processors --region=us-west2 --limit=50
   ```

---

### When Panel 3 shows blocked processing

1. **Dependency Missing:**
   ```bash
   # Check what's missing
   python scripts/check_dependencies.py --processor PlayerGameSummaryProcessor --date 2025-11-15

   # Run missing dependency
   python scripts/run_processor.py --processor GameboxScoreProcessor --date 2025-11-15
   ```

2. **Historical Data Missing:**
   ```bash
   # Backfill raw data
   python scripts/backfill_raw_data.py --table nbac_gamebook_player_stats --start-date 2025-11-10 --end-date 2025-11-15

   # Then reprocess Phase 3
   python scripts/backfill_analytics.py --processor PlayerGameSummaryProcessor --start-date 2025-11-10
   ```

---

### When Panel 5 shows DLQ depth > 0

1. **Pull and inspect DLQ messages:**
   ```bash
   gcloud pubsub subscriptions pull nba-phase2-raw-complete-dlq-sub --limit=10 > /tmp/dlq_messages.json
   cat /tmp/dlq_messages.json
   ```

2. **Identify error pattern:**
   ```bash
   # Count error types
   cat /tmp/dlq_messages.json | jq '.[] | .message.data' | sort | uniq -c
   ```

3. **Fix root cause and republish:**
   ```bash
   # After fixing issue, republish messages
   python scripts/republish_dlq.py --subscription nba-phase2-raw-complete-dlq-sub
   ```

---

## Expected Patterns

### Normal Behavior (Game Day with 10 Games)

**Phase 2 Processing:**
- Expected runs: 10 (one per game)
- Success rate: >95%
- Avg duration: 30-60s per game
- Total processing: <10 minutes for all games

**Phase 3 Processing:**
- Expected runs: 30-50 (multiple analytics processors)
- Success rate: >95%
- Avg duration: 10-30s per processor
- Total processing: <20 minutes for all analytics

**Pipeline Lag:**
- Phase 1→2: <60 seconds
- Phase 2→3: <30 seconds
- End-to-end: <90 seconds

**DLQ Depth:**
- Phase 1→2 DLQ: 0 messages
- Phase 2→3 DLQ: 0 messages

---

### Warning Signs

**🔴 Critical Issues:**
- Any processor blocked >15 minutes
- DLQ depth >5 messages
- Pipeline lag >10 minutes
- Success rate <80%
- Missing >3 expected processors

**⚠️ Warning Signs:**
- Success rate 80-95%
- Pipeline lag 2-5 minutes
- DLQ depth 1-2 messages
- Processor missing expected run time by >30 minutes

---

## Dashboard Refresh Settings

**Recommended refresh intervals:**
- Critical panels (Health, Blocked, DLQ): **Every 1 minute**
- Standard panels (Expected vs Actual, Performance): **Every 5 minutes**
- Historical panels (Trends, Waste Detection): **Every 30 minutes**

**Time range:** "Today so far" (from midnight ET to now)

---

## Integration with Phase 1 Monitoring

**Combined health check workflow:**

1. **Check Phase 1 Orchestration** (Dashboard from `01-grafana-monitoring-guide.md`)
   - Are scrapers running?
   - Are workflows executing?

2. **Check Phase 2-3 Pipeline** (This dashboard)
   - Is processing happening?
   - Any blocked/stuck processes?

3. **Check End-to-End Flow**
   - Phase 1 scrapers → Phase 2 processors → Phase 3 analytics
   - Total latency from scrape to analytics

**One unified view:** Create a master dashboard with both Phase 1 and Phase 2-3 panels.

---

## Related Documentation

**Phase-Based Pipeline:**
- `docs/01-architecture/pipeline-design.md` - Overall design
- `docs/01-architecture/orchestration/` - v1.0 Pub/Sub orchestration
- `docs/02-operations/orchestrator-monitoring.md` - Orchestrator operations

**Orchestration (Phase 1):**
- `01-grafana-monitoring-guide.md` - Phase 1 workflow monitoring
- `02-grafana-daily-health-check.md` - Quick daily check

**Infrastructure:**
- `docs/infrastructure/PUBSUB_AND_SERVICE_NAMES.md` - Resource naming
- `docs/HANDOFF-2025-11-16-phase-rename-complete.md` - Current deployment state

---

## Future Enhancements

**Sprint 8 (Entity-Level Monitoring):**
- Track incremental vs full-date processing split
- Monitor entity-level processing efficiency
- Measure 60x speedup achievement
- Detect entity-level expansion patterns

**Additional Metrics:**
- BigQuery slot usage by processor
- Cost per processor execution
- Data lineage tracking (which raw tables → which analytics)
- Processing queue depth over time

---

**Last Updated:** 2025-11-16
**Version:** 1.0
**Status:** Ready for Implementation (after Phase 2-3 deployment)
**Next Review:** After first week of production data

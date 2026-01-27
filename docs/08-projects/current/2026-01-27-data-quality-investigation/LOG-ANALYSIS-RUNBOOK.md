# Log Analysis Runbook

**Created:** 2026-01-27
**Purpose:** Step-by-step guide for using structured logs to diagnose pipeline failures

---

## Quick Start

When investigating a pipeline failure, follow this process:

1. **Identify the failure** (symptom: missing data, late arrival, incorrect values)
2. **Determine the date and processor** involved
3. **Run the appropriate query** from [log-analysis-queries.sql](./log-analysis-queries.sql)
4. **Analyze the structured log output** using this guide
5. **Document findings** in the incident report

---

## Common Failure Scenarios

### Scenario 1: "Why did player stats run before team stats?"

**Symptom:** Player stats show 0 values because team stats weren't available yet

**Root Cause:** Dependency timing issue

**Investigation Steps:**

```bash
# 1. Check processing order
bq query --use_legacy_sql=false --parameter=game_date:STRING:2026-01-27 '
SELECT
  FORMAT_TIMESTAMP("%Y-%m-%d %H:%M:%S UTC", timestamp) as time,
  jsonPayload.processor,
  jsonPayload.event,
  jsonPayload.all_dependencies_ready
FROM `nba-props-platform.logs`
WHERE jsonPayload.event = "processor_started"
  AND jsonPayload.game_date = @game_date
ORDER BY timestamp
'

# 2. Check dependency details
bq query --use_legacy_sql=false --parameter=game_date:STRING:2026-01-27 '
SELECT
  jsonPayload.processor,
  jsonPayload.dependencies_status
FROM `nba-props-platform.logs`
WHERE jsonPayload.event = "processor_started"
  AND jsonPayload.processor = "player_game_summary"
  AND jsonPayload.game_date = @game_date
'
```

**What to Look For:**
- `all_dependencies_ready: false` → Processor started before deps were ready
- `dependencies_status` → Check which tables were stale/missing
- `staleness_hours > 2` → Upstream data was too old

**Resolution:**
- If dependency check passed incorrectly: Fix dependency threshold in processor
- If dependency bypassed (backfill mode): Expected behavior, verify pre-flight checks
- If race condition: Add stricter dependency checks or adjust orchestrator timing

---

### Scenario 2: "Why did MERGE fall back to DELETE+INSERT?"

**Symptom:** Data duplicates or unexpected DELETE operations

**Root Cause:** MERGE statement failed, fell back to DELETE+INSERT strategy

**Investigation Steps:**

```bash
# Check MERGE fallbacks
bq query --use_legacy_sql=false '
SELECT
  FORMAT_TIMESTAMP("%Y-%m-%d %H:%M:%S UTC", timestamp) as time,
  jsonPayload.processor,
  jsonPayload.reason,
  jsonPayload.error_message,
  jsonPayload.primary_keys,
  jsonPayload.update_fields_count
FROM `nba-props-platform.logs`
WHERE jsonPayload.event = "merge_fallback"
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY timestamp DESC
'
```

**What to Look For:**
- `reason: "syntax_error"` → Invalid MERGE query (check primary keys, update fields)
- `reason: "streaming_buffer"` → BigQuery streaming buffer conflict
- `update_fields_count: 0` → No fields to update (schema issue)
- `error_message` → Full error text for diagnosis

**Resolution:**
- **syntax_error:** Check PRIMARY_KEY_FIELDS definition, verify schema alignment
- **streaming_buffer:** Wait 90 minutes or switch to MERGE strategy permanently
- **bad_request:** Check for schema mismatches (field types, names)

---

### Scenario 3: "Why did coordinator time out?"

**Symptom:** Phase 2→3 transition never happened, timeout exceeded

**Root Cause:** Some Phase 2 processors didn't complete in time

**Investigation Steps:**

```bash
# Check orchestrator progress (if logging implemented)
bq query --use_legacy_sql=false --parameter=game_date:STRING:2026-01-27 '
SELECT
  FORMAT_TIMESTAMP("%H:%M:%S UTC", timestamp) as time,
  jsonPayload.completed_count,
  jsonPayload.expected_count,
  jsonPayload.missing_processors,
  jsonPayload.elapsed_minutes
FROM `nba-props-platform.logs`
WHERE jsonPayload.event = "orchestrator_progress"
  AND jsonPayload.game_date = @game_date
ORDER BY timestamp
'

# Check which processors didn't complete
bq query --use_legacy_sql=false --parameter=game_date:STRING:2026-01-27 '
SELECT
  jsonPayload.processor,
  MIN(timestamp) as started_at,
  MAX(CASE WHEN jsonPayload.event = "phase_timing" THEN timestamp END) as completed_at
FROM `nba-props-platform.logs`
WHERE jsonPayload.game_date = @game_date
  AND jsonPayload.event IN ("processor_started", "phase_timing")
GROUP BY jsonPayload.processor
HAVING completed_at IS NULL
'
```

**What to Look For:**
- `missing_processors` → Which processors didn't finish
- `elapsed_minutes` → How long orchestrator waited
- `completed_at IS NULL` → Processor started but never finished

**Resolution:**
- Check processor logs for errors (Query #2 in log-analysis-queries.sql)
- Check for stuck processors (long-running without completion)
- Verify scrapers actually ran (check Phase 1/2 logs)

---

### Scenario 4: "When did betting lines arrive vs Phase 3 run?"

**Symptom:** Predictions used stale betting lines

**Root Cause:** Phase 3 ran before betting lines were ingested

**Investigation Steps:**

```bash
# Check phase timing correlation
bq query --use_legacy_sql=false --parameter=game_date:STRING:2026-01-27 '
WITH phase2_complete AS (
  SELECT MIN(timestamp) as phase2_done
  FROM `nba-props-platform.logs`
  WHERE jsonPayload.event = "orchestrator_progress"
    AND jsonPayload.will_trigger_next_phase = true
    AND jsonPayload.game_date = @game_date
),
betting_lines_arrival AS (
  SELECT MIN(timestamp) as lines_arrived
  FROM `nba-props-platform.logs`
  WHERE jsonPayload.processor LIKE "%betting%"
    AND jsonPayload.event = "phase_timing"
    AND jsonPayload.game_date = @game_date
),
phase3_start AS (
  SELECT MIN(timestamp) as phase3_started
  FROM `nba-props-platform.logs`
  WHERE jsonPayload.event = "processor_started"
    AND jsonPayload.game_date = @game_date
)
SELECT
  FORMAT_TIMESTAMP("%H:%M:%S", p2.phase2_done) as phase2_done,
  FORMAT_TIMESTAMP("%H:%M:%S", bl.lines_arrived) as betting_lines_done,
  FORMAT_TIMESTAMP("%H:%M:%S", p3.phase3_started) as phase3_started,
  TIMESTAMP_DIFF(bl.lines_arrived, p2.phase2_done, SECOND) as lines_after_phase2_sec,
  TIMESTAMP_DIFF(p3.phase3_started, bl.lines_arrived, SECOND) as phase3_after_lines_sec
FROM phase2_complete p2, betting_lines_arrival bl, phase3_start p3
'
```

**What to Look For:**
- `lines_after_phase2_sec < 0` → Betting lines arrived AFTER Phase 2 "complete"
- `phase3_after_lines_sec < 0` → Phase 3 started BEFORE betting lines arrived

**Resolution:**
- Add betting line processor to `EXPECTED_PROCESSORS` list
- Adjust Phase 2 completion criteria to wait for betting lines
- Consider separate orchestrator for betting lines (Phase 2b)

---

### Scenario 5: "Why did we skip processing this date?"

**Symptom:** No data in tables for a specific game_date

**Root Cause:** Streaming buffer prevented DELETE operation, processor skipped

**Investigation Steps:**

```bash
# Check for streaming buffer conflicts
bq query --use_legacy_sql=false --parameter=game_date:STRING:2026-01-27 '
SELECT
  FORMAT_TIMESTAMP("%Y-%m-%d %H:%M:%S UTC", timestamp) as time,
  jsonPayload.processor,
  jsonPayload.table,
  jsonPayload.records_affected,
  jsonPayload.retry_behavior
FROM `nba-props-platform.logs`
WHERE jsonPayload.event = "streaming_buffer_active"
  AND jsonPayload.game_dates LIKE CONCAT("%", @game_date, "%")
ORDER BY timestamp DESC
'
```

**What to Look For:**
- `event: "streaming_buffer_active"` → DELETE was blocked
- `will_retry: true` → Data will be processed on next trigger
- `retry_behavior` → When/how retry will happen

**Resolution:**
- **Short-term:** Wait 90 minutes for streaming buffer to flush, then re-trigger
- **Long-term:** Switch to MERGE strategy to avoid DELETE operations
- **Immediate:** Manually backfill the missed date using backfill script

---

## Log Event Reference

### processor_started
**Purpose:** Track when processors start and dependency status
**Key Fields:**
- `processor` - Processor name
- `game_date` - Date being processed
- `start_time` - ISO timestamp of start
- `dependencies_status` - Map of {table: {status, last_update, staleness_hours}}
- `all_dependencies_ready` - Boolean (true if all deps available)

**Example:**
```json
{
  "event": "processor_started",
  "processor": "player_game_summary",
  "game_date": "2026-01-27",
  "start_time": "2026-01-28T07:30:15.123Z",
  "dependencies_status": {
    "nba_raw.bdl_boxscores": {
      "status": "available",
      "last_update": "2026-01-28T06:15:30Z",
      "staleness_hours": 1.25
    }
  },
  "all_dependencies_ready": true
}
```

---

### phase_timing
**Purpose:** Track processor completion timing and performance
**Key Fields:**
- `phase` - Pipeline phase (e.g., "phase_3")
- `processor` - Processor name
- `game_date` - Date processed
- `completed_at` - ISO timestamp of completion
- `duration_seconds` - Total runtime
- `records_processed` - Number of records written
- `extract_time`, `transform_time`, `save_time` - Breakdown of duration

**Example:**
```json
{
  "event": "phase_timing",
  "phase": "phase_3",
  "processor": "player_game_summary",
  "game_date": "2026-01-27",
  "completed_at": "2026-01-28T07:32:45.678Z",
  "duration_seconds": 150.5,
  "records_processed": 281,
  "extract_time": 45.2,
  "transform_time": 90.1,
  "save_time": 15.2
}
```

---

### merge_fallback
**Purpose:** Track why MERGE operations fail and fallback to DELETE+INSERT
**Key Fields:**
- `processor` - Processor name
- `table` - Target table
- `reason` - Why MERGE failed (syntax_error, streaming_buffer, bad_request, etc.)
- `error_message` - First 500 chars of error
- `rows_affected` - How many rows were involved
- `fallback_strategy` - What fallback was used

**Example:**
```json
{
  "event": "merge_fallback",
  "processor": "PlayerGameSummaryProcessor",
  "table": "nba_analytics.player_game_summary",
  "reason": "syntax_error",
  "error_message": "Syntax error: Expected end of statement but got identifier...",
  "rows_affected": 281,
  "primary_keys": ["player_id", "game_date"],
  "update_fields_count": 0,
  "fallback_strategy": "DELETE_INSERT"
}
```

---

### streaming_buffer_active
**Purpose:** Track when streaming buffer prevents DELETE operations
**Key Fields:**
- `processor` - Processor name
- `table` - Table with streaming buffer conflict
- `operation` - Operation blocked (usually "DELETE")
- `game_dates` - List of dates affected
- `will_retry` - Whether it will retry automatically
- `retry_behavior` - When/how retry happens

**Example:**
```json
{
  "event": "streaming_buffer_active",
  "processor": "PlayerGameSummaryProcessor",
  "table": "nba_analytics.player_game_summary",
  "operation": "DELETE",
  "game_dates": ["2026-01-27"],
  "records_affected": 281,
  "will_retry": true,
  "retry_behavior": "Next trigger will process after buffer flushes (90 min max)"
}
```

---

### dependency_check_failed
**Purpose:** Track why dependency checks fail
**Key Fields:**
- `processor` - Processor name
- `game_date` - Date being checked
- `missing_critical` - List of missing critical dependencies
- `stale_fail` - List of stale dependencies (exceeded fail threshold)
- `dependency_details` - Map of {table: {status, staleness_hours, etc.}}

**Example:**
```json
{
  "event": "dependency_check_failed",
  "processor": "player_game_summary",
  "game_date": "2026-01-27",
  "missing_critical": ["nba_raw.team_game_summary"],
  "stale_fail": [],
  "dependency_details": {
    "nba_raw.team_game_summary": {
      "status": "missing",
      "last_update": null,
      "staleness_hours": null,
      "is_critical": true
    }
  }
}
```

---

## Cloud Logging Console Filters

**Quick filters for Cloud Logging UI:**

### All structured events for a date
```
jsonPayload.game_date="2026-01-27"
jsonPayload.event=~"processor_started|phase_timing|merge_fallback|streaming_buffer_active|dependency_check_failed"
```

### Errors only
```
jsonPayload.event=~"merge_fallback|dependency_check_failed|error"
severity>=ERROR
```

### Specific processor
```
jsonPayload.processor="player_game_summary"
jsonPayload.event=~"processor_started|phase_timing"
```

### Slow processors (>60 seconds)
```
jsonPayload.event="phase_timing"
jsonPayload.duration_seconds>60
```

---

## Integration with Existing Tools

### 1. BigQuery Views
Create views for common queries:

```sql
-- Save as nba_orchestration.v_recent_processor_runs
CREATE OR REPLACE VIEW nba_orchestration.v_recent_processor_runs AS
SELECT
  TIMESTAMP(jsonPayload.start_time) as started_at,
  TIMESTAMP(jsonPayload.completed_at) as completed_at,
  jsonPayload.processor,
  jsonPayload.game_date,
  jsonPayload.duration_seconds,
  jsonPayload.records_processed
FROM `nba-props-platform.logs`
WHERE jsonPayload.event IN ("processor_started", "phase_timing")
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY);
```

### 2. Monitoring Alerts
Set up log-based metrics for alerting:

```yaml
# Example Cloud Monitoring log metric
name: merge_fallback_rate
filter: jsonPayload.event="merge_fallback"
metric_descriptor:
  metric_kind: DELTA
  value_type: INT64
  labels:
    - key: processor
      value_type: STRING
```

### 3. Incident Response
Add to incident response checklist:
1. ✅ Run Query #2 (all errors in last 24h)
2. ✅ Run Query #1 (processing order for affected date)
3. ✅ Check dependency_check_failed events
4. ✅ Document findings in incident report

---

## Troubleshooting the Logs Themselves

### "No logs found for structured events"

**Possible causes:**
1. Logs not yet shipped to Cloud Logging (1-2 min delay)
2. `ENABLE_STRUCTURED_LOGGING` not enabled
3. Wrong project/dataset in query

**Resolution:**
```bash
# Check if structured logging is enabled
gcloud run services describe player-game-summary-service \
  --region=us-central1 \
  --format='value(spec.template.spec.containers[0].env)'

# Check recent logs (any event type)
bq query --use_legacy_sql=false '
SELECT COUNT(*) as log_count
FROM `nba-props-platform.logs`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
'
```

### "Query returns empty dependency_status"

**Possible cause:** Processor doesn't use dependency checking

**Resolution:** Only Phase 3 analytics processors log dependency status. For other phases, check pipeline_event_log table instead.

---

## Best Practices

1. **Always check logs BEFORE changing code** - Logs tell you what actually happened
2. **Save common queries as views** - Faster diagnosis in incidents
3. **Include log queries in incident reports** - Makes RCA traceable
4. **Set up alerts for critical events** - Proactive rather than reactive
5. **Update this runbook** - Add new scenarios as they're discovered

---

## Next Steps After Log Analysis

Once you've identified the root cause:

1. **Document in incident report** - Include log query results
2. **File bug/improvement ticket** - Link to log evidence
3. **Update monitors** - Prevent recurrence
4. **Update runbooks** - Share learnings with team
5. **Consider preventive fix** - Can we prevent this entirely?

---

**Last Updated:** 2026-01-27
**Owner:** Data Platform Team
**Related:** [LOGGING-IMPROVEMENTS.md](./LOGGING-IMPROVEMENTS.md), [log-analysis-queries.sql](./log-analysis-queries.sql)

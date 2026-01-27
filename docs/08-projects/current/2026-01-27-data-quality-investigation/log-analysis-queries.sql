-- Log Analysis Queries for Post-Mortem Diagnosis
-- Created: 2026-01-27
-- Purpose: Quick queries to diagnose pipeline failures using new structured logging

-- ==============================================================================
-- 1. PROCESSING ORDER FOR A DATE
-- ==============================================================================
-- Shows exact order processors ran, with dependency status and timing
-- Use this to answer: "Why did player stats run before team stats?"

SELECT
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S UTC', timestamp) as time,
  jsonPayload.processor,
  jsonPayload.event,
  jsonPayload.duration_seconds,
  jsonPayload.records_processed,
  jsonPayload.all_dependencies_ready,
  jsonPayload.dependencies_status
FROM `nba-props-platform.logs`
WHERE jsonPayload.event IN ("processor_started", "phase_timing")
  AND jsonPayload.game_date = "2026-01-27"  -- Replace with target date
ORDER BY timestamp;

-- ==============================================================================
-- 2. ALL ERRORS IN LAST 24 HOURS
-- ==============================================================================
-- Shows all structured error events with context
-- Use this to answer: "What failed and why?"

SELECT
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S UTC', timestamp) as time,
  jsonPayload.processor,
  jsonPayload.event,
  jsonPayload.error_message,
  jsonPayload.reason,
  jsonPayload.game_date,
  jsonPayload
FROM `nba-props-platform.logs`
WHERE jsonPayload.event IN (
    "merge_fallback",
    "dependency_check_failed",
    "streaming_buffer_active",
    "error"
  )
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY timestamp DESC;

-- ==============================================================================
-- 3. MERGE FALLBACK ANALYSIS
-- ==============================================================================
-- Shows why MERGEs failed and fell back to DELETE+INSERT
-- Use this to answer: "Why did MERGE fall back to DELETE+INSERT?"

SELECT
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S UTC', timestamp) as time,
  jsonPayload.processor,
  jsonPayload.table,
  jsonPayload.reason,
  jsonPayload.error_message,
  jsonPayload.rows_affected,
  jsonPayload.primary_keys,
  jsonPayload.update_fields_count
FROM `nba-props-platform.logs`
WHERE jsonPayload.event = "merge_fallback"
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY timestamp DESC;

-- ==============================================================================
-- 4. STREAMING BUFFER CONFLICTS
-- ==============================================================================
-- Shows when streaming buffer prevented DELETE operations
-- Use this to answer: "Why did we skip processing this date?"

SELECT
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S UTC', timestamp) as time,
  jsonPayload.processor,
  jsonPayload.table,
  jsonPayload.game_dates,
  jsonPayload.records_affected,
  jsonPayload.retry_behavior
FROM `nba-props-platform.logs`
WHERE jsonPayload.event = "streaming_buffer_active"
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY timestamp DESC;

-- ==============================================================================
-- 5. DEPENDENCY CHECK FAILURES
-- ==============================================================================
-- Shows which dependencies were missing or stale
-- Use this to answer: "Why didn't this processor run?"

SELECT
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S UTC', timestamp) as time,
  jsonPayload.processor,
  jsonPayload.game_date,
  jsonPayload.missing_critical,
  jsonPayload.stale_fail,
  jsonPayload.dependency_details
FROM `nba-props-platform.logs`
WHERE jsonPayload.event = "dependency_check_failed"
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY timestamp DESC;

-- ==============================================================================
-- 6. TIMING CORRELATION ACROSS PHASES
-- ==============================================================================
-- Shows gaps between Phase 2→3→4 transitions
-- Use this to answer: "When exactly did betting lines arrive vs Phase 3 run?"

WITH phase2_complete AS (
  SELECT
    MIN(timestamp) as phase2_done,
    jsonPayload.game_date
  FROM `nba-props-platform.logs`
  WHERE jsonPayload.event = "orchestrator_progress"
    AND jsonPayload.will_trigger_next_phase = true
    AND jsonPayload.game_date = "2026-01-27"  -- Replace with target date
  GROUP BY jsonPayload.game_date
),
phase3_start AS (
  SELECT
    MIN(timestamp) as phase3_started,
    jsonPayload.game_date
  FROM `nba-props-platform.logs`
  WHERE jsonPayload.event = "processor_started"
    AND jsonPayload.game_date = "2026-01-27"  -- Replace with target date
  GROUP BY jsonPayload.game_date
),
phase3_complete AS (
  SELECT
    MAX(timestamp) as phase3_done,
    jsonPayload.game_date
  FROM `nba-props-platform.logs`
  WHERE jsonPayload.event = "phase_timing"
    AND jsonPayload.phase = "phase_3"
    AND jsonPayload.game_date = "2026-01-27"  -- Replace with target date
  GROUP BY jsonPayload.game_date
)
SELECT
  p2.game_date,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S UTC', p2.phase2_done) as phase2_complete_time,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S UTC', p3s.phase3_started) as phase3_start_time,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S UTC', p3c.phase3_done) as phase3_complete_time,
  TIMESTAMP_DIFF(p3s.phase3_started, p2.phase2_done, SECOND) as phase2_to_3_gap_seconds,
  TIMESTAMP_DIFF(p3c.phase3_done, p3s.phase3_started, SECOND) as phase3_duration_seconds
FROM phase2_complete p2
LEFT JOIN phase3_start p3s ON p2.game_date = p3s.game_date
LEFT JOIN phase3_complete p3c ON p2.game_date = p3c.game_date;

-- ==============================================================================
-- 7. ORCHESTRATOR PROGRESS TIMELINE
-- ==============================================================================
-- Shows orchestrator progress over time (if orchestrator logging implemented)
-- Use this to answer: "Why did coordinator time out?"

SELECT
  FORMAT_TIMESTAMP('%H:%M:%S UTC', timestamp) as time,
  jsonPayload.completed_count,
  jsonPayload.expected_count,
  jsonPayload.completion_pct,
  jsonPayload.recently_completed,
  jsonPayload.missing_processors,
  jsonPayload.elapsed_minutes
FROM `nba-props-platform.logs`
WHERE jsonPayload.event = "orchestrator_progress"
  AND jsonPayload.game_date = "2026-01-27"  -- Replace with target date
ORDER BY timestamp;

-- ==============================================================================
-- 8. PROCESSOR DURATION ANALYSIS
-- ==============================================================================
-- Shows which processors took longest and why
-- Use this to answer: "Which processor is the bottleneck?"

SELECT
  jsonPayload.processor,
  jsonPayload.game_date,
  jsonPayload.duration_seconds,
  jsonPayload.records_processed,
  jsonPayload.extract_time,
  jsonPayload.transform_time,
  jsonPayload.save_time,
  jsonPayload.is_incremental,
  jsonPayload.entities_changed_count,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S UTC', timestamp) as completed_at
FROM `nba-props-platform.logs`
WHERE jsonPayload.event = "phase_timing"
  AND jsonPayload.game_date = "2026-01-27"  -- Replace with target date
ORDER BY jsonPayload.duration_seconds DESC;

-- ==============================================================================
-- 9. DEPENDENCY READINESS TIMELINE
-- ==============================================================================
-- Shows when each processor's dependencies became ready
-- Use this to answer: "When did the upstream data arrive?"

SELECT
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S UTC', timestamp) as processor_start_time,
  jsonPayload.processor,
  jsonPayload.game_date,
  jsonPayload.all_dependencies_ready,
  jsonPayload.dependency_check_seconds,
  dep_table,
  dep_status.status,
  dep_status.last_update,
  dep_status.staleness_hours
FROM `nba-props-platform.logs`,
  UNNEST(JSON_EXTRACT_ARRAY(TO_JSON_STRING(jsonPayload.dependencies_status))) AS dep WITH OFFSET dep_idx,
  UNNEST([STRUCT(
    JSON_EXTRACT_SCALAR(dep, '$.status') AS status,
    JSON_EXTRACT_SCALAR(dep, '$.last_update') AS last_update,
    CAST(JSON_EXTRACT_SCALAR(dep, '$.staleness_hours') AS FLOAT64) AS staleness_hours
  )]) AS dep_status,
  UNNEST([ARRAY(SELECT key FROM UNNEST(JSON_EXTRACT_ARRAY(TO_JSON_STRING(jsonPayload.dependencies_status))) WITH OFFSET WHERE OFFSET = dep_idx)[SAFE_OFFSET(0)]]) AS dep_table
WHERE jsonPayload.event = "processor_started"
  AND jsonPayload.game_date = "2026-01-27"  -- Replace with target date
ORDER BY timestamp, jsonPayload.processor, dep_table;

-- ==============================================================================
-- 10. FAILURE RATE BY PROCESSOR
-- ==============================================================================
-- Shows which processors fail most often
-- Use this to answer: "Which processor is least reliable?"

WITH all_runs AS (
  SELECT
    jsonPayload.processor,
    DATE(timestamp) as run_date,
    COUNTIF(jsonPayload.event = "phase_timing") as success_count,
    COUNTIF(jsonPayload.event IN ("dependency_check_failed", "error", "merge_fallback")) as failure_count
  FROM `nba-props-platform.logs`
  WHERE jsonPayload.processor IS NOT NULL
    AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  GROUP BY jsonPayload.processor, run_date
)
SELECT
  processor,
  SUM(success_count) as total_successes,
  SUM(failure_count) as total_failures,
  ROUND(SUM(failure_count) / (SUM(success_count) + SUM(failure_count)) * 100, 2) as failure_rate_pct
FROM all_runs
GROUP BY processor
ORDER BY failure_rate_pct DESC;

-- ==============================================================================
-- USAGE NOTES
-- ==============================================================================
/*
1. Replace placeholder dates ("2026-01-27") with actual target dates
2. Adjust time windows (INTERVAL 24 HOUR) as needed
3. For parameterized queries in scripts, use @game_date parameter
4. Save frequently used queries as views in BigQuery for easier access

RECOMMENDED SAVED VIEWS:
- `v_processor_timeline`: Query #1 (processing order)
- `v_recent_errors`: Query #2 (errors in last 24h)
- `v_merge_failures`: Query #3 (MERGE fallbacks)
- `v_phase_timing`: Query #6 (phase timing correlation)

CREATE VIEW nba_orchestration.v_processor_timeline AS
  SELECT ... (Query #1)

Then query with:
  SELECT * FROM nba_orchestration.v_processor_timeline
  WHERE game_date = "2026-01-27"
*/

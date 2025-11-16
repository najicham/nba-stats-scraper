-- Pipeline Health Monitoring Queries
-- See docs/architecture/03-pipeline-monitoring-and-error-handling.md for context

-- Query 1: Pipeline Completion Status (Today)
-- Detects stuck pipelines that didn't complete end-to-end
WITH pipeline_phases AS (
    SELECT
        correlation_id,
        game_date,
        MAX(phase) as max_phase_reached,
        COUNTIF(status = 'failed') as failure_count,
        ARRAY_AGG(
            IF(status = 'failed',
               STRUCT(phase, processor_name, error_message),
               NULL)
            IGNORE NULLS
        ) as failures
    FROM nba_orchestration.pipeline_execution_log
    WHERE game_date = CURRENT_DATE('America/New_York')
    GROUP BY correlation_id, game_date
)
SELECT
    correlation_id,
    game_date,
    max_phase_reached,
    failure_count,
    failures
FROM pipeline_phases
WHERE max_phase_reached < 6  -- Didn't reach Phase 6 (publishing)
  OR failure_count > 0
ORDER BY game_date DESC, max_phase_reached ASC
LIMIT 100;


-- Query 2: Phase-by-Phase Breakdown (Today)
-- Shows execution stats for each phase
SELECT
    phase,
    COUNT(*) as executions,
    COUNTIF(status = 'completed') as successes,
    COUNTIF(status = 'failed') as failures,
    COUNTIF(status = 'skipped') as skipped,
    AVG(duration_seconds) as avg_duration,
    MAX(duration_seconds) as max_duration
FROM nba_orchestration.pipeline_execution_log
WHERE game_date = CURRENT_DATE('America/New_York')
GROUP BY phase
ORDER BY phase;


-- Query 3: Recent Failures (Last 24 Hours)
-- Identifies error patterns
SELECT
    phase,
    processor_name,
    error_type,
    error_message,
    COUNT(*) as occurrence_count,
    MAX(started_at) as last_occurrence
FROM nba_orchestration.pipeline_execution_log
WHERE status = 'failed'
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY phase, processor_name, error_type, error_message
ORDER BY last_occurrence DESC
LIMIT 20;


-- Query 4: Track Specific Entity Through Pipeline
-- Example: Did LeBron's injury update reach Phase 6?
SELECT
    phase,
    processor_name,
    status,
    started_at,
    completed_at,
    duration_seconds,
    JSON_EXTRACT_SCALAR(affected_entities, '$.players[0]') as player_id
FROM nba_orchestration.pipeline_execution_log
WHERE game_date = '2025-11-15'
  AND JSON_EXTRACT_SCALAR(affected_entities, '$.players[0]') = '1630567'  -- LeBron
ORDER BY phase, started_at;


-- Query 5: Pipeline Health Overview (Grafana Panel)
-- Single-row summary for dashboard
SELECT
    COUNT(DISTINCT correlation_id) as total_pipelines,
    COUNTIF(max_phase >= 6) as completed_pipelines,
    COUNTIF(max_phase < 6) as incomplete_pipelines,
    COUNTIF(has_failures) as failed_pipelines,
    ROUND(AVG(avg_duration), 2) as avg_pipeline_duration_seconds
FROM (
    SELECT
        correlation_id,
        MAX(phase) as max_phase,
        COUNTIF(status = 'failed') > 0 as has_failures,
        AVG(duration_seconds) as avg_duration
    FROM nba_orchestration.pipeline_execution_log
    WHERE game_date = CURRENT_DATE('America/New_York')
    GROUP BY correlation_id
);


-- Query 6: Dependency Check Failures
-- Find which dependencies are frequently missing
SELECT
    processor_name,
    game_date,
    missing_dependencies,
    COUNT(*) as skip_count,
    MAX(started_at) as last_skip
FROM nba_orchestration.pipeline_execution_log,
UNNEST(missing_dependencies) as missing_dep
WHERE status = 'skipped'
  AND dependencies_met = FALSE
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY processor_name, game_date, missing_dependencies
ORDER BY skip_count DESC, last_skip DESC
LIMIT 50;


-- Query 7: Correlation ID Tracking (Specific Pipeline)
-- Track entire pipeline journey for debugging
SELECT
    phase,
    processor_name,
    status,
    started_at,
    completed_at,
    duration_seconds,
    error_message,
    dependencies_met,
    records_processed
FROM nba_orchestration.pipeline_execution_log
WHERE correlation_id = 'CORRELATION_ID_HERE'  -- Replace with actual correlation_id
ORDER BY phase, started_at;


-- Query 8: Average Pipeline Latency (Phase 1 to Phase 6)
-- How long does it take for data to flow end-to-end?
WITH pipeline_times AS (
    SELECT
        correlation_id,
        MIN(started_at) as pipeline_start,
        MAX(completed_at) as pipeline_end,
        MAX(phase) as max_phase
    FROM nba_orchestration.pipeline_execution_log
    WHERE game_date = CURRENT_DATE('America/New_York')
      AND status = 'completed'
    GROUP BY correlation_id
    HAVING max_phase = 6  -- Only complete pipelines
)
SELECT
    COUNT(*) as complete_pipelines,
    AVG(TIMESTAMP_DIFF(pipeline_end, pipeline_start, SECOND)) as avg_latency_seconds,
    MIN(TIMESTAMP_DIFF(pipeline_end, pipeline_start, SECOND)) as min_latency_seconds,
    MAX(TIMESTAMP_DIFF(pipeline_end, pipeline_start, SECOND)) as max_latency_seconds
FROM pipeline_times;

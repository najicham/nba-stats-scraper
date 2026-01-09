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


-- =============================================================================
-- PREDICTION SYSTEM HEALTH MONITORING
-- =============================================================================
-- These queries detect prediction system failures that can cause 0% actionable
-- predictions (as occurred on 2026-01-09).


-- Query 9: Fallback Prediction Detection (CRITICAL ALERT)
-- Avg confidence of 50.0 indicates fallback predictions were used
-- This means the ML model failed to load or generate real predictions
SELECT
    system_id,
    game_date,
    COUNT(*) as total_predictions,
    COUNTIF(recommendation = 'OVER') as over_count,
    COUNTIF(recommendation = 'UNDER') as under_count,
    COUNTIF(recommendation = 'PASS') as pass_count,
    ROUND(AVG(confidence_score), 2) as avg_confidence,
    COUNTIF(confidence_score = 50.0) as fallback_count,
    ROUND(100.0 * COUNTIF(confidence_score = 50.0) / COUNT(*), 1) as fallback_pct
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v8'
GROUP BY system_id, game_date
HAVING avg_confidence = 50.0  -- CRITICAL: All predictions are fallbacks
    OR over_count = 0  -- CRITICAL: No OVER recommendations
    OR under_count = 0;  -- CRITICAL: No UNDER recommendations


-- Query 10: Prediction System Comparison (Today)
-- Compare performance across all 5 prediction systems
SELECT
    system_id,
    COUNT(*) as total_predictions,
    COUNTIF(recommendation = 'OVER') as overs,
    COUNTIF(recommendation = 'UNDER') as unders,
    COUNTIF(recommendation = 'PASS') as passes,
    COUNTIF(recommendation = 'NO_LINE') as no_lines,
    ROUND(AVG(confidence_score), 2) as avg_confidence,
    ROUND(STDDEV(confidence_score), 2) as stddev_confidence,
    MIN(confidence_score) as min_confidence,
    MAX(confidence_score) as max_confidence
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
GROUP BY system_id
ORDER BY system_id;


-- Query 11: Actionable Prediction Rate (Daily Trend)
-- Track OVER/UNDER recommendation rates over time
SELECT
    game_date,
    system_id,
    COUNT(*) as total,
    ROUND(100.0 * COUNTIF(recommendation IN ('OVER', 'UNDER')) / COUNT(*), 1) as actionable_pct,
    ROUND(AVG(confidence_score), 2) as avg_confidence
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND system_id = 'catboost_v8'
GROUP BY game_date, system_id
ORDER BY game_date DESC;


-- Query 12: Feature Version Validation
-- Verify ML Feature Store is producing correct version
SELECT
    game_date,
    feature_version,
    COUNT(*) as row_count,
    AVG(ARRAY_LENGTH(features)) as avg_feature_count,
    COUNTIF(ARRAY_LENGTH(features) = 33) as correct_count,
    COUNTIF(ARRAY_LENGTH(features) != 33) as incorrect_count
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date, feature_version
ORDER BY game_date DESC;


-- Query 13: Prediction Worker Health (Today)
-- Single-row summary for alerting dashboard
SELECT
    CURRENT_DATE() as check_date,
    -- Overall prediction count
    (SELECT COUNT(DISTINCT universal_player_id)
     FROM `nba-props-platform.nba_predictions.player_prop_predictions`
     WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v8') as players_predicted,
    -- Actionable predictions
    (SELECT COUNTIF(recommendation IN ('OVER', 'UNDER'))
     FROM `nba-props-platform.nba_predictions.player_prop_predictions`
     WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v8') as actionable_predictions,
    -- Fallback detection
    (SELECT ROUND(AVG(confidence_score), 2)
     FROM `nba-props-platform.nba_predictions.player_prop_predictions`
     WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v8') as catboost_avg_confidence,
    -- Feature store health
    (SELECT COUNT(*)
     FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
     WHERE game_date = CURRENT_DATE() AND feature_version = 'v2_33features') as feature_store_rows,
    -- Alert conditions
    CASE
        WHEN (SELECT AVG(confidence_score)
              FROM `nba-props-platform.nba_predictions.player_prop_predictions`
              WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v8') = 50.0
        THEN 'CRITICAL: CatBoost using fallback predictions'
        WHEN (SELECT COUNTIF(recommendation IN ('OVER', 'UNDER'))
              FROM `nba-props-platform.nba_predictions.player_prop_predictions`
              WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v8') = 0
        THEN 'CRITICAL: No actionable predictions'
        WHEN (SELECT COUNT(*)
              FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
              WHERE game_date = CURRENT_DATE() AND feature_version = 'v2_33features') = 0
        THEN 'WARNING: No v2_33features in feature store today'
        ELSE 'OK'
    END as health_status;

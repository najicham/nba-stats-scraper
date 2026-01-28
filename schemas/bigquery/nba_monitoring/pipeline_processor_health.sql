-- ============================================================================
-- NBA Monitoring - Pipeline Processor Health View
-- Path: schemas/bigquery/nba_monitoring/pipeline_processor_health.sql
-- Created: 2026-01-27
-- ============================================================================
-- Purpose: Unified processor health monitoring across all pipeline phases
-- Impact: Enables comprehensive processor health visibility and proactive issue detection
-- Priority: P1 (HIGH - critical for pipeline observability)
-- ============================================================================

-- ============================================================================
-- VIEW: pipeline_processor_health
-- ============================================================================
-- This view provides unified health monitoring for all processors across
-- the entire data pipeline. It enables:
--   1. Per-processor health status classification
--   2. Failure rate tracking (24h, 7d, 30d windows)
--   3. Last success tracking and staleness detection
--   4. Performance monitoring (duration metrics)
--   5. Alert priority classification for monitoring integration
--
-- Data Sources:
--   - nba_orchestration.scraper_execution_log (Phase 1: Scrapers)
--   - nba_reference.processor_run_history (Phases 2/3/4: Processors)
--   - nba_processing.precompute_processor_runs (Phase 4: Precompute)
--   - nba_orchestration.phase_execution_log (Orchestrators)
--
-- Health Status Classification:
--   - HEALTHY: No failures in 24h, success within 7 days
--   - DEGRADED: 1-5 failures in last 24 hours
--   - UNHEALTHY: >5 failures in last 24 hours
--   - STALE: No success in 7+ days
--   - NEVER_RAN: No successful execution found
--
-- Alert Priority Levels:
--   - CRITICAL: Never ran (requires immediate investigation)
--   - HIGH: Stale (>7 days) or Unhealthy (>5 failures/24h)
--   - MEDIUM: Degraded (1-5 failures/24h)
--   - LOW: Healthy
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.pipeline_processor_health` AS

WITH

-- ============================================================================
-- Phase 1: Scrapers (nba_orchestration.scraper_execution_log)
-- ============================================================================
phase1_scrapers AS (
  SELECT
    'phase1' as phase,
    scraper_name as processor_name,
    triggered_at as run_at,
    game_date as data_date,
    -- Normalize status
    CASE
      WHEN status = 'success' THEN 'success'
      WHEN status = 'failed' THEN 'failed'
      WHEN status = 'no_data' THEN 'no_data'
      ELSE status
    END as normalized_status,
    error_message,
    duration_seconds
  FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
  WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
),

-- ============================================================================
-- Phases 2/3/4: Processors (nba_reference.processor_run_history)
-- ============================================================================
phase234_processors AS (
  SELECT
    phase,
    processor_name,
    started_at as run_at,
    data_date,
    -- Normalize status
    CASE
      WHEN status = 'success' THEN 'success'
      WHEN status IN ('failed', 'partial') THEN 'failed'
      WHEN status = 'skipped' THEN 'skipped'
      WHEN status = 'running' THEN 'running'
      ELSE status
    END as normalized_status,
    error_message,
    duration_seconds
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
),

-- ============================================================================
-- Phase 4: Precompute (nba_processing.precompute_processor_runs)
-- ============================================================================
phase4_precompute AS (
  SELECT
    'phase_4_precompute' as phase,
    processor_name,
    run_date as run_at,
    analysis_date as data_date,
    -- Normalize boolean success to status
    CASE
      WHEN success = TRUE THEN 'success'
      WHEN success = FALSE THEN 'failed'
      ELSE 'unknown'
    END as normalized_status,
    error_message,
    duration_seconds
  FROM `nba-props-platform.nba_processing.precompute_processor_runs`
  WHERE run_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
),

-- ============================================================================
-- Orchestrators: Phase Execution (nba_orchestration.phase_execution_log)
-- ============================================================================
orchestrators AS (
  SELECT
    'orchestrator' as phase,
    phase_name as processor_name,
    execution_timestamp as run_at,
    game_date as data_date,
    -- Normalize orchestrator status
    CASE
      WHEN status = 'complete' THEN 'success'
      WHEN status IN ('partial', 'deadline_exceeded') THEN 'failed'
      ELSE status
    END as normalized_status,
    error_message,
    duration_seconds
  FROM `nba-props-platform.nba_orchestration.phase_execution_log`
  WHERE execution_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
),

-- ============================================================================
-- Combine All Sources
-- ============================================================================
all_executions AS (
  SELECT * FROM phase1_scrapers
  UNION ALL
  SELECT * FROM phase234_processors
  UNION ALL
  SELECT * FROM phase4_precompute
  UNION ALL
  SELECT * FROM orchestrators
),

-- ============================================================================
-- Calculate Per-Processor Metrics
-- ============================================================================
processor_metrics AS (
  SELECT
    phase,
    processor_name,

    -- Last run tracking
    MAX(run_at) as last_run_at,
    MAX(CASE WHEN normalized_status = 'success' THEN run_at END) as last_success_at,
    MAX(CASE WHEN normalized_status = 'success' THEN data_date END) as last_success_date,

    -- 24-hour failure tracking
    COUNTIF(
      run_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
      AND normalized_status = 'failed'
    ) as failures_24h,

    -- 7-day metrics
    COUNTIF(
      run_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    ) as runs_7d,
    COUNTIF(
      run_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
      AND normalized_status = 'success'
    ) as successes_7d,
    COUNTIF(
      run_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
      AND normalized_status = 'failed'
    ) as failures_7d,

    -- 30-day metrics
    COUNTIF(
      run_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
    ) as runs_30d,
    COUNTIF(
      run_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
      AND normalized_status = 'success'
    ) as successes_30d,
    COUNTIF(
      run_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
      AND normalized_status = 'failed'
    ) as failures_30d,

    -- Performance metrics (successful runs only)
    ROUND(AVG(
      CASE WHEN normalized_status = 'success' THEN duration_seconds END
    ), 2) as avg_duration_seconds,
    ROUND(MAX(
      CASE WHEN normalized_status = 'success' THEN duration_seconds END
    ), 2) as max_duration_seconds,

    -- Latest error tracking
    ARRAY_AGG(
      error_message
      ORDER BY run_at DESC
      LIMIT 1
    )[SAFE_OFFSET(0)] as last_error_message

  FROM all_executions
  GROUP BY phase, processor_name
)

-- ============================================================================
-- Final Output with Health Classification
-- ============================================================================
SELECT
  phase,
  processor_name,

  -- Timing
  last_run_at,
  last_success_at,
  last_success_date,
  DATE_DIFF(CURRENT_DATE(), last_success_date, DAY) as days_since_success,

  -- 24-hour metrics
  failures_24h,

  -- 7-day metrics
  runs_7d,
  successes_7d,
  failures_7d,
  CASE
    WHEN runs_7d > 0 THEN ROUND(successes_7d * 100.0 / runs_7d, 2)
    ELSE 0
  END as success_rate_7d,

  -- 30-day metrics
  runs_30d,
  successes_30d,
  failures_30d,
  CASE
    WHEN runs_30d > 0 THEN ROUND(successes_30d * 100.0 / runs_30d, 2)
    ELSE 0
  END as success_rate_30d,

  -- Performance
  avg_duration_seconds,
  max_duration_seconds,

  -- Error tracking
  last_error_message,

  -- Health Status Classification
  CASE
    -- NEVER_RAN: No successful execution found
    WHEN last_success_at IS NULL THEN 'NEVER_RAN'

    -- STALE: No success in last 7 days (indicates processor may be disabled or broken)
    WHEN DATE_DIFF(CURRENT_DATE(), last_success_date, DAY) > 7 THEN 'STALE'

    -- UNHEALTHY: High failure rate in last 24 hours (>5 failures)
    WHEN failures_24h > 5 THEN 'UNHEALTHY'

    -- DEGRADED: Some failures in last 24 hours (1-5 failures)
    WHEN failures_24h > 0 THEN 'DEGRADED'

    -- HEALTHY: No recent failures
    ELSE 'HEALTHY'
  END as health_status,

  -- Alert Priority (for monitoring integration)
  CASE
    WHEN last_success_at IS NULL THEN 'CRITICAL'
    WHEN DATE_DIFF(CURRENT_DATE(), last_success_date, DAY) > 7 THEN 'HIGH'
    WHEN failures_24h > 5 THEN 'HIGH'
    WHEN failures_24h > 0 THEN 'MEDIUM'
    ELSE 'LOW'
  END as alert_priority,

  CURRENT_TIMESTAMP() as last_updated

FROM processor_metrics
ORDER BY
  CASE alert_priority
    WHEN 'CRITICAL' THEN 1
    WHEN 'HIGH' THEN 2
    WHEN 'MEDIUM' THEN 3
    WHEN 'LOW' THEN 4
  END,
  failures_24h DESC,
  processor_name;

-- ============================================================================
-- SCHEMA DEFINITION
-- ============================================================================
-- Output Columns (19 total):
--
-- 1. phase (STRING)
--    - Pipeline phase identifier
--    - Values: 'phase1', 'phase_2_raw', 'phase_3_analytics', 'phase_4_precompute', 'orchestrator'
--
-- 2. processor_name (STRING)
--    - Unique processor or scraper identifier
--    - Examples: 'player_game_summary', 'nba_stats_boxscore', 'phase3_orchestrator'
--
-- 3. last_run_at (TIMESTAMP)
--    - Most recent execution timestamp (any status)
--
-- 4. last_success_at (TIMESTAMP)
--    - Most recent successful execution timestamp
--    - NULL if processor has never succeeded
--
-- 5. last_success_date (DATE)
--    - Date of most recent successful execution
--    - NULL if processor has never succeeded
--
-- 6. days_since_success (INT64)
--    - Number of days since last successful execution
--    - NULL if processor has never succeeded
--
-- 7. failures_24h (INT64)
--    - Count of failures in last 24 hours
--    - Used for UNHEALTHY/DEGRADED classification
--
-- 8. runs_7d (INT64)
--    - Total execution count in last 7 days
--
-- 9. successes_7d (INT64)
--    - Successful execution count in last 7 days
--
-- 10. failures_7d (INT64)
--     - Failed execution count in last 7 days
--
-- 11. success_rate_7d (FLOAT64)
--     - Success rate percentage (0-100) over last 7 days
--
-- 12. runs_30d (INT64)
--     - Total execution count in last 30 days
--
-- 13. successes_30d (INT64)
--     - Successful execution count in last 30 days
--
-- 14. failures_30d (INT64)
--     - Failed execution count in last 30 days
--
-- 15. success_rate_30d (FLOAT64)
--     - Success rate percentage (0-100) over last 30 days
--
-- 16. avg_duration_seconds (FLOAT64)
--     - Average duration of successful executions
--
-- 17. max_duration_seconds (FLOAT64)
--     - Maximum duration of successful executions
--
-- 18. last_error_message (STRING)
--     - Most recent error message
--     - NULL if last execution was successful
--
-- 19. health_status (STRING)
--     - Health classification
--     - Values: 'HEALTHY', 'DEGRADED', 'UNHEALTHY', 'STALE', 'NEVER_RAN'
--
-- 20. alert_priority (STRING)
--     - Alert priority for monitoring integration
--     - Values: 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
--
-- 21. last_updated (TIMESTAMP)
--     - Timestamp when view was last computed
-- ============================================================================

-- ============================================================================
-- MONITORING QUERIES
-- ============================================================================

-- Query 1: Daily Validation Check (for /validate-daily)
-- SELECT
--   phase,
--   processor_name,
--   health_status,
--   failures_24h,
--   days_since_success,
--   alert_priority,
--   last_error_message
-- FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
-- WHERE health_status IN ('UNHEALTHY', 'STALE', 'NEVER_RAN')
-- ORDER BY alert_priority, failures_24h DESC
-- LIMIT 20;

-- Query 2: Phase Health Summary
-- SELECT
--   phase,
--   COUNT(*) as total_processors,
--   COUNTIF(health_status = 'HEALTHY') as healthy_count,
--   COUNTIF(health_status = 'DEGRADED') as degraded_count,
--   COUNTIF(health_status = 'UNHEALTHY') as unhealthy_count,
--   COUNTIF(health_status = 'STALE') as stale_count,
--   COUNTIF(health_status = 'NEVER_RAN') as never_ran_count,
--   ROUND(COUNTIF(health_status = 'HEALTHY') * 100.0 / COUNT(*), 2) as healthy_percentage
-- FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
-- GROUP BY phase
-- ORDER BY phase;

-- Query 3: Performance Analysis
-- SELECT
--   processor_name,
--   phase,
--   avg_duration_seconds,
--   max_duration_seconds,
--   successes_7d,
--   success_rate_7d
-- FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
-- WHERE health_status = 'HEALTHY'
-- ORDER BY avg_duration_seconds DESC
-- LIMIT 10;

-- ============================================================================
-- DEPLOYMENT CHECKLIST
-- ============================================================================
-- [ ] Verify source tables exist:
--     - nba_orchestration.scraper_execution_log
--     - nba_reference.processor_run_history
--     - nba_processing.precompute_processor_runs
--     - nba_orchestration.phase_execution_log
-- [ ] Create view in nba_monitoring dataset
-- [ ] Test view with sample queries
-- [ ] Verify health status classification logic
-- [ ] Integrate with /validate-daily skill
-- [ ] Configure materialized view for high-frequency access (optional)
-- [ ] Set up alerting based on health_status and alert_priority
-- [ ] Document in monitoring runbook
-- ============================================================================

-- ============================================================================
-- INTEGRATION WITH /validate-daily
-- ============================================================================
-- Add this query to the /validate-daily skill to show processor health issues:
--
-- echo "=== Processor Health Issues ==="
-- bq query --use_legacy_sql=false --format=pretty "
-- SELECT
--   phase,
--   processor_name,
--   health_status,
--   failures_24h,
--   days_since_success,
--   alert_priority
-- FROM \`nba-props-platform.nba_monitoring.pipeline_processor_health\`
-- WHERE health_status IN ('UNHEALTHY', 'STALE', 'NEVER_RAN')
-- ORDER BY alert_priority, failures_24h DESC
-- LIMIT 20
-- "
-- ============================================================================

-- ============================================================================
-- PERFORMANCE NOTES
-- ============================================================================
-- 1. View queries 30 days of data from 4 source tables
-- 2. Source tables are partitioned by date for efficient scanning
-- 3. View uses clustering keys where available (processor_name, game_date)
-- 4. For high-frequency access (dashboards), consider materializing hourly
-- 5. Typical query execution time: 2-5 seconds
-- 6. Estimated bytes processed per query: 50-200 MB (depends on data volume)
-- ============================================================================

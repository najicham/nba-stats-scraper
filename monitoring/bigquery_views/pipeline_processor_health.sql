-- ============================================================================
-- View: pipeline_processor_health
-- Purpose: Unified processor health monitoring across all pipeline phases
-- ============================================================================
-- Combines execution data from all 4 tracking tables to provide comprehensive
-- per-processor health status with:
--   - Status normalization (consistent status values across sources)
--   - Health classification (HEALTHY, DEGRADED, UNHEALTHY, STALE, NEVER_RAN)
--   - Last success tracking
--   - Failure rate monitoring (24h rolling window)
--
-- Coverage:
--   - Phase 1: Scrapers (scraper_execution_log)
--   - Phase 2: Raw Processing (processor_run_history)
--   - Phase 3: Analytics (processor_run_history)
--   - Phase 4: Precompute (processor_run_history + precompute_processor_runs)
--   - Phase 5: Predictions (covered by prediction_coverage_metrics)
--   - Orchestrators: Phase execution orchestrators (phase_execution_log)
--
-- Usage:
--   -- Current health overview
--   SELECT * FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
--   WHERE health_status IN ('UNHEALTHY', 'STALE', 'NEVER_RAN')
--   ORDER BY health_status, failures_24h DESC;
--
--   -- Processor-specific monitoring
--   SELECT * FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
--   WHERE processor_name = 'player_game_summary'
--   ORDER BY last_run_at DESC;
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
-- EXAMPLE QUERIES
-- ============================================================================

-- 1. Current health snapshot - processors requiring attention
-- SELECT
--   phase,
--   processor_name,
--   health_status,
--   failures_24h,
--   days_since_success,
--   last_error_message
-- FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
-- WHERE health_status IN ('UNHEALTHY', 'STALE', 'NEVER_RAN')
-- ORDER BY alert_priority, failures_24h DESC
-- LIMIT 20;

-- 2. Phase-level health overview
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

-- 3. Processor performance analysis (top 10 slowest)
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

-- 4. Recent degradation detection (healthy but showing failures)
-- SELECT
--   processor_name,
--   phase,
--   health_status,
--   failures_24h,
--   success_rate_7d,
--   last_error_message
-- FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
-- WHERE health_status IN ('DEGRADED', 'UNHEALTHY')
--   AND success_rate_7d >= 90  -- Was healthy historically
-- ORDER BY failures_24h DESC;

-- 5. Staleness audit (processors that haven't run recently)
-- SELECT
--   processor_name,
--   phase,
--   days_since_success,
--   last_success_at,
--   last_run_at,
--   health_status
-- FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
-- WHERE health_status IN ('STALE', 'NEVER_RAN')
-- ORDER BY days_since_success DESC;

-- 6. Daily validation query (for /validate-daily skill)
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

-- ============================================================================
-- MONITORING INTEGRATION
-- ============================================================================

-- Alert Trigger 1: CRITICAL - Processors that have never successfully run
-- SELECT processor_name, phase, last_run_at
-- FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
-- WHERE health_status = 'NEVER_RAN';

-- Alert Trigger 2: HIGH - Stale processors (no success in 7+ days)
-- SELECT processor_name, phase, days_since_success, last_error_message
-- FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
-- WHERE health_status = 'STALE';

-- Alert Trigger 3: HIGH - Unhealthy processors (>5 failures in 24h)
-- SELECT processor_name, phase, failures_24h, success_rate_7d, last_error_message
-- FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
-- WHERE health_status = 'UNHEALTHY';

-- Alert Trigger 4: MEDIUM - Degraded processors (1-5 failures in 24h)
-- SELECT processor_name, phase, failures_24h, last_error_message
-- FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
-- WHERE health_status = 'DEGRADED'
--   AND alert_priority = 'MEDIUM';

-- ============================================================================
-- NOTES
-- ============================================================================
-- 1. Status Normalization: Different source tables use different status values.
--    This view normalizes them to: success, failed, no_data, skipped, running
--
-- 2. Health Thresholds:
--    - HEALTHY: No failures in 24h, success within 7 days
--    - DEGRADED: 1-5 failures in 24h
--    - UNHEALTHY: >5 failures in 24h
--    - STALE: No success in 7+ days
--    - NEVER_RAN: No successful execution found
--
-- 3. Failure Category Filtering: To reduce noise, consider filtering out
--    'no_data_available' errors when building alerts:
--    WHERE last_error_message NOT LIKE '%no_data_available%'
--
-- 4. Data Retention: View includes last 30 days of execution data for metrics.
--    Source tables have their own retention policies (see table schemas).
--
-- 5. Performance: View is optimized with partitioned source tables and
--    appropriate date filters. Consider materializing for high-frequency access.
-- ============================================================================

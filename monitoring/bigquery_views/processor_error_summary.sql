-- ============================================================================
-- View: processor_error_summary
-- Purpose: Error counts and patterns by processor and error type
-- ============================================================================
-- Provides detailed error analysis for troubleshooting, showing:
-- - Error counts by processor
-- - Transient vs permanent error classification
-- - Retry success rates
-- - Top error messages
--
-- Usage:
--   -- Top failing processors (last 24h)
--   SELECT * FROM `nba-props-platform.nba_monitoring.processor_error_summary`
--   WHERE time_window = 'last_24h'
--   ORDER BY error_count DESC
--   LIMIT 10;
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.processor_error_summary` AS

WITH time_ranges AS (
  SELECT
    'last_24h' as time_window,
    TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR) as start_time,
    CURRENT_TIMESTAMP() as end_time
  UNION ALL
  SELECT
    'last_7d' as time_window,
    TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY) as start_time,
    CURRENT_TIMESTAMP() as end_time
),

-- Phase 3 Analytics errors
phase3_errors AS (
  SELECT
    tr.time_window,
    prh.processor_name,
    'phase_3_analytics' as phase,
    prh.status,
    prh.failure_category,

    -- Classify error type
    CASE
      WHEN prh.failure_category IN ('no_data_available', 'upstream_failure') THEN 'transient'
      WHEN prh.failure_category IN ('configuration_error', 'processing_error') THEN 'permanent'
      WHEN prh.failure_category = 'timeout' THEN 'transient'
      ELSE 'unknown'
    END as error_type,

    -- Check if retried
    prh.retry_attempt > 1 as was_retried,
    prh.retry_attempt,

    -- Extract error message (first error from JSON)
    CASE
      WHEN prh.errors IS NOT NULL THEN JSON_VALUE(prh.errors, '$[0].message')
      ELSE NULL
    END as error_message,

    prh.data_date
  FROM `nba-props-platform.nba_reference.processor_run_history` prh
  CROSS JOIN time_ranges tr
  WHERE prh.phase = 'phase_3_analytics'
    AND prh.status IN ('failed', 'partial')
    AND prh.started_at >= tr.start_time
    AND prh.started_at < tr.end_time
),

-- Phase 4 Precompute errors
phase4_errors AS (
  SELECT
    tr.time_window,
    ppr.processor_name,
    'phase_4_precompute' as phase,
    CASE WHEN ppr.success THEN 'success' ELSE 'failed' END as status,

    -- Extract failure category from errors JSON
    CASE
      WHEN JSON_VALUE(ppr.errors_json, '$[0].category') IS NOT NULL
      THEN JSON_VALUE(ppr.errors_json, '$[0].category')
      ELSE 'unknown'
    END as failure_category,

    -- Classify error type
    CASE
      WHEN ppr.skip_reason IN ('no_games', 'offseason') THEN 'transient'
      WHEN ppr.dependency_check_passed = FALSE THEN 'transient'
      ELSE 'permanent'
    END as error_type,

    FALSE as was_retried,  -- Not tracked in precompute_processor_runs
    0 as retry_attempt,

    -- Extract error message
    CASE
      WHEN ppr.errors_json IS NOT NULL THEN JSON_VALUE(ppr.errors_json, '$[0].message')
      ELSE NULL
    END as error_message,

    ppr.analysis_date as data_date
  FROM `nba-props-platform.nba_processing.precompute_processor_runs` ppr
  CROSS JOIN time_ranges tr
  WHERE ppr.success = FALSE
    AND ppr.run_date >= tr.start_time
    AND ppr.run_date < tr.end_time
),

-- Combine all errors
all_errors AS (
  SELECT * FROM phase3_errors
  UNION ALL
  SELECT * FROM phase4_errors
),

-- Aggregate by processor and error type
error_summary AS (
  SELECT
    time_window,
    processor_name,
    phase,
    error_type,
    failure_category,

    COUNT(*) as error_count,
    COUNT(DISTINCT data_date) as affected_dates,

    -- Retry analysis
    COUNTIF(was_retried) as retried_count,
    AVG(retry_attempt) as avg_retry_attempts,

    -- Most common error message
    APPROX_TOP_COUNT(error_message, 1)[OFFSET(0)].value as top_error_message,
    APPROX_TOP_COUNT(error_message, 1)[OFFSET(0)].count as top_error_count,

    -- Latest occurrence
    MAX(data_date) as latest_error_date

  FROM all_errors
  GROUP BY time_window, processor_name, phase, error_type, failure_category
),

-- Calculate retry success rate (subsequent runs that succeeded)
retry_success AS (
  SELECT
    tr.time_window,
    prh.processor_name,
    COUNT(*) as total_retries,
    COUNTIF(prh.status = 'success') as successful_retries
  FROM `nba-props-platform.nba_reference.processor_run_history` prh
  CROSS JOIN time_ranges tr
  WHERE prh.retry_attempt > 1
    AND prh.started_at >= tr.start_time
    AND prh.started_at < tr.end_time
  GROUP BY tr.time_window, prh.processor_name
)

SELECT
  es.time_window,
  es.processor_name,
  es.phase,
  es.error_type,
  es.failure_category,
  es.error_count,
  es.affected_dates,
  es.retried_count,
  es.avg_retry_attempts,
  es.top_error_message,
  es.top_error_count,
  es.latest_error_date,

  -- Retry success rate
  COALESCE(rs.total_retries, 0) as total_retries,
  COALESCE(rs.successful_retries, 0) as successful_retries,
  CASE
    WHEN COALESCE(rs.total_retries, 0) > 0
    THEN ROUND(COALESCE(rs.successful_retries, 0) * 100.0 / rs.total_retries, 2)
    ELSE 0
  END as retry_success_rate,

  -- Alert priority (higher = more urgent)
  CASE
    WHEN es.error_type = 'permanent' AND es.error_count > 10 THEN 'CRITICAL'
    WHEN es.error_type = 'permanent' AND es.error_count > 5 THEN 'HIGH'
    WHEN es.error_type = 'transient' AND es.error_count > 20 THEN 'MEDIUM'
    ELSE 'LOW'
  END as alert_priority,

  CURRENT_TIMESTAMP() as last_updated

FROM error_summary es
LEFT JOIN retry_success rs
  ON es.time_window = rs.time_window
  AND es.processor_name = rs.processor_name
ORDER BY es.time_window, es.error_count DESC;

-- ============================================================================
-- EXAMPLE QUERIES
-- ============================================================================

-- 1. Top 10 failing processors (last 24h)
-- SELECT
--   processor_name,
--   phase,
--   error_count,
--   error_type,
--   failure_category,
--   retry_success_rate,
--   top_error_message
-- FROM `nba-props-platform.nba_monitoring.processor_error_summary`
-- WHERE time_window = 'last_24h'
-- ORDER BY error_count DESC
-- LIMIT 10;

-- 2. Critical errors requiring immediate attention
-- SELECT
--   processor_name,
--   phase,
--   error_count,
--   affected_dates,
--   alert_priority,
--   top_error_message,
--   latest_error_date
-- FROM `nba-props-platform.nba_monitoring.processor_error_summary`
-- WHERE time_window = 'last_24h'
--   AND alert_priority IN ('CRITICAL', 'HIGH')
-- ORDER BY alert_priority, error_count DESC;

-- 3. Processors with low retry success rates
-- SELECT
--   processor_name,
--   error_count,
--   total_retries,
--   successful_retries,
--   retry_success_rate,
--   error_type
-- FROM `nba-props-platform.nba_monitoring.processor_error_summary`
-- WHERE time_window = 'last_7d'
--   AND total_retries > 5
--   AND retry_success_rate < 50
-- ORDER BY retry_success_rate;

-- 4. Error trend analysis (compare 24h vs 7d)
-- SELECT
--   processor_name,
--   phase,
--   MAX(CASE WHEN time_window = 'last_24h' THEN error_count END) as errors_24h,
--   MAX(CASE WHEN time_window = 'last_7d' THEN error_count END) as errors_7d,
--   MAX(CASE WHEN time_window = 'last_24h' THEN error_type END) as error_type
-- FROM `nba-props-platform.nba_monitoring.processor_error_summary`
-- GROUP BY processor_name, phase
-- HAVING MAX(CASE WHEN time_window = 'last_24h' THEN error_count END) > 0
-- ORDER BY errors_24h DESC;

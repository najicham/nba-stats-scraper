-- ============================================================================
-- View: pipeline_health_summary
-- Purpose: Aggregated phase completion metrics for pipeline health monitoring
-- ============================================================================
-- Provides real-time visibility into Phase 3/4/5 completion rates, showing
-- percentage of games successfully processed through each phase.
--
-- Usage:
--   -- Last 24 hours overview
--   SELECT * FROM `nba-props-platform.nba_monitoring.pipeline_health_summary`
--   WHERE time_window = 'last_24h'
--   ORDER BY phase_name;
--
--   -- Last 7 days trend
--   SELECT * FROM `nba-props-platform.nba_monitoring.pipeline_health_summary`
--   WHERE time_window = 'last_7d'
--   ORDER BY phase_name;
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.pipeline_health_summary` AS

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

-- Phase 3 (Analytics) completion from processor_run_history
phase3_stats AS (
  SELECT
    tr.time_window,
    'phase_3_analytics' as phase_name,
    COUNT(DISTINCT CONCAT(data_date, processor_name)) as total_processor_runs,
    COUNTIF(status = 'success') as successful_runs,
    COUNTIF(status IN ('failed', 'partial')) as failed_runs,
    COUNTIF(skip_reason IS NOT NULL) as skipped_runs,
    COUNT(DISTINCT data_date) as total_dates,
    COUNT(DISTINCT CASE WHEN status = 'success' THEN data_date END) as dates_with_success
  FROM `nba-props-platform.nba_reference.processor_run_history` prh
  CROSS JOIN time_ranges tr
  WHERE prh.phase = 'phase_3_analytics'
    AND prh.started_at >= tr.start_time
    AND prh.started_at < tr.end_time
  GROUP BY tr.time_window
),

-- Phase 4 (Precompute) completion
phase4_stats AS (
  SELECT
    tr.time_window,
    'phase_4_precompute' as phase_name,
    COUNT(DISTINCT CONCAT(analysis_date, processor_name)) as total_processor_runs,
    COUNTIF(success = TRUE) as successful_runs,
    COUNTIF(success = FALSE) as failed_runs,
    COUNTIF(skip_reason IS NOT NULL) as skipped_runs,
    COUNT(DISTINCT analysis_date) as total_dates,
    COUNT(DISTINCT CASE WHEN success = TRUE THEN analysis_date END) as dates_with_success
  FROM `nba-props-platform.nba_processing.precompute_processor_runs` ppr
  CROSS JOIN time_ranges tr
  WHERE ppr.run_date >= tr.start_time
    AND ppr.run_date < tr.end_time
  GROUP BY tr.time_window
),

-- Phase 5 (Predictions) completion
phase5_stats AS (
  SELECT
    tr.time_window,
    'phase_5_predictions' as phase_name,
    COUNT(DISTINCT CONCAT(game_date, system_id)) as total_processor_runs,
    COUNT(DISTINCT CONCAT(game_date, system_id)) as successful_runs,  -- All records indicate success
    0 as failed_runs,
    0 as skipped_runs,
    COUNT(DISTINCT game_date) as total_dates,
    COUNT(DISTINCT game_date) as dates_with_success
  FROM `nba-props-platform.nba_predictions.player_prop_predictions` ppp
  CROSS JOIN time_ranges tr
  WHERE ppp.created_at >= tr.start_time
    AND ppp.created_at < tr.end_time
    AND ppp.is_active = TRUE
  GROUP BY tr.time_window
),

-- Combine all phases
all_phases AS (
  SELECT * FROM phase3_stats
  UNION ALL
  SELECT * FROM phase4_stats
  UNION ALL
  SELECT * FROM phase5_stats
)

SELECT
  time_window,
  phase_name,
  total_processor_runs,
  successful_runs,
  failed_runs,
  skipped_runs,
  total_dates,
  dates_with_success,

  -- Calculate completion percentage
  CASE
    WHEN total_processor_runs > 0
    THEN ROUND(successful_runs * 100.0 / total_processor_runs, 2)
    ELSE 0
  END as completion_percentage,

  -- Calculate failure rate
  CASE
    WHEN total_processor_runs > 0
    THEN ROUND(failed_runs * 100.0 / total_processor_runs, 2)
    ELSE 0
  END as failure_rate,

  -- Date coverage (% of dates with at least one success)
  CASE
    WHEN total_dates > 0
    THEN ROUND(dates_with_success * 100.0 / total_dates, 2)
    ELSE 0
  END as date_coverage_percentage,

  CURRENT_TIMESTAMP() as last_updated

FROM all_phases
ORDER BY time_window, phase_name;

-- ============================================================================
-- EXAMPLE QUERIES
-- ============================================================================

-- 1. Current pipeline health snapshot (last 24 hours)
-- SELECT
--   phase_name,
--   completion_percentage,
--   failure_rate,
--   successful_runs,
--   failed_runs,
--   date_coverage_percentage
-- FROM `nba-props-platform.nba_monitoring.pipeline_health_summary`
-- WHERE time_window = 'last_24h'
-- ORDER BY phase_name;

-- 2. Compare 24h vs 7d performance
-- SELECT
--   phase_name,
--   MAX(CASE WHEN time_window = 'last_24h' THEN completion_percentage END) as completion_24h,
--   MAX(CASE WHEN time_window = 'last_7d' THEN completion_percentage END) as completion_7d,
--   MAX(CASE WHEN time_window = 'last_24h' THEN failure_rate END) as failure_rate_24h,
--   MAX(CASE WHEN time_window = 'last_7d' THEN failure_rate END) as failure_rate_7d
-- FROM `nba-props-platform.nba_monitoring.pipeline_health_summary`
-- GROUP BY phase_name
-- ORDER BY phase_name;

-- 3. Alert if completion rate drops below 80%
-- SELECT
--   phase_name,
--   completion_percentage,
--   failure_rate,
--   'ALERT: Low completion rate' as alert_message
-- FROM `nba-props-platform.nba_monitoring.pipeline_health_summary`
-- WHERE time_window = 'last_24h'
--   AND completion_percentage < 80
-- ORDER BY completion_percentage;

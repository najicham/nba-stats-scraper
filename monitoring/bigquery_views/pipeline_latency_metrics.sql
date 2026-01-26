-- ============================================================================
-- View: pipeline_latency_metrics
-- Purpose: Track end-to-end pipeline latency across phase boundaries
-- ============================================================================
-- Measures time from game start to predictions ready, broken down by phase:
-- - Phase 2 (Raw data ingestion): Game start -> raw data complete
-- - Phase 3 (Analytics): Raw data -> analytics complete
-- - Phase 4 (Precompute): Analytics -> precompute complete
-- - Phase 5 (Predictions): Precompute -> predictions ready
--
-- Usage:
--   -- Latest latency metrics
--   SELECT * FROM `nba-props-platform.nba_monitoring.pipeline_latency_metrics`
--   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--   ORDER BY game_date DESC;
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.pipeline_latency_metrics` AS

WITH scheduled_games AS (
  -- Get game start times from schedule
  SELECT
    game_date,
    game_id,
    game_start_time_utc,
    home_team_abbr,
    away_team_abbr
  FROM `nba-props-platform.nba_reference.daily_expected_schedule`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),

-- Phase 2: Raw data arrival times (from scraper execution log)
phase2_completion AS (
  SELECT
    game_date,
    MIN(execution_timestamp) as first_scraper_complete,
    MAX(execution_timestamp) as last_scraper_complete,
    COUNT(DISTINCT scraper_name) as scrapers_completed,
    AVG(duration_seconds) as avg_scraper_duration
  FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND status = 'success'
    AND phase = 'phase_2_raw'
  GROUP BY game_date
),

-- Phase 3: Analytics completion (from processor_run_history)
phase3_completion AS (
  SELECT
    data_date as game_date,
    MIN(started_at) as first_processor_start,
    MAX(processed_at) as last_processor_complete,
    COUNT(DISTINCT processor_name) as processors_completed,
    AVG(duration_seconds) as avg_processor_duration,
    COUNTIF(status = 'success') as successful_processors
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND phase = 'phase_3_analytics'
  GROUP BY data_date
),

-- Phase 4: Precompute completion
phase4_completion AS (
  SELECT
    analysis_date as game_date,
    MIN(run_date) as first_processor_start,
    MAX(TIMESTAMP_ADD(run_date, INTERVAL CAST(duration_seconds AS INT64) SECOND)) as last_processor_complete,
    COUNT(DISTINCT processor_name) as processors_completed,
    AVG(duration_seconds) as avg_processor_duration,
    COUNTIF(success = TRUE) as successful_processors
  FROM `nba-props-platform.nba_processing.precompute_processor_runs`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY analysis_date
),

-- Phase 5: Prediction generation
phase5_completion AS (
  SELECT
    game_date,
    MIN(created_at) as first_prediction_created,
    MAX(created_at) as last_prediction_created,
    COUNT(DISTINCT system_id) as systems_completed,
    COUNT(DISTINCT player_lookup) as players_with_predictions
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND is_active = TRUE
  GROUP BY game_date
),

-- Phase execution log (orchestrator timing)
phase_transitions AS (
  SELECT
    game_date,
    phase_name,
    MIN(execution_timestamp) as transition_time,
    AVG(duration_seconds) as avg_transition_duration,
    COUNTIF(status = 'complete') as complete_transitions,
    COUNTIF(status = 'deadline_exceeded') as timeout_transitions
  FROM `nba-props-platform.nba_orchestration.phase_execution_log`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date, phase_name
),

-- Combine all metrics
combined_metrics AS (
  SELECT
    sg.game_date,
    sg.game_start_time_utc,

    -- Phase 2 (Raw Data)
    p2.first_scraper_complete as phase2_start,
    p2.last_scraper_complete as phase2_complete,
    p2.scrapers_completed,
    p2.avg_scraper_duration,

    -- Phase 3 (Analytics)
    p3.first_processor_start as phase3_start,
    p3.last_processor_complete as phase3_complete,
    p3.processors_completed as phase3_processors,
    p3.avg_processor_duration as phase3_avg_duration,
    p3.successful_processors as phase3_successful,

    -- Phase 4 (Precompute)
    p4.first_processor_start as phase4_start,
    p4.last_processor_complete as phase4_complete,
    p4.processors_completed as phase4_processors,
    p4.avg_processor_duration as phase4_avg_duration,
    p4.successful_processors as phase4_successful,

    -- Phase 5 (Predictions)
    p5.first_prediction_created as phase5_start,
    p5.last_prediction_created as phase5_complete,
    p5.systems_completed,
    p5.players_with_predictions

  FROM scheduled_games sg
  LEFT JOIN phase2_completion p2 ON sg.game_date = p2.game_date
  LEFT JOIN phase3_completion p3 ON sg.game_date = p3.game_date
  LEFT JOIN phase4_completion p4 ON sg.game_date = p4.game_date
  LEFT JOIN phase5_completion p5 ON sg.game_date = p5.game_date
)

SELECT
  game_date,
  game_start_time_utc,

  -- Phase completion times
  phase2_complete,
  phase3_complete,
  phase4_complete,
  phase5_complete,

  -- Phase-level latencies (in minutes)
  CASE
    WHEN game_start_time_utc IS NOT NULL AND phase2_complete IS NOT NULL
    THEN ROUND(TIMESTAMP_DIFF(phase2_complete, game_start_time_utc, SECOND) / 60.0, 2)
    ELSE NULL
  END as phase2_latency_minutes,

  CASE
    WHEN phase2_complete IS NOT NULL AND phase3_complete IS NOT NULL
    THEN ROUND(TIMESTAMP_DIFF(phase3_complete, phase2_complete, SECOND) / 60.0, 2)
    ELSE NULL
  END as phase3_latency_minutes,

  CASE
    WHEN phase3_complete IS NOT NULL AND phase4_complete IS NOT NULL
    THEN ROUND(TIMESTAMP_DIFF(phase4_complete, phase3_complete, SECOND) / 60.0, 2)
    ELSE NULL
  END as phase4_latency_minutes,

  CASE
    WHEN phase4_complete IS NOT NULL AND phase5_complete IS NOT NULL
    THEN ROUND(TIMESTAMP_DIFF(phase5_complete, phase4_complete, SECOND) / 60.0, 2)
    ELSE NULL
  END as phase5_latency_minutes,

  -- End-to-end latency
  CASE
    WHEN game_start_time_utc IS NOT NULL AND phase5_complete IS NOT NULL
    THEN ROUND(TIMESTAMP_DIFF(phase5_complete, game_start_time_utc, SECOND) / 60.0, 2)
    ELSE NULL
  END as total_latency_minutes,

  -- Phase completion counts
  scrapers_completed,
  phase3_processors,
  phase3_successful,
  phase4_processors,
  phase4_successful,
  systems_completed,
  players_with_predictions,

  -- Average processing durations (seconds)
  ROUND(avg_scraper_duration, 2) as avg_scraper_duration_seconds,
  ROUND(phase3_avg_duration, 2) as phase3_avg_duration_seconds,
  ROUND(phase4_avg_duration, 2) as phase4_avg_duration_seconds,

  -- Calculate 7-day rolling averages for latency
  ROUND(AVG(CASE
    WHEN phase2_complete IS NOT NULL AND phase3_complete IS NOT NULL
    THEN TIMESTAMP_DIFF(phase3_complete, phase2_complete, SECOND) / 60.0
  END) OVER (
    ORDER BY game_date
    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
  ), 2) as phase3_latency_7d_avg,

  ROUND(AVG(CASE
    WHEN phase3_complete IS NOT NULL AND phase4_complete IS NOT NULL
    THEN TIMESTAMP_DIFF(phase4_complete, phase3_complete, SECOND) / 60.0
  END) OVER (
    ORDER BY game_date
    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
  ), 2) as phase4_latency_7d_avg,

  ROUND(AVG(CASE
    WHEN phase4_complete IS NOT NULL AND phase5_complete IS NOT NULL
    THEN TIMESTAMP_DIFF(phase5_complete, phase4_complete, SECOND) / 60.0
  END) OVER (
    ORDER BY game_date
    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
  ), 2) as phase5_latency_7d_avg,

  -- Completeness flags
  phase2_complete IS NOT NULL as phase2_completed,
  phase3_complete IS NOT NULL as phase3_completed,
  phase4_complete IS NOT NULL as phase4_completed,
  phase5_complete IS NOT NULL as phase5_completed,

  -- Health status
  CASE
    WHEN phase5_complete IS NULL THEN 'INCOMPLETE'
    WHEN TIMESTAMP_DIFF(phase5_complete, game_start_time_utc, SECOND) / 60.0 <= 180 THEN 'HEALTHY'  -- 3 hours
    WHEN TIMESTAMP_DIFF(phase5_complete, game_start_time_utc, SECOND) / 60.0 <= 360 THEN 'DEGRADED'  -- 6 hours
    ELSE 'SLOW'
  END as pipeline_health,

  CURRENT_TIMESTAMP() as last_updated

FROM combined_metrics
ORDER BY game_date DESC;

-- ============================================================================
-- EXAMPLE QUERIES
-- ============================================================================

-- 1. Latest pipeline latency (today)
-- SELECT
--   game_date,
--   phase2_latency_minutes,
--   phase3_latency_minutes,
--   phase4_latency_minutes,
--   phase5_latency_minutes,
--   total_latency_minutes,
--   pipeline_health
-- FROM `nba-props-platform.nba_monitoring.pipeline_latency_metrics`
-- WHERE game_date = CURRENT_DATE();

-- 2. Average latency by phase (last 7 days)
-- SELECT
--   'Phase 2 (Raw)' as phase,
--   ROUND(AVG(phase2_latency_minutes), 2) as avg_latency_minutes,
--   ROUND(MAX(phase2_latency_minutes), 2) as max_latency_minutes
-- FROM `nba-props-platform.nba_monitoring.pipeline_latency_metrics`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- UNION ALL
-- SELECT
--   'Phase 3 (Analytics)' as phase,
--   ROUND(AVG(phase3_latency_minutes), 2),
--   ROUND(MAX(phase3_latency_minutes), 2)
-- FROM `nba-props-platform.nba_monitoring.pipeline_latency_metrics`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- UNION ALL
-- SELECT
--   'Phase 4 (Precompute)' as phase,
--   ROUND(AVG(phase4_latency_minutes), 2),
--   ROUND(MAX(phase4_latency_minutes), 2)
-- FROM `nba-props-platform.nba_monitoring.pipeline_latency_metrics`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- UNION ALL
-- SELECT
--   'Phase 5 (Predictions)' as phase,
--   ROUND(AVG(phase5_latency_minutes), 2),
--   ROUND(MAX(phase5_latency_minutes), 2)
-- FROM `nba-props-platform.nba_monitoring.pipeline_latency_metrics`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY);

-- 3. Slow pipeline executions (>6 hours)
-- SELECT
--   game_date,
--   total_latency_minutes,
--   phase2_latency_minutes,
--   phase3_latency_minutes,
--   phase4_latency_minutes,
--   phase5_latency_minutes,
--   pipeline_health
-- FROM `nba-props-platform.nba_monitoring.pipeline_latency_metrics`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--   AND total_latency_minutes > 360
-- ORDER BY total_latency_minutes DESC;

-- 4. Incomplete pipelines (stuck phases)
-- SELECT
--   game_date,
--   phase2_completed,
--   phase3_completed,
--   phase4_completed,
--   phase5_completed,
--   phase3_processors,
--   phase4_processors,
--   players_with_predictions
-- FROM `nba-props-platform.nba_monitoring.pipeline_latency_metrics`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
--   AND phase5_completed = FALSE
-- ORDER BY game_date DESC;

-- 5. Latency distribution (last 7 days)
-- SELECT
--   CASE
--     WHEN total_latency_minutes <= 60 THEN '0-1 hour'
--     WHEN total_latency_minutes <= 120 THEN '1-2 hours'
--     WHEN total_latency_minutes <= 180 THEN '2-3 hours'
--     WHEN total_latency_minutes <= 360 THEN '3-6 hours'
--     ELSE '>6 hours'
--   END as latency_bucket,
--   COUNT(*) as game_count
-- FROM `nba-props-platform.nba_monitoring.pipeline_latency_metrics`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--   AND total_latency_minutes IS NOT NULL
-- GROUP BY latency_bucket
-- ORDER BY MIN(total_latency_minutes);

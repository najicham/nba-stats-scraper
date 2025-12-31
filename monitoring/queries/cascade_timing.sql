-- Pipeline Cascade Timing Analysis
-- Shows when each phase ran and delays between phases
-- Use this to track pipeline performance improvements

WITH phase_times AS (
  SELECT
    DATE(started_at, 'America/New_York') as game_date,
    'Phase 3' as phase,
    MIN(started_at) as phase_start
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE processor_name IN (
    'UpcomingPlayerGameContextProcessor',
    'PlayerGameSummaryProcessor'
  )
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  GROUP BY DATE(started_at, 'America/New_York')

  UNION ALL

  SELECT
    DATE(started_at, 'America/New_York') as game_date,
    'Phase 4' as phase,
    MIN(started_at) as phase_start
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE processor_name LIKE '%FeatureStore%'
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  GROUP BY DATE(started_at, 'America/New_York')

  UNION ALL

  SELECT
    game_date,
    'Phase 5' as phase,
    MIN(created_at) as phase_start
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE game_date >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
  AND is_active = TRUE
  GROUP BY game_date
)
SELECT
  game_date,
  DATETIME(MAX(CASE WHEN phase = 'Phase 3' THEN phase_start END), 'America/New_York') as phase3_time,
  DATETIME(MAX(CASE WHEN phase = 'Phase 4' THEN phase_start END), 'America/New_York') as phase4_time,
  DATETIME(MAX(CASE WHEN phase = 'Phase 5' THEN phase_start END), 'America/New_York') as phase5_time,
  TIMESTAMP_DIFF(
    MAX(CASE WHEN phase = 'Phase 4' THEN phase_start END),
    MAX(CASE WHEN phase = 'Phase 3' THEN phase_start END),
    MINUTE
  ) as phase3_to_4_delay_min,
  TIMESTAMP_DIFF(
    MAX(CASE WHEN phase = 'Phase 5' THEN phase_start END),
    MAX(CASE WHEN phase = 'Phase 4' THEN phase_start END),
    MINUTE
  ) as phase4_to_5_delay_min,
  TIMESTAMP_DIFF(
    MAX(CASE WHEN phase = 'Phase 5' THEN phase_start END),
    MAX(CASE WHEN phase = 'Phase 3' THEN phase_start END),
    MINUTE
  ) as total_delay_min
FROM phase_times
GROUP BY game_date
ORDER BY game_date DESC

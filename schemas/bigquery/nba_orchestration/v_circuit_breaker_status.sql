-- ============================================================================
-- CIRCUIT BREAKER STATUS VIEW
-- ============================================================================
-- Purpose: Easy monitoring of circuit breaker states across all processors
-- Created: 2026-01-24 (Session 12)
--
-- Usage:
--   SELECT * FROM `nba_orchestration.v_circuit_breaker_status`;
--   SELECT * FROM `nba_orchestration.v_circuit_breaker_status` WHERE state = 'OPEN';

CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_circuit_breaker_status` AS
SELECT
  processor_name,
  state,
  failure_count,
  success_count,
  opened_at,
  last_failure,
  last_success,
  updated_at,
  last_error_type,
  last_error_message,
  threshold,
  timeout_seconds,

  -- Calculated fields
  CASE
    WHEN state = 'OPEN' THEN
      TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), opened_at, MINUTE)
    ELSE NULL
  END AS open_duration_minutes,

  CASE
    WHEN state = 'OPEN' AND timeout_seconds IS NOT NULL THEN
      GREATEST(0, timeout_seconds - TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), opened_at, SECOND))
    ELSE NULL
  END AS seconds_until_half_open,

  CASE
    WHEN state = 'OPEN' AND opened_at IS NOT NULL THEN
      TIMESTAMP_ADD(opened_at, INTERVAL COALESCE(timeout_seconds, 1800) SECOND)
    ELSE NULL
  END AS expected_half_open_at,

  -- Processor category
  CASE
    WHEN processor_name LIKE 'Mlb%' THEN 'MLB'
    WHEN processor_name LIKE '%Player%' THEN 'Player Analytics'
    WHEN processor_name LIKE '%Team%' THEN 'Team Analytics'
    WHEN processor_name LIKE '%Feature%' OR processor_name LIKE '%Cache%' THEN 'Precompute'
    WHEN processor_name LIKE '%xgboost%' OR processor_name LIKE '%catboost%' THEN 'ML Models'
    ELSE 'Other'
  END AS processor_category

FROM `nba-props-platform.nba_orchestration.circuit_breaker_state`
WHERE updated_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY
  CASE state WHEN 'OPEN' THEN 1 WHEN 'HALF_OPEN' THEN 2 ELSE 3 END,
  opened_at DESC NULLS LAST;

-- ============================================================================
-- CIRCUIT BREAKER SUMMARY VIEW
-- ============================================================================
-- Aggregate view for dashboard/monitoring

CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_circuit_breaker_summary` AS
SELECT
  CASE
    WHEN processor_name LIKE 'Mlb%' THEN 'MLB'
    WHEN processor_name LIKE '%Player%' THEN 'Player Analytics'
    WHEN processor_name LIKE '%Team%' THEN 'Team Analytics'
    WHEN processor_name LIKE '%Feature%' OR processor_name LIKE '%Cache%' THEN 'Precompute'
    WHEN processor_name LIKE '%xgboost%' OR processor_name LIKE '%catboost%' THEN 'ML Models'
    ELSE 'Other'
  END AS processor_category,
  state,
  COUNT(*) AS processor_count,
  SUM(failure_count) AS total_failures,
  MAX(updated_at) AS last_state_change,
  ARRAY_AGG(processor_name ORDER BY failure_count DESC LIMIT 5) AS top_failing_processors
FROM `nba-props-platform.nba_orchestration.circuit_breaker_state`
WHERE updated_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY processor_category, state
ORDER BY
  CASE state WHEN 'OPEN' THEN 1 WHEN 'HALF_OPEN' THEN 2 ELSE 3 END,
  processor_count DESC;

-- ============================================================================
-- COMPLETENESS CHECKING MONITORING DASHBOARD
-- ============================================================================
-- Purpose: BigQuery queries for monitoring completeness checking across all processors
-- Usage: Copy queries into BigQuery console or Grafana
-- Last Updated: 2025-11-22
-- ============================================================================

-- ============================================================================
-- QUERY 1: Overall Completeness Health by Processor
-- ============================================================================
-- Shows current completeness status across all 7 processors
-- Update frequency: Every hour or on-demand
-- ============================================================================

WITH all_processors AS (
  SELECT
    'team_defense_zone_analysis' as processor_name,
    'nba_precompute' as dataset,
    team_abbr as entity_id,
    analysis_date,
    completeness_percentage,
    is_production_ready,
    circuit_breaker_active,
    backfill_bootstrap_mode,
    processing_decision_reason
  FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

  UNION ALL

  SELECT
    'player_shot_zone_analysis' as processor_name,
    'nba_precompute' as dataset,
    player_lookup as entity_id,
    analysis_date,
    completeness_percentage,
    is_production_ready,
    circuit_breaker_active,
    backfill_bootstrap_mode,
    processing_decision_reason
  FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

  UNION ALL

  SELECT
    'player_daily_cache' as processor_name,
    'nba_precompute' as dataset,
    player_lookup as entity_id,
    analysis_date,
    completeness_percentage,
    is_production_ready,
    circuit_breaker_active,
    backfill_bootstrap_mode,
    processing_decision_reason
  FROM `nba-props-platform.nba_precompute.player_daily_cache`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

  UNION ALL

  SELECT
    'player_composite_factors' as processor_name,
    'nba_precompute' as dataset,
    player_lookup as entity_id,
    analysis_date,
    completeness_percentage,
    is_production_ready,
    circuit_breaker_active,
    backfill_bootstrap_mode,
    processing_decision_reason
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

  UNION ALL

  SELECT
    'ml_feature_store' as processor_name,
    'nba_predictions' as dataset,
    player_lookup as entity_id,
    analysis_date,
    completeness_percentage,
    is_production_ready,
    circuit_breaker_active,
    backfill_bootstrap_mode,
    processing_decision_reason
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

  UNION ALL

  SELECT
    'upcoming_player_game_context' as processor_name,
    'nba_analytics' as dataset,
    player_lookup as entity_id,
    game_date as analysis_date,
    completeness_percentage,
    is_production_ready,
    circuit_breaker_active,
    backfill_bootstrap_mode,
    processing_decision_reason
  FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

  UNION ALL

  SELECT
    'upcoming_team_game_context' as processor_name,
    'nba_analytics' as dataset,
    team_abbr as entity_id,
    game_date as analysis_date,
    completeness_percentage,
    is_production_ready,
    circuit_breaker_active,
    backfill_bootstrap_mode,
    processing_decision_reason
  FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
)

SELECT
  processor_name,
  dataset,
  COUNT(DISTINCT entity_id) as unique_entities,
  COUNT(*) as total_records,
  ROUND(AVG(completeness_percentage), 2) as avg_completeness_pct,
  MIN(completeness_percentage) as min_completeness_pct,
  MAX(completeness_percentage) as max_completeness_pct,
  SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as production_ready_count,
  SUM(CASE WHEN circuit_breaker_active THEN 1 ELSE 0 END) as circuit_breaker_count,
  SUM(CASE WHEN backfill_bootstrap_mode THEN 1 ELSE 0 END) as bootstrap_mode_count,
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct
FROM all_processors
GROUP BY processor_name, dataset
ORDER BY processor_name;


-- ============================================================================
-- QUERY 2: Active Circuit Breakers (Alerts)
-- ============================================================================
-- Shows all entities currently blocked by circuit breaker
-- Alert on: circuit_breaker_count > 0
-- ============================================================================

SELECT
  processor_name,
  entity_id,
  analysis_date,
  attempt_number,
  completeness_pct,
  skip_reason,
  attempted_at,
  circuit_breaker_until,
  DATETIME_DIFF(circuit_breaker_until, CURRENT_TIMESTAMP(), DAY) as days_until_retry,
  notes
FROM `nba-props-platform.nba_orchestration.reprocess_attempts`
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
ORDER BY circuit_breaker_until DESC;


-- ============================================================================
-- QUERY 3: Completeness Trends (Last 30 Days)
-- ============================================================================
-- Shows completeness percentage trends over time per processor
-- Use for Grafana time-series visualization
-- ============================================================================

WITH all_processors AS (
  SELECT
    'team_defense_zone_analysis' as processor,
    analysis_date,
    completeness_percentage
  FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

  UNION ALL

  SELECT
    'player_shot_zone_analysis' as processor,
    analysis_date,
    completeness_percentage
  FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

  UNION ALL

  SELECT
    'player_daily_cache' as processor,
    analysis_date,
    completeness_percentage
  FROM `nba-props-platform.nba_precompute.player_daily_cache`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

  UNION ALL

  SELECT
    'player_composite_factors' as processor,
    analysis_date,
    completeness_percentage
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

  UNION ALL

  SELECT
    'ml_feature_store' as processor,
    analysis_date,
    completeness_percentage
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

  UNION ALL

  SELECT
    'upcoming_player_game_context' as processor,
    game_date as analysis_date,
    completeness_percentage
  FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

  UNION ALL

  SELECT
    'upcoming_team_game_context' as processor,
    game_date as analysis_date,
    completeness_percentage
  FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)

SELECT
  analysis_date,
  processor,
  ROUND(AVG(completeness_percentage), 2) as avg_completeness_pct,
  COUNT(*) as record_count
FROM all_processors
GROUP BY analysis_date, processor
ORDER BY analysis_date DESC, processor;


-- ============================================================================
-- QUERY 4: Entities Below 90% Threshold (Action Required)
-- ============================================================================
-- Identifies entities that need attention (incomplete data)
-- Alert on: count > threshold (e.g., > 10% of entities)
-- ============================================================================

WITH incomplete_entities AS (
  SELECT
    'team_defense_zone_analysis' as processor,
    team_abbr as entity_id,
    analysis_date,
    completeness_percentage,
    expected_games_count,
    actual_games_count,
    missing_games_count,
    processing_decision_reason
  FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date = CURRENT_DATE() - 1
    AND completeness_percentage < 90.0
    AND backfill_bootstrap_mode = FALSE

  UNION ALL

  SELECT
    'player_shot_zone_analysis' as processor,
    player_lookup as entity_id,
    analysis_date,
    completeness_percentage,
    expected_games_count,
    actual_games_count,
    missing_games_count,
    processing_decision_reason
  FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
  WHERE analysis_date = CURRENT_DATE() - 1
    AND completeness_percentage < 90.0
    AND backfill_bootstrap_mode = FALSE

  -- Add other processors as needed...
)

SELECT
  processor,
  entity_id,
  analysis_date,
  completeness_percentage,
  expected_games_count,
  actual_games_count,
  missing_games_count,
  processing_decision_reason
FROM incomplete_entities
ORDER BY completeness_percentage ASC, processor, entity_id;


-- ============================================================================
-- QUERY 5: Circuit Breaker History (Last 30 Days)
-- ============================================================================
-- Shows all circuit breaker trips over time
-- Use for analyzing failure patterns
-- ============================================================================

SELECT
  DATE(attempted_at) as attempt_date,
  processor_name,
  entity_id,
  attempt_number,
  ROUND(completeness_pct, 2) as completeness_pct,
  skip_reason,
  circuit_breaker_tripped,
  CASE
    WHEN circuit_breaker_tripped THEN DATETIME_DIFF(circuit_breaker_until, attempted_at, DAY)
    ELSE NULL
  END as cooldown_days,
  manual_override_applied,
  notes
FROM `nba-props-platform.nba_orchestration.reprocess_attempts`
WHERE attempted_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
ORDER BY attempted_at DESC, processor_name, entity_id;


-- ============================================================================
-- QUERY 6: Bootstrap Mode Records (First 30 Days Tracking)
-- ============================================================================
-- Monitors records processed during bootstrap/backfill mode
-- ============================================================================

WITH bootstrap_records AS (
  SELECT
    'team_defense_zone_analysis' as processor,
    analysis_date,
    COUNT(*) as bootstrap_count
  FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
  WHERE backfill_bootstrap_mode = TRUE
  GROUP BY analysis_date

  UNION ALL

  SELECT
    'player_shot_zone_analysis' as processor,
    analysis_date,
    COUNT(*) as bootstrap_count
  FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
  WHERE backfill_bootstrap_mode = TRUE
  GROUP BY analysis_date

  -- Add other processors...
)

SELECT
  processor,
  analysis_date,
  bootstrap_count
FROM bootstrap_records
ORDER BY analysis_date DESC, processor;


-- ============================================================================
-- QUERY 7: Multi-Window Completeness Detail
-- ============================================================================
-- Shows per-window completeness for multi-window processors
-- Useful for debugging which specific windows are failing
-- ============================================================================

SELECT
  player_lookup,
  analysis_date,
  -- Overall
  completeness_percentage,
  is_production_ready,
  all_windows_complete,
  -- L5 window
  l5_completeness_pct,
  l5_is_complete,
  -- L10 window
  l10_completeness_pct,
  l10_is_complete,
  -- L7d window
  l7d_completeness_pct,
  l7d_is_complete,
  -- L14d window
  l14d_completeness_pct,
  l14d_is_complete
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE analysis_date = CURRENT_DATE() - 1
  AND all_windows_complete = FALSE
ORDER BY completeness_percentage ASC
LIMIT 20;


-- ============================================================================
-- QUERY 8: Production Readiness Summary (Daily Report)
-- ============================================================================
-- Daily summary of production readiness across all processors
-- Send as daily email/Slack report
-- ============================================================================

WITH daily_stats AS (
  SELECT
    'team_defense_zone_analysis' as processor,
    COUNT(*) as total_records,
    SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as ready_count,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness
  FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT
    'player_shot_zone_analysis' as processor,
    COUNT(*) as total_records,
    SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as ready_count,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness
  FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT
    'player_daily_cache' as processor,
    COUNT(*) as total_records,
    SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as ready_count,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness
  FROM `nba-props-platform.nba_precompute.player_daily_cache`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT
    'player_composite_factors' as processor,
    COUNT(*) as total_records,
    SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as ready_count,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT
    'ml_feature_store' as processor,
    COUNT(*) as total_records,
    SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as ready_count,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT
    'upcoming_player_game_context' as processor,
    COUNT(*) as total_records,
    SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as ready_count,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness
  FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
  WHERE game_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT
    'upcoming_team_game_context' as processor,
    COUNT(*) as total_records,
    SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as ready_count,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness
  FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
  WHERE game_date = CURRENT_DATE() - 1
)

SELECT
  processor,
  total_records,
  ready_count,
  total_records - ready_count as not_ready_count,
  ROUND(100.0 * ready_count / NULLIF(total_records, 0), 2) as ready_pct,
  avg_completeness,
  CASE
    WHEN ready_pct >= 95 THEN '✅ EXCELLENT'
    WHEN ready_pct >= 90 THEN '✓ GOOD'
    WHEN ready_pct >= 80 THEN '⚠ WARNING'
    ELSE '❌ CRITICAL'
  END as status
FROM daily_stats
ORDER BY ready_pct ASC;


-- ============================================================================
-- QUERY 9: Reprocessing Attempt Patterns
-- ============================================================================
-- Analyzes patterns in reprocessing attempts to identify systemic issues
-- ============================================================================

SELECT
  processor_name,
  skip_reason,
  COUNT(DISTINCT entity_id) as affected_entities,
  COUNT(*) as total_attempts,
  AVG(attempt_number) as avg_attempts_per_entity,
  ROUND(AVG(completeness_pct), 2) as avg_completeness_at_skip,
  SUM(CASE WHEN circuit_breaker_tripped THEN 1 ELSE 0 END) as circuit_breaker_trips
FROM `nba-props-platform.nba_orchestration.reprocess_attempts`
WHERE attempted_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY processor_name, skip_reason
ORDER BY affected_entities DESC, processor_name;


-- ============================================================================
-- GRAFANA DASHBOARD CONFIGURATION
-- ============================================================================
-- Recommended panels for Grafana:
--
-- 1. Overall Health (Query 1)
--    - Panel type: Table
--    - Refresh: 5 minutes
--    - Alert: production_ready_pct < 90%
--
-- 2. Completeness Trends (Query 3)
--    - Panel type: Time series
--    - Refresh: 5 minutes
--    - Group by: processor
--
-- 3. Active Circuit Breakers (Query 2)
--    - Panel type: Table
--    - Refresh: 1 minute
--    - Alert: circuit_breaker_count > 0
--
-- 4. Production Readiness (Query 8)
--    - Panel type: Stat/Gauge
--    - Refresh: 5 minutes
--    - Show: ready_pct for each processor
--
-- 5. Incomplete Entities (Query 4)
--    - Panel type: Table
--    - Refresh: 15 minutes
--    - Alert: count > 10% of total entities
--
-- ============================================================================

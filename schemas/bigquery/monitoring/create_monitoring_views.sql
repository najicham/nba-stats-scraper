-- ============================================================================
-- NBA MONITORING VIEWS
-- ============================================================================
-- Purpose: Create BigQuery views for monitoring pipeline health
-- Dataset: nba_monitoring
-- Created: 2025-11-23
-- ============================================================================

-- ============================================================================
-- VIEW 1: completeness_summary
-- Purpose: Overall completeness health across all 7 processors
-- Usage: SELECT * FROM `nba-props-platform.nba_monitoring.completeness_summary`
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.completeness_summary` AS
WITH all_processors AS (
  SELECT
    'team_defense_zone_analysis' as processor_name,
    'nba_precompute' as dataset,
    'Phase 4' as phase,
    team_abbr as entity_id,
    analysis_date,
    completeness_percentage,
    is_production_ready,
    circuit_breaker_active,
    backfill_bootstrap_mode,
    processing_decision_reason,
    processed_at
  FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

  UNION ALL

  SELECT
    'player_shot_zone_analysis' as processor_name,
    'nba_precompute' as dataset,
    'Phase 4' as phase,
    player_lookup as entity_id,
    analysis_date,
    completeness_percentage,
    is_production_ready,
    circuit_breaker_active,
    backfill_bootstrap_mode,
    processing_decision_reason,
    processed_at
  FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

  UNION ALL

  SELECT
    'player_daily_cache' as processor_name,
    'nba_precompute' as dataset,
    'Phase 4' as phase,
    player_lookup as entity_id,
    analysis_date,
    completeness_percentage,
    is_production_ready,
    circuit_breaker_active,
    backfill_bootstrap_mode,
    processing_decision_reason,
    processed_at
  FROM `nba-props-platform.nba_precompute.player_daily_cache`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

  UNION ALL

  SELECT
    'player_composite_factors' as processor_name,
    'nba_precompute' as dataset,
    'Phase 4' as phase,
    player_lookup as entity_id,
    game_date as analysis_date,
    completeness_percentage,
    is_production_ready,
    circuit_breaker_active,
    backfill_bootstrap_mode,
    processing_decision_reason,
    processed_at
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

  UNION ALL

  SELECT
    'ml_feature_store' as processor_name,
    'nba_predictions' as dataset,
    'Phase 4' as phase,
    player_lookup as entity_id,
    game_date as analysis_date,
    completeness_percentage,
    is_production_ready,
    circuit_breaker_active,
    backfill_bootstrap_mode,
    processing_decision_reason,
    processed_at
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

  UNION ALL

  SELECT
    'upcoming_player_game_context' as processor_name,
    'nba_analytics' as dataset,
    'Phase 3' as phase,
    player_lookup as entity_id,
    game_date as analysis_date,
    completeness_percentage,
    is_production_ready,
    circuit_breaker_active,
    backfill_bootstrap_mode,
    processing_decision_reason,
    processed_at
  FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

  UNION ALL

  SELECT
    'upcoming_team_game_context' as processor_name,
    'nba_analytics' as dataset,
    'Phase 3' as phase,
    team_abbr as entity_id,
    game_date as analysis_date,
    completeness_percentage,
    is_production_ready,
    circuit_breaker_active,
    backfill_bootstrap_mode,
    processing_decision_reason,
    processed_at
  FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
)

SELECT
  processor_name,
  phase,
  dataset,
  COUNT(DISTINCT entity_id) as unique_entities,
  COUNT(*) as total_records,
  ROUND(AVG(completeness_percentage), 2) as avg_completeness_pct,
  MIN(completeness_percentage) as min_completeness_pct,
  MAX(completeness_percentage) as max_completeness_pct,
  SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as production_ready_count,
  SUM(CASE WHEN circuit_breaker_active THEN 1 ELSE 0 END) as circuit_breaker_count,
  SUM(CASE WHEN backfill_bootstrap_mode THEN 1 ELSE 0 END) as bootstrap_mode_count,
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct,
  MAX(processed_at) as last_processed_at
FROM all_processors
GROUP BY processor_name, phase, dataset
ORDER BY phase, processor_name;


-- ============================================================================
-- VIEW 2: active_circuit_breakers
-- Purpose: Show all entities currently blocked by circuit breaker
-- Alert when: circuit_breaker_count > 0
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.active_circuit_breakers` AS
SELECT
  processor_name,
  entity_id,
  analysis_date,
  attempt_number,
  completeness_pct,
  skip_reason,
  attempted_at,
  circuit_breaker_until,
  DATETIME_DIFF(circuit_breaker_until, CURRENT_DATETIME(), DAY) as days_until_retry,
  notes
FROM `nba-props-platform.nba_orchestration.reprocess_attempts`
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_DATETIME()
ORDER BY circuit_breaker_until DESC;


-- ============================================================================
-- VIEW 3: completeness_trends
-- Purpose: Completeness percentage trends over time (last 30 days)
-- Usage: Time-series visualization in Grafana
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.completeness_trends` AS
WITH all_processors AS (
  SELECT
    'team_defense_zone_analysis' as processor,
    'Phase 4' as phase,
    analysis_date,
    completeness_percentage
  FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

  UNION ALL

  SELECT
    'player_shot_zone_analysis' as processor,
    'Phase 4' as phase,
    analysis_date,
    completeness_percentage
  FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

  UNION ALL

  SELECT
    'player_daily_cache' as processor,
    'Phase 4' as phase,
    analysis_date,
    completeness_percentage
  FROM `nba-props-platform.nba_precompute.player_daily_cache`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

  UNION ALL

  SELECT
    'player_composite_factors' as processor,
    'Phase 4' as phase,
    game_date as analysis_date,
    completeness_percentage
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

  UNION ALL

  SELECT
    'ml_feature_store' as processor,
    'Phase 4' as phase,
    game_date as analysis_date,
    completeness_percentage
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

  UNION ALL

  SELECT
    'upcoming_player_game_context' as processor,
    'Phase 3' as phase,
    game_date as analysis_date,
    completeness_percentage
  FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

  UNION ALL

  SELECT
    'upcoming_team_game_context' as processor,
    'Phase 3' as phase,
    game_date as analysis_date,
    completeness_percentage
  FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)

SELECT
  analysis_date,
  processor,
  phase,
  ROUND(AVG(completeness_percentage), 2) as avg_completeness_pct,
  COUNT(*) as record_count
FROM all_processors
GROUP BY analysis_date, processor, phase
ORDER BY analysis_date DESC, processor;


-- ============================================================================
-- VIEW 4: incomplete_entities
-- Purpose: Entities below 90% threshold requiring attention
-- Alert when: count > threshold (e.g., > 10% of entities)
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.incomplete_entities` AS
WITH incomplete_records AS (
  SELECT
    'team_defense_zone_analysis' as processor,
    'Phase 4' as phase,
    team_abbr as entity_id,
    analysis_date,
    completeness_percentage,
    expected_games_count,
    actual_games_count,
    missing_games_count,
    processing_decision_reason
  FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND completeness_percentage < 90.0
    AND backfill_bootstrap_mode = FALSE

  UNION ALL

  SELECT
    'player_shot_zone_analysis' as processor,
    'Phase 4' as phase,
    player_lookup as entity_id,
    analysis_date,
    completeness_percentage,
    expected_games_count,
    actual_games_count,
    missing_games_count,
    processing_decision_reason
  FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND completeness_percentage < 90.0
    AND backfill_bootstrap_mode = FALSE

  UNION ALL

  SELECT
    'player_daily_cache' as processor,
    'Phase 4' as phase,
    player_lookup as entity_id,
    analysis_date,
    completeness_percentage,
    expected_games_count,
    actual_games_count,
    missing_games_count,
    processing_decision_reason
  FROM `nba-props-platform.nba_precompute.player_daily_cache`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND completeness_percentage < 90.0
    AND backfill_bootstrap_mode = FALSE

  UNION ALL

  SELECT
    'upcoming_player_game_context' as processor,
    'Phase 3' as phase,
    player_lookup as entity_id,
    game_date as analysis_date,
    completeness_percentage,
    expected_games_count,
    actual_games_count,
    missing_games_count,
    processing_decision_reason
  FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND completeness_percentage < 90.0
    AND backfill_bootstrap_mode = FALSE

  UNION ALL

  SELECT
    'upcoming_team_game_context' as processor,
    'Phase 3' as phase,
    team_abbr as entity_id,
    game_date as analysis_date,
    completeness_percentage,
    expected_games_count,
    actual_games_count,
    missing_games_count,
    processing_decision_reason
  FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND completeness_percentage < 90.0
    AND backfill_bootstrap_mode = FALSE
)

SELECT
  processor,
  phase,
  entity_id,
  analysis_date,
  completeness_percentage,
  expected_games_count,
  actual_games_count,
  missing_games_count,
  processing_decision_reason
FROM incomplete_records
ORDER BY analysis_date DESC, completeness_percentage ASC, processor, entity_id;


-- ============================================================================
-- VIEW 5: production_readiness_daily
-- Purpose: Daily summary of production readiness
-- Usage: Daily report email/Slack notification
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.production_readiness_daily` AS
WITH daily_stats AS (
  SELECT
    'team_defense_zone_analysis' as processor,
    'Phase 4' as phase,
    COUNT(*) as total_records,
    SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as ready_count,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness,
    MAX(processed_at) as last_processed_at
  FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT
    'player_shot_zone_analysis' as processor,
    'Phase 4' as phase,
    COUNT(*) as total_records,
    SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as ready_count,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness,
    MAX(processed_at) as last_processed_at
  FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT
    'player_daily_cache' as processor,
    'Phase 4' as phase,
    COUNT(*) as total_records,
    SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as ready_count,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness,
    MAX(processed_at) as last_processed_at
  FROM `nba-props-platform.nba_precompute.player_daily_cache`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT
    'player_composite_factors' as processor,
    'Phase 4' as phase,
    COUNT(*) as total_records,
    SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as ready_count,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness,
    MAX(processed_at) as last_processed_at
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT
    'ml_feature_store' as processor,
    'Phase 4' as phase,
    COUNT(*) as total_records,
    SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as ready_count,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness,
    MAX(processed_at) as last_processed_at
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE game_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT
    'upcoming_player_game_context' as processor,
    'Phase 3' as phase,
    COUNT(*) as total_records,
    SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as ready_count,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness,
    MAX(processed_at) as last_processed_at
  FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
  WHERE game_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT
    'upcoming_team_game_context' as processor,
    'Phase 3' as phase,
    COUNT(*) as total_records,
    SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as ready_count,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness,
    MAX(processed_at) as last_processed_at
  FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
  WHERE game_date = CURRENT_DATE() - 1
)

SELECT
  processor,
  phase,
  total_records,
  ready_count,
  total_records - ready_count as not_ready_count,
  ROUND(100.0 * ready_count / NULLIF(total_records, 0), 2) as ready_pct,
  avg_completeness,
  last_processed_at,
  CASE
    WHEN total_records = 0 THEN '⚪ NO DATA'
    WHEN ready_pct >= 95 THEN '✅ EXCELLENT'
    WHEN ready_pct >= 90 THEN '✓ GOOD'
    WHEN ready_pct >= 80 THEN '⚠ WARNING'
    ELSE '❌ CRITICAL'
  END as status
FROM daily_stats
ORDER BY phase, ready_pct ASC;


-- ============================================================================
-- VIEW 6: cascade_scheduler_status (NEW)
-- Purpose: Monitor CASCADE scheduler job execution
-- Usage: Check if nightly scheduler jobs ran successfully
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.cascade_scheduler_status` AS
WITH latest_runs AS (
  SELECT
    'player_composite_factors' as processor,
    game_date as analysis_date,
    is_production_ready,
    completeness_percentage,
    data_quality_issues,
    processed_at,
    processing_decision_reason
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)

  UNION ALL

  SELECT
    'ml_feature_store' as processor,
    game_date as analysis_date,
    is_production_ready,
    completeness_percentage,
    data_quality_issues,
    processed_at,
    processing_decision_reason
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
)

SELECT
  processor,
  analysis_date,
  COUNT(DISTINCT player_lookup) as entities_processed,
  SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as production_ready_count,
  ROUND(AVG(completeness_percentage), 2) as avg_completeness,
  ARRAY_AGG(DISTINCT issue IGNORE NULLS) as all_data_quality_issues,
  MAX(processed_at) as last_run_time,
  CASE
    WHEN MAX(processed_at) IS NULL THEN '❌ NEVER RAN'
    WHEN DATE(MAX(processed_at), 'America/Los_Angeles') = CURRENT_DATE() THEN '✅ RAN TODAY'
    WHEN DATE(MAX(processed_at), 'America/Los_Angeles') = CURRENT_DATE() - 1 THEN '✓ RAN YESTERDAY'
    ELSE '⚠ STALE'
  END as run_status
FROM latest_runs
CROSS JOIN UNNEST(IFNULL(data_quality_issues, [])) as issue
GROUP BY processor, analysis_date
ORDER BY processor, analysis_date DESC;


-- ============================================================================
-- VIEW 7: pubsub_flow_health (NEW)
-- Purpose: Monitor Pub/Sub message flow Phase 3 → Phase 4
-- Usage: Detect publishing or subscription issues
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.pubsub_flow_health` AS
WITH phase3_completions AS (
  -- Phase 3 processors that should have published
  SELECT
    'player_game_summary' as source_table,
    game_date as analysis_date,
    MAX(processed_at) as phase3_completed_at
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY game_date

  UNION ALL

  SELECT
    'team_defense_game_summary' as source_table,
    game_date as analysis_date,
    MAX(processed_at) as phase3_completed_at
  FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY game_date

  UNION ALL

  SELECT
    'team_offense_game_summary' as source_table,
    game_date as analysis_date,
    MAX(processed_at) as phase3_completed_at
  FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY game_date
),

phase4_executions AS (
  -- Phase 4 processors that should have been triggered
  SELECT
    'team_defense_zone_analysis' as processor,
    'team_defense_game_summary' as source_table,
    analysis_date,
    MAX(processed_at) as phase4_completed_at
  FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY analysis_date

  UNION ALL

  SELECT
    'player_shot_zone_analysis' as processor,
    'team_offense_game_summary' as source_table,
    analysis_date,
    MAX(processed_at) as phase4_completed_at
  FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY analysis_date

  UNION ALL

  SELECT
    'player_daily_cache' as processor,
    'player_game_summary' as source_table,
    analysis_date,
    MAX(processed_at) as phase4_completed_at
  FROM `nba-props-platform.nba_precompute.player_daily_cache`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY analysis_date
)

SELECT
  p3.source_table,
  p3.analysis_date,
  p3.phase3_completed_at,
  p4.processor as phase4_processor,
  p4.phase4_completed_at,
  TIMESTAMP_DIFF(p4.phase4_completed_at, p3.phase3_completed_at, SECOND) as latency_seconds,
  CASE
    WHEN p4.phase4_completed_at IS NULL THEN '❌ PHASE 4 DID NOT RUN'
    WHEN TIMESTAMP_DIFF(p4.phase4_completed_at, p3.phase3_completed_at, SECOND) < 300 THEN '✅ FAST (<5min)'
    WHEN TIMESTAMP_DIFF(p4.phase4_completed_at, p3.phase3_completed_at, SECOND) < 1800 THEN '✓ NORMAL (<30min)'
    ELSE '⚠ SLOW (>30min)'
  END as pubsub_status
FROM phase3_completions p3
LEFT JOIN phase4_executions p4
  ON p3.source_table = p4.source_table
  AND p3.analysis_date = p4.analysis_date
ORDER BY p3.analysis_date DESC, p3.source_table;


-- ============================================================================
-- VIEW 8: multi_window_completeness (NEW)
-- Purpose: Detail for multi-window processors (player_daily_cache, upcoming contexts)
-- Usage: Debug which specific windows are failing
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.multi_window_completeness` AS
SELECT
  'player_daily_cache' as processor,
  player_lookup,
  analysis_date,
  completeness_percentage as overall_completeness,
  is_production_ready,
  all_windows_complete,
  l5_completeness_pct,
  l5_is_complete,
  l10_completeness_pct,
  l10_is_complete,
  l7d_completeness_pct,
  l7d_is_complete,
  l14d_completeness_pct,
  l14d_is_complete,
  NULL as l30d_completeness_pct,
  NULL as l30d_is_complete
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND all_windows_complete = FALSE

UNION ALL

SELECT
  'upcoming_player_game_context' as processor,
  player_lookup,
  game_date as analysis_date,
  completeness_percentage as overall_completeness,
  is_production_ready,
  all_windows_complete,
  l5_completeness_pct,
  l5_is_complete,
  l10_completeness_pct,
  l10_is_complete,
  l7d_completeness_pct,
  l7d_is_complete,
  l14d_completeness_pct,
  l14d_is_complete,
  l30d_completeness_pct,
  l30d_is_complete
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND all_windows_complete = FALSE

ORDER BY analysis_date DESC, processor, overall_completeness ASC
LIMIT 100;


-- ============================================================================
-- VIEWS CREATED:
-- 1. completeness_summary - Overall health by processor
-- 2. active_circuit_breakers - Blocked entities requiring attention
-- 3. completeness_trends - Time-series data for Grafana
-- 4. incomplete_entities - Entities below 90% threshold
-- 5. production_readiness_daily - Daily status report
-- 6. cascade_scheduler_status - CASCADE scheduler job monitoring (NEW)
-- 7. pubsub_flow_health - Pub/Sub Phase 3→4 latency tracking (NEW)
-- 8. multi_window_completeness - Multi-window processor detail (NEW)
-- ============================================================================

-- ============================================================================
-- NBA Props Platform - Phase 4 Precompute Dataset
-- ============================================================================
-- File: dataset_precompute.sql
-- Purpose: Create Phase 4 precompute dataset for aggregated analytics
-- Location: US
-- Tables: 4 (player_shot_zone_analysis, team_defense_zone_analysis,
--           player_composite_factors, player_daily_cache)
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_precompute`
OPTIONS (
  description = "Phase 4: Pre-computed aggregations, shot zone analysis, and composite factors for prediction systems. Updated nightly (11 PM - 6 AM) and on-demand.",
  location = "US"
);

-- ============================================================================
-- Purpose & Update Schedule
-- ============================================================================
-- This dataset contains pre-calculated metrics that are expensive to compute
-- in real-time but don't change frequently during the day.
--
-- UPDATE SCHEDULE:
-- 1. Nightly (11:00 PM - 1:00 AM): Full recalculation after Phase 3 complete
--    - player_shot_zone_analysis (11:15 PM, ~5-8 min)
--    - team_defense_zone_analysis (11:00 PM, ~2 min)
--    - player_composite_factors (11:30 PM, ~10 min)
--    - player_daily_cache (11:45 PM, ~5 min)
--
-- 2. Morning (6:00 AM): Final updates for today's games
--    - player_composite_factors (refresh)
--    - player_daily_cache (lock for day)
--
-- 3. Real-time (During Day): Only when needed
--    - player_composite_factors (when betting lines change)
--
-- RETENTION:
-- - 90 days for most tables (sufficient for analysis)
-- - Can regenerate from Phase 3 if needed
--
-- DEPENDENCIES:
-- - Phase 3 (nba_analytics): Must be current (<24 hours)
-- - Phase 2 (nba_structured): Historical backfill only
-- ============================================================================

-- ============================================================================
-- Table Summary
-- ============================================================================
-- 1. player_shot_zone_analysis (~450 players)
--    - Shot distribution by zone (paint, mid-range, three-point)
--    - Last 10 games + last 20 games
--    - Efficiency and volume per zone
--    - Source: nba_analytics.player_game_summary
--
-- 2. team_defense_zone_analysis (30 teams)
--    - Defensive performance by zone
--    - Last 15 games
--    - Zone strengths/weaknesses
--    - Source: nba_analytics.team_defense_game_summary
--
-- 3. player_composite_factors (~450 players × games)
--    - Fatigue, matchup, pace, usage adjustments
--    - Week 1-4: 4 active factors, 4 deferred (set to 0)
--    - Sources: Multiple Phase 3 + Phase 4 tables
--
-- 4. player_daily_cache (~450 players)
--    - Daily snapshot of stable player data
--    - Updated once at 6 AM
--    - Speeds up line change re-predictions
--    - Sources: Multiple Phase 3 tables
-- ============================================================================

-- ============================================================================
-- Monitoring & Alerts
-- ============================================================================
-- Monitor dataset health:
SELECT 
  table_name,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), 
    (SELECT MAX(processed_at) FROM `nba-props-platform.nba_precompute.{table_name}`),
    HOUR
  ) as hours_since_update,
  (SELECT COUNT(*) FROM `nba-props-platform.nba_precompute.{table_name}` 
   WHERE DATE(processed_at) = CURRENT_DATE()) as today_rows
FROM `nba-props-platform.nba_precompute.INFORMATION_SCHEMA.TABLES`
WHERE table_name IN (
  'player_shot_zone_analysis',
  'team_defense_zone_analysis', 
  'player_composite_factors',
  'player_daily_cache'
);

-- Alert conditions:
-- - Any table >72 hours stale
-- - player_shot_zone_analysis: <400 rows today
-- - team_defense_zone_analysis: <25 rows today
-- - player_composite_factors: <100 rows today
-- ============================================================================

-- ============================================================================
-- Cost Estimates (per day)
-- ============================================================================
-- Storage: ~50 MB/day (90 days = 4.5 GB)
--   - player_shot_zone_analysis: ~20 MB
--   - team_defense_zone_analysis: ~1 MB
--   - player_composite_factors: ~25 MB
--   - player_daily_cache: ~4 MB
--
-- Query Cost: ~$0.10/day
--   - Nightly updates: ~$0.05
--   - Phase 5 reads: ~$0.03
--   - Monitoring: ~$0.02
--
-- Total: ~$4/month (negligible)
-- ============================================================================

-- ============================================================================
-- Related Documentation
-- ============================================================================
-- - phase4_processor_implementation.md: How processors work
-- - dependency_tracking_v4.md: Source tracking design
-- - phase5_infrastructure_architecture.md: How Phase 5 uses this data
-- ============================================================================
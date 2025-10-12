-- ============================================================================
-- File: validation/queries/raw/nbac_gamebook/realtime_scraper_check.sql
-- Purpose: Real-time check of today's game processing status
-- Usage: Run during the day to monitor live scraper/processor health
-- ============================================================================
-- Instructions:
--   1. Run periodically during game days (e.g., every hour after games end)
--   2. Monitor for games that should be processed but aren't yet
--   3. No date parameters needed - automatically checks today
-- ============================================================================
-- Expected Results:
--   - Shows which games are processed vs pending
--   - Flags games that should be ready but are missing data
--   - Helps identify scraper/processor delays or failures
-- ============================================================================

WITH todays_schedule AS (
  SELECT
    game_id,
    game_date,
    home_team_name,
    home_team_tricode,
    away_team_name,
    away_team_tricode,
    CONCAT(away_team_tricode, ' @ ', home_team_tricode) as matchup,
    -- Estimate game completion time (games ~2.5 hours, add 30 min buffer)
    TIMESTAMP_ADD(
      TIMESTAMP(CONCAT(CAST(game_date AS STRING), ' 19:00:00')), 
      INTERVAL 3 HOUR
    ) as estimated_completion
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = CURRENT_DATE()
),

todays_gamebook AS (
  SELECT
    game_id,
    COUNT(*) as player_count,
    COUNT(CASE WHEN player_status = 'active' THEN 1 END) as active_count,
    COUNT(CASE WHEN player_status = 'inactive' THEN 1 END) as inactive_count,
    COUNT(CASE WHEN player_status = 'inactive' AND name_resolution_status = 'resolved' THEN 1 END) as resolved_count,
    MAX(processed_at) as last_processed,
    ROUND(SAFE_DIVIDE(
      COUNT(CASE WHEN player_status = 'inactive' AND name_resolution_status = 'resolved' THEN 1 END),
      COUNT(CASE WHEN player_status = 'inactive' THEN 1 END)
    ) * 100, 1) as resolution_rate_pct
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date = CURRENT_DATE()
  GROUP BY game_id
)

SELECT
  s.game_date,
  s.matchup,
  s.home_team_name,
  s.away_team_name,
  COALESCE(g.player_count, 0) as players_found,
  COALESCE(g.active_count, 0) as active_players,
  COALESCE(g.inactive_count, 0) as inactive_players,
  COALESCE(g.resolved_count, 0) as resolved_inactive,
  CONCAT(CAST(COALESCE(g.resolution_rate_pct, 0) AS STRING), '%') as resolution_rate,
  g.last_processed,
  CASE
    WHEN g.game_id IS NULL AND CURRENT_TIMESTAMP() < s.estimated_completion 
      THEN '⏳ Game in progress'
    WHEN g.game_id IS NULL AND CURRENT_TIMESTAMP() >= s.estimated_completion 
      THEN '❌ MISSING (should be ready)'
    WHEN g.player_count < 25 
      THEN '⚠️ INCOMPLETE (too few players)'
    WHEN g.resolution_rate_pct < 98.0 
      THEN '⚠️ Low resolution rate'
    ELSE '✅ Processed'
  END as status,
  -- Time since game should have been processed
  CASE
    WHEN g.game_id IS NULL AND CURRENT_TIMESTAMP() >= s.estimated_completion
      THEN CONCAT(
        CAST(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), s.estimated_completion, MINUTE) AS STRING), 
        ' min overdue'
      )
    ELSE NULL
  END as delay
FROM todays_schedule s
LEFT JOIN todays_gamebook g ON s.game_id = g.game_id
ORDER BY 
  CASE 
    WHEN g.game_id IS NULL AND CURRENT_TIMESTAMP() >= s.estimated_completion THEN 1
    WHEN g.player_count < 25 THEN 2
    WHEN g.game_id IS NULL THEN 3
    ELSE 4
  END,
  s.matchup;

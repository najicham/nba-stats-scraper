-- ============================================================================
-- File: validation/queries/raw/nbac_gamebook/daily_check_yesterday.sql
-- Purpose: Daily morning check to verify yesterday's games were processed
-- Usage: Run every morning as part of automated monitoring (e.g., 9 AM)
-- ============================================================================
-- Instructions:
--   1. Schedule this to run daily at ~9 AM (after processor completes)
--   2. Set up alerts for status != "✅ Complete" or "✅ No games scheduled"
--   3. No date parameters needed - automatically checks yesterday
-- ============================================================================
-- Expected Results:
--   - status = "✅ Complete" when all games processed with proper player counts
--   - status = "✅ No games scheduled" on off days
--   - status = "❌ CRITICAL" requires immediate investigation
-- ============================================================================

WITH yesterday_schedule AS (
  SELECT
    COUNT(*) as scheduled_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND is_playoffs = FALSE  -- Set to TRUE during playoffs
),

yesterday_gamebook AS (
  SELECT
    COUNT(DISTINCT game_id) as gamebook_games,
    COUNT(*) as total_players,
    COUNT(CASE WHEN player_status = 'active' THEN 1 END) as active_players,
    COUNT(CASE WHEN player_status = 'inactive' THEN 1 END) as inactive_players,
    COUNT(CASE WHEN player_status = 'dnp' THEN 1 END) as dnp_players,
    -- Name resolution for inactive players
    COUNT(CASE WHEN player_status = 'inactive' AND name_resolution_status = 'resolved' THEN 1 END) as inactive_resolved,
    ROUND(SAFE_DIVIDE(
      COUNT(CASE WHEN player_status = 'inactive' AND name_resolution_status = 'resolved' THEN 1 END),
      COUNT(CASE WHEN player_status = 'inactive' THEN 1 END)
    ) * 100, 1) as resolution_rate_pct
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),

games_with_issues AS (
  SELECT
    COUNT(*) as games_with_issues
  FROM (
    SELECT
      game_id,
      COUNT(*) as player_count
    FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
    WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    GROUP BY game_id
    HAVING player_count < 25  -- Flag games with too few players
  )
)

SELECT
  DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
  s.scheduled_games,
  g.gamebook_games,
  g.total_players,
  g.active_players,
  g.inactive_players,
  g.dnp_players,
  g.inactive_resolved,
  CONCAT(CAST(g.resolution_rate_pct AS STRING), '%') as resolution_rate,
  i.games_with_issues,
  CASE
    WHEN s.scheduled_games = 0 THEN '✅ No games scheduled'
    WHEN g.gamebook_games = 0 THEN '❌ CRITICAL: No gamebook data'
    WHEN g.gamebook_games < s.scheduled_games THEN CONCAT('⚠️ WARNING: ', CAST(s.scheduled_games - g.gamebook_games AS STRING), ' games missing')
    WHEN i.games_with_issues > 0 THEN CONCAT('⚠️ WARNING: ', CAST(i.games_with_issues AS STRING), ' games incomplete')
    WHEN g.resolution_rate_pct < 98.0 THEN '⚠️ WARNING: Low resolution rate'
    ELSE '✅ Complete'
  END as status
FROM yesterday_schedule s
CROSS JOIN yesterday_gamebook g
CROSS JOIN games_with_issues i;


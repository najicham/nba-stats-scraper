-- ============================================================================
-- File: validation/queries/raw/odds_api_props/daily_check_yesterday.sql
-- Purpose: Daily morning check to verify yesterday's games have player props
-- Usage: Run every morning as part of automated monitoring
-- ============================================================================
-- Instructions:
--   1. Schedule this to run daily at ~9 AM (after scraper/processor complete)
--   2. Set up alerts for status != "✅ Complete" or "✅ No games scheduled"
--   3. No date parameters needed - automatically checks yesterday
-- ============================================================================
-- Expected Results:
--   - status = "✅ Complete" when all games have adequate props
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

yesterday_props AS (
  SELECT
    COUNT(DISTINCT game_id) as games_with_props,
    COUNT(DISTINCT player_lookup) as total_unique_players,
    COUNT(DISTINCT CASE WHEN bookmaker = 'DraftKings' THEN game_id END) as games_with_dk,
    COUNT(DISTINCT CASE WHEN bookmaker = 'FanDuel' THEN game_id END) as games_with_fd,
    ROUND(AVG(players_per_game), 1) as avg_players_per_game,
    MIN(players_per_game) as min_players_per_game,
    MAX(players_per_game) as max_players_per_game
  FROM (
    SELECT
      game_id,
      COUNT(DISTINCT player_lookup) as players_per_game
    FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
    WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    GROUP BY game_id
  )
),

games_with_low_coverage AS (
  SELECT
    COUNT(*) as low_coverage_games
  FROM (
    SELECT
      game_id,
      COUNT(DISTINCT player_lookup) as players_per_game
    FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
    WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    GROUP BY game_id
    HAVING COUNT(DISTINCT player_lookup) < 6
  )
)

SELECT
  DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
  s.scheduled_games,
  p.games_with_props,
  p.total_unique_players,
  p.avg_players_per_game,
  p.min_players_per_game,
  p.max_players_per_game,
  p.games_with_dk,
  p.games_with_fd,
  l.low_coverage_games,
  CASE
    WHEN s.scheduled_games = 0 THEN '✅ No games scheduled'
    WHEN p.games_with_props = 0 THEN '❌ CRITICAL: No props data'
    WHEN p.games_with_props < s.scheduled_games THEN 
      CONCAT('🔴 CRITICAL: ', CAST(s.scheduled_games - p.games_with_props AS STRING), ' games missing props')
    WHEN p.avg_players_per_game < 6.0 THEN 
      CONCAT('🟡 WARNING: Low average coverage (', CAST(p.avg_players_per_game AS STRING), ' players/game)')
    WHEN l.low_coverage_games > 0 THEN
      CONCAT('⚠️ WARNING: ', CAST(l.low_coverage_games AS STRING), ' games with <6 players')
    ELSE '✅ Complete'
  END as status,
  CASE
    WHEN p.games_with_props > 0 AND p.games_with_dk = 0 THEN '⚠️ No DraftKings data'
    WHEN p.games_with_props > 0 AND p.games_with_fd = 0 THEN '⚠️ No FanDuel data'
    WHEN p.games_with_dk > 0 OR p.games_with_fd > 0 THEN '✅ At least one bookmaker'
    ELSE ''
  END as bookmaker_status
FROM yesterday_schedule s
CROSS JOIN yesterday_props p
CROSS JOIN games_with_low_coverage l;

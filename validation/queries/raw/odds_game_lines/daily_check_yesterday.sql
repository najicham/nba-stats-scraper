-- ============================================================================
-- File: validation/queries/raw/odds_game_lines/daily_check_yesterday.sql
-- Purpose: Daily morning check to verify yesterday's games were captured
-- Usage: Run every morning as part of automated monitoring
-- ============================================================================
-- Instructions:
--   1. Schedule this to run daily at ~9 AM (after scraper/processor complete)
--   2. Set up alerts for status != "✅ Complete" or "✅ No games scheduled"
--   3. No date parameters needed - automatically checks yesterday
-- ============================================================================
-- Expected Results:
--   - status = "✅ Complete" when all games captured
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

yesterday_odds AS (
  SELECT 
    COUNT(DISTINCT game_id) as odds_games,
    COUNT(DISTINCT CASE WHEN market_key = 'spreads' THEN game_id END) as games_with_spreads,
    COUNT(DISTINCT CASE WHEN market_key = 'totals' THEN game_id END) as games_with_totals,
    COUNT(DISTINCT CASE WHEN bookmaker_key = 'draftkings' THEN game_id END) as games_with_dk,
    COUNT(DISTINCT CASE WHEN bookmaker_key = 'fanduel' THEN game_id END) as games_with_fd
  FROM `nba-props-platform.nba_raw.odds_api_game_lines`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
)

SELECT 
  DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
  s.scheduled_games,
  o.odds_games,
  o.games_with_spreads,
  o.games_with_totals,
  o.games_with_dk,
  o.games_with_fd,
  CASE 
    WHEN s.scheduled_games = 0 THEN '✅ No games scheduled'
    WHEN o.odds_games = s.scheduled_games THEN '✅ Complete'
    WHEN o.odds_games = 0 THEN '❌ CRITICAL: No odds data'
    ELSE CONCAT('⚠️ WARNING: ', CAST(s.scheduled_games - o.odds_games AS STRING), ' games missing')
  END as status
FROM yesterday_schedule s
CROSS JOIN yesterday_odds o;
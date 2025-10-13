-- ============================================================================
-- File: validation/queries/raw/nbac_referee/daily_check_yesterday.sql
-- Purpose: Daily morning check to verify yesterday's referee assignments were captured
-- Usage: Run every morning as part of automated monitoring
-- ============================================================================
-- Instructions:
--   1. Schedule this to run daily at ~9 AM (after scraper/processor complete)
--   2. Set up alerts for status != "✅ Complete" or "✅ No games scheduled"
--   3. No date parameters needed - automatically checks yesterday
-- ============================================================================
-- Expected Results:
--   - status = "✅ Complete" when all games captured with correct official counts
--   - status = "✅ No games scheduled" on off days
--   - status = "❌ CRITICAL" requires immediate investigation
-- ============================================================================

WITH yesterday_schedule AS (
  SELECT
    COUNT(*) as scheduled_games,
    SUM(CASE WHEN is_playoffs = FALSE THEN 1 ELSE 0 END) as regular_season_games,
    SUM(CASE WHEN is_playoffs = TRUE THEN 1 ELSE 0 END) as playoff_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),

yesterday_refs AS (
  SELECT
    COUNT(DISTINCT game_id) as games_with_refs,
    COUNT(DISTINCT official_code) as unique_officials,
    COUNT(*) as total_assignments,
    MIN(CASE 
      WHEN game_date < '2024-04-13' THEN 3  -- Regular season expects 3
      ELSE 4  -- Playoffs expect 4
    END) as min_officials_per_game,
    MAX(CASE 
      WHEN game_date < '2024-04-13' THEN 3
      ELSE 4
    END) as max_officials_per_game
  FROM `nba-props-platform.nba_raw.nbac_referee_game_assignments`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),

-- Check for games with wrong official counts
wrong_counts AS (
  SELECT
    game_id,
    COUNT(DISTINCT official_code) as official_count
  FROM `nba-props-platform.nba_raw.nbac_referee_game_assignments`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  GROUP BY game_id
  HAVING COUNT(DISTINCT official_code) NOT IN (3, 4)
)

SELECT
  DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
  s.scheduled_games,
  s.regular_season_games,
  s.playoff_games,
  r.games_with_refs,
  r.unique_officials,
  r.total_assignments,
  (SELECT COUNT(*) FROM wrong_counts) as games_with_wrong_count,
  CASE
    WHEN s.scheduled_games = 0 THEN '✅ No games scheduled'
    WHEN r.games_with_refs = s.scheduled_games 
     AND (SELECT COUNT(*) FROM wrong_counts) = 0 THEN '✅ Complete'
    WHEN r.games_with_refs = 0 THEN '❌ CRITICAL: No referee data'
    WHEN (SELECT COUNT(*) FROM wrong_counts) > 0 THEN '⚠️ WARNING: Some games have wrong official count'
    ELSE CONCAT('⚠️ WARNING: ', CAST(s.scheduled_games - r.games_with_refs AS STRING), ' games missing')
  END as status
FROM yesterday_schedule s
CROSS JOIN yesterday_refs r;

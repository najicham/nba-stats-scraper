-- ============================================================================
-- File: validation/queries/raw/bdl_boxscores/daily_check_yesterday.sql
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
),

-- Get per-game player counts
game_player_counts AS (
  SELECT
    game_id,
    COUNT(DISTINCT player_lookup) as players_per_game
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  GROUP BY game_id
),

-- Get overall stats
yesterday_boxscores AS (
  SELECT
    (SELECT COUNT(DISTINCT game_id) FROM game_player_counts) as games_with_data,
    (SELECT COUNT(*) FROM `nba-props-platform.nba_raw.bdl_player_boxscores` 
     WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)) as total_player_records,
    (SELECT COUNT(DISTINCT player_lookup) FROM `nba-props-platform.nba_raw.bdl_player_boxscores` 
     WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)) as unique_players,
    ROUND(AVG(players_per_game), 1) as avg_players_per_game,
    MIN(players_per_game) as min_players_per_game,
    MAX(players_per_game) as max_players_per_game
  FROM game_player_counts
)

SELECT
  DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
  s.scheduled_games,
  b.games_with_data,
  b.total_player_records,
  b.unique_players,
  b.avg_players_per_game,
  b.min_players_per_game,
  b.max_players_per_game,
  CASE
    WHEN s.scheduled_games = 0 THEN '✅ No games scheduled'
    WHEN b.games_with_data = s.scheduled_games 
     AND b.min_players_per_game >= 20  -- Sanity check: at least 20 players per game
    THEN '✅ Complete'
    WHEN b.games_with_data = 0 THEN '❌ CRITICAL: No box score data'
    WHEN b.min_players_per_game < 20 THEN '⚠️ WARNING: Suspiciously low player count'
    ELSE CONCAT('⚠️ WARNING: ', CAST(s.scheduled_games - b.games_with_data AS STRING), ' games missing')
  END as status
FROM yesterday_schedule s
CROSS JOIN yesterday_boxscores b;
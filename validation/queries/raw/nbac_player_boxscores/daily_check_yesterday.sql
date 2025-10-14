-- ============================================================================
-- File: validation/queries/raw/nbac_player_boxscores/daily_check_yesterday.sql
-- Purpose: Daily morning check to verify yesterday's games were captured
-- Usage: Run every morning as part of automated monitoring
-- ============================================================================
-- ⚠️ NOTE: Table is currently empty (awaiting NBA season start)
-- This query is ready to execute once data arrives
-- ============================================================================
-- Instructions:
--   1. Schedule this to run daily at ~9 AM (after scraper/processor complete)
--   2. Set up alerts for status != "✅ Complete" or "✅ No games scheduled"
--   3. No date parameters needed - automatically checks yesterday
--   4. Compare with BDL daily check for consistency
-- ============================================================================
-- Expected Results:
--   - status = "✅ Complete" when all games captured
--   - status = "✅ No games scheduled" on off days
--   - status = "❌ CRITICAL" requires immediate investigation
--   - Should closely match BDL boxscore daily check results
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
    COUNT(DISTINCT player_lookup) as players_per_game,
    COUNT(DISTINCT CASE WHEN starter = TRUE THEN player_lookup END) as starters_per_game
  FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  GROUP BY game_id
),

-- Get overall stats
yesterday_boxscores AS (
  SELECT
    (SELECT COUNT(DISTINCT game_id) FROM game_player_counts) as games_with_data,
    (SELECT COUNT(*) FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
     WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)) as total_player_records,
    (SELECT COUNT(DISTINCT player_lookup) FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
     WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)) as unique_players,
    (SELECT COUNT(DISTINCT nba_player_id) FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
     WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)) as unique_nba_player_ids,
    ROUND(AVG(players_per_game), 1) as avg_players_per_game,
    ROUND(AVG(starters_per_game), 1) as avg_starters_per_game,
    MIN(players_per_game) as min_players_per_game,
    MAX(players_per_game) as max_players_per_game
  FROM game_player_counts
),

-- Compare with BDL for cross-validation
bdl_comparison AS (
  SELECT
    COUNT(DISTINCT game_id) as bdl_games,
    COUNT(*) as bdl_total_records
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
)

SELECT
  DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
  s.scheduled_games,
  b.games_with_data,
  b.total_player_records,
  b.unique_players,
  b.unique_nba_player_ids,
  b.avg_players_per_game,
  b.avg_starters_per_game,
  b.min_players_per_game,
  b.max_players_per_game,
  
  -- BDL comparison
  c.bdl_games,
  c.bdl_total_records,
  
  -- Primary status
  CASE
    WHEN s.scheduled_games = 0 THEN '✅ No games scheduled'
    WHEN b.games_with_data = s.scheduled_games
     AND b.min_players_per_game >= 20
     AND b.avg_starters_per_game BETWEEN 4.5 AND 5.5  -- Should be ~5 starters per team
    THEN '✅ Complete'
    WHEN b.games_with_data = 0 THEN '❌ CRITICAL: No box score data'
    WHEN b.min_players_per_game < 20 THEN '⚠️ WARNING: Suspiciously low player count'
    WHEN b.avg_starters_per_game < 4 OR b.avg_starters_per_game > 6 
      THEN '⚠️ WARNING: Unusual starter count'
    ELSE CONCAT('⚠️ WARNING: ', CAST(s.scheduled_games - b.games_with_data AS STRING), ' games missing')
  END as status,
  
  -- BDL consistency check
  CASE
    WHEN ABS(COALESCE(b.games_with_data, 0) - COALESCE(c.bdl_games, 0)) = 0 
      THEN '✅ Matches BDL'
    WHEN ABS(COALESCE(b.games_with_data, 0) - COALESCE(c.bdl_games, 0)) <= 2 
      THEN '⚠️ Minor discrepancy vs BDL'
    ELSE '❌ Major discrepancy vs BDL'
  END as bdl_consistency,
  
  -- Additional notes
  CASE
    WHEN b.unique_nba_player_ids < b.unique_players 
      THEN CONCAT('⚠️ Missing NBA player IDs: ', 
           CAST(b.unique_players - b.unique_nba_player_ids AS STRING), ' players')
    WHEN b.games_with_data = 0 AND s.scheduled_games > 0
      THEN '❌ Check scraper and processor logs immediately'
    WHEN b.games_with_data < s.scheduled_games
      THEN CONCAT('⚠️ Missing games: Check find_missing_games.sql for details')
    ELSE '✅ All checks passed'
  END as notes

FROM yesterday_schedule s
CROSS JOIN yesterday_boxscores b
CROSS JOIN bdl_comparison c;

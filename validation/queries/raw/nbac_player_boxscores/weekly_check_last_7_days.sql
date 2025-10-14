-- ============================================================================
-- File: validation/queries/raw/nbac_player_boxscores/weekly_check_last_7_days.sql
-- Purpose: Weekly health check showing daily coverage trends
-- Usage: Run weekly to spot patterns and ensure consistent data capture
-- ============================================================================
-- ⚠️ NOTE: Table is currently empty (awaiting NBA season start)
-- This query is ready to execute once data arrives
-- ============================================================================
-- Instructions:
--   1. Run once per week (e.g., Monday mornings)
--   2. Review for patterns (specific days with issues)
--   3. Compare with BDL weekly check for consistency
--   4. No date parameters needed - automatically checks last 7 days
-- ============================================================================
-- Expected Results:
--   - Each day should show "✅ Complete" or "⚪ No games"
--   - Multiple "⚠️ Incomplete" or "❌ Missing all" = scraper issue
--   - Should closely match BDL weekly check results
-- ============================================================================

WITH date_range AS (
  SELECT date
  FROM UNNEST(GENERATE_DATE_ARRAY(
    DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY),
    DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  )) as date
),

daily_schedule AS (
  SELECT
    game_date,
    COUNT(*) as scheduled_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  GROUP BY game_date
),

-- NBA.com boxscore stats
daily_boxscores AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as games_with_data,
    SUM(total_players) as total_player_records,
    SUM(unique_players) as unique_players,
    SUM(unique_nba_ids) as unique_nba_ids,
    ROUND(AVG(players_per_game), 1) as avg_players_per_game,
    ROUND(AVG(starters_per_game), 1) as avg_starters_per_game,
    MIN(players_per_game) as min_players_per_game
  FROM (
    SELECT
      game_date,
      game_id,
      COUNT(*) as total_players,
      COUNT(DISTINCT player_lookup) as unique_players,
      COUNT(DISTINCT nba_player_id) as unique_nba_ids,
      COUNT(DISTINCT player_lookup) as players_per_game,
      COUNT(DISTINCT CASE WHEN starter = TRUE THEN player_lookup END) as starters_per_game
    FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
    WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    GROUP BY game_date, game_id
  )
  GROUP BY game_date
),

-- BDL comparison
bdl_daily_stats AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as bdl_games,
    COUNT(*) as bdl_total_records
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  GROUP BY game_date
)

SELECT
  d.date as game_date,
  FORMAT_DATE('%A', d.date) as day_of_week,
  COALESCE(s.scheduled_games, 0) as scheduled_games,
  COALESCE(b.games_with_data, 0) as nbac_games,
  COALESCE(bdl.bdl_games, 0) as bdl_games,
  COALESCE(b.total_player_records, 0) as total_player_records,
  COALESCE(b.unique_players, 0) as unique_players,
  COALESCE(b.avg_players_per_game, 0) as avg_players_per_game,
  COALESCE(b.avg_starters_per_game, 0) as avg_starters_per_game,
  COALESCE(b.min_players_per_game, 0) as min_players_per_game,
  
  -- Primary status
  CASE
    WHEN COALESCE(s.scheduled_games, 0) = 0 THEN '⚪ No games'
    WHEN COALESCE(b.games_with_data, 0) = COALESCE(s.scheduled_games, 0)
     AND COALESCE(b.min_players_per_game, 0) >= 20
     AND COALESCE(b.avg_starters_per_game, 0) BETWEEN 9.5 AND 10.5
    THEN '✅ Complete'
    WHEN COALESCE(b.games_with_data, 0) = 0 THEN '❌ Missing all'
    WHEN COALESCE(b.min_players_per_game, 0) < 20 THEN '⚠️ Low player count'
    WHEN COALESCE(b.avg_starters_per_game, 0) < 9 OR COALESCE(b.avg_starters_per_game, 0) > 11 
      THEN '⚠️ Unusual starter count'
    ELSE '⚠️ Incomplete'
  END as status,
  
  -- BDL consistency check
  CASE
    WHEN COALESCE(b.games_with_data, 0) = COALESCE(bdl.bdl_games, 0) 
      AND COALESCE(b.games_with_data, 0) > 0
      THEN '✅ Matches BDL'
    WHEN COALESCE(bdl.bdl_games, 0) = 0 AND COALESCE(b.games_with_data, 0) = 0
      THEN '⚪ No data in either source'
    WHEN ABS(COALESCE(b.games_with_data, 0) - COALESCE(bdl.bdl_games, 0)) <= 1
      THEN '⚠️ Minor discrepancy'
    WHEN COALESCE(bdl.bdl_games, 0) > 0 AND COALESCE(b.games_with_data, 0) = 0
      THEN '❌ BDL has data, NBA.com missing'
    WHEN COALESCE(b.games_with_data, 0) > 0 AND COALESCE(bdl.bdl_games, 0) = 0
      THEN '🟡 NBA.com has data, BDL missing'
    ELSE '❌ Major discrepancy'
  END as bdl_consistency,
  
  -- Detailed notes
  CASE
    WHEN COALESCE(s.scheduled_games, 0) = 0 THEN 'Off day - no games scheduled'
    WHEN COALESCE(b.games_with_data, 0) = 0 AND COALESCE(s.scheduled_games, 0) > 0
      THEN CONCAT('❌ CRITICAL: ', CAST(COALESCE(s.scheduled_games, 0) AS STRING), ' games missing - check scraper')
    WHEN COALESCE(b.games_with_data, 0) < COALESCE(s.scheduled_games, 0)
      THEN CONCAT('⚠️ Missing ', 
           CAST(COALESCE(s.scheduled_games, 0) - COALESCE(b.games_with_data, 0) AS STRING), 
           ' games - run find_missing_games.sql')
    WHEN COALESCE(b.unique_nba_ids, 0) < COALESCE(b.unique_players, 0)
      THEN CONCAT('⚠️ ', 
           CAST(COALESCE(b.unique_players, 0) - COALESCE(b.unique_nba_ids, 0) AS STRING), 
           ' players missing NBA player IDs')
    WHEN ABS(COALESCE(b.games_with_data, 0) - COALESCE(bdl.bdl_games, 0)) > 1
      THEN 'Cross-validate with BDL - significant discrepancy'
    ELSE '✅ All checks passed'
  END as notes

FROM date_range d
LEFT JOIN daily_schedule s ON d.date = s.game_date
LEFT JOIN daily_boxscores b ON d.date = b.game_date
LEFT JOIN bdl_daily_stats bdl ON d.date = bdl.game_date

ORDER BY d.date DESC;

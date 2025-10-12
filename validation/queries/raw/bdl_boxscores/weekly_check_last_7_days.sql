-- ============================================================================
-- File: validation/queries/raw/bdl_boxscores/weekly_check_last_7_days.sql
-- Purpose: Weekly health check showing daily coverage trends
-- Usage: Run weekly to spot patterns and ensure consistent data capture
-- ============================================================================
-- Instructions:
--   1. Run once per week (e.g., Monday mornings)
--   2. Review for patterns (specific days with issues)
--   3. No date parameters needed - automatically checks last 7 days
-- ============================================================================
-- Expected Results:
--   - Each day should show "✅ Complete" or "⚪ No games"
--   - Multiple "⚠️ Incomplete" or "❌ Missing all" = scraper issue
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

daily_boxscores AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as games_with_data,
    COUNT(*) as total_player_records,
    ROUND(AVG(players_per_game), 1) as avg_players_per_game,
    MIN(players_per_game) as min_players_per_game
  FROM (
    SELECT
      game_date,
      game_id,
      COUNT(DISTINCT player_lookup) as players_per_game
    FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
    WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    GROUP BY game_date, game_id
  )
  GROUP BY game_date
)

SELECT
  d.date as game_date,
  FORMAT_DATE('%A', d.date) as day_of_week,
  COALESCE(s.scheduled_games, 0) as scheduled_games,
  COALESCE(b.games_with_data, 0) as games_with_data,
  COALESCE(b.total_player_records, 0) as total_player_records,
  COALESCE(b.avg_players_per_game, 0) as avg_players_per_game,
  COALESCE(b.min_players_per_game, 0) as min_players_per_game,
  CASE
    WHEN COALESCE(s.scheduled_games, 0) = 0 THEN '⚪ No games'
    WHEN COALESCE(b.games_with_data, 0) = COALESCE(s.scheduled_games, 0) 
     AND COALESCE(b.min_players_per_game, 0) >= 20 
    THEN '✅ Complete'
    WHEN COALESCE(b.games_with_data, 0) = 0 THEN '❌ Missing all'
    WHEN COALESCE(b.min_players_per_game, 0) < 20 THEN '⚠️ Low player count'
    ELSE '⚠️ Incomplete'
  END as status
FROM date_range d
LEFT JOIN daily_schedule s ON d.date = s.game_date
LEFT JOIN daily_boxscores b ON d.date = b.game_date
ORDER BY d.date DESC;

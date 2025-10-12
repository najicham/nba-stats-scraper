-- ============================================================================
-- File: validation/queries/raw/odds_api_props/weekly_check_last_7_days.sql
-- Purpose: Weekly health check showing daily player props coverage trends
-- Usage: Run weekly to spot patterns and ensure consistent data capture
-- ============================================================================
-- Instructions:
--   1. Run once per week (e.g., Monday mornings)
--   2. Review for patterns (specific days with issues)
--   3. No date parameters needed - automatically checks last 7 days
-- ============================================================================
-- Expected Results:
--   - Each day should show "✅ Complete" or "⚪ No games"
--   - Multiple "⚠️ Low Coverage" or "❌ Missing all" = scraper issue
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

daily_props AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as games_with_props,
    COUNT(DISTINCT player_lookup) as total_players,
    ROUND(AVG(players_per_game), 1) as avg_players_per_game,
    COUNT(DISTINCT CASE WHEN bookmaker = 'DraftKings' THEN game_id END) as games_with_dk,
    COUNT(DISTINCT CASE WHEN bookmaker = 'FanDuel' THEN game_id END) as games_with_fd
  FROM (
    SELECT
      game_date,
      game_id,
      bookmaker,
      player_lookup,
      COUNT(DISTINCT player_lookup) OVER (PARTITION BY game_id) as players_per_game
    FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
    WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  )
  GROUP BY game_date
)

SELECT
  d.date as game_date,
  FORMAT_DATE('%A', d.date) as day_of_week,
  COALESCE(s.scheduled_games, 0) as scheduled_games,
  COALESCE(p.games_with_props, 0) as games_with_props,
  COALESCE(p.total_players, 0) as total_players,
  COALESCE(p.avg_players_per_game, 0) as avg_players_per_game,
  CONCAT(
    COALESCE(p.games_with_dk, 0), ' DK / ',
    COALESCE(p.games_with_fd, 0), ' FD'
  ) as bookmaker_coverage,
  CASE
    WHEN COALESCE(s.scheduled_games, 0) = 0 THEN '⚪ No games'
    WHEN COALESCE(p.games_with_props, 0) = 0 THEN '❌ Missing all'
    WHEN COALESCE(p.games_with_props, 0) < COALESCE(s.scheduled_games, 0) THEN 
      CONCAT('🔴 Incomplete (', 
        CAST(COALESCE(s.scheduled_games, 0) - COALESCE(p.games_with_props, 0) AS STRING), 
        ' missing)')
    WHEN COALESCE(p.avg_players_per_game, 0) < 6.0 THEN 
      CONCAT('🟡 Low coverage (', CAST(COALESCE(p.avg_players_per_game, 0) AS STRING), ' avg)')
    ELSE '✅ Complete'
  END as status
FROM date_range d
LEFT JOIN daily_schedule s ON d.date = s.game_date
LEFT JOIN daily_props p ON d.date = p.game_date
ORDER BY d.date DESC;

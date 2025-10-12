-- ============================================================================
-- File: validation/queries/raw/nbac_gamebook/weekly_check_last_7_days.sql
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
--   - Multiple "⚠️ Incomplete" or "❌ Missing all" = scraper/processor issue
--   - Resolution rate should stay ≥98% across all days
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

daily_gamebook AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as gamebook_games,
    COUNT(*) as total_players,
    ROUND(COUNT(*) / COUNT(DISTINCT game_id), 1) as avg_players_per_game,
    -- Name resolution tracking
    COUNT(CASE WHEN player_status = 'inactive' THEN 1 END) as inactive_players,
    COUNT(CASE WHEN player_status = 'inactive' AND name_resolution_status = 'resolved' THEN 1 END) as inactive_resolved,
    ROUND(SAFE_DIVIDE(
      COUNT(CASE WHEN player_status = 'inactive' AND name_resolution_status = 'resolved' THEN 1 END),
      COUNT(CASE WHEN player_status = 'inactive' THEN 1 END)
    ) * 100, 1) as resolution_rate_pct
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  GROUP BY game_date
)

SELECT
  d.date as game_date,
  FORMAT_DATE('%A', d.date) as day_of_week,
  COALESCE(s.scheduled_games, 0) as scheduled_games,
  COALESCE(g.gamebook_games, 0) as gamebook_games,
  COALESCE(g.total_players, 0) as total_players,
  COALESCE(g.avg_players_per_game, 0) as avg_players_per_game,
  COALESCE(g.inactive_players, 0) as inactive_players,
  COALESCE(g.inactive_resolved, 0) as inactive_resolved,
  CONCAT(CAST(COALESCE(g.resolution_rate_pct, 0) AS STRING), '%') as resolution_rate,
  CASE
    WHEN COALESCE(s.scheduled_games, 0) = 0 THEN '⚪ No games'
    WHEN COALESCE(g.gamebook_games, 0) = 0 THEN '❌ Missing all'
    WHEN COALESCE(g.gamebook_games, 0) < COALESCE(s.scheduled_games, 0) THEN '⚠️ Incomplete'
    WHEN COALESCE(g.avg_players_per_game, 0) < 28 THEN '⚠️ Low player count'
    WHEN COALESCE(g.resolution_rate_pct, 0) < 98.0 THEN '⚠️ Low resolution'
    ELSE '✅ Complete'
  END as status
FROM date_range d
LEFT JOIN daily_schedule s ON d.date = s.game_date
LEFT JOIN daily_gamebook g ON d.date = g.game_date
ORDER BY d.date DESC;

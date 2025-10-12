-- ============================================================================
-- File: validation/queries/raw/odds_game_lines/weekly_check_last_7_days.sql
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

daily_odds AS (
  SELECT 
    game_date,
    COUNT(DISTINCT game_id) as odds_games
  FROM `nba-props-platform.nba_raw.odds_api_game_lines`
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  GROUP BY game_date
)

SELECT 
  d.date as game_date,
  FORMAT_DATE('%A', d.date) as day_of_week,
  COALESCE(s.scheduled_games, 0) as scheduled_games,
  COALESCE(o.odds_games, 0) as odds_games,
  CASE 
    WHEN COALESCE(s.scheduled_games, 0) = 0 THEN '⚪ No games'
    WHEN COALESCE(o.odds_games, 0) = COALESCE(s.scheduled_games, 0) THEN '✅ Complete'
    WHEN COALESCE(o.odds_games, 0) = 0 THEN '❌ Missing all'
    ELSE '⚠️ Incomplete'
  END as status
FROM date_range d
LEFT JOIN daily_schedule s ON d.date = s.game_date
LEFT JOIN daily_odds o ON d.date = o.game_date
ORDER BY d.date DESC;
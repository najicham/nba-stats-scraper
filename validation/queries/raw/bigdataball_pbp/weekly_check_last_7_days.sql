-- ============================================================================
-- FILE: validation/queries/raw/bigdataball_pbp/weekly_check_last_7_days.sql
-- ============================================================================
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

daily_pbp AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as games_with_data,
    COUNT(*) as total_events,
    ROUND(AVG(events_per_game), 1) as avg_events_per_game,
    MIN(events_per_game) as min_events_per_game,
    ROUND(AVG(shots_with_coords * 100.0 / NULLIF(shots_per_game, 0)), 1) as pct_coords
  FROM (
    SELECT
      game_date,
      game_id,
      COUNT(*) as events_per_game,
      COUNT(CASE WHEN event_type = 'shot' THEN 1 END) as shots_per_game,
      COUNT(CASE WHEN original_x IS NOT NULL THEN 1 END) as shots_with_coords
    FROM `nba-props-platform.nba_raw.bigdataball_play_by_play`
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
  COALESCE(b.total_events, 0) as total_events,
  COALESCE(b.avg_events_per_game, 0) as avg_events_per_game,
  COALESCE(b.min_events_per_game, 0) as min_events_per_game,
  COALESCE(b.pct_coords, 0) as pct_shots_with_coords,
  CASE
    WHEN COALESCE(s.scheduled_games, 0) = 0 THEN '⚪ No games'
    WHEN COALESCE(b.games_with_data, 0) = COALESCE(s.scheduled_games, 0) 
     AND COALESCE(b.min_events_per_game, 0) >= 400
     AND COALESCE(b.pct_coords, 0) >= 70
    THEN '✅ Complete'
    WHEN COALESCE(b.games_with_data, 0) = 0 THEN '❌ Missing all'
    WHEN COALESCE(b.min_events_per_game, 0) < 300 THEN '❌ Critical: Very low events'
    WHEN COALESCE(b.min_events_per_game, 0) < 400 THEN '⚠️ Low event count'
    WHEN COALESCE(b.pct_coords, 0) < 70 THEN '⚠️ Poor coordinate coverage'
    ELSE '⚠️ Incomplete'
  END as status
FROM date_range d
LEFT JOIN daily_schedule s ON d.date = s.game_date
LEFT JOIN daily_pbp b ON d.date = b.game_date
ORDER BY d.date DESC;

-- Status Guide:
-- ✅ Complete: All games, 400+ events, 70%+ coordinates
-- ⚠️ Warnings: Low events (300-399) OR poor coords (<70%)
-- ❌ Critical: <300 events OR missing all games
-- ⚪ No games: Off day (normal)

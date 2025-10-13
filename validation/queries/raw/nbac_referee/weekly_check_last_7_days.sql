-- ============================================================================
-- File: validation/queries/raw/nbac_referee/weekly_check_last_7_days.sql
-- Purpose: Monitor referee assignment collection over the past week
-- Usage: Run weekly or when investigating recent data issues
-- ============================================================================
-- Expected Results:
--   - Each game day should show expected vs actual game counts
--   - Official counts should be consistent (3 or 4 per game)
--   - No missing dates or incomplete assignments
-- ============================================================================

WITH last_7_days AS (
  SELECT
    game_date,
    FORMAT_DATE('%A', game_date) as day_of_week,
    COUNT(DISTINCT game_id) as games_with_refs,
    COUNT(DISTINCT official_code) as unique_officials,
    COUNT(*) as total_assignments,
    ROUND(COUNT(*) / COUNT(DISTINCT game_id), 1) as avg_officials_per_game,
    MIN(created_at) as first_processed,
    MAX(created_at) as last_processed
  FROM `nba-props-platform.nba_raw.nbac_referee_game_assignments`
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND CURRENT_DATE()
  GROUP BY game_date
),

scheduled_games AS (
  SELECT
    game_date,
    COUNT(*) as scheduled_count
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND CURRENT_DATE()
  GROUP BY game_date
)

SELECT
  COALESCE(r.game_date, s.game_date) as game_date,
  r.day_of_week,
  s.scheduled_count,
  r.games_with_refs,
  r.unique_officials,
  r.total_assignments,
  r.avg_officials_per_game,
  CASE
    WHEN s.scheduled_count IS NULL THEN '⚪ Future date'
    WHEN s.scheduled_count = 0 THEN '⚪ No games scheduled'
    WHEN r.games_with_refs = s.scheduled_count 
     AND r.avg_officials_per_game IN (3.0, 4.0) THEN '✅ Complete'
    WHEN r.games_with_refs IS NULL THEN '❌ No referee data'
    WHEN r.avg_officials_per_game NOT IN (3.0, 4.0) THEN '⚠️ Wrong official count'
    ELSE CONCAT('⚠️ Missing ', CAST(s.scheduled_count - r.games_with_refs AS STRING), ' games')
  END as status,
  r.first_processed,
  r.last_processed
FROM last_7_days r
FULL OUTER JOIN scheduled_games s
  ON r.game_date = s.game_date
ORDER BY COALESCE(r.game_date, s.game_date) DESC;

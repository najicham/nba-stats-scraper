-- Data Coverage % Including Source Blocks
--
-- Calculates actual data coverage accounting for source-blocked resources.
-- Shows: total games, blocked games, expected available, actual collected, coverage %.
-- Useful for: Accurate success rate reporting (100% of available vs total).

WITH expected AS (
  SELECT game_date, COUNT(*) as total_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY game_date
),
blocked AS (
  SELECT game_date, COUNT(*) as blocked_count
  FROM `nba-props-platform.nba_orchestration.source_blocked_resources`
  WHERE resource_type = 'play_by_play'
    AND is_resolved = FALSE
    AND game_date >= CURRENT_DATE() - 7
  GROUP BY game_date
),
actual AS (
  SELECT game_date, COUNT(DISTINCT game_id) as actual_count
  FROM `nba-props-platform.nba_raw.bigdataball_play_by_play`
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY game_date
)
SELECT
  e.game_date,
  e.total_games,
  COALESCE(b.blocked_count, 0) as blocked_games,
  e.total_games - COALESCE(b.blocked_count, 0) as expected_available,
  COALESCE(a.actual_count, 0) as actual_collected,
  CASE
    WHEN e.total_games - COALESCE(b.blocked_count, 0) = 0 THEN 100.0
    ELSE ROUND(100.0 * COALESCE(a.actual_count, 0) /
               (e.total_games - COALESCE(b.blocked_count, 0)), 1)
  END as coverage_pct,
  CASE
    WHEN COALESCE(a.actual_count, 0) >= (e.total_games - COALESCE(b.blocked_count, 0))
    THEN '✅ Complete'
    ELSE '⚠️ Missing'
  END as status
FROM expected e
LEFT JOIN blocked b ON e.game_date = b.game_date
LEFT JOIN actual a ON e.game_date = a.game_date
ORDER BY e.game_date DESC;
